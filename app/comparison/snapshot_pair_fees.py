"""Retail fees for the exact cent allocation shown by the ordinary arb desk."""
from fractions import Fraction as F
from hashlib import sha256

from .cashflows import exact_wire as wire
from .current_dependencies import instant
from .snapshot_conservative import kalshi_public_fee, prophetx_market_commission, prophetx_public_fee
from .snapshot_fee_scope import ROOT
from .snapshot_polymarket_fee import PROFILE, public_fee


def _leg_fee(row, *, stake, price, quantity, receipts, allow_fractional=False):
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
        if venue == 'novig' and (row.get('source') or {}).get('provider') == 'sportsgameodds':
            from app.fees.novig_v3 import retail_pregame_fill, taker_fill
            from .sgo_native_binding import fee_offer_identity

            if row.get('game_state') != 'scheduled':
                return dict(available=False, reason='pair_fee_size_unverified')
            if not evidence or fee_offer_identity(row['source']) != evidence.get('offer_identity'):
                return dict(available=False, reason='pair_fee_witness_changed')
            try:
                if price != F(evidence['fee_price']):
                    return dict(available=False, reason='pair_fee_witness_changed')
                if evidence.get('basis') == 'reviewed_retail_pregame_straight':
                    model = retail_pregame_fill(market_id=evidence['schedule_market_id'], review=evidence,
                        at=evidence['fee_evaluated_at'], price=price, quantity=quantity)
                else:
                    terms = evidence['catalog_fee_terms']
                    if terms.get('charged') != 'WHEN_LIVE':
                        return dict(available=False, reason='pair_fee_witness_changed')
                    model = taker_fill(market_id=evidence['native_market_id'], terms=terms,
                        event_status='OPEN_PREGAME', at=evidence['fee_evaluated_at'], price=price, quantity=quantity)
            except (ValueError, TypeError, KeyError, ArithmeticError):
                return dict(available=False, reason='pair_fee_size_unverified')
            if model['schedule_hash'] != evidence.get('schedule_hash'):
                return dict(available=False, reason='pair_fee_witness_changed')
            fill = model['amount']
            rounding_trace = model['trace']
            assumptions = model['assumptions']
        elif quantity == F(fee.get('quantity', '1')):
            fill = F(cashflows['at_fill_usd'])
        else:
            if not allow_fractional and venue in ('kalshi', 'polymarket_us') and quantity.denominator != 1:
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
    reserve = F(cashflows.get('held_reserve_usd', '0'))
    released = dict.fromkeys(receipts, F(0))
    if reserve:
        if reserve < 0 or quantity != F(fee.get('quantity', '1')):
            return dict(available=False, reason='pair_fee_size_unverified')
        released = {state: F(cashflows['reserve_released_usd'][state]) for state in receipts}
        if any(not 0 <= amount <= reserve for amount in released.values()):
            return dict(available=False, reason='pair_settlement_unverified')
    return dict(available=True, classification=fee['classification'], quantity=wire(quantity),
                at_fill_usd=wire(fill), settlement_usd={state: wire(amount) for state, amount in settlement.items()},
                reserve_usd=wire(reserve), reserve_released_usd={state: wire(amount) for state, amount in released.items()},
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
        try:
            if (depth and instant(depth['received_at']) == instant(row['times']['received_at'])
                    and F(depth['price']) == price and F(row.get('original', {}).get('payout', '1')) == 1):
                fee['depth_status'] = 'available' if F(depth['quantity']) >= quantity else 'insufficient'
                fee['depth_evidence'] = depth
        except (ValueError, KeyError, TypeError, ArithmeticError):
            pass
        step = (depth or {}).get('quantity_increment')
        if row['venue'] == 'kalshi':
            step = '1'
        elif row['venue'] == 'polymarket_us':
            retail = (row.get('fee_applicability') or {}).get('retail') or {}
            step = (retail.get('values') or {}).get('minimumTradeQty')
        fee['size_status'] = 'unverified'
        try:
            if step is not None and F(step) > 0:
                fee['quantity_increment'] = wire(F(step))
                fee['size_status'] = 'available' if quantity >= F(step) and not quantity % F(step) else 'unsupported'
        except (ValueError, TypeError, ArithmeticError):
            pass
        legs.append(fee)
    states_covered = list(payouts)
    omissions = ['void', 'cancellation', 'postponement', 'partial_completion']
    execution = next((reason for field, status, reason in (
        ('depth_status', 'insufficient', 'pair_execution_depth_insufficient'),
        ('size_status', 'unsupported', 'pair_size_unsupported'),
        ('depth_status', 'unverified', 'pair_execution_depth_unverified'),
        ('size_status', 'unverified', 'pair_order_increment_unverified'),
    ) if any(leg[field] == status for leg in legs)), None)
    scope = dict(basis='completed_game_at_captured_prices', states_covered=states_covered,
                 states_unverified=omissions, full_arbitrage_qualified=False,
                 execution_reason=execution)
    gross = {state: wire(sum(payout[state] for payout in receipts)) for state in payouts}
    acquisition = F(allocation['funding_usd'])
    scope.update(acquisition_usd=wire(acquisition), gross_receipts_usd=gross,
                 minimum_gross_payout_usd=wire(min(map(F, gross.values()))),
                 minimum_gross_profit_usd=wire(min(map(F, gross.values())) - acquisition))
    if not all(leg['available'] for leg in legs):
        reason = ('pair_stake_rounds_to_zero' if any(leg.get('reason')=='pair_stake_rounds_to_zero' for leg in legs)
                  else 'pair_missing_leg_fees')
        return dict(available=False, reason=reason, legs=legs, sizing=sizing, **scope)
    funding = acquisition + sum(F(leg['at_fill_usd']) + F(leg.get('reserve_usd', '0')) for leg in legs)
    scope['funding_usd'] = wire(funding)
    if execution in ('pair_execution_depth_insufficient', 'pair_size_unsupported'):
        return dict(available=False, reason=execution, legs=legs, sizing=sizing, **scope)
    states = {}
    for state in payouts:
        net_receipt = sum(payout[state] + F(leg.get('reserve_released_usd', {}).get(state, '0'))
                          - F(leg['settlement_usd'][state])
                          for payout, leg in zip(receipts, legs, strict=True))
        states[state] = dict(net_receipt_usd=wire(net_receipt), net_profit_usd=wire(net_receipt - funding))
    minimum = min(F(state['net_profit_usd']) for state in states.values())
    return dict(available=True, legs=legs, states=states,
                fee_basis='conservative' if any(leg.get('classification')=='conservative' for leg in legs) else 'captured_terms',
                minimum_net_payout_usd=wire(minimum + funding),
                minimum_net_profit_usd=wire(minimum), sizing=sizing, **scope)
