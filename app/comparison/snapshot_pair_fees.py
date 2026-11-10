"""Retail fees for the exact cent allocation shown by the ordinary arb desk."""
from fractions import Fraction as F
from hashlib import sha256

from .cashflows import exact_wire as wire
from .current_dependencies import instant
from .snapshot_conservative import kalshi_public_fee, prophetx_market_commission, prophetx_public_fee
from .snapshot_fee_scope import ROOT
from .snapshot_polymarket_fee import PROFILE, public_fee


def _leg_fee(row, *, stake, price, quantity, receipts):
    fee = row.get('trade_fee') or {}
    if not fee.get('available'):
        return dict(available=False, reason=fee.get('reason') or 'fee_outcome_not_published')
    cashflows = fee['fee_cashflows']
    evidence = fee['evidence']
    venue = row['venue']
    if not stake:
        return dict(available=False, reason='pair_stake_rounds_to_zero')
    if 'winning_settlement_usd' in cashflows:
        if venue != 'prophetx':
            return dict(available=False, reason='pair_fee_size_unverified')
        fill = F(0)
        settlement = {state: prophetx_market_commission(
            rate=evidence['fee_rate'], cost_basis=stake, gross_payout=payout)[1]
            for state, payout in receipts.items()}
    else:
        settlement = dict.fromkeys(receipts, F(0))
        if quantity == 1:
            fill = F(cashflows['at_fill_usd'])
        elif (venue == 'novig' and fee['classification'] == 'exact_public'
              and evidence.get('fee_rate') == '0' and row.get('game_state') == 'scheduled'):
            fill = F(0)
        else:
            if venue in ('kalshi', 'polymarket_us') and quantity.denominator != 1:
                return dict(available=False, reason='pair_size_unsupported')
            at = row['captured_at']
            if venue == 'prophetx':
                model = prophetx_public_fee(dict(row, cost_per_normal_claim=wire(price)),
                                            at=at, review=evidence, quantity=quantity)
            elif venue == 'polymarket_us' and evidence.get('order_inserted_at'):
                model = public_fee(row, at=instant(evidence['order_inserted_at']),
                                   phase=evidence['phase'], review=dict(evidence, profile=PROFILE), quantity=quantity)
            elif venue == 'kalshi' and evidence.get('path'):
                # The captured revision must still match the witness on disk.
                path = ROOT / evidence['path']
                if sha256(path.read_bytes()).hexdigest() != evidence['sha256']:
                    return dict(available=False, reason='pair_fee_witness_changed')
                model = kalshi_public_fee(row, at=at, review=evidence, quantity=quantity)
                if model['available'] and model['evidence']['metadata_revision'] != evidence.get('metadata_revision'):
                    return dict(available=False, reason='pair_fee_witness_changed')
            else:
                return dict(available=False, reason='pair_fee_size_unverified')
            if not model['available']:
                return dict(available=False, reason=model.get('reason') or 'pair_fee_size_unverified')
            fill = F(model['trade_fee_usd'])
    return dict(available=True, classification=fee['classification'], quantity=wire(quantity),
                at_fill_usd=wire(fill), settlement_usd={state: wire(amount) for state, amount in settlement.items()})


def pair_fees(proof, allocation, rows):
    """Model captured completed-game states, with fees in addition to stakes."""
    payouts = proof.get('settlement_payouts')
    if not payouts:
        return dict(available=False, reason='pair_settlement_unverified', legs=[])
    legs, receipts = [], []
    for index, (row, leg) in enumerate(zip(rows, allocation['legs'], strict=True)):
        stake, price = F(leg['allocation_usd']), F(leg['cost_per_claim'])
        quantity = stake / price
        receipts.append({state: quantity * F(sides[index]) for state, sides in payouts.items()})
        try:
            fee = _leg_fee(row, stake=stake, price=price, quantity=quantity, receipts=receipts[-1])
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
            fee = dict(available=False, reason='pair_fee_size_unverified')
        legs.append(fee)
    if not all(leg['available'] for leg in legs):
        return dict(available=False, reason='pair_missing_leg_fees', legs=legs)
    funding = F(allocation['funding_usd']) + sum(F(leg['at_fill_usd']) for leg in legs)
    states = {}
    for state in payouts:
        net_receipt = sum(payout[state] - F(leg['settlement_usd'][state])
                          for payout, leg in zip(receipts, legs, strict=True))
        states[state] = dict(net_receipt_usd=wire(net_receipt), net_profit_usd=wire(net_receipt - funding))
    minimum = min(F(state['net_profit_usd']) for state in states.values())
    return dict(available=True, legs=legs, funding_usd=wire(funding), states=states,
                minimum_net_profit_usd=wire(minimum))
