"""Schedule identity, public-depth storage and collector recovery in disposable SQL."""
import asyncio
from contextlib import closing, nullcontext
from datetime import timedelta
from functools import partial
from multiprocessing import get_context
from pathlib import Path
import signal
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

import psycopg
from psycopg.types.json import Jsonb

from app.collection import experiment_depth as collector
from app.collection.experiment_depth_stage import DepthStage
from app.collection.native_trading import NativeTrading
from app.research import experiment
from app.storage import experiment_depth as depth
from app.storage.store import encoded, hashed
from tests.latest_board_fixture import LatestBoardFixture, SOCKET


def captured_book(known):
    received = known - timedelta(milliseconds=90)
    evidence = dict(path='/native/book', status=200, sha256=hashed('fixture-book'),
                    requested_at=depth.clock(received - timedelta(milliseconds=30)),
                    received_at=depth.clock(received))
    identification = dict(path='/native/market', sha256=hashed('fixture-contract'),
                          observed_at=depth.clock(known - timedelta(seconds=2)))
    return {'fixture-offer': dict(venue='kalshi', market_id='fixture-contract', complete=True,
        levels=[dict(price='2/5', size='100')], receipts=[evidence], identity_receipts=[identification])}


def run_depth_collector(database, stage_path, task, mode, events):
    """Run the actual collector loop in a process that the test can kill."""
    connector = partial(LatestBoardFixture.connect, database)
    target, deadline = task['target_at'], task['deadline_at']
    known = target - timedelta(seconds=1) if mode == 'stage' else deadline + timedelta(seconds=1)

    class DepthProbe(collector.ExperimentDepth):
        def _bindings(self, _task, _at):
            return {}, None, [], None, {}, {'fixture-offer': {}}, (), {}

        async def _observe(self, *_args, **_kwargs):
            if mode != 'stage':
                events.send(('unexpected_venue_request', None))
                raise AssertionError('Recovery dispatched a venue request')
            return captured_book(known), {}

        def _persist(self, payload):
            admission = (patch.object(experiment, '_admit', side_effect=ValueError('research_retention_capacity'))
                         if mode == 'storage_deferred' else nullcontext())
            try:
                with admission:
                    saved = super()._persist(payload)
            except Exception as exc:
                events.send(('publication_deferred', str(exc)))
                raise
            if mode == 'after_commit':
                events.send(('after_commit', saved['id']))
                Event().wait()
            return saved

    async def idle_dashboard(*_args):
        await asyncio.Future()

    async def main():
        worker = SimpleNamespace(controls=lambda: dict(stopped=False, source_paused=False),
                                 now=lambda: known, experiment_late_windows=[(target, deadline)])
        service = SimpleNamespace(dispatch=True, globally_stopped=False,
            paused_sources={'sportsgameodds'} if mode == 'paused' else set(),
            workers={'sportsgameodds': worker}, config=dict(requests_per_source=0, source_bytes=0))
        owner = DepthProbe(service, connector=connector, now=lambda: known, stage_path=stage_path)
        with patch.object(NativeTrading, 'run', idle_dashboard):
            await owner.start()
            try:
                while True:
                    if events.poll():
                        return
                    state = owner.progress
                    if mode == 'stage' and state.get('pending'):
                        events.send(('captured', state['pending']))
                        await asyncio.Future()
                    if mode == 'paused' and state['state'] == 'paused':
                        events.send(('paused', None))
                        await asyncio.Future()
                    await asyncio.sleep(0.02)
            finally:
                await owner.close()

    asyncio.run(main())


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class ExperimentDepthSQL(LatestBoardFixture):
    def declare(self, db, *, event_id, at=None):
        at = at or experiment.utc()
        start = at + timedelta(minutes=10, seconds=20)
        event = dict(provider='sportsgameodds', source_event_id=event_id, event_id=hashed(event_id),
                     league='NCAAB', home='home', away='away', title='Away at Home',
                     starts_at=depth.clock(start), status={})
        experiment.discover(db, [event], at=at)
        row = db.execute("""SELECT t.* FROM public.ev_experiment_task t
                            JOIN public.ev_experiment_game g ON g.id=t.game_id
                            WHERE t.checkpoint='late' AND g.source_event_id=%s""", (event_id,)).fetchone()
        return at, row, event

    async def test_replay_pins_unique_decision_and_rejects_later_receipts(self):
        with self.connect() as db:
            at, task, event = self.declare(db, event_id='depth-schedule-one',
                                           at=experiment.utc() - timedelta(seconds=60))
            evidence = dict(received_at=depth.clock(at), requested_at=depth.clock(at), path='/public',
                            age='NaN', date='Fri, 27 Nov 2026 15:00:00 GMT')
            observations = {'offer1': dict(venue='novig', levels=[], complete=True, receipts=[evidence]),
                            'offer2': dict(venue='novig', levels=[], complete=True, receipts=[evidence])}
            saved = depth.save(db, task, known_at=at, observations=observations)
            self.assertEqual(len(saved['http_receipts']), 1)
            self.assertIsNone(saved['metrics']['max_response_age_seconds'])
            self.assertEqual(saved, depth.save(db, task, known_at=at, observations={}))
            task_ref = (task['game_id'], task['schedule_id'], task['target_at'])
            self.assertEqual(depth.read(db, *task_ref), saved)
            self.assertEqual(depth.input_ids(db, [task_ref]), {task['game_id']: saved['id']})
            self.assertEqual(depth.read_ids(db, [saved['id']]), {saved['id']: saved})
            with self.assertRaises(psycopg.DatabaseError), db.transaction():
                db.execute('DELETE FROM public.ev_experiment_depth WHERE id=%s', (saved['id'],))
            later = task['target_at'] + timedelta(seconds=30)
            with self.assertRaisesRegex(ValueError, 'experiment_depth_cutoff'):
                depth.save(db, task, known_at=later, observations={})
            with self.assertRaisesRegex(ValueError, 'experiment_depth_receipt_clock'):
                depth.save(db, task, known_at=at, observations={'later': {
                    'receipts': [dict(evidence, received_at=depth.clock(later))]}})
            microsecond = at.replace(microsecond=123456)
            submicrosecond = depth.clock(microsecond).replace('.123456+', '.1234561+')
            with self.assertRaisesRegex(ValueError, 'experiment_depth_receipt_clock'):
                depth.normalize(task, known_at=microsecond, observations={'later': {
                    'receipts': [dict(evidence, requested_at=depth.clock(microsecond), received_at=submicrosecond)]}})
            followup = depth.save(db, task, known_at=later, observations={}, kind='followup',
                                  cutoff_at=later, origin_id=saved['id'])
            self.assertEqual(depth.read(db, *task_ref, kind='followup')['id'], followup['id'])
            self.assertEqual(depth.followups(db, [saved['id']]), {saved['id']: followup})
            self.assertEqual(depth.input_ids(db, [task_ref]), {task['game_id']: saved['id']})

            changed = dict(event, starts_at=depth.clock(experiment.stamp(event['starts_at']) + timedelta(hours=2)))
            experiment.discover(db, [changed], at=at)
            revised = db.execute("""SELECT * FROM public.ev_experiment_task
                WHERE game_id=%s AND checkpoint='late'""", (task['game_id'],)).fetchone()
            revised_ref = (revised['game_id'], revised['schedule_id'], revised['target_at'])
            self.assertIsNone(depth.read(db, *revised_ref))
            self.assertEqual(depth.input_ids(db, [revised_ref]), {})
            self.assertEqual(depth.read(db, *task_ref)['id'], saved['id'])

    async def test_candidate_admission_and_nonblocking_writer_leave_sgo_task_untouched(self):
        with self.connect() as db:
            _, task, event = self.declare(db, event_id='depth-active-campaign')
            db.execute("UPDATE public.ev_experiment_game SET early_id=schedule_id WHERE id=%s", (task['game_id'],))
            at = experiment.utc()
            self.assertEqual(collector.targets(db, at), [])
            config = dict(depth_policy=depth.POLICY)
            campaign_id = hashed(config)
            db.execute('INSERT INTO public.paper_campaign VALUES (%s,DEFAULT,%s,%s)',
                       (campaign_id, Jsonb(config), len(encoded(config))))
            db.execute("""INSERT INTO public.paper_campaign_day(campaign_id,game_date)
                VALUES (%s,(%s::timestamptz AT TIME ZONE 'America/New_York')::date)""",
                (campaign_id, event['starts_at']))
            at = experiment.utc()
            self.assertIn(task['game_id'], [row['game_id'] for row in collector.targets(db, at)])
            self.assertEqual(collector.targets(db, at, exclude=[(task['game_id'], task['schedule_id'])]), [])
            self.assertIn(task['game_id'], [row['game_id'] for row in collector.targets(
                db, at, exclude=[(task['game_id'], 'preceding-schedule')])])
            with self.assertRaisesRegex(BlockingIOError, 'protected_tminus10_capture_due'):
                depth.save(db, task, known_at=at, observations={}, protect_checkpoint=True)
            with self.connect() as writer, writer.transaction():
                experiment._lock(writer)
                with self.assertRaisesRegex(BlockingIOError, 'experiment_depth_writer_busy'):
                    depth.save(db, task, known_at=at, observations={})
            after = db.execute("""SELECT * FROM public.ev_experiment_task
                WHERE game_id=%s AND checkpoint='late'""", (task['game_id'],)).fetchone()
            self.assertEqual(task, after)


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class ExperimentDepthRecoverySQL(LatestBoardFixture):
    async def asyncSetUp(self):
        directory = TemporaryDirectory(prefix='predict-native-depth-')
        self.addCleanup(directory.cleanup)
        self.stage_path = Path(directory.name) / 'depth.sqlite3'
        with self.connect() as db:
            db.execute('TRUNCATE ev_experiment_record,ev_experiment_game,ev_experiment_task,'
                       'ev_experiment_accounting,paper_campaign CASCADE')
            db.execute('INSERT INTO ev_experiment_accounting(singleton) VALUES(true)')

    def fixture_game(self, db, *, seconds_ago=2, event_id='fixture-restart-game'):
        target = experiment.utc() - timedelta(seconds=seconds_ago)
        declared = target - timedelta(minutes=1)
        event = dict(provider='sportsgameodds', source_event_id=event_id,
                     event_id=hashed(event_id), league='NCAAB', home='home',
                     away='away', starts_at=depth.clock(target + timedelta(minutes=10)), status={})
        experiment.discover(db, [event], at=declared)
        claim, = experiment.due(db, at=declared)
        early = self.write_checkpoint(db, claim, declared)
        self.assertEqual(early['state'], 'captured')
        config = dict(depth_policy=depth.POLICY)
        campaign = hashed(config)
        db.execute('INSERT INTO public.paper_campaign VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                   (campaign, declared, Jsonb(config), len(encoded(config))))
        db.execute("""INSERT INTO public.paper_campaign_day(campaign_id,game_date)
            VALUES (%s,(%s::timestamptz AT TIME ZONE 'America/New_York')::date) ON CONFLICT DO NOTHING""",
            (campaign, event['starts_at']))
        task = db.execute("SELECT * FROM ev_experiment_task WHERE checkpoint='late' AND game_id=%s",
                          (claim['game_id'],)).fetchone()
        return task, event

    def write_checkpoint(self, db, claim, known):
        event = claim['event']
        snapshot = dict(event=dict(home=event['home'], away=event['away'], competition=event['league'],
            scheduled_start=event['starts_at']), times=dict(received_at=depth.clock(known),
            known_at=depth.clock(known)), offers=[], coverage={})
        return experiment.capture(db, claim['game_id'], claim['checkpoint'], snapshot,
            token=claim['token'], requested_at=known, received_at=known, known_at=known,
            defer_comparison=True)

    def start_collector(self, task, mode):
        context = get_context('spawn')
        monitor, sender = context.Pipe()
        process = context.Process(target=run_depth_collector,
            args=(self.name, self.stage_path, task, mode, sender))
        process.start()
        sender.close()
        self.addCleanup(monitor.close)
        self.addCleanup(self.stop_collector, process)
        return process, monitor

    def stop_collector(self, process):
        if process.is_alive():
            process.kill()
        process.join(timeout=5)
        self.assertFalse(process.is_alive(), 'Collector process did not stop')

    async def message(self, process, monitor):
        async with asyncio.timeout(15):
            while not monitor.poll():
                self.assertTrue(process.is_alive(), f'Collector exited {process.exitcode}')
                await asyncio.sleep(0.02)
        return monitor.recv()

    def staged(self):
        if not self.stage_path.exists():
            return []
        with closing(sqlite3.connect(self.stage_path.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            return list(map(dict, db.execute('SELECT * FROM staged')))

    async def wait_until_drained(self, process, monitor):
        async with asyncio.timeout(15):
            while self.staged():
                self.assertTrue(process.is_alive(), f'Collector exited {process.exitcode}')
                self.assertFalse(monitor.poll(), 'Unexpected collector event')
                await asyncio.sleep(0.02)

    def receipt_rows(self, db):
        return db.execute('SELECT id,known_at,cutoff_at,recorded_at,payload FROM ev_experiment_depth').fetchall()

    def dispositions(self):
        with closing(sqlite3.connect(self.stage_path.as_uri() + '?mode=ro', uri=True)) as db:
            return db.execute('SELECT reason,receipt_id FROM disposition ORDER BY sequence').fetchall()

    def stage_decision(self, task):
        stage = DepthStage(self.stage_path)
        stage.initialize()
        known = task['target_at'] - timedelta(seconds=1)
        payload = depth.normalize(task, known_at=known, observations=captured_book(known))
        stage.put(payload, task['deadline_at'], experiment.utc())
        return stage, payload

    async def test_kill_after_capture_and_after_commit_recovers_once_through_pause_and_sgo_lock(self):
        with self.connect() as db, self.connect() as writer:
            task, _ = self.fixture_game(db)
            with writer.transaction():
                experiment._lock(writer)
                capture, capture_events = self.start_collector(task, 'stage')
                self.assertEqual(await self.message(capture, capture_events), ('captured', 1))
                original_stage, = self.staged()
                self.assertEqual(self.receipt_rows(db), [])
                self.stop_collector(capture)
                self.assertEqual(capture.exitcode, -signal.SIGKILL)

                # The restarted collector's clock has crossed T−9 while
                # PostgreSQL still has the protected writer's transaction.
                publisher, publish_events = self.start_collector(task, 'after_commit')
                self.assertEqual(await self.message(publisher, publish_events),
                                 ('publication_deferred', 'experiment_depth_writer_busy'))
                self.assertEqual(self.staged(), [original_stage])
                self.assertEqual(self.receipt_rows(db), [])
                late, = experiment.due(writer, at=experiment.utc(), late_only=True)
                checkpoint = self.write_checkpoint(writer, late, experiment.utc())
                self.assertEqual(checkpoint['state'], 'captured')
                self.assertLessEqual(experiment.stamp(checkpoint['recorded_at']), task['deadline_at'])

            event, receipt_id = await self.message(publisher, publish_events)
            self.assertEqual(event, 'after_commit')
            committed, = self.receipt_rows(db)
            self.assertEqual(receipt_id, committed['id'])
            self.assertEqual(receipt_id, original_stage['receipt_id'])
            self.assertEqual(self.staged(), [original_stage])
            self.stop_collector(publisher)
            self.assertEqual(publisher.exitcode, -signal.SIGKILL)

            paused, paused_events = self.start_collector(task, 'paused')
            self.assertEqual(await self.message(paused, paused_events), ('paused', None))
            self.assertEqual(self.staged(), [original_stage])
            self.assertEqual(self.receipt_rows(db), [committed])
            self.stop_collector(paused)

            resumed, resumed_events = self.start_collector(task, 'recover')
            await self.wait_until_drained(resumed, resumed_events)
            self.assertEqual(self.receipt_rows(db), [committed])
            known = task['target_at'] - timedelta(seconds=1)
            observation = captured_book(known)['fixture-offer']
            self.assertEqual(committed['known_at'], known)
            self.assertEqual(committed['cutoff_at'], task['target_at'])
            self.assertGreaterEqual(committed['recorded_at'], experiment.stamp(checkpoint['recorded_at']))
            body = committed['payload']
            self.assertEqual(hashed(body), receipt_id)
            self.assertEqual(list(body['http_receipts'].values()), observation['receipts'])
            self.assertEqual(list(body['identity_receipts'].values()), observation['identity_receipts'])
            self.assertEqual(body['observations']['fixture-offer']['levels'], observation['levels'])
            self.assertEqual(self.dispositions(), [('published', receipt_id)])

    async def test_storage_deferral_keeps_decision_and_separate_followup(self):
        with self.connect() as db:
            task, _ = self.fixture_game(db, seconds_ago=70)
            stage, decision = self.stage_decision(task)
            later = task['target_at'] + timedelta(seconds=15)
            followup = depth.normalize(task, kind='followup', origin_id=hashed(decision),
                cutoff_at=later, known_at=later, observations=captured_book(later))
            stage.put(followup, task['deadline_at'], experiment.utc())
            before = self.staged()
            deferred, deferred_events = self.start_collector(task, 'storage_deferred')
            self.assertEqual(await self.message(deferred, deferred_events),
                             ('publication_deferred', 'research_retention_capacity'))
            self.assertEqual(self.staged(), before)
            self.assertEqual(self.receipt_rows(db), [])
            self.assertEqual(self.dispositions(), [])
            self.stop_collector(deferred)

            recovered, recovered_events = self.start_collector(task, 'recover')
            await self.wait_until_drained(recovered, recovered_events)
            reference = (task['game_id'], task['schedule_id'], task['target_at'])
            self.assertEqual(depth.read(db, *reference), dict(decision, id=hashed(decision)))
            self.assertEqual(depth.followups(db, [hashed(decision)]),
                             {hashed(decision): dict(followup, id=hashed(followup))})
            self.assertEqual(self.dispositions(), [('published', hashed(decision)), ('published', hashed(followup))])

    async def test_superseded_and_cancelled_schedules_are_disposed(self):
        with self.connect() as db:
            old, event = self.fixture_game(db, seconds_ago=90)
            self.stage_decision(old)
            experiment.discover(db, [dict(event, starts_at=depth.clock(
                experiment.stamp(event['starts_at']) + timedelta(hours=2)))])
            cancelled, event = self.fixture_game(db, seconds_ago=90, event_id='fixture-cancelled-game')
            self.stage_decision(cancelled)
            experiment.discover(db, [dict(event, status={'cancelled': True})])

            recovered, events = self.start_collector(cancelled, 'recover')
            await self.wait_until_drained(recovered, events)
            self.assertEqual(self.receipt_rows(db), [])
            self.assertEqual(self.dispositions(), [('schedule_no_longer_current', None)] * 2)

    async def test_corrupt_and_late_staged_evidence_is_disposed(self):
        with self.connect() as db:
            corrupt, _ = self.fixture_game(db, seconds_ago=90)
            self.stage_decision(corrupt)
            malformed, _ = self.fixture_game(db, seconds_ago=90, event_id='fixture-malformed-deadline')
            self.stage_decision(malformed)
            late, _ = self.fixture_game(db, seconds_ago=90, event_id='fixture-late-evidence')
            _, payload = self.stage_decision(late)
            after_cutoff = depth.clock(late['target_at'] + timedelta(seconds=1))
            known = experiment.stamp(payload['known_at'])
            past_cutoff = captured_book(known)
            past_cutoff['fixture-offer']['receipts'][0]['received_at'] = after_cutoff
            with self.assertRaisesRegex(ValueError, 'experiment_depth_receipt_clock'):
                depth.normalize(late, known_at=known, observations=past_cutoff)

            evidence = next(iter(payload['http_receipts'].values()))
            evidence['received_at'] = after_cutoff
            with closing(sqlite3.connect(self.stage_path)) as spool, spool:
                spool.execute("UPDATE staged SET body=? WHERE game_id=?", (b'corrupt', corrupt['game_id']))
                spool.execute("UPDATE staged SET deadline_at=? WHERE game_id=?",
                              ('bad timestamp', malformed['game_id']))
                # A checksum match alone cannot make a post-cutoff receipt causal.
                spool.execute("UPDATE staged SET body=?,receipt_id=? WHERE game_id=?",
                              (encoded(payload), hashed(payload), late['game_id']))

            recovered, events = self.start_collector(late, 'recover')
            await self.wait_until_drained(recovered, events)
            self.assertEqual(self.receipt_rows(db), [])
            self.assertEqual(self.dispositions(), [
                ('experiment_depth_stage_checksum', None), ('experiment_depth_stage_deadline', None),
                ('experiment_depth_receipt_clock', None)])
