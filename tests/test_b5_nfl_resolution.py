"""Labeled retained-record fixtures; no sporting source or venue qualification."""
import json,unittest,tempfile
from copy import deepcopy
from pathlib import Path
from app.resolution import nfl as resolution
from app.dashboard import session_history,product_view
from app.dashboard.session_projection import SessionProjection
from tests.test_b5_nfl_first_half import fixture as half
from tests.test_b5_nfl_lines import fixture as full
from tests.test_session_projection import fixture as legacy

PRE='2026-09-16T12:00:00+00:00'
START='2026-10-04T17:00:00+00:00'
ASOF='2026-10-05T00:00:00+00:00'


def fixture(family='spread',period='first_half',line='-3',equality='predicate'):
    if family=='moneyline' and period=='full_game':
        rows=legacy();cat=rows[1]['inventory'];rows=[r for r in rows if r.get('source')!='novig'];del cat['novig']
        for c in cat.values():
            c['events']=c['events'][:1];c['markets']=c['markets'][:1]
            e=c['events'][0];e.update(participants={'Buffalo Bills':'NFL:BUF','Detroit Lions':'NFL:DET'},home='NFL:BUF',away='NFL:DET',game_id='SYNTHETIC-NFL-game-1',stage='regular_season',scheduled_start=START,original_start=START,schedule_status='scheduled',title='SYNTHETIC NFL winner resolution')
            from app.normalization.nfl_lines import event_key
            e['canonical_key']=event_key(e)
            c['selection']['ids']=[c['markets'][0]['id']]
        rows=[r for r in rows if r['type'] not in ('market_selected','prediction_book') or r.get('market',r.get('book'))['raw']['ref']['event_id'].endswith('e0')]
    else:rows=(half if period=='first_half' else full)(family=family,line=line,equality=equality)
    p=SessionProjection()
    for r in rows:p.apply(r)
    s=p.snapshot();g=next(g for g in s['games'] if set(g['sources'])=={'kalshi','polymarket_us'})
    event=rows[1]['inventory']['kalshi']['events'][0]
    return rows,s,g,event


def rec(s,g,e,kind='sporting',*,status=None,minute=0,supersedes=(),contract=None,home=14,away=14,**changes):
    status=status or ('final' if kind=='sporting' else 'settled')
    at=f'2026-10-04T21:{minute:02}:00+00:00'
    p=dict(target=resolution.target(s,g,e),source='SYNTHETIC-sporting',source_event_id='SYNTHETIC-official-event',period=g['product_identity']['period'],status=status,source_at=at,published_at=at,supersedes=list(supersedes))
    if kind=='sporting':p.update(home_score=home,away_score=away,completion='first_two_quarters_definitively_completed' if p['period']=='first_half' else 'all_regulation_and_applicable_overtime')
    else:
        contract=contract or next(k for k in g['sides'] if k.startswith('kalshi:yes:'));source=contract.split(':')[0]
        p.update(source=source,source_event_id=g['sources'][source]['event_id'],contract=contract,native={**g['sources'][source],'outcome_id':g['sides'][contract]['native_id']},payout=None if status=='pending' else dict(kind='fraction',value='0',fee_treatment='unknown'))
    p.update(changes)
    return resolution.record(kind,json.dumps({'SYNTHETIC_resolution':p}),url='https://example.invalid/SYNTHETIC-resolution',path=['SYNTHETIC_resolution'],received_at=at,evidence_mode='synthetic')


def alter(r,**changes):
    r=deepcopy(r);p=r['payload'];p.update(changes)
    return resolution.record(r['kind'],json.dumps({'SYNTHETIC_resolution':p}),url=r['raw']['url'],path=['SYNTHETIC_resolution'],received_at=r['received_at'],evidence_mode=r['evidence_mode'])


def wrappers(records):return [dict(record=r,observed_at=r['received_at'] or ASOF,cursor=i+1) for i,r in enumerate(records)]
def view(s,g,records,at=ASOF):return resolution.resolve(wrappers(records),s,g,at,dict(quantity='100',scenario='cent'))


