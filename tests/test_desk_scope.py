from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from app.dashboard.desk_scope import pregame_search


def test_pregame_search_keeps_all_sources_for_exact_matching_occurrences():
    now = datetime(2026, 11, 15, 16, tzinfo=timezone.utc)
    kickoff = (now + timedelta(hours=2)).isoformat()
    local = dict(competition='NFL', scheduled_start=kickoff,
                 home='NFL:NO', away='NFL:ATL', participants={})
    db = Mock()
    db.execute.return_value = [
        dict(local, id='native', title='New Orleans Saints game'),
        dict(local, id='aggregate', title='N.O. vs Atlanta'),
        dict(local, id='different-matchup', title='Tampa Bay vs Atlanta',
             home='NFL:TB', away='NFL:ATL'),
    ]
    published_game = dict(game_key='saved', league='NFL', start_at=kickoff, title='N.O. vs Atlanta',
        participants=[dict(id='NFL:NO', role='home'), dict(id='NFL:ATL', role='away')])
    result = {'games': [published_game], 'rows': [dict(published_game, game_title='N.O. vs Atlanta')]}
    games, events = pregame_search(db, result, {'search': 'Saints vs. Atlanta'}, now)
    assert games == {'saved'}
    assert events == ['aggregate', 'native']


def test_unfiltered_summary_skips_event_search_and_excluded_league_is_empty():
    db = Mock()
    now = datetime(2026, 11, 15, 16, tzinfo=timezone.utc)
    assert pregame_search(db, None, {}, now) == (None, None)
    assert pregame_search(db, None, {'league': 'none'}, now) == (set(), [])
    db.execute.assert_not_called()
