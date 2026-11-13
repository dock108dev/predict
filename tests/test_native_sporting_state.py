from copy import deepcopy
from datetime import datetime,timezone
from app.collection.native_sporting_state import (
    PAGE_SIZE, SportingStatePages, active_leagues, apply, handoff_leagues, newest_observations, observations,
)


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

    repeat = dict(current, received_at='2026-11-08T00:01:03Z', body_sha256='b'*64)
    same_clock_conflict = dict(repeat, state={'live':False,'ended':False})
    assert newest_observations(inv['polymarket_us']['events'], [repeat, same_clock_conflict, older], {'e':current}) == {}


def test_nhl_state_uses_shared_typed_sportradar_id_when_numeric_game_id_is_missing():
    inv, row, receipt = fixture()
    event = inv['polymarket_us']['events'][0]
    uuid = '96d98092-e332-436d-83ef-278b56d52013'
    event.update(competition='NHL', _native={'sportradarGameId': uuid})
    for item in (row, row['eventState']):
        del item['gameId']
        item['sportradarGameId'] = uuid
    value, = observations([row], league='NHL', receipt=receipt)
    assert value['sportradar_game_id'] == uuid and 'game_id' not in value
    updated, changed = apply(inv, [value])
    assert changed == {'e'} and updated['polymarket_us']['events'][0]['status']['live'] is True
    assert updated['polymarket_us']['events'][0]['sporting_state_evidence'] == value

    for wrong_id in ('no-provider-id', '00000000-0000-0000-0000-000000000000',
                     'f23afd04-bc62-4593-8648-0c54cf1ef81c'):
        invalid = deepcopy(row)
        invalid['eventState']['sportradarGameId'] = wrong_id
        assert not observations([invalid], league='NHL', receipt=receipt)
    event['_native']['sportradarGameId'] = 'f23afd04-bc62-4593-8648-0c54cf1ef81c'
    assert not apply(inv, [value])[1]


def test_admission_enrichment_keeps_newer_exact_state_from_league_route():
    from app.collection.admission_enrichment import enrich_game
    from app.comparison.game_phase import price_phase

    inv, row, receipt = fixture()
    event = inv['polymarket_us']['events'][0]
    event['_native']['eventState'] = dict(gameId=42, live=False, ended=False, updatedAt='2026-11-07T23:59:55Z')
    observed, = observations([row], league='NBA', receipt=receipt)
    changed, _ = apply(inv, [observed])
    current = changed['polymarket_us']['events'][0]
    enriched = enrich_game(dict(current, source='polymarket_us'))
    assert enriched['status']['source_evidence'] == observed
    assert enriched['_native']['eventState']['live'] is False
    quote = dict(source=dict(provider='polymarket_us'),
                 times=dict(source_at=observed['source_at'], received_at=receipt['received_at']))
    assert price_phase(enriched, quote, receipt['received_at'])['state'] == 'live'

    for wrong in (dict(observed, game_id='43'), dict(observed, source_at='2026-11-08T00:01:03Z')):
        rejected = enrich_game(dict(current, source='polymarket_us', sporting_state_evidence=wrong))
        assert rejected['status']['live'] is False
    newer = deepcopy(current)
    newer['_native']['eventState'].update(live=False, ended=True, updatedAt='2026-11-08T00:01:05Z')
    assert enrich_game(dict(newer, source='polymarket_us'))['status']['ended'] is True


def test_sporting_state_rejects_conflict_even_when_one_typed_id_agrees():
    inv, row, receipt = fixture()
    event = inv['polymarket_us']['events'][0]
    uuid = '96d98092-e332-436d-83ef-278b56d52013'
    event['_native']['sportradarGameId'] = uuid
    row['sportradarGameId'] = row['eventState']['sportradarGameId'] = uuid
    row['eventState']['gameId'] = 43
    assert not observations([row], league='NBA', receipt=receipt)

    # A supplied catalog ID must not contradict the new same-namespace proof
    # even when the other provider ID can qualify the immediate state row.
    del row['eventState']['gameId']
    row['gameId'] = 43
    value, = observations([row], league='NBA', receipt=receipt)
    assert not apply(inv, [value])[1]
    row['gameId'] = row['eventState']['gameId'] = 42
    value, = observations([row], league='NBA', receipt=receipt)
    event['_native']['sportradarGameId'] = 'f23afd04-bc62-4593-8648-0c54cf1ef81c'
    assert not apply(inv, [value])[1]


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


def test_handoff_priority_excludes_completed_and_old_catalog_events():
    inv, _, _ = fixture()
    cat = inv['polymarket_us']
    event = cat['events'][0]
    cat['events'].extend((dict(event, competition='NHL'),
        dict(event, competition='NFL', scheduled_start='2026-11-07T23:00:00Z'),
        dict(event, competition='NCAAB', status={'ended':True})))
    now = datetime(2026,11,8,0,15,tzinfo=timezone.utc)
    assert active_leagues(cat,now) == ['NBA','NCAAB','NFL','NHL']
    assert handoff_leagues(cat,now) == ['NBA','NHL']


