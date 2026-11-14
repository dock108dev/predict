"""An isolated, fictional price change with exact odds and explicit test fees."""
from fractions import Fraction
from functools import lru_cache

from app.comparison.cashflows import exact_wire as wire
from app.comparison.inspection_math import offer_math
from app.comparison.snapshot_math import assumptions, before_fee_pair, funded
from app.comparison.snapshot_metrics import statuses
from app.storage.ordinary_publication import counts
from .local_security import PublicRequestError


@lru_cache(maxsize=2)
def practice(frame):
    if frame not in ('initial', 'changed'):
        raise PublicRequestError('Unknown practice frame')
    changed = frame == 'changed'
    result_id = f'practice-{frame}-1'
    at = '2026-11-08T03:59:30Z' if not changed else '2026-11-08T03:59:50Z'
    start = '2026-11-08T04:30:00Z'
    title = 'Harbor Foxes vs. Summit Owls'
    home, away = 'Harbor Foxes', 'Summit Owls'
    markets = (
        ('winner', None, ('win', 'win'), ('2.2', '2.1' if changed else '1.75')),
        ('spread', '-3.5', ('cover', 'cover'), ('1.91', '1.87' if changed else '1.91')),
        ('total', '218.5', ('over', 'under'), ('1.91', '1.95' if changed else '1.91')),
    )
    settings, policy = assumptions(dict(amount='100', buffer='0', scenario='decisive_only',
        sizing='hypothetical_fractional', fees={'novig':'0.01', 'prophetx':'0.02'}))
    rows = []
    details = {}
    for family, line, predicates, prices in markets:
        for side, (venue, team) in enumerate((('novig', home), ('prophetx', away))):
            selection = dict(predicate=predicates[side])
            signed = str(-Fraction(line)) if line and family == 'spread' and side else line
            if family != 'total':
                selection.update(participant=team, label=team)
            if signed is not None:
                selection['signed_line'] = signed
            display = team if family == 'winner' else (
                f'{team} {float(Fraction(signed)):+g}' if family == 'spread'
                else f'{predicates[side].title()} {line}')
            key = str(side) if family == 'winner' else f'{family}-{side}'
            threshold = (1 if not side else 0) if family == 'winner' else (
                (4 if not side else 3) if family == 'spread' else (219 if not side else 218))
            row = practice_offer(key=key, side=side, venue=venue, display=display,
                odds=prices[side], family=family, line=line, selection=selection, threshold=threshold,
                at=at, start=start, title=title, result_id=result_id, settings=settings, policy=policy)
            rows.append(row)
    for offer in rows:
        market = offer['market']
        peers = [row for row in rows if row['market'] == market]
        offer['reference_calculation']['pair'] = [
            dict(original=dict(value='2', units='decimal_odds'), selection=dict(label=row['participant_label']),
                 times=dict(source_at=at)) for row in peers
        ]
        details[offer['id']] = dict(result_id=result_id, row=offer, inspection=offer_math(offer), captured_at=at,
                                    assumptions=settings, provider_requests=0)
    winners = rows[:2]
    pair = before_fee_pair(*winners, 'practice-winner')
    assumed_pair = funded([row['cost_per_normal_claim'] for row in winners], [Fraction(1, 2)],
                          [row['venue'] for row in winners], settings, policy)
    pairs = [dict(id='practice-pair', kind='pair', game_key='practice-game', game_title=title, start_at=start,
                  league='NBA', market=winners[0]['market'], legs=[row['id'] for row in winners], before_fees=pair,
                  math=assumed_pair)]
    result = dict(id=result_id, rows=rows, pairs=pairs, games=[], assumptions=settings,
                  publication=dict(policy='practice', state='ready', current_prices=len(rows), retained_prices=0),
                  replay=dict(id=result_id, dataset='practice', captured_at=at, frame=frame, synthetic=True))
    counts(result)
    return result, details


def practice_offer(*, key, side, venue, display, odds, family, line, selection, threshold,
                   at, start, title, result_id, settings, policy):
    market = dict(market=family, period='full_game', line=line)
    cost = 1 / Fraction(odds)
    probability = Fraction(1, 2)
    source = dict(provider='practice', native_side='fictional outcome', native_event_id='practice-game',
                  native_market_id=f'practice-{family}', native_outcome_id=f'practice-{key}')
    predicate = ['total_score' if family == 'total' else 'home_margin',
                 'le' if side else 'ge', [threshold, 1], None]
    identity = ['practice-game', 'NBA', family, 'full_game', 'fictional', 'settlement', 'normal',
                selection.get('participant'), selection['predicate'], predicate, ['predicate'], 'USD', '1']
    row = dict(id=f'practice-offer-{key}', venue=venue, source=source, kind='single', game_key='practice-game',
        game_title=title, start_at=start, league='NBA', market=market, selection=selection, participant_label=display,
        original=dict(value=odds, units='decimal_odds', payout='1'),
        same_outcome=dict(supported=True, key=identity), binding=dict(verified=True, basis='synthetic'),
        probability=wire(probability), cost_per_normal_claim=wire(cost),
        gross_profit_per_claim=wire(probability - cost), gross_return_percent=wire(100 * (probability / cost - 1)),
        conditional_trade_benchmark=dict(available=False, reason='synthetic_account_terms_unavailable'),
        conservative_trade_benchmark=dict(available=False, reason='synthetic_public_schedule_unavailable'),
        math=funded([cost], [probability], [venue], settings, policy),
        current_authority=dict(synthetic=True), price_current=True, current_reasons=[], game_state='scheduled',
        game_state_basis='fictional scenario', captured_at=at, evidence_result_id=result_id,
        publication_policy='practice', price_revision=f'{key}:{odds}', economic_revision=f'{key}:{odds}',
        times=dict(source_at=at, received_at=at))
    row['net_return_percent'] = row['math']['buffered_return_percent']
    # The practice calculator uses the same per-fill payoff path as the desk.
    rate = Fraction(settings['fees'][venue])
    row['trade_fee'] = dict(available=True, classification='synthetic',
        trade_fee_usd=wire(rate * cost), quantity='1', quantity_unit='USD payout contracts',
        fill_count=1, evidence=dict(fictional_rate=wire(rate)),
        fee_cashflows=dict(at_fill_usd=wire(rate * cost)))
    row['snapshot_benchmark'] = dict(bookmaker='pinnacle', selected=side, odds=['2', '2'])
    row['reference_calculation'] = dict(available=True, venue='pinnacle', selected=side,
        method='proportional_no_vig', probability='0.5', overround='0', fair_decimal_odds='2',
        conditioning='Fictional decisive win/loss outcomes')
    statuses(row)
    return row
