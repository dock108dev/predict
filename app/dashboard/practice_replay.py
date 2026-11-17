"""Packaged, authored examples read only through the replay routes."""

from fractions import Fraction
from functools import lru_cache

from app.comparison.cashflows import exact_wire as wire
from app.comparison.pregame_valuation import valuation
from app.comparison.snapshot_fee_outcome import unavailable
from app.comparison.snapshot_math import assumptions, before_fee_pair
from app.storage.ordinary_projection import counts
from app.storage.pregame_unit_board import fair_odds
from app.storage.store import hashed


AT = '2026-11-16T19:06:03+00:00'
START = '2026-11-17T03:00:00+00:00'
UNIT = Fraction(25)


def example_game(key, home, away, league='NBA'):
    return dict(game_key=key, title=f'{home} vs. {away}', start_at=START, league=league,
                participants=[dict(id=team, name=team, role=role)
                              for role, team in (('home', home), ('away', away))])


def authored_offer(game, venue, side, cost, *, line=None):
    team = game['participants'][side]['id']
    key = game['game_key']
    family = 'spread' if line else 'winner'
    predicate = 'cover' if line else 'win'
    selection = dict(participant=team, predicate=predicate)
    if line:
        selection['signed_line'] = line
    operator = 'ge' if not side else 'le'
    threshold = 19 if line else 0 if side else 1
    identity = [key, game['league'], family, 'full_game', 'practice', 'settlement', 'normal',
                team, predicate, ['home_margin', operator, [threshold, 1], None], ['predicate'], 'USD', '1']
    id_ = f'{key}-{side}'
    odds = wire(1 / Fraction(cost))
    return dict(id=id_, kind='single', game_key=key, game_title=game['title'], venue=venue,
        league=game['league'], start_at=START, captured_at=AT, game_state='scheduled',
        market=dict(market=family, period='full_game', line=line), selection=selection, participant_label=team,
        original=dict(value=odds, units='decimal_odds', payout='1'),
        cost_per_normal_claim=cost, same_outcome=dict(supported=True, key=identity),
        source=dict(provider='practice', native_event_id=key, native_market_id=f'{key}-{family}',
                    native_outcome_id=id_, native_side=operator),
        times=dict(source_at=AT, received_at=AT), price_current=True, current_reasons=[],
        publication_policy='practice', trade_fee=unavailable('fee_outcome_not_published'),
        price_revision=hashed([id_, cost]), economic_revision=hashed([id_, cost, 'practice']))


def saint_marys(game, result_id):
    row = authored_offer(game, 'prophetx', 0, '25/53', line='-18.5')
    # Same +112 offer, FanDuel -110/-110 reference and fictional fee terms
    # as the Sprint 3 Saint Mary's worked example.
    ref = dict(available=True, book='fanduel', probability='0.5', fair_decimal_odds='2',
        selected_outcome='home', prices=[
            dict(side=side, line=line, price_american='-110', source_at=AT)
            for side, line in (('home', '-18.5'), ('away', '18.5'))])
    row.update(evidence_result_id=result_id, pregame_reference=ref,
        settlement_assessment=dict(available=True, comparable=True, scope='event_goes_ahead',
            state_probabilities=dict(win='0.5', loss='0.5')),
        valuation_fill_terms=dict(kind='stake', order_type='straight_stake', increment='0.01',
            minimum='0.01', maximum='1000', revision='saint-marys-fixture-fill-1', evidence_class='fixture',
            cash_terms=dict(order_type='straight_stake', entry_rate='0.03', flat_entry_usd='0.02',
                evidence=dict(revision='saint-marys-fixture-fee-1', source='Authored Saint Mary’s practice terms',
                              **{'class': 'fixture'}))))
    return row


def practice_valuation(row, result_id):
    model = valuation(row, UNIT, publication_id=result_id, snapshot_id=result_id)
    return dict(model, fair_odds=fair_odds(model['reference']))


@lru_cache(maxsize=1)
def examples():
    rows, pairs, games = [], [], []
    scenarios = (
        ('practice-positive', 'Harbor Foxes', 'Summit Owls', '0.40', '200', 'zero'),
        ('practice-shortfall', 'Canyon Hawks', 'Lake Wolves', '100/199', '200', 'unknown'),
        ('practice-depth', 'Prairie Bears', 'Pine Lynx', '0.40', '25', 'zero'),
        ('practice-rules', 'River Otters', 'Coast Seals', '0.40', '200', 'mismatch'),
    )
    for key, home, away, cost, size, terms in scenarios:
        game = example_game(key, home, away)
        legs = [authored_offer(game, venue, side, cost) for side, venue in enumerate(('novig', 'prophetx'))]
        if terms != 'unknown':
            for row in legs:
                row['trade_fee'] = dict(available=True, classification='synthetic',
                    fee_cashflows=dict(at_fill_usd='0'), evidence=dict(fictional_rate='0'))
        if terms == 'mismatch':
            # The second example venue allows a tied score to void its leg.
            legs[1]['same_outcome']['key'][10] = ['refund', [0, 1], None]
        proof = before_fee_pair(*legs, key) or dict(market_key=key, blocker='pair_settlement_unverified')
        step = '0.5' if terms == 'unknown' else '1'
        proof['depth_evidence'] = [dict(price=cost, quantity=quantity, received_at=AT, quantity_increment=step)
                                   for quantity in (size, '200')]
        pairs.append(dict(id=key, kind='pair', game_key=key, league=game['league'], game_title=game['title'],
            start_at=START, market=legs[0]['market'], legs=[row['id'] for row in legs], before_fees=proof))
        rows.extend(legs)
        games.append(game)
    ev_game = example_game('practice-saint-marys', "Saint Mary's Gaels", 'Gonzaga Bulldogs', league='NCAAB')
    # A content revision pins all exact terms and pair inputs to the replay.
    ev = saint_marys(ev_game, None)
    result_id = hashed([rows, pairs, ev])[:32]
    ev['evidence_result_id'] = result_id
    rows.append(ev)
    games.append(ev_game)
    for row in rows:
        row['evidence_result_id'] = result_id
    for pair in pairs:
        pair['evidence_result_id'] = result_id
    settings, _ = assumptions(dict(amount='100', buffer='0', scenario='decisive_only', sizing='hypothetical_fractional'))
    settings['benchmark_venue'] = None
    result = dict(id=result_id, captured_at=AT, rows=rows, pairs=pairs, games=games, assumptions=settings,
        publication=dict(policy='practice', state='ready', read_at=AT, current_prices=len(rows)),
        replay=dict(id=result_id, dataset='practice', synthetic=True))
    counts(result)
    return result, ev
