"""Component planning cannot loop or ignore cancellation on inconsistent membership."""
from unittest.mock import patch
import pytest
from app.storage import board_capture
from app.comparison.calculation_control import cancellation, CalculationStopped


def test_inconsistent_membership_refuses_instead_of_appending_empty_groups():
    frame=dict(active_events={'new-event'},events={},offers={},neighborhoods={})
    with patch.object(board_capture.publication,'identity_index',return_value=frame):
        with pytest.raises(ValueError,match='publication_component_membership_inconsistent'):
            board_capture.capture_batches(None)


def test_cancelled_planning_stops_before_neighborhood_work():
    with patch.object(board_capture.publication,'identity_index',return_value={'active_events':{'a'}}), \
         patch.object(board_capture.publication,'neighborhood') as neighborhood:
        with pytest.raises(CalculationStopped),cancellation(lambda:True):
            board_capture.capture_batches(None)
        neighborhood.assert_not_called()


def test_complete_components_advance_once_including_inactive_peers():
    with patch.object(board_capture.publication,'identity_index',return_value={'active_events':{'a','b','c'}}), \
         patch.object(board_capture.publication,'neighborhood',side_effect=[
             [('a','r',True),('b','r',True),('inactive','r',False)],[('c','r',True)]]):
        assert board_capture.capture_batches(None)==[['a','b','inactive'],['c']]


@pytest.mark.parametrize('failure_name',['LockNotAvailable','SerializationFailure','DeadlockDetected'])
def test_observation_contention_preserves_authority_and_cursor(failure_name):
    import asyncio
    from types import SimpleNamespace
    from psycopg import errors
    from app.storage.latest_board import LatestBoardOwner
    async def exercise():
        owner=LatestBoardOwner(SimpleNamespace(config={}))
        owner.admission_status={'observations_after':'completed-component'}
        async def contend(*args,**kwargs):
            owner.closed=True
            owner.wake.set()
            raise getattr(errors,failure_name)('authored SQL contention')
        with patch('app.collection.background_work.source_thread',side_effect=contend):
            await owner.run(observations_only=True)
        assert owner.observation_error is None and owner.error is None
        assert owner.progress['observations']['reason']=='publication_retry'
        assert owner.admission_status['observations_after']=='completed-component'
    asyncio.run(exercise())


def test_pending_priority_uses_committed_membership_and_preserves_rotation():
    from unittest.mock import MagicMock
    db=MagicMock()
    db.execute.return_value.fetchall.return_value=[{'members':['pending','peer']},{'members':['later']}]
    groups=[['done'],['later'],['pending','peer'],['other-done']]
    assert board_capture.prioritize_pending(db,groups)==[['later'],['pending','peer'],['done'],['other-done']]
    db.execute.return_value.fetchall.return_value=[{'members':['later']}]
    assert board_capture.prioritize_pending(db,groups)==[['later'],['done'],['pending','peer'],['other-done']]


def test_unpublished_window_priority_keeps_peers_and_rotated_order():
    from unittest.mock import MagicMock
    db=MagicMock();db.execute.return_value.fetchall.return_value=[{'id':'new'},{'id':'other'}]
    groups=[['old'],['other','peer'],['new'],['later']]
    assert board_capture.prioritize_unpublished(db,groups,'2026-10-31T12:00:00Z')==[['other','peer'],['new'],['old'],['later']]
    start,end=db.execute.call_args.args[1]
    assert (end-start).total_seconds()==72*3600
    db.execute.return_value.fetchall.return_value=[]
    assert board_capture.prioritize_unpublished(db,groups,'2026-10-31T12:00:00Z')==groups


def test_window_waiters_retry_oldest_component_without_hot_arrival_starvation():
    from unittest.mock import MagicMock
    db=MagicMock()
    db.execute.return_value.fetchall.side_effect=[[
        dict(id='old',attempted='2026-10-31T10:00:00Z'),
        dict(id='hot',attempted='2026-10-31T11:59:00Z'),
        dict(id='new',attempted=None)],[]]
    groups=[['new'],['outside'],['hot'],['old','peer']]
    assert board_capture.prioritize_window_waiters(db,groups,'2026-10-31T12:00:00Z',observations_only=False)==[
        ['old','peer'],['hot'],['new'],['outside']]
    assert db.execute.call_args_list[0].args[1][0]=='metrics'


