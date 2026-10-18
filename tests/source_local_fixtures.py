"""Authored missing-context inputs for source-local observation regressions.

Only fake source response dictionaries are changed. No application admission,
event, occurrence, model or scoring registry is extended by these helpers.
"""
from copy import deepcopy

from tests.multisport_fixtures import source_case


def source_local_case(league, family, token, *, clock=None,
                      missing_context=True, missing_occurrence=False):
    case = source_case(league, family, token, clock=clock)
    if missing_context:
        remove_context(case)
    if missing_occurrence:
        remove_occurrence(case)
    return case


def remove_context(case):
    """Keep native event, league, canonical roles and schedule exactly intact."""
    for value in (case['event'], case['milestone']['details'],
                  case['events']['polymarket_us']):
        for key in ('season', 'stage', 'season_type', 'season_year', 'season_name'):
            value.pop(key, None)


def remove_occurrence(case):
    """Retain source-local identity without inventing an MLB occurrence."""
    for key in ('game_id', 'game_number', 'original_start', 'schedule_status'):
        case['event'].pop(key, None)
    for key in ('source_id', 'source_provider', 'source_ids'):
        case['milestone'].pop(key, None)
    for key in ('game_number', 'original_start', 'schedule_status'):
        case['milestone']['details'].pop(key, None)
    for key in ('sportradarGameId', 'gameNumber', 'originalStartTime',
                'rescheduledFromGameId'):
        case['events']['polymarket_us'].pop(key, None)


def restore_context(case, original):
    """Later explicit source metadata, never inferred from a ticker or date."""
    for target, source, keys in (
        (case['event'], original['event'], ('season', 'stage')),
        (case['milestone']['details'], original['milestone']['details'], ('season',)),
        (case['events']['polymarket_us'], original['events']['polymarket_us'],
         ('season', 'stage')),
    ):
        for key in keys:
            if key in source:
                target[key] = deepcopy(source[key])


def member(case, venue):
    event = case['events'][venue]
    return venue, event['event_ticker'] if venue == 'kalshi' else event['id']
