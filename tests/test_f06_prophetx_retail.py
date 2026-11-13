from datetime import timedelta
from fractions import Fraction as F

import pytest

from app.comparison.inspection_math import offer_math
from app.comparison.snapshot_conservative import metric, prophetx_market_commission, prophetx_public_fee
from app.comparison.snapshot_fee_outcome import EXPIRED, outcome
from app.dashboard.trade_desk import offer
from app.fees import schedule_lifecycle as lifecycle
from app.storage.store import stamp
from tests.test_trade_desk import quote

AT = stamp('2026-11-10T15:00:00Z')


@pytest.fixture
def review():
    approval = lifecycle.approved()
    state = dict(last_verified=dict(approval=approval, verified_at=AT.isoformat(),
        review_before=(AT + timedelta(hours=24)).isoformat(), revision='fixture',
        retrieval=dict(document=dict(sha256=approval['document_sha256']))))
    return lifecycle.basis(state, AT)


def retail_row(league, price):
    row = quote('prophetx-offer', 'prophetx')
    row.pop('reference')
    row.update(league=league, start_at=(AT + timedelta(hours=2)).isoformat(),
        source=dict(provider='the_odds_api', native_side='bookmaker_outcome'),
        original=dict(units='decimal_odds', value=str(1 / F(price))), times={},
        cost_per_normal_claim=price)
    return row


def test_official_single_fill(review):
    row = retail_row('NHL', '0.62')
    model = prophetx_public_fee(row, at=AT.isoformat(), review=review, quantity='100')
    assert model['available']
    assert model['quantity'] == '100' and model['fill_count'] == 1
    assert model['trade_fee_usd'] == '0.82'
    assert model['normalization_risk_usd'] == '62.82'
    assert model['normal_win_receipt_usd'] == '100'
    assert model['win_profit_usd'] == '37.18' and model['loss_profit_usd'] == '-62.82'
    assert model['details']['rounding_trace'] == [dict(quantity='100', price_usd='0.62',
        raw_fill_fee_usd='0.8246', carry_in_usd='0', fee_usd='0.82', carry_out_usd='0.0046')]


@pytest.mark.parametrize('phase', ['scheduled', 'live'])
def test_sgo_american_prices_use_retail_straight_fees_without_depth(review, phase):
    row = retail_row('NHL', '0.4')
    row['source']['provider'] = 'sportsgameodds'
    row['original'] = dict(units='american_odds', value='+150')
    row.pop('cost_per_normal_claim')
    if phase == 'live':
        row['start_at'] = (AT - timedelta(minutes=1)).isoformat()
    nhl = outcome(row, at=AT, phase=phase, review=review)
    assert nhl['fee_cashflows'] == {'at_fill_usd': '0.01'}
    nba = outcome(dict(row, league='NBA'), at=AT, phase=phase, review=review)
    assert nba['fee_cashflows'] == dict(at_fill_usd='0', winning_settlement_usd='0.02', losing_settlement_usd='0')


def test_official_split_fill(review):
    row = retail_row('NHL', '0.40')
    model = prophetx_public_fee(row, at=AT.isoformat(), review=review, fills=[(30, '0.40'), (70, '0.40')])
    assert model['available']
    assert model['quantity'] == '100' and model['fill_count'] == 2
    assert model['trade_fee_usd'] == '0.84' and model['normalization_risk_usd'] == '40.84'
    first, second = model['details']['rounding_trace']
    assert (first['fee_usd'], first['carry_out_usd']) == ('0.25', '0.002')
    assert (second['fee_usd'], second['carry_in_usd'], second['carry_out_usd']) == ('0.59', '0.002', '0')


def test_negative_carry_crosses_prices_and_resets_on_a_new_order(review):
    row = retail_row('NHL', '0.50')
    model = prophetx_public_fee(row, at=AT.isoformat(), review=review, fills=[(4, '0.50'), (1, '0.20')])
    first, second = model['details']['rounding_trace']
    assert (first['fee_usd'], first['carry_out_usd']) == ('0.04', '-0.005')
    assert (second['fee_usd'], second['carry_in_usd']) == ('0', '-0.005')
    assert model['normalization_risk_usd'] == '2.24'
    new_order = prophetx_public_fee(row, at=AT.isoformat(), review=review, fills=[(1, '0.20')])
    assert new_order['trade_fee_usd'] == '0.01'