def test_first_engine_work_precedes_older_completed_work():
    from unittest.mock import MagicMock
    db=MagicMock()
    db.execute.return_value.fetchall.side_effect=[[
        dict(id='done',attempted='2026-10-31T10:00:00Z'),
        dict(id='pending',attempted='2026-10-31T11:00:00Z')],
        [dict(members=['done'])]]
    assert board_capture.prioritize_window_waiters(db,[['done'],['pending']],
        '2026-10-31T12:00:00Z',observations_only=False)==[['pending'],['done']]


def test_hot_priority_work_cannot_reset_ordinary_rotation():
    from contextlib import nullcontext
    from itertools import count
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from app.storage import latest_board as latest
    db=MagicMock();db.execute.return_value.fetchall.return_value=[]
    lease=SimpleNamespace(reason=None,resident_bytes=0)
    budget=SimpleNamespace(acquisition_pressure=lambda:False,
        claim=lambda *a,**kw:nullcontext(lease),resize=lambda *a:None)
    selected=[];admission={}
    def reconcile(db,**kwargs):
        selected.append(kwargs['event_ids'][0])
        return dict(published=False,unchanged=True)
    with patch('app.collection.background_work.BACKGROUND',budget), \
         patch.object(latest,'capture_reservation',return_value=1), \
         patch.object(latest,'runtime',return_value={'runtime_id':'fixture'}), \
         patch('app.storage.board_capture.refresh_waiters',return_value=[]), \
         patch.object(latest,'capture_batches',return_value=[['a-quiet'],['b-quiet'],['z-hot']]), \
         patch.object(board_capture,'prioritize_window_waiters',side_effect=lambda db,groups,*a,**kw:sorted(groups,key=lambda g:g!=['z-hot'])), \
         patch.object(latest,'_reconcile',side_effect=reconcile), \
         patch.object(latest,'monotonic',side_effect=count(0,100)), \
         patch('app.storage.pipeline_attempt.enqueue'), \
         patch('app.storage.pipeline_attempt.scheduled'), \
         patch('app.storage.pipeline_attempt.record'):
        # capture_batches is ordered by its minimum stable source-event ID.
        for _ in range(8):latest.reconcile(db,admission=admission,turn_seconds=1)
    assert selected==['z-hot','z-hot','z-hot','a-quiet','z-hot','z-hot','z-hot','b-quiet']
    assert admission['estimates_rotation_after']=='b-quiet'


@pytest.mark.parametrize('reason',['background_capture_changed','attempt_LockNotAvailable'])
def test_deferred_component_cannot_pin_ordinary_rotation(reason):
    from contextlib import nullcontext
    from itertools import count
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from app.storage import latest_board as latest
    db=MagicMock();db.execute.return_value.fetchall.return_value=[]
    lease=SimpleNamespace(reason=None,resident_bytes=0)
    budget=SimpleNamespace(acquisition_pressure=lambda:False,
        claim=lambda *a,**kw:nullcontext(lease),resize=lambda *a:None)
    selected=[];admission={'estimates_window_turn':3}
    def reconcile(db,**kwargs):
        selected.append(kwargs['event_ids'][0])
        return dict(published=False,unchanged=False,deferred=True,reason=reason)
    with patch('app.collection.background_work.BACKGROUND',budget), \
         patch.object(latest,'capture_reservation',return_value=1), \
         patch.object(latest,'capture_batches',return_value=[['a-blocked'],['b-ready'],['c-ready']]), \
         patch.object(latest,'_reconcile',side_effect=reconcile), \
         patch.object(latest,'monotonic',side_effect=count(0,100)), \
         patch('app.storage.pipeline_attempt.enqueue'), \
         patch('app.storage.pipeline_attempt.scheduled'), \
         patch('app.storage.pipeline_attempt.record'):
        for _ in range(4):
            admission['estimates_window_turn']=3  # Each ordinary fourth turn.
            result=latest.reconcile(db,admission=admission,turn_seconds=1)
            assert result['batches'][0]['state']=='deferred'
    assert selected==['a-blocked','b-ready','c-ready','a-blocked']
