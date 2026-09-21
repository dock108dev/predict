"""Offline actual-loop expiry scheduling and receive ownership regressions."""
import asyncio
from datetime import timedelta
import unittest
from unittest.mock import patch

from app.adapters.kalshi_stream import MarketStream
from app.models.core import BookSync, ReceiptFreshness
from tests.test_kalshi import NOW, ack, frame, market


class ExpiryTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_sibling_cannot_defer_expiry(self):
        clock = [NOW]
        messages = [(0, ack()), (0, frame(1, mid='quiet')),
                    (0, frame(2, mid='busy')),
                    (31, frame(3, 'orderbook_delta', mid='busy')),
                    (32, frame(4, 'orderbook_delta', mid='busy'))]

        class Clock:
            @staticmethod
            def now(tz): return clock[0]

        class Conn:
            async def send(self, body): pass
            async def close(self): pass
            async def recv(self):
                age, body = messages.pop(0)
                clock[0] = NOW + timedelta(seconds=age)
                return body

        async def factory(): return Conn()
        stream = MarketStream([market('quiet'), market('busy')], factory,
                              stale_seconds=30, duration=60, max_connections=1,
                              max_messages=5)
        observed = []
        with patch('app.adapters.kalshi_stream.datetime', Clock):
            async for book in stream.run():
                if book.sync == BookSync.SYNCHRONIZED:
                    observed.append((book.raw.ref.market_id, book.receipt_freshness,
                                     (clock[0] - NOW).total_seconds()))
        self.assertIn(('quiet', ReceiptFreshness.STALE, 31), observed)
        self.assertEqual(sum(mid == 'quiet' and fresh == ReceiptFreshness.STALE
                             for mid, fresh, _ in observed), 1)

    async def test_real_timer_expires_while_sibling_keeps_receiving(self):
        # Small threshold only in this fixture; production configuration is untouched.
        class Conn:
            def __init__(self):
                self.frames = [ack(), frame(1, mid='quiet'), frame(2, mid='busy')]
                self.seq, self.closed, self.active, self.maximum = 2, False, 0, 0
            async def send(self, body): pass
            async def close(self): self.closed = True
            async def recv(self):
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                try:
                    if self.frames: return self.frames.pop(0)
                    await asyncio.sleep(.002)
                    self.seq += 1
                    return frame(self.seq, 'orderbook_delta', mid='busy')
                finally:
                    self.active -= 1
        conn = Conn()
        async def factory(): return conn
        stream = MarketStream([market('quiet'), market('busy')], factory,
                              stale_seconds=.03, duration=.4, max_connections=1)
        iterator = stream.run()
        start = asyncio.get_running_loop().time()
        try:
            async for book in iterator:
                if book.raw.ref.market_id == 'quiet' and book.receipt_freshness == ReceiptFreshness.STALE:
                    self.assertEqual(book.sync, BookSync.SYNCHRONIZED)
                    self.assertLess(asyncio.get_running_loop().time() - start, .2)
                    break
            else:
                self.fail('quiet market never expired during sibling traffic')
        finally:
            await iterator.aclose()
        self.assertTrue(conn.closed)
        self.assertEqual((conn.active, conn.maximum), (0, 1))
        self.assertGreater(conn.seq, 3)
        self.assertLess(conn.seq, 100)
        self.assertIsNone(stream._receive_task)

    async def test_transport_timeout_then_unchanged_snapshot_recovers(self):
        clock = [NOW]
        entries = [(0, ack()), (0, frame(1)), (30.000001, None), (31, frame(2))]
        class Clock:
            @staticmethod
            def now(tz): return clock[0]
        class Conn:
            closed = False
            async def send(self, body): pass
            async def close(self): self.closed = True
            async def recv(self):
                age, body = entries.pop(0)
                clock[0] = NOW + timedelta(seconds=age)
                if body is None: raise TimeoutError
                return body
        conn = Conn()
        async def factory(): return conn
        stream = MarketStream([market()], factory, stale_seconds=30,
                              duration=60, max_connections=1, max_messages=3)
        with patch('app.adapters.kalshi_stream.datetime', Clock):
            books = [b async for b in stream.run() if b.sync == BookSync.SYNCHRONIZED]
        self.assertEqual([b.receipt_freshness.value for b in books], ['recent', 'stale', 'recent'])
        self.assertEqual(books[0].outcomes, books[2].outcomes)
        self.assertEqual(books[2].raw.received_at, NOW + timedelta(seconds=31))
        self.assertEqual(stream.engine.generation, 1)
        self.assertFalse(any(d['event'] == 'connection_or_protocol_failure' for d in stream.diagnostics))
        self.assertTrue(conn.closed)

    async def exercise(self, actions, *, stop=None):
        """Run real stream/reconstructor/tasks, controlling UTC and wait readiness only."""
        clock, waits, received, cancelled = [NOW], [], [], []
        queue = asyncio.Queue()
        active = [0, 0]
        real_wait = asyncio.wait
        current = [None]
        trace = []

        class Clock:
            @staticmethod
            def now(tz): return clock[0]

        class Conn:
            closed = False
            async def send(self, body): pass
            async def close(self): self.closed = True
            async def recv(self):
                active[0] += 1
                active[1] = max(active)
                try:
                    body = await queue.get()
                    received.append(body)
                    return body
                except asyncio.CancelledError:
                    cancelled.append(True)
                    raise
                finally:
                    active[0] -= 1

        conn = Conn()
        async def factory(): return conn
        stream = MarketStream([market('quiet'), market('busy')], factory,
                              stale_seconds=30, duration=90, max_connections=1)

        async def controlled_wait(tasks, *, timeout):
            self.assertEqual(len(tasks), 1)
            task = next(iter(tasks))
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, .5)
            if current[0] is not None:
                self.assertIs(task, current[0], 'timer replaced pending receive')
            waits.append(timeout)
            if not actions:
                # Ensure receive actually starts before Stop/cancellation.
                await asyncio.sleep(0)
                if stop == 'cancel':
                    raise asyncio.CancelledError
                await stream.aclose()
                return {task}, set()
            age, body = actions.pop(0)
            clock[0] = NOW + timedelta(seconds=age)
            if body is None:
                current[0] = task
                await asyncio.sleep(0)
                return set(), {task}
            queue.put_nowait(body)
            done, pending = await real_wait(tasks, timeout=1)
            self.assertEqual(done, {task})
            current[0] = None
            return done, pending

        with patch('app.adapters.kalshi_stream.datetime', Clock), \
             patch('app.adapters.kalshi_stream.asyncio.wait', controlled_wait):
            iterator = stream.run()
            try:
                async for book in iterator:
                    if book.sync == BookSync.SYNCHRONIZED:
                        trace.append((book.raw.ref.market_id, book.receipt_freshness.value,
                                      (clock[0] - NOW).total_seconds(), book))
            except asyncio.CancelledError:
                self.assertEqual(stop, 'cancel')
            finally:
                await iterator.aclose()
        self.assertTrue(conn.closed)
        self.assertEqual(active, [0, 1])
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(stream.message_count, len(received))
        self.assertEqual(len(received), len(set(received)))
        self.assertLess(len(waits), 30, 'unexpected timer spinning')
        return trace, waits, stream

    async def test_boundaries_recovery_unchanged_and_one_emission_per_episode(self):
        trace, waits, stream = await self.exercise([
            (0, ack()), (0, frame(1, mid='quiet')), (0, frame(2, mid='busy')),
            (29.999999, None), (30, None), (30.000001, None),
            (31, frame(3, 'orderbook_delta', mid='busy')),
            (32, frame(4, 'orderbook_delta', mid='quiet', delta_fp='0')),
            (61, None), (62, None), (62.000001, None), (63, None)])
        quiet = [(f, t, b) for m, f, t, b in trace if m == 'quiet']
        self.assertEqual([(f, t) for f, t, _ in quiet],
                         [('recent', 0), ('stale', 30.000001),
                          ('recent', 32), ('stale', 62.000001)])
        self.assertEqual(quiet[0][2].outcomes, quiet[2][2].outcomes)
        self.assertEqual(quiet[2][2].raw.received_at, NOW + timedelta(seconds=32))
        self.assertAlmostEqual(waits[4], .000001, places=9)
        self.assertAlmostEqual(waits[5], .000001, places=9)

    async def test_simultaneous_expiry_and_receive_are_both_processed_once(self):
        trace, _, stream = await self.exercise([
            (0, ack()), (0, frame(1, mid='quiet')), (0, frame(2, mid='busy')),
            (30.000001, frame(3, 'orderbook_delta', mid='quiet')),
            (30.000002, frame(4, 'orderbook_delta', mid='busy'))])
        self.assertEqual([(m, f, t) for m, f, t, _ in trace], [
            ('quiet', 'recent', 0), ('busy', 'recent', 0),
            ('quiet', 'stale', 30.000001), ('busy', 'stale', 30.000001),
            ('quiet', 'recent', 30.000001), ('busy', 'recent', 30.000002)])
        self.assertEqual(stream.engine.seq, None)  # cleanup invalidates subscription

    async def test_control_traffic_does_not_refresh_receipts(self):
        trace, _, _ = await self.exercise([
            (0, ack()), (0, frame(1, mid='quiet')), (0, frame(2, mid='busy')),
            (30, '{"type":"ok","sid":7,"seq":3,"msg":{}}'),
            (30.000001, None)])
        self.assertEqual([(m, t) for m, f, t, _ in trace if f == 'stale'],
                         [('quiet', 30.000001), ('busy', 30.000001)])

    async def test_cancellation_cleans_pending_receive(self):
        await self.exercise([(0, ack()), (0, frame(1, mid='quiet')),
                             (0, frame(2, mid='busy')), (1, None)], stop='cancel')


if __name__ == '__main__':
    unittest.main()
