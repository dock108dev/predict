"""Exact inspection values derived from the same captured models as the desk."""
from decimal import Decimal
from fractions import Fraction

from .cashflows import exact_wire as wire
from .conditional_benchmark import basis
from .current_dependencies import instant
from app.fees.evidence import applies

FEE_REQUIREMENTS = {
    'kalshi': 'A reviewed account result requires the applicable instrument terms, account channel, membership, precision and intermediary charges.',
    'polymarket_us': 'A reviewed result requires the account taker coefficient, its effective dates and any override.',
    'novig': 'The public zero-fee review covers eligible pregame straight trades within its effective dates. Live trades need separate fee evidence.',
    'prophetx': 'A reviewed result requires the account agreement, fee model, rate, assessment basis, rounding and effective dates.',
}


def starting_fee_terms(row, captured_at, assumptions=None):
    """Describe the saved fee inputs independently of offer eligibility."""
    venue = row.get('venue')
    if (row.get('source') or {}).get('provider') == 'practice':
        rate = (assumptions or {}).get('fees', {}).get(venue)
        if rate is None:
            return None
        return dict(values=[['Fictional assumption', f'{wire(100 * Fraction(rate))}% of acquisition cost']],
                    scope='Used only in the synthetic fee scenario.')
    if venue not in FEE_REQUIREMENTS:
        return None
    try:
        at = instant(captured_at)
        captured = (row.get('trade_fee') or {}).get('evidence') or {}
        if not captured.get('schedule_revision'):
            captured = (row.get('conservative_trade_benchmark') or {}).get('evidence') or {}
        review = captured if captured.get('schedule_revision') else basis(venue, at=at)
        in_window = applies(review, at)
        rate = review['fee_rate']
        if venue == 'novig':
            native = ((row.get('trade_fee') or {}).get('evidence') or {}).get('native')
            if native:
                terms = native['market_fee']
                values = [['Captured market coefficient', terms['coefficient']],
                          ['Charge condition', terms['charged']], ['Observed event state', native['event_status']]]
                scope = 'One immediate taker fill. Each native contract pays $0.01; 100 pay $1. Multi-price fills are not modeled.'
            else:
                values = [['Recorded pregame fee', f'${Decimal(rate):.2f} per $1 claim']]
                scope = 'Eligible pregame straight trades. Live trades require separate fee evidence.'
        elif venue == 'kalshi':
            values = [['Standard starting formula', f'{rate} × price × (1 − price) per contract']]
            scope = 'Before series or event adjustments and account rounding. Price is the acquisition cost in dollars.'
        elif venue == 'polymarket_us':
            from .snapshot_polymarket_fee import PROFILE
            if review.get('profile') == PROFILE:
                values = [['Standard taker tiers', ' / '.join(review['allowed_taker_coefficients'])],
                          ['Manual retail estimate', f'{rate} × contracts × acquired price × (1 − acquired price)']]
                scope = ('Highest published standard tier at order insertion. Half-even cent rounding and cumulative '
                         'order cap apply. Assumed rebates are $0. Personal tiers and overrides require account evidence.')
            else:
                initial = basis(venue)['fee_rate']
                values = [['Historical assumption', f'{initial} taker coefficient']]
                if tiers := review.get('allowed_taker_coefficients'):
                    values.append(['Recorded taker tiers', ' / '.join(tiers)])
                scope = 'The coefficient multiplies price × (1 − price) before rounding. The applicable account tier is required.'
        elif row.get('league') == 'NHL' and (nhl := review.get('nhl_taker_coefficient')):
            values = [['Recorded public NHL taker formula', f'{nhl} × price × (1 − price) per contract']]
            scope = 'Public site, before rounding. Negotiated account terms may differ.'
        else:
            values = [['Recorded public commission', f'{wire(100 * Fraction(rate))}% of positive net gains per market']]
            scope = 'Public-site straight trades under the recorded schedule. Negotiated account terms may differ.'
        return dict(values=values, scope=scope, review_ends_at=review['review_before'], in_review_window=in_window)
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError):
        return dict(values=[], scope='The recorded starting fee terms could not be verified for this capture.')


