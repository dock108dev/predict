"""Size one read-only retail trade using its admitted quote and fee terms."""
import re
from fractions import Fraction as F

from .cashflows import exact_wire as wire
from . import snapshot_pair_fees


def parse_amount(value):
    if not re.fullmatch(r'[0-9]{1,7}(?:\.[0-9]{1,2})?', value):
        raise ValueError('Enter a dollar amount with at most two decimal places')
    amount = F(value)
    if not 0 < amount <= 1_000_000:
        raise ValueError('Enter an amount between $0.01 and $1,000,000')
    return amount


def order_step(row):
    venue = row['venue']
    if venue == 'polymarket_us':
        values = (row.get('fee_applicability') or {}).get('retail', {}).get('values') or {}
        try:
            return F(values['minimumTradeQty'])
        except (KeyError, ValueError, TypeError, ArithmeticError):
            return None
    if venue == 'kalshi' or venue == 'prophetx' and row['league'] == 'NHL':
        return F(1)
    if venue == 'novig':
        return F(1, 100)
    # An aggregate non-NHL ProphetX price only models dollars staked.
    return None


def preview(row, amount):
    cost = F(row.get('cost_per_normal_claim') or 0)
    if not 0 < cost < 1:
        return dict(available=False, reason='source_price_or_selection_unsupported')
    original_fee = row.get('trade_fee') or {}
    row = dict(row, fee_applicability=row.get('preview_fee_input') or row.get('fee_applicability'))
    step = order_step(row)
    if step is not None and step <= 0:
        return dict(available=False, reason='pair_size_unsupported')
    depth = row.get('book_size') or {}
    size_limit = F(depth['quantity']) if depth.get('quantity') is not None else None

    def fee(size):
        return snapshot_pair_fees._leg_fee(row, stake=size * cost, price=cost, quantity=size,
                                          receipts={'win': size, 'loss': F(0)}, allow_fractional=True)

    if step is None:
        quantity = amount / cost
    else:
        ceiling = amount // (cost * step)
        if size_limit is not None:
            ceiling = min(ceiling, size_limit // step)
        quantity = ceiling * step
    if quantity <= 0:
        return dict(available=False, reason='preview_size_unavailable')

    charge = fee(quantity)
    if charge['available'] and quantity * cost + F(charge['at_fill_usd']) > amount:
        if step is None:
            return dict(available=False, reason='pair_fee_size_unverified')
        low, high = 0, ceiling
        while low + 1 < high:
            mid = (low + high) // 2
            candidate = fee(mid * step)
            if not candidate['available']:
                return dict(available=False, reason=candidate['reason'])
            if mid * step * cost + F(candidate['at_fill_usd']) <= amount:
                low = mid
            else:
                high = mid
        if low == 0:
            return dict(available=False, reason='preview_size_unavailable')
        quantity = low * step
        charge = fee(quantity)

    acquisition = quantity * cost
    sportsbook = row.get('sportsbook_baseline') or {}
    result = dict(available=True, amount_usd=wire(amount), acquisition_usd=wire(acquisition),
                  gross_win_payout_usd=wire(quantity), gross_win_profit_usd=wire(quantity-acquisition),
                  quantity=wire(quantity) if step is not None else None,
                  quantity_unit='1¢ contracts' if row['venue'] == 'novig' else '$1 payout contracts',
                  modeled=step is None or not size_limit or bool(row.get('live_aggregate_desk')),
                  fee_available=charge['available'], fee_reason=charge.get('reason'))
    if row['venue'] == 'novig' and result['quantity'] is not None:
        result['quantity'] = wire(quantity * 100)
    if not charge['available']:
        return result
    upfront = acquisition + F(charge['at_fill_usd'])
    win_fee = F(charge['settlement_usd']['win'])
    loss_fee = F(charge['settlement_usd']['loss'])
    win_receipt = quantity - win_fee
    result.update(upfront_usd=wire(upfront), fee_at_entry_usd=wire(upfront-acquisition),
                  fee_if_win_usd=wire(win_fee), fee_timing=original_fee.get('fee_payment'),
                  net_win_payout_usd=wire(win_receipt), net_win_profit_usd=wire(win_receipt-upfront),
                  net_loss_usd=wire(upfront+loss_fee), classification=original_fee.get('classification'),
                  rounding_trace=charge.get('rounding_trace'))
    settlement = row.get('settlement_assessment')
    binary = settlement is None or (settlement.get('available') and
        set(settlement['state_probabilities']) == {'win', 'loss'})
    if sportsbook.get('probability') is not None and binary:
        probability = F(sportsbook['probability'])
        ev = probability * win_receipt - (1 - probability) * loss_fee - upfront
        result['estimated_return_percent'] = wire(100 * ev / upfront)
    return result
