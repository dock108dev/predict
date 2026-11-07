"""Exact group reuse versus the complete admission oracle, including failures."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.storage import capture_materialization as cache
from app.storage.comparison_board import ReadContext
from app.dashboard.current_contract import drain,serialize_steps
from app.comparison.estimated_policy import DEFAULT_POLICY
from tests.test_current_board_reads import frame,AT


def raw_state():
    context=ReadContext(SimpleNamespace(db=None),at=AT,frame=frame(),reuse_catalog_inputs=True)
    context.catalog_bundles()
    return deepcopy(next(iter(context._catalog_inputs.values())))


def complete(raw):
    return drain(serialize_steps(deepcopy(raw),prices_only=True,estimate_policy=DEFAULT_POLICY))


def test_incremental_exact_material_depth_confirmation_membership_and_clock_matrix(tmp_path):
    raw=raw_state();cache.clear()
    assert cache.materialize(raw,binding='exact')==complete(raw)
    path=tmp_path/'material.json';assert cache.save(path);cache.load(path)
    assert cache.materialize(raw,binding='exact')==complete(raw)
    assert cache.metrics()['hits']
    cases=[]
    for clock in ('2026-10-14T01:15:59Z','2026-10-14T03:00:00Z'):
        value=deepcopy(raw);value['clock_at']=clock;cases.append(value)
    for mode in ('price','depth','confirmation','rule','remove','resyncing','stopped'):
        value=deepcopy(raw);o=next(o for e in value['events'] for g in e['groups'] for o in g['outcomes'] if o['quotes'])
        q=next(iter(o['quotes'].values()))
        if mode=='price':
            q['original']['value']='0.37'
            if q['original'].get('transformation')=='one_minus_native_bid':q['original']['native_value']='0.63'
            elif 'native_value'in q['original']:q['original']['native_value']='0.37'
        elif mode=='depth':q['depth']=[dict(price='0.37',quantity='9007199254740993.00000001')]
        elif mode=='confirmation':q['times']['received_at']='2026-10-14T01:15:59Z'
        elif mode=='rule':q['rule_note']+=' changed'
        elif mode=='remove':o['quotes'].pop(next(iter(o['quotes'])))
        else:q['state']=mode
        cases.append(value)
    for value in cases:
        original=deepcopy(value)
        assert cache.materialize(value,binding='exact')==complete(value)
        assert value==original
    misses=cache.metrics().get('misses',0)
    assert cache.materialize(raw,binding='new epoch/settings/fee/model/control')==complete(raw)
    assert cache.metrics()['misses']>misses
    changed=cache.materialize(raw,binding='exact');changed['events'][0]['title']='caller'
    assert cache.materialize(raw,binding='exact')==complete(raw)


def test_reuse_does_not_bypass_cross_group_identity_or_envelope_guards():
    raw=raw_state();cache.clear();cache.materialize(raw,binding='exact')
    bad=deepcopy(raw);bad['state']='invented'
    with pytest.raises(ValueError):cache.materialize(bad,binding='exact')
    bad=deepcopy(raw);bad['events'][0]['groups'].append(deepcopy(bad['events'][0]['groups'][0]))
    with pytest.raises(ValueError,match='Duplicate exact group'):cache.materialize(bad,binding='exact')
    with patch.object(cache,'MAX_BYTES',1):
        cache.clear();assert cache.materialize(raw,binding='exact')==complete(raw)
        assert cache.metrics()['entries']==0
