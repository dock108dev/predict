from copy import deepcopy
from decimal import Decimal
import unittest
from unittest.mock import patch
from app.dashboard.price_comparison import comparisons,entry_cost,comparison_order,group_comparisons,market_url
from app.dashboard.session_projection import SessionProjection
from tests.test_session_projection import fixture
from app.collection.comparison_policy import specification
from app.collection.two_source_policy import validate
from tests.test_two_source_qualification import spec

class Comparisons(unittest.TestCase):
    def test_us_link_requires_exact_retained_event_slug(self):
        native={'event_id':'112325','native_slug':'aec-market-slug'}
        event={'id':'112325','native_aliases':{'slug':'nfl-event-slug'},'native_metadata':{'slug':'nfl-event-slug'}}
        snapshot={'data_mode':'live','sources':[{'source_id':'polymarket_us','catalog':{'events':[event]}}]}
        self.assertEqual(market_url(snapshot,'polymarket_us',native),'https://polymarket.us/event/nfl-event-slug')
        event['native_metadata']['slug']='different-event'
        self.assertIsNone(market_url(snapshot,'polymarket_us',native))
        snapshot['sources']=[]
        self.assertIsNone(market_url(snapshot,'polymarket_us',native))

    def projection(self):
        p=SessionProjection()
        for r in fixture():p.apply(r)
        return p

    def test_raw_no_probability_orientation_and_exact_quantities(self):
        rows=comparisons(self.projection().snapshot(),{})
        self.assertEqual(len(rows),4)
        for r in rows:
            self.assertIsNone(r['ev']);self.assertIsNone(r['net']);self.assertFalse(r['timing']['synchronized'])
            self.assertEqual({l['venue'] for l in r['legs']},{'kalshi','polymarket_us'})
            self.assertEqual(len(r['legs']),2)
            if r['raw_difference'] is not None:
                prices=[Decimal(l['ask']) for l in r['legs']]
                self.assertEqual(Decimal(r['raw_difference']),abs(prices[0]-prices[1]))
                if prices[0]!=prices[1]:self.assertEqual(r['lower_raw'],r['legs'][prices.index(min(prices))]['label'])
        self.assertEqual(rows,comparisons(self.projection().snapshot(),{}))
        self.assertEqual(comparisons(self.projection().snapshot(),{'competition':'NBA'}),[])

    def test_health_independent_update_and_no_false_freshness(self):
        p=self.projection();before=comparisons(p.snapshot(),{})
        row=deepcopy(next(r for r in fixture() if r['type']=='prediction_book' and r['source']=='kalshi'))
        row['observed_at']='2026-09-16T12:00:02+00:00';row['book']['raw']['received_at']=row['observed_at'];p.apply(row)
        after=comparisons(p.snapshot(),{})
        self.assertEqual([r['id'] for r in before],[r['id'] for r in after])
        for a,b in zip(before,after):
            for x,y in zip(a['legs'],b['legs']):
                if x['venue']=='polymarket_us':self.assertEqual(x['ask'],y['ask']);self.assertEqual(x['received_at'],y['received_at'])
        aged=comparisons(p.snapshot(mode='current',now='2026-09-16T12:00:20+00:00'),{})
        self.assertTrue(all(l['status']=='stale or unavailable' for r in aged for l in r['legs']))
        self.assertTrue(any(r['lower_raw'] for r in aged))

    def test_all_events_rank_by_exact_gap_with_unknown_last(self):
        rows=comparisons(self.projection().snapshot(),{})
        self.assertEqual(len({r['game_id'] for r in rows}),2)
        self.assertEqual(rows,sorted(rows,key=comparison_order))
        cases=[dict(rows[0],id=str(i),raw_difference=g) for i,g in enumerate(
            [None,'0','0.0300','0.030000000000000001','0.10'])]
        self.assertEqual([r['id'] for r in sorted(cases,key=comparison_order)],['4','3','2','1','0'])
        selected=comparisons(self.projection().snapshot(),{'search':rows[0]['game_title']})
        self.assertTrue(selected)
        self.assertTrue(all(r['game_title']==rows[0]['game_title'] for r in selected))

    def test_native_alternatives_share_card_without_combining_liquidity(self):
        row=comparisons(self.projection().snapshot(),{})[0]
        direct=deepcopy(row);alternate=deepcopy(row)
        direct['id']='direct';alternate['id']='alternate'
        for leg in direct['legs']:leg['native_outcome']['predicate']='win'
        alternate['legs'][0]['native_outcome']['predicate']='not_win'
        alternate['legs'][0]['top_size']='999'
        grouped=group_comparisons([alternate,direct])
        self.assertEqual(len(grouped),1)
        self.assertEqual(grouped[0]['legs'],direct['legs'])
        self.assertEqual(grouped[0]['alternatives'][0]['legs'][0]['top_size'],'999')
        other=deepcopy(direct);other['legs'][0]['native_identity']['event_id']='different'
        self.assertEqual(len(group_comparisons([direct,other])),2)

    def test_provisional_fees_unknown_quantity_and_missing_depth(self):
        c=dict(venue='polymarket_us',levels=[dict(price='0.5',quantity='100',provenance='fixture')],top_size='100')
        v=entry_cost(c,Decimal(100),'2026-09-27T00:00:00+00:00',{},dict(market_id='test'))
        self.assertEqual(v['lower'],'50.0');self.assertEqual(v['upper'],'51.74');self.assertIsNone(v['net'])
        self.assertEqual(v['audit']['coefficient'],'0.0695')
        for missing in (dict(c,top_size=None),dict(c,levels=None)):
            self.assertIsNone(entry_cost(missing,Decimal(100),'2026-09-27T00:00:00+00:00',{},dict(market_id='test'))['upper'])

    def test_fresh_policy_does_not_change_old_policy(self):
        old=spec();new=specification(old['start_after'],old['start_before'],old['two_source_qualification']['attempt_id'],'mock')
        validate(old);validate(new)
        self.assertEqual(old['duration'],90);self.assertEqual(new['duration'],180)
        new['duration']=181
        with self.assertRaises(ValueError):validate(new)


