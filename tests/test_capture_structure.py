"""Incremental structure must equal complete capture, never cached authority."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.storage import capture_structure as plans, discovery_index
from app.storage.comparison_board import ReadContext
from tests.test_current_board_reads import frame, AT


def capture(value, *, binding=None, at=AT):
    return ReadContext(SimpleNamespace(db=None),at=at,frame=value,
        reuse_catalog_inputs=True,capture_binding=binding).observation_bundles()


def test_exact_incremental_material_confirmation_reference_and_control_matrix():
    plans.clear()
    original=frame()
    assert capture(deepcopy(original),binding='policy/settings/control')==capture(deepcopy(original))
    cases=[]
    for venue in ('kalshi','polymarket_us'):
        material=deepcopy(original)
        q=next(r['quote'] for r in material['records'] if r['quote']['venue']==venue)
        q['original']['value']='0.37'
        if q['original'].get('transformation')=='one_minus_native_bid':q['original']['native_value']='0.63'
        q['provenance']['sha256']='f'*64
        q['times']['received_at']='2026-10-14T01:15:10Z'
        cases.append(material)
        confirmation=deepcopy(original)
        q=next(r['quote'] for r in confirmation['records'] if r['quote']['venue']==venue)
        q['times']['received_at']='2026-10-14T01:15:10Z'
        cases.append(confirmation)
    reference=deepcopy(original)
    next(r for r in reference['records'] if r['quote']['venue']=='pinnacle')['quote']['original']['value']='2.1'
    cases.append(reference)
    for state in ('stopped','resyncing','connecting','available'):
        value=deepcopy(original);value['source_status']={'kalshi':dict(state=state)};cases.append(value)
    removed=deepcopy(original);removed['records']=removed['records'][1:];cases.append(removed)
    reset=deepcopy(original);reset['epoch']='new-epoch';cases.append(reset)
    for value in cases:
        before=deepcopy(value)
        assert capture(value,binding='policy/settings/control')==capture(deepcopy(value))
        assert value==before
    assert plans.metrics()['hits']>=6
    # An elapsed authority/fee boundary never comes from the stored plan.
    for at in ('2026-10-14T01:15:59Z','2026-10-14T03:00:00Z'):
        assert capture(deepcopy(original),binding='policy/settings/control',at=at)==capture(deepcopy(original),at=at)
    misses=plans.metrics()['misses']
    capture(deepcopy(original),binding='changed fee/model/settings/control')
    assert plans.metrics()['misses']>misses


def test_fresh_depth_and_invalid_complement_still_pass_complete_validator():
    plans.clear();original=frame();capture(deepcopy(original),binding='same')
    changed=deepcopy(original)
    q=next(r['quote'] for r in changed['records'] if r['quote']['venue']=='kalshi')
    q['depth']=[dict(price='0.43',quantity='987654321.123456789')]
    assert capture(changed,binding='same')==capture(deepcopy(changed))
    q['original']['value']='0.12'
    for binding in (None,'same'):
        with pytest.raises(ValueError,match='complement'):capture(deepcopy(changed),binding=binding)


def test_bounded_transfer_corruption_and_output_mutation_rebuild(tmp_path):
    plans.clear();original=frame();expected=capture(deepcopy(original),binding='same')
    path=tmp_path/'plans.json';assert plans.save(path)
    plans.load(path)
    value=capture(deepcopy(original),binding='same');assert value==expected
    value[0]['state_inputs']['events'][0]['title']='changed by caller'
    assert capture(deepcopy(original),binding='same')==expected
    key=next(iter(plans._plans));at,_,proof=plans._plans[key];plans._plans[key]=(at,b'broken',proof)
    assert capture(deepcopy(original),binding='same')==expected
    assert plans.metrics()['invalid']==1
    with patch.object(plans,'MAX_BYTES',1):
        plans.clear();assert capture(deepcopy(original),binding='same')==expected
        assert plans.metrics()['entries']==0
    path.write_text('{');plans.load(path);assert plans.metrics()['entries']==0


def test_structural_proof_shells_never_edit_original_evidence():
    records=frame()['records'];before=deepcopy(records)
    for r in records:discovery_index.structural_record(r)
    assert records==before


def test_immutable_contract_reuse_checks_current_rule_content():
    from app.comparison import native_scoring_scope as scope
    plans.clear();original=frame()
    expected=capture(deepcopy(original),binding='same')
    with patch.object(scope,'attach',side_effect=AssertionError('Unchanged rules must reuse their proved result')):
        assert capture(deepcopy(original),binding='same')==expected
    rules=deepcopy(scope.source_rules());rules[0]['native_type']='authored-different-rule'
    misses=plans.metrics()['misses']
    with patch.object(scope,'source_rules',return_value=rules):
        assert capture(deepcopy(original),binding='same')==capture(deepcopy(original))
    assert plans.metrics()['misses']>misses
