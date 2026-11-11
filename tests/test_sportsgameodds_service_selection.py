import asyncio
from pathlib import Path
import tempfile
import unittest

from app.collection.current_policy import DEFAULT, validate
from app.collection.current_service import CurrentService
from app.collection.local_ownership import LocalOwnership
from app.dashboard.current_state import CurrentStore
from tests.test_current_service import FakeWorker


class AggregateSelection(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_config_defaults_to_existing_provider(self):
        old = dict(DEFAULT)
        old.pop('aggregate_provider')
        self.assertEqual(validate(old)['aggregate_provider'], 'the_odds_api')

    async def test_unconfigured_sgo_does_not_fall_back_to_paid_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = CurrentService(config=dict(DEFAULT, aggregate_provider='sportsgameodds'),
                directory=root/'state', ownership=LocalOwnership(root/'owner'), worker_factory=FakeWorker)
            store = CurrentStore(service)
            try:
                await service.start(store)
                self.assertNotIn('the_odds_api', service.workers)
                self.assertIn('sportsgameodds', service.workers)
                await asyncio.sleep(0)
                self.assertEqual(service.states['novig']['state'], 'unavailable')
                self.assertIn('kalshi', service.workers)
                self.assertIn('polymarket_us', service.workers)
            finally:
                await service.close()
                await store.close()

    async def test_sgo_pause_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def no_start(_):
                raise AssertionError('paused provider must not start')
            service = CurrentService(config=dict(DEFAULT, aggregate_provider='sportsgameodds'),
                directory=root/'state', ownership=LocalOwnership(root/'owner'), worker_factory=FakeWorker,
                sgo_factory=no_start, paused_sources={'sportsgameodds'})
            store = CurrentStore(service)
            try:
                await service.start(store)
                self.assertEqual(service.states['novig']['state'], 'stopped')
                self.assertIn('kalshi', service.workers)
                self.assertIn('polymarket_us', service.workers)
            finally:
                await service.close()
                await store.close()
