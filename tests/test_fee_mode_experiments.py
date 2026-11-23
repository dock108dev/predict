"""Captured fee assumptions survive comparisons, packing and offline replay."""
from copy import deepcopy
from fractions import Fraction as F
from unittest.mock import patch

import pytest

from app.comparison import fee_mode, pregame_arbs
from app.research import ev_movement
from app.research.experiment_evidence import pack_checkpoint, unpack
from tests.test_ev_movement import checkpoint, offer
from tests.test_pregame_arbs import AT, entry


def captured(enabled, win):
    mode = fee_mode.state(enabled, int(enabled))
    row = offer(win)
    row['calculation_payload']['fee_mode'] = deepcopy(mode)
    value = checkpoint(row)
    value['fee_mode'] = deepcopy(mode)
    return value


def test_each_checkpoint_keeps_its_fee_assumption_and_early_cross_cashflows():
    early, late = captured(False, '220'), captured(True, '210')
    original = deepcopy(early)
    result = ev_movement.compare_checkpoints(early, late)
    row = result['cases'][0]
    assert result['fee_modes_differ'] is True
    assert result['fee_modes']['early']['enabled'] is False
    assert result['fee_modes']['late']['enabled'] is True
    assert F(row['early']['screen']['ev']) == F(1, 10)
    assert F(row['late']['screen']['ev']) == F(1, 20)
    assert F(row['early_offer_late_reference']['screen']['ev']) == F(1, 10)
    assert early == original


def test_explicit_fee_modes_are_hashed_losslessly_and_replay_never_reads_flag():
    early = captured(False, '220')
    late = captured(True, '220')
    roots = []
    with patch.object(fee_mode, 'read', side_effect=AssertionError('offline flag read')):
        for snapshot in (early, late):
            root, dependencies = pack_checkpoint(dict(status='captured', snapshot=snapshot))
            roots.append(root)
            restored = unpack(root, dependencies)['snapshot']
            assert restored == snapshot
            assert ev_movement.reproduce_checkpoint(restored)['fee_mode'] == snapshot['fee_mode']
    assert roots[0] != roots[1]
    # Original unmarked evidence remains unmarked; its mathematics is legacy fees-on.
    legacy = checkpoint(offer('220'))
    assert 'fee_mode' not in ev_movement.offer_measurements(legacy['offers'][0])
    assert 'fee_mode' not in ev_movement.reproduce_checkpoint(legacy)


def test_offline_replay_refuses_disagreeing_snapshot_and_calculation_modes():
    value = captured(False, '220')
    value['fee_mode'] = fee_mode.state(True, 1)
    with pytest.raises(ValueError, match='fee_mode_snapshot_mismatch'):
        ev_movement.reproduce_checkpoint(value)
    value = captured(False, '220')
    value['offers'][0]['fee_input'] = dict(fee_mode=fee_mode.state(True, 1))
    with pytest.raises(ValueError, match='fee_mode_input_mismatch'):
        ev_movement.reproduce_checkpoint(value)


def test_pair_mode_is_captured_and_mixed_modes_do_not_form_one_result():
    left, right = entry('novig', 'home'), entry('prophetx', 'away', line='1.5')
    for item in (left, right):
        item['payload']['fee_mode'] = fee_mode.state(False)
    pair = pregame_arbs.evaluate(left, right, at=AT)
    assert pair['fee_mode']['enabled'] is False
    assert F(pair['minimum_profit_usd']) == 5
    right['payload']['fee_mode'] = fee_mode.state(True, 1)
    assert pregame_arbs.evaluate(left, right, at=AT) is None


def test_reprice_cache_does_not_reuse_a_result_after_its_captured_mode_changes():
    item = entry('novig', 'home')
    item['payload']['fee_mode'] = fee_mode.state(False)
    with patch.object(pregame_arbs, '_reprice', wraps=pregame_arbs._reprice) as work:
        pregame_arbs.reprice(item, F(50), at=AT)
        pregame_arbs.reprice(item, F(50), at=AT)
        assert work.call_count == 1
        item['payload']['fee_mode'] = fee_mode.state(True, 1)
        pregame_arbs.reprice(item, F(50), at=AT)
        assert work.call_count == 2


def test_new_received_page_freezes_zero_fee_inputs_and_reproduces_without_settings():
    from types import SimpleNamespace
    from tests.pregame_fixture import AT as captured_at, page, parse

    mode = fee_mode.state(False)
    context = SimpleNamespace(fee_mode=mode,
        price_routes={venue:'sportsgameodds' for venue in ('kalshi','polymarket_us','novig','prophetx')},
        fee=lambda record, at:fee_mode.zero_fee(record, mode))
    received = parse(page())
    with patch('app.storage.current_pregame.CalculationContext', return_value=context):
        snapshot = ev_movement.build_snapshot(None, received,
            request_scope=dict(bookmakerID='prophetx,fanduel,draftkings', includeAltLines=True),
            dispatch_at=captured_at, known_at=captured_at)
    assert snapshot['fee_mode'] == mode
    assert len(snapshot['offers']) == 2
    for item in snapshot['offers']:
        assert item['fee_input']['fee_mode'] == mode
        assert item['calculation_payload']['fee_mode'] == mode
        assert F(item['calculation_payload']['fee']['entry_usd']) == 0
        assert all(F(state['total_fee_usd']) == 0 for state in item['calculation_payload']['fee']['cashflows'].values())
    with patch.object(fee_mode, 'read', side_effect=AssertionError('offline settings read')):
        proof = ev_movement.reproduce_checkpoint(snapshot)
    assert proof['numeric_screen_results'] == 2
    assert proof['fee_mode'] == mode
