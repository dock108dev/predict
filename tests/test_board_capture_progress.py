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
