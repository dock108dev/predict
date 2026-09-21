import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from aiohttp.test_utils import TestClient, TestServer
from app.dashboard.e5_preview import load_package, create_app, ROOT, percent
from app.opportunities.service import restore

class FilesOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch('psycopg.connect', side_effect=AssertionError('DB access forbidden')), patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
            cls.package=load_package()

    def test_all_seven_saved_cases(self):
        self.assertEqual(len(self.package['cases']),7)
        expected=[('1.73',None),('1.73','1.265'),('-0.07','-0.535'),('1.73',None),(None,None),(None,None),(None,None)]
        for c,values in zip(self.package['cases'],expected):
            self.assertEqual(tuple(s['display']['net'] for s in c['signals']),values)
            self.assertEqual(c['replay'],'Verified · byte-exact restore and recomputation')

    def test_reference_binding_and_timestamps(self):
        baseline=self.package['estimates'][4]
        self.assertEqual(baseline['percent'],'52.5')
        chosen=next(r for r in baseline['references'] if r['included'])
        self.assertEqual(chosen['receipt_id'],'synthetic-historical-download')
        self.assertEqual(chosen['read_age_seconds'],'45')
        self.assertIsNone(chosen['bookmaker_change_time'])
        self.assertTrue(any(not r['included'] for r in baseline['references']))
        self.assertIsNone(self.package['estimates'][5]['percent'])

    def test_exact_money_presentation(self):
        positive=self.package['cases'][1]['signals'][1]
        self.assertEqual(positive['display']['capital'],'0.64')
        self.assertEqual(positive['display']['return_percent'],'197.6562')
        self.assertEqual(percent('0.0000001'),'0')
        self.assertIsNone(percent(None))

    def test_unknowns_and_ranking_preserved(self):
        self.assertIsNone(self.package['ranking']['aggregate_attainable_profit_usd'])
        for group in self.package['ranking']['groups']:
            self.assertTrue(all(row['signal_class']==group['basis'][0] for row in group['rows']))
        self.assertTrue(self.package['cases'][-1]['books'][0]['stale'])
        self.assertTrue(self.package['ranking']['unavailable'])

    def test_tampered_audit_rejected(self):
        row=json.loads((ROOT/'evidence/e4/durable/invented-positive.json').read_text())
        row['payload']['signals'][1]['net_total_usd']='999'
        with self.assertRaisesRegex(ValueError,'identity mismatch'):restore(json.dumps(row))

    def test_missing_dependency_rejected_before_results(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):load_package(Path(d))

    def test_external_e3_dependency_mismatch_rejected(self):
        with patch('app.dashboard.e5_preview.as_of',return_value='changed'):
            with self.assertRaisesRegex(ValueError,'reference history'):load_package()

class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client=TestClient(TestServer(create_app()));await self.client.start_server()
    async def asyncTearDown(self):await self.client.close()
    async def test_no_collector_routes(self):
        for path in ('/api/start','/api/stop','/api/live','/api/sessions'):
            response=await self.client.post(path);self.assertEqual(response.status,404)
    async def test_validation_failure_is_closed(self):
        with patch('app.dashboard.e5_preview.load_package',side_effect=ValueError('changed dependency')):
            response=await self.client.get('/api/package');self.assertEqual(response.status,422)
            body=await response.json();self.assertNotIn('cases',body)
    async def test_page_reuses_css_and_restricts_connections(self):
        response=await self.client.get('/');self.assertEqual(response.status,200)
        self.assertIn("connect-src 'self'",response.headers['Content-Security-Policy'])
        self.assertIn('/assets/style.css',await response.text())