def test_head_requests_do_not_displace_deep_fair_cursor():
    leagues = ['NBA','NCAAB','NCAAF','NFL','NHL']
    pages = SportingStatePages()
    for league in leagues:
        assert pages.next_request(leagues,[]) == (league,0,'round_robin')
        assert pages.record_page(league,0,'round_robin',PAGE_SIZE) == PAGE_SIZE
    for league in leagues:
        assert pages.next_request(leagues,['NHL']) == ('NHL',0,'priority_head')
        assert pages.record_page('NHL',0,'priority_head',PAGE_SIZE) == PAGE_SIZE
        assert pages.next_request(leagues,['NHL']) == (league,PAGE_SIZE,'round_robin')
        assert pages.record_page(league,PAGE_SIZE,'round_robin',7) == 0

    fresh = SportingStatePages()
    assert fresh.next_request(leagues,['NBA','NHL']) == ('NBA',0,'round_robin')
    assert fresh.next_request(leagues,['NBA','NHL']) == ('NCAAB',0,'round_robin')
    assert fresh.next_request(leagues,['NBA','NHL']) == ('NHL',0,'priority_head')


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


def test_sporting_state_rechecks_exact_subscription_proof_before_adoption():
    from types import SimpleNamespace
    from unittest.mock import patch
    from app.collection.current_service import CurrentService

    inv,row,receipt=fixture()
    cat=inv['polymarket_us']
    event=cat['events'][0]
    event.update(identity='resolved',sport='basketball',home='a',away='b',
                 source_participant_roles={'home':'a','away':'b'})
    cat['events'].append(dict(event,id='other'))

    def market(mid, *, unique=True, terms=True, event_id='e'):
        return dict(id=mid,event_id=event_id,market_type='moneyline',period='full_game',
            subscription_evidence_exclusion='unresolved_native_identity',subscription_slug_unique=unique,
            terms={'description':'Explicit full-game native terms'} if terms else {},
            _native=dict(id=mid,slug=mid,marketSides=[
                dict(id=mid+'-long',long=True,marketId=mid),dict(id=mid+'-short',long=False,marketId=mid)]))

    cat['markets']=[market('exact'),market('duplicate',unique=False),market('no-terms',terms=False),
                    market('untouched',event_id='other')]
    before=deepcopy(inv)
    service=SimpleNamespace(dispatch=True,database_mode=True,states={},
        sink=SimpleNamespace(reducer=SimpleNamespace(inventory=inv,generation=1)),
        row=lambda kind,venue,**fields: dict(type=kind,source=venue,**fields))
    values=observations([row],league='NBA',receipt=receipt)

    def binding(event,market,venue,**kwargs):
        assert event['id']=='e' and event['status']['live'] is True
        return dict(status='BOUND_RAW_PREDICATE',identity={'family':'moneyline'},predicate=[
            dict(native_id=side['id'],participant=event['home'],predicate='win' if side['long'] else 'not_win')
            for side in market['_native']['marketSides']])

    with patch('app.collection.v1_comparison.bind',side_effect=binding) as checked:
        operation=CurrentService.sporting_states.operation(service,'polymarket_us',values)
        envelope,_=next(operation)
    assert checked.call_count==3 and inv==before
    updated=envelope['inventory']['polymarket_us']
    assert updated['events'][0]['status']['live'] is True
    exact,duplicate,unresolved,untouched=updated['markets']
    assert exact['subscription_evidence_exclusion'] is None
    assert duplicate['subscription_evidence_exclusion']=='unresolved_native_identity'
    assert unresolved['subscription_evidence_exclusion']=='unresolved_native_identity'
    assert untouched is cat['markets'][-1]
    assert envelope['catalog_delta']['refresh']=={('polymarket_us','e',m['id']) for m in updated['markets'][:3]}


def test_full_catalog_annotation_retires_copied_gate_only_for_explicit_live():
    from tests.test_current_service import native_fixture
    from app.collection.v1_comparison import annotate
    for live in (False,True):
        cat,_=native_fixture();event=cat['events'][0];market=cat['markets'][0]
        event.update(exclusion='kickoff_reached',observed_identity_facts=[dict(status='inprogress' if live else 'scheduled')])
        market['exclusion']='event_excluded:kickoff_reached'
        annotate(cat,'kalshi',policy='manual-comparison-2')
        assert (market['exclusion'] is None)==live


def test_polymarket_hockey_total_binds_exact_team_abbreviations_and_goals():
    from app.collection.admission_enrichment import us_score
    from app.collection.public_contracts import us_type

    event=dict(competition='NHL',participants={'Hurricanes':'NHL:CAR','Kraken':'NHL:SEA'},
        _native=dict(teams=[dict(name='Hurricanes',safeName='Carolina Hurricanes',displayAbbreviation='CAR'),
                           dict(name='Kraken',safeName='Seattle Kraken',abbreviation='sea')]))
    native=dict(id='2300466',sportsMarketType='hockey_team_full_game_total',line=5.5,
        description=('This market will settle to Yes if CAR Hurricanes and SEA Kraken combine for over 5.5 goals '
                     'in the CAR Hurricanes vs SEA Kraken NHL game. Overtime is included if played. '
                     'If a shootout determines the winner, the shootout will count as one goal for the winning team.'),
        marketSides=[dict(id='over',marketId='2300466',description='Over',long=True),
                     dict(id='under',marketId='2300466',description='Under',long=False)])
    locator=us_type(native,competition='NHL')
    result=us_score(native,locator,event)
    assert result['participant']=='combined' and result['line']=='5.5'
    assert [(s['native_id'],s['operator']) for s in result['outcomes']]==[('over','gt'),('under','le')]

    assert us_score(native,dict(locator,total_scope='team'),event) is None
    assert us_score(dict(native,line=6.5),locator,event) is None
    for wrong_text in ('SEA Hurricanes', 'CAR Hurricanes score over 5.5 goals'):
        assert us_score(dict(native,description=native['description'].replace('CAR Hurricanes',wrong_text,1)),
                        locator,event) is None
    wrong=deepcopy(native)
    wrong['marketSides'][1]['description']='Over'
    assert us_score(wrong,locator,event) is None


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
