"""SC01 offline matrices. All refreshed prices/grids here are authored fixtures."""
import tempfile
# Disposable root exists before importing storage/collection owners.
TEST_ROOT = tempfile.TemporaryDirectory(prefix='predict-sc01-test-')
from copy import deepcopy
from datetime import timedelta
from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app.comparison.current_dependencies import digest, instant, profile, references
from app.comparison.combined_inputs import build
from app.comparison.readiness_inputs import instrument, model_checks
from app.comparison.scanner_readiness import Selection, assemble, check, clock_reasons
from app.storage.scanner_readiness import scope_inventory
from app.collection.current_policy import DEFAULT, GRANT
from app.dashboard.current_contract import quotes_of
from tests.test_ev09_n01 import envelopes, AT, SELECTED


def authored():
    b = build(envelopes(), at=AT, selected=SELECTED)[0]
    s = b['state_inputs'];e = s['events'][0]
    g, q = next((g, q) for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o) if q['source']['native_side'] == 'Long')
    p = s['comparison_profiles']
    from app.comparison.shared_templates import keys, resolve
    p = {key: resolve(p,key) for key in keys(p)}
    q, p, e, g = deepcopy((q, p, e, g))
    # Explicit fixture-only legal-grid/stage assumptions; never bound to live data.
    e['stage'] = 'regular_season'
    quantity = deepcopy(references(q, p)['quantity']['payload'])
    quantity.update(actual_grid_qualified=True, grid_qualification='authored_legal_test_grid')
    key, v = profile('quantity', quantity);p[key] = v
    q['comparison_input_refs']['refs']['quantity'] = key
    q['times'].update(source_at=AT, received_at=AT, projected_at=AT)
    q['provider_clocks']={k:AT for k in ('book','market')}
    q['depth'] = [dict(price=q['original']['value'], quantity='100')]
    book = dict(source_at=AT, received_at=AT, sync='synchronized', state='active', quantity_unit='contracts')
    return q, p, e, g, book


def row(q=None, p=None, e=None, g=None, book=None, *, at=AT, status=None):
    if q is None:q, p, e, g, book = authored()
    return instrument(q, p, e, g, at=at, source_status=status or dict(state='available'), authorized=True, book=book)


def projection(rows, *, selection=None, evaluations=(), at=AT, scopes=None):
    selection = selection or Selection(venues=('polymarket_us', 'kalshi'))
    scopes = scopes or scope_inventory(selection, DEFAULT, GRANT)
    return assemble(rows, selection=selection, at=at, epoch='authored-epoch', input_revision='authored-inputs', scopes=scopes, evaluations=evaluations)


def pair_rows():
    a = row();b = deepcopy(a)
    # Pure contract projection vectors; not native/model evidence for Kalshi.
    b.update(id='authored-second-leg', venue='kalshi', direction='home')
    b['predicate']['predicate']='not_win'
    b['native_contract_id']='native-contract:'+digest('authored-second-contract')
    b['terms_sha256']=digest('authored-second-terms')
    b['model_versions']={'execution_template':digest('authored-second-model')}
    b['native_key'] = ['kalshi', 'authored-event', 'authored-market', 'no', 'no']
    b['scope_key'] = digest(dict(venue='kalshi', sport='football', league='NFL', market='winner', period='full_game'))
    return [a, b]


