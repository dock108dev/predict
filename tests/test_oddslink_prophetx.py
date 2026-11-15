"""Exact team aliases do not independently put a game in play."""
from datetime import timedelta
import pytest

from app.collection.oddslink_prophetx import records
from app.storage.store import stamp


@pytest.mark.parametrize('home,away,home_id,away_id', [
    ('Arizona Wildcats', 'Utah Utes', 'NCAAF:NCAA29', 'NCAAF:NCAA732'),
    ('Montana Grizzlies', 'Idaho State Bengals', 'NCAAF:NCAA441', 'NCAAF:NCAA294'),
])
def test_college_live_oddslink_requires_identical_independent_occurrence(home, away, home_id, away_id):
    start = stamp('2026-11-15T01:30:00Z')
    at = start + timedelta(minutes=12)
    source = at - timedelta(seconds=5)
    capture = dict(sport_key='ncaaf', received_at=at.isoformat(), generated_at=at.isoformat(),
                   sha256='a'*64, fixtures=[dict(
        id='ncaaf:live', sport_key='ncaaf', commence_time=start.isoformat(), in_play=True,
        home_team=home, away_team=away, bookmakers=[dict(
            key='prophetx', kind='exchange', last_update=source.isoformat(),
            markets={'h2h': [dict(name=home, price=-110), dict(name=away, price=105)]})])])
    assert not records(capture)
    assert not records(capture, live={(start, away_id, home_id): source})
    assert not records(capture, live={(start + timedelta(hours=1), home_id, away_id): source})
    rows = records(capture, live={(start, home_id, away_id): source})
    assert len(rows) == 2
    assert {row['selection']['participant'] for row in rows} == {home_id, away_id}
    assert all(row['quote']['times']['source_at'] == source.isoformat() for row in rows)
