"""Shared-input card arithmetic, grouping and frozen-reopening regression."""
from copy import deepcopy
from decimal import Decimal
import tempfile
from pathlib import Path
import unittest
from app.dashboard.opportunity_feed import combine, GROUPS
from app.dashboard import product_view, session_history
from app.collection.transport_session import ObservationJournal
from tests.test_reference_integration import projection, references, add


def feed(snapshot, assumptions=None, **query):
    return combine(product_view.dashboard(snapshot,dict(query,view='ev'),assumptions or {}),
                   product_view.dashboard(snapshot,dict(query,view='arb'),{}))


class OpportunityFeed(unittest.TestCase):
    def test_direct_combined_view_uses_shared_groups_and_both_calculations(self):
        p,rows=projection();g=p.snapshot()['games'][0]
        add(p,rows,references(g));snapshot=p.snapshot()
        manual={g['id']+'~'+next(iter(g['sides'])):
                {'probability':'0','basis':'Explicit synthetic zero'}}
        for query in ({}, {'sort':'dollars'}, {'scenario':'unknown'},
                      {'competition':'NBA'}, {'search':'not-an-existing-game'}):
            with self.subTest(query=query):
                actual=product_view.dashboard(snapshot,dict(query,view='feed'),manual)
                self.assertEqual(actual,feed(snapshot,manual,**query))
        actual=product_view.dashboard(snapshot,{'view':'feed'},manual)
        self.assertTrue(any(r['calculation_view']=='arb' for r in actual))
        self.assertTrue(any(r['calculation_view']=='ev' for r in actual))
        self.assertTrue(any(r.get('probability')=='0' for r in actual))

    def test_rank_percent_not_status_dollars_or_input_order(self):
        base=dict(candidate='',probability='.5',legs=[dict(reasons=[])],venues=['kalshi'])
        rows=[dict(base,id=k,return_pct=n,status=status,profit=dollars) for k,n,status,dollars in
              [('negative','-1','Qualified','100'),('zero','0','Qualified','0'),
               ('positive','20','Conditional scenario','1'),('unknown',None,'Qualified',None),
               ('tie','20','Qualified','3')]]
        ranked=combine(rows,[])
        self.assertEqual([x['id'] for x in ranked],['positive','tie','zero','negative','unknown'])
        self.assertEqual(ranked,combine(list(reversed(rows)),[]))
        self.assertIn('unavailable_reason',ranked[-1])
        self.assertIsNone(ranked[-1]['return_pct'])

    def test_original_inputs_math_zero_negative_missing_and_no_model_core(self):
        p,rows=projection();s=p.snapshot();g=s['games'][0]
        before=feed(s)
        self.assertTrue(any(r['group']==GROUPS[4] and r['return_pct'] is not None for r in before))
        self.assertTrue(all(r['return_pct'] is None for r in before if r['group']!=GROUPS[4]))
        self.assertTrue(any(l['ask'] is not None for r in before for l in r['legs']))
        refs=references(g);add(p,rows,refs);s=p.snapshot()
        cards=feed(s)
        self.assertTrue(any(r['group']==GROUPS[0] and r['return_pct'] is not None for r in cards))
        self.assertTrue(any(r['group']==GROUPS[2] for r in cards))
        for r in cards:
            if r['return_pct'] is None:continue
            cash=sum(Decimal(l['cash']) for l in r['legs'])
            if r['group']==GROUPS[4]:
                profit=min(Decimal(v) for v in r['normal_cashflows'].values())
            else:
                leg=r['legs'][0];prob=Decimal(r['probability'])
                flows=list(leg['cashflows'].values())
                win=max(Decimal(f['net_cashflow']) for f in flows if f and f['net_cashflow'] is not None)
                lose=min(Decimal(f['net_cashflow']) for f in flows if f and f['net_cashflow'] is not None)
                # Supported fixture normal winner legs; excluded exceptional states
                # are disclosed by the shared calculation and not renormalized.
                profit=prob*win+(1-prob)*lose
            self.assertEqual(Decimal(r['profit']),profit)
            self.assertAlmostEqual(Decimal(r['return_pct']),profit/cash*100,places=20)
        key=next(r['contract'] for r in cards if r['group']==GROUPS[0] and r['return_pct'] is not None)
        leg=product_view.calculate(s,g,dict(contract=key,probability='.5'))['ev']['leg']
        win=max(Decimal(x['net_cashflow']) for x in leg['cashflows'].values() if x and x['net_cashflow'] is not None)
        lose=min(Decimal(x['net_cashflow']) for x in leg['cashflows'].values() if x and x['net_cashflow'] is not None)
        for probability,sign in [(str(-lose/(win-lose)),0),('0',-1),('1',1)]:
            result=product_view.calculate(s,g,dict(contract=key,probability=probability))['ev']
            self.assertEqual(Decimal(result['expected_profit']).compare(Decimal(0)),sign)
        missing=feed(s,scenario='unknown')
        self.assertTrue(all(r['return_pct'] is None for r in missing))
        self.assertEqual(feed(s,search='not-an-existing-game'),[])
        self.assertEqual(feed(s,competition='NBA'),[])
        self.assertEqual(feed(s,family='futures'),[])

    def test_exact_reopening_keeps_original_cutoff_and_manual_basis(self):
        p,rows=projection();g=p.snapshot()['games'][0];add(p,rows,references(g))
        old=p.snapshot();cut=old['durable_cursor'];key=next(iter(g['sides']))
        assumptions={g['id']+'~'+key:dict(probability='0',basis='Explicit synthetic zero test')}
        expected=feed(old,assumptions)
        add(p,rows,references(g,'2026-09-17T12:00:00+00:00'))
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/p.sid;folder.mkdir();j=ObservationJournal(folder/(p.sid+'.jsonl'))
            for row in rows:j.save(row)
            j.close()
            reopened=session_history.load(folder,cut)
            self.assertEqual(feed(reopened,assumptions),expected)
            self.assertEqual(reopened['references'],old['references'])
            self.assertEqual(reopened['durable_cursor'],cut)

    def test_health_and_recovery_do_not_change_saved_feed(self):
        p,rows=projection();old=p.snapshot();saved=feed(old)
        p.apply(dict(type='source_health',session_id=p.sid,observed_at=p.last,source='kalshi',state='disconnected',market_ids=['kalshi-m0'],stream_group='kalshi0'))
        self.assertTrue(any(not r['usable'] for r in feed(p.snapshot())))
        book=deepcopy(next(r for r in rows if r['type']=='prediction_book' and r['source']=='kalshi'))
        p.apply(dict(type='source_health',session_id=p.sid,observed_at=p.last,source='kalshi',state='connected',market_ids=['kalshi-m0'],stream_group='kalshi0'))
        p.apply(book)
        self.assertEqual(feed(old),saved)
        self.assertTrue(any(r['usable'] for r in feed(p.snapshot())))