class Readiness(TestCase):
    def test_healthy_model_and_native_meaning(self):
        r = row()
        self.assertEqual(r['checks']['contract'], check([]))
        self.assertEqual(r['checks']['execution'], check([]))
        self.assertEqual(r['native_key'][-1], 'Long')
        self.assertEqual(r['predicate']['predicate'], 'win')

    def test_disconnected_retained_and_connected_stale(self):
        self.assertIn('source_disconnected', row(status=dict(state='disconnected'))['checks']['execution']['reason_codes'])
        later = (instant(AT)+timedelta(seconds=30)).isoformat()
        stale = row(at=later)
        self.assertEqual(stale['checks']['execution']['state'], 'stale_only')
        self.assertIn('source_price_expired', stale['checks']['execution']['reason_codes'])
        self.assertEqual(stale['clocks']['source_at'], AT)

    def test_reference_purpose_never_blocks_cashflow_inputs(self):
        q, p, e, g, b = authored()
        q['comparison_input_refs']['refs']['reference'] = None
        r = row(q, p, e, g, b)
        self.assertEqual(r['checks']['contract']['state'], 'ready')
        self.assertEqual(r['checks']['execution']['state'], 'ready')
        self.assertIn('reference_missing', r['checks']['ev']['reason_codes'])
        q, p, e, g, b = authored()
        now = (instant(AT)+timedelta(hours=1)).isoformat()
        q['times'].update(source_at=now, received_at=now, projected_at=now)
        q['provider_clocks']={k:now for k in ('book','market')}
        b.update(source_at=now, received_at=now)
        r = row(q, p, e, g, b, at=now)
        self.assertEqual(r['checks']['execution']['state'], 'ready')
        self.assertEqual(r['checks']['contract']['state'], 'ready')
        self.assertIn('reference_expired', r['checks']['ev']['reason_codes'])

    def expire(self, kind, start=False):
        q, p, e, g, b = authored()
        old = references(q, p)[kind]
        payload = deepcopy(old['payload'])
        if start:payload['effective_from'] = (instant(AT)+timedelta(seconds=1)).isoformat()
        key, value = profile(kind, payload, expires_at=None if start else AT)
        p[key] = value;q['comparison_input_refs']['refs'][kind] = key
        if kind in ('fee','payout'):
            recipe = q['comparison_input_status'][kind]['estimate_content']
            recipe['original_profile_ref'] = key;recipe['id'] = digest({k:v for k,v in recipe.items() if k != 'id'})
        return row(q, p, e, g, b)

    def test_probability_expiry_is_separate_from_required_facts(self):
        r = self.expire('probability')
        self.assertIn('probability_expired', r['checks']['ev']['reason_codes'])
        self.assertEqual(r['checks']['contract']['state'], 'ready')
        for kind in ('identity','fee','payout','quantity'):
            with self.subTest(kind=kind):
                self.assertIn(kind+'_expired', self.expire(kind)['checks']['contract']['reason_codes'])
                self.assertIn(kind+'_not_effective', self.expire(kind, start=True)['checks']['contract']['reason_codes'])

    def test_unknown_future_and_conflicting_clocks(self):
        for source, receipt, code in [(None, AT, 'source_clock_unknown'), ('2027-01-01T00:00:00Z', AT, 'source_clock_conflict'), (AT, '2026-10-01T00:00:00Z', 'source_clock_conflict')]:
            self.assertEqual(clock_reasons(source, receipt, instant(AT), 30), [code])
        q,p,e,g,b = authored();q['times']['projected_at'] = '2027-01-01T00:00:00Z'
        self.assertIn('projection_clock_conflict', row(q,p,e,g,b)['checks']['execution']['reason_codes'])

    def test_book_sync_depth_clock_and_exact_price(self):
        q,p,e,g,b = authored()
        for change, code in [({'sync':'unsynchronized'},'book_unsynchronized'), ({'source_at':None}, 'book_clock_unknown'), ({'quantity_unit':'USD'}, 'book_units_conflict')]:
            self.assertIn(code, row(q,p,e,g,dict(b,**change))['checks']['execution']['reason_codes'])
        q['depth'] = []
        self.assertIn('observed_depth_missing', row(q,p,e,g,b)['checks']['execution']['reason_codes'])
        q['depth'] = [dict(price=q['original']['value'], quantity='0.001')]
        self.assertIn('observed_depth_insufficient', row(q,p,e,g,b)['checks']['execution']['reason_codes'])
        q['depth'] = [dict(price='0.999', quantity='100')]
        self.assertIn('book_offer_price_conflict', row(q,p,e,g,b)['checks']['execution']['reason_codes'])

    def test_native_side_collateral_and_contract_conflict(self):
        b = build(envelopes(), at=AT, selected=SELECTED)[0];s = b['state_inputs'];e = s['events'][0]
        g, short = next((g, q) for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o) if q['source']['native_side'] == 'Short')
        r = model_checks(short, s['comparison_profiles'], e, g, instant(AT))
        self.assertIn('short_collateral_unsupported', r['contract']['reason_codes'])
        q,p,e,g,b = authored();q['binding']['selection']['predicate'] = 'not_win'
        r = row(q,p,e,g,b)
        self.assertIn('identity_conflict',r['checks']['contract']['reason_codes'])
        self.assertIn('contract_predicate_conflict',r['checks']['contract']['reason_codes'])

    def test_partial_healthy_coverage_and_no_unearned_zero(self):
        rows = pair_rows();more = deepcopy(rows[0]);more.update(id='authored-blocked', occurrence_id='other')
        more['checks']['execution'] = check(['aggregate_transport_uncertain'])
        r = projection([*rows,more])
        self.assertEqual(r['state'], 'partial')
        self.assertEqual(r['counts']['cashflow_pairs_ready']['value'], 1)
        self.assertEqual(r['evaluation']['state'], 'not_evaluated')
        self.assertIsNone(r['evaluation']['qualifying_pairs'])
        self.assertFalse(r['evaluation']['no_qualifying_opportunities'])

    def test_no_pairs_and_waiting_are_not_evaluated_zero(self):
        r = projection([row()])
        self.assertEqual(r['pair_coverage'],'no_compatible_pairs')
        self.assertEqual(r['evaluation']['state'],'not_evaluated')
        self.assertFalse(r['evaluation']['no_qualifying_opportunities'])
        self.assertEqual(projection([])['state'], 'waiting')

    def test_authoritative_exact_evaluated_zero_and_withdrawal(self):
        rows = pair_rows();r = projection(rows)
        receipt = dict(pair_id=r['pairs'][0]['id'],readiness_revision=r['revision'],evaluated_at=AT,qualifying=False,evaluator_revision='authored-sc02-test')
        checked = projection(rows,evaluations=[receipt])
        self.assertEqual(checked['evaluation']['state'],'evaluated_zero')
        self.assertTrue(checked['evaluation']['no_qualifying_opportunities'])
        rows[0]['checks']['execution'] = check(['source_price_expired'])
        r = projection(rows,evaluations=[receipt])
        self.assertEqual(r['evaluation']['state'],'not_evaluated')
        self.assertFalse(r['evaluation']['no_qualifying_opportunities'])
        with self.assertRaisesRegex(ValueError,'evaluation_clock_conflict'):
            projection(pair_rows(),evaluations=[dict(receipt,evaluated_at='2027-01-01T00:00:00Z')])

    def test_cross_leg_skew_and_actual_model_horizon(self):
        rows=pair_rows();rows[1]['clocks']['source_at']=(instant(AT)-timedelta(seconds=31)).isoformat()
        self.assertIn('cross_leg_skew_exceeded',projection(rows)['pairs'][0]['input_check']['reason_codes'])
        q,p,e,g,b=authored();r=row(q,p,e,g,b,at='2026-10-16T04:00:00Z')
        self.assertIn('execution_model_expired',r['checks']['contract']['reason_codes'])
        self.assertEqual(r['clocks']['source_at'],AT)

    def test_scope_denominators_overlap_stability_and_filters(self):
        rows=pair_rows();rows[0]['checks']['execution']=check(['source_price_expired','book_price_expired'])
        r=projection(rows);self.assertEqual(r,projection(list(reversed(rows))))
        self.assertEqual(r['counts']['observed_occurrences']['value'],1)
        self.assertEqual(r['counts']['cashflow_pairs_ready']['denominator'],1)
        causes=[c for c in r['causes'] if c['purpose']=='execution']
        self.assertEqual(sum(c['count']['value'] for c in causes),2)
        self.assertEqual(r['counts']['observed_instruments']['value'],2)
        s=Selection(leagues=('NBA',),sports=('basketball',))
        scopes=scope_inventory(s,DEFAULT,GRANT)
        self.assertTrue(all(not x['authorized'] and not x['supported'] for x in scopes))
        self.assertEqual(projection([],selection=s,scopes=scopes)['state'],'unsupported')
        with self.assertRaises(ValueError):Selection(venues=('pinnacle',))

    def test_read_does_not_mutate_inputs_or_acquire(self):
        rows=pair_rows();before=deepcopy(rows);scopes=scope_inventory(Selection(venues=('polymarket_us','kalshi')),DEFAULT,GRANT);original=deepcopy(scopes)
        with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
            projection(rows,scopes=scopes)
        self.assertEqual(rows,before);self.assertEqual(scopes,original)

    def test_actual_deadlines_withdraw_without_packets(self):
        q,p,e,g,b=authored()
        before='2026-10-16T03:59:50Z'
        q['times'].update(source_at=before,received_at=before,projected_at=before)
        q['provider_clocks']={k:before for k in ('book','market')}
        b.update(source_at=before,received_at=before)
        r=row(q,p,e,g,b,at=before)
        self.assertEqual(instant(r['expires_at']),instant('2026-10-16T04:00:00Z'))
        later=row(q,p,e,g,b,at='2026-10-16T04:00:00Z')
        self.assertIn('execution_model_expired',later['checks']['contract']['reason_codes'])
        self.assertNotEqual(projection([r],at=before)['revision'],projection([later],at='2026-10-16T04:00:00Z')['revision'])

    def test_selected_counts_failure_and_scope_capacity(self):
        rows=pair_rows()
        r=projection(rows,selection=Selection(venues=('kalshi',)))
        self.assertEqual(r['counts']['observed_instruments']['value'],1)
        self.assertEqual(r['counts']['compatible_pair_inputs']['value'],0)
        scopes=scope_inventory(Selection(venues=('polymarket_us','kalshi')),DEFAULT,GRANT)
        scopes[0]['check']=check(['source_failed'])
        self.assertEqual(projection(rows,scopes=scopes)['state'],'partial')
        with self.assertRaisesRegex(ValueError,'scope_capacity'):
            scope_inventory(Selection(sports=tuple('s'+str(i) for i in range(16)),leagues=tuple('l'+str(i) for i in range(16))),DEFAULT,GRANT)

    def test_settings_read_is_local_and_changes_no_source_clocks(self):
        from app.comparison.estimated_policy import load
        root=Path(TEST_ROOT.name);p=root/'authored-settings.json'
        p.write_text('{"capital_ceiling_usd":"500"}')
        with patch('socket.socket.connect',side_effect=AssertionError('No acquisition')):
            policy=load(p)
            r=row()
        self.assertEqual(policy.capital_ceiling_usd,'500')
        self.assertEqual(r['clocks']['source_at'],AT)
