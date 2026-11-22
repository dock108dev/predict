from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.collection.research_result_capture import eligible

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)
OWNER = dict(active=True, global_stopped=False, paused_sources=[], config=dict(
    enabled=True, aggregate_enabled=True, aggregate_provider='sportsgameodds', sports=['NBA']))
CASES = [dict(source_event_ids=['source-event'], starts_at='2026-11-20T00:00:00Z', league='NBA')]


def test_result_scope_requires_declared_source_id_started_event_and_running_authority():
    assert eligible(OWNER, CASES, ['source-event'], at=NOW)
    assert not eligible(OWNER, CASES, ['not-declared'], at=NOW)
    assert not eligible(OWNER, [], ['source-event'], at=NOW)
    assert not eligible(OWNER, [dict(CASES[0], starts_at='2026-11-23T00:00:00Z')], ['source-event'], at=NOW)
    assert not eligible(OWNER, [dict(CASES[0], league='NFL')], ['source-event'], at=NOW)


@pytest.mark.parametrize('change', [
    dict(active=False), dict(global_stopped=True), dict(paused_sources=['sportsgameodds']),
    dict(config=dict(OWNER['config'], enabled=False)),
    dict(config=dict(OWNER['config'], aggregate_enabled=False)),
    dict(config=dict(OWNER['config'], aggregate_provider='the_odds_api')),
])
def test_research_capture_preserves_stop_pause_configuration_and_provider_choice(change):
    owner = deepcopy(OWNER)
    owner.update(change)
    assert not eligible(owner, CASES, ['source-event'], at=NOW)
