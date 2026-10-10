"""Paid policy/daytime/percentage checks use only controlled local state."""
import asyncio
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from fractions import Fraction
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.collection.current_schedule import schedule
from app.collection.current_quota import QuotaLedger,QuotaStop
from app.collection.current_aggregate import AggregateScheduler,PARAMS
from app.collection.current_policy import DEFAULT,SPORTS
from app.collection.current_service import CurrentService
from app.collection.current_sink import LatestStateSink
from app.collection.local_ownership import LocalOwnership
from app.dashboard.current_state import CurrentStore
from app.dashboard.current_contract import serialize,arbitrage_pairs
from app.opportunities.percentages import normalized_pair
from app.reference.product import SPORT_KEYS
from tests.test_current_quota import WINDOW,quota
from tests.test_current_aggregate import body
from tests.current_fixture import fixture

class SlotTests(unittest.TestCase):
    def test_eastern_inclusive_exclusive_dst(self):
        for at,opened,due in [('2026-10-07T12:59:59Z',False,'2026-10-07T13:00:00+00:00'),('2026-10-07T13:00:00Z',True,'2026-10-07T13:15:00+00:00'),('2026-10-08T02:59:59Z',True,'2026-10-08T13:00:00+00:00'),('2026-10-08T03:00:00Z',False,'2026-10-08T13:00:00+00:00'),('2026-11-01T13:59:59Z',False,'2026-11-01T14:00:00+00:00'),('2026-11-01T14:00:00Z',True,'2026-11-01T14:15:00+00:00'),('2026-03-08T13:00:00Z',True,'2026-03-08T13:15:00+00:00')]:
            with self.subTest(at=at):
                s=schedule(at);self.assertEqual(s['open'],opened);self.assertEqual(s['next_due_at'],due)

class MathTests(unittest.TestCase):
    def test_independent_signed_original_math(self):
        for a,b,expected in [('0.4','0.4',Fraction(25)),('0.5','0.5',Fraction(0)),('0.6','0.6',Fraction(-50,3)),('0.50000000000000000001','0.5',(1-Fraction('1.00000000000000000001'))/Fraction('1.00000000000000000001')*100)]:
            r=normalized_pair(a,b);self.assertEqual(Fraction(int(r['numerator']),int(r['denominator'])),expected)
    def test_board_gross_without_stake_and_missing_probability(self):
        s=serialize(fixture(),allow_synthetic=True)
        q=s['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi'];r=q['calculations']['arbitrage']
        self.assertTrue(r['eligible']);self.assertIn('denominator',r['basis']);self.assertEqual(len(r['basis']['inputs']),2)
        self.assertFalse(q['calculations']['ev']['eligible']);self.assertIn('Pinnacle',q['calculations']['ev']['reason'])
    def test_arbs_names_opposing_legs_and_original_inputs(self):
        pairs=arbitrage_pairs(serialize(fixture(),allow_synthetic=True))['pairs']
        self.assertTrue(pairs)
        for pair in pairs:
            self.assertNotEqual(pair['legs'][0]['selection'],pair['legs'][1]['selection'])
            self.assertNotEqual(pair['legs'][0]['quote']['venue'],pair['legs'][1]['quote']['venue'])
            self.assertEqual(len(pair['arbitrage']['basis']['inputs']),2)
    def test_unverified_outcome_or_single_venue_withholds_pair(self):
        raw=fixture()
        for o in raw['events'][0]['groups'][0]['outcomes']:o['quotes']={k:v for k,v in o['quotes'].items() if k=='kalshi'}
        s=serialize(raw,allow_synthetic=True);q=s['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi']
        self.assertFalse(q['calculations']['arbitrage']['eligible'])

