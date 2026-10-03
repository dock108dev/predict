"""Supported pre-start zero-aggregate boundary, including guarded recovery."""
from copy import deepcopy
import asyncio
from unittest.mock import Mock
from app.collection.current_policy import DEFAULT, validate
from tests.test_current_service import ServiceLifecycle

class NativeOnly(ServiceLifecycle):
    async def test_disable_survives_recovery_without_constructing_aggregate(self):
        self.service.config=validate(dict(DEFAULT,aggregate_enabled=False))
        factory=Mock(side_effect=AssertionError('Aggregate must never be constructed'))
        self.service.aggregate_factory=factory
        await self.service.start(self.store)
        stream=asyncio.Queue(maxsize=1);self.store.subscribers.add(stream)
        first=self.service.runtime_id
        status=await self.service.recover(first,self.service.digest)
        await asyncio.sleep(0)
        self.assertNotEqual(first,status['runtime_id'])
        self.assertEqual(set(self.service.workers),{'kalshi','polymarket_us'})
        self.assertEqual(status['odds_api_requests'],0)
        self.assertIsNone(status['quota'])
        self.assertTrue(all(status['source_status'][v]['reason_code']=='aggregate_disabled' for v in ('novig','prophetx')))
        factory.assert_not_called()
        self.assertFalse(self.service.attempt['config']['aggregate_enabled'])
        self.store.subscribers.discard(stream)

    def test_legacy_configuration_and_strict_boolean(self):
        legacy=deepcopy(DEFAULT);legacy.pop('aggregate_enabled')
        self.assertTrue(validate(legacy)['aggregate_enabled'])
        for invalid in (0,None,'false'):
            with self.assertRaises(ValueError):validate(dict(DEFAULT,aggregate_enabled=invalid))
