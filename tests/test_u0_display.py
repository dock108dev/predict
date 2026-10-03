"""Original-input math and isolation checks for U0, with independent fractions."""
import unittest
from fractions import Fraction
from decimal import Decimal
from unittest.mock import patch
from aiohttp.test_utils import AioHTTPTestCase
from app.dashboard.u0_display import quote_display
from app.dashboard.u0_preview import create_app, sample_payload


class OriginalConversions(unittest.TestCase):
    def test_original_inputs_and_unrounded_equivalents(self):
        for value, units, cents, american in [
            ('0.48','usd_per_contract','48.0','+108'),
            ('52','cents_per_contract','52.0','-108'),
            ('2','decimal_odds','50.0','+100'),
            ('1.91','decimal_odds','52.4','-110'),
            ('2.005','decimal_odds','49.9','+101'),
            ('0.50001','usd_per_contract','50.0','-100'),
        ]:
            result=quote_display(value,units)
            self.assertTrue(result['supported'])
            self.assertEqual((result['cents'],result['american']),(cents,american))
            original=Fraction(value)
            p=1/original if units=='decimal_odds' else original/100 if units=='cents_per_contract' else original
            with __import__('decimal').localcontext() as ctx:
                ctx.prec=60
                independently=Decimal(p.numerator)/Decimal(p.denominator)
                self.assertEqual(Decimal(result['conversion']['price_approx']),independently)
            self.assertEqual(result['conversion']['original'],value)
        # Same rounded cents are different original prices, not a true tie.
        self.assertNotEqual(quote_display('.50001','usd_per_contract')['conversion']['price_approx'],
                            quote_display('.5','usd_per_contract')['conversion']['price_approx'])

    def test_boundaries_units_payout(self):
        for value in ['0','1','-1','1.01','NaN','Infinity','garbage']:
            self.assertFalse(quote_display(value,'usd_per_contract')['supported'])
        for value in ['0','1','-1','NaN']:
            self.assertFalse(quote_display(value,'decimal_odds')['supported'])
        for value in ['0','100','101']:
            self.assertFalse(quote_display(value,'cents_per_contract')['supported'])
        for units in ['probability','ticks','contracts','american_odds']:
            self.assertFalse(quote_display('.5',units)['supported'])
        self.assertFalse(quote_display('.5','usd_per_contract','2')['supported'])
        self.assertFalse(quote_display(.5,'usd_per_contract')['supported'])
        self.assertTrue(quote_display('.00001','usd_per_contract')['supported'])
        self.assertTrue(quote_display('.99999','usd_per_contract')['supported'])

    def test_fixtures_are_exact_explicit_and_distinct(self):
        payload=sample_payload(); latest=sample_payload(2)
        self.assertEqual(payload['mode'],'synthetic')
        e=payload['events'][0]
        groups=[g for g in e['groups'] if g['market']=='spread' and g['period']=='full_game']
        self.assertEqual({g['line'] for g in groups},{'-3.5','-4.5'})
        self.assertNotEqual(groups[0]['id'],groups[1]['id'])
        q=e['groups'][0]['outcomes'][0]['quotes']
        self.assertEqual(q['kalshi']['original']['value'],'0.48')
        self.assertEqual(q['novig']['original']['value'],'2.05')
        for event in payload['events']:
            for group in event['groups']:
                for o in group['outcomes']:
                    for quote in o['quotes'].values():
                        self.assertFalse(quote['provenance']['real_source'])
                        self.assertTrue(all(quote['source'][k].startswith('syn:') for k in ['native_event_id','native_market_id','native_outcome_id']))
                        self.assertFalse(quote['calculations']['ev']['eligible'])
        nq=latest['events'][0]['groups'][0]['outcomes'][0]['quotes']
        self.assertEqual(nq['novig'],q['novig'])
        self.assertEqual(nq['kalshi']['revision'],2)


class PreviewBoundary(AioHTTPTestCase):
    async def get_application(self):return create_app()
    async def test_isolated_routes_security_and_no_default_samples(self):
        response=await self.client.get('/preview/u0/state')
        self.assertEqual(response.status,200)
        self.assertEqual((await response.json())['mode'],'synthetic')
        self.assertIn("default-src 'self'",response.headers['Content-Security-Policy'])
        for headers in [{'Host':'evil.example'}, {'Origin':'http://evil.example'}, {'Sec-Fetch-Site':'cross-site'}]:
            self.assertEqual((await self.client.get('/preview/u0/state',headers=headers)).status,403)
        self.assertEqual((await self.client.get('/preview/u0/state?revision=3')).status,400)
        self.assertEqual((await self.client.post('/api/start',json={},headers={'Origin':str(self.client.make_url('/')).rstrip('/')})).status,404)
        self.assertEqual((await self.client.get('/preview/u0')).status,200)

    async def test_ordinary_app_mount_does_not_change_landing(self):
        from unittest.mock import Mock,AsyncMock
        from app.dashboard.multi_game_server import create_app as ordinary
        owner=Mock();owner.session=None;owner.active.return_value=False;owner.saved.return_value=[]
        owner.close=AsyncMock();owner.status.return_value={'active':False}
        from aiohttp.test_utils import TestServer,TestClient
        async with TestClient(TestServer(ordinary(owner=owner,sessions={}))) as client:
            response=await client.get('/')
            self.assertEqual(response.status,200)
            self.assertNotIn('U0 DESIGN PREVIEW',await response.text())
            self.assertEqual((await client.get('/preview/u0')).status,200)
            owner.start.assert_not_called()
