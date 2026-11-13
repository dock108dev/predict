import asyncio
from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace

import httpx
import pytest

from app.collection.novig_v3_public import NovigPublicDiscovery
from app.comparison.sgo_native_binding import bind, capture_catalog, event_link_id, pregame_fee, settlement_profile
from app.storage.store import stamp

AT = '2026-11-12T16:54:00+00:00'
START = '2026-11-12T17:00:00+00:00'
SGO = 'sgo-event'
EVENT = '01a1cba2-f2a0-7272-a837-d00172656341'
MARKET = '01a1cba2-f314-7381-bc87-29b0261a6c5d'
AWAY = '01a1cba2-f314-7381-bc87-29df87f5669e'
HOME = '01a1cba2-f314-7381-bc87-29cc27704468'
EVENT_PATH = '/v3/public/catalog/events/' + EVENT
MARKETS_PATH = '/v3/public/catalog/markets'


def receipt(path, at=AT, age=None):
    return dict(path=path, sha256='1'*64, observed_at=at, age=age)


def fixture():
    kickoff = int(stamp(START).timestamp() * 1000)
    official_event = dict(eventId=EVENT, league='NHL', startsTs=kickoff, status='OPEN_PREGAME')
    official_market = dict(marketId=MARKET, eventId=EVENT, marketType='SPREAD', startsTs=kickoff,
        status='OPEN', strike='1.5', voids='FMV', fee=dict(charged='WHEN_LIVE', coefficient='0.06', makerCredit='0.25'),
        outcomes=[dict(outcomeId=AWAY, name='CAR -1.5', status='TBD', subjectId='7e2a2d8d-3048-4d42-a06d-f008b35dabfc'),
                  dict(outcomeId=HOME, name='SEA +1.5', status='TBD', subjectId='84887622-78ea-42ce-bb95-7d229d648dd6')])
    record = dict(quote=dict(venue='novig', state='available',
        original=dict(value='-135', units='american_odds', payout='1', payout_units='USD'),
        source=dict(provider='sportsgameodds', native_event_id=SGO,
            native_outcome_id='points-home-game-sp-home', native_line='1.5')),
        event=dict(competition='NHL', scheduled_start=START, home='NHL:SEA', away='NHL:CAR',
            shared_provider_ids=dict(novig_event=EVENT)),
        market_identity=dict(family='spread', period='full_game', scheduled_start=START),
        comparison_source_metadata=dict(provider_phase='pregame', bookmaker_market_link=dict(
            host='novig.com', path='/events/'+HOME+'/sportsgameodds')),
        selection=dict(predicate='cover', participant='NHL:SEA', signed_line='1.5'))
    return record, official_event, official_market


def witness(event, market, at=AT):
    return dict(capture_catalog(SGO, EVENT, event, receipt(EVENT_PATH,at),
        [(dict(items=[market]), receipt(MARKETS_PATH,at))], {HOME, AWAY}), revision='current')


def test_public_catalog_binds_exact_quote_and_pregame_terms_without_claiming_execution():
    row, event, market = fixture()
    initial = deepcopy(row)
    result = bind(row,witness(event,market),at=AT)
    assert row == initial
    assert result['available'] and result['phase_verified']
    assert (result['event_id'],result['market_id'],result['outcome_id'],result['opposite_outcome_id']) == (EVENT,MARKET,HOME,AWAY)
    assert result['settlement']['scope'] == 'completed_full_game'
    assert result['settlement']['shootout'] == 'official_final_score'
    assert result['settlement']['void'] == 'fair_market_value' and result['settlement']['void_payout'] is None
    assert result['current_until'] == START
    fee = pregame_fee(result)
    assert fee['available'] and fee['trade_fee_usd'] == '0'
    assert fee['evidence']['native_binding_revision'] == 'current'
    result['settlement'] = dict(available=False)
    assert pregame_fee(result)['trade_fee_usd'] == '0'


