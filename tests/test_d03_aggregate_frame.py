"""One ordinary aggregate decode; exact adapter semantics and venue isolation."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from app.collection.current_aggregate import AggregateScheduler
from app.collection.current_aggregate_admission import admit,admit_venues,parse_frame,market_exclusions
from app.comparison.coverage import CoverageLedger
from app.dashboard.current_state import unavailable
from tests.test_current_aggregate import body

AT='2026-10-15T12:00:00Z'


def ordinary_scheduler():
    committed=[];issues=[]
    service=SimpleNamespace(states=unavailable()['source_status'],database=object(),config=dict(sports=['NFL']),
        coverage=CoverageLedger({v:['NFL'] for v in ('novig','prophetx','pinnacle')}),
        sink=SimpleNamespace(commit=lambda row,states:committed.append((row,states))),
        observation=lambda *args:None,issue=lambda *args:issues.append(args))
    scheduler=AggregateScheduler.__new__(AggregateScheduler)
    scheduler.service=service;scheduler.issue_context={};scheduler.metrics={};scheduler.sport_states={}
    scheduler.permitted=lambda:None
    scheduler.quota_next_due_at=...
    scheduler.ledger=SimpleNamespace(snapshot=lambda:dict(next_due_at=None),pause=lambda reason:None)
    return scheduler,committed,issues


class AggregateFrame(unittest.TestCase):
    def test_ordinary_admission_decodes_once_and_preserves_exact_adapter_values(self):
        raw=body('NFL',books=('novig','prophetx','pinnacle'),price='2.500000000000000000000001')
        expected=[r for venue in ('novig','prophetx','pinnacle') for r in admit(raw,'NFL',AT,venue=venue)]
        scheduler,committed,_=ordinary_scheduler()
        with patch('json.loads',wraps=json.loads) as decode:
            scheduler.admit_response(dict(body=raw,received_at=AT),'NFL')
        self.assertEqual(decode.call_count,1)
        self.assertEqual(committed[0][0]['records'],expected)
        self.assertEqual(committed[0][0]['complete_venues'],['novig','prophetx','pinnacle'])
        self.assertTrue(any(r['quote']['original']['value']=='2.500000000000000000000001' for r in expected))
        self.assertTrue(all(v['latest']['completeness']=='complete' for v in scheduler.service.coverage.observations.values()))

    def test_transport_supplied_frame_is_reused_without_decoding(self):
        raw=body('NFL',books=('novig','prophetx','pinnacle'));frame=parse_frame(raw)
        scheduler,committed,_=ordinary_scheduler()
        admit(raw,'NFL',AT,venue='novig')
        with patch('json.loads',side_effect=AssertionError('response decoded again')):
            scheduler.admit_response(dict(body=raw,received_at=AT,parsed_frame=frame),'NFL')
        self.assertEqual(len(committed),1)
        self.assertEqual(frame.payload,parse_frame(raw).payload)

    def test_transport_and_admission_share_the_only_response_decode(self):
        import asyncio
        from app.collection.current_aggregate import CurrentOddsTransport
        raw=body('NFL',books=('novig','prophetx','pinnacle'))
        # Warm the shared reviewed registry before measuring response decoding.
        admit(raw,'NFL',AT,venue='novig')
        class Response:
            status=200;headers={}
            async def __aenter__(self):return self
            async def __aexit__(self,*args):return False
            async def iter_chunked(self,size):yield raw
            @property
            def content(self):return self
        transport=CurrentOddsTransport();transport.client=SimpleNamespace(get=lambda *args,**kwargs:Response())
        scheduler,committed,_=ordinary_scheduler()
        async def ordinary():
            response=await transport.request(dict(path='/v4/sports/americanfootball_nfl/odds',params={}), 'authored-local-test-secret')
            scheduler.admit_response(response,'NFL')
        with patch('json.loads',wraps=json.loads) as decode:asyncio.run(ordinary())
        self.assertEqual(decode.call_count,1);self.assertEqual(len(committed),1)

    def test_one_bad_venue_keeps_other_venues_and_does_not_mutate_frame(self):
        payload=json.loads(body('NFL',books=('novig','prophetx','pinnacle')))
        payload[0]['bookmakers'][1]['markets'][0]['outcomes'].pop()
        raw=json.dumps(payload).encode();frame=parse_frame(raw);before=deepcopy(frame.payload)
        accepted,errors=admit_venues(raw,'NFL',AT,frame=frame,include_reference=True)
        self.assertEqual(set(accepted),{'novig','prophetx','pinnacle'});self.assertEqual(len(accepted['prophetx']),4);self.assertEqual(set(errors),{'prophetx'})
        self.assertEqual(frame.payload,before)
        scheduler,committed,issues=ordinary_scheduler()
        scheduler.admit_response(dict(body=raw,received_at=AT,parsed_frame=frame),'NFL')
        self.assertEqual(committed[0][0]['complete_venues'],['novig','pinnacle'])
        self.assertTrue(any(issue[0]=='prophetx' for issue in issues))
        self.assertEqual(scheduler.service.coverage.observations[('NFL','prophetx')]['latest']['status'],'rejected_payload')

    def test_normalizer_optional_frame_matches_unchanged_default(self):
        from app.reference.odds_sample import normalize
        raw=body('NFL',books=('novig','prophetx','pinnacle')).replace(b'"2.5000"',b'2.500000000000000000000001')
        frame=parse_frame(raw)
        self.assertEqual(normalize(raw,'NFL',AT),normalize(raw,'NFL',AT,_parsed_events=frame.payload,_receipt_sha256=frame.receipt_sha256))
        accepted,rejected=admit_venues(b'[{','NFL',AT)
        self.assertEqual(accepted,{})
        self.assertEqual(set(rejected),{'novig','prophetx'})

    def test_numeric_decimal_spelling_and_strict_invalid_json(self):
        raw=body('NFL',books=('novig','prophetx','pinnacle')).replace(b'"2.5000"',b'2.500000000000000000000001')
        frame=parse_frame(raw);rows=admit(raw,'NFL',AT,venue='novig',frame=frame)
        self.assertTrue(all(r['quote']['original']['value']=='2.500000000000000000000001' for r in rows))
        for invalid in (b'{"x":1,"x":2}',b'[NaN]',b'[Infinity]'):
            with self.assertRaises(ValueError):parse_frame(invalid)
        with self.assertRaisesRegex(ValueError,'parsed_frame_identity'):admit(b'[]','NFL',AT,frame=frame)

    def test_excluded_price_market_and_reference_share_one_frame(self):
        payload=json.loads(body('NFL',books=('novig','prophetx','pinnacle')))
        payload[0]['bookmakers'][0]['markets'][0]['outcomes'][0]['price']='1.0000'
        raw=json.dumps(payload).encode();scheduler,committed,_=ordinary_scheduler()
        admit(raw,'NFL',AT,venue='novig')
        with patch('json.loads',wraps=json.loads) as decode:scheduler.admit_response(dict(body=raw,received_at=AT),'NFL')
        self.assertEqual(decode.call_count,1)
        self.assertEqual(scheduler.metrics['unsupported_market_exclusions']['NFL'],{'novig':1})
        self.assertEqual(len([r for r in committed[0][0]['records'] if r['quote']['venue']=='novig']),4)

if __name__=='__main__':unittest.main()
