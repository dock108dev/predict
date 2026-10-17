"""Independent episode and physical-storage oracles; authored facts, no providers."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from threading import Condition, Event
from unittest import TestCase
from unittest.mock import patch

from app.comparison.scanner_projection import Filters, Projection
from app.comparison.scanner_summaries import (
    HEADER_BYTES, MAX_BYTES, MAX_JOINT, MAX_QUEUE, SummaryStore, SummaryWorker,
)

AT = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def clock(seconds=0):
    return (AT + timedelta(seconds=seconds)).isoformat()


def fact(index=0, *, category='covered_outcome_arb', edge='2', size='100', revision='0'):
    return dict(id=f'row:{category}:{index}', opportunity_id=f'opportunity:{index}',
        pair_id=f'pair:{index}', category=category, current=True,
        sport='americanfootball', league='NFL', market='winner', period='full_game',
        venues=['kalshi', 'polymarket_us'], dependency_revision=revision,
        economic_revision=revision, expires_at=clock(1000000),
        source_clocks=[dict(source_at=clock(), received_at=clock())], edge=edge, size=size)


def snapshot(rows=(), *, seconds=0, publication=None, reason='evaluated',
             pending=False, errors=False, state=None, pair_ids=None, epoch='epoch:0'):
    rows = deepcopy(list(rows))
    ids = sorted(set(pair_ids if pair_ids is not None else [r['pair_id'] for r in rows] or ['pair:0']))
    complete = not pending and not errors and (state is None or state in ('evaluated_positive', 'evaluated_zero')) and reason not in ('expired', 'stopped', 'capture_failed')
    pairs = [dict(id=identity, sport='americanfootball', league='NFL', market='winner',
        period='full_game', venues=['kalshi', 'polymarket_us'], complete=complete, pending=pending,
        expires_at=clock(1000000)) for identity in ids]
    return dict(server_id='authored:sc06', epoch=epoch,
        publication=seconds + 1 if publication is None else publication,
        observed_at=clock(seconds), reason=reason,
        state=state or ('evaluated_positive' if rows else 'evaluated_zero'),
        pending=pending, errors=errors, rows=rows, pairs=pairs,
        scopes=[dict(venue=v, sport='americanfootball', league='NFL', market='winner',
            period='full_game', state='ready') for v in ('kalshi', 'polymarket_us')],
        options=dict(venues=['kalshi', 'polymarket_us'], sports=['americanfootball'],
            leagues=['NFL'], markets=['winner'], periods=['full_game']))


class EpisodeSemantics(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='predict-sc06-summary-')
        self.path = Path(self.folder.name) / 'episodes.sc06'
        self.store = SummaryStore(self.path)
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.store.close)

    def read(self, seconds=0, **filters):
        return self.store.read(filters=Filters(**filters), at=clock(seconds))

    def test_baseline_and_unchanged_receipts_do_not_create_episodes(self):
        row = fact()
        self.store.observe(snapshot([row]))
        physical = self.path.stat().st_size
        for index in range(1, 101):
            changed = deepcopy(row)
            changed['source_clocks'][0]['received_at'] = clock(index)
            self.store.observe(snapshot([changed], seconds=index))
        result = self.read(100)
        self.assertEqual(result['counts']['observed_episodes'], 1)
        self.assertEqual(result['counts']['observed_new'], 0)
        self.assertEqual(result['counts']['left_censored'], 1)
        record = next(iter(self.store.records.values()))
        self.assertEqual(record['first_observed'], clock())
        self.assertEqual(record['last_observed'], clock(100))
        self.assertEqual(record['meaningful_changes'], 0)
        self.assertEqual(self.path.stat().st_size, physical)

    def test_new_requires_observed_same_pair_zero_then_authoritative_withdrawal(self):
        self.store.observe(snapshot())
        self.store.observe(snapshot([fact()], seconds=1))
        self.store.observe(snapshot(seconds=2))
        result = self.read(2)
        self.assertEqual(result['counts']['observed_new'], 1)
        self.assertEqual(result['counts']['left_censored'], 0)
        self.assertEqual(result['duration_seconds']['complete_episodes'], 1)
        record = next(iter(self.store.records.values()))
        self.assertEqual(record['termination'], 'withdrawn')
        self.assertFalse(record['right_censored'])
        self.assertEqual(result['duration_seconds']['maximum_observed'], 0)
        self.store.observe(snapshot([fact(1)], seconds=3))
        self.assertEqual(self.read(3)['counts']['left_censored'], 1)

    def test_pending_is_intermediate_and_coverage_loss_is_censored(self):
        self.store.observe(snapshot([fact()]))
        self.store.observe(snapshot(seconds=1, pending=True, state='partial'))
        self.assertEqual(self.read(1)['counts']['open'], 1)
        self.assertIsNone(self.read(1)['coverage']['checked_zero'])
        self.store.observe(snapshot([fact(revision='1')], seconds=2))
        self.assertEqual(self.read(2)['counts']['observed_episodes'], 1)
        self.store.observe(snapshot(seconds=3, pair_ids=['pair:elsewhere']))
        record = next(iter(self.store.records.values()))
        self.assertEqual(record['termination'], 'coverage_gap')
        self.assertTrue(record['right_censored'])

    def test_same_pair_negative_proof_survives_intermediate_pending_work(self):
        self.store.observe(snapshot())
        self.store.observe(snapshot(seconds=1, pending=True, state='partial'))
        self.store.observe(snapshot([fact()], seconds=2))
        result = self.read(2)
        self.assertEqual(result['counts']['observed_new'], 1)
        self.assertEqual(result['counts']['left_censored'], 0)

    def test_partial_ready_pair_observed_while_unrelated_pair_pending_or_failed(self):
        initial = snapshot(pair_ids=['pair:0', 'pair:1'])
        self.store.observe(initial)
        partial = snapshot([fact()], seconds=1, pair_ids=['pair:0', 'pair:1'], pending=True, state='partial')
        partial['pairs'][0].update(complete=True, pending=False)
        self.store.observe(partial)
        result = self.read(1)
        self.assertEqual(result['counts']['observed_episodes'], 1)
        self.assertEqual(result['counts']['observed_new'], 1)
        self.assertFalse(result['coverage']['complete'])
        unrelated_error = snapshot([fact(edge='7', revision='1')], seconds=2,
                                   pair_ids=['pair:0', 'pair:1'], errors=True, state='incomplete')
        unrelated_error['pairs'][0].update(complete=True, pending=False)
        self.store.observe(unrelated_error)
        result = self.read(2)
        self.assertEqual(result['counts']['observed_episodes'], 1)
        self.assertEqual(result['counts']['open'], 1)
        self.assertEqual(result['edge_percent']['maximum'], '7')
        self.assertIsNone(result['coverage']['checked_zero'])

    def test_ev_reference_loss_is_unknown_and_reappearance_is_left_censored(self):
        self.store.observe(snapshot([fact(category='ev')]))
        self.store.observe(snapshot([fact()], seconds=1))
        missing = self.read(1, category='ev')
        self.assertFalse(missing['coverage']['complete'])
        self.assertIsNone(missing['coverage']['checked_zero'])
        old = next(r for r in self.store.records.values() if r['category'] == 'ev')
        self.assertEqual(old['termination'], 'coverage_gap')
        self.assertTrue(old['right_censored'])
        self.store.observe(snapshot([fact(category='ev', revision='again')], seconds=2))
        again = self.read(2, category='ev')
        self.assertEqual(again['counts']['observed_episodes'], 2)
        self.assertEqual(again['counts']['left_censored'], 2)
        self.assertEqual(again['counts']['observed_new'], 0)

    def test_selected_complete_scope_is_available_despite_unrelated_pending_pair(self):
        partial = snapshot([fact()], pending=True, state='partial', pair_ids=['pair:0', 'pair:1'])
        partial['pairs'][0].update(complete=True, pending=False)
        partial['pairs'][1]['league'] = 'NBA'
        partial['options']['leagues'].append('NBA')
        partial['scopes'] += [dict(s, league='NBA', state='pending') for s in partial['scopes']]
        self.store.observe(partial)
        self.assertFalse(self.read()['coverage']['complete'])
        selected = self.read(leagues=('NFL',))
        self.assertTrue(selected['coverage']['complete'])
        self.assertFalse(selected['coverage']['checked_zero'])
        self.assertEqual(selected['counts']['observed_episodes'], 1)

    def test_negative_only_coverage_hole_is_a_persistent_gap_without_active_episode(self):
        for removed in (False, True):
            with self.subTest(removed=removed):
                self.store.observe(snapshot(seconds=10))
                unknown = snapshot(seconds=11, errors=True, state='incomplete')
                if removed:
                    unknown['pairs'] = []
                self.store.observe(unknown)
                self.store.observe(snapshot(seconds=12))
                result = self.read(12)
                self.assertTrue(result['history']['continuity_lost'])
                self.assertFalse(result['history']['complete'])
                self.assertGreater(result['coverage']['gaps'], 0)

    def test_errors_stop_expiry_unknown_and_epoch_cut_continuity(self):
        for reason, errors, state in (
            ('evaluated', True, 'evaluated_positive'), ('stopped', False, 'stopped'),
            ('expired', False, 'unavailable'), ('capture_failed', False, 'incomplete'),
            ('evaluated', False, 'unavailable'),
        ):
            with self.subTest(reason=reason, errors=errors, state=state):
                self.store.observe(snapshot([fact()], seconds=10))
                self.store.observe(snapshot(seconds=11, reason=reason, errors=errors, state=state))
                self.assertEqual(len(self.store.active), 0)
                self.store.observe(snapshot([fact()], seconds=12))
                self.assertTrue(self.store.records[self.store.active[fact()['id']]]['left_censored'])
        self.store.observe(snapshot([fact()], seconds=13, epoch='epoch:new'))
        self.assertTrue(self.store.records[self.store.active[fact()['id']]]['left_censored'])
        self.assertGreater(self.read(13)['counts']['gap_censored'], 0)

    def test_category_separation_and_coverage_checked_zero_remains_unknown_on_expiry(self):
        self.store.observe(snapshot([fact(category='conditional_hedge'), fact(category='ev')]))
        self.assertEqual(self.read()['counts']['observed_episodes'], 0)
        self.assertTrue(self.read()['coverage']['checked_zero'])
        self.assertEqual(self.read(category='conditional_hedge')['counts']['observed_episodes'], 1)
        self.assertEqual(self.read(category='ev')['counts']['observed_episodes'], 1)
        self.assertFalse(self.read(1000000)['coverage']['complete'])
        self.assertIsNone(self.read(1000000)['coverage']['checked_zero'])
        self.store.observe(snapshot(seconds=1))
        self.assertTrue(self.read(1)['coverage']['checked_zero'])
        self.assertIsNone(self.read(1000000)['coverage']['checked_zero'])
        self.assertFalse(self.read(1, leagues=('NBA',))['coverage']['complete'])

    def test_extrema_update_inside_alert_cooldown_and_joint_thresholds_need_witness(self):
        self.store.observe(snapshot([fact(edge='10', size='20')]))
        self.store.observe(snapshot([fact(edge='1', size='200', revision='1')], seconds=1))
        self.store.observe(snapshot([fact(edge='11', size='10', revision='2')], seconds=2))
        result = self.read(2)
        self.assertEqual(result['edge_percent']['maximum'], '11')
        self.assertEqual(result['supported_capital_usd']['maximum'], '200')
        self.assertEqual(next(iter(self.store.records.values()))['meaningful_changes'], 2)
        self.assertEqual(self.read(2, minimum_edge='9', minimum_size='100')['counts']['observed_episodes'], 0)
        self.assertTrue(self.read(2, minimum_edge='9', minimum_size='100')['history']['threshold_history_complete'])
        self.store.observe(snapshot([fact(edge='9', size='100', revision='3')], seconds=3))
        self.assertEqual(self.read(3, minimum_edge='9', minimum_size='100')['counts']['observed_episodes'], 1)

    def test_joint_frontier_overflow_is_explicit(self):
        for index in range(MAX_JOINT + 3):
            self.store.observe(snapshot([fact(edge=str(index + 1), size=str(100-index), revision=str(index))], seconds=index))
        record = next(iter(self.store.records.values()))
        self.assertLessEqual(len(record['joint']), MAX_JOINT)
        self.assertFalse(record['joint_complete'])
        result = self.read(MAX_JOINT + 2, minimum_edge='1', minimum_size='100')
        self.assertFalse(result['history']['threshold_history_complete'])
        self.assertEqual(result['counts']['observed_episodes'], 0)

    def test_restart_censors_prior_open_episode_and_preserves_extrema(self):
        self.store.observe(snapshot([fact(edge='3')]))
        self.store.close()
        self.store = SummaryStore(self.path)
        self.addCleanup(self.store.close)
        old = next(iter(self.store.records.values()))
        self.assertEqual(old['termination'], 'restart')
        self.assertTrue(old['right_censored'])
        self.store.observe(snapshot([fact(edge='2')], seconds=2))
        self.assertEqual(self.read(2)['counts']['observed_episodes'], 2)
        self.assertEqual(self.read(2)['edge_percent']['maximum'], '3')
        self.assertEqual(self.read(2)['counts']['left_censored'], 2)


class StorageBounds(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='predict-sc06-bounds-')
        self.path = Path(self.folder.name) / 'episodes.sc06'
        self.addCleanup(self.folder.cleanup)

    def make(self, **caps):
        store = SummaryStore(self.path, **caps)
        self.addCleanup(store.close)
        return store

    def test_count_eviction_deterministic_and_old_episode_eviction_keeps_new_active(self):
        store = self.make(max_episodes=2)
        store.observe(snapshot([fact()], seconds=0))
        store.observe(snapshot(seconds=1))
        store.observe(snapshot([fact(revision='again')], seconds=2))
        store.observe(snapshot([fact(revision='again'), fact(1)], seconds=3))
        self.assertEqual(len(store.records), 2)
        self.assertEqual(len(store.active), 2)
        self.assertEqual({r['first_observed'] for r in store.records.values()}, {clock(2), clock(3)})
        self.assertEqual(store.meta['evicted'], 1)
        self.assertTrue(store.read(at=clock(3))['history']['continuity_lost'])

    def test_retention_is_first_observation_age_and_eviction_does_not_extend_on_update(self):
        store = self.make(retention_seconds=10)
        store.observe(snapshot([fact()]))
        store.observe(snapshot([fact(revision='1')], seconds=9))
        store.observe(snapshot([fact(revision='2')], seconds=10))
        self.assertEqual(len(store.records), 1)
        self.assertEqual(next(iter(store.records.values()))['first_observed'], clock(10))
        self.assertTrue(next(iter(store.records.values()))['left_censored'])
        self.assertEqual(store.meta['evicted'], 1)

    def test_byte_cap_first_and_repeated_updates_bound_real_physical_growth(self):
        store = self.make(max_bytes=HEADER_BYTES + 3 * 4096, max_episodes=100)
        store.observe(snapshot([fact(index) for index in range(7)]))
        self.assertEqual(len(store.records), 3)
        physical = max(self.path.stat().st_size, self.path.stat().st_blocks * 512)
        for index in range(1, 101):
            store.observe(snapshot([fact(j, revision=str(index)) for j in range(4, 7)], seconds=index))
        result = store.read(at=clock(100))
        self.assertEqual(max(self.path.stat().st_size, self.path.stat().st_blocks * 512), physical)
        self.assertLessEqual(result['bounds']['physical_high_water_bytes'], HEADER_BYTES + 3 * 4096)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ['episodes.sc06'])

    def test_default_full_physical_cap_real_growth_without_unbounded_sidecars(self):
        store = self.make()
        store.observe(snapshot([fact(index) for index in range(2700)]))
        self.assertIsNone(store.failed)
        self.assertEqual(store.capacity, 2047)
        self.assertEqual(len(store.records), store.capacity)
        self.assertEqual(store.meta['evicted'], 2700 - store.capacity)
        stat = self.path.stat()
        self.assertLessEqual(max(stat.st_size, stat.st_blocks * 512), MAX_BYTES)
        self.assertEqual(stat.st_size, HEADER_BYTES + store.capacity * 4096)
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)

    def test_corrupt_slot_recovery_and_one_physical_owner(self):
        store = self.make()
        store.observe(snapshot([fact(), fact(1)]))
        with self.assertRaises((BlockingIOError, OSError)):
            SummaryStore(self.path)
        slot = min(store.slots.values())
        store.close()
        with self.path.open('r+b') as stream:
            stream.seek(HEADER_BYTES + slot * 4096 + 40)
            stream.write(b'CORRUPTED')
        recovered = self.make()
        self.assertEqual(len(recovered.records), 1)
        self.assertTrue(recovered.meta['lost'])
        self.assertGreaterEqual(recovered.meta['gaps'], 1)
        self.assertTrue(next(iter(recovered.records.values()))['right_censored'])

    def test_truncated_header_recovers_with_explicit_unknown_history(self):
        for length in (1, 2, 3):
            with self.subTest(length=length):
                self.path.write_bytes(b'\x00' * length)
                store = SummaryStore(self.path)
                try:
                    self.assertTrue(store.meta['lost'])
                    self.assertGreaterEqual(store.meta['gaps'], 1)
                    self.assertEqual(len(store.records), 0)
                    self.assertFalse(store.read(at=clock())['coverage']['complete'])
                finally:
                    store.close()

    def test_restart_after_checked_zero_or_ended_history_still_records_gap(self):
        for ended in (False, True):
            with self.subTest(ended=ended):
                self.path.unlink(missing_ok=True)
                store = SummaryStore(self.path)
                if ended:
                    store.observe(snapshot([fact()]))
                store.observe(snapshot(seconds=1))
                store.close()
                reopened = SummaryStore(self.path)
                try:
                    self.assertTrue(reopened.meta['lost'])
                    self.assertGreater(reopened.meta['gaps'], 0)
                    self.assertFalse(reopened.read(at=clock(2))['coverage']['complete'])
                    reopened.observe(snapshot([fact()], seconds=2))
                    active = reopened.records[reopened.active[fact()['id']]]
                    self.assertTrue(active['left_censored'])
                finally:
                    reopened.close()

    def test_close_sync_failure_releases_descriptor_and_exclusive_ownership(self):
        store = self.make()
        store.observe(snapshot([fact()]))
        with patch('app.comparison.scanner_summaries.os.fsync', side_effect=OSError('authored sync failure')):
            with self.assertRaises(OSError):
                store.close()
        self.assertIsNone(store.fd)
        reopened = self.make()
        self.assertTrue(reopened.records)

    def test_write_failure_returns_unavailable_without_escaping_to_projection(self):
        store = self.make()
        store.observe(snapshot([fact()]))
        with patch('app.comparison.scanner_summaries.os.pwrite', side_effect=OSError('authored disk full')):
            store.observe(snapshot([fact(revision='1')], seconds=1))
        result = store.read(at=clock(1))
        self.assertEqual(result['state'], 'unavailable')
        self.assertFalse(result['coverage']['complete'])
        self.assertIn('summary_write_failed', result['notes'])
        p = Projection()
        p.summary_observer = lambda value: (_ for _ in ()).throw(OSError('authored store failure'))
        p.stop()
        self.assertTrue(p.stopped)

    def test_worker_is_lazy_and_queue_overflow_censors_without_unbounded_tasks(self):
        worker = SummaryWorker(self.path)
        self.addCleanup(worker.close)
        self.assertFalse(self.path.exists())
        self.assertEqual(worker.read(at=clock())['state'], 'unavailable')
        self.assertFalse(self.path.exists())
        entered, release = Event(), Event()
        original = SummaryStore.observe
        def paused(store, obs):
            if obs['publication'] == 1:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('authored release missing')
            return original(store, obs)
        with patch.object(SummaryStore, 'observe', paused):
            worker.offer(snapshot([fact()]))
            self.assertTrue(entered.wait(5))
            for index in range(1, MAX_QUEUE * 3):
                worker.offer(snapshot([fact(revision=str(index))], seconds=index))
            self.assertLessEqual(len(worker.queue), MAX_QUEUE)
            release.set()
            self.assertTrue(worker.flush(10))
        result = worker.read(at=clock(MAX_QUEUE * 3))
        self.assertTrue(result['history']['continuity_lost'])
        self.assertGreater(result['coverage']['gaps'], 0)
        self.assertLessEqual(len(worker.store.active), worker.store.capacity)

    def test_worker_idle_maintenance_does_not_open_store_before_publication(self):
        idle_finished = Event()
        class ImmediateIdleTimeout(Condition):
            first = True
            def wait_for(self, predicate, timeout=None):
                if self.first:
                    self.first = False
                    return False
                idle_finished.set()
                return super().wait_for(predicate, timeout)
        condition = ImmediateIdleTimeout()
        with patch('app.comparison.scanner_summaries.Condition', return_value=condition):
            worker = SummaryWorker(self.path)
        try:
            self.assertTrue(idle_finished.wait(5))
            self.assertIsNone(worker.store)
            self.assertFalse(self.path.exists())
        finally:
            worker.close()

    def test_worker_failed_open_is_bounded_and_never_throws_on_read(self):
        self.path.write_text('a regular file cannot contain a summary child')
        worker = SummaryWorker(self.path / 'child')
        self.addCleanup(worker.close)
        worker.offer(snapshot([fact()]))
        self.assertTrue(worker.flush(5))
        result = worker.read(at=clock())
        self.assertEqual(result['state'], 'unavailable')
        self.assertFalse(result['coverage']['complete'])
        self.assertTrue(result['history']['continuity_lost'])
        self.assertEqual(result['provider_requests'], 0)
        self.assertEqual(result['financial_evaluations'], 0)
