from datetime import datetime, timedelta, timezone
from fractions import Fraction

from app.comparison.game_phase import price_phase
from app.comparison.public_sportsbook_estimate import SOURCE, collect_pairs, estimate, market_pairs, quote, select
from app.dashboard.trade_desk import page
from app.storage.current_native_desk import overlay
from app.storage.current_rows import contract_id
from tests.test_trade_desk import quote as desk_quote, result


AT = datetime(2026, 11, 13, tzinfo=timezone.utc)
START = AT + timedelta(minutes=5)
OCCURRENCE = ('NFL', START, 'NFL:NYG', 'NFL:WAS')
HOME = ('moneyline', 'home', None)
AWAY = ('moneyline', 'away', None)
SPREAD = ('spread', 'away', Fraction('-2.5'))
OPPOSITE_SPREAD = ('spread', 'home', Fraction('2.5'))


def observation(*, first=AT, second=AT, source=SOURCE):
    def item(value, clock, key, identifier, opposite):
        return dict(quote(value, clock.isoformat(), key), odd_id=identifier, opposing_odd_id=opposite)

    return dict(source=source, event_id='game', frame_id='frame', frame_received_at=AT.isoformat(),
                scheduled=True, quotes={
        HOME: {'draftkings': [item('-125', first, HOME, 'home', 'away')],
               'fanduel': [item('-118', AT, HOME, 'home', 'away')]},
        AWAY: {'draftkings': [item('+105', second, AWAY, 'away', 'home')],
               'fanduel': [item('+100', AT, AWAY, 'away', 'home')]},
    })


def test_best_payout_uses_one_book_and_exact_unrounded_devig():
    match = observation()
    selected = estimate(Fraction('0.4625'), {OCCURRENCE: [match]}, OCCURRENCE, AWAY, at=AT)
    assert selected['book'] == 'draftkings'
    assert Fraction(selected['probability']) == Fraction(36, 77)
    assert Fraction(selected['return_percent']) == 100 * (Fraction(36, 77) / Fraction('0.4625') - 1)
    assert [leg['price_american'] for leg in selected['prices']] == ['+105', '-125']
    assert datetime.fromisoformat(selected['current_until']) == START


def test_current_public_prophetx_price_has_the_same_exact_line_reference():
    row = dict(league='NFL', venue='prophetx',
               original=dict(value='+115', units='american_odds', payout='1', payout_units='USD'),
               original_record=dict(event=dict(scheduled_start=START.isoformat(), home='NFL:NYG', away='NFL:WAS'),
                                    market_identity=dict(family='moneyline', period='full_game'),
                                    selection=dict(participant='NFL:WAS', predicate='win', signed_line=None)))
    authority = dict(provider=SOURCE, lifecycle=dict(state='scheduled'), expected=['revision'])
    basis = select(row, authority, {OCCURRENCE: [observation()]}, at=AT)
    assert basis['book'] == 'draftkings'
    assert Fraction(basis['return_percent']) == 100 * (Fraction(36, 77) * Fraction(215, 100) - 1)
    assert select(row, dict(authority, reasons=['source_expired']), {OCCURRENCE: [observation()]}, at=AT) is None


def test_public_browse_can_show_fair_odds_while_price_ev_is_pending():
    saved = dict(desk_quote('native', 'kalshi', current=False), game_key='game')
    data = result(saved)

    def enrich(out, *, include_retained):
        for group in out['rows']:
            pairs = group.setdefault('_sportsbook_pairs', {})
            collect_pairs(pairs, [observation()], AWAY, at=AT, start=START)

    query = dict(layout='desk', browse_odds='1', basis='sportsbooks', lines='main', summary='1')
    group, = page(data, query, ('ev', None, 0, 5), enrich=enrich)['rows']
    ref = group['sportsbook_reference']
    assert ref['book'] == 'draftkings'
    assert ref['fair_odds']['american'] == '+113.89'
    assert group['offers'][0]['value'] is None
    assert not group['offers'][0]['current']


