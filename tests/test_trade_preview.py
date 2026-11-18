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


def test_default_estimate_sizes_public_commission_without_execution_or_jurisdiction_proof():
    from app.comparison.pregame_estimate import inputs
    from app.comparison.pregame_valuation import valuation

    row = retail_row('NBA', '25/51')
    row.update(captured_at=AT.isoformat(), game_state='scheduled')
    row['trade_fee'] = outcome(row, at=AT, phase='scheduled', review=prophetx_review.__wrapped__())
    reference = dict(snapshot_id='coherent-two-sided-reference', source='sportsgameodds', book='fanduel',
        market=dict(family='moneyline', kickoff=row['start_at']), rules=None,
        selected_outcome='home', probability='0.5', fair_decimal_odds='2',
        prices=[dict(side=side, price_american='-110', alternate=False) for side in ('home', 'away')])
    row['pregame_reference'] = dict(available=False, reason='sportsbook_settlement_rules_unverified',
                                   observed_snapshot=reference)
    row['settlement_assessment'] = dict(available=False, reason='venue_settlement_rules_unverified')
    prepared = inputs(row, Fraction(100))
    model = valuation(prepared, Fraction(100), publication_id='root', snapshot_id='member')
    assert model['status'] == 'qualified'
    assert model['evidence_class'] == 'public_estimate'
    assert model['actual_outlay_usd'] == '100'
    assert model['states']['win']['net_receipt_usd'] == '201.92'
    assert model['states']['win']['settlement_fee_usd'] == '2.08'
    assert model['raw']['net_ev'] == '0.0096'
    assert model['assumptions']
    assert row['pregame_reference']['available'] is False
    unknown = dict(row, trade_fee=dict(available=False, reason='missing_schedule'))
    missing = valuation(inputs(unknown, Fraction(100)), Fraction(100), publication_id='root', snapshot_id='member')
    assert missing['status'] == 'indicative'
    assert 'net_ev' not in missing['raw']
    conflict = dict(row, settlement_assessment=dict(available=False, comparable=False, reason='settlement_scoring_mismatch'))
    assert inputs(conflict, Fraction(100)) is conflict


def test_default_polymarket_estimate_uses_whole_claims_and_highest_public_tier():
    from app.comparison.pregame_estimate import inputs
    from app.comparison.pregame_valuation import valuation
    from app.comparison.snapshot_polymarket_fee import order_fee

    at = PM_AT + timedelta(days=7)
    row = native('scheduled', 'Long', at=at)
    from app.comparison.snapshot_fee_scope import applicability
    row['fee_applicability'] = applicability(row['original_record'])
    row.update(captured_at=at.isoformat(), game_state='scheduled')
    review = dict(basis('polymarket_us', at=PM_AT), published_effective_from='2026-11-14T05:00:00Z',
                  reviewed_at=at.isoformat(), review_before=None, standing_public_terms=True)
    row['trade_fee'] = outcome(row, at=at, phase='scheduled', review=review)
    assert row['trade_fee']['available']
    # Older retained members have a verified fee but no execution grid.
    # The model must use payout contracts, rather than interpreting dollars as stake.
    row.pop('original_record')
    row.pop('fee_applicability')
    reference = dict(snapshot_id='exact-pair', book='fanduel', market=dict(family='spread'),
        selected_outcome='home', probability='1/2', fair_decimal_odds='2', prices=[])
    row['pregame_reference'] = dict(available=False, observed_snapshot=reference)
    prepared = inputs(row, Fraction(100))
    model = valuation(prepared, Fraction(100), publication_id='root', snapshot_id='member')
    assert model['status'] == 'qualified', model['reasons']
    quantity = Fraction(model['fill']['quantity'])
    assert quantity.denominator == 1
    audit = order_fee('market', inserted_at=at.isoformat(), evaluated_at=at.isoformat(),
                      fills=[dict(price='0.55', quantity=str(quantity))], tier='0.095')
    assert model['fees']['entry_usd'] == audit['entry_fees']
    assert Fraction(model['actual_outlay_usd']) <= 100
    assert any('minimum and tick are unverified' in item for item in model['assumptions'])