class Linkage(unittest.TestCase):
    def test_all_six_scopes_exact_orientation_and_cashflows(self):
        for period in ['first_half','full_game']:
            for family in ['moneyline','spread','total']:
                rows,s,g,e=fixture(family,period,'20' if family=='total' else '-3')
                v=view(s,g,[rec(s,g,e,home=17,away=7)]);self.assertEqual(v['sporting']['state'],'final')
                for side in v['venues']:
                    expected=side['expected'];self.assertIsNotNone(expected['payout'],expected)
                    self.assertEqual(side['observed']['state'],'missing')
                    if expected['cashflow']:
                        cf=expected['cashflow'];self.assertIn(cf['gross_payout'],['0','100']);self.assertNotIn('realized_profit',cf)
                self.assertIn('No fills',v['limitation'])

    def test_winner_ties_both_periods(self):
        for period in ['full_game','first_half']:
            _,s,g,e=fixture('moneyline',period);v=view(s,g,[rec(s,g,e)])
            yes=next(x for x in v['venues'] if x['contract'].startswith('kalshi:yes:'))
            # Legacy full-game profile retains fractional tie; H1 inclusive native
            # YES is not-win in this inverted fixture, not a positive win contract.
            self.assertEqual(yes['expected']['payout']['value'],'0.5' if period=='full_game' else '1')

    def test_independent_integer_predicates_and_refund(self):
        for equality in ['predicate','stake_refund']:
            for period in ['first_half','full_game']:
                _,s,g,e=fixture('spread',period,'-3',equality);v=view(s,g,[rec(s,g,e,home=17,away=14)])
                for x in v['venues']:
                    side=g['sides'][x['contract']];expect='refund' if equality=='stake_refund' else '1' if side['operator'] in ('ge','le') else '0'
                    self.assertEqual(x['expected']['payout']['kind'],'stake_refund' if expect=='refund' else 'fraction')
                    if expect!='refund':self.assertEqual(x['expected']['payout']['value'],expect)
                    if expect=='refund' and x['expected']['cashflow']:
                        cf=x['expected']['cashflow'];self.assertLess(float(cf['net_cashflow']),0);self.assertNotEqual(cf['gross_payout'],'100')

    def test_full_and_half_isolation_and_later_scoring(self):
        _,s,g,e=fixture();r=rec(s,g,e);a=view(s,g,[r]);b=view(s,g,[alter(r,second_half_score=[99,0],overtime_score=[99,0])]);self.assertEqual([x['expected'] for x in a['venues']],[dict(x['expected'],sporting_record=r['id']) for x in b['venues']])
        self.assertEqual(view(s,g,[alter(r,period='full_game')])['sporting']['state'],'missing')
        self.assertEqual(view(s,g,[alter(r,home_score=None,away_score=None)])['sporting']['state'],'unsupported')

    def test_exact_native_identity_unbound(self):
        _,s,g,e=fixture();r=rec(s,g,e,'venue')
        for change in [dict(source='polymarket_us'),dict(source_event_id='other'),dict(native={}),dict(contract='other'),dict(period='full_game')]:
            v=view(s,g,[alter(r,**change)]);self.assertEqual(len(v['unbound']),1);self.assertTrue(all(x['observed']['state']=='missing' for x in v['venues']))
        for field,value in [('game_id','wrong'),('season','2025'),('stage','postseason'),('original_start','2026-10-03T17:00:00Z'),('home','NFL:DET')]:
            t=deepcopy(r['payload']['target']);t['event'][field]=value;self.assertEqual(len(view(s,g,[alter(r,target=t)])['unbound']),1)

    def test_legacy_missing_review_stays_unbound(self):
        _,s,g,e=fixture('moneyline','full_game');r=rec(s,g,e)
        for source in s['sources']:
            if source.get('catalog'):
                for event in source['catalog']['events']:event.pop('game_id',None)
        self.assertEqual(len(view(s,g,[r])['unbound']),1)

    def test_sport_final_venue_pending_and_independent_sources(self):
        _,s,g,e=fixture();pending=rec(s,g,e,'venue',status='pending');other=next(k for k in g['sides'] if k.startswith('polymarket_us:'))
        v=view(s,g,[rec(s,g,e),pending,rec(s,g,e,'venue',contract=other,status='void')]);states={x['contract']:x['observed']['state'] for x in v['venues']}
        self.assertEqual(states[pending['payload']['contract']],'pending');self.assertEqual(states[other],'void');self.assertEqual(v['sporting']['state'],'final')

    def test_conflicts_no_last_write_wins(self):
        _,s,g,e=fixture();a=rec(s,g,e);b=rec(s,g,e,minute=1,home=21);v=view(s,g,[a,b]);self.assertEqual(v['sporting']['state'],'conflicting');self.assertTrue(all(x['expected']['payout'] is None for x in v['venues']))
        c=rec(s,g,e,'venue');d=rec(s,g,e,'venue',minute=1,payout=dict(kind='fraction',value='1',fee_treatment='unknown'))
        v=view(s,g,[a,c,d]);self.assertEqual(next(x for x in v['venues'] if x['contract']==c['payload']['contract'])['observed']['state'],'conflicting')

    def test_corrections_supersede_branches_without_deleting(self):
        _,s,g,e=fixture();a=rec(s,g,e);b=rec(s,g,e,minute=1,home=21);c=rec(s,g,e,minute=2,home=10,supersedes=[a['id'],b['id']]);v=view(s,g,[c,b,a]);self.assertEqual(v['sporting']['state'],'corrected');self.assertEqual(len(v['sporting']['records']),3);self.assertEqual(sum(x['correction_state']=='superseded' for x in v['sporting']['records']),2)
        self.assertEqual(view(s,g,[a,b,c],'2026-10-04T21:01:00Z')['sporting']['state'],'conflicting')
        self.assertEqual(view(s,g,[c])['sporting']['state'],'unsupported')

    def test_unknown_conflicting_and_future_times(self):
        _,s,g,e=fixture();r=rec(s,g,e)
        for p in [dict(published_at=None),dict(source_at=None),dict(source_at='2026-10-04T21:01:00Z'),dict(published_at='2026-10-04T21:01:00Z')]:self.assertEqual(view(s,g,[alter(r,**p)])['sporting']['state'],'unsupported')
        for p in [dict(published_at='2026-10-06T00:00:00Z'),dict(source_at='2026-10-06T00:00:00Z')]:self.assertEqual(view(s,g,[alter(r,**p)])['sporting']['state'],'missing')
        x=resolution.record('sporting',r['raw']['body'],url=r['raw']['url'],path=r['raw']['path'],received_at=None,evidence_mode='synthetic');self.assertEqual(view(s,g,[x])['sporting']['state'],'unsupported')
        self.assertEqual(view(s,g,[r],PRE)['excluded_future_count'],1)
        with self.assertRaises(ValueError):view(s,g,[r],'2026-10-05T00:00:00')

    def test_exception_is_not_normal_final_or_inferred_refund(self):
        _,s,g,e=fixture()
        for status in ['cancelled','suspended','abandoned','postponed','unknown']:
            v=view(s,g,[rec(s,g,e,status=status)]);self.assertTrue(all(x['expected']['payout'] is None for x in v['venues']))
        v=view(s,g,[rec(s,g,e,'venue',status='void',payout=None)]);x=next(x for x in v['venues'] if x['observed']['selected']);self.assertIsNone(x['observed']['selected']['payload']['payout'])

    def test_report_disagreement_is_not_execution(self):
        _,s,g,e=fixture('moneyline');v=view(s,g,[rec(s,g,e),rec(s,g,e,'venue')]);x=next(x for x in v['venues'] if x['observed']['selected']);self.assertTrue(x['disagrees_with_rule']);self.assertEqual(x['observed']['state'],'settled');self.assertNotIn('realized_profit',json.dumps(v))

    def test_record_integrity_and_mode(self):
        _,s,g,e=fixture();r=rec(s,g,e);resolution.validate(r);bad=deepcopy(r);bad['payload']['home_score']=0
        with self.assertRaises(ValueError):resolution.validate(bad)
        rows=fixture()[0];p=SessionProjection()
        for row in rows:p.apply(row)
        before=p.snapshot();p.apply(dict(type='product_resolution',source='resolution',session_id=p.sid,observed_at=ASOF,resolution=r));self.assertEqual(p.snapshot()['resolutions'][0]['record'],r)
        replay=session_history.project_rows([*rows,dict(type='product_resolution',source='resolution',session_id=p.sid,observed_at=ASOF,resolution=r)],before['durable_cursor']);self.assertEqual(replay,before)

    def test_prediction_math_unchanged(self):
        rows,s,g,e=fixture();before=product_view.calculate(s,g,{});r=rec(s,g,e);after=session_history.project_rows([*rows,dict(type='product_resolution',source='resolution',session_id=s['session_id'],observed_at=ASOF,resolution=r)],s['durable_cursor']);self.assertEqual(before,product_view.calculate(after,g,{}));self.assertNotIn('resolutions',after)

class Lifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_import_stop_resolution_asof_and_exact_prediction(self):
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.multi_game_server import create_app
        from tests.b5_nfl_resolution_preview import owner
        from urllib.parse import urlencode
        with tempfile.TemporaryDirectory() as tmp:
            o=owner(Path(tmp));c=TestClient(TestServer(create_app(owner=o,sessions={})));await c.start_server();origin=str(c.make_url('')).rstrip('/')
            async def post(path,data):return await c.post(path,json=data,headers={'Origin':origin})
            async def get(path):
                r=await c.get(path);v=await r.json();self.assertEqual(r.status,200,v);return v
            try:
                self.assertEqual((await post('/api/start',{'duration':175})).status,200);s=o.session.target;g=o.session.game
                q=dict(session=s['session_id']+'~'+g['id'],hash=s['session_id'],cutoff=s['durable_cursor'],quantity='100',scenario='cent',contract=next(iter(g['sides'])))
                before=await get('/api/calculate?'+urlencode(q));res=await post('/api/resolutions',o.session.records);self.assertEqual(res.status,200,await res.text())
                self.assertEqual((await get('/api/resolution?'+urlencode(q)))['options'],[])
                await post('/api/stop',{});await o.finalizer;self.assertIsNone(o.error)
                after=await get('/api/calculate?'+urlencode(q))
                self.assertEqual(before['state'],'incomplete');self.assertEqual(after['state'],'saved')
                self.assertEqual(dict(before,state='saved'),after)
                options=(await get('/api/resolution?'+urlencode(q)))['options'];self.assertEqual(len(options),6)
                states=[]
                for option in options:
                    rq=dict(q,resolution_session=option['session'],resolution_cutoff=option['cutoff'],resolution_asof=option['as_of'])
                    v=(await get('/api/resolution?'+urlencode(rq)))['view'];states.append(v['sporting']['state'])
                    folder=o.history_paths()[option['session']];saved=session_history.resolution_history(folder,option['cutoff']);self.assertEqual(v['sporting'],resolution.resolve(saved['records'],s,g,option['as_of'])['sporting'])
                self.assertEqual(states,['pending','pending','corrected','corrected','conflicting','corrected'])
                self.assertEqual((await post('/api/resolutions',o.session.records)).status,422)
                bad=dict(q,resolution_session=options[-1]['session'],resolution_cutoff=options[-1]['cutoff']);self.assertEqual((await c.get('/api/resolution?'+urlencode(bad))).status,422)
                older=dict(bad,resolution_asof=PRE);self.assertEqual((await get('/api/resolution?'+urlencode(older)))['view']['sporting']['state'],'missing')
                with (folder/(folder.name+'.jsonl')).open('a') as out:out.write(' ')
                with self.assertRaises(ValueError):session_history.resolution_history(folder)
            finally:await c.close()

    async def test_later_session_links_without_rewriting_saved_prediction(self):
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.multi_game_server import create_app
        from tests.b5_nfl_resolution_preview import owner
        from urllib.parse import urlencode
        from hashlib import sha256
        with tempfile.TemporaryDirectory() as tmp:
            o=owner(Path(tmp));c=TestClient(TestServer(create_app(owner=o,sessions={})));await c.start_server();origin=str(c.make_url('')).rstrip('/')
            async def post(path,data):return await c.post(path,json=data,headers={'Origin':origin})
            try:
                await post('/api/start',{'duration':175});old=o.session;records=deepcopy(old.records);s=old.target;g=old.game
                await post('/api/stop',{});await o.finalizer
                files={str(p):sha256(p.read_bytes()).hexdigest() for p in old.output.rglob('*') if p.is_file()}
                await post('/api/start',{'duration':175});newid=o.session.sid
                self.assertEqual((await post('/api/resolutions',records)).status,200)
                await post('/api/stop',{});await o.finalizer
                q=dict(session=s['session_id']+'~'+g['id'],hash=s['session_id'],cutoff=s['durable_cursor'])
                response=await c.get('/api/resolution?'+urlencode(q));data=await response.json();self.assertEqual(response.status,200,data);self.assertEqual(len(data['options']),6);self.assertTrue(all(v['session']==newid for v in data['options']))
                self.assertTrue(all(sha256(Path(p).read_bytes()).hexdigest()==h for p,h in files.items()))
            finally:await c.close()

