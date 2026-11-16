"""Public list reuse and representation respect evidence boundaries."""
import asyncio
from datetime import datetime, timedelta, timezone
from gzip import decompress
from unittest import IsolatedAsyncioTestCase

from aiohttp.web import HTTPServiceUnavailable

from app.dashboard.desk_delivery import MAX_DESK_READS, ReadBurst, common_page, encode, gzip_allowed


class TestDeskDelivery(IsolatedAsyncioTestCase):
    async def test_late_list_completion_can_be_picked_up_by_the_next_retry(self):
        clock = [0.0]
        reads = ReadBurst(clock=lambda: clock[0])
        entered, finish = asyncio.Event(), asyncio.Event()
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            entered.set()
            await finish.wait()
            return calls, 6.0, 100

        first = asyncio.create_task(reads.read('list', load, reuse=0, late_reuse=3.5))
        await entered.wait()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        clock[0] = 1.5
        finish.set()
        await asyncio.gather(*reads.active)
        clock[0] = 3.0
        self.assertEqual(await reads.read('list', load, reuse=0, late_reuse=3.5), (1, True))
        self.assertEqual(await reads.read('list', load, reuse=0, late_reuse=3.5), (2, False))

    async def test_distinct_and_unshared_reads_share_capacity_until_completion(self):
        reads = ReadBurst()
        full = asyncio.Event()
        finish = asyncio.Event()
        started = 0

        async def load():
            nonlocal started
            started += 1
            if started == MAX_DESK_READS:
                full.set()
            await finish.wait()
            return 'packet', float('inf'), 0

        jobs = [asyncio.create_task(reads.read(index, load)) for index in range(MAX_DESK_READS)]
        await full.wait()
        jobs[0].cancel()
        with self.assertRaises(asyncio.CancelledError):
            await jobs[0]
        try:
            async def over_capacity():
                self.fail('over-capacity read started')

            with self.assertRaises(HTTPServiceUnavailable):
                await reads.read('another key', over_capacity)
            with self.assertRaises(HTTPServiceUnavailable):
                await reads.read(None, over_capacity)
            follower = asyncio.create_task(reads.read(0, load))
            await asyncio.sleep(0)
        finally:
            finish.set()
            await asyncio.gather(*jobs[1:])
        self.assertEqual(await follower, ('packet', True))
        self.assertEqual(started, MAX_DESK_READS)
        self.assertEqual(await reads.read(None, load), ('packet', False))

    async def test_no_waiter_receives_a_packet_that_expired_in_flight(self):
        clock = [10.0]
        reads = ReadBurst(clock=lambda: clock[0])
        fill_started = asyncio.Event()
        finish = asyncio.Event()
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            if calls == 1:
                fill_started.set()
                await finish.wait()
                return 'first packet', 10.2, 0
            return 'new packet', 11.0, 0

        first = asyncio.create_task(reads.read('list', load))
        await fill_started.wait()
        early = asyncio.create_task(reads.read('list', load))
        await asyncio.sleep(0)
        clock[0] = 10.3
        late = asyncio.create_task(reads.read('list', load))
        await asyncio.sleep(0)
        finish.set()
        with self.assertRaises(HTTPServiceUnavailable):
            await first
        self.assertEqual((await early)[0], 'new packet')
        self.assertEqual((await late)[0], 'new packet')
        self.assertEqual(calls, 2)

    async def test_one_fill_for_a_burst_and_no_reuse_past_quote_deadline(self):
        clock = [10.0]
        reads = ReadBurst(clock=lambda: clock[0])
        fill_started = asyncio.Event()
        finish = asyncio.Event()
        loads = []

        async def load():
            loads.append(1)
            fill_started.set()
            await finish.wait()
            return 'packet', 10.2 if len(loads) == 1 else float('inf'), 100

        leaving = asyncio.create_task(reads.read('ordinary', load))
        await fill_started.wait()
        arrivals = [asyncio.create_task(reads.read('ordinary', load)) for _ in range(64)]
        leaving.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await leaving
        finish.set()
        self.assertEqual(await asyncio.gather(*arrivals), [('packet', True)] * 64)
        self.assertEqual(loads, [1])
        self.assertEqual(await reads.read('ordinary', load), ('packet', True))
        clock[0] = 10.2
        self.assertEqual(await reads.read('ordinary', load), ('packet', False))
        self.assertEqual(len(loads), 2)
        self.assertEqual(await reads.read('updates', load, reuse=0), ('packet', False))
        self.assertEqual(await reads.read('updates', load, reuse=0), ('packet', False))

    def test_compact_gzip_representation_and_bound(self):
        at = datetime(2026, 11, 15, 15, tzinfo=timezone.utc)
        page = {'rows': ['repeat the same public quote fields'] * 100,
                'refresh_at': (at + timedelta(seconds=0.25)).isoformat()}
        (identity, packed), expires, size = encode(page, at=at, started=100)
        self.assertEqual(decompress(packed), identity)
        self.assertLess(len(packed), len(identity) / 4)
        self.assertEqual(size, len(packed) + len(identity))
        self.assertEqual(expires, 100.25)
        self.assertTrue(gzip_allowed('br, gzip;q=0.7'))
        self.assertFalse(gzip_allowed('gzip;q=0, *'))
        self.assertFalse(gzip_allowed('identity, notgzip'))

    def test_shared_key_excludes_filters_with_user_text_and_page_membership(self):
        query = {'layout': 'desk', 'summary': '1', 'phase': 'pregame', 'limit': '12'}
        options = ('ev', 'conditional_return_percent', 0, 12)
        self.assertEqual(common_page(query, options)[0], 'list')
        for other in ({'search': 'teams'}, {'browse_id': 'token'}, {'locate': 'event'},
                      {'game_key': 'game'}, {'phase': 'live'}):
            self.assertIsNone(common_page(query | other, options))
