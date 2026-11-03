from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
import pytest
from app.dashboard import comparison_board as board
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.storage.comparison_board import calculate_current
from app.storage.store import stamp
from tests.test_current_board_reads import context,bundle
from tests.test_ev09_n01 import AT


@pytest.mark.parametrize('state',['unchanged','changed','expired','pending'])
def test_shared_financial_render_matches_separate_validations(state):
    c=context();b=bundle(c);value=calculate_current(b,DEFAULT_POLICY,context=c)
    b['calculation_context']=value['calculation_context']
    at=AT
    if state=='changed':
        q=board.entries(b['state_inputs'])[0][2]
        q['revision']='meaningfully-changed-input'
    if state=='expired':at=(stamp(AT)+timedelta(hours=8)).isoformat()
    if state=='pending':value=None
    original=deepcopy((b,value))
    expected={view:board.response(b,value,DEFAULT_POLICY,view=view,filter='all',at=at) for view in ('ev','arbs')}
    with patch.object(board,'age',wraps=board.age) as age:
        actual=board.financial_responses(b,value,DEFAULT_POLICY,at=at)
    assert actual==expected
    assert age.call_count==(0 if value is None else 1)
    assert (b,value)==original
    actual['ev']['policy']['revision']='caller-mutated'
    assert actual['arbs']['policy']['revision']!='caller-mutated'
