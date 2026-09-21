import asyncio
import base64
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from app.edge_contracts import reference_decisions
from app.models.core import Venue
from app.reference.adapter import OddsAPIReferenceAdapter, Response, Bounds, PersistenceFailure
from app.reference.enrichment import enrich
from app.reference.records import (Receipt, QuoteRevision, ReferenceGap, request_metadata, packed,
    export_records, import_records, as_of, EVENT)
from app.reference.fixtures import source, assessment, terms, payload, before, FixtureClock, FixtureTransport


def receipt(body=None, identity='r1', at=None, status=200):
    body = payload() if body is None else body
    return Receipt(id=identity, session_id='synthetic-e2', received_at=at or before(), request_started_at=at or before(),
        body_b64=base64.b64encode(body).decode(), body_sha256=sha256(body).hexdigest(), status=status,
        request_json=packed(request_metadata()), headers=())


def changed(fn):
    data = json.loads(payload(), parse_float=str)
    fn(data)
    return json.dumps(data).encode()


def market(d): return d['bookmakers'][0]['markets'][0]


class ReferenceTests(unittest.TestCase):
    def revision(self, body=None, **kw): return enrich(receipt(body), source(), assessment(**kw))

    def test_complete_exact_and_reversed(self):
        a = self.revision()
        b = self.revision(changed(lambda d: market(d)['outcomes'].reverse()))
        self.assertEqual(a.reasons, ())
        self.assertEqual(a.quote.decimal_odds, (Decimal('1.90000000000000000001'), Decimal('2.1000')))
        self.assertEqual(a.quote.decimal_odds, b.quote.decimal_odds)
        self.assertEqual(a.quote.native_outcome_ids, b.quote.native_outcome_ids)
        self.assertEqual(str(a.quote.decimal_odds[1]), '2.1000')

    def test_missing_side_never_borrows(self):
        q = self.revision(changed(lambda d: market(d)['outcomes'].pop())).quote
        self.assertEqual(q.decimal_odds[1], None)

    def test_duplicate_third_draw(self):
        for change in (lambda d: market(d)['outcomes'].append(market(d)['outcomes'][0]),
                       lambda d: market(d)['outcomes'].__setitem__(1, market(d)['outcomes'][0]),
                       lambda d: market(d)['outcomes'][1].update(name='Draw')):
            self.assertIsNone(self.revision(changed(change)).quote)

    def test_malformed_missing_id_and_bad_prices(self):
        for body in (b'no json', b'\xff', b'[]', b'{"id":"x","id":"y"}',
                     changed(lambda d: d.pop('id')), changed(lambda d: market(d)['outcomes'][0].update(price='NaN')),
                     changed(lambda d: market(d)['outcomes'][0].update(price=True)), changed(lambda d: d.pop('commence_time'))):
            self.assertIsNone(self.revision(body).quote)

    def test_optional_ids_times_limits_unknown(self):
        def change(d):
            d['bookmakers'][0].pop('sid'); market(d).pop('sid'); market(d).pop('last_update')
            for o in market(d)['outcomes']: o.pop('sid')
        rev = self.revision(changed(change))
        self.assertIsNone(rev.quote.source_at)
        self.assertIsNone(rev.quote.limits)
        self.assertEqual(json.loads(rev.evidence_json)['side_timestamps'], [None, None])
        self.assertEqual(json.loads(rev.evidence_json)['native_sids']['outcomes'], [None, None])

    def test_identity_schedule_phase_and_terms(self):
        for change in (lambda d: d.update(home_team='Unknown City'), lambda d: d.update(away_team='Atlanta Falcons'),
                       lambda d: d.update(commence_time=before(1)), lambda d: d.update(phase='live'),
                       lambda d: market(d).update(period='first_half'), lambda d: market(d)['outcomes'][0].update(point='3')):
            self.assertIsNone(self.revision(changed(change)).quote)

    def test_unknown_pair_lineage_rules_ineligible(self):
        for src, assess in ((source(), assessment(pairing=False)), (source(assessed=False), assessment()),
                            (source(), assessment(rules=False))):
            rev = enrich(receipt(), src, assess)
            decisions = reference_decisions([rev.quote], target=Venue.KALSHI, terms=terms(), cutoff=terms().scheduled_start-timedelta(seconds=59), max_receipt_age=timedelta(seconds=30), mode='synthetic')
            self.assertFalse(decisions[0].included)
            self.assertTrue(rev.reasons)
        self.assertIsNone(source(assessed=False).copied_from)

    def test_synthetic_positive_is_explicit(self):
        with self.assertRaises(ValueError): replace(assessment(), evidence=())
        with self.assertRaises(ValueError): replace(source(), evidence=('provider truth',))

    def test_later_knowledge_and_late_receipts(self):
        r = receipt(); s0 = source(assessed=False); v0 = enrich(r, s0, assessment(pairing=False, rules=False), revision_id='v0')
        s1 = source(known_at=before(40), identity='s1'); v1 = enrich(r, s1, assessment(known_at=before(40)), revision_id='v1')
        late = receipt(identity='late', at=before(30)); vl = enrich(late, s1, assessment(known_at=before(30)), revision_id='vl')
        records = [r,s0,v0,s1,v1,late,vl]
        early = import_records(as_of(records, before(50)))
        self.assertEqual([x.id for x in early if isinstance(x, QuoteRevision)], ['v0'])
        self.assertEqual([x.id for x in early if isinstance(x, Receipt)], ['r1'])
        self.assertEqual(v0.quote.copied_from, None)
        self.assertEqual([x.id for x in import_records(as_of(records, before(35))) if isinstance(x, QuoteRevision)], ['v1'])

    def test_historical_snapshot_is_not_receipt(self):
        d = json.loads(payload(), parse_float=str)
        body = json.dumps({'timestamp':before(3600), 'previous_timestamp':before(3900), 'next_timestamp':before(3300), 'data':d}).encode()
        r=receipt(body); s=source(); v=enrich(r,s,assessment())
        self.assertEqual(json.loads(v.evidence_json)['historical_snapshot']['timestamp'],before(3600))
        self.assertEqual(v.quote.received_at.isoformat(),before())
        self.assertEqual([r for r in import_records(as_of([r,s,v],before(3500))) if isinstance(r,Receipt)],[])

    def test_exact_roundtrip_and_tamper(self):
        r=receipt(); s=source(); v=enrich(r,s,assessment())
        blob=export_records([r,s,v])
        self.assertEqual(export_records(import_records(blob)),blob)
        self.assertEqual(next(x for x in import_records(blob) if isinstance(x,Receipt)).body,payload())
        with self.assertRaises(ValueError): import_records(blob.replace('reference-bundle-1','reference-bundle-2'))
        with self.assertRaises(ValueError): export_records([r,s,v,r])
        with self.assertRaises(ValueError): export_records([r,s,replace(v,known_at=before(200))])

    def test_request_secret_rejected(self):
        with self.assertRaises(ValueError): replace(receipt(),request_json='{"apiKey":"secret"}')
        with self.assertRaises(ValueError): replace(receipt(),headers=(('authorization','secret'),))


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)

    def adapter(self,responses,**options):
        self.saved=[]; self.transport=FixtureTransport(responses)
        return OddsAPIReferenceAdapter(transport=self.transport, clock=FixtureClock(), sink=options.pop('sink',self.saved.append),
            source=source(), assessment=options.pop('assessment',assessment()), session_id='synthetic-e2',
            failure_journal=Path(self.tmp.name)/'failures.jsonl', bounds=options.pop('bounds',Bounds(max_requests=len(responses))), **options)

    async def test_repeats_nonopportunities_recovery(self):
        adapter=self.adapter([Response(200,payload()),Response(200,payload()),Response(429,b'{"message":"rate limit"}'),Response(200,changed(lambda d:market(d)['outcomes'][0].update(price='1.8')))])
        output=[x async for x in adapter.observe(EVENT)]
        receipts=[r for r in self.saved if isinstance(r,Receipt)]
        self.assertEqual(len(receipts),4); self.assertEqual(len({r.id for r in receipts}),4)
        self.assertEqual(receipts[0].body_sha256,receipts[1].body_sha256)
        recovery=[r for r in output if isinstance(r,ReferenceGap) and r.recovery=='fresh_snapshot']
        self.assertEqual(len(recovery),1); self.assertIsNone(recovery[0].start_at)
        self.assertEqual(recovery[0].receipt_id,receipts[-1].id)
        self.assertTrue(self.transport.closed)

    async def test_quota_and_entitlement_stop(self):
        for response in [Response(429,b'{"error_code":"OUT_OF_USAGE_CREDITS"}'),Response(200,payload(),(('x-requests-remaining','0'),)),Response(403,b'forbidden')]:
            a=self.adapter([response,Response(200,payload())]); output=[x async for x in a.observe(EVENT)]
            self.assertEqual(self.transport.calls,1)
            self.assertIn(output[-1].reason,('quota_exhausted','entitlement_stop'))
            self.assertEqual(len([r for r in self.saved if isinstance(r,Receipt)]),1)

    async def test_finite_retries_and_guidance(self):
        a=self.adapter([Response(429,b'{}',(('Retry-After','99'),)),Response(200,payload())])
        output=[x async for x in a.observe(EVENT)]
        self.assertEqual(output[-1].reason,'retry_guidance_exceeds_budget');self.assertEqual(self.transport.calls,1)
        a=self.adapter([OSError('offline')]*5,bounds=Bounds(max_requests=5,max_retries=1))
        output=[x async for x in a.observe(EVENT)]
        self.assertEqual(self.transport.calls,2)

    async def test_incomplete_recovery_uses_new_pair(self):
        a=self.adapter([Response(200,changed(lambda d:market(d)['outcomes'].pop())),Response(200,payload())])
        output=[x async for x in a.observe(EVENT)]
        self.assertIsNone(output[0].decimal_odds[1]); self.assertTrue(any(isinstance(x,ReferenceGap) and x.recovery=='fresh_snapshot' for x in output))

    async def test_cancel_request_and_backoff(self):
        for during_request in (True,False):
            entered=asyncio.Event()
            a=self.adapter([Response(429,b'{}')])
            async def block(*args): entered.set(); await asyncio.Event().wait()
            if during_request: a.transport.request=block
            else: a.clock.sleep=block
            async def run(): return [x async for x in a.observe(EVENT)]
            task=asyncio.create_task(run());await entered.wait();task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertEqual(self.saved[-1].reason,'cancelled');self.assertTrue(self.transport.closed)

    async def test_storage_and_queue_failure_journal(self):
        for error in (OSError('disk'),asyncio.QueueFull()):
            def fail(record):raise error
            a=self.adapter([Response(200,payload())],sink=fail)
            with self.assertRaises(PersistenceFailure): [x async for x in a.observe(EVENT)]
            journal=json.loads((Path(self.tmp.name)/'failures.jsonl').read_text().splitlines()[-1])
            self.assertEqual(journal['record']['type'],'Receipt');self.assertTrue(self.transport.closed)
            self.assertEqual(base64.b64decode(journal['record']['data']['body_b64']),payload())

    async def test_schedule_phase_stop_and_kickoff(self):
        for body in (changed(lambda d:d.update(commence_time=before(1))),changed(lambda d:d.update(phase='live'))):
            a=self.adapter([Response(200,body),Response(200,payload())]);out=[x async for x in a.observe(EVENT)]
            self.assertEqual(out[-1].reason,'phase_schedule_identity_stop');self.assertEqual(self.transport.calls,1)
        a=self.adapter([Response(200,payload())]);a.clock=FixtureClock(terms().scheduled_start.isoformat())
        out=[x async for x in a.observe(EVENT)];self.assertEqual(self.transport.calls,0)

    async def test_raw_rejected_headers_and_work_bound(self):
        a=self.adapter([Response(500,b'invalid json',(('X-Requests-Used','01'),('Set-Cookie','secret')))],bounds=Bounds(max_requests=1,max_response_bytes=2))
        out=[x async for x in a.observe(EVENT)]
        self.assertEqual(out[-1].reason,'payload_work_limit')
        self.assertEqual(self.saved[0].body,b'invalid json');self.assertEqual(self.saved[0].headers,(('x-requests-used','01'),))

    async def test_close_and_scope(self):
        a=self.adapter([Response(200,payload())])
        with self.assertRaises(ValueError): [x async for x in a.observe('another-event')]
        await a.aclose();await a.aclose();self.assertTrue(self.transport.closed)