@pytest.mark.parametrize('quantity,fills,reason', [
    (0, None, 'prophetx_positive_quantity_required'),
    (None, [], 'prophetx_nhl_fills_required'),
    (None, [(2, '1')], 'prophetx_invalid_nhl_fill'),
    (None, [(-1, '0.50')], 'prophetx_invalid_nhl_fill'),
    (2, [(1, '0.50')], 'prophetx_nhl_fill_quantity_mismatch'),
])
def test_invalid_sized_scenario_has_no_numeric_fee(review, quantity, fills, reason):
    model = prophetx_public_fee(retail_row('NHL', '0.50'), at=AT.isoformat(), review=review,
                                quantity=quantity, fills=fills)
    assert model['reason'] == reason
    assert 'trade_fee_usd' not in model


@pytest.mark.parametrize('cost,payout,expected', [
    (50, 100, 1),  # Official example, $50 net gain.
    (50, 0, 0),    # Losing position.
    (70, 100, F('0.60')),  # Same market, $50 gain offset by a $20 loss.
    (100, 100, 0),  # Same market, fully offsetting positions.
    (110, 100, 0),  # Same market, net loss.
])
def test_market_commission_on_positive_net_settlement_gain(review, cost, payout, expected):
    assert prophetx_market_commission(rate=review['fee_rate'], cost_basis=cost, gross_payout=payout) == (expected, expected)


@pytest.mark.parametrize('league,fee,expected_fee,win,loss', [
    ('NHL', '0.01', '0.01', '0.59', '-0.41'),
    ('NBA', '0.02', '0.012', '0.58', '-0.4'),
])
def test_decisive_payoff_keeps_fill_debit_separate_from_winning_commission(review, league, fee, expected_fee, win, loss):
    row = dict(retail_row(league, '0.40'), probability='0.60', gross_return_percent='50')
    model = metric(row, at=AT.isoformat(), review=review)
    assert model['trade_fee_usd'] == fee and model['expected_trade_fee_usd'] == expected_fee
    assert (model['win_profit_usd'], model['loss_profit_usd']) == (win, loss)


@pytest.mark.parametrize('league,price,cashflows', [
    ('NHL', '0.62', dict(at_fill_usd='0.01')),
    ('NHL', '0.10', dict(at_fill_usd='0')),
    ('NBA', '0.62', dict(at_fill_usd='0', winning_settlement_usd='0.01', losing_settlement_usd='0')),
])
def test_ordinary_and_pinned_fee_share_normalized_timing_without_reference(review, league, price, cashflows):
    row = retail_row(league, price)
    row['trade_fee'] = outcome(row, at=AT, phase='scheduled', review=review)
    shown = offer(row, 'conservative_return_percent')
    pinned = offer_math(row)
    assert shown['current'] and not shown['reference_current']
    assert shown['trade_fee'] == pinned['trade_fee']
    assert shown['trade_fee']['quantity'] == '1' and shown['trade_fee']['fill_count'] == 1
    assert shown['trade_fee']['fee_cashflows'] == cashflows


def test_existing_scope_and_review_guards_remain_in_force(review):
    row = retail_row('NHL', '0.62')
    assert outcome(row, at=AT, phase='live', review=review)['reason'] == 'live_market_fee_evidence_unbound'
    row['start_at'] = (AT + timedelta(days=2)).isoformat()
    expired = outcome(row, at=stamp(review['review_before']), phase='scheduled', review=review)
    assert expired['reason'] == EXPIRED and not expired['available']
    model = prophetx_public_fee(retail_row('NBA', '0.62'), at=AT.isoformat(), review=review, fills=[(1, '0.62')])
    assert not model['available']
