"""Connection authority and delivery progress, independent of price-change age.

Only the ordered reconstructor may acknowledge subscription/image progress.
Heartbeat liveness cannot add an image or repair a broken sequence. A connection
failure revokes the whole affected subscription before asynchronous cleanup.
"""
from collections import deque
from datetime import datetime, timezone
import math


class Synchronization:
    def __init__(self):
        self.generation = 0
        self.members = set()
        self.images = set()
        self.persisted = set()
        self.invalid = set()
        self.active = False
        self.subscription = None
        self.sequence = None
        self.reason = 'not_connected'
        self.latencies = {stage: deque(maxlen=2048) for stage in ('reconstruction', 'raw', 'derived', 'metadata_recalculation')}

    def begin(self, generation, members):
        self.generation = generation
        self.members = set(members)
        self.images.clear()
        self.persisted.clear()
        self.invalid.clear()
        self.active = True
        self.subscription = self.sequence = None
        self.reason = None
        for samples in self.latencies.values():
            samples.clear()

    def acknowledge(self, subscription, sequence=None):
        if self.active:
            self.subscription, self.sequence = subscription, sequence

    def image(self, market):
        if not self.active or self.subscription is None or market not in self.members:
            raise ValueError('Unowned synchronization image')
        self.images.add(market)
        self.invalid.discard(market)

    def persist(self, generation, markets):
        if self.active and generation == self.generation:
            self.persisted.update(set(markets) & self.members)

    def invalidate(self, market):
        self.images.discard(market)
        self.persisted.discard(market)
        self.invalid.add(market)

    def revoke(self, reason):
        self.active = False
        self.reason = reason

    def delivered(self, stage, receipts):
        now = datetime.now(timezone.utc)
        for receipt in receipts:
            elapsed = (now - datetime.fromisoformat(receipt.replace('Z', '+00:00'))).total_seconds()
            self.elapsed(stage,[elapsed])

    def elapsed(self,stage,durations):
        for elapsed in durations:
            if math.isfinite(elapsed) and elapsed>=0:self.latencies[stage].append(elapsed)

    def snapshot(self, metrics, *, enabled=True):
        transport_pending = sum(metrics.get(key, 0) or 0 for key in (
            'receive_buffer_frames', 'reconstruction_inflight_frames',
            'reconstruction_ready_frames', 'processing_inflight_frames'))
        raw_pending = (metrics.get('raw_backlog', 0) or 0) + (metrics.get('raw_inflight_images', 0) or 0)
        derived_pending = (metrics.get('pending_books', 0) or 0) + (metrics.get('derived_inflight_images', 0) or 0)
        active = self.active and enabled and metrics.get('stream_connected', False)
        missing = self.members - self.images
        durable_missing = self.members - self.persisted
        now = datetime.now(timezone.utc)
        delay = metrics.get('receive_oldest_seconds', 0) or 0
        for key in ('reconstruction_oldest_received_at', 'processing_received_at'):
            if metrics.get(key):
                delay = max(delay, (now-datetime.fromisoformat(metrics[key])).total_seconds())
        delay = max(delay, metrics.get('raw_oldest_pending_seconds', 0) or 0)
        state = ('disconnected' if not active else
                 'awaiting_subscription' if self.subscription is None else
                 'partial' if self.invalid else
                 'initializing' if missing or durable_missing else
                 ('catching_up' if delay>2 else 'streaming') if transport_pending or raw_pending else 'synchronized')
        latency = {}
        for stage, samples in self.latencies.items():
            values = sorted(samples)
            latency[stage] = dict(samples=len(values), window='latest_2048_recalculations' if stage=='metadata_recalculation' else 'latest_2048_deliveries',
                basis='metadata_queue_to_processing_complete' if stage=='metadata_recalculation' else 'socket_receipt_to_delivery',
                p50_seconds=values[math.ceil(len(values)*.5)-1] if values else None,
                p95_seconds=values[math.ceil(len(values)*.95)-1] if values else None,
                maximum_seconds=max(values) if values else None)
        return dict(version='native-continuity-1', state=state, generation=self.generation,
            subscription_id=self.subscription, sequence=self.sequence,
            subscribed_markets=len(self.members), initial_images=len(self.images),
            missing_images=len(missing), missing_durable_images=len(durable_missing), invalid_images=len(self.invalid),
            processing_target_seconds=2, oldest_processing_delay_seconds=max(0,delay),
            current=state in ('streaming','synchronized'),
            continuity_intact=bool(active and self.subscription is not None),
            transport_pending_frames=transport_pending, raw_pending_images=raw_pending,
            derived_pending_images=derived_pending, reason=self.reason,
            delivery_latency=latency, price_change_age_is_sync_age=False)