@pytest.mark.parametrize('alter,reason', [
    ('opposite', 'sgo_native_selected_side_conflict'),
    ('line', 'sgo_native_line_conflict'),
    ('start', 'sgo_native_market_scope_conflict'),
    ('host', 'sgo_native_outcome_link_unavailable'),
    ('expiry', 'sgo_native_catalog_expired'),
])
def test_public_catalog_binding_fails_closed_when_exact_inputs_disagree(alter, reason):
    row, event, market = fixture()
    at = AT
    if alter == 'opposite':
        row['comparison_source_metadata']['bookmaker_market_link']['path'] = '/events/'+AWAY+'/sportsgameodds'
    elif alter == 'line':
        market['strike'] = '2.5'
    elif alter == 'start':
        event['startsTs'] += 300000
    elif alter == 'host':
        row['comparison_source_metadata']['bookmaker_market_link']['host'] = 'novig.com.invalid'
    elif alter == 'expiry':
        at = '2026-11-12T17:10:00+00:00'
    result = bind(row,witness(event,market),at=at)
    assert result == dict(available=False, reason=reason)


def test_official_live_contract_identity_carries_no_signed_fee_evidence():
    row, event, market = fixture()
    live = '2026-11-12T17:01:00+00:00'
    event['status'] = 'OPEN_INGAME'
    proof = witness(event,market,live)
    stale_phase = bind(row,proof,at=live)
    assert stale_phase['available'] and not stale_phase['phase_verified']
    assert pregame_fee(stale_phase)['reason'] == 'sgo_native_catalog_phase_or_quote_unverified'
    row['comparison_source_metadata']['provider_phase'] = 'live'
    current = bind(row,proof,at=live)
    assert current['available'] and current['phase_verified']
    assert pregame_fee(current)['reason'] == 'sgo_native_live_fee_requires_signed_book'


def test_provider_age_shortens_proof_and_cross_event_outcomes_are_rejected():
    _, event, market = fixture()
    saved = capture_catalog(SGO,EVENT,event,receipt(EVENT_PATH,age='320'),
                            [(dict(items=[market]), receipt(MARKETS_PATH))], {HOME})
    assert saved['expires_at'] == '2026-11-12T17:03:40+00:00'
    with pytest.raises(ValueError, match='membership_conflict'):
        capture_catalog(SGO,EVENT,event,receipt(EVENT_PATH),
                        [(dict(items=[market,dict(market, marketId=EVENT)]),receipt(MARKETS_PATH))],{HOME})


def test_immutable_subject_roles_from_typed_spread_verify_unresolved_college_winner():
    row, event, spread = fixture()
    event['league'] = row['event']['competition'] = 'NCAAB'
    row['event'].update(home='sportsgameodds:NCAAB:sgo-event:home',away='sportsgameodds:NCAAB:sgo-event:away')
    row['selection']['participant'] = row['event']['home']
    for outcome,name in zip(spread['outcomes'],('College A -1.5','College B +1.5')):
        outcome['name'] = name
    winner_market, winner_home, winner_away = (f'0300000{n}-0000-0000-0000-000000000000' for n in (0,1,2))
    winner = dict(spread, marketId=winner_market, marketType='MONEY', strike=None,
        outcomes=[dict(spread['outcomes'][0],outcomeId=winner_away,name='College A'),
                  dict(spread['outcomes'][1],outcomeId=winner_home,name='College B')])
    links = {HOME: [dict(odd_id='points-home-game-sp-home',opposing_odd_id='points-away-game-sp-away',
                          side='home',line='1.5',market='spread',period='game')],
             AWAY: [dict(odd_id='points-away-game-sp-away',opposing_odd_id='points-home-game-sp-home',
                          side='away',line='-1.5',market='spread',period='game')],
             winner_home: [], winner_away: []}

    def proof(markets, original_links=links):
        return dict(capture_catalog(SGO, EVENT, event, receipt(EVENT_PATH),
            [(dict(items=markets), receipt(MARKETS_PATH))], original_links, sgo_frame='2'*64), revision='current')

    verified = proof([winner,spread])
    assert verified['subject_roles']['home'] == spread['outcomes'][1]['subjectId']
    assert bind(row,verified,at=AT)['available']
    row['market_identity']['family'] = 'moneyline'
    row['quote']['source'].update(native_line=None,native_outcome_id='points-home-game-ml-home')
    row['selection'].update(signed_line=None,predicate='win')
    row['comparison_source_metadata']['bookmaker_market_link']['path'] = '/events/'+winner_home+'/sportsgameodds'
    result = bind(row,verified,at=AT)
    assert result['available'] and result['market_id'] == winner_market
    assert result['subject_role_anchors'][0]['market_id'] == MARKET
    assert result['settlement']['rule_id'] == 'NCAAMWIN'
    assert result['settlement']['equality'] == 'void_without_official_winner'
    assert not bind(row,proof([winner,spread],dict(links, **{AWAY: []})),at=AT)['available']

    conflict_market, conflict_home, conflict_away = (f'0400000{n}-0000-0000-0000-000000000000' for n in (0,1,2))
    conflicting = dict(spread,marketId=conflict_market,outcomes=[
        dict(spread['outcomes'][0],outcomeId=conflict_away,subjectId=spread['outcomes'][1]['subjectId']),
        dict(spread['outcomes'][1],outcomeId=conflict_home,subjectId=spread['outcomes'][0]['subjectId'])])
    contradictory = proof([winner,spread,conflicting], dict(links, **{conflict_home:links[HOME],conflict_away:links[AWAY]}))
    assert bind(row,contradictory,at=AT)['reason'] == 'sgo_native_subject_roles_conflict'