class Cycles(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.at=datetime(2026,10,3,14,tzinfo=timezone.utc)
        self.clock=lambda:self.at.isoformat()
        self.service=CurrentService(config=dict(DEFAULT,sports=list(SPORTS)),directory=root/'service',ownership=LocalOwnership(root/'owner'))
        self.store=CurrentStore(self.service);self.service.store=self.store;self.service.sink=LatestStateSink(self.store,self.service.initial_state())
        self.service.ownership.acquire(self.service.runtime_id);self.service.dispatch=True;self.service.digest='controlled';self.service.deadline=float('inf')
        self.q=QuotaLedger(root/'quota',clock=self.clock)
        self.q.transition_account(dict(account_id='controlled-paid',monthly_credits=100000));self.q.bind_window(WINDOW)
        self.calls=[];self.used=100
        test=self
        class Wire:
            bytes=0
            async def request(self,request,key):
                test.calls.append(deepcopy(request));bootstrap=request['path']=='/v4/sports'
                test.used+=0 if bootstrap else 3
                if bootstrap:raw=[dict(key=k,active=True,has_outrights=False) for k in SPORT_KEYS.values()]
                else:
                    sport=next(s for s,k in SPORT_KEYS.items() if k in request['path'])
                    raw=json.loads(body());raw[0]['sport_key']=SPORT_KEYS[sport];raw[0]['id']+='-'+sport
                return dict(status=200,headers=[('x-requests-used',str(test.used)),('x-requests-remaining',str(100000-test.used)),('x-requests-last','0' if bootstrap else '3')],body=json.dumps(raw).encode(),received_at=test.clock())
            async def close(self):pass
        self.scheduler=AggregateScheduler(self.service,ledger=self.q,transport=Wire(),key_loader=lambda:'CONTROLLED-only',window_loader=lambda:WINDOW)
        self.patch=patch('app.collection.current_aggregate.now',side_effect=self.clock);self.patch.start()
    async def asyncTearDown(self):
        self.patch.stop();await self.scheduler.close();await self.store.close();self.service.ownership.release();self.temp.cleanup()
    async def test_all_scope_each_cycle_no_tabs_no_duplicates_and_sleep_skip(self):
        await self.scheduler.step();self.assertEqual(len(self.calls),7);self.assertEqual(self.q.snapshot()['used'],118)
        self.assertEqual({r['path'] for r in self.calls[1:]},{'/v4/sports/'+k+'/odds' for k in SPORT_KEYS.values()})
        await self.scheduler.step();self.assertEqual(len(self.calls),7)
        # A restart cannot duplicate the paid scope in a consumed slot.
        other=AggregateScheduler(self.service,ledger=self.q,transport=self.scheduler.transport,key_loader=lambda:'CONTROLLED',window_loader=lambda:WINDOW)
        await other.step();self.assertEqual(len(self.calls),7)
        # Sleep across 3 slots sends one current cycle, never missed-slot bursts.
        self.at+=timedelta(minutes=47);await self.scheduler.step();self.assertEqual(len(self.calls),13)
        self.assertEqual(self.q.snapshot()['used'],136)
        self.service.dispatch=False
        with self.assertRaisesRegex(QuotaStop,'revoked'):await self.scheduler.step()
        self.assertEqual(len(self.calls),13)
    async def test_outside_window_depletion_and_preserved_account_history(self):
        self.at=self.at.replace(hour=3);await self.scheduler.step();self.assertEqual(self.calls,[])
        self.assertIn('09:00',self.service.states['novig']['reason'])
        self.at=self.at.replace(hour=14);await self.scheduler.step()
        old=deepcopy(self.q._read());self.q.transition_account(dict(account_id='next-account',monthly_credits=100000))
        new=self.q._read();self.assertEqual(new['attempts'],old['attempts']);self.assertEqual(new['next_due_at'],old['next_due_at']);self.assertEqual(new['account_transitions'][-1]['old_observation'],old['observation'])
        self.at+=timedelta(minutes=15)
        self.q.transact(lambda v,at:v.update(observation=dict(used=99950,remaining=50,last=0,at=at),next_due_at=None))
        with self.assertRaisesRegex(QuotaStop,'exhausted'):self.q.begin_cycle(self.service.ownership,[dict(path='/v4/sports/baseball_mlb/odds',params=PARAMS)])
    async def test_manual_outside_window_keeps_due_and_blocks_duplicate_or_stop(self):
        await self.scheduler.step()
        due=self.q.snapshot()['next_due_at'];count=len(self.calls)
        self.at=(self.at+timedelta(days=1)).replace(hour=3)
        await self.scheduler.refresh(['NFL'],'controlled-manual')
        self.assertEqual(len(self.calls),count+1)
        self.assertEqual(self.q.snapshot()['next_due_at'],due)
        with self.assertRaisesRegex(QuotaStop,'already_consumed'):
            await self.scheduler.refresh(['NFL'],'controlled-manual')
        self.assertEqual(len(self.calls),count+1)
        await self.scheduler.acquisition_lock.acquire()
        try:
            with self.assertRaisesRegex(QuotaStop,'in_progress'):
                await self.scheduler.refresh(['NFL'],'controlled-other')
        finally:self.scheduler.acquisition_lock.release()
        self.service.dispatch=False
        with self.assertRaisesRegex(QuotaStop,'revoked'):
            await self.scheduler.refresh(['NFL'],'controlled-stopped')
        self.assertEqual(len(self.calls),count+1)
    async def test_reference_manual_pull_retains_baseline_without_duplicate_or_due_reset(self):
        await self.scheduler.step()
        due=self.q.snapshot()['next_due_at'];count=len(self.calls)
        self.at+=timedelta(seconds=1)
        root=Path(self.temp.name)
        with patch('app.collection.current_aggregate.ROOT',root):
            await self.scheduler.refresh(['NFL'],'controlled-reference',reference=True)
        self.assertEqual(len(self.calls),count+1)
        self.assertEqual(self.calls[-1]['params']['bookmakers'],'novig,prophetx,pinnacle')
        paths=list((root/'.local/predict-odds/baselines').glob('*/NFL.json'))
        self.assertEqual(len(paths),1)
        retained=json.loads(paths[0].read_text())
        self.assertNotIn('CONTROLLED-only',json.dumps(retained))
        self.assertEqual(retained['received_at'],self.clock())
        self.assertEqual(self.q.snapshot()['next_due_at'],due)
        with self.assertRaisesRegex(QuotaStop,'already_consumed'):
            await self.scheduler.refresh(['NFL'],'controlled-reference',reference=True)
        self.assertEqual(len(self.calls),count+1)
    async def test_invalid_decimal_market_preserves_other_markets_and_opposing_pair(self):
        from app.collection.current_aggregate_admission import admit_venues,market_exclusions
        raw=json.loads(body());raw[0]['bookmakers'][0]['markets'][0]['outcomes'][0]['price']='1.0'
        wire=json.dumps(raw).encode();batches,rejected=admit_venues(wire,'MLB',self.clock())
        self.assertEqual(len(batches['novig']),4);self.assertEqual(len(batches['prophetx']),6)
        self.assertEqual(rejected,{});self.assertEqual(market_exclusions(wire),{'novig':1})
    async def test_precise_rejection_redacted_replay_independent_venue(self):
        from app.collection.current_aggregate_admission import admit_venues,diagnostic
        raw=json.loads(body());raw[0]['apiKey']='MUST-NOT-RETAIN';raw[0]['bookmakers'][0]['markets'][0]['outcomes'].pop()
        wire=json.dumps(raw).encode();batches,rejected=admit_venues(wire,'MLB',self.clock())
        self.assertEqual(len(batches['prophetx']),6);self.assertEqual(rejected['novig'],'aggregate_complete_two_way_required')
        retained=diagnostic(wire,'MLB',self.clock(),rejected);self.assertNotIn('MUST-NOT-RETAIN',json.dumps(retained))
        replay=json.dumps(retained['replay']).encode();self.assertEqual(admit_venues(replay,'MLB',self.clock())[1],rejected)

class Credentials(unittest.TestCase):
    def test_hidden_local_handoff_preserves_unrelated_settings_and_minimal_launch(self):
        from app.collection.credential_handoff import handoff,existing_key,git_executable
        from app.collection.current_aggregate import credential
        import subprocess,os
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            subprocess.run([git_executable(),'init','-q',str(root)],check=True)
            (root/'.gitignore').write_text('.env\n.local/\n')
            (root/'.env').write_text('UNRELATED=preserve\nODDS_API_KEY=CONTROLLED-old\n# preserve comment\n')
            handoff(root,'CONTROLLED-paid')
            self.assertEqual((root/'.env').read_text(),'UNRELATED=preserve\nODDS_API_KEY=CONTROLLED-paid\n# preserve comment\n')
            self.assertEqual((root/'.env').stat().st_mode&0o777,0o600)
            (root/'.local').mkdir();(root/'.local/predict-odds-account.json').write_text('{"plan":"paid"}')
            with patch('app.collection.current_aggregate.ROOT',root),patch.dict(os.environ,{'PATH':'/usr/bin:/bin','ODDS_API_KEY':'CONTROLLED-wrong'},clear=True):
                self.assertEqual(credential(),'CONTROLLED-paid')
            with patch('app.collection.current_aggregate.ROOT',root),patch('app.collection.credential_handoff.existing_key',side_effect=ValueError('controlled')):
                with self.assertRaisesRegex(QuotaStop,'paid_credential_selection_failed'):credential()
    def test_paid_headers_and_precise_failed_attempt_retention(self):
        from app.collection.current_quota import headers
        self.assertEqual(headers([('x-requests-used','0'),('x-requests-remaining','100000'),('x-requests-last','0')],100000)['remaining'],100000)
        with self.assertRaises(QuotaStop):headers([('x-requests-used','0'),('x-requests-remaining','500'),('x-requests-last','0')],100000)

class Overlap(unittest.TestCase):
    def test_evidenced_provider_roles_and_unique_occurrence_required(self):
        from app.collection.current_overlap import associate
        from app.collection.current_aggregate_admission import admit
        from app.comparison.event_links import EventLinks,ProviderEdge
        rows=admit(body(),'MLB','2026-10-07T14:00:00Z')
        # Explicit controlled canonical identities; provider-slot fallbacks withheld.
        for r in rows:
            for role in ('home','away'):r['event'][role]='CONTROLLED-'+role
            r['event']['participants']={'CONTROLLED HOME':'CONTROLLED-home','CONTROLLED AWAY':'CONTROLLED-away'}
        r=rows[0];native=deepcopy(r);native['result_policy']='predict-direct-win-1:normal-full-game-win';native['market_identity']['event']=['CONTROLLED-native-occurrence'];native['event_scope']=None
        native['event']['game_id']='CONTROLLED-occurrence'
        native['quote']['source'].update(provider='kalshi',native_event_id='CONTROLLED-native-event')
        at=datetime(2026,10,7,14,tzinfo=timezone.utc)
        def edge(provider,native_id):
            return ProviderEdge(provider,native_id,'CONTROLLED-occurrence','MLB','CONTROLLED-home','CONTROLLED-away','a'*64,
                '2026-10-06T00:00:00Z','2026-10-06T00:00:00Z','2026-10-11T00:00:00Z','authored','manual_review')
        links=EventLinks([edge('the_odds_api','CONTROLLED-event'),edge('kalshi','CONTROLLED-native-event')])
        self.assertIn('event_scope',associate([native],rows,links=EventLinks(),clock=at)[0])
        joined=associate([native],rows,links=links,clock=at);self.assertNotIn('event_scope',joined[0]);self.assertIn('comparison-evidenced-overlap-2',joined[0]['orientation_evidence'][-1])
        changed=deepcopy(native);changed['event']['scheduled_start']='2026-10-10T12:01:00Z'
        self.assertNotIn('event_scope',associate([changed],rows,links=links,clock=at)[0])
        changed=deepcopy(native);changed['market_identity']['event']=['CONTROLLED-other-occurrence']
        self.assertIn('event_scope',associate([native,changed],rows,links=links,clock=at)[0])
        changed=deepcopy(native);changed['event']['home'],changed['event']['away']=changed['event']['away'],changed['event']['home']
        self.assertIn('event_scope',associate([changed],rows,links=links,clock=at)[0])

class SelectionRepair(unittest.TestCase):
    def test_only_returned_free_wrong_account_bootstrap_can_be_resolved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);owner=LocalOwnership(root/'owner');owner.acquire('controlled')
            try:
                q=QuotaLedger(root/'quota',clock=lambda:'2026-10-03T14:00:00+00:00')
                q.transition_account(dict(account_id='controlled-paid',monthly_credits=100000));q.bind_window(WINDOW)
                aid=q.reserve(owner,'controlled',dict(path='/v4/sports',params={}),0,bootstrap=True);q.dispatched(aid,owner);q.reconcile(aid,quota(254,0))
                before=q._read();self.assertEqual(before['attempts'][aid]['quota_headers'],[list(x) for x in quota(254,0)])
                q.repair_credential_selection(dict(reason='controlled verified credential path defect'))
                after=q._read();self.assertEqual(after['attempts'][aid]['charged'],0);self.assertEqual(after['next_due_at'],before['next_due_at']);self.assertIsNone(after['observation'])
                self.assertEqual(after['attempts'][aid]['quota_failure'],before['attempts'][aid]['quota_failure'])
                # Paid uncertain work cannot enter this narrow repair path.
                q.transact(lambda v,at:v.update(pause='quota_ceiling_or_headers_contradictory',observation=dict(used=0,remaining=100000,last=0,at=at)))
                q.transact(lambda v,at:v['attempts'][aid].update(state='uncertain',bootstrap=False,cost=3))
                with self.assertRaisesRegex(QuotaStop,'not_a_free'):q.repair_credential_selection({})
            finally:owner.release()