from tests import test_two_source_qualification as qualification_tests
from app.dashboard import session_history
from app.collection.native_approval import digest
import asyncio

class Lifecycle(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=qualification_tests.ProductTests.asyncSetUp
    asyncTearDown=qualification_tests.ProductTests.asyncTearDown
    fixture_rest=qualification_tests.ProductTests.fixture_rest

    async def test_new_policy_ordinary_start_updates_stop_exact_reopen(self):
        self.s=specification(self.s['start_after'],self.s['start_before'],self.s['two_source_qualification']['attempt_id'],'mock')
        response=await self.client.post('/api/start',json=dict(duration=180),headers={'Origin':str(self.client.make_url('/')).rstrip('/')})
        self.assertEqual(response.status,200,await response.text())
        await self.f.wait(lambda:len(self.f.active())==2)
        s=self.o.session;original=s.journal.save
        def saved(r):original(r);self.f.books+=r['type']=='prediction_book';self.f.changed.set()
        s.journal.save=saved
        await self.f.images();d=await (await self.client.get('/api/dashboard?view=feed')).json()
        self.assertTrue(d['comparisons']);before=d['comparisons']
        for c in self.f.active():
            if c['venue']=='polymarket_us':self.assertIs(c['command']['subscribe']['responsesDebounced'],False)
        await self.f.send(next(c for c in self.f.active() if c['venue']=='kalshi'))
        fresh=await (await self.client.get('/api/dashboard?view=feed')).json()
        self.assertNotEqual(d['durable_cursor'],fresh['durable_cursor'])
        frozen=s.projection.snapshot(mode='saved');expected=comparisons(frozen,{})
        await self.o.stop();await self.o.finalizer
        self.assertIsNone(self.o.error)
        reopened=session_history.load(s.output,frozen['durable_cursor'])
        self.assertEqual(expected,comparisons(reopened,{}))
        self.assertFalse(self.o.status()['start_available'])
        self.assertFalse(s.emit('session',dict(type='after_stop')))

if __name__=='__main__':unittest.main()