class FeedHTTP(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_feed_no_model_start_stop_and_frozen_details(self):
        from aiohttp.test_utils import TestClient, TestServer
        from tests.opportunity_card_preview import TermsFixture
        from app.dashboard.multi_game_server import create_app
        from urllib.parse import urlencode
        with tempfile.TemporaryDirectory() as root:
            f=TermsFixture();owner=await f.start(root,product_mode=True,duration=30)
            client=TestClient(TestServer(create_app(owner=owner,sessions={})))
            await client.start_server()
            try:
                requests=len(f.rest_calls)
                response=await client.get('/api/dashboard?view=feed')
                self.assertEqual(response.status,200)
                data=await response.json()
                self.assertTrue(data['rows'])
                self.assertEqual(len(f.rest_calls),requests)
                self.assertTrue(any(r['group']==GROUPS[4] and r['return_pct'] is not None for r in data['rows']))
                self.assertTrue(all(r['return_pct'] is None for r in data['rows'] if r['group']!=GROUPS[4]))
                old=data['rows'][0]
                query=urlencode(dict(session=old['session'],hash=old['hash'],cutoff=old['cutoff'],contract=old['legs'][0]['id']))
                before=await (await client.get('/api/calculate?'+query)).json()
                self.assertEqual((await client.post('/api/stop',json={},headers={'Origin':str(client.make_url('/')).rstrip('/')})).status,200)
                await owner.finalizer
                after=await (await client.get('/api/calculate?'+query)).json()
                self.assertEqual(after.pop("state"),"saved")
                before.pop("state") # Lifecycle label changes; every calculation field is frozen.
                self.assertEqual(before,after)
                self.assertFalse(owner.active())
                self.assertTrue(owner.status()['start_available'])
            finally:
                await client.close();await f.close()
