"""Portable B02/U02 response inputs from the real current-row read owners.

Only repository fixtures and a fake read-only database are used. No collectors,
installed database, saved /tmp reports or external services are consulted.
"""
from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch

from app.comparison.calculation_availability import combine
from app.comparison.current_dependencies import instant
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.dashboard.comparison_board import expand_financial, expand_odds
from app.dashboard.comparison_slate import read
from app.storage.store import hashed
from tests.test_current_board_reads import _ReadOnlyDB, frame, context, latest_frame
from tests.test_ev09_n01 import AT


def responses():
    at = (instant(AT) + timedelta(hours=1)).isoformat()
    # Build the authored background result before any ordinary read. Aging uses
    # the real calculation owners against retained inputs; readers only consume
    # that publication and never calculate or capture current rows themselves.
    published = latest_frame(context(frame(), at=at))
    published['at'] = at
    published['read_authority'] = 'authored-authority'
    database = _ReadOnlyDB()
    output = {}
    with patch('app.storage.latest_board.snapshot', return_value=published), patch(
        'app.storage.latest_board.slate_authority', return_value=hashed(['authored-authority', False])
    ), patch(
        'app.storage.latest_board.calculate_current', side_effect=AssertionError('Ordinary read cannot calculate')
    ):
        for view in ('ev', 'arbs', 'odds'):
            slate, _ = read(database, DEFAULT_POLICY, view=view, filter='all', stopped=False, limit=50)
            assert slate['boards'] and not slate['errors'], slate['errors']
            # Renderer unit cases consume the same detached, locally hydrated
            # inputs that the client validator supplies from compact wire refs.
            for board in slate['boards']:
                (expand_odds if view == 'odds' else expand_financial)(board)
            output['slate_' + view] = slate
            output[view] = slate['boards'][0]
    assert not database.statements, database.statements
    output['slate'] = output['slate_ev']
    # An authored failure on a second occurrence leaves the real healthy board.
    partial = deepcopy(output['slate_ev'])
    game = dict(partial['games'][0], game_key='authored-failed-occurrence', title='Authored failed occurrence')
    partial['games'].append(game)
    partial['errors'] = [dict(game_key=game['game_key'], reason='calculation_read_failed',
        availability=dict(state='calculation_failed', reason_codes=['calculation_read_failed']))]
    partial['availability'] = combine([b['availability'] for b in partial['boards']],
        games=len(partial['games']), failures=[(game['game_key'], 'calculation_read_failed')])
    output['partial'] = partial
    return output


if __name__ == '__main__':
    print(json.dumps(responses(), separators=(',', ':')))
