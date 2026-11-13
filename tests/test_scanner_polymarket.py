"""Current published standard contract economics for Scanner."""

from fractions import Fraction

import pytest

from app.comparison.current_dependencies import instant
from app.comparison.scanner_polymarket import PROFILE, _schedule_hashes, entry_fee, resolve


AT = instant('2026-11-13T02:00:00Z')
TERMS = (
    "This market will settle to the winner of the Philadelphia Eagles vs Dallas Cowboys professional football "
    "game scheduled for November 26, 2026 at 4:30PM ET (as of the listing of the event's first instrument). "
    "Overtime is included if played. If the game ends in a tie, the market will settle to $0.50. "
    "If the game is delayed, postponed, suspended or otherwise rescheduled to a date and time not within two "
    "days of the originally scheduled date and time, the market will settle to the last fair market price. "
    "Outcome sourced from the relevant governing body."
)


def inputs(side='Long'):
    long = side == 'Long'
    market, event = '2454047', '10448'
    outcome = '123' if long else '456'
    source = dict(provider='polymarket_us', native_event_id=event, native_market_id=market,
                  native_outcome_id=outcome, native_side=side, quote_side='buy')
    quote = dict(venue='polymarket_us', source=source, binding=dict(verified=True),
                 original=dict(units='usd_per_contract', quantity_units='contracts', payout_units='USD',
                               payout='1', value='0.2250'))
    if not long:
        quote['original'].update(transformation='one_minus_native_bid', native_value='0.7750',
                                 native_units='usd_per_contract')
    material = '1' * 64
    evidence = dict(
        phase='pregame', event=dict(league='NFL'), group=dict(market='winner', period='full_game'),
        native_market_type='football_team_full_game_winner',
        native_key=['polymarket_us', event, market, outcome, side], material_sha256=material,
        public_retail_observation=dict(market_id=market, instrument_id=outcome, long=long,
            is_combo=None, description=TERMS, material_sha256=material,
            values=dict(minimumTradeQty='0.01', orderPriceMinTickSize='0.0025', feeCoefficient='0.085')),
        native_contract=dict(scope=dict(overtime='included'), same_outcome=dict(
            predicate=dict(operator='gt' if long else 'le', domain='home_margin', threshold='0'),
            equality=dict(treatment='fraction', payout='1/2'))),
        fee_review=dict(profile=PROFILE, product='standard_sports', fee_rate='0.095',
                        reviewed_at='2026-11-12T22:37:00Z', verification_revision='test-verified-review',
                        standing_public_terms=True, review_before=None,
                        retrieval=dict(normalized_sha256=sorted(_schedule_hashes())[0])))
    return quote, evidence


@pytest.mark.parametrize('side,phase', [('Long', 'pregame'), ('Short', 'live')])
def test_direct_standard_terms_bind_side_and_fee_ceiling(side, phase):
    quote, evidence = inputs(side)
    evidence['phase'] = phase
    model = resolve(quote, evidence, at=AT)
    assert model['phase'] == phase
    assert model['grid'] == dict(minimum='0.01', increment='0.01', tick='0.0025',
                                 minimum_price='0.01', maximum_price='0.99')
    decisive = ('0', '1') if side == 'Long' else ('1', '0')
    assert model['payout'] == dict(below=decisive[0], equal='0.5', above=decisive[1], terminal=None)
    assert model['completion']['maximum'] == '2'
    assert model['completion']['original_start'] == '2026-11-26T21:30:00+00:00'
    assert model['completion']['terminal'] == 'discretionary_last_fair_market_price'
    assert model['fee']['coefficient'] == '0.095'
    assert model['fee']['clearing'] == '0'
    assert model['fee']['account_verified'] is False
    assert entry_fee(model, [(Fraction(100), Fraction(1, 2))]) == Fraction(119, 50)
    assert entry_fee(model, [(Fraction(15, 100), Fraction(1, 2))] * 2) == Fraction(1, 100)
    with pytest.raises(ValueError, match='polymarket_scanner_fill_outside_fee_scope'):
        entry_fee(model, [(Fraction(1), Fraction(199, 200))])


def test_expired_or_changed_schedule_and_unbound_market_refuse():
    quote, evidence = inputs()
    evidence['fee_review']['review_before'] = AT.isoformat()
    with pytest.raises(ValueError, match='polymarket_scanner_fee_review_unavailable'):
        resolve(quote, evidence, at=AT)
    evidence['fee_review']['review_before'] = None
    evidence['public_retail_observation']['instrument_id'] = 'unrelated'
    with pytest.raises(ValueError, match='polymarket_scanner_selected_market_unbound'):
        resolve(quote, evidence, at=AT)


def test_missing_exception_keeps_terminal_unknown_and_refuses_conflicting_tie():
    quote, evidence = inputs()
    evidence['public_retail_observation']['description'] = TERMS.split('If the game is delayed')[0]
    model = resolve(quote, evidence, at=AT)
    assert model['completion'] is None
    assert model['payout']['terminal'] is None
    evidence['public_retail_observation']['description'] = TERMS.replace('$0.50', '$0.25')
    with pytest.raises(ValueError, match='polymarket_scanner_tie_terms_conflict'):
        resolve(quote, evidence, at=AT)
