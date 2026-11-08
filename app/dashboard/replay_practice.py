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
    market = dict(market='winner', period='full_game', line=None)
    settings, policy = assumptions(dict(amount='100', buffer='0', scenario='decisive_only',
        sizing='hypothetical_fractional', fees={'novig':'0.01', 'prophetx':'0.02'}))
    rows = []
    details = {}
    for index, (venue, team, odds) in enumerate((('novig', 'Harbor Foxes', '2.2'),
            ('prophetx', 'Summit Owls', '2.1' if changed else '1.75'))):
        lower = index == 0
        cost = 1 / Fraction(odds)
        probability = Fraction(1, 2)
        source = dict(provider='practice', native_side='fictional outcome', native_event_id='practice-game',
                      native_market_id='practice-winner', native_outcome_id=f'practice-{index}')
        selection = dict(participant=team, label=team, predicate='win')
        predicate = ['home_margin', 'ge' if lower else 'le', [1 if lower else 0, 1], None]
        identity = ['practice-game', 'NBA', 'winner', 'full_game', 'fictional', 'settlement', 'normal',
                    team, 'win', predicate, ['predicate'], 'USD', '1']
        row = dict(id=f'practice-offer-{index}', venue=venue, source=source, kind='single', game_key='practice-game',
            game_title=title, start_at=start, league='NBA', market=market, selection=selection, participant_label=team,
            original=dict(value=odds, units='decimal_odds', payout='1'),
            same_outcome=dict(supported=True, key=identity), binding=dict(verified=True, basis='synthetic'),
            probability=wire(probability), cost_per_normal_claim=wire(cost),
            gross_profit_per_claim=wire(probability - cost), gross_return_percent=wire(100 * (probability / cost - 1)),
            conditional_trade_benchmark=dict(available=False, reason='synthetic_account_terms_unavailable'),
            conservative_trade_benchmark=dict(available=False, reason='synthetic_public_schedule_unavailable'),
            math=funded([cost], [probability], [venue], settings, policy),
            current_authority=dict(synthetic=True), price_current=True, current_reasons=[], game_state='scheduled',
            game_state_basis='fictional scenario', captured_at=at, evidence_result_id=result_id,
            publication_policy='practice', price_revision=f'{index}:{odds}', economic_revision=f'{index}:{odds}',
            times=dict(source_at=at, received_at=at))
        row['net_return_percent'] = row['math']['buffered_return_percent']
        row['snapshot_benchmark'] = dict(bookmaker='pinnacle', selected=index, odds=['2', '2'])
        row['reference_calculation'] = dict(available=True, venue='pinnacle', selected=index,
            method='proportional_no_vig', probability='0.5', overround='0', fair_decimal_odds='2',
            conditioning='Fictional decisive win/loss outcomes', pair=[
                dict(original=dict(value='2', units='decimal_odds'), selection=dict(label=name), times=dict(source_at=at))
                for name in ('Harbor Foxes', 'Summit Owls')])
        statuses(row)
        rows.append(row)
        details[row['id']] = dict(result_id=result_id, row=row, inspection=offer_math(row), captured_at=at,
                                  assumptions=settings, provider_requests=0)
    pair = before_fee_pair(*rows, 'practice-winner')
    assumed_pair = funded([row['cost_per_normal_claim'] for row in rows], [Fraction(1, 2)],
                          [row['venue'] for row in rows], settings, policy)
    pairs = [dict(id='practice-pair', kind='pair', game_key='practice-game', game_title=title, start_at=start,
                  league='NBA', market=market, legs=[row['id'] for row in rows], before_fees=pair,
                  math=assumed_pair)]
    result = dict(id=result_id, rows=rows, pairs=pairs, games=[], assumptions=settings,
                  publication=dict(policy='practice', state='ready', current_prices=2, retained_prices=0),
                  replay=dict(id=result_id, dataset='practice', captured_at=at, frame=frame, synthetic=True))
    counts(result)
    return result, details
