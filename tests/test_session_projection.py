"""fixture acceptance. Retained input is read-only; all writes are disposable."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.dashboard.session_projection import SessionProjection,identity
from app.dashboard import session_history,product_view
from app.collection.transport_session import ObservationJournal,TransportSession
from app.dashboard.e6_live import save_json,digest

ROOT=Path('evidence/multi-game/sessions/5c9b7dca-a813-4d77-80f5-0691d06068eb')


def fixture():
    saved=json.loads((ROOT/'saved-observations.json').read_text())['rows']
    games=next(r['games'] for r in saved if r['type']=='multi_game_selection')[:2]
    cats={v:dict(events=[],markets=[],selection=dict(ids=[])) for v in ('kalshi','polymarket_us','novig')}
    rows=[]; at='2026-09-16T12:00:00+00:00'
    def row(typ,source='session',**kw):
        r=dict(type=typ,source=source,session_id='b2-fixture',observed_at=at,ingress_id='fixture-'+str(len(rows)),**kw);rows.append(r);return r
    row('session_started',spec=dict(saved[0]['spec'],mode='mock'))
    for i,g in enumerate(games):
        for v in cats:
            original='polymarket_us' if v=='novig' else v;src=g['sources'][original]
            eid=v+'-e'+str(i);mid=v+'-m'+str(i)
            e=dict(id=eid,title=g['title'],scheduled_start=g['scheduled_start'],canonical_key=['fixture-event-'+str(i)],sport='american_football',competition='NFL',season='2026',participants=src['participant_mapping'],identity='resolved',exclusion=None)
            sides=[deepcopy(s) for k,s in g['sides'].items() if k.startswith(original+':')]
            m=dict(id=mid,event_id=eid,market_type='moneyline',period='full_game',status='active',exclusion=None,product_outcomes=sides)
            cats[v]['events'].append(e);cats[v]['markets'].append(m);cats[v]['selection']['ids'].append(mid)
    row('coverage_inventory',generation=1,previous_generation=None,inventory=cats)
    for i,g in enumerate(games):
        for v in cats:
            original='polymarket_us' if v=='novig' else v;src=g['sources'][original]
            key=dict(event_id=v+'-e'+str(i),market_id=v+'-m'+str(i))
            meta=next(r for r in saved if r['type']=='market_selected' and r['source']==original and r['market']['raw']['ref']['market_id']==src['market_id'])
            book=next(r for r in saved if r['type']=='prediction_book' and r['source']==original and r['book']['raw']['ref']['market_id']==src['market_id'])
            meta=deepcopy(meta['market']);meta['raw']['ref'].update(key)
            native=json.loads(meta['raw']['json_text'])
            for event in native.get('events',[]):
                if str(event.get('id'))==src['event_id']:event['id']=key['event_id']
            for market in native.get('markets',[])+[m for event in native.get('events',[]) for m in event.get('markets',[])]:
                if market.get('ticker')==src['market_id']:market['ticker']=key['market_id']
                if str(market.get('id'))==src['market_id']:market['id']=key['market_id']
            meta['raw']['json_text']=json.dumps(native);meta['raw']['kind']='synthetic'
            # Fixture identities wrap copied native terms; original files remain untouched.
            row('market_selected',v,market=meta)
            row('source_health',v,state='connected',market_ids=[key['market_id']],stream_group=v+str(i))
            b=deepcopy(book['book']);b['raw']['ref'].update(key);b['raw']['received_at']=at;b['raw']['kind']='synthetic'
            row('prediction_book',v,book=b,packets=deepcopy(book['packets']),stream_group=v+str(i))
    return rows


class Projection(unittest.TestCase):
    def projection(self):
        p=SessionProjection()
        for r in fixture():p.apply(r)
        return p

    def test_three_sources_two_events_no_fallback_and_stable_update(self):
        p=self.projection();s=p.snapshot();r=product_view.dashboard(s,{}, {})
        self.assertEqual(len(s['games']),6)
        self.assertTrue(any(x['venues']==['novig','polymarket_us'] for x in r))
        self.assertTrue(all(x['profit'] is None for x in r if 'novig' in x['venues']))
        self.assertEqual(next(x for x in s['sources'] if x['source_id']=='prophetx')['state'],'not_configured')
        before={x['id'] for x in r};b=deepcopy(fixture()[-1]);b['ingress_id']='next';p.apply(b)
        self.assertEqual(before,{x['id'] for x in product_view.dashboard(p.snapshot(),{}, {})})
        self.assertEqual(p.cursor,len(fixture())+1)
        p.apply(b,p.cursor);self.assertEqual(p.cursor,len(fixture())+1)

    def test_market_scopes_and_generation_invalidation(self):
        p=self.projection();base=deepcopy(p.inventory);e=base['kalshi']['events'][0];m=base['kalshi']['markets'][0]
        variants=[dict(m,period=x) for x in ('full_game','H1','H2','innings_1_5','period_1')]+[dict(m,line=x,market_type='spread') for x in ('-3.5','-4.5')]+[dict(m,market_type='futures',category='championship',horizon='2027')]
        keys={json.dumps(identity(e,v),sort_keys=True) for v in variants}
        keys|={json.dumps(identity(dict(e,competition='NCAAF'),m),sort_keys=True),json.dumps(identity(dict(e,season='2027'),m),sort_keys=True)}
        self.assertEqual(len(keys),10)
        e['scheduled_start']='2027-01-01T00:00:00+00:00'
        row=dict(type='coverage_inventory',session_id=p.sid,source='session',observed_at=p.last,generation=2,previous_generation=1,inventory=base)
        p.apply(row);self.assertNotIn(('kalshi',e['id'],m['id']),p.books)
        row['inventory']['kalshi']['markets'][0]['period']='H1';row.update(generation=3,previous_generation=2);p.apply(row)
        self.assertTrue(any(x['reason']=='unsupported family or period' for x in p.snapshot()['market_catalog']))

    def test_health_isolation_clock_and_resync(self):
        p=self.projection();at=p.last
        def health(state):p.apply(dict(type='source_health',session_id=p.sid,observed_at=at,source='kalshi',state=state,market_ids=['kalshi-m0'],stream_group='kalshi0'))
        health('disconnected');s=p.snapshot()
        self.assertTrue(any(x['usable'] for x in s['market_catalog'] if x['source_id']=='kalshi' and x['market_id']=='kalshi-m1'))
        health('connected');self.assertIn(('kalshi','kalshi-e0','kalshi-m0'),p.invalid)
        b=deepcopy(next(r for r in fixture() if r['type']=='prediction_book' and r['source']=='kalshi'));p.apply(b);self.assertNotIn(('kalshi','kalshi-e0','kalshi-m0'),p.invalid)
        aged=p.snapshot(mode='current',now=(datetime.fromisoformat(at)+timedelta(seconds=31)).isoformat())
        self.assertFalse(any(x.get('usable') for x in aged['market_catalog']))
        self.assertTrue(any(x.get('usable') for x in p.snapshot()['market_catalog']))

    def test_references_dates_roles_probability_and_cutoff(self):
        p=self.projection();s=p.snapshot();g=s['games'][0];key=next(k for k,x in g['sides'].items() if x['predicate']=='win')
        old=s['durable_cursor'];rows=fixture()
        for role,kind in [('model_reference','probability'),('bookmaker_reference','native_odds')]:
            r=dict(type='product_reference',session_id=p.sid,source='reference',observed_at=p.last,reference=dict(id=role,role=role,provider_id='fixture-provider',origin_id='synthetic' if role=='model_reference' else 'pinnacle',market_identity=g['product_identity'],participant=g['sides'][key]['participant'],value_kind=kind,value='0.6',conversion_method='explicit synthetic probability',model_as_of='2026-09-15T12:00:00+00:00',source_at='2026-09-15T12:00:00+00:00',delay_seconds=None,provenance='Synthetic B2 integration input'))
            rows.append(r);p.apply(r)
        s=p.snapshot();self.assertEqual(len(s['references']),2);self.assertEqual(product_view.calculate(s,g,dict(contract=key,reference='model_reference'))['ev']['reference']['role'],'model_reference')
        self.assertTrue(any(x['probability']=='0.6' and x['profit'] is not None for x in product_view.dashboard(s,{'view':'ev'},{})))
        self.assertEqual(session_history.project_rows(rows,old)['references'],[])
        self.assertTrue(all('reference' not in l['venue'] for x in product_view.dashboard(s,{}, {}) for l in x['legs']))
        self.assertEqual(len(p.snapshot(mode='current',now='2026-09-16T13:00:00+00:00')['references']),2)
        rating=deepcopy(rows[-2]);rating['reference'].update(value_kind='rating',value='12')
        p.apply(rating)
        self.assertIsNone(product_view.calculate(p.snapshot(),g,dict(contract=key,reference='model_reference'))['ev']['probability'])
        future=deepcopy(rows[-2]);future['reference']['model_as_of']='2027-01-01T00:00:00+00:00';p.apply(future)
        self.assertFalse(any(r['role']=='model_reference' for r in p.snapshot()['references']))


    def test_flat_complete_interrupted_corruption_and_exact_reopen(self):
        with tempfile.TemporaryDirectory() as t:
            f=Path(t)/'b2-fixture';f.mkdir();rows=fixture();j=ObservationJournal(f/'b2-fixture.jsonl')
            for r in rows:j.save(r)
            j.close();a=session_history.load(f);self.assertEqual(a['state'],'incomplete')
            self.assertEqual(a['durable_cursor'],self.projection().snapshot()['durable_cursor'])
            # A chain failure is rejected, not promoted to a partial success.
            with (f/'b2-fixture.jsonl').open('ab') as out:out.write(b'{broken\n')
            with self.assertRaises(ValueError):session_history.load(f)


class Durable(unittest.IsolatedAsyncioTestCase):
    async def test_no_publication_on_failed_write_and_reconcile_after_queue_failure(self):
        with tempfile.TemporaryDirectory() as t:
            s=TransportSession({},Path(t),{});s.journal=ObservationJournal(Path(t)/'j.jsonl');s.projection=SessionProjection();s.acknowledged_observer=s.projection.apply
            with patch.object(s.journal,'save',side_effect=OSError('injected')):
                with self.assertRaises(OSError):s.emit('session',dict(type='session_started',spec={}))
            self.assertEqual(s.projection.cursor,0);s.journal.close()
        with tempfile.TemporaryDirectory() as t:
            s=TransportSession({},Path(t),{});s.journal=ObservationJournal(Path(t)/'j.jsonl');s.projection=SessionProjection();s.acknowledged_observer=s.projection.apply
            with patch.object(s.queue,'put_nowait',side_effect=asyncio.QueueFull):
                with self.assertRaises(asyncio.QueueFull):s.emit('session',dict(type='session_started',spec={}))
            self.assertEqual(s.projection.cursor,1);self.assertEqual(s.counts['durably_acknowledged'],1)
            from app.collection.transport_session import reopen
            self.assertEqual(s.projection.chain,session_history.project_rows(reopen(s.journal.path)['rows'])['durable_cursor'].split('-',1)[1]);s.journal.close()

class PartialDiscovery(unittest.IsolatedAsyncioTestCase):
    async def test_initial_source_failure_retains_other_source_and_refresh_generation(self):
        from types import SimpleNamespace
        from app.collection.continuous import Discovery
        from tests.test_coverage import fixture as pages, AS_OF
        records=[]
        s=SimpleNamespace(spec={},product_session=True,profile=None,credentials={},producers={},emit=lambda v,r:records.append(r))
        d=Discovery(s)
        async def venue(v):
            if v=='polymarket_us':raise ValueError('fixture unavailable')
            d.pages.extend(p for p in pages() if p['source']==v)
        d.venue=venue
        with patch('app.collection.continuous.now',return_value=AS_OF):
            await d.discover()
            self.assertEqual(d.inventory['polymarket_us']['selection']['ids'],[])
            self.assertEqual(d.inventory['polymarket_us']['event_discovery'],'failed')
            self.assertTrue(d.inventory['kalshi']['selection']['ids'])
            with self.assertRaises(ValueError):await d.discover(force=True)
            self.assertEqual(d.published_generation,1);self.assertEqual(d.refresh['state'],'failed')
            async def recovered(v):d.pages.extend(p for p in pages() if p['source']==v)
            d.venue=recovered;await d.discover(force=True)
            self.assertEqual(d.published_generation,3)
            self.assertEqual(records[-1]['previous_generation'],1)

class FrozenIdentity(unittest.TestCase):
    def test_immutable_snapshot_removed_market_and_origin_isolation(self):
        rows=fixture();p=SessionProjection()
        for r in rows:p.apply(r)
        snap=p.snapshot();token=snap['durable_cursor'];game_ids=[g['id'] for g in snap['games']]
        snap['rows_by_game'][game_ids[0]][0]['market']['title']='external mutation'
        self.assertNotEqual(p.snapshot()['rows_by_game'][game_ids[0]][0]['market']['title'],'external mutation')
        inventory=deepcopy(p.inventory)
        inventory['novig']['origin_id']='polymarket_us'
        r=dict(type='coverage_inventory',source='session',session_id=p.sid,observed_at=p.last,generation=2,previous_generation=1,inventory=inventory)
        p.apply(r)
        self.assertEqual(len(p.snapshot()['games']),4)
        r=dict(r,generation=3,previous_generation=2,inventory={});p.apply(r);rows.append(dict(r,previous_generation=1))
        self.assertEqual(p.snapshot()['games'],[])
        self.assertEqual([g['id'] for g in session_history.project_rows(rows,token)['games']],game_ids)

class SegmentedPrefix(unittest.TestCase):
    def test_verified_interrupted_prefix_and_corrupt_segment(self):
        from app.collection.segmented import SegmentedJournal
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)/'b2-fixture';folder.mkdir()
            journal=SegmentedJournal(folder/'history',label='B2 synthetic interrupted prefix',output_root=Path(t))
            for row in fixture():journal.save(row)
            journal.finish(cleanup_complete=False)
            result=session_history.load(folder)
            self.assertEqual(result['state'],'incomplete');self.assertEqual(len(result['games']),6)
            segment=next((folder/'history').glob('segment-*.jsonl'))
            with segment.open('ab') as out:out.write(b' ')
            with self.assertRaises(ValueError):session_history.load(folder)
