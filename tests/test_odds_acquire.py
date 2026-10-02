"""Offline mocked transport only; all keys/events/quotas below are synthetic."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from app.reference import odds_acquire as runner
from app.reference.odds_sample import LIMIT
from tests.test_odds_bindings import event, AT
from app.dashboard.session_history import load
from app.dashboard.price_comparison import comparisons

KEY = 'syntheticCredential00000000000000'

def headers(cost=0, remaining=10, used=0):
    return {'x-requests-last':str(cost), 'x-requests-remaining':str(remaining), 'x-requests-used':str(used)}

class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks, failure=None):
        self.chunks=chunks;self.failure=failure
    async def __aiter__(self):
        for chunk in self.chunks: yield chunk
        if self.failure: raise self.failure

class Acquisition(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.folder=Path(temp.name)/'attempt';self.calls=[]
        self.auth=dict(authorized=True, source_sha256=runner.identity()['source_sha256'],
                      spec_sha256=runner.SPEC_SHA256, attempt_path=str(self.folder.resolve()),
                      maximum_requests=2,maximum_credits=3)

    def run_capture(self, discovery=None, odds=None, *, clock=lambda:AT, mono=lambda:0):
        def handler(req):
            self.calls.append(req)
            self.assertLessEqual(len(self.calls),2)
            self.assertEqual(req.method,'GET')
            self.assertEqual(req.url.host,'api.the-odds-api.com')
            if len(self.calls)==1:
                self.assertEqual(req.url.path,'/v4/sports/americanfootball_nfl/events')
                self.assertEqual(dict(req.url.params),dict(apiKey=KEY,dateFormat='iso'))
                value=discovery
                default=httpx.Response(200,json=[event()],headers=headers())
            else:
                self.assertEqual(req.url.path,'/v4/sports/americanfootball_nfl/events/abc123/odds')
                self.assertEqual(dict(req.url.params),dict(runner.acquisition_plan('abc123')['params'],apiKey=KEY))
                value=odds
                default=httpx.Response(200,json=event(),headers=headers(3,7,3))
            if isinstance(value,BaseException):raise value
            return default if value is None else value
        return asyncio.run(runner.capture(self.folder,KEY,self.auth,
            transport=httpx.MockTransport(handler),clock=clock,monotonic=mono))

    def assert_evidence(self, count):
        self.assertEqual(len(self.calls),count)
        self.assertTrue(json.loads((self.folder/'attempt.json').read_text())['consumed'])
        for name in ('discovery','odds')[:count]:
            path=self.folder/name
            self.assertTrue((path/'attempt.json').exists())
            meta=json.loads((path/'result.json').read_text())
            if meta['body_retained']:
                body=(path/'response.json').read_bytes()
                self.assertLessEqual(len(body),LIMIT)
                self.assertEqual(runner.sha256(body).hexdigest(),meta['body_sha256'])
        data=b''.join(p.read_bytes() for p in self.folder.rglob('*') if p.is_file())
        self.assertNotIn(KEY.encode(),data)
        self.assertNotIn(b'apiKey=',data)
        with self.assertRaises(FileExistsError):
            self.run_capture()
        self.assertEqual(len(self.calls),count)

    def test_success_import_and_exact_historical_reopening(self):
        result=self.run_capture();self.assertEqual(result['outcome'],'acquired')
        self.assertEqual(result['credits_reserved'],3);self.assert_evidence(2)
        folder=runner.import_retained(self.folder,self.folder/'sessions')
        snapshot=load(folder);self.assertEqual(load(folder),snapshot)
        pairs=comparisons(snapshot,{})
        self.assertEqual(len(pairs),1)
        self.assertIsNone(pairs[0]['net']);self.assertIsNone(pairs[0]['ev'])

    def test_empty_reference_only_and_partial_are_final(self):
        for books in ([],[dict(key='pinnacle',markets=[])],event()['bookmakers'][:1]):
            with self.subTest(books=books):
                self.setUp();e=event();e['bookmakers']=books
                result=self.run_capture(odds=httpx.Response(200,json=e,headers=headers(1,9,1)))
                self.assertEqual(result['outcome'],'acquired');self.assert_evidence(2)
                saved=runner.import_retained(self.folder,self.folder/'sessions')
                self.assertFalse(comparisons(load(saved),{}))

    def test_three_reference_books_are_reference_only_after_import(self):
        e=event();template=e['bookmakers'][0]
        e['bookmakers']=[dict(deepcopy(template),key=book) for book in ('pinnacle','draftkings','betmgm')]
        self.assertEqual(self.run_capture(odds=httpx.Response(200,json=e,headers=headers(3,7,3)))['outcome'],'acquired')
        snapshot=load(runner.import_retained(self.folder,self.folder/'sessions'))
        self.assertEqual(len(snapshot['references']),3)
        self.assertFalse(comparisons(snapshot,{}));self.assert_evidence(2)

    def test_both_bodies_at_limit_and_zero_cost_empty_odds(self):
        e=event();e['bookmakers']=[]
        discovery=json.dumps([event()]).encode();odds=json.dumps(e).encode()
        self.assertEqual(self.run_capture(
            discovery=httpx.Response(200,content=discovery.ljust(LIMIT,b' '),headers=headers()),
            odds=httpx.Response(200,content=odds.ljust(LIMIT,b' '),headers=headers()))['outcome'],'acquired')
        self.assert_evidence(2)
        self.assertEqual(sum(len((self.folder/name/'response.json').read_bytes()) for name in ('discovery','odds')),2*LIMIT)

    def test_absent_and_outside_window(self):
        for events in ([],[dict(event(),commence_time=AT)],[dict(event(),commence_time='2027-01-01T00:00:00Z')]):
            self.setUp();result=self.run_capture(discovery=httpx.Response(200,json=events,headers=headers()))
            self.assertEqual(result['outcome'],'no_eligible_event');self.assert_evidence(1)

    def test_invalid_discovery_and_duplicates(self):
        for value in ({},[event(),event()],[dict(event(),home_team='Beta')],
                      [dict(event(),sport_key='basketball_nba')],[dict(event(),id='../bad')],
                      [dict(event(),commence_time='bad')], [None]):
            self.setUp();self.assertEqual(self.run_capture(discovery=httpx.Response(200,json=value,headers=headers()))['outcome'],'stopped')
            self.assert_evidence(1)

    def test_selection_is_receipt_relative_and_deterministic(self):
        later=dict(event(),id='later',commence_time='2026-10-02T00:00:00Z')
        tie=dict(event(),id='zzz')
        self.assertEqual(self.run_capture(discovery=httpx.Response(200,json=[later,tie,event()],headers=headers()))['outcome'],'acquired')
        self.assertEqual(json.loads((self.folder/'selection.json').read_text())['selected']['id'],'abc123')
        self.assert_evidence(2)

    def test_missing_malformed_insufficient_or_charged_discovery_quota(self):
        for quota in ({},headers(0,2),headers(1),dict(headers(),**{'x-requests-remaining':'NaN'}),dict(headers(),**{'x-requests-remaining':'-1'})):
            self.setUp();result=self.run_capture(discovery=httpx.Response(200,json=[event()],headers=quota))
            self.assertNotEqual(result['outcome'],'acquired');self.assert_evidence(1)

    def test_odds_quota_failure_retains_original_and_stops(self):
        for quota in ({},headers(4,6,4),headers(3,8,3)):
            self.setUp();result=self.run_capture(odds=httpx.Response(200,json=event(),headers=quota))
            self.assertEqual(result['outcome'],'stopped');self.assert_evidence(2)
            with self.assertRaises(ValueError):runner.import_retained(self.folder)

    def test_http_redirect_timeout_malformed_oversize_both_stages(self):
        for stage in ('discovery','odds'):
            for response in (httpx.Response(302,headers={'location':'https://example.com/?apiKey='+KEY}),
                httpx.Response(500,text='error'),httpx.ReadTimeout('secret '+KEY),
                httpx.Response(200,text='{bad',headers=headers()),
                httpx.Response(200,stream=Stream([b'x'*LIMIT,b'y']),headers=headers())):
                self.setUp();result=self.run_capture(**{stage:response})
                self.assertEqual(result['outcome'],'stopped');self.assert_evidence(1 if stage=='discovery' else 2)

    def test_partial_timeout_and_interruption_retain_bytes(self):
        for stage in ('discovery','odds'):
            for failure in (httpx.ReadTimeout('key='+KEY),asyncio.CancelledError()):
                self.setUp()
                response=httpx.Response(200,stream=Stream([b'{"partial":'],failure),headers=headers())
                if isinstance(failure,asyncio.CancelledError):
                    with self.assertRaises(asyncio.CancelledError):self.run_capture(**{stage:response})
                    self.assertEqual(json.loads((self.folder/'summary.json').read_text())['outcome'],'interrupted')
                else:self.run_capture(**{stage:response})
                self.assertEqual((self.folder/stage/'response.json').read_bytes(),b'{"partial":')
                self.assert_evidence(1 if stage=='discovery' else 2)

    def test_scope_schema_mismatch_and_extra_market_stop(self):
        for e in (dict(event(),id='different'),dict(event(),bookmakers=None),
                  event(market='h2h'),dict(event(),bookmakers=[dict(key='unknown',markets=[])])):
            self.setUp();self.assertEqual(self.run_capture(odds=httpx.Response(200,json=e,headers=headers(3,7,3)))['outcome'],'stopped')
            self.assert_evidence(2)

    def test_event_started_before_dispatch(self):
        calls=0
        def clock():
            nonlocal calls
            calls+=1
            return AT if calls<=3 else '2026-10-01T00:00:00Z'
        self.assertEqual(self.run_capture(clock=clock)['outcome'],'event_started');self.assert_evidence(1)

    def test_wall_budget_stops_second_request(self):
        ticks=iter([0,0,46])
        self.assertEqual(self.run_capture(mono=lambda:next(ticks))['outcome'],'stopped')
        self.assert_evidence(1)

    def test_credential_echo_variants_withheld(self):
        for value in (KEY, ''.join('\\u%04x'%ord(c) for c in KEY),
                      ''.join('%%%02x'%ord(c) for c in KEY),'https://example.com/?apiKey=other'):
            self.setUp();self.run_capture(discovery=httpx.Response(200,content=('"'+value+'"').encode(),headers=headers()))
            self.assertFalse((self.folder/'discovery/response.json').exists());self.assert_evidence(1)

    def test_authorization_and_candidate_fail_closed_without_dispatch(self):
        for key in ('authorized','source_sha256','spec_sha256','maximum_requests','maximum_credits','attempt_path'):
            original=self.auth[key];self.auth[key]=None
            with self.assertRaises(ValueError):self.run_capture()
            self.auth[key]=original
            self.assertFalse(self.folder.exists());self.assertEqual(self.calls,[])

    def test_request_and_outer_deadlines_are_enforced(self):
        original = asyncio.timeout
        seen = []
        def short_deadline(seconds):
            seen.append(seconds)
            return original(0.02 if seconds == 20 else 0.1)
        class Slow(Stream):
            async def __aiter__(self):
                yield b'partial'
                await asyncio.sleep(1)
        with patch('asyncio.timeout', side_effect=short_deadline):
            self.run_capture(discovery=httpx.Response(200,stream=Slow([]),headers=headers()))
        self.assertEqual(seen,[45,20]);self.assert_evidence(1)
        self.assertEqual((self.folder/'discovery/response.json').read_bytes(),b'partial')
        result=json.loads((self.folder/'discovery/result.json').read_text())
        self.assertEqual(result['error_type'],'TimeoutError')

    def test_last_moment_pregame_recheck_blocks_dispatch(self):
        calls=0
        def clock():
            nonlocal calls
            calls+=1
            return AT if calls<=5 else '2026-10-01T00:00:00Z'
        result=self.run_capture(clock=clock)
        self.assertEqual(result['outcome'],'stopped');self.assert_evidence(1)
        self.assertTrue((self.folder/'odds/attempt.json').exists())

    def test_hard_exit_keeps_attempt_closed(self):
        import subprocess
        import sys
        code = """
import asyncio, json, os, sys
from pathlib import Path
import httpx
from app.reference.odds_acquire import capture
folder=Path(sys.argv[1]);auth=json.loads(sys.argv[2])
def crash(request):os._exit(17)
asyncio.run(capture(folder,'syntheticCredential00000000000000',auth,transport=httpx.MockTransport(crash)))
"""
        process=subprocess.run([sys.executable,'-c',code,str(self.folder),json.dumps(self.auth)],capture_output=True)
        self.assertEqual(process.returncode,17)
        self.assertTrue((self.folder/'attempt.json').exists())
        self.assertTrue((self.folder/'discovery/attempt.json').exists())
        self.assertFalse((self.folder/'summary.json').exists())
        with self.assertRaises(FileExistsError):self.run_capture()
        self.assertEqual(self.calls,[])

    def test_duplicate_json_keys_rejected(self):
        self.run_capture(discovery=httpx.Response(200,content=b'[{"id":"a","id":"b"}]',headers=headers()))
        self.assert_evidence(1)

if __name__=='__main__':unittest.main()
