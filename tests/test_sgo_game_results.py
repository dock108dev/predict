import json
from unittest.mock import patch

import pytest

from app.collection.sgo_game_results import observations
from app.collection.sportsgameodds_adapter import parse_page
from tests.test_sportsgameodds_adapter import response

RECEIVED = '2026-11-11T01:00:00Z'


def page(*, final=True, scores=True, game=True):
    raw = response()
    event = raw['data'][0]
    event['status'].update(started=True, live=False, completed=final, ended=final)
    if scores:
        event['teams']['home']['score'] = 99
        event['teams']['away']['score'] = 98
    if game:
        event['results'] = {'game': {'home': {'points': 99}, 'away': {'points': 98}}}
    return raw


def result(raw):
    return observations(parse_page(json.dumps(raw).encode(), RECEIVED), known_at=RECEIVED)


def test_final_game_points_keep_identity_clocks_and_separate_settlement():
    item, = result(page())
    assert item['state'] == 'available' and item['final']
    assert (item['home_score'], item['away_score']) == ('99', '98')
    assert item['event_id'] == 'event' and item['league'] == 'NBA'
    assert item['home'] == item['canonical_event']['home']
    assert item['home_provider_id'] == 'home'
    assert item['received_at'] == item['observed_at'] == RECEIVED
    assert item['source_at'] is item['published_at'] is None
    assert item['venue_settlement'] is item['actual_trade_result'] is None


@pytest.mark.parametrize(('mutate', 'reason'), [
    (lambda event: event['status'].update(completed=False, ended=True), 'sporting_result_not_final'),
    (lambda event: event['status'].update(cancelled=True), 'sporting_result_cancelled'),
    (lambda event: event['status'].update(live=True), 'sporting_result_live_conflict'),
    (lambda event: event['teams']['home'].update(score=100), 'sporting_result_score_conflict'),
])
def test_unsupported_received_result_is_preserved_with_explicit_reason(mutate, reason):
    raw = page()
    mutate(raw['data'][0])
    item, = result(raw)
    assert not item['final'] and item['reason'] == reason


def test_missing_scores_are_null_not_zero_and_pregame_empty_is_not_result():
    item, = result(page(scores=False, game=False))
    assert item['home_score'] is item['away_score'] is None
    assert item['reason'] == 'sporting_result_score_missing'
    assert result(response()) == []


def test_cancelled_game_without_score_is_retained_as_an_exception():
    raw = response()
    raw['data'][0]['status']['cancelled'] = True
    item, = result(raw)
    assert item['reason'] == 'sporting_result_cancelled'
    assert not item['final']


def test_result_receipt_cannot_be_known_before_arrival():
    parsed = parse_page(json.dumps(page()).encode(), RECEIVED)
    with pytest.raises(ValueError, match='future_receipt'):
        observations(parsed, known_at='2026-11-10T23:00:00Z')


def test_changed_canonical_roles_cannot_silently_reverse_the_score():
    from app.collection.sportsgameodds_current_rows import event_record
    def reverse(*args, **kwargs):
        event = event_record(*args, **kwargs)
        return dict(event, home=event['away'], away=event['home'])
    with patch('app.collection.sgo_game_results.event_record', side_effect=reverse):
        item, = result(page())
    assert not item['final']
    assert item['reason'] == 'sporting_result_canonical_role_mapping_changed'
