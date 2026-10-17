"""Authored state/race/link vectors; scalar finance isolates protocol behavior."""
import asyncio
from copy import deepcopy
from threading import Event
from time import sleep
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch
from app.comparison.current_dependencies import digest
from app.comparison.scanner_projection import Projection
from app.comparison.scanner_tickets import Tickets, TicketError, selector, MAX_CLIENTS
from app.comparison.scanner_destinations import Destinations, binding
from tests.test_sc02_projection import frame, fake
from tests.test_ev09_n01 import AT

CLIENT='authored_client_0001'


def finance(pair,instruments,inputs,*,at,policy):
    r=fake(pair,instruments,inputs)['rows'][0]
    capital=r['metrics']['deployed_capital_usd']
    return dict(categories=[{k:r[k] for k in ('category','metric','metric_basis')}],
        metrics=r['metrics'],legs=[dict(native_quantity=policy.capital_ceiling_usd)],
        funding=dict(requested_amount_usd=policy.capital_ceiling_usd,deployed_capital_usd=capital),
        states=dict(a_wins=dict(profit_usd='1')),settlement_complete=True)


def catalog(instruments):
    """Invented authored routes exercise implementation; never venue evidence."""
    routes={};markets=[]
    for index,i in enumerate(instruments):
        host={'kalshi':'kalshi.com','polymarket_us':'polymarket.us','novig':'novig.us','prophetx':'prophetx.co'}[i['venue']]
        name=f'authored_route_{index}';template=f'https://{host}/authored-fixture/{{market}}'
        retained=dict(documented_template=template,source='authored route documentation')
        routes[name]=dict(venue=i['venue'],template=template,evidence=dict(
            retained=retained,sha256=digest(retained),**{'class':'authored_fixture'}))
        url=template.format(market=str(index));exact=binding(i)
        retained=dict(url=url,binding=exact,source='authored exact market and predicate')
        markets.append(dict(binding=exact,url=url,route_id=name,parameters=dict(market=str(index)),
            evidence=dict(retained=retained,sha256=digest(retained),**{'class':'authored_fixture'})))
    return dict(version='predict-market-destinations-1',routes=routes,markets=markets)


