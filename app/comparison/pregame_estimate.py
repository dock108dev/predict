"""Public retail estimates from exact pregame prices and disclosed fill assumptions."""
from fractions import Fraction

from .cashflows import exact_wire
from .trade_preview import order_step
from app.dashboard.current_contract import price
from app.storage.store import hashed


def inputs(row, amount):
    """Prepare a decisive completed-game model without asserting execution proof."""
    terms = row.get('valuation_fill_terms') or {}
    if terms.get('evidence_class') == 'fixture':
        return row
    reference = row.get('pregame_reference') or {}
    observed = reference if reference.get('available') else reference.get('observed_snapshot')
    settlement = row.get('settlement_assessment') or {}
    if settlement.get('comparable') is False:
        return row
    assumptions = [
        'Estimated for a decisive completed full game. Pushes, voids and cancellations are excluded.',
        'Uses the applicable public retail fee schedule for a new standalone position. Private account charges and rebates are excluded.',
    ]
    baseline = row.get('sportsbook_baseline')
    if observed:
        probability = Fraction(observed['probability'])
        if not 0 < probability < 1:
            return row
        reference = dict(observed, available=True, conditioning='if_decisive_completed_game',
                         bet_id=hashed([observed['market'], observed['selected_outcome'], 'decisive_completed_game']))
        settlement = dict(available=True, comparable=True, scope='decisive_completed_game',
            state_probabilities={'win': exact_wire(probability), 'loss': exact_wire(1 - probability)},
            venue_rules=dict(cashflow_states={'win': 'ordinary_win', 'loss': 'zero'}),
            assumptions=assumptions)
        baseline = dict(book=reference['book'], source=reference.get('source'), prices=reference['prices'],
            probability=reference['probability'], fair_decimal_odds=reference['fair_decimal_odds'],
            conditioning=reference['conditioning'], current_until=row['start_at'],
            return_percent=exact_wire(100 * (probability / price(row) - 1)))
    if terms:
        terms = dict(terms, evidence_class='public_estimate')
        assumptions.append('Fill uses the order book captured with this exact price and its size constraints.')
    else:
        cost = price(row)
        step = order_step(row)
        if step is None and row['venue'] == 'polymarket_us':
            step = Fraction(1)
            assumptions.append('Modeled in whole $1-payout contracts. Market execution minimum and tick are unverified.')
        if step is None:
            terms = dict(kind='stake', order_type='straight_stake', increment='0.01', minimum='0.01',
                         maximum=exact_wire(amount))
        else:
            terms = dict(kind='exchange', order_type='taker', increment=exact_wire(step), minimum=exact_wire(step),
                         asks=[dict(price=exact_wire(cost), quantity=exact_wire(amount / cost))])
        terms.update(evidence_class='public_estimate', pricing_model='posted_price',
                     evidence=dict(basis='posted_price', source_clocks=row.get('times'), depth_verified=False))
        assumptions.append('Modeled at the posted price. Available size and slippage are unverified.')
        terms['revision'] = hashed(terms)
    return dict(row, game_state='scheduled', pregame_reference=reference,
                settlement_assessment=settlement, sportsbook_baseline=baseline,
                valuation_fill_terms=terms, estimate_assumptions=assumptions)
