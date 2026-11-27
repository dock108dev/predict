from copy import deepcopy
from fractions import Fraction as F

import pytest

from app.comparison import execution_contract
from app.comparison.experiment_depth_execution import FIXED_PROFIT_VERSION, evaluate, evaluate_at_stake
from tests.test_experiment_depth_execution import receipt
from tests.test_paper_experiments import frozen_priced


AT = '2026-11-27T23:50:00Z'
START = '2026-11-28T00:00:00Z'


def admitted(*levels, league='NCAAB', family='spread', side='home', line='-10.5',
             complete=True, coefficient='0', equality='not_possible'):
    return dict(receipt(*levels, complete=complete, coefficient=coefficient),
                 received_at='2026-11-27T23:49:57Z', source_at='2026-11-27T23:49:56Z',
                 valid_until='2026-11-27T23:50:06Z', currency='USD',
                 contract=dict(league=league, family=family, period='full_game', starts_at=START,
                     selected_side=side, signed_line=line, phase='pregame',
                     settlement=dict(available=True, rule_id='reviewed-example', overtime='included',
                         equality=equality)))


def preview(book, *, stake='8', probability='.3', minimum='.04', **kwargs):
    return evaluate_at_stake(book, at=AT, stake=stake, probability=probability, minimum=minimum, **kwargs)


def test_partial_has_own_ev_payout_and_cash_commitment():
    book = admitted(('.25', 2000))
    result = preview(book)
    assert result['status'] == 'partial_size' and result['size_status'] == 'partial_size'
    assert result['available_native_quantity'] == '2000'
    assert result['available_purchase_usd'] == result['modeled_stake_usd'] == '5'
    assert result['modeled_win_profit_usd'] == '15'
    assert result['modeled_loss_usd'] == '-5'
    assert result['modeled_net_ev'] == '0.2'
    assert result['modeled_cashflows']['loss']['net_profit_usd'] == '-5'
    assert result['supported_eligible'] and not result['eligible']
    assert result['book_received_at'] == book['received_at']
    assert result['book_source_at'] == book['source_at']
    assert result['as_of'] == '2026-11-27T23:50:00+00:00'


def test_native_price_can_be_eligible_despite_a_negative_proxy_screen():
    book = admitted(('.30', 12000))
    assert F('.4') / F('.5') - 1 < 0
    result = preview(book, stake='25', probability='.4')
    assert result['price_limit_policy'] == 'native_discovery'
    assert result['status'] == 'full_size' and result['eligible']
    assert result['modeled_average_price'] == '0.3'
    assert F(result['modeled_net_ev']) == F(1, 3)


def test_requested_size_uses_both_price_levels_and_ceil_fees():
    book = admitted(('.20', 1000, 1000), ('.25', 2000, 2000), coefficient='.03')
    result = preview(book, stake='7.16')
    assert result['status'] == 'full_size' and result['eligible']
    assert result['modeled_native_quantity'] == '2999'
    assert result['modeled_purchase_usd'] == '6.9975'
    assert result['modeled_fee_usd'] == '0.16045'
    assert result['modeled_stake_usd'] == '7.15795'
    assert result['modeled_win_profit_usd'] == '22.83205'
    assert not result['fee_is_upper_bound']


@pytest.mark.parametrize('levels,complete,status', [
    ([], True, 'confirmed_empty'), ([('.30', 100)], True, 'above_limit'),
    ([('.235', 1000)], False, 'unknown'),
])
def test_empty_above_limit_and_truncation_remain_distinct(levels, complete, status):
    result = preview(admitted(*levels, complete=complete), price_limit='.25')
    assert result['status'] == status and not result['eligible']
    if status == 'unknown':
        assert result['reason'] == 'truncated'
        assert result['availability_is_lower_bound']
        assert result['available_purchase_usd'] == '2.35'
        assert result['modeled_net_ev'] is not None


def test_invalid_currency_or_source_clock_never_qualifies_depth():
    book = admitted(('.25', 5000))
    assert preview(dict(book, currency='CAD'))['reason'] == 'depth_currency_unverified'
    assert preview(dict(book, valid_until='2026-11-27T23:49:58Z'))['reason'] == 'stale'
    assert preview(dict(book, source_at='2026-11-27T23:49:57.000000001Z'))['reason'] == 'depth_source_clock_invalid'
    assert preview(dict(book, received_at='2026-11-27T23:50:00.000000001Z'))['reason'] == 'depth_receipt_outside_decision'
    assert preview(None)['reason'] == 'no_book_receipt'


def test_whole_line_keeps_size_and_requires_a_qualified_refund_partition():
    book = admitted(('.25', 2000), line='-3', equality='push_refund')
    book['contract']['settlement']['equality_cashflow'] = 'full_outlay'
    no_probability = preview(book, stake='5', probability='.27')
    assert no_probability['status'] == 'unknown' and no_probability['full_size_supported']
    assert no_probability['reason'] == 'depth_equality_probability_unverified'
    modeled = preview(book, stake='5', probability='.27',
        probabilities={'win': '.243', 'loss': '.657', 'refund': '.1'},
        cashflow_rules={'reference_equivalent': True, 'refund': 'full_outlay'})
    assert modeled['eligible'] and modeled['modeled_net_ev'] == '0.072'
    assert modeled['modeled_cashflows']['refund']['net_profit_usd'] == '0'


