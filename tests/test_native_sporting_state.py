from copy import deepcopy
from datetime import datetime,timezone
from app.collection.native_sporting_state import apply,observations,active_leagues,newest_observations


def fixture():
    event=dict(id='e',competition='NBA',scheduled_start='2026-11-08T00:00:00Z',exclusion='kickoff_reached',
        status=dict(live=False,ended=False),_native=dict(gameId=42),participants={'A':'a','B':'b'})
    receipt=dict(received_at='2026-11-08T00:01:01Z',body_sha256='a'*64,path='/v2/leagues/nba/events')
    row=dict(id='e',gameId=42,startTime=event['scheduled_start'],active=True,closed=False,
        eventState=dict(eventId='e',gameId=42,live=True,ended=False,updatedAt='2026-11-08T00:01:00Z'))
    inventory={'polymarket_us':dict(events=[event],markets=[dict(id='m',event_id='e',sides=['unchanged'])])}
    return inventory,row,receipt


def test_state_patch_preserves_material_and_rejects_identity_clock_conflicts():
    inv,row,receipt=fixture();old=deepcopy(inv)
    values=observations([row],league='NBA',receipt=receipt)
    changed,ids=apply(inv,values)
    assert ids=={'e'} and inv==old
    e=changed['polymarket_us']['events'][0]
    assert e['exclusion'] is None and e['status']['live']
    assert e['_native'] is inv['polymarket_us']['events'][0]['_native']
    assert changed['polymarket_us']['markets'][0] is inv['polymarket_us']['markets'][0]
    assert e['status']['source_evidence']['body_sha256']=='a'*64
    for field,value in [('game_id','43'),('start_at','2026-11-09T00:00:00Z'),('league','NHL')]:
        assert apply(inv,[dict(values[0],**{field:value})])[1]==set()
    for patch in ({'gameId':43},{'eventId':'other'},{'updatedAt':'2026-11-08T00:02:00Z'},{'live':'true'}):
        invalid=deepcopy(row);invalid['eventState'].update(patch)
        assert observations([invalid],league='NBA',receipt=receipt)==[]


def test_bad_identity_and_out_of_order_page_do_not_advance_sporting_clock():
    inv, row, receipt = fixture()
    current, = observations([None, row], league='NBA', receipt=receipt)
    wrong_game = dict(current, game_id='43', source_at='2026-11-08T00:01:01Z')
    older = dict(current, source_at='2026-11-08T00:00:59Z', state={'live': False, 'ended': False})
    assert newest_observations(inv['polymarket_us']['events'], [wrong_game, current, older], {}) == {'e': current}
    updated, changed = apply(inv, [current, older])
    assert changed == {'e'} and updated['polymarket_us']['events'][0]['status']['live'] is True


def test_final_unknown_and_live_transitions_do_not_refresh_old_quote_clocks():
    from app.comparison.game_phase import price_phase
    inv,row,receipt=fixture();values=observations([row],league='NBA',receipt=receipt)
    inv,_=apply(inv,values);event=inv['polymarket_us']['events'][0]
    q=dict(source=dict(provider='polymarket_us'),times=dict(source_at='2026-11-08T00:00:30Z',received_at='2026-11-08T00:00:31Z'))
    assert price_phase(event,q,receipt['received_at'])['reason']=='live_price_expired'
    for live,ended,expected in [(False,False,'unknown'),(True,False,'live'),(False,True,'final')]:
        value=dict(values[0],state=dict(live=live,ended=ended))
        inv,_=apply(inv,[value]);e=inv['polymarket_us']['events'][0]
        q['times']=dict(source_at='2026-11-08T00:01:00Z',received_at='2026-11-08T00:01:01Z')
        assert price_phase(e,q,receipt['received_at'])['state']==expected
    older=dict(values[0],source_at='2026-11-08T00:00:59Z')
    assert apply(inv,[older])[1]==set()


