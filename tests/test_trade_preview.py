from datetime import timedelta
from fractions import Fraction

from app.comparison.snapshot_fee_outcome import outcome
from app.comparison.trade_preview import preview
from app.comparison.conditional_benchmark import basis
from tests.test_f04_kalshi_public import input_row
from tests.test_f05_polymarket_public import AT as PM_AT, native
from tests.test_f06_prophetx_retail import AT, retail_row, review as prophetx_review
from tests.test_f07_desk import novig_schedule_quote


def sized(row, review, at):
    row.update(captured_at=at.isoformat(), game_state='scheduled')
    row['trade_fee'] = outcome(row, at=at, phase='scheduled', review=review)
    return preview(row, Fraction(10))


def test_prophetx_settlement_commission_and_indicative_return():
    row = retail_row('NBA', '25/51')
    row['sportsbook_baseline'] = {'probability': '1/2'}
    result = sized(row, prophetx_review.__wrapped__(), AT)
    assert result['upfront_usd'] == '10'
    assert result['fee_if_win_usd'] == '0.21'
    assert result['net_win_payout_usd'] == '20.19'
    assert result['net_win_profit_usd'] == '10.19'
    assert result['net_loss_usd'] == '10'
    assert result['estimated_return_percent'] == '0.95'


def test_prophetx_nhl_fee_fits_budget_and_uses_order_rounding():
    result = sized(retail_row('NHL', '0.40'), prophetx_review.__wrapped__(), AT)
    assert result['quantity'] == '24'
    assert result['fee_at_entry_usd'] == '0.2'
    assert result['upfront_usd'] == '9.8'
    assert result['net_win_profit_usd'] == '14.2'
    assert 'estimated_return_percent' not in result


def test_kalshi_sized_exchange_fee_does_not_scale_rounded_single_claim():
    row, review, at = input_row()
    row.update(cost_per_normal_claim='0.50', start_at=(at + timedelta(hours=1)).isoformat())
    result = sized(row, review, at)
    assert result['quantity'] == '19'
    assert result['fee_at_entry_usd'] == '0.34'
    assert result['upfront_usd'] == '9.84'
    assert result['modeled']


def test_polymarket_applied_tier_is_visible_and_uses_the_size_grid():
    row = native('scheduled', 'Long')
    from app.comparison.snapshot_fee_scope import applicability
    row['fee_applicability'] = applicability(row['original_record'])
    row['cost_per_normal_claim'] = '0.55'
    result = sized(row, basis('polymarket_us', at=PM_AT), PM_AT)
    assert result['quantity'] == '17'
    assert result['fee_at_entry_usd'] == '0.4'
    assert result['upfront_usd'] == '9.75'
    assert row['trade_fee']['evidence']['profile']
    assert row['trade_fee']['evidence']['coefficient'] == '0.095'


def test_confirmed_novig_zero_and_unknown_fee_are_distinct():
    row = dict(novig_schedule_quote('0.25'), league='NCAAB')
    result = preview(row, Fraction(10))
    assert result['quantity'] == '4000'
    assert result['fee_available'] and result['fee_at_entry_usd'] == '0'
    unknown = preview(dict(row, trade_fee={'available': False, 'reason': 'missing_terms'}), Fraction(10))
    assert unknown['available'] and not unknown['fee_available']
    assert unknown['fee_reason'] == 'missing_terms'
    assert unknown['gross_win_payout_usd'] == '40'
