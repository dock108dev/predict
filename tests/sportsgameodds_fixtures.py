"""Shared authored SportsGameOdds clock and discovery event."""

from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 11, 10, 20, tzinfo=timezone.utc)


def event(n):
    return {'event_id': f'e{n}', 'league':'NFL', 'starts_at':(NOW + timedelta(days=4)).isoformat(),
            'received_at':NOW.isoformat(), 'phase':'pregame', 'status':{}}
