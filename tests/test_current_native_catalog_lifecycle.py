"""Independent bounded-catalog continuity and Stop checks; fake transport only."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.collection.current_policy import DEFAULT
from app.collection import coverage
from app.collection.native_selectors import query
from app.comparison.coverage import CoverageLedger
from tests.multisport_fixtures import current_book, fake_discovery, source_case
from tests.test_current_multisport_ingress import worker


class CatalogContinuity(unittest.IsolatedAsyncioTestCase):
    async def test_omitted_parent_cannot_clear_observed_market_id_conflict(self):
        value, _ = worker('polymarket_us', ['NFL'], ['moneyline'])
        cases = [source_case('NFL', 'moneyline', 'market-id-collision-first'),
                 source_case('NFL', 'moneyline', 'market-id-collision-second')]
        market_id = cases[0]['markets']['polymarket_us']['id']
        second = cases[1]['events']['polymarket_us']['markets'][0]
        second['id'] = market_id
        for side in second['marketSides']:
            side['marketId'] = market_id
        fake_discovery(value, cases)
        at = datetime.now(timezone.utc)
        path, params = query('polymarket_us', 'NFL', at, families=['moneyline'])
        value._coverage_sport = 'NFL'
        value._coverage_checked = set()
        await value.get(path, dict(params, limit=5, offset=0), 'events')
        pages = deepcopy(value.pages)
        event_id = cases[1]['events']['polymarket_us']['id']
        full = coverage.catalog(pages, 'polymarket_us', at, compact_output=False)
        selected = coverage.catalog(pages, 'polymarket_us', at, compact_output=False,
                                    current_selection=dict(events=[event_id], markets=[market_id]))
        original = next(row for row in full['markets'] if row['id'] == market_id)
        projected = selected['markets'][0]
        self.assertTrue(original['conflicting_duplicate'])
        self.assertTrue(projected['conflicting_duplicate'])
        self.assertEqual(projected['exclusion'], original['exclusion'])
        self.assertEqual(pages, value.pages)

    async def test_omitted_sibling_cannot_clear_observed_slug_ambiguity(self):
        value, _ = worker('polymarket_us', ['NFL'], ['moneyline'])
        cases = [source_case('NFL', 'moneyline', 'slug-collision-first'),
                 source_case('NFL', 'moneyline', 'slug-collision-second')]
        cases[1]['events']['polymarket_us']['markets'][0]['slug'] = cases[0]['markets']['polymarket_us']['slug']
        fake_discovery(value, cases)
        at = datetime.now(timezone.utc)
        path, params = query('polymarket_us', 'NFL', at, families=['moneyline'])
        value._coverage_sport = 'NFL'
        value._coverage_checked = set()
        await value.get(path, dict(params, limit=5, offset=0), 'events')
        pages = deepcopy(value.pages)
        event_id = cases[1]['events']['polymarket_us']['id']
        market_id = cases[1]['markets']['polymarket_us']['id']
        full = coverage.catalog(pages, 'polymarket_us', at, compact_output=False)
        selected = coverage.catalog(pages, 'polymarket_us', at, compact_output=False,
                                    current_selection=dict(events=[event_id], markets=[market_id]))
        original = next(row for row in full['markets'] if row['id'] == market_id)
        projected = selected['markets'][0]
        self.assertEqual(original['subscription_evidence_exclusion'], 'ambiguous_subscription_slug')
        self.assertEqual(projected['subscription_evidence_exclusion'], original['subscription_evidence_exclusion'])
        self.assertEqual(pages, value.pages)

    async def test_selected_later_event_preserves_original_flattened_provenance(self):
        value, _ = worker('polymarket_us', ['NFL'], ['moneyline'])
        cases = [source_case('NFL', 'moneyline', 'provenance-first'),
                 source_case('NFL', 'moneyline', 'provenance-second')]
        for case, count in zip(cases, (2, 3)):
            native = case['markets']['polymarket_us']
            rows = []
            for index in range(count):
                row = deepcopy(native)
                row['id'] += str(index)
                row['slug'] += '-' + str(index)
                for side in row['marketSides']:
                    side['marketId'] = row['id']
                    side['id'] += str(index)
                rows.append(row)
            case['events']['polymarket_us']['markets'] = rows
        fake_discovery(value, cases)
        at = datetime.now(timezone.utc)
        path, params = query('polymarket_us', 'NFL', at, families=['moneyline'])
        value._coverage_sport = 'NFL'
        value._coverage_checked = set()
        await value.get(path, dict(params, limit=5, offset=0), 'events')
        pages = deepcopy(value.pages)
        full = coverage.catalog(pages, 'polymarket_us', at, compact_output=False)
        event_id = cases[1]['events']['polymarket_us']['id']
        market_id = cases[1]['events']['polymarket_us']['markets'][2]['id']
        selected = coverage.catalog(pages, 'polymarket_us', at, compact_output=False,
                                    current_selection=dict(events=[event_id], markets=[market_id]))
        for kind, identity in (('events', event_id), ('markets', market_id)):
            original = next(row for row in full[kind] if row['id'] == identity)
            projected = next(row for row in selected[kind] if row['id'] == identity)
            self.assertEqual(projected['provenance'], original['provenance'])
        self.assertEqual(pages, value.pages)

    async def seeded(self, venue):
        value, published = worker(venue, ['NFL'], ['moneyline'])
        value.service.coverage = CoverageLedger({venue: ['NFL']}, ['moneyline'])
        case = source_case('NFL', 'moneyline', 'independent-catalog-continuity')
        cases = [case]
        calls = fake_discovery(value, cases)
        await value.discover()
        self.assertEqual(len(value.markets), 1)
        value.lifecycle.begin_connection(1)
        value.metrics['connections'] = 1
        value.source_highwater['independent-original-clock'] = 123
        images = []
        value.service.books = lambda *args: images.append(deepcopy(args))
        started = asyncio.Event()
        socket = SimpleNamespace(close=AsyncMock())
        value.socket = socket

        async def held_stream():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await socket.close()
                value.socket = None

        value.stream_task = asyncio.create_task(held_stream())
        await started.wait()
        value.queue_book(current_book(case, venue))
        # Hold the authored pending batch until after the control assertions;
        # ordinary publication timers are covered by current-native tests.
        value.publication_handle.cancel()
        value.publication_handle = asyncio.get_running_loop().call_later(60, value.flush_books)
        # One complete response can be valid transport while its repeated
        # normalized metadata would exceed the existing 2 MiB inventory bound.
        large = source_case('NFL', 'moneyline', 'independent-unfit-catalog')
        native = large['markets'][venue]
        field = 'rules_primary' if venue == 'kalshi' else 'description'
        native[field] += ' Complete original source wording.' * 30000
        if venue == 'polymarket_us':
            large['events'][venue]['markets'] = [deepcopy(native)]
        cases[:] = [large]
        return value, published, calls, images, socket

    def coherent_state(self, value):
        return dict(catalog=deepcopy(value.catalog), markets=dict(value.markets),
                    signature=value.signature, leases=deepcopy(value.lifecycle.leases),
                    books=deepcopy(value.lifecycle.books), highwater=deepcopy(value.source_highwater),
                    pending=deepcopy(value.pending_books), stream=value.stream_task,
                    handle=value.publication_handle)

    def assert_coherent(self, value, before):
        self.assertEqual(value.catalog, before['catalog'])
        self.assertEqual(value.markets, before['markets'])
        self.assertEqual(value.signature, before['signature'])
        self.assertEqual(value.lifecycle.leases, before['leases'])
        self.assertEqual(value.lifecycle.books, before['books'])
        self.assertEqual(value.source_highwater, before['highwater'])
        self.assertEqual(value.pending_books, before['pending'])
        self.assertIs(value.stream_task, before['stream'])
        self.assertIs(value.publication_handle, before['handle'])

    async def test_infeasible_rediscovery_retains_complete_owned_frame(self):
        for venue in ('kalshi', 'polymarket_us'):
            with self.subTest(venue=venue):
                value, published, calls, images, socket = await self.seeded(venue)
                before = self.coherent_state(value)
                count = len(published)
                last_success = deepcopy(value.service.coverage.family_observations[('NFL', venue, 'moneyline')]['last_success'])
                try:
                    await value.discover()
                    self.assert_coherent(value, before)
                    self.assertEqual(len(published), count)
                    self.assertEqual(images, [])
                    self.assertFalse(value.failed)
                    self.assertEqual(value.pages, [])
                    self.assertEqual(value.metrics['catalog_projection']['state'], 'retained_previous')
                    self.assertEqual(value.metrics['catalog_projection']['reason'], 'native_source_inventory_cap')
                    coverage_cell = value.service.coverage.family_observations[('NFL', venue, 'moneyline')]
                    self.assertEqual(coverage_cell['last_success'], last_success)
                    self.assertEqual(coverage_cell['latest']['status'], 'not_checked')
                    self.assertEqual(coverage_cell['latest']['reason'], 'query_capacity')
                    self.assertEqual(coverage_cell['latest']['completeness'], 'partial')
                    self.assertEqual(coverage_cell['latest']['offered'], dict(games=None, markets=None, quotes=None))
                    self.assertLessEqual(len(calls), 2 * DEFAULT['discovery_pages'])
                    socket.close.assert_not_awaited()
                finally:
                    await value.close()
                socket.close.assert_awaited_once()
                self.assertFalse(value.lifecycle.dispatch)
                self.assertEqual(value.lifecycle.leases, {})
                self.assertEqual(value.pending_books, {})
                self.assertTrue(before['stream'].done())
                self.assertEqual(images, [])

    async def test_stop_at_capacity_deferred_due_wait_never_restarts_discovery(self):
        value, published, calls, images, socket = await self.seeded('kalshi')
        value.service.deadline = float('inf')
        waiting = asyncio.Event()
        client = SimpleNamespace(budget=SimpleNamespace(requests=0, bytes=0), aclose=AsyncMock())

        async def due_wait(seconds):
            self.assertEqual(seconds, DEFAULT['rediscovery_seconds'])
            waiting.set()
            await asyncio.Event().wait()

        with patch('app.collection.current_native.load_credentials', return_value={'kalshi': object()}), \
                patch('app.collection.current_native.REST', return_value=client), \
                patch('app.collection.current_native.native_payload.configure_transport'), \
                patch('app.collection.current_native.asyncio.sleep', side_effect=due_wait):
            task = asyncio.create_task(value.run())
            try:
                await asyncio.wait_for(waiting.wait(), 5)
                self.assertFalse(value.failed)
                self.assertEqual(value.metrics['catalog_projection']['state'], 'retained_previous')
                self.assertEqual(len(published), 1)
                count = len(calls)
                # Stop revokes dispatch before cancellation/cleanup can yield.
                value.service.dispatch = False
                value.lifecycle.revoke()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                self.assertEqual(len(calls), count)
                self.assertEqual(images, [])
                socket.close.assert_awaited_once()
                self.assertFalse(value.lifecycle.dispatch)
                self.assertEqual(value.lifecycle.leases, {})
                self.assertEqual(value.pending_books, {})
                self.assertEqual(value.metrics['owned_subscriptions'], 0)
                client.aclose.assert_awaited_once()
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await value.close()


if __name__ == '__main__':
    unittest.main()
