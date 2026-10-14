import unittest
from app.collection.current_aggregate import AggregateScheduler
from app.collection.odds_http import BudgetStop
from unittest.mock import AsyncMock,Mock
from types import SimpleNamespace
class StorageRefusal(unittest.IsolatedAsyncioTestCase):
    async def test_full_journal_is_precise_and_paid_worker_stops(self):
        ledger=Mock();ledger.snapshot.return_value={'pause':None}
        service=SimpleNamespace(dispatch=True,store=SimpleNamespace(closed=False),issue=Mock())
        worker=AggregateScheduler(service,ledger=ledger,transport=SimpleNamespace())
        worker.restore_retained=Mock();worker.step=AsyncMock(side_effect=BudgetStop('current_observation_storage_cap'));worker.state=Mock()
        await worker.run()
        worker.step.assert_awaited_once();ledger.pause.assert_called_once_with('current_observation_storage_cap')
        service.issue.assert_called_once_with('the_odds_api','quota_or_source','current_observation_storage_cap')
