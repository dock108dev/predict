"""Optional fees change economics, never the captured price or quantity units."""

from copy import deepcopy
from fractions import Fraction as F
from unittest.mock import patch

import pytest

from app.collection.sportsgameodds_current_rows import current_rows
from app.comparison import current_pregame as math, fee_mode
from app.fees import pricing
from app.research.calculation import freeze, reproduce
from app.storage.sportsgameodds_reference import prepare_page
from app.storage.store import stamp
from tests.pregame_fixture import AT, page, parse
from tests.test_fee_pricing import rule


def inputs():
    data = page()
    for odd in data['data'][0]['odds'].values():
        odd['byBookmaker']['kalshi'] = dict(odd['byBookmaker']['prophetx'], odds='+120')
        for book in ('fanduel', 'draftkings'):
            odd['byBookmaker'][book]['odds'] = '-110'
    parsed = parse(data)
    record = next(row for row in current_rows(parsed, parsed.receipt_sha256)[0]
        if row['quote']['venue']=='kalshi')
    observations = {parsed.events[0]['event_id']: prepare_page(parsed)}
    reference = math.reference(record, observations, at=stamp(AT))
    row = dict(venue='kalshi', source=record['quote']['source'], original=record['quote']['original'],
        market=dict(market='spread', period='full_game'), league='NBA', captured_at=AT)
    included = pricing.outcome(row, rule('kalshi'))
    return record, observations, reference, included


def test_zero_fee_mode_uses_full_stake_and_exact_price_probability_fraction():
    record, _, reference, _ = inputs()
    mode = fee_mode.state(False)
    result = math.calculate(record, reference, fee_mode.zero_fee(record, mode), at=stamp(AT), game_key='game')
    assert result['fee_mode'] == mode
    assert result['fee']['classification'] == 'assumed_zero'
    assert result['fee']['entry_usd'] == result['fee']['reserve_usd'] == '0'
    assert result['fee']['committed_usd'] == result['fee']['purchase_usd'] == '100'
    assert F(result['fee']['cashflows']['win']['net_receipt_usd']) == 220
    assert F(result['raw']['net_ev']) == F(1, 10)
    assert all(F(value['total_fee_usd']) == 0 for value in result['fee']['cashflows'].values())
    assert result['posted'] == record['quote']['original']
    assert result['times'] == record['quote']['times']


def test_explicit_on_preserves_nonzero_schedule_and_legacy_inputs_still_mean_on():
    record, _, reference, included = inputs()
    off = math.calculate(record, reference, fee_mode.zero_fee(record, fee_mode.state()), at=stamp(AT), game_key='game')
    legacy = math.calculate(record, reference, included, at=stamp(AT), game_key='game')
    on_input = dict(included, fee_mode=fee_mode.state(True, 1))
    on = math.calculate(record, reference, on_input, at=stamp(AT), game_key='game')
    assert F(on['fee']['entry_usd']) > 0
    assert on['raw'] == legacy['raw']
    assert on['fee'] == legacy['fee']
    assert on['fee_mode']['enabled'] and legacy['fee_mode']['enabled']
    assert F(on['raw']['net_ev']) < F(off['raw']['net_ev'])
    assert on['posted'] == off['posted'] and on['times'] == off['times']


def test_zero_fee_preserves_native_contract_quantity_grid_and_real_outlay():
    record, _, reference, _ = inputs()
    record['quote']['source']['provider'] = 'kalshi'
    record['quote']['original'] = dict(value='0.37', units='usd_per_contract', payout='1')
    result = math.calculate(record, reference, fee_mode.zero_fee(record, fee_mode.state()), at=stamp(AT), game_key='game')
    assert result['fee']['quantity'] == '270'
    assert result['fee']['quantity_increment'] == '1'
    assert F(result['fee']['purchase_usd']) == F(999, 10)
    assert F(result['raw']['net_ev']) == F(1, 2)*270/F(999, 10)-1


def test_frozen_zero_and_legacy_fee_inputs_reproduce_without_reading_current_mode():
    record, observations, reference, included = inputs()
    for fee in (included, fee_mode.zero_fee(record, fee_mode.state())):
        value = math.calculate(record, reference, fee, at=stamp(AT), game_key='game')
        value['coherent_probability'] = math.coherent_reference(record, observations, at=stamp(AT))
        frozen = freeze(value, record=record, fee_input=fee)
        before = deepcopy(frozen)
        with patch.object(fee_mode, 'read', side_effect=AssertionError('offline_mode_read')):
            proof = reproduce(frozen)
        assert proof['status'] == 'calculated'
        assert frozen == before


@pytest.mark.parametrize('value', ['yes', 0, 1, None])
def test_mode_requires_an_explicit_boolean(value):
    with pytest.raises(ValueError, match='fee_mode_state_invalid'):
        fee_mode.state(value)