def test_same_state_confirmation_is_noop_but_slow_catalog_keeps_newer_proof():
    inv,row,receipt=fixture();values=observations([row],league='NBA',receipt=receipt)
    live,_=apply(inv,values)
    assert apply(live,values)[0] is live
    restored=deepcopy(inv);restored['polymarket_us']['events'][0]['status']={'live':True,'ended':False,'active':True,'closed':False}
    merged,_=apply(restored,values,retain_evidence=True)
    assert merged['polymarket_us']['events'][0]['sporting_state_evidence']==values[0]
    restored['polymarket_us']['events'][0]['_native']['eventState']={'updatedAt':'2026-11-08T00:02:00Z'}
    assert apply(restored,values,retain_evidence=True)[1]==set()


def test_refresh_scope_is_near_start_and_does_not_infer_live():
    inv,_,_=fixture();cat=inv['polymarket_us'];before=deepcopy(cat)
    assert active_leagues(cat,datetime(2026,11,8,0,1,tzinfo=timezone.utc))==['NBA']
    assert active_leagues(cat,datetime(2026,11,10,tzinfo=timezone.utc))==[]
    assert cat==before


def test_same_live_state_retires_only_copied_kickoff_market_gate():
    inv,row,receipt=fixture();values=observations([row],league='NBA',receipt=receipt)
    event=inv['polymarket_us']['events'][0];event.update(status=values[0]['state'],exclusion=None)
    markets=inv['polymarket_us']['markets'];markets[0]['exclusion']='event_excluded:kickoff_reached'
    markets.append(dict(id='blocked',event_id='e',exclusion='conflicting_query_identity'))
    updated,changed=apply(inv,values)
    assert changed=={'e'}
    assert updated['polymarket_us']['markets'][0]['exclusion'] is None
    assert updated['polymarket_us']['markets'][1]['exclusion']=='conflicting_query_identity'
    assert markets[0]['exclusion']=='event_excluded:kickoff_reached'


def test_full_catalog_annotation_retires_copied_gate_only_for_explicit_live():
    from tests.test_current_service import native_fixture
    from app.collection.v1_comparison import annotate
    for live in (False,True):
        cat,_=native_fixture();event=cat['events'][0];market=cat['markets'][0]
        event.update(exclusion='kickoff_reached',observed_identity_facts=[dict(status='inprogress' if live else 'scheduled')])
        market['exclusion']='event_excluded:kickoff_reached'
        annotate(cat,'kalshi',policy='manual-comparison-2')
        assert (market['exclusion'] is None)==live


def test_worker_state_route_uses_owned_http_and_does_not_enter_catalog_pages():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch,AsyncMock
    from app.collection.current_native import NativeWorker
    from app.collection.current_policy import DEFAULT
    inv,row,receipt=fixture()
    async def run():
        service=SimpleNamespace(config=DEFAULT,dispatch=True,database_mode=True,sporting_states=lambda *args:None)
        worker=NativeWorker(service,'polymarket_us');worker.catalog=inv['polymarket_us']
        worker.guard=lambda:None;calls=[]
        async def get(path,params,field):
            assert worker.http_lock.locked() and worker.sporting_http
            calls.append((path,params,field));worker.sporting_receipt=receipt
            return [row]
        worker._get=get
        async def stop(_):worker.closed=True
        with patch('app.collection.native_sporting_state.active_leagues',return_value=['NBA']), \
             patch('app.collection.native_sporting_state.active_events',return_value=inv['polymarket_us']['events']), \
             patch('app.collection.current_native.call',new_callable=AsyncMock) as adopted, \
             patch('app.collection.current_native.asyncio.sleep',side_effect=stop):
            await worker.sporting_state_loop()
        assert len(calls)==1 and calls[0][0]=='/v2/leagues/nba/events'
        assert adopted.await_count==1 and not worker.sporting_http and not worker.pages
        assert worker.metrics['sporting_state_refresh']['next_offset']==0
        entered=asyncio.Event();released=asyncio.Event()
        async def owned():
            try:entered.set();await asyncio.Event().wait()
            finally:released.set()
        worker.sporting_task=asyncio.create_task(owned());await entered.wait()
        await asyncio.gather(worker.stop_sporting_states(),worker.stop_sporting_states())
        assert released.is_set() and worker.sporting_task is None
    asyncio.run(run())
