from copy import deepcopy
from fractions import Fraction as F

import pytest

from app.comparison.pregame_valuation import board_order, drawer_order, score, valuation


def fixture_terms(**cash):
    return dict(kind='stake', order_type='straight_stake', revision='saint-marys-fixture-fill-1',
        venue_type='marketplace', increment='0.01', minimum='0.01', maximum='1000',
        evidence_class='fixture', evidence={'source': 'Sprint 3 worked sample (simulation)'},
        cash_terms=dict(order_type='straight_stake', flat_entry_usd='0.75', **cash,
                        evidence={'class': 'fixture', 'source': 'Sprint 3 worked sample (simulation)',
                                  'revision': 'saint-marys-fixture-fee-1'}))


def fixture_offer():
    terms = fixture_terms()
    return dict(id='prophetx-fixture', evidence_result_id='fixture-member', venue='prophetx',
        original=dict(units='american_odds', value='+112', payout='1'),
        pregame_reference=dict(available=True, snapshot_id='fixture-reference', bet_id='saint-marys-minus-18.5',
                               probability='0.5', rules={'evidence': 'fixture'}, conditioning=None),
        settlement_assessment=dict(available=True, comparable=True,
            state_probabilities={'win': '0.5', 'loss': '0.5'}, venue_rules={'evidence': 'fixture'}),
        valuation_fill_terms=terms)


def evaluate(row=None, amount=25):
    return valuation(row or fixture_offer(), amount, publication_id='root-1', snapshot_id='snapshot-1')


def test_unit_drives_all_in_stake_and_raw_math():
    result = evaluate()
    assert result['status'] == 'qualified'
    assert result['fill']['stake_usd'] == '24.25'
    assert result['fees']['entry_usd'] == '0.75'
    assert result['states']['win']['net_receipt_usd'] == '51.41'
    assert result['display'] == dict(selected_usd='25.00', actual_outlay_usd='25.00', stake_usd='24.25',
        fee='$0.75', after_fee_odds='+106', expected_net_profit_usd='0.71', net_ev='+2.82%',
        opportunity_score='267')
    assert F(result['raw']['opportunity_score']) == F(705000, 2641)
    assert result['raw']['net_ev'] == '0.0282'
    for amount in ('0', '-1', '0.001', '1000000.01'):
        with pytest.raises(ValueError):
            evaluate(amount=amount)
    assert evaluate(amount=None)['reasons']['size'] == 'unit_size_unset'
    assert evaluate(amount=None)['actual_outlay_usd'] is None


@pytest.mark.parametrize('basis, ev, shown_score, fee', [
    ('full_outlay', '0.02538', '267', 'Varies'),
    ('stake_only', '0.02238', '235', '$0.75'),
])
def test_push_state_changes_cash_flow_and_score(basis, ev, shown_score, fee):
    row = fixture_offer()
    settlement = row['settlement_assessment']
    settlement.update(state_probabilities=dict(win='0.45', loss='0.45', refund='0.10'),
                      refund_cashflows=dict(venue=basis))
    result = evaluate(row)
    assert result['raw']['net_ev'] == ev
    assert result['display']['opportunity_score'] == shown_score
    assert result['display']['fee'] == fee


