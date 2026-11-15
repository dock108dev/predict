from datetime import datetime, timedelta, timezone
from fractions import Fraction

from app.comparison.game_phase import price_phase
from app.comparison.public_sportsbook_estimate import SOURCE, collect_pairs, estimate, market_pairs, quote, select
from app.dashboard.trade_desk import page
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