def test_native_pregame_desk_uses_current_books_before_the_slate_catches_up(monkeypatch):
    clock = AT - timedelta(seconds=3)
    records = []
    for venue, cost in [('kalshi', '0.42'), ('polymarket_us', '0.46')]:
        records.append(dict(
            event=dict(competition='NFL', scheduled_start=START.isoformat(), home='NFL:NYG', away='NFL:WAS',
                       source_participant_roles=dict(home='NFL:NYG', away='NFL:WAS')),
            market_identity=dict(family='moneyline', period='full_game', line=None),
            selection=dict(participant='NFL:WAS', predicate='win', signed_line=None),
            quote=dict(venue=venue, state='available',
                source=dict(provider=venue, native_event_id='game', native_market_id='game-winner',
                            native_outcome_id='away'),
                original=dict(value=cost, units='usd_per_contract', payout='1', payout_units='USD'),
                times=dict(source_at=clock.isoformat(), received_at=AT.isoformat()),
                freshness_policy=dict(maximum_age_seconds=30))))
    deps = {contract_id(record): ['price', 'contract', 'event'] for record in records}

    def active(db, *, at, venues, contract):
        return [record for record in records if record['quote']['venue'] in venues
                and (contract is None or contract_id(record) == contract)], deps

    monkeypatch.setattr('app.storage.current_native_desk.active_records', active)
    monkeypatch.setattr('app.storage.ordinary_publication.pregame_sportsbooks',
                        lambda db, owner, states, at, occurrences: {OCCURRENCE: [observation()]})
    data = dict(result(), games=[])
    data['publication']['read_at'] = AT.isoformat()
    owner = dict(active=True, healthy=True)
    states = dict(kalshi={'state': 'available'}, polymarket_us={'state': 'available'})
    projected = overlay(None, data, owner, states, at=AT)
    query = dict(layout='desk', ranked='1', basis='sportsbooks', lines='main', summary='1')
    group, = page(projected, query, ('ev', None, 0, 10))['rows']
    offers = {offer['venue']: offer for offer in group['offers']}
    assert set(offers) == {'kalshi', 'polymarket_us'}
    for record in records:
        q = record['quote']
        offer = offers[q['venue']]
        assert offer['current'] and offer['live_native_desk']
        assert offer['fair_reference']['books'] == ['draftkings']
        assert offer['current_until'] == (clock + timedelta(seconds=30)).isoformat()
        assert Fraction(offer['value']) == 100 * (Fraction(36, 77) / Fraction(q['original']['value']) - 1)
    assert projected['rows'][0]['id'] == 'native-current:' + contract_id(records[0])
    assert len(overlay(None, data, owner, states, at=AT, contract=contract_id(records[0]))['rows']) == 1
    assert overlay(None, data, owner, states, at=AT + timedelta(seconds=31)) is data
    assert overlay(None, data, dict(owner, global_stopped=True), states, at=AT) is data
    assert [offer['venue'] for offer in overlay(None, data,
        dict(owner, paused_sources=['kalshi']), states, at=AT)['rows']] == ['polymarket_us']


def test_both_original_clocks_kickoff_omission_and_suspension():
    deadline = AT - timedelta(minutes=15)
    match = observation(first=deadline, second=AT - timedelta(seconds=1))
    pairs = market_pairs(match, AWAY, at=AT, start=START)
    assert 'draftkings' in pairs
    match['frame_received_at'] = (AT + timedelta(seconds=1)).isoformat()
    later = AT + timedelta(microseconds=1)
    assert set(market_pairs(match, AWAY, at=later, start=START)) == {'fanduel'}
    assert estimate(Fraction('0.46'), {OCCURRENCE: [match]}, OCCURRENCE, AWAY, at=START) is None
    match['quotes'][HOME].clear()
    assert not market_pairs(match, AWAY, at=AT, start=START)
    match = observation()
    match['scheduled'] = False
    assert not market_pairs(match, AWAY, at=AT, start=START)


def test_alternate_spread_requires_mirrored_line_and_reciprocal_sgo_ids():
    match = observation(source='sportsgameodds')
    target = dict(quote('+108', AT.isoformat(), SPREAD), odd_id='spread-away', opposing_odd_id='spread-home')
    other = dict(quote('-120', AT.isoformat(), OPPOSITE_SPREAD), odd_id='spread-home', opposing_odd_id='other')
    match['quotes'] = {SPREAD: {'caesars': [target]}, OPPOSITE_SPREAD: {'caesars': [other]}}
    assert not market_pairs(match, SPREAD, at=AT, start=START)
    other['opposing_odd_id'] = target['odd_id']
    assert set(market_pairs(match, SPREAD, at=AT, start=START)) == {'caesars'}
    wrong_line = ('spread', 'home', Fraction('-2.5'))
    match['quotes'][wrong_line] = match['quotes'].pop(OPPOSITE_SPREAD)
    assert not market_pairs(match, SPREAD, at=AT, start=START)


def test_phase_is_applied_before_counts_filters_and_pagination():
    base = dict(desk_quote('eligible', 'kalshi'), start_at=START.isoformat(),
                game_state='scheduled', sportsbook_return_percent='1', sportsbook_baseline=estimate(
                    Fraction('0.46'), {OCCURRENCE: [observation()]}, OCCURRENCE, AWAY, at=AT))
    live = dict(base, id='early-live', game_state='live', sportsbook_return_percent='50')
    kickoff = dict(base, id='kickoff', start_at=AT.isoformat(), sportsbook_return_percent='99')
    suspended = dict(base, id='suspended', game_state='suspended')
    half = dict(base, id='half', market=dict(base['market'], period='first_half'))
    data = result(base, live, kickoff, suspended, half)
    data['publication']['read_at'] = AT.isoformat()
    query = dict(layout='desk', ranked='1', last_known='1', game_state='live', period='first_half')
    pregame = page(data, query, ('ev', None, 0, 1))
    assert pregame['phase'] == 'pregame' and pregame['basis'] == 'sportsbooks'
    assert pregame['matched_offer_count'] == pregame['total'] == 1
    assert pregame['rows'][0]['offers'][0]['id'] == 'eligible'
    assert price_phase({'scheduled_start': START.isoformat(), 'status': {'live': True}}, {}, AT.isoformat()) == {
        'state': 'live', 'reason': 'event_started_before_schedule', 'basis': 'explicit_source_state'}