def test_walk_asks_and_use_actual_outlay():
    row = fixture_offer()
    row['original'] = dict(units='usd_per_contract', value='0.48', payout='1')
    terms = row['valuation_fill_terms']
    terms['cash_terms'].update(flat_entry_usd='0', order_type='taker')
    terms.update(kind='exchange', order_type='taker', increment='1', minimum='1', maximum=None,
                 asks=[dict(price='0.48', quantity='12'), dict(price='0.49', quantity='100')])
    first = evaluate(row, '5.80')
    assert first['status'] == 'qualified'
    assert first['actual_outlay_usd'] == '5.76'
    assert first['fill']['quantity'] == '12'
    assert first['display']['fee'] == '$0.00'
    assert 'blended_offer' not in first['display']
    second = evaluate(row, '24.42')
    assert second['status'] == 'qualified'
    assert second['actual_outlay_usd'] == '24.38'
    assert second['fill']['levels'] == [dict(price='0.48', quantity='12'), dict(price='0.49', quantity='38')]
    assert second['display']['blended_offer'] == '+105'
    assert F(second['raw']['net_ev']) == F(25) / F('24.38') - 1
    assert evaluate(row, '5.90')['reasons']['fill'] == 'unit_fill_outside_tolerance'
    assert evaluate(row, '250')['reasons']['fill'] == 'unit_fill_depth_insufficient'
    no_book = deepcopy(row)
    no_book['valuation_fill_terms'].pop('asks')
    unknown = evaluate(no_book)
    assert unknown['offer'] == row['original']
    assert unknown['display']['fee'] == '$0.00'
    assert 'after_fee_decimal' not in unknown['raw']
    row['valuation_fill_terms'].pop('cash_terms')
    assert evaluate(row)['reasons']['fee'] == 'unit_fee_schedule_unverified'


def test_sportsbook_limits_reserve_and_state_fees():
    row = fixture_offer()
    row['venue'] = 'fanduel'
    terms = row['valuation_fill_terms']
    terms.update(venue_type='sportsbook', maximum='24')
    terms['cash_terms'].update(reserve_usd='1', reserve_release=dict(win='1', loss='0.5'),
                               settlement_fee_usd=dict(win='0.20'), settlement_rebate_usd=dict(win='0.07'))
    result = evaluate(row)
    assert result['actual_outlay_usd'] == '25'
    assert result['fill']['stake_usd'] == '23.25'
    assert result['states']['win']['net_receipt_usd'] == '50.16'
    assert result['states']['win']['total_fee_usd'] == '0.88'
    assert result['states']['loss']['net_receipt_usd'] == '0.5'
    assert result['display']['fee'] == 'Varies'
    assert result['raw']['net_ev'] == '0.0132'
    assert evaluate(row, 27)['reasons']['fill'] == 'unit_fill_limit_insufficient'


def test_nonbinary_boundaries_and_field_specific_qualification():
    assert score({'win': F(1), 'loss': F(0), 'refund': F(0)},
                 {'win': F(1, 10), 'loss': F(-1), 'refund': F(0)}, F(1, 10)) == 10000
    assert score({'win': F(1, 2), 'loss': F(1, 2)}, {'win': F(1), 'loss': F(-1)}, F(0)) == 0
    row = fixture_offer()
    row['pregame_reference']['available'] = False
    value = evaluate(row)
    assert value['display']['after_fee_odds'] == '+106'
    assert value['display']['fee'] == '$0.75'
    assert 'net_ev' not in value['raw']
    assert 'indicative_before_fee' not in value
    row['pregame_reference'].update(available=True, conditioning='if_no_push')
    row['settlement_assessment'].update(available=False, reason='push_probability_missing')
    value = evaluate(row)
    assert value['indicative_before_fee']['conditioning'] == 'if_no_push'
    assert value['reasons']['settlement'] == 'push_probability_missing'
    assert 'opportunity_score' not in value['raw']


def test_board_chooses_top_marketplace_then_ranks_by_unrounded_score():
    def item(venue, bet, ev, opp, *, venue_type='marketplace', status='qualified'):
        return dict(venue=venue, bet_id=bet, offer_id=venue + bet, venue_type=venue_type, status=status,
                    raw=dict(net_ev=ev, opportunity_score=opp))
    a = item('a', 'one', '.0221', '235.3')
    b = item('b', 'one', '.023', '234.5')
    c = item('a', 'two', '.021', '234.6')
    book = item('sportsbook', 'one', '.03', '240', venue_type='sportsbook')
    negative = item('c', 'one', '-.01', '0')
    indicative = item('d', 'one', '.9', '999', status='indicative')
    items = [a, c, b, book, negative, indicative]
    assert board_order(items) == [c, b]
    assert board_order(items, highest_ev=True) == [b, c]
    assert drawer_order(items) == [book, b, a, c, negative, indicative]
