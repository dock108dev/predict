"""Shared payoff calculation for a captured ordinary comparison pair."""

from fractions import Fraction

from .cashflows import exact_wire
from .inspection_math import pair_math
from .snapshot_pair_fees import pair_fees

DEFAULT_FUNDING = Fraction(100)


def evaluate(proof, legs, funding):
    inspection = pair_math(proof, funding)
    payoff = pair_fees(proof, inspection, legs)
    score = (100 * Fraction(payoff['minimum_net_profit_usd']) / Fraction(payoff['funding_usd'])
             if payoff['available'] else None)
    return dict(inspection=inspection, retail_payoff=payoff,
                score=None if score is None else exact_wire(score))


def fee_identity(legs):
    from app.storage.store import hashed

    return [hashed(row.get('trade_fee')) for row in legs]


def current_payoff(pair, legs, funding):
    saved = pair.get('default_funding_result') if funding == DEFAULT_FUNDING else None
    if saved is not None and pair.get('default_funding_fee_identity') == fee_identity(legs):
        return saved
    return evaluate(pair['before_fees'], legs, funding)
