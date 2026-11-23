"""Receipt status and paired presentation retain their actual meanings."""
from app.collection.current_admin import valid_receipt
from app.comparison.pregame_arbs import evaluate
from tests.test_pregame_arbs import AT, entry
from app.comparison.acquisition import validate


def test_sql_mode_valid_receipt_does_not_need_a_diagnostic_quote():
    receipt = valid_receipt({'last_valid_received_at': '2026-11-23T12:00:00Z'})
    assert receipt == dict(at='2026-11-23T12:00:00+00:00', basis='validated_provider_page')
    assert valid_receipt({'last_received_at': '2026-11-23T12:00:00Z',
                          'original_receipt': {'status': 503}}) == dict(at=None, basis=None)


def test_valid_receipt_compares_instants_and_keeps_the_evidence_owner():
    receipt = valid_receipt({'last_valid_received_at': 'invalid'},
        ['2026-11-23T12:00:00Z'], ['2026-11-23T08:00:00-05:00'])
    assert receipt == dict(at='2026-11-23T08:00:00-05:00', basis='source_state')


def test_market_pair_shows_both_allocations_and_captured_time():
    left, right = entry('novig', 'home'), entry('prophetx', 'away', line='1.5')
    left['payload']['times'] = {'received_at': '2026-11-18T14:00:00Z'}
    right['payload']['times'] = {'received_at': '2026-11-18T14:01:00Z'}
    result = evaluate(left, right, at=AT)
    assert result['category_label'] == 'Market-to-market arbitrage'
    assert result['executable_legs'] is True
    assert result['captured_at'] == '2026-11-18T14:01:00+00:00'
    assert [leg['allocation_usd'] for leg in result['legs']] == ['50', '50']
    assert all(leg['input_role'] == 'trading_market' for leg in result['legs'])


def test_book_benchmark_cannot_present_a_second_executable_trading_leg():
    result = evaluate(entry('novig', 'home'), entry('fanduel', 'away'), at=AT)
    assert result['category_label'] == 'Sportsbook reference comparison'
    assert result['executable_legs'] is False
    assert [leg['executable_venue'] for leg in result['legs']] == [True, False]
    assert 'not an executable two-leg trade' in result['liquidity_note']


def test_pair_rejects_cross_pull_and_whole_input_span_and_keeps_inclusive_boundary():
    left, right = entry('novig', 'home'), entry('prophetx', 'away')
    def witness(pull, received):
        return dict(pull_id=pull,attempt_id='child',receipt_sha256='a'*64,received_at=received)
    first = witness('pull-a','2026-11-18T14:00:00Z')
    left['payload']['acquisition'] = validate([first])
    right['payload']['acquisition'] = validate([witness('pull-b','2026-11-18T14:00:01Z')])
    assert evaluate(left,right,at=AT) is None

    right['payload']['acquisition'] = validate([witness('pull-a','2026-11-18T14:10:00Z')])
    assert evaluate(left,right,at=AT)['acquisition']['receipt_span_seconds'] == 600
    right['payload']['acquisition'] = validate([witness('pull-a','2026-11-18T14:10:00.000001Z')])
    assert evaluate(left,right,at=AT) is None
    left['payload']['acquisition'] = validate([first,witness('pull-a','2026-11-18T14:09:50Z')])
    right['payload']['acquisition'] = validate([witness('pull-a','2026-11-18T14:19:40Z')])
    assert evaluate(left,right,at=AT) is None


def test_team_display_uses_exact_participant_name_in_full_and_old_compact_evidence():
    from app.storage.market_board import offer as display
    from tests.test_ev_movement import offer

    value = offer()
    value['record']['event']['participants'] = {'Home Team':'home','Away Team':'away'}
    value['calculation_payload']['selection_label'] = 'Home Team'
    expanded = display({},value,'same-pull')
    assert expanded['outcome'] == 'Home Team'
    compact = dict(value,display_offer=dict(expanded,outcome='provider:raw-id'))
    restored = display({},compact,'same-pull')
    assert restored['outcome'] == 'Home Team'
    assert restored['revision'] == expanded['revision']