class Lifecycle(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now=AT;self.time=0
        self.p=Projection(clock=lambda:self.now,evaluator=fake)
        self.f,self.x=frame(2);self.p.ingest(self.f,self.x);self.p.drain()
        self.selection=selector(self.p,next(iter(self.p.rows.values())))
        self.t=Tickets(self.p,allow_authored=True,clock=lambda:self.now,timer=lambda:self.time,calculate=finance,
            destinations=Destinations(catalog(self.f['instruments'][:2])))
        self.seq=0;self.ticket=None

    async def asyncTearDown(self):await self.t.close()

    async def cmd(self,op,**kw):
        self.seq+=1
        command=dict(operation=op,client_id=CLIENT,sequence=self.seq,**kw)
        if op=='select':command['selection']=kw.get('selection',self.selection)
        elif self.ticket:command['ticket_id']=self.ticket
        r=await self.t.command(command)
        self.ticket=r.get('ticket_id');return r

    def changed(self,*,key='0:0',value='9'):
        self.x=deepcopy(self.x);self.x[key]['quote']['original']['value']=value
        self.p.ingest(self.f,self.x);self.p.drain()

    async def test_selected_latest_replacement_explicit_adoption(self):
        r=await self.cmd('select');self.assertTrue(r['ready_for_manual_action'])
        old=deepcopy(r['selected_frame']);self.changed()
        r=self.t.inspect(CLIENT,self.ticket)
        self.assertEqual(r['selected_frame'],old);self.assertEqual(r['state'],'revised')
        self.assertFalse(r['ready_for_manual_action'])
        r=await self.cmd('revalidate');self.assertEqual(r['selected_frame'],old)
        self.assertIsNotNone(r['replacement_frame']);self.assertTrue(r['changes'])
        replacement=r['replacement_frame'];r=await self.cmd('adopt',replacement_frame_id=replacement['id'])
        self.assertEqual(r['selected_frame'],replacement);self.assertIsNone(r['replacement_frame'])
        self.assertTrue(r['ready_for_manual_action'])

    async def test_amount_changes_default_and_stale_replacement_cannot_adopt(self):
        r=await self.cmd('select');self.assertEqual(r['selected_frame']['result']['funding']['requested_amount_usd'],'1000')
        r=await self.cmd('revalidate',amount='500');a=r['replacement_frame']
        self.assertEqual(r['selected_frame']['result']['funding']['requested_amount_usd'],'1000')
        self.assertEqual(a['result']['funding']['requested_amount_usd'],'500')
        r=await self.cmd('revalidate',amount='250')
        with self.assertRaises(TicketError):await self.cmd('adopt',replacement_frame_id=a['id'])
        r=await self.cmd('revalidate')
        self.assertIsNone(r['replacement_frame']);self.assertEqual(r['state'],'unchanged')

    async def test_receipt_churn_preserves_original_calculation_clocks(self):
        r=await self.cmd('select');old=r['selected_frame'];calls=[]
        self.t.calculate=lambda *a,**kw:calls.append(True)
        self.now='2026-10-14T01:15:11Z'
        # AT fixture is Oct 14 01:15:10, not a source refresh.
        self.now=AT
        self.f=deepcopy(self.f);self.f['revision']='unrelated_scope'
        self.p.ingest(self.f,self.x);self.p.drain()
        r=await self.cmd('revalidate')
        self.assertEqual(r['selected_frame'],old);self.assertEqual(calls,[])
        self.assertEqual(r['state'],'unchanged')

    async def test_unrelated_event_price_change_keeps_selection_and_finance(self):
        r=await self.cmd('select');old=r['selected_frame']
        self.changed(key='1:0',value='100')
        r=await self.cmd('revalidate');self.assertEqual(r['selected_frame'],old)
        self.assertEqual(r['state'],'unchanged')

    async def test_during_calculation_price_change_rejects_late_publication(self):
        def during(*a,**kw):self.changed();return finance(*a,**kw)
        self.t.calculate=during
        r=await self.cmd('select')
        self.assertIsNone(r['selected_frame']);self.assertFalse(r['ready_for_manual_action'])
        self.assertIn('changed_during_calculation',r['reason'])
        self.t.calculate=finance;r=await self.cmd('revalidate')
        self.assertIsNotNone(r['replacement_frame'])
        r=await self.cmd('adopt',replacement_frame_id=r['replacement_frame']['id'])
        self.assertTrue(r['ready_for_manual_action'])

    async def test_fresh_sql_dependency_change_and_generation_publication_race(self):
        def fresh():
            f=deepcopy(self.f);x=deepcopy(self.x);x['0:0']['quote']['original']['value']='33';return f,x
        self.t.fresh=fresh;r=await self.cmd('select')
        self.assertIsNone(r['selected_frame']);self.assertFalse(r['ready_for_manual_action'])
        self.t.fresh=None
        def during(*a,**kw):
            self.p.stop();self.p.ingest(self.f,self.x);self.p.drain();return finance(*a,**kw)
        self.t.calculate=during
        self.selection=selector(self.p,next(iter(self.p.rows.values())))
        r=await self.cmd('select');self.assertIsNone(r['selected_frame'])

    async def test_targeted_fresh_capture_is_two_legs_outside_lock_and_unrelated_churn_survives(self):
        captures=[]
        def fresh_selected(capture):
            self.assertFalse(self.p.lock._is_owned())
            self.assertEqual(set(capture['inputs']),set(capture['pair']['legs']))
            self.assertEqual(len(capture['instruments']),2)
            captures.append(deepcopy(capture))
            self.changed(key='1:0',value='100')
            return deepcopy(self.f),deepcopy(self.x)
        self.t.fresh_selected=fresh_selected
        selected=await self.cmd('select');self.assertTrue(selected['ready_for_manual_action'])
        prior=deepcopy(selected['selected_frame'])
        checked=await self.cmd('revalidate')
        self.assertTrue(checked['ready_for_manual_action'])
        self.assertEqual(checked['selected_frame'],prior)
        self.assertEqual(len(captures),2)
        self.assertEqual(captures[0]['dependency_revision'],captures[1]['dependency_revision'])

    async def test_targeted_current_change_and_failed_proof_never_leave_ready_authority(self):
        self.t.fresh_selected=lambda capture:(deepcopy(self.f),deepcopy(self.x))
        selected=await self.cmd('select');prior=deepcopy(selected['selected_frame'])
        def unavailable(capture):raise TicketError('ticket_current_proof_unavailable')
        self.t.fresh_selected=unavailable
        checked=await self.cmd('revalidate')
        self.assertFalse(checked['ready_for_manual_action'])
        self.assertEqual(checked['selected_frame'],prior)
        self.assertFalse(self.t.inspect(CLIENT,self.ticket)['ready_for_manual_action'])
        def changed_sql(capture):
            values=deepcopy(self.x);values['0:0']['quote']['original']['value']='33'
            return deepcopy(self.f),values
        self.t.fresh_selected=changed_sql
        checked=await self.cmd('revalidate')
        self.assertFalse(checked['ready_for_manual_action'])
        self.assertIn('dependencies_changed_during_calculation',checked['reason'])
        self.t.fresh_selected=lambda capture:(deepcopy(self.f),deepcopy(self.x))
        checked=await self.cmd('revalidate')
        self.assertTrue(checked['ready_for_manual_action'])
        self.assertEqual(checked['selected_frame'],prior)

    async def test_targeted_adoption_rechecks_same_pair_and_withdraws_on_rebound(self):
        captures=[]
        def fresh_selected(capture):
            self.assertFalse(self.p.lock._is_owned())
            captures.append(capture['pair']['id'])
            return deepcopy(self.f),deepcopy(self.x)
        self.t.fresh_selected=fresh_selected
        selected=await self.cmd('select');prior=deepcopy(selected['selected_frame'])
        checked=await self.cmd('revalidate',amount='500');replacement=checked['replacement_frame']
        def rebound(capture):
            latest=deepcopy(self.f);latest['engine_binding']='changed-engine'
            return latest,deepcopy(self.x)
        self.t.fresh_selected=rebound
        with self.assertRaisesRegex(TicketError,'replacement_no_longer_current'):
            await self.cmd('adopt',replacement_frame_id=replacement['id'])
        self.assertEqual(self.t.inspect(CLIENT,self.ticket)['selected_frame'],prior)
        self.assertFalse(self.t.inspect(CLIENT,self.ticket)['ready_for_manual_action'])
        self.t.fresh_selected=fresh_selected
        adopted=await self.cmd('adopt',replacement_frame_id=replacement['id'])
        self.assertTrue(adopted['ready_for_manual_action'])
        self.assertEqual(adopted['selected_frame'],replacement)
        self.assertEqual(captures,[self.selection['pair_id']]*3)

    async def test_explicit_legacy_fresh_fixture_overrides_targeted_capture(self):
        self.t.fresh_selected=lambda capture:(_ for _ in ()).throw(AssertionError('targeted callback must not replace fixture'))
        self.t.fresh=lambda:(deepcopy(self.f),deepcopy(self.x))
        selected=await self.cmd('select')
        self.assertTrue(selected['ready_for_manual_action'])

    async def test_overlapping_selections_and_amounts_supersede_old_work(self):
        entered=Event();release=Event()
        def delayed(*a,**kw):entered.set();release.wait(1);return finance(*a,**kw)
        self.t.calculate=delayed
        one=asyncio.create_task(self.cmd('select',amount='100'))
        await asyncio.to_thread(entered.wait,1)
        self.t.calculate=finance
        two=await self.cmd('select',amount='500')
        release.set()
        with self.assertRaises(TicketError):await one
        self.assertEqual(self.t.inspect(CLIENT,two['ticket_id'])['selected_frame']['result']['funding']['requested_amount_usd'],'500')
        with self.assertRaisesRegex(TicketError,'superseded'):
            await self.t.command(dict(operation='select',client_id=CLIENT,sequence=1,selection=self.selection))

    async def test_stop_expiry_equality_restart_and_rebound_identity(self):
        r=await self.cmd('select');self.p.stop()
        self.assertEqual(self.t.inspect(CLIENT,self.ticket)['state'],'stopped')
        self.p.ingest(self.f,self.x);self.p.drain()
        self.now=self.f['pairs'][0]['expires_at']
        self.assertEqual(self.t.inspect(CLIENT,self.ticket)['state'],'expired')
        self.now=AT;self.f=deepcopy(self.f);self.f['epoch']='restarted'
        self.p.ingest(self.f,self.x);self.p.drain()
        r=self.t.inspect(CLIENT,self.ticket);self.assertEqual(r['state'],'withdrawn')
        self.assertFalse(r['ready_for_manual_action'])
        with self.assertRaises(TicketError):await self.cmd('select')

    async def test_withdrawn_contract_and_no_longer_qualifying(self):
        await self.cmd('select')
        original=self.t.calculate
        def lost(*a,**kw):
            r=original(*a,**kw);r['categories']=[];return r
        self.changed();self.t.calculate=lost
        r=await self.cmd('revalidate');self.assertEqual(r['state'],'no_longer_qualifying')
        f=deepcopy(self.f);f['instruments'][0]['predicate']['predicate']='changed_native_meaning'
        self.p.ingest(f,self.x);self.p.drain()
        self.assertEqual(self.t.inspect(CLIENT,self.ticket)['state'],'withdrawn')

    async def test_missing_destinations_and_mandatory_finance_unavailable(self):
        self.t.destinations=Destinations();r=await self.cmd('select')
        self.assertEqual(r['state'],'temporarily_unavailable');self.assertFalse(r['ready_for_manual_action'])
        self.assertTrue(all(d['url'] is None for d in r['selected_frame']['destinations']))
        self.changed()
        def broken(*a,**kw):raise ValueError('mandatory cost unknown')
        self.t.calculate=broken;r=await self.cmd('revalidate')
        self.assertEqual(r['state'],'temporarily_unavailable');self.assertFalse(r['ready_for_manual_action'])

    async def test_frame_count_bytes_ttl_churn_and_disconnect_cleanup(self):
        for i in range(100):
            await self.cmd('select',amount=str(100+i))
            self.assertLessEqual(len(self.t.clients),1)
            self.assertLessEqual(self.t._bytes(),16*1024**2)
        self.time=120;self.t.cleanup();self.assertEqual(len(self.t.clients),0)
        with self.assertRaises(TicketError):self.t.inspect(CLIENT,self.ticket)
        self.time=121;await self.cmd('select');await self.cmd('close')
        self.assertEqual(self.t.clients,{})

    async def test_capacity_queue_payload_and_disconnected_future(self):
        entered=Event();release=Event()
        def delayed(*a,**kw):entered.set();release.wait(1);return finance(*a,**kw)
        self.t.calculate=delayed;pending=[]
        for n in range(6):
            c=dict(operation='select',client_id=f'capacity_client_{n:02}',sequence=1,selection=self.selection)
            task,result=self.t.prepare(c);pending.append(task)
        await asyncio.to_thread(entered.wait,1)
        with self.assertRaisesRegex(TicketError,'calculation_capacity'):
            self.t.prepare(dict(operation='select',client_id='capacity_overflow_00',sequence=1,selection=self.selection))
        self.assertLessEqual(len(self.t.jobs),6)
        release.set()
        for future,job in pending:
            try:await asyncio.wrap_future(future)
            except TicketError:pass
        for amount in (100, '0','100001','x'):
            with self.assertRaises(ValueError):await self.cmd('select',amount=amount)
        bad=dict(self.selection);bad['rank']='1'
        with self.assertRaises(TicketError):await self.cmd('select',selection=bad)

    async def test_deadline_and_stop_during_finance_never_publish(self):
        def late(*a,**kw):
            with patch('app.comparison.scanner_tickets.DEADLINE_SECONDS',-1):
                # Emulate already exceeded deadline through the job start.
                for job in self.t.jobs.values():job['started']-=3
            return finance(*a,**kw)
        self.t.calculate=late;r=await self.cmd('select')
        self.assertFalse(r['ready_for_manual_action']);self.assertIsNone(r['selected_frame'])
        def stopped(*a,**kw):self.p.stop();return finance(*a,**kw)
        self.t.calculate=stopped;r=await self.cmd('select')
        self.assertEqual(r['state'],'stopped');self.assertIsNone(r['selected_frame'])


class Links(TestCase):
    def setUp(self):self.items=frame()[0]['instruments'];self.c=catalog(self.items)

    def test_exact_mapping_position_and_retained_provenance(self):
        r=Destinations(self.c).resolve(self.items[0]);self.assertEqual(r['state'],'verified')
        self.assertEqual(r['provenance']['evidence_class'],'authored_fixture')
        i=deepcopy(self.items[0]);i['predicate']['predicate']='not_the_same_contract'
        self.assertEqual(Destinations(self.c).resolve(i)['state'],'unavailable')
        self.assertEqual(Destinations().resolve(self.items[0])['state'],'unavailable')

    def test_unsafe_urls_rebound_routes_and_forged_evidence_rejected(self):
        for url in ('http://kalshi.com/authored-fixture/0','https://evil.test/authored-fixture/0',
                    'https://kalshi.com@evil.test/authored-fixture/0','https://kalshi.com:443/authored-fixture/0',
                    'https://kalshi.com/authored-fixture/0?token=secret','https://kalshi.com/',
                    'https://kalshi.com/authored-fixture/0#account','javascript:alert(1)'):
            c=deepcopy(self.c);r=c['routes']['authored_route_0'];r['template']=url
            r['evidence']['retained']['documented_template']=url;r['evidence']['sha256']=digest(r['evidence']['retained'])
            m=c['markets'][0];m['url']=url;m['evidence']['retained']['url']=url;m['evidence']['sha256']=digest(m['evidence']['retained'])
            with self.subTest(url=url):self.assertEqual(Destinations(c).resolve(self.items[0])['state'],'unavailable')
        c=deepcopy(self.c);c['markets'][0]['evidence']['sha256']='forged'
        self.assertEqual(Destinations(c).resolve(self.items[0])['state'],'unavailable')


class AdditionalBounds(Lifecycle):
    # Inherit fixture setup only; inherited lifecycle tests are disabled below.
    async def test_production_refuses_authored_destination_authority(self):
        self.t.allow_authored=False
        r=await self.cmd('select')
        self.assertFalse(r['ready_for_manual_action'])
        self.assertTrue(all(d['provenance']['evidence_class']=='authored_fixture' for d in r['selected_frame']['destinations']))

    async def test_capture_frame_total_and_client_limits_are_fail_closed(self):
        with patch('app.comparison.scanner_tickets.MAX_CLIENTS',0):
            with self.assertRaisesRegex(TicketError,'client_capacity'):await self.cmd('select')
        with patch('app.comparison.scanner_tickets.MAX_CAPTURE_BYTES',1):
            with self.assertRaisesRegex(TicketError,'capture_capacity'):await self.cmd('select')
        with patch('app.comparison.scanner_tickets.MAX_FRAME_BYTES',1):
            r=await self.cmd('select');self.assertIsNone(r['selected_frame'])
            self.assertIn('frame_capacity',r['reason'])
        with patch('app.comparison.scanner_tickets.MAX_BYTES',1):
            r=await self.cmd('select');self.assertIsNone(r['selected_frame'])
            self.assertFalse(r['ready_for_manual_action'])
            self.assertEqual(r['reason'],'ticket_total_capacity')

    async def test_cancelled_disconnected_http_work_cannot_publish(self):
        entered=Event();release=Event()
        def delayed(*a,**kw):entered.set();release.wait(1);return finance(*a,**kw)
        self.t.calculate=delayed;job=asyncio.create_task(self.cmd('select'))
        await asyncio.to_thread(entered.wait,1)
        job.cancel()
        with self.assertRaises(asyncio.CancelledError):await job
        release.set();await asyncio.sleep(.02)
        slot=self.t.clients[CLIENT]
        self.assertIsNone(slot['selected']);self.assertTrue(slot['cancel'].is_set())


# Keep inherited test discovery from counting the same assertions twice.
for _name in tuple(vars(Lifecycle)):
    if _name.startswith('test_'):setattr(AdditionalBounds,_name,None)
