"""Verify the NHL scoring basis from one original SportsGameOdds event."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.storage.store import exact_time


BASIS = 'sgo_nhl_full_game_official_score'
ROLES = ('home', 'away')
REGULATION_PERIODS = ('1p', '2p', '3p')
DECISIONS = {
    'F': ('regulation', ()),
    'F (OT)': ('overtime', ('ot',)),
    'F (SO)': ('shootout', ('ot', 'so')),
}


def _score(value):
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)) or len(str(value)) > 32:
        raise ValueError('invalid NHL score')
    score = Decimal(value)
    if not score.is_finite() or not 0 <= score <= 10000 or score != score.to_integral_value():
        raise ValueError('invalid NHL score')
    return int(score)


def _period_scores(results, period):
    return {role: _score(results[period][role]['points']) for role in ROLES}


def _completed_periods(values, expected):
    return (isinstance(values, list) and len(values) == len(expected)
            and all(isinstance(value, str) for value in values) and set(values) == expected)


def nhl_scoring(event, *, event_id, starts_at, team_ids, final_scores):
    """Bind a completed raw NHL event to exact retained occurrence and scores."""
    try:
        if not isinstance(event_id, str) or not event_id or event['eventID'] != event_id or event['leagueID'] != 'NHL':
            return None
        status = event['status']
        if not (status['started'] is True and status['ended'] is True and status['live'] is False
                and (status.get('completed') is True or status.get('finalized') is True)):
            return None
        if any(status.get(key) is True for key in ('cancelled', 'suspended')):
            return None
        start = starts_at.isoformat() if isinstance(starts_at, datetime) else starts_at
        if exact_time(status['startsAt']) != exact_time(start):
            return None

        teams = event['teams']
        raw_team_ids = {role: teams[role]['teamID'] for role in ROLES}
        if (raw_team_ids != team_ids or any(not isinstance(value, str) or not value for value in raw_team_ids.values())
                or raw_team_ids['home'] == raw_team_ids['away']):
            return None
        decision, extra = DECISIONS[status['displayShort']]
        periods = status['periods']
        expected = {*REGULATION_PERIODS, 'game', 'reg', *extra}
        if not all(_completed_periods(periods[key], expected) for key in ('started', 'ended')):
            return None

        results = event['results']
        if not isinstance(results, dict) or any(results.get(period) is not None for period in {'ot', 'so'}.difference(extra)):
            return None
        final = _period_scores(results, 'game')
        if final != {role: _score(final_scores[role]) for role in ROLES}:
            return None
        if any(teams[role].get('score') is not None and _score(teams[role]['score']) != final[role] for role in ROLES):
            return None
        regulation = _period_scores(results, 'reg')
        segments = [_period_scores(results, period) for period in REGULATION_PERIODS]
        if regulation != {role: sum(segment[role] for segment in segments) for role in ROLES}:
            return None

        overtime = _period_scores(results, 'ot') if extra else dict.fromkeys(ROLES, 0)
        attempts = _period_scores(results, 'so') if decision == 'shootout' else None
        winner = 'home' if final['home'] > final['away'] else 'away'
        loser = 'away' if winner == 'home' else 'home'
        if final[winner] <= final[loser]:
            return None
        if extra and regulation[winner] != regulation[loser]:
            return None
        if decision == 'overtime' and (overtime[winner], overtime[loser]) != (1, 0):
            return None
        if attempts is not None and (any(overtime.values()) or attempts[winner] <= attempts[loser]):
            return None

        # A shootout contributes one official goal, regardless of attempts made.
        official = {role: regulation[role] + overtime[role] + int(attempts is not None and role == winner) for role in ROLES}
        if official != final:
            return None
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return None

    return dict(decision=decision, basis=BASIS, scores=official, regulation_scores=regulation,
                overtime_scores=overtime, shootout_attempt_scores=attempts)
