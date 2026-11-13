"""Kalshi public direct acquisition and exact contract cashflow evidence."""

from copy import deepcopy
from fractions import Fraction

import pytest

from app.comparison.conditional_benchmark import basis
from app.comparison.current_dependencies import instant
from app.comparison.scanner_kalshi import entry_fee, resolve
from app.fees.engine import Registry, calculate


AT = instant('2026-11-13T02:00:00Z')


def inputs(side='yes'):
    event_id = 'KXNFLGAME-26NOV12WASNYG'
    market_id = event_id + '-NYG'
    source = dict(provider='kalshi', native_event_id=event_id, native_market_id=market_id,
                  native_outcome_id=side, native_side=side, quote_side='buy')
    quote = dict(venue='kalshi', source=source, original=dict(units='usd_per_contract',
                 quantity_units='contracts', payout_units='USD', payout='1', value='0.50'))
    terms = dict(rules_primary='If New York wins, then the market resolves to Yes.',
                 rules_secondary='If the game ends in a tie, the market will resolve to $0.50 for each team. '
                 'If the game is not started within 48 hours, the market will resolve to a fair price.')
    market_hash = '1' * 64
    review = dict(basis('kalshi', at=AT), standing_public_terms=True, review_before=None,
                  reviewed_at='2026-11-12T22:30:14Z', verification_revision='verified-public-review')
    return quote, dict(native_key=['kalshi', event_id, market_id, side, side], material_sha256=market_hash,
                       group=dict(period='full_game', market='winner'), event=dict(league='NFL'),
                       series_id='KXNFLGAME', fee_review=review, **terms,
                       combined_native_binding=dict(original_terms=terms),
                       selected_market_observation=dict(status='observed', native_event_id=event_id,
                           native_market_id=market_id, material_sha256=market_hash,
                           source=dict(body_sha256='2' * 64), values=dict(notional_value_dollars='1.00',
                               price_ranges=[dict(start='0', end='1', step='0.01')])) )


def test_exact_direct_series_binary_claim_and_retained_tie_with_unknown_terminal():
    quote, evidence = inputs()
    model = resolve(quote, evidence, at=AT)
    assert model['fee']['account_verified'] is False
    assert model['fee']['context']['balance_precision'] == '0.0001'
    assert model['grid'] == dict(minimum='1', increment='1', tick='0.01', price_ranges=[['0','1','0.01']])
    assert model['payout'] == dict(below=None, equal='0.5', above=None, terminal=None, binary_face='1')
    assert model['completion']['terminal'] == 'exchange_discretionary_fair_price'
    assert entry_fee(model, [(Fraction(1), Fraction('0.50'))]) == Fraction('0.0175')
    assert entry_fee(model, [(Fraction(1), Fraction('0.01'))]) == Fraction('0.0007')
    assert model['evidence']['market_receipt'] == evidence['selected_market_observation']['source']['body_sha256']


def test_no_side_uses_native_yes_price_grid_and_refuses_market_drift():
    quote, evidence = inputs('no')
    quote['original']['value'] = '0.795'
    evidence['selected_market_observation']['values']['price_ranges'] = [
        dict(start='0', end='0.2', step='0.01'), dict(start='0.2', end='1', step='0.005')]
    model = resolve(quote, evidence, at=AT)
    assert model['grid']['price_ranges'] == [['0', '0.8', '0.005'], ['0.8', '1', '0.01']]
    with pytest.raises(ValueError, match='kalshi_fill_grid_conflict'):
        entry_fee(model, [(Fraction(1), Fraction('0.805'))])
    evidence['selected_market_observation']['material_sha256'] = '3' * 64
    with pytest.raises(ValueError, match='kalshi_market_grid_unbound'):
        resolve(quote, evidence, at=AT)


def test_fragment_upper_bound_covers_engine_fees_for_same_and_mixed_prices():
    quote, evidence = inputs()
    model = resolve(quote, evidence, at=AT)
    prices = ['0.20', '0.41', '0.50']
    quantities = ['0.03', '0.17', '1.00']
    fills = [dict(fill_id=str(i), order_id='sample', role='taker', price=price,
                  quantity=quantity, unit='contracts') for i,(quantity,price) in enumerate(zip(quantities, prices))]
    fee = model['fee']
    audit = calculate(dict(fee['context'], fills=fills), Registry(fee['registry']))
    pairs = [(Fraction(quantity), Fraction(price)) for quantity,price in zip(quantities, prices)]
    assert entry_fee(model, pairs) >= Fraction(audit['entry_fees'])


def test_expired_review_crossed_identity_and_unknown_tie_stay_unbound():
    quote, evidence = inputs()
    expired = deepcopy(evidence)
    expired['fee_review']['review_before'] = AT.isoformat()
    with pytest.raises(ValueError, match='kalshi_fee_review_unavailable'):
        resolve(quote, expired, at=AT)
    crossed = deepcopy(evidence)
    crossed['series_id'] = 'KXNBAGAME'
    with pytest.raises(ValueError, match='kalshi_series_fee_scope_unbound'):
        resolve(quote, crossed, at=AT)
    evidence['combined_native_binding']['original_terms']['rules_secondary'] = evidence['rules_secondary'] = ''
    assert resolve(quote, evidence, at=AT)['payout']['equal'] is None


def test_fractional_grid_does_not_certify_scalar_tie_net_of_settlement_rounding():
    quote, evidence = inputs()
    evidence['selected_market_observation']['values']['fractional_trading_enabled'] = True
    model = resolve(quote, evidence, at=AT)
    assert model['grid']['minimum'] == '0.01'
    assert model['payout']['equal'] is None