def test_ice_hockey_scoring_and_nfl_tie_have_explicit_economics():
    nhl = admitted(('.25', 2000), league='NHL')
    nhl['contract']['settlement'].update(shootout='official_final_score', shootout_count='different')
    assert preview(nhl, stake='5')['reason'] == 'depth_settlement_scoring_mismatch'
    nhl['contract']['settlement']['shootout_count'] = 'one_goal_to_winning_team'
    assert preview(nhl, stake='5')['eligible']
    nfl = admitted(('.625', 1000), league='NFL', family='moneyline', line=None, equality='half_face')
    values = preview(nfl, stake='6.25', probability='.7', probabilities={'win': '.63', 'loss': '.27', 'tie': '.1'},
        cashflow_rules={'reference_equivalent': True, 'tie': {'face_fraction': '.5'}})
    assert values['eligible']
    assert values['modeled_cashflows']['tie']['net_profit_usd'] == '-1.25'
    assert values['modeled_net_ev'] == '0.088'


def test_prophetx_stake_value_and_late_commission_are_distinct():
    book = admitted(('33/58', '1387.08'))
    book.update(venue='prophetx', quantity_unit='usd_stake', quantity_increment='.01', quantity_minimum='1',
                legal_prices=['33/58'], fee=dict(model='prophetx_market_commission', rate='.02',
                    rounding='nearest_cent_profit_then_commission', schedule_revision='account-qualified-fixture'))
    result = preview(book, stake='100', probability='.6')
    assert result['eligible'] and result['quantity_unit'] == 'usd_stake'
    assert result['available_purchase_usd'] == '1387.08'
    assert result['modeled_native_quantity'] == result['modeled_stake_usd'] == '100'
    assert result['modeled_win_profit_usd'] == '74.24'
    assert result['modeled_fee_usd'] == '1.52' and result['modeled_entry_fee_usd'] == '0'
    assert result['modeled_net_ev'] == '0.04544'
    unknown = preview(dict(book, fee={'reason': 'prophetx_account_fee_schedule_unverified'}), stake='100')
    assert unknown['status'] == 'unknown' and unknown['available_purchase_usd'] == '1387.08'


def test_fixed_profit_v2_enforces_exact_signed_line_and_separates_full_size_below_ev():
    offer = frozen_priced('+300', venue='novig', ev='.05', line='-10.5')
    offer['record']['event'].update(competition='NCAAB', scheduled_start=START)
    book = admitted(('.25', 5000, 5000), coefficient='.03')
    result, grade = evaluate(offer, book, at=AT, game_key='g', target=25, minimum='.04', version=FIXED_PROFIT_VERSION)
    assert result['status'] == 'below_ev_floor' and result['full_size_supported']
    assert result['size_status'] == 'full_size' and not result['eligible'] and grade is None
    assert F(result['modeled_net_ev']) < F('.04')
    wrong = deepcopy(book)
    wrong['contract']['signed_line'] = '-16.5'
    invalid, _ = evaluate(offer, wrong, at=AT, game_key='g', target=25, minimum='.04', version=FIXED_PROFIT_VERSION)
    assert invalid['reason'] == 'depth_native_identity_mismatch'
    assert preview(wrong, expected=execution_contract.expected(offer['record']))['reason'] == 'depth_native_identity_mismatch'
    # Earlier frozen runs still interpret the original contract by the pilot.
    old, _ = evaluate(offer, book, at=AT, game_key='g', target=25, minimum='.04')
    assert old['status'] == 'full_size' and old['reason'] == 'net_ev_below_minimum'


def test_fixed_profit_v2_prophetx_sizes_net_of_settlement_commission():
    offer = frozen_priced('+150', venue='prophetx', ev='.15', line='-10.5')
    offer['record']['event'].update(competition='NCAAB', scheduled_start=START)
    book = admitted(('.4', '100'))
    book.update(venue='prophetx', quantity_unit='usd_stake', quantity_increment='.01', quantity_minimum='1',
                legal_prices=['.4'], fee=dict(model='prophetx_market_commission', rate='.02',
                    rounding='nearest_cent_profit_then_commission', schedule_revision='account-qualified-fixture'))
    result, grade = evaluate(offer, book, at=AT, game_key='g', target=25, minimum='.04', version=FIXED_PROFIT_VERSION)
    assert result['status'] == 'full_size' and result['eligible']
    assert result['modeled_stake_usd'] == '17.01'
    assert result['modeled_fee_usd'] == '0.51'
    assert result['modeled_win_profit_usd'] == '25'
    assert F(grade['fee']['cashflows']['win']['net_receipt_usd']) == F('42.01')
    old, _ = evaluate(offer, book, at=AT, game_key='g', target=25, minimum='.04')
    assert old['status'] == 'unknown'
