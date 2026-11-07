"""Complete census durability is independent of subsequent socket success."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.collection import bulk_native
from tests.multisport_fixtures import fake_discovery, source_case
from tests.test_current_multisport_ingress import worker


class CatalogCheckpoint(unittest.IsolatedAsyncioTestCase):
    async def run_discovery(self, venue, failure):
        value, published = worker(venue, ['NFL'], ['moneyline'])
        original_catalog=deepcopy(value.catalog);original_markets=deepcopy(value.markets)
        fake_discovery(value, [source_case('NFL', 'moneyline', 'checkpoint-order')])
        order = []; saved = []
        enumerate_native = bulk_native.enumerate_native
        # Fake HTTP produces the real complete catalog. Introduce the storage
        # boundary after enumeration, without using any installed database.
        async def enumerate_fixture(w):
            result = await enumerate_native(w)
            w.checkpoint = SimpleNamespace(scope='fixture', finish=lambda: order.append('finish'))
            return result
        def adopt(source, catalog):
            order.append('adopt'); published.append(deepcopy(catalog))
            if failure == 'adoption': raise ValueError('adoption failed')
            if failure == 'stop': value.service.dispatch = False
        def save(source, scope, catalog, parsed):
            self.assertEqual(source, venue); self.assertEqual(scope, 'fixture')
            self.assertEqual(set(parsed), set(value.markets))
            self.assertEqual(catalog['acquisition_census_generation'], 'fixture-census')
            order.append('save'); saved.append(deepcopy(catalog))
            if failure == 'save': raise ValueError('save failed')
        async def transition():
            order.append('socket')
            raise ConnectionError('socket closed after adoption')
        value.service.catalog = adopt
        value.finish_subscription_transition = transition
        expected = asyncio.CancelledError if failure == 'stop' else ValueError if failure in ('adoption', 'save') else ConnectionError
        with patch.object(bulk_native, 'enumerate_native', new=enumerate_fixture), patch(
                'app.collection.bulk_checkpoint.save_census', return_value='fixture-census'), patch(
                'app.collection.native_recovery.save', side_effect=save), patch.object(value, 'stream', new=AsyncMock()) as stream:
            with self.assertRaises(expected): await value.discover()
            stream.assert_not_awaited()
        if failure == 'socket':
            self.assertEqual(order, ['adopt', 'save', 'finish', 'socket'])
            expected_catalog = dict(published[-1], acquisition_census_generation='fixture-census')
            self.assertEqual(saved[0], expected_catalog)
            self.assertTrue(value.markets)
            self.assertFalse(value.synchronization.images)
            self.assertTrue(all(not lease.get('image_current') for lease in value.lifecycle.leases.values()))
        elif failure == 'save': self.assertEqual(order, ['adopt', 'save'])
        else: self.assertEqual(order, ['adopt'])
        if failure=='adoption':
            self.assertEqual(value.catalog,original_catalog)
            self.assertEqual(value.markets,original_markets)
            self.assertFalse(value.lifecycle.leases)
            self.assertIsNone(value.subscription_transition)

    async def test_adopted_catalog_survives_socket_failure_without_book_authority(self):
        for venue in ('kalshi', 'polymarket_us'):
            with self.subTest(venue=venue): await self.run_discovery(venue, 'socket')

    async def test_adoption_failure_stop_and_save_failure_do_not_finish_or_subscribe(self):
        for venue in ('kalshi', 'polymarket_us'):
            for failure in ('adoption', 'stop', 'save'):
                with self.subTest(venue=venue, failure=failure): await self.run_discovery(venue, failure)