class AdditionalChecks(unittest.TestCase):
    def test_refund_cashflows_are_actual_purchase_stake_not_face_value(self):
        from decimal import Decimal
        _,s,g,e=fixture('spread','first_half','-3','stake_refund');v=view(s,g,[rec(s,g,e,home=17,away=14)])
        expected={'kalshi:no':('33','-1.55'),'kalshi:yes':('68','-1.53'),'polymarket_us:1315440':('33','-1.33')}
        for x in v['venues']:
            key=':'.join(x['contract'].split(':')[:2]);cf=x['expected']['cashflow']
            if key in expected:self.assertEqual((Decimal(cf['gross_payout']),Decimal(cf['net_cashflow'])),tuple(map(Decimal,expected[key])))
            else:self.assertIsNone(cf)

    def test_unknown_economics_and_real_target_isolation(self):
        _,s,g,e=fixture();r=rec(s,g,e)
        v=resolution.resolve(wrappers([r]),s,g,ASOF,{'scenario':'unknown'});self.assertTrue(all(x['expected']['cashflow'] is None for x in v['venues']))
        s['data_mode']='production';self.assertEqual(len(view(s,g,[r])['unbound']),1)

    def test_correction_cannot_cross_venue_or_native_side(self):
        _,s,g,e=fixture();a=rec(s,g,e,'venue');other=next(k for k in g['sides'] if k.startswith('polymarket_us:'))
        b=rec(s,g,e,'venue',minute=1,contract=other,supersedes=[a['id']]);v=view(s,g,[b,a]);self.assertEqual(next(x for x in v['venues'] if x['contract']==other)['observed']['state'],'unsupported');self.assertEqual(next(x for x in v['venues'] if x['contract']==a['payload']['contract'])['observed']['state'],'settled')

    def test_segmented_and_flat_resolution_prefixes_match(self):
        from app.collection.segmented import SegmentedJournal
        from app.collection.transport_session import ObservationJournal,reopen
        from app.dashboard.e6_live import save_json,digest
        from unittest.mock import patch
        rows,s,g,e=fixture();r=rec(s,g,e);rows=deepcopy(rows)+[dict(type='product_resolution',source='resolution',session_id=s['session_id'],observed_at=ASOF,resolution=r),dict(type='session_finished',source='session',session_id=s['session_id'],observed_at=ASOF,reason='manual_stop')]
        values=[]
        with tempfile.TemporaryDirectory() as temp,patch('app.collection.segmented.POLICY',dict(__import__('app.collection.segmented',fromlist=['POLICY']).POLICY,segment_logical=8)):
            for mode in ['flat','segmented']:
                folder=Path(temp)/mode/s['session_id'];folder.mkdir(parents=True)
                if mode=='flat':
                    j=ObservationJournal(folder/(s['session_id']+'.jsonl'))
                    for row in rows:j.save(row)
                    j.close();name=s['session_id']+'.jsonl'
                else:
                    j=SegmentedJournal(folder/'history',label='SYNTHETIC resolution prefix replay')
                    for row in rows:j.save(row)
                    j.finish(cleanup_complete=True);name='history/manifest.json'
                for name2,value in [('run-spec.json',rows[0]['spec']),('aggregate-limits.json',{}),('report.json',dict(cleanup_complete=True,outcome=dict(status='complete'))),('replay.json',dict(verified=True))]:save_json(folder/name2,value)
                names=['run-spec.json','aggregate-limits.json','report.json','replay.json',name];manifest=dict(files={n:digest(folder/n) for n in names})
                if mode=='flat':manifest['journal_chain']=reopen(folder/name)['sha256']
                save_json(folder/'manifest.json',manifest)
                hist=session_history.resolution_history(folder);values.append(hist)
                self.assertEqual(session_history.load(folder,s['durable_cursor']),dict(s,state='saved'))
            self.assertEqual(values[0],values[1])


class NumericSettlement(unittest.TestCase):
    def test_equivalent_fraction_strings_do_not_conflict(self):
        _,s,g,e=fixture('moneyline','full_game');v=view(s,g,[rec(s,g,e),rec(s,g,e,'venue',payout=dict(kind='fraction',value='0.50',fee_treatment='unknown'))]);x=next(x for x in v['venues'] if x['observed']['selected']);self.assertFalse(x['disagrees_with_rule'])


class LegacyOrientation(unittest.TestCase):
    def test_unknown_legacy_side_cannot_derive_payout(self):
        _,s,g,e=fixture('moneyline','full_game');r=rec(s,g,e);g['sides'][next(iter(g['sides']))]['participant']='unreviewed team';v=view(s,g,[r]);self.assertEqual(len(v['unbound']),1);self.assertTrue(all(x['expected']['payout'] is None for x in v['venues']))