@pytest.mark.parametrize('league, moneyline_equality, shortened_counts', [
    ('NFL', 'half_face', False), ('NCAAF', 'half_face', True),
    ('NHL', 'half_face', True), ('NBA', 'void_without_official_winner', True),
    ('NCAAB', 'void_without_official_winner', True), ('MLB', 'void_without_official_winner', False),
])
def test_filed_full_game_rules_are_specific_to_league_and_family(league, moneyline_equality, shortened_counts):
    winner = settlement_profile(league,'moneyline',None,'FMV')
    spread = settlement_profile(league,'spread',Fraction(-3,2),'FMV')
    total = settlement_profile(league,'total',Fraction(81,2),'FMV')
    assert winner['equality'] == moneyline_equality
    assert winner['equality_payout'] == ('0.5' if moneyline_equality == 'half_face' else None)
    assert spread['equality'] == total['equality'] == 'not_possible'
    assert ('competition_shortened_play' in spread['shortened_game']) is shortened_counts
    assert ('competition_shortened_play' in total['shortened_game']) is shortened_counts
    assert not settlement_profile(league,'spread',Fraction(-1),'FMV')['available']
    assert not settlement_profile(league,'total',Fraction(40),'PUSH')['available']
    for rule in (winner,spread,total):
        assert rule['available'] and rule['scope'] == 'completed_full_game'
        assert rule['source_url'].endswith('.pdf') and rule['class_url'].endswith('.pdf')
        assert (rule['extra_innings'] == 'included') is (league == 'MLB')
        assert (rule['overtime'] == 'included') is (league != 'MLB')
        assert (rule['shootout_count'] == 'one_goal_to_winning_team') is (league == 'NHL')
        assert rule['void'] == 'fair_market_value' and rule['void_payout'] is None
        assert not rule['exceptional_payoff_available']


def test_worker_collects_only_official_linked_instruments_and_respects_stop(monkeypatch):
    asyncio.run(worker_catalog_case(monkeypatch))


async def worker_catalog_case(monkeypatch):
    _, event, market = fixture()
    assert event_link_id(dict(host='novig.com',path='/event-markets/'+EVENT+'/sportsgameodds')) == EVENT
    calls, saved = [], []

    def server(request):
        calls.append(request)
        if request.url.path == EVENT_PATH:
            return httpx.Response(200,json=event)
        assert request.url.path == MARKETS_PATH and request.url.params['event'] == EVENT
        return httpx.Response(200,json=dict(items=[market],next=None))

    service = SimpleNamespace(dispatch=True, globally_stopped=False, paused_sources=set(),
                              config=dict(aggregate_provider='sportsgameodds'))
    worker = NovigPublicDiscovery(service, transport=httpx.MockTransport(server))
    monkeypatch.setattr(worker,'catalog_targets', lambda _: [(SGO,EVENT,{HOME:[]},'2'*64)])
    monkeypatch.setattr(worker,'save_catalog', lambda event_id,proof: saved.append((event_id,proof)) or True)
    async with httpx.AsyncClient(transport=worker.transport) as client:
        worker.client = client
        await worker.poll_sgo_catalog()
        assert len(calls) == 2 and all(request.method == 'GET' for request in calls)
        assert len(saved) == 1 and set(saved[0][1]['markets']) == {HOME}
        assert worker.metrics['sgo_catalog_outcomes'] == 1
        service.paused_sources.add('sportsgameodds')
        await worker.poll_sgo_catalog()
        assert len(calls) == 2 and len(saved) == 1
