import asyncio
import json
from pathlib import Path
import tempfile
import unittest
import httpx
from app.reference.odds_sample import BOOKS, SPORT_KEYS, capture, normalize

AT='2026-09-29T12:00:00Z'
KEY='test-credential-not-real'

def payload(sport='NFL'):
    return [dict(id='e1',sport_key=SPORT_KEYS[sport],commence_time=AT,
                 home_team='Home',away_team='Away',bookmakers=[
        dict(key=b,last_update=AT,markets=[dict(key='spreads',outcomes=[
            dict(name='Home',price=1.91,point=-3.5,sid='literal',bet_limit=25)])]) for b in BOOKS])]

class Parser(unittest.TestCase):
    def test_identity_line_roles_and_unknowns(self):
        rows=normalize(json.dumps(payload()).encode(),'NFL',AT)
        self.assertEqual(len(rows),5)
        self.assertEqual(rows[0]['point'],'-3.5')
        self.assertEqual(rows[0]['source_fields']['outcome']['bet_limit'],25)
        self.assertEqual([r['role'] for r in rows][2:],['bookmaker_reference']*3)
        self.assertTrue(all(r['fees'] is None and not r['executable'] for r in rows))
        self.assertTrue(all(r['purchasable_depth'] is None for r in rows))
    def test_reject_wrong_sport_or_missing_line(self):
        with self.assertRaises(ValueError): normalize(json.dumps(payload()).encode(),'NBA',AT)
        data=payload();del data[0]['bookmakers'][0]['markets'][0]['outcomes'][0]['point']
        with self.assertRaises(ValueError): normalize(json.dumps(data).encode(),'NFL',AT)
    def test_invalid_price_retained_but_not_calculated(self):
        data=payload();data[0]['bookmakers'][0]['markets'][0]['outcomes'][0]['price']=1.0
        rows=normalize(json.dumps(data).encode(),'NFL',AT)
        self.assertEqual(len(rows),5)
        self.assertIsNone(rows[0]['raw_implied_probability'])
        self.assertIsNotNone(rows[0]['price_issue'])
    def test_empty_is_empty(self):
        self.assertEqual(normalize(b'[]','NBA',AT),[])

class Capture(unittest.TestCase):
    def run_sample(self, handler):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        folder=Path(temp.name)/'live'
        results=asyncio.run(capture(folder,KEY,transport=httpx.MockTransport(handler)))
        return folder,results
    def test_budget_and_consumed_attempt(self):
        calls=[]
        def handler(req):
            calls.append(req)
            self.assertEqual(req.url.params['bookmakers'],','.join(BOOKS))
            return httpx.Response(200,json=[],headers={'x-requests-last':'3','x-requests-remaining':'482'})
        folder,results=self.run_sample(handler)
        self.assertEqual(len(calls),6)
        self.assertEqual(len(results),6)
        self.assertEqual(json.loads((folder/'summary.json').read_text())['reported_credits'],18)
        with self.assertRaises(FileExistsError):
            asyncio.run(capture(folder,KEY,transport=httpx.MockTransport(handler)))
        self.assertEqual(len(calls),6)
        self.assertFalse(any(KEY in p.read_text() for p in folder.rglob('*.json')))
    def test_failure_no_retry(self):
        folder,results=self.run_sample(lambda req:httpx.Response(401,json={'message':'invalid'}))
        self.assertEqual(len(results),1)
        self.assertEqual(results['NFL']['outcome'],'http_failure')
    def test_echo_not_retained(self):
        folder,results=self.run_sample(lambda req:httpx.Response(401,text=KEY))
        self.assertEqual(results['NFL']['outcome'],'credential_echo_not_retained')
        self.assertFalse((folder/'NFL/response.json').exists())
    def test_unknown_quota_stops(self):
        _,results=self.run_sample(lambda req:httpx.Response(200,json=[]))
        self.assertEqual(len(results),1)
    def test_transport_error_does_not_save_url(self):
        def fail(req): raise httpx.ConnectError(str(req.url))
        folder,results=self.run_sample(fail)
        self.assertEqual(results['NFL']['error_type'],'ConnectError')
        self.assertFalse(any(KEY in p.read_text() for p in folder.rglob('*.json')))

if __name__=='__main__': unittest.main()