class EnrichmentRevisionTests(unittest.TestCase):
    def test_later_alias_knowledge_does_not_rewrite_unresolved(self):
        from app.normalization.registry import Registry
        body=changed(lambda d:d.update(home_team='Synthetic ATL Alias'))
        r=receipt(body);s=source();initial=enrich(r,s,assessment(),revision_id='initial')
        self.assertIsNone(initial.quote)
        data=json.loads(Registry.load().to_json())
        data['version']='synthetic-later-alias-v2'
        data['aliases'].append({'kind':'team','league':'NFL','text':'Synthetic ATL Alias','targets':['NFL:ATL'],'source':'synthetic:invented alias'})
        later=enrich(r,s,assessment(known_at=before(40)),registry=Registry(data),revision_id='later')
        self.assertIsNotNone(later.quote)
        records=[r,s,initial,later]
        self.assertEqual([x.id for x in import_records(as_of(records,before(50))) if isinstance(x,QuoteRevision)],['initial'])
        self.assertEqual(export_records(import_records(export_records(records))),export_records(records))

    def test_ambiguous_alias_is_not_chosen(self):
        from app.normalization.registry import Registry
        data=json.loads(Registry.load().to_json())
        data['aliases'].append({'kind':'team','league':'NFL','text':'Ambiguous Team','targets':['NFL:ATL','NFL:PIT'],'source':'synthetic:ambiguous test alias'})
        rev=enrich(receipt(changed(lambda d:d.update(home_team='Ambiguous Team'))),source(),assessment(),registry=Registry(data))
        self.assertIn('ambiguous_or_missing_participants',rev.reasons)

    def test_recomputed_enrichment_rejects_tampered_prices(self):
        r=receipt();s=source();v=enrich(r,s,assessment())
        forged=replace(v,quote=replace(v.quote,decimal_odds=(Decimal('1.8'),Decimal('2.1'))))
        with self.assertRaises(ValueError):export_records([r,s,forged])

    def test_effective_after_receipt_not_eligible_reconstruction(self):
        r=receipt();s=source();a=replace(assessment(known_at=before(40)),effective_at=before(40))
        v=enrich(r,s,a)
        self.assertIn('assessment_not_effective',v.reasons)
        self.assertFalse([x for x in import_records(as_of([r,s,v],before(50))) if isinstance(x,QuoteRevision)])

