import json
import unittest
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from app.collection.current_aggregate_admission import admit
from app.collection.current_benchmark import attach,calculate,validate_reference
from app.dashboard.current_contract import serialize,stamp,packed
from app.dashboard.current_normalized import catalog_from_normalized
from tests.test_current_aggregate import body
from tests.current_fixture import fixture

AT='2026-10-03T00:00:00Z'

class BenchmarkTests(unittest.TestCase):
    def raw(self):
        payload=json.loads(body(books=('novig','prophetx','pinnacle')))
        for book in payload[0]['bookmakers']:
            if book['key']=='pinnacle':
                for market in book['markets']:
                    market['outcomes'][0]['price']='1.6'
                    market['outcomes'][1]['price']='2.4'
        encoded=json.dumps(payload).encode()
        records=admit(encoded,'MLB',AT,venue='novig')
        refs=admit(encoded,'MLB',AT,venue='pinnacle')
        attach(records,refs)
        for r in records:
            r.pop('_instrument');r.pop('_fingerprint')
            r['quote']['provenance']=dict(mode='synthetic',real_source=False,fixture='controlled-pinnacle')
        envelope=fixture();envelope['clock_at']=AT;envelope['projected_at']=AT;envelope['events']=[]
        return catalog_from_normalized(envelope,records)
    def quote(self,s):
        return next(q for e in s['events'] for g in e['groups'] for o in g['outcomes'] for q in o['quotes'].values() if q['sharp_reference']['odds'][q['sharp_reference']['selected']]=='1.6')
    def test_exact_devig_and_positive_negative_zero(self):
        raw=self.raw()
        for e in raw['events']:
            for g in e['groups']:
                for o in g['outcomes']:
                    for q in o['quotes'].values():q['original']['value']='2'
        s=serialize(raw,allow_synthetic=True);q=self.quote(s)
        self.assertEqual(Decimal(q['calculations']['ev']['value']),20)
        self.assertEqual(Decimal(q['calculations']['ev']['basis']['probability']['decimal_approx']),Decimal('.6'))
        for odds,want in [('1.666666666666666666666666666666666666666666666666666666666666','nearzero'),('1.25','negative')]:
            changed=deepcopy(q);changed['original']['value']=odds
            value=Decimal(calculate(changed,stamp(AT))['value'])
            if want=='nearzero':self.assertLess(abs(value),Decimal('1e-50'))
            else:self.assertEqual(value,Decimal('-25'))
        changed=deepcopy(q);changed['sharp_reference']['odds']=['2','2'];changed['original']['value']='2'
        self.assertEqual(Decimal(calculate(changed,stamp(AT))['value']),0)
        self.assertIn('fees excluded',q['calculations']['ev']['scope'])
    def test_age_unknown_future_and_binding(self):
        q=self.quote(serialize(self.raw(),allow_synthetic=True))
        self.assertFalse(calculate(q,stamp(AT)+timedelta(seconds=1801))['eligible'])
        for times in [[None,AT],[AT,'2026-10-03T00:00:01Z']]:
            changed=deepcopy(q);changed['sharp_reference']['source_at']=times
            self.assertFalse(calculate(changed,stamp(AT))['eligible'])
        wrong=deepcopy(q['sharp_reference']);wrong['selection_digest']='binding:wrong-selection'
        with self.assertRaises(ValueError):validate_reference(wrong,q['binding']['selection'])
    def test_exact_line_and_missing_pair(self):
        encoded=body(books=('novig','pinnacle'))
        records=admit(encoded,'MLB',AT,venue='novig');refs=admit(encoded,'MLB',AT,venue='pinnacle')
        for r in refs:r['market_identity']['line']='99.5'
        attach(records,refs);self.assertTrue(all('sharp_reference' not in r['quote'] for r in records))
        refs=admit(encoded,'MLB',AT,venue='pinnacle')
        attach(records,refs[:1]);self.assertTrue(all('sharp_reference' not in r['quote'] for r in records))
    def test_reference_is_not_a_board_venue_and_snapshot_reproduces(self):
        from app.dashboard.current_contract import validate_snapshot,snapshot_inputs
        s=serialize(self.raw(),allow_synthetic=True)
        validate_snapshot(s,allow_synthetic=True)
        self.assertTrue(all(set(o['quotes'])=={'novig'} for e in s['events'] for g in e['groups'] for o in g['outcomes']))
        raw=snapshot_inputs(s);raw['clock_at']='2026-10-03T00:31:00Z'
        aged=serialize(raw,allow_synthetic=True)
        self.assertFalse(self.quote(aged)['calculations']['ev']['eligible'])

    def test_store_expires_benchmark_when_aggregate_stale_flag_is_already_true(self):
        from app.dashboard.current_state import CurrentStore
        from tests.current_fixture import InjectedTestProvider
        ticks=[0]
        store=CurrentStore(InjectedTestProvider(self.raw()),monotonic=lambda:ticks[0])
        before=store.snapshot();self.assertTrue(self.quote(before)['calculations']['ev']['eligible'])
        ticks[0]=1801
        after=store.snapshot();self.assertFalse(self.quote(after)['calculations']['ev']['eligible'])
        self.assertGreater(after['state_revision'],before['state_revision'])

    def test_whole_lines_and_different_periods_are_withheld(self):
        encoded=body(books=('novig','pinnacle'))
        records=admit(encoded,'MLB',AT,venue='novig');refs=admit(encoded,'MLB',AT,venue='pinnacle')
        for r in [*records,*refs]:
            if r['market_identity']['family'] in ('spread','total'):
                r['market_identity']['line']='47'
                r['selection']['signed_line']='47'
            else:
                r['market_identity']['period']='first_half' if r in refs else 'full_game'
        attach(records,refs)
        self.assertTrue(all('sharp_reference' not in r['quote'] for r in records))

    def test_stopped_source_does_not_claim_seventeen_minute_quote_is_too_old(self):
        q=self.quote(serialize(self.raw(),allow_synthetic=True))
        q['state']='stopped'
        result=calculate(q,stamp(AT)+timedelta(minutes=17))
        self.assertFalse(result['eligible'])
        self.assertEqual(result['reason'],'Updates stopped; reopen current prices')
        q['state']='budget_delayed'
        self.assertTrue(calculate(q,stamp(AT)+timedelta(minutes=18))['eligible'])
        q['times']['source_at']='2026-10-02T23:40:00Z'
        result=calculate(q,stamp(AT)+timedelta(minutes=18))
        self.assertEqual(result['reason'],'Comparison quote is older than the 30-minute limit')
