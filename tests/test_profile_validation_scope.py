from copy import deepcopy
from unittest.mock import patch
import pytest
from app.comparison import current_dependencies as deps


def test_exact_validation_reuse_is_scoped_and_mutations_still_reject():
    key,value=deps.profile('fee',{'authored':'evidence'})
    profiles={key:value}
    with patch.object(deps,'_validate_profiles',wraps=deps._validate_profiles) as check:
        with deps.validation_scope():
            deps.validate_profiles(profiles)
            deps.validate_profiles(deepcopy(profiles))
            assert check.call_count==1
            altered=deepcopy(profiles);altered[key]['payload']['authored']='changed'
            with pytest.raises(ValueError):deps.validate_profiles(altered)
            with pytest.raises(ValueError):deps.validate_profiles(altered)
            assert check.call_count==3
        deps.validate_profiles(profiles)
        assert check.call_count==4


def test_shared_subsets_reuse_only_exact_resolved_profile_validation():
    from app.comparison.shared_templates import ProfilePool,validate
    with deps.validation_scope():
        key,value=deps.profile('fee',{'rule':{'version':'authored','rate':'0.01'}})
        pool=ProfilePool(compact=True);assert pool.add(key,value)
        profiles=pool.finish()
        validate(profiles)
        bad=deepcopy(profiles)
        template=next(iter(bad['templates'].values()))
        template['payload']['rate']='0.99'
        with pytest.raises(ValueError):validate(bad)
        bad=deepcopy(profiles);bad['bindings'][key]['expires_at']='not-a-clock'
        with pytest.raises(ValueError):validate(bad)
        validate(deepcopy(profiles))


def discovery_context(records=None):
    from tests.test_current_board_reads import context,frame
    from app.storage import latest_board as latest
    c=context(frame(records) if records is not None else None)
    c.publication_runtime=latest.runtime_identity(dict(active=True,healthy=True))
    c.result_control=None
    return c


def prepared_discovery(c):
    from app.storage.discovery_index import prepare
    from app.comparison.estimated_policy import DEFAULT_POLICY
    observed=c.observation_bundles()[0]
    return prepare(c,observed['game_key'],DEFAULT_POLICY,observed)


def test_discovery_reuse_rehydrates_exact_selected_inputs_and_manifests():
    from app.storage import discovery_index as index
    from app.storage import result_dependencies as units
    from app.comparison.estimated_policy import DEFAULT_POLICY
    from app.storage.current_rows import contract_id
    from app.dashboard.comparison_board import entries
    from tests.test_current_board_reads import frame
    index.clear()
    original=frame()['records']
    cold=prepared_discovery(discovery_context(original))
    assert not cold['_discovery_reused']
    changed=deepcopy(original)
    for r in changed:
        if r['quote']['venue']!='pinnacle':
            r['quote']['original']['value']='0.37' if r['quote']['original']['units']=='usd_per_contract' else r['quote']['original']['value']
            if r['quote']['original'].get('transformation')=='one_minus_native_bid':
                r['quote']['original']['native_value']='0.63'
            r['quote']['provenance']['sha256']='f'*64
    c=discovery_context(changed)
    warm=prepared_discovery(c)
    assert warm['_discovery_reused']
    assert c.occurrence_index_reused
    full=c.bundles(game=warm['game_key'])[0]
    assert warm['_discovery_plan']['units']==units.partitions(full)
    for unit in warm['_discovery_plan']['units']:
        sliced=index.hydrate(c,warm,unit,DEFAULT_POLICY)
        expected=units.slice_bundle(full,unit)
        from app.comparison.shared_templates import keys,resolve
        for value in (sliced,expected):
            profiles=value['state_inputs']['comparison_profiles']
            value['state_inputs']['comparison_profiles']={key:resolve(profiles,key) for key in keys(profiles)}
        assert sliced['state_inputs']==expected['state_inputs']
        assert {contract_id(dict(quote=q)) for _,_,q in entries(sliced['state_inputs'])}==set(warm['_discovery_plan']['contracts'][unit['id']])
    index.clear()
    assert not prepared_discovery(discovery_context(changed))['_discovery_reused']


def test_occurrence_reuse_matches_fresh_resolver_including_new_receipt_audit():
    from app.storage import discovery_index as index
    from app.storage.comparison_board import _records
    from app.comparison.occurrence_matching import OccurrenceResolver
    from tests.test_current_board_reads import frame
    from tests.test_ev09_n01 import AT
    index.clear()
    rows=_records(frame()['records'],AT)
    first,reused=index.resolve(rows,at=AT,engine='e',epoch='one')
    assert not reused
    changed=deepcopy(rows)
    for r in changed:
        if r['quote']['venue']!='pinnacle':
            r['quote']['provenance']['sha256']='a'*64
            r['quote']['times']['received_at']=AT
    second,reused=index.resolve(changed,at=AT,engine='e',epoch='one')
    assert reused
    assert second==OccurrenceResolver().resolve(changed,clock=AT)
    second[0]['event']['title']='mutated detached result'
    third,reused=index.resolve(changed,at=AT,engine='e',epoch='one')
    assert reused and third==OccurrenceResolver().resolve(changed,clock=AT)
    assert not index.resolve(changed,at=AT,engine='e',epoch='two')[1]


def test_discovery_candidate_reference_eligibility_and_authority_invalidation():
    from app.storage import discovery_index as index
    from tests.test_current_board_reads import frame
    rows=frame()['records']
    index.clear()
    prepared_discovery(discovery_context(rows))
    assert prepared_discovery(discovery_context(rows))['_discovery_reused']
    # A new complete captured universe never inherits an old absence proof.
    removed=rows[:-1]
    assert not prepared_discovery(discovery_context(removed))['_discovery_reused']
    changed=deepcopy(rows)
    ref=next(r for r in changed if r['quote']['venue']=='pinnacle')
    ref['quote']['times']['received_at']='2026-09-15T00:00:00Z'
    assert not prepared_discovery(discovery_context(changed))['_discovery_reused']
    c=discovery_context(rows);c.result_control='new Stop barrier'
    assert not prepared_discovery(c)['_discovery_reused']
    eligible=deepcopy(rows)
    eligible[0]['verified']=not eligible[0]['verified']
    assert index.structural_record(rows[0])!=index.structural_record(eligible[0])
    changed=deepcopy(rows)
    changed[0]['quote']['state']='unavailable'
    assert not prepared_discovery(discovery_context(changed))['_discovery_reused']


def test_discovery_retention_and_temporal_boundaries_are_bounded():
    from app.storage import discovery_index as index
    from tests.test_ev09_n01 import AT
    index.clear()
    with patch.object(index,'MAX_BYTES',1),patch.object(index,'OCCURRENCE_BYTES',1):
        prepared_discovery(discovery_context())
        assert not index._CACHE and not index._OCCURRENCES
    value={'unselected_rule':{'effective_from':AT}}
    from app.storage.store import stamp
    from datetime import timedelta
    assert index.temporal_partition(value,AT)!=index.temporal_partition(value,(stamp(AT)-timedelta(seconds=1)).isoformat())
