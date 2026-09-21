import json
import unittest
from dataclasses import replace
from decimal import Decimal, localcontext, ROUND_UP
from fractions import Fraction

from app.edge_contracts import dumps, loads
from app.pricing.baseline import Policy, calculate, devig, restore, recompute, Estimate
from app.pricing.fixtures import target, receipt, records, example
from app.reference.fixtures import source, assessment, before, payload, terms
from app.reference.enrichment import enrich
from app.reference.records import as_of, export_records, packed, QuoteRevision
from app.settlement import profile
from app.normalization.registry import Registry


def price(rows=None, cutoff=None, **kw):
    cutoff = cutoff or before(55)
    return calculate(as_of(rows or records(), cutoff), target=kw.pop('target', target()),
                     cutoff=cutoff, estimated_at=kw.pop('estimated_at', cutoff), **kw)


def changed(fn):
    data = json.loads(payload(), parse_float=str)
    fn(data['bookmakers'][0]['markets'][0])
    return json.dumps(data).encode()


class PricingTests(unittest.TestCase):
    def assertUnavailable(self, estimate, reason):
        d = estimate.data
        self.assertEqual(d['status'], 'unavailable')
        self.assertIsNone(d['conditional_target_probability'])
        self.assertTrue(reason in d['reasons'] or any(reason in c['reasons'] for c in d['candidates']), reason)

    def test_independent_rational_values(self):
        # Independently: qA=(1/a)/((1/a)+(1/b))=b/(a+b)=21/40.
        result = devig((Decimal('1.90'), Decimal('2.1000')))
        self.assertEqual(Fraction(Decimal(result['probabilities'][0])), Fraction(21, 40))
        self.assertEqual(Fraction(Decimal(result['probabilities'][1])), Fraction(19, 40))
        self.assertEqual(result['decimal_odds'], ['1.90', '2.1000'])
        self.assertEqual(result['probabilities'], ['0.525000000000000000', '0.475000000000000000'])

    def test_exact_e2_scale_and_conditional_units(self):
        d = price().data
        self.assertEqual(d['calculation']['decimal_odds'], ['1.90000000000000000001', '2.1000'])
        self.assertEqual(d['status'], 'degraded')
        self.assertEqual(d['probability_unit'], 'fraction')
        self.assertIsNone(d['unconditional_target_probability'])
        self.assertIsNone(d['target_fair_value_usd'])
        self.assertIsNone(d['net_expected_profit'])
        self.assertTrue(all(x is None for x in d['exceptional_probabilities'].values()))
        self.assertEqual(d['target_scenario_payouts']['canceled']['kind'], 'fraction')
        self.assertEqual(d['target_scenario_payouts']['canceled']['value'], '0.5')

    def test_decimal_context_and_bounds(self):
        for odds in [('1.000001', '1000000'), ('3', '3'), ('1.9', '2.3'), ('2', '2')]:
            a = devig(tuple(map(Decimal, odds)))
            with localcontext() as ctx:
                ctx.prec = 6; ctx.rounding = ROUND_UP
                self.assertEqual(a, devig(tuple(map(Decimal, odds))))
            ps = list(map(Decimal, a['probabilities']))
            self.assertEqual(sum(ps), 1)
            self.assertTrue(all(0 <= p <= 1 for p in ps))
        for odds in [(Decimal('NaN'), Decimal(2)), (Decimal(1), Decimal(2)), (1.9, 2.1)]:
            with self.assertRaises(ValueError): devig(odds)

    def test_missing_invalid_and_unknown(self):
        cases = [
            (records(receipt(changed(lambda m: m['outcomes'].pop()))), 'missing_paired_outcome'),
            (records(receipt(payload().replace(b'2.1000', b'0.90'))), 'invalid_decimal_price'),
            (records(receipt(b'not json')), 'rejected_or_incomplete_snapshot'),
            (records(assessed=assessment(pairing=False)), 'unknown_pairing'),
            (records(assessed=assessment(rules=False)), 'unknown_rules'),
            (records(src=source(assessed=False)), 'unknown_source_lineage'),
            (records(receipt(changed(lambda m: m.pop('last_update')))), 'unknown_provider_read_time'),
        ]
        for rows, reason in cases:
            with self.subTest(reason=reason): self.assertUnavailable(price(rows), reason)

    def test_freshness_boundaries(self):
        self.assertEqual(price(cutoff=before(30)).data['status'], 'degraded')
        self.assertUnavailable(price(cutoff=before(29)), 'stale_receipt')
        self.assertUnavailable(price(policy=Policy(max_provider_read_age_seconds=9)), 'stale_provider_read')
        self.assertEqual(price(policy=Policy(max_provider_read_age_seconds=10)).data['status'], 'degraded')
        r = receipt(changed(lambda m: m.update(last_update=before(59))))
        self.assertUnavailable(price(records(r)), 'provider_read_after_receipt_or_cutoff')
        # Retained nanoseconds, not datetime's truncated microseconds, decide eligibility.
        exact = before(65).replace('+00:00', '.000000001+00:00')
        r = receipt(changed(lambda m: m.update(last_update=exact)))
        self.assertEqual(price(records(r), policy=Policy(max_provider_read_age_seconds=10)).data['status'], 'degraded')

    def test_latest_invalid_never_falls_back(self):
        history, estimates = example()
        self.assertEqual(estimates[0].data['status'], 'degraded')
        self.assertUnavailable(estimates[1], 'no_eligible_pair')
        older = next(c for c in estimates[1].data['candidates'] if c['receipt_id'] == 'e3-r1')
        self.assertIn('superseded_snapshot', older['reasons'])
        # Even receipt without any available enrichment blocks older complete pair.
        self.assertUnavailable(price(history[:-1], cutoff=before(45)), 'no_enrichment_known_at_cutoff')

    def test_target_copy_and_duplicate_deliveries(self):
        for field in ('origin', 'family', 'copied_from'):
            src = replace(source(), **{field: ('kalshi',) if field == 'copied_from' else 'kalshi'})
            self.assertUnavailable(price(records(src=src)), 'target_venue_or_known_copy')
        first = records()
        second = receipt(identity='another-path', at=before(58), session='synthetic-other-delivery')
        rows = (*first, second, enrich(second, first[0], assessment(), revision_id='another-revision'))
        d = price(rows).data
        self.assertEqual(sum(c['included'] for c in d['candidates']), 1)
        self.assertIn('duplicate_source_family', next(c for c in d['candidates'] if c['receipt_id'] == 'e3-r1')['reasons'])
        self.assertIn('one_information_family', d['reasons'])

    def test_late_download_cannot_backdate(self):
        history = json.dumps({'timestamp': before(3600), 'data': json.loads(payload(), parse_float=str)}).encode()
        rows = records(receipt(history, at=before(30)))
        self.assertUnavailable(price(rows), 'no_eligible_pair')
        self.assertEqual(price(rows, cutoff=before(25)).data['status'], 'degraded')
        with self.assertRaises(ValueError):
            calculate(export_records(rows), target=target(), cutoff=before(55), estimated_at=before(55))

    def test_later_source_and_rule_assessments(self):
        initial = records(src=source(assessed=False), assessed=assessment(pairing=False, rules=False))
        saved = price(initial)
        later = source(known_at=before(40), identity='later-source')
        rev = enrich(initial[1], later, assessment(known_at=before(40)), revision_id='later-rules')
        history = (*initial, later, rev)
        self.assertEqual(price(history), saved)
        self.assertEqual(price(history, cutoff=before(35)).data['status'], 'degraded')
        self.assertEqual(recompute(saved), saved)

    def test_later_alias_registry(self):
        r = receipt(payload().replace(b'Atlanta Falcons', b'Invented ATL Alias'))
        initial = records(r)
        saved = price(initial)
        self.assertUnavailable(saved, 'ambiguous_or_missing_participants')
        data = json.loads(Registry.load().to_json())
        data['version'] = 'synthetic-e3-later-registry'
        data['aliases'].append({'kind': 'team', 'league': 'NFL', 'text': 'Invented ATL Alias',
                               'targets': ['NFL:ATL'], 'source': 'synthetic:invented alias'})
        revision = enrich(r, initial[0], assessment(known_at=before(40)), registry=Registry(data), revision_id='later-alias')
        history = (*initial, revision)
        self.assertEqual(price(history), saved)
        self.assertEqual(price(history, cutoff=before(35)).data['status'], 'degraded')

    def test_effective_and_knowledge_boundaries(self):
        self.assertUnavailable(price(records(assessed=replace(assessment(), effective_at=before(59)))), 'assessment_not_effective')
        self.assertEqual(price(records(assessed=replace(assessment(), effective_at=before(60)))).data['status'], 'degraded')
        self.assertUnavailable(price(records(assessed=assessment(known_at=before(54)))), 'no_enrichment_known_at_cutoff')
        self.assertEqual(price(records(assessed=assessment(known_at=before(55)))).data['status'], 'degraded')
        for field in ('known_at', 'effective_at'):
            with self.assertRaises(ValueError): price(target=target(**{field: before(54)}))
        with self.assertRaises(ValueError): price(estimated_at=before(56))

    def test_pregame_and_target_rules(self):
        self.assertUnavailable(price(cutoff=before(1)), 'pregame_cutoff_reached')
        self.assertUnavailable(price(cutoff=before(0)), 'pregame_cutoff_reached')
        self.assertUnavailable(price(target=target(terms_json=dumps(replace(terms(), rules_profile_json=None)))), 'unknown_or_unsupported_target_terms')
        p = json.loads(terms().rules_profile_json)
        for dimension in ('tie', 'overtime'):
            altered = json.loads(terms().rules_profile_json)
            altered['dimensions'][dimension]['value'] = 'synthetic incompatible condition'
            p2 = profile(sources=p['sources'], dimensions=altered['dimensions'], payouts=p['payouts'], effective_date=p['effective_date'], actor=p['actor'])
            self.assertUnavailable(price(target=target(terms_json=dumps(replace(terms(), rules_profile_json=json.dumps(p2))))), 'incompatible_or_unknown_target_rules')
        self.assertEqual(price(target=target(predicate='not_win')).data['conditional_target_probability'], '0.475000000000000000')
        self.assertEqual(price(target=target(venue='polymarket_us')).data['status'], 'degraded')

    def test_void_refund_and_exceptional_rules(self):
        original = json.loads(terms().rules_profile_json)
        for kind in ('refund', 'unknown', 'discretionary'):
            payouts = dict(original['payouts'])
            payouts['canceled'] = {'kind': kind, 'evidence': original['sources'][0]['sha256']}
            revised = profile(sources=original['sources'], dimensions=original['dimensions'], payouts=payouts,
                              effective_date=original['effective_date'], actor=original['actor'])
            new_terms = replace(terms(), rules_profile_json=json.dumps(revised))
            own_target = target(terms_json=dumps(new_terms))
            self.assertUnavailable(price(target=own_target), 'incompatible_or_unknown_target_rules')
            # Matched refund terms still do not supply the probability of a void.
            rows = records(assessed=replace(assessment(), target=new_terms, rules_json=json.dumps(revised)))
            result = price(rows, target=own_target)
            if kind == 'refund':
                self.assertEqual(result.data['status'], 'degraded')
                self.assertEqual(result.data['target_scenario_payouts']['canceled']['kind'], 'refund')
                self.assertIsNone(result.data['exceptional_probabilities']['canceled'])
            else:
                self.assertUnavailable(result, 'incompatible_or_unknown_target_rules')

    def test_full_recomputation_ignores_ambient_decimal_context(self):
        saved = price()
        with localcontext() as ctx:
            ctx.prec = 6; ctx.rounding = ROUND_UP
            self.assertEqual(recompute(saved), saved)

    def test_restore_exclusions_and_tamper(self):
        for e in example()[1]:
            self.assertEqual(restore(e.export()).export(), e.export())
            d = e.data; d['candidates'] = []
            with self.assertRaises(ValueError): recompute(Estimate(packed(d)))
        with self.assertRaises(ValueError): restore(price().export().replace('proportional-devig-1', 'proportional-devig-2'))
        with self.assertRaises(ValueError): Policy(precision=28)
        with self.assertRaises(ValueError): Policy(max_receipt_age_seconds=0)

    def test_order_and_exact_cutoff(self):
        rows = records()
        self.assertEqual(price(rows), price(tuple(reversed(rows))))
        self.assertEqual(price(rows, cutoff=before(60)).data['status'], 'degraded')
        self.assertUnavailable(price(rows, cutoff=before(61)), 'no_eligible_pair')
        t = before(60).replace('+00:00', '.000000001+00:00')
        # Receipt can retain exact strings when no quote projection is possible.
        newer = receipt(b'bad', identity='nanosecond-receipt', at=t)
        self.assertEqual(price((*rows, newer), cutoff=before(60)).data['status'], 'degraded')
        self.assertUnavailable(price((*rows, newer), cutoff=t), 'no_enrichment_known_at_cutoff')


if __name__ == '__main__': unittest.main()
