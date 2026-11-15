"""Public list reuse and representation respect evidence boundaries."""
import asyncio
from datetime import datetime, timedelta, timezone
from gzip import decompress
from unittest import IsolatedAsyncioTestCase

from app.dashboard.desk_delivery import ReadBurst, common_page, encode, gzip_allowed


class TestDeskDelivery(IsolatedAsyncioTestCase):
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
