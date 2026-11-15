from datetime import datetime,timezone,timedelta
from decimal import Decimal
from types import SimpleNamespace
from app.collection.native_priority import matching_main_markets, select
from app.dashboard.session_projection import stable


def population():
    markets=[];events=[];metadata=[];now=datetime(2026,11,8,tzinfo=timezone.utc)
    for league in ('NFL','NBA','NCAAF','NCAAB','MLB','NHL'):
        for n in range(3):
            eid=f'{league}-{n}';events.append(dict(id=eid,competition=league,scheduled_start=(now+timedelta(hours=n)).isoformat()))
            for family in ('moneyline','spread','total'):
                for line in range(4):
                    mid=f'{eid}-{family}-{line}'
                    markets.append(SimpleNamespace(raw=SimpleNamespace(ref=SimpleNamespace(event_id=eid,market_id=mid))))
                    metadata.append(dict(id=mid,event_id=eid,market_type=family))
    return markets,dict(events=events,markets=metadata),now


def test_full_catalog_is_unchanged_and_every_deferred_market_receives_a_fair_slot():
    markets,catalog,now=population();original=list(markets);seen=set();fixed=None
    for offset in range(12):
        chosen,detail=select(markets,catalog,now,offset,limit=36)
        ids=[m.raw.ref.market_id for m in chosen]
        assert len(ids)==len(set(ids))==36
        if fixed is None:fixed=ids[:18]
        assert ids[:18]==fixed
        seen.update(ids)
        assert detail['eligible_markets']==216 and detail['deferred_markets']==180
        assert len(detail['cells'])==18
        assert all(c['active']>=1 for c in detail['cells'])
        assert sum(c['active']+c['deferred'] for c in detail['cells'])==216
    assert seen=={m.raw.ref.market_id for m in markets}
    assert markets==original and len(catalog['markets'])==216


def test_small_roster_needs_no_deferral_and_unknown_times_are_retained():
    markets,catalog,now=population();catalog['events'][0]['scheduled_start']=None
    chosen,detail=select(markets,catalog,now,0)
    assert {m.raw.ref.market_id for m in chosen}=={m.raw.ref.market_id for m in markets}
    assert detail['deferred_markets']==0


def test_confirmed_live_event_has_a_stable_slot_ahead_of_nearer_kickoff():
    markets,catalog,now=population()
    live=catalog['events'][2]
    live.update(scheduled_start=(now-timedelta(hours=2)).isoformat(),status={'live': True})
    for offset in range(12):
        chosen,_=select(markets,catalog,now,offset,limit=36)
        fixed={m.raw.ref.market_id for m in chosen[:18]}
        assert {f"{live['id']}-{family}-0" for family in ('moneyline','spread','total')} <= fixed
    live['status']={'live': True, 'ended': True}
    chosen,_=select(markets,catalog,now,0,limit=36)
    assert all(m.raw.ref.event_id!=live['id'] for m in chosen[:18])


def test_sparse_live_event_retains_all_lines_without_losing_other_cells_or_rotation():
    markets, catalog, now = population()
    event = catalog['events'][-1]
    start = (now - timedelta(hours=2)).isoformat()
    event.update(scheduled_start=start, _native={'gameId': 42, 'eventState': {'updatedAt': start}})
    observation = dict(event_id=event['id'], league='NHL', game_id='42', start_at=start, source_at=now.isoformat())
    committed = dict(event, status={'live': True}, sporting_state_evidence=observation)
    live = {m.raw.ref.market_id for m in markets if m.raw.ref.event_id == event['id']}
    seen = set()
    for offset in range(8):
        chosen, detail = select(markets, catalog, now, offset, limit=72, phase_events=[committed])
        ids = [m.raw.ref.market_id for m in chosen]
        assert live <= set(ids[:36])
        assert len(ids) == len(set(ids)) == detail['active_markets'] == 72
        assert all(cell['active'] for cell in detail['cells'])
        seen.update(ids)
    assert seen == {m.raw.ref.market_id for m in markets}
    for invalid in (dict(observation, game_id='77'),
                    dict(observation, source_at=(now-timedelta(hours=3)).isoformat())):
        chosen, _ = select(markets, catalog, now, 0, limit=72,
                           phase_events=[dict(committed, sporting_state_evidence=invalid)])
        assert live - {m.raw.ref.market_id for m in chosen[:36]}


