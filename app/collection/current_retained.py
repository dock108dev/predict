"""Prepare authentic retained prices without credentials, dispatch or accounting.

The ordinary reducer builds original inputs only. CurrentStore's owned retained
admission subsequently validates and evaluates them before complete publication.
"""
from copy import deepcopy
import json
from pathlib import Path

from .current_aggregate_policy import POLICY
from .current_policy import aggregate_scope
from .current_sink import LatestStateSink


class RetainedInputs:
    def __init__(self, raw):
        self._state = raw

    def commit(self, raw):
        self._state = raw
        return True


def prepare(envelope, config, directory):
    capture = RetainedInputs(envelope)
    sink = LatestStateSink(capture, envelope, config)
    states = deepcopy(envelope['source_status'])
    rejected = []
    batches = []
    for sport in aggregate_scope(config):
        path = Path(directory) / (sport + '.json')
        if not path.exists():
            continue
        try:
            if path.is_symlink() or path.stat().st_size > POLICY.response_bytes:
                raise ValueError('Retained response bound')
            value = json.loads(path.read_bytes())
            if value.get('schema') != 'predict-redacted-aggregate-diagnostic-1' or value.get('sport') != sport:
                raise ValueError('Retained response identity')
            body = json.dumps(value['replay']).encode()
            from .current_aggregate_admission import admit_venues
            _, failures = admit_venues(body, sport, value['received_at'])
            if len(failures) == 2:
                raise ValueError('Retained response rejected')
            next_states = deepcopy(states)
            for venue in ('novig', 'prophetx'):
                next_states[venue] = dict(state='budget_delayed', reason_code='retained_observations',
                    reason='Historical retained observations; original quote clocks apply. Acquisition is separate.',
                    received_at=value['received_at'], next_due_at=None)
            batches.append(dict(type='current_aggregate', source='the_odds_api', sport=sport,
                body=body, received_at=value['received_at'],
                venue_states=next_states))
            states = next_states
        except (ValueError, KeyError, TypeError, OSError, ArithmeticError):
            rejected.append(sport)
    if batches:
        sink.commit(dict(type='current_aggregate_batches', source='the_odds_api', batches=batches), states)
    return capture._state, sink, rejected
