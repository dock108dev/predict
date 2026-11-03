"""Evidence counters distinguish sampled currentness, receipts and generations."""
from app.storage.pipeline_delivery import witness,difference
from scripts.pipeline_delivery_report import build
import json


def test_witness_is_bounded_allowlist_and_receipt_only_change_is_explicit():
    offers={str(i):dict(id=str(i),event_id='event',price_value='0.4',price_units='USD',
        source_at='2026-11-01T00:00:00Z',received_at='2026-11-01T00:00:01Z',offer_revision='same',
        raw={'secret':'never include'},contract_dependency='contract',scoring_dependency='rule') for i in range(20)}
    deps=dict(observations={key:'hash' for key in offers})
    before=witness(dict(offers=offers),deps,'2026-11-01T00:00:02Z','2026-11-01T00:00:03Z')
    assert before['dependency_count']==20 and len(before['witnesses'])==8
    assert 'secret' not in json.dumps(before)
    offers['0']['received_at']='2026-11-01T00:00:04Z'
    after=witness(dict(offers=offers),deps,'2026-11-01T00:00:05Z','2026-11-01T00:00:06Z')
    assert difference(before,after)[0]['classification']=='receipt_only'
    offers['0']['price_value']='0.5'
    changed=witness(dict(offers=offers),deps,'2026-11-01T00:00:05Z','2026-11-01T00:00:06Z')
    assert difference(before,changed)[0]['classification']=='dependency_change'


def test_delivery_report_deduplicates_generations_and_does_not_call_history_current(tmp_path):
    (tmp_path/'historical-identities.json').write_text('["event", "retired"]')
    for i in range(2):
        at=f'2026-11-01T00:00:0{i+2}+00:00'
        sample=dict(at=at,engine='engine',runtime=dict(runtime_id='r',healthy=True,active=True,
            calculation_state='running',observation_state='running'),events=[dict(id='event',provider='kalshi',native_event_id='native')],
            generations=[dict(id='generation',engine='engine',disposition='superseded',published_at=at,completed_at=at,admitted_at=at,
                reuses=0,facts=dict(retained_financial_only=True),trace={})],
            publications=[dict(generation='generation',publication_events=['event'],selected=True,engine='engine',dependency_current=False,
                retained_only='true',dependency_failures=dict(all=['changed']),valid_until=None)],
            attempts=[],field_observation=dict(changes=[]),summary=dict(database_bytes=100+i,changed_events=['event']))
        (tmp_path/f'sample-{i:03}.json').write_text(json.dumps(sample))
    result=build(tmp_path)
    assert result['unique_generations']==1
    assert result['unique_completed']==1
    assert result['unique_sampled_current_generations']==0
    assert result['changing']['ever_current']==0
    assert result['historical_not_observed']==['retired']
    assert result['storage']['net_growth']==1
