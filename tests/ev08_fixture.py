"""Explicit authored matching/content/kickoff browser transitions, no intake."""
from datetime import timedelta
from uuid import uuid4

from app.dashboard.current_contract import snapshot_inputs, quotes_of, stamp


ACTIONS = ('matching_conflict', 'prepare_kickoff', 'prepare_content_expiry', 'advance_boundary')


def transition(store, boundary, action):
    from tests.ev07_fixture_runtime import authored_fixture
    if action == 'advance_boundary':
        store._clock_origin += timedelta(seconds=3)
        store.refresh_age()
    else:
        raw = authored_fixture()
        raw['runtime_id'] = 'synthetic:ev08:' + action + ':' + str(uuid4())
        if action == 'prepare_kickoff':
            for event in raw['events']:
                event['start_at'] = (stamp(raw['clock_at']) + timedelta(seconds=2)).isoformat()
        elif action == 'prepare_content_expiry':
            from app.comparison.current_dependencies import digest
            expiry = (stamp(raw['clock_at']) + timedelta(seconds=2)).isoformat()
            for event in raw['events']:
                for group in event['groups']:
                    for outcome in group['outcomes']:
                        for quote in quotes_of(outcome):
                            for status in quote['comparison_input_status'].values():
                                recipe = status.get('estimate_content')
                                if recipe is not None:
                                    recipe['expires_at'] = expiry
                                    recipe['id'] = digest({k:v for k,v in recipe.items() if k != 'id'})
        elif action == 'matching_conflict':
            raw = snapshot_inputs(store._state)
            raw['state_revision'] += 1
            for event in raw['events']:
                for group in event['groups']:
                    for outcome in group['outcomes']:
                        for quote in quotes_of(outcome):
                            quote['binding']['verified'] = False
                            quote['revision'] += 1
        else:
            raise ValueError('Unknown EV08 authored boundary')
        if not store.commit(raw):
            raise ValueError('Authored boundary did not commit')
    return dict(action=action, runtime_id=store._state['runtime_id'],
                state_revision=store._state['state_revision'], clock_at=store._state['clock_at'],
                evidence_class='authored isolated boundary; original source/receipt clocks unchanged')