def offer_disclosures(row, captured_at, originals, assumptions=None):
    from .inspection_settlement import settlement_terms

    original = next((quote for quote in originals if quote.get('id') == row['id']), None)
    return dict(starting_fee_terms=starting_fee_terms(row, captured_at, assumptions),
                settlement=settlement_terms(row, original))


def offer_math(row):
    """Expose calculation inputs and cashflows without filling unsupported values."""
    cost = row.get('cost_per_normal_claim')
    probability = row.get('probability')
    gross = dict(cost_usd=cost, win_receipt_usd=None, win_profit_usd=None,
                 loss_profit_usd=None, expected_profit_usd=row.get('gross_profit_per_claim'),
                 risk_usd=cost, return_percent=row.get('gross_return_percent'))
    if cost is not None:
        gross.update(win_receipt_usd='1', win_profit_usd=wire(1-Fraction(cost)),
                     loss_profit_usd=wire(-Fraction(cost)))
    reference = dict(row.get('reference_calculation') or {})
    if reference.get('available') and reference.get('pair'):
        reference['implied_probabilities'] = [wire(1/Fraction(leg['original']['value']))
                                               for leg in reference['pair']]
    reviewed = dict(row.get('conditional_trade_benchmark') or {})
    if reviewed.get('available') and all(reviewed.get(k) is not None for k in ('normalization_risk_usd', 'normal_win_receipt_usd')):
        risk = Fraction(reviewed['normalization_risk_usd'])
        reviewed.update(win_profit_usd=wire(Fraction(reviewed['normal_win_receipt_usd']) - risk),
                        loss_profit_usd=wire(-risk))
    elif row.get('source', {}).get('provider') != 'practice':
        reviewed['required_evidence'] = FEE_REQUIREMENTS.get(row.get('venue'))
    return dict(original=row.get('original'), source=row.get('source'), selection=row.get('selection'),
                market=row.get('market'), clocks=row.get('times'),
                probability=probability, fair_reference=reference, before_fees=gross,
                trade_fee=row.get('trade_fee'), reviewed=reviewed,
                conservative=row.get('conservative_trade_benchmark'),
                assumed_scenario=row.get('math'), fee_applicability=row.get('fee_applicability'),
                metric_status=row.get('metric_status', {}),
                identity=dict(binding=row.get('binding'), outcome=row.get('same_outcome'),
                              reference_reason=row.get('snapshot_benchmark_reason'),
                              probability_reason=row.get('probability_missing')))


def pair_math(proof, funding):
    """Separate exact equal-payout economics from a cent-rounded allocation."""
    roi = Fraction(proof['value']) / 100
    weights = [Fraction(weight) for weight in proof['weights']]
    # In the exact normalized proof, sum of costs = 1 / (1 + return).
    costs = [weight / (1 + roi) for weight in weights]
    exact = [funding * weight for weight in weights]
    first = min(funding, Fraction(round(exact[0] * 100), 100))
    amounts = [first, funding - first]
    receipts = [amount / cost for amount, cost in zip(amounts, costs)]
    profits = [receipt - funding for receipt in receipts]
    return dict(funding_usd=wire(funding), ideal_payout_usd=wire(funding * (1 + roi)),
                ideal_profit_usd=wire(funding * roi), minimum_profit_usd=wire(min(profits)),
                rounded_return_percent=wire(100 * min(profits) / funding),
                legs=[dict(cost_per_claim=wire(cost), ideal_allocation_usd=wire(ideal),
                           allocation_usd=wire(amount), win_receipt_usd=wire(receipt),
                           win_profit_usd=wire(profit))
                      for cost, ideal, amount, receipt, profit in zip(costs, exact, amounts, receipts, profits)],
                rounding='First allocation rounded to nearest cent, ties to even. Second receives the remainder.',
                missing=['Fees for each leg at the displayed quantity and fill pattern',
                         'Executable size at both prices', 'Joint void, cancellation and other exceptional settlement'])