def test_older_live_flags_do_not_crowd_out_alternates_for_a_recent_game():
    markets, catalog, now = population()
    for event in catalog['events']:
        event.update(scheduled_start=(now-timedelta(hours=16)).isoformat(), status={'live': True})
    recent = catalog['events'][-1]
    recent['scheduled_start'] = (now-timedelta(minutes=35)).isoformat()
    for offset in range(8):
        chosen, detail = select(markets, catalog, now, offset, limit=72)
        assert sum(m.raw.ref.event_id == recent['id'] for m in chosen[:36]) == 12
        assert detail['active_markets'] == 72
        assert all(cell['active'] for cell in detail['cells'])


def test_pregame_main_markets_prefer_exact_native_sides():
    event = dict(id='event', competition='NFL', scheduled_start='2026-11-15T14:30:00Z',
                 identity='resolved', home='NFL:DET', away='NFL:NE',
                 participants={'Detroit': 'NFL:DET', 'New England': 'NFL:NE'},
                 source_participant_roles={'home': 'NFL:DET', 'away': 'NFL:NE'})
    start = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)
    game = ('NFL', start, 'NFL:DET', 'NFL:NE')
    main = {(*game, 'spread'): Decimal('-2.5'), (*game, 'total'): Decimal('49.5')}

    def market(id_, family, participant, line, *, context_missing=False, period='full_game'):
        sides = [dict(native_id='4316818', operator='gt', equality='unreachable'),
                 dict(native_id='4316819', operator='le', equality='unreachable')]
        binding = dict(source='polymarket_us', event_id='event', market_id=id_,
                       status='IDENTITY_BLOCKED' if context_missing else 'BOUND_RAW_PREDICATE',
                       blockers=['Exact game identity facts unavailable: season, stage'] if context_missing else [],
                       identity=dict(competition='NFL', family=family, period=period,
                                     roles=event['source_participant_roles']),
                       source_predicate=dict(family=family, period=period, participant=participant,
                                             line=line, outcomes=sides),
                       predicate=[participant, line, sides])
        binding['sha256'] = stable(binding)
        return dict(id=id_, event_id='event', market_type=family, period=period, v1_raw_binding=binding,
                    sides=[dict(id=side['native_id']) for side in sides])

    markets = [
        market('home-favorite', 'spread', 'NFL:DET', '-2.5', context_missing=True),
        market('away-underdog', 'spread', 'NFL:NE', '2.5'),
        market('away-favorite', 'spread', 'NFL:NE', '-2.5'),
        market('other-line', 'spread', 'NFL:DET', '-3.5'),
        market('total', 'total', 'combined', '49.5'),
        market('team-total', 'total', 'NFL:DET', '49.5'),
        market('first-half', 'total', 'combined', '49.5', period='first_half'),
    ]
    assert matching_main_markets(dict(events=[event], markets=markets), main) == {
        'home-favorite', 'away-underdog', 'total',
    }
    assert markets[0]['v1_raw_binding']['status'] == 'IDENTITY_BLOCKED'


def test_main_market_priority_preserves_rotation_and_cap():
    markets, catalog, now = population()
    preferred = {'NFL-2-spread-2', 'NFL-2-moneyline-3'}
    seen = set()
    for offset in range(9):
        chosen, _ = select(markets, catalog, now, offset, limit=72, preferred=preferred)
        ids = [m.raw.ref.market_id for m in chosen]
        assert len(ids) == len(set(ids)) == 72
        assert preferred <= set(ids[:36])
        seen.update(ids)
    assert seen == {m.raw.ref.market_id for m in markets}