class AdditionalBoundsTests(unittest.IsolatedAsyncioTestCase):
    setUp = AdapterTests.setUp
    adapter = AdapterTests.adapter

    async def test_duplicate_quota_headers_stop_conservatively(self):
        a=self.adapter([Response(200,payload(),(('x-requests-remaining','0'),('x-requests-remaining','10'))),Response(200,payload())])
        out=[x async for x in a.observe(EVENT)]
        self.assertEqual(self.transport.calls,1);self.assertEqual(out[-1].reason,'quota_exhausted')

    async def test_request_timeout_is_bounded(self):
        a=self.adapter([Response(200,payload())],bounds=Bounds(max_requests=1,request_timeout=0.01,max_retries=0))
        async def pending(*args):await asyncio.Event().wait()
        a.transport.request=pending
        out=[x async for x in a.observe(EVENT)]
        self.assertEqual(out[-1].reason,'transport_failure');self.assertTrue(self.transport.closed)

    async def test_consumer_generator_close_records_interruption(self):
        a=self.adapter([Response(200,payload())]);stream=a.observe(EVENT)
        await anext(stream);await stream.aclose()
        self.assertEqual(self.saved[-1].reason,'consumer_closed');self.assertTrue(self.transport.closed)

    async def test_unresolved_schedule_stops_after_raw_ingress(self):
        a=self.adapter([Response(200,changed(lambda d:d.pop('commence_time'))),Response(200,payload())])
        out=[x async for x in a.observe(EVENT)]
        self.assertEqual(self.transport.calls,1);self.assertEqual(out[-1].reason,'phase_schedule_identity_stop')
