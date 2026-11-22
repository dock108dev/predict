"""Bounded sporting results from an SGO receipt, never venue settlement."""
from decimal import Decimal, InvalidOperation

from app.storage.store import stamp
from .sportsgameodds_current_rows import event_record, participant_ids
from app.normalization.college_registry import sgo_registry

VERSION = 'sgo-final-team-points-1'


def _score(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        score = Decimal(str(value))
        if score.is_finite() and 0 <= score <= 10000 and score == score.to_integral_value():
            return str(score.to_integral_value())
    except InvalidOperation:
        pass
    return None


def observations(page, *, known_at):
    """Retain received final-result cases and explicit unsupported dispositions.

    Ordinary pregame empty scores are not results. Missing provider publication
    clocks stay null; receipt/knowledge clocks are not relabeled source clocks.
    """
    known = stamp(known_at)
    result = []
    registry = None
    for event in page.events:
        status = event['status']
        final = status.get('completed') is True or status.get('finalized') is True
        if not final and not event.get('game_results') and not event.get('scores'):
            continue
        received = event['received_at']
        if stamp(received) > known:
            raise ValueError('sporting_result_future_receipt')
        game = event.get('game_results') or {}
        team = event.get('scores') or {}
        scores = {role: _score(game.get(role, team.get(role))) for role in ('home', 'away')}
        conflict = any(game.get(role) is not None and team.get(role) is not None
                       and _score(game[role]) != _score(team[role]) for role in scores)
        reason = ('sporting_result_not_final' if not final else
                  'sporting_result_cancelled' if status.get('cancelled') is True else
                  'sporting_result_live_conflict' if status.get('live') is True else
                  'sporting_result_score_conflict' if conflict else
                  'sporting_result_score_missing' if any(value is None for value in scores.values()) else None)
        if registry is None:
            registry = sgo_registry()
        canonical = event_record(event, page.receipt_sha256, received, registry)
        provider_roles = participant_ids(event['teams'], event['league'], event['event_id'], registry)
        if any(canonical[role] != provider_roles[role] for role in ('home', 'away')):
            reason = 'sporting_result_canonical_role_mapping_changed'
        result.append(dict(version=VERSION, source='sportsgameodds', kind='sporting_result',
                           event_id=event['event_id'], league=event['league'],
                           starts_at=canonical['scheduled_start'], source_starts_at=event['starts_at'],
                           canonical_event=canonical, home=canonical['home'], away=canonical['away'],
                           home_provider_id=event['teams']['home']['id'],
                           away_provider_id=event['teams']['away']['id'],
                           home_score=scores['home'], away_score=scores['away'], final=reason is None,
                           state='available' if reason is None else 'unavailable', reason=reason,
                           published_at=None, source_at=None, observed_at=received, received_at=received,
                           known_at=known.isoformat(), knowledge_at=known.isoformat(),
                           receipt_sha256=page.receipt_sha256, provider_status=dict(status),
                           venue_settlement=None, actual_trade_result=None))
    return result


def ingest(page, *, known_at):
    items = observations(page, known_at=known_at)
    if not items:
        return dict(state='no_result_fields', received=0, matched=0)
    from app.storage.store import connect
    from app.research.records import import_sporting
    with connect() as db:
        return import_sporting(db, items)
