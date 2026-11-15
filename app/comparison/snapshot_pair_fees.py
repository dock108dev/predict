"""Retail fees for the exact cent allocation shown by the ordinary arb desk."""
from fractions import Fraction as F
from hashlib import sha256

from .cashflows import exact_wire as wire
from .current_dependencies import instant
from .snapshot_conservative import kalshi_public_fee, prophetx_market_commission, prophetx_public_fee
from .snapshot_fee_scope import ROOT
from .snapshot_polymarket_fee import PROFILE, public_fee


def _leg_fee(row, *, stake, price, quantity, receipts):
    if not stake:
        return dict(available=False, reason='pair_stake_rounds_to_zero')
    fee = row.get('trade_fee') or {}
    if not fee.get('available'):
        return dict(available=False, reason=fee.get('reason') or 'fee_outcome_not_published')
    cashflows = fee['fee_cashflows']
    evidence = fee['evidence']
    venue = row['venue']
    rounding_trace = None
    assumptions = fee.get('assumptions', ())
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
        elif (row.get('source') or {}).get('provider') == 'practice' and fee['classification'] == 'synthetic':
            fill = F(evidence['fictional_rate']) * stake
        elif (venue == 'novig' and fee['classification'] == 'exact_public'
              and evidence.get('fee_rate') == '0' and row.get('game_state') == 'scheduled'):
            fill = F(0)
        else:
            if venue in ('kalshi', 'polymarket_us') and quantity.denominator != 1:
                return dict(available=False, reason='pair_size_unsupported')
            at = row['captured_at']
            if venue == 'prophetx':
                model = prophetx_public_fee(dict(row, cost_per_normal_claim=wire(price)),
                                            at=at, review=evidence, quantity=quantity, phase=row.get('game_state', 'scheduled'))
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
            rounding_trace = (model.get('details') or {}).get('rounding_trace')
            assumptions = model.get('assumptions', assumptions)
    return dict(available=True, classification=fee['classification'], quantity=wire(quantity),
                at_fill_usd=wire(fill), settlement_usd={state: wire(amount) for state, amount in settlement.items()},
                receipts_usd={state: wire(amount) for state, amount in receipts.items()},
                assumptions=assumptions, rounding_trace=rounding_trace)


def _whole_contract_allocation(allocation, rows):
    if {row['venue'] for row in rows} != {'kalshi', 'polymarket_us'}:
        return allocation, None
    pmus = next(row for row in rows if row['venue'] == 'polymarket_us')
    retail = (pmus.get('fee_applicability') or {}).get('retail') or {}
    try:
        minimum = F(retail['values']['minimumTradeQty'])
        costs = [F(leg['cost_per_claim']) for leg in allocation['legs']]
        requested = F(allocation['funding_usd'])
        # The common quantity uses whole USD payout contracts and must be a
        # multiple of the observed Polymarket US size grid.
        step = minimum.numerator
        if step <= 0:
            return allocation, None
        quantity = (requested // (step * sum(costs))) * step
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return allocation, None
    stakes = [quantity * cost for cost in costs]
    used = sum(stakes)
    sizing = dict(quantity=str(quantity), requested_stake_usd=wire(requested),
                  acquisition_usd=wire(used), unused_stake_usd=wire(requested - used),
                  basis='equal_whole_contracts_at_captured_prices', execution_qualified=False)
    return dict(funding_usd=wire(used), legs=[dict(cost_per_claim=wire(cost), allocation_usd=wire(stake))
                for cost, stake in zip(costs, stakes, strict=True)]), sizing


def pair_fees(proof, allocation, rows):
    """Model captured completed-game states, with fees in addition to stakes."""
    payouts = proof.get('settlement_payouts')
    if not payouts:
        return dict(available=False, reason='pair_settlement_unverified', legs=[])
    allocation, sizing = _whole_contract_allocation(allocation, rows)
    if sizing is not None and sizing['quantity'] == '0':
        return dict(available=False, reason='pair_size_unsupported', legs=[], sizing=sizing)
    legs, receipts = [], []
    depths = proof.get('depth_evidence') or [None] * len(rows)
    for index, (row, leg) in enumerate(zip(rows, allocation['legs'], strict=True)):
        stake, price = F(leg['allocation_usd']), F(leg['cost_per_claim'])
        quantity = stake / price
        receipts.append({state: quantity * F(sides[index]) for state, sides in payouts.items()})
        try:
            fee = _leg_fee(row, stake=stake, price=price, quantity=quantity, receipts=receipts[-1])
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
            fee = dict(available=False, reason='pair_fee_size_unverified')
        fee.update(acquisition_usd=wire(stake), quantity=wire(quantity))
        depth = depths[index]
        fee['depth_status'] = 'unverified'
        if (depth and depth.get('received_at') == row.get('times', {}).get('received_at')
                and F(depth['price']) == price and F(row.get('original', {}).get('payout', '1')) == 1):
            fee['depth_status'] = 'available' if F(depth['quantity']) >= quantity else 'insufficient'
            fee['depth_evidence'] = depth
        legs.append(fee)
    states_covered = list(payouts)
    omissions = ['void', 'cancellation', 'postponement', 'partial_completion']
    scope = dict(basis='completed_game_at_captured_prices', states_covered=states_covered,
                 states_unverified=omissions, full_arbitrage_qualified=False,
                 execution_reason=('pair_execution_depth_insufficient' if any(leg['depth_status']=='insufficient' for leg in legs)
                                   else 'pair_execution_depth_unverified' if any(leg['depth_status']!='available' for leg in legs)
                                   else None))
    if not all(leg['available'] for leg in legs):
        reason = ('pair_stake_rounds_to_zero' if any(leg.get('reason')=='pair_stake_rounds_to_zero' for leg in legs)
                  else 'pair_missing_leg_fees')
        return dict(available=False, reason=reason, legs=legs, sizing=sizing, **scope)
    funding = F(allocation['funding_usd']) + sum(F(leg['at_fill_usd']) for leg in legs)
    states = {}
    for state in payouts:
        net_receipt = sum(payout[state] - F(leg['settlement_usd'][state])
                          for payout, leg in zip(receipts, legs, strict=True))
        states[state] = dict(net_receipt_usd=wire(net_receipt), net_profit_usd=wire(net_receipt - funding))
    minimum = min(F(state['net_profit_usd']) for state in states.values())
    return dict(available=True, legs=legs, funding_usd=wire(funding), states=states,
                fee_basis='conservative' if any(leg.get('classification')=='conservative' for leg in legs) else 'captured_terms',
                minimum_net_payout_usd=wire(minimum + funding),
                minimum_net_profit_usd=wire(minimum), sizing=sizing, **scope)
