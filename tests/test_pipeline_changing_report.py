from copy import deepcopy
import pytest
from scripts.pipeline_changing_report import build


def inputs():
    history={'rows':[dict(source_event_id='e',source='source',native_event_id='native',current_disposition='deferred')]}
    generation=dict(id='generation',engine='engine',events=['e'],game_key='game',
        admitted_at='2026-10-31T10:00:00Z',published_at='2026-10-31T10:00:01Z',
        disposition='superseded',reason='inputs_changed_during_calculation',facts={'retained_financial_only':True})
    sample=dict(at='2026-10-31T10:00:00Z',engine='engine',runtime=dict(runtime_id='runtime',healthy=True,active=True,
        calculation_state='running',observation_state='running'),events=[dict(id='e',semantic_revision='a',component=['e'])],
        publications=[],attempts=[],generations=[])
    end=deepcopy(sample);end['at']='2026-10-31T10:01:00Z';end['generations']=[generation]
    end['events'][0]['semantic_revision']='b'
    return history,{'records':[sample,end]}


def test_overtaken_commit_is_not_a_current_publication():
    history,run=inputs();report=build(history,run);row=report['rows'][0]
    assert row['final_disposition']=='only_historical_commits_inputs_overtaken'
    assert row['valid_commit_generations']==0 and row['historical_commit_generations']==1
    assert row['receipt_to_publication_seconds'] is None
    assert row['capture_to_first_commit_seconds']['maximum']==1
    assert row['observed_component_revision_changes']==1
    assert report['fresh_live_observation'] is False


def test_valid_commit_and_observed_currentness_are_separate():
    history,run=inputs();g=run['records'][-1]['generations'][0]
    g.update(disposition='published',reason=None,facts={})
    assert build(history,run)['rows'][0]['final_disposition']=='valid_commit_between_samples'
    publication=dict(publication_events=['e'],selected=True,game_key='game',engine='engine',dependency_current=True,
        retained_only=None,valid_until=None,dependency_failures={},calculated_at='2026-10-31T10:00:00Z')
    run['records'][0]['publications']=[publication]
    row=build(history,run)['rows'][0]
    assert row['final_disposition']=='published_current_then_invalidated'
    assert row['current_samples']==1
    assert row['last_observed_current_publication']==publication['calculated_at']


def test_mixed_runtime_cannot_be_reported_as_a_fixed_implementation():
    history,run=inputs();run['records'][-1]['runtime']['runtime_id']='replacement'
    with pytest.raises(ValueError,match='fixed_engine_and_runtime'):build(history,run)
