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
from app.dashboard.comparison_slate import read
from tests.test_current_board_reads import _ReadOnlyDB, frame
from tests.test_ev09_n01 import AT


def responses():
    at = (instant(AT) + timedelta(hours=1)).isoformat()
    captured = frame()
    output = {}
    with patch('app.storage.current_rows.CurrentRowStore.capture', return_value=captured), patch(
        'app.storage.comparison_board.utc', return_value=at
    ):
        for view in ('ev', 'arbs', 'odds'):
            slate, _ = read(_ReadOnlyDB(), DEFAULT_POLICY, view=view, filter='all', stopped=False, limit=50)
            assert slate['boards'] and not slate['errors'], slate['errors']
            output['slate_' + view] = slate
            output[view] = slate['boards'][0]
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
