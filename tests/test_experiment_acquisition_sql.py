"""Real scheduler/store handoff in disposable SQL, with an accounted fake source."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from app.collection import experiment_acquisition as acquisition
from app.collection.background_work import BackgroundWork
from app.collection.sportsgameodds_adapter import parse_page
from app.collection.sportsgameodds_ledger import ObjectLedger
from app.collection.sportsgameodds_transport import PageResponse
from app.research import experiment
from app.storage.sportsgameodds_reference import prepare_page, prepare_frames, upsert_rows, upsert_frames
from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import PregameFixture, page


def source_data(start, *, final=False, scores=False):
    data = deepcopy(page())
    event = data['data'][0]
    event['status'].update(startsAt=start.isoformat(), started=final, live=False,
                           completed=final, finalized=final, ended=final)
    for odd in event['odds'].values():
        base = next(iter(odd['byBookmaker'].values()))
        odd['byBookmaker'] = {book:dict(base, lastUpdatedAt=datetime.now(timezone.utc).isoformat())
                              for book in acquisition.BOOKS}
    if final or scores:
        event['teams']['home']['score'] = '100' if final else '0'
        event['teams']['away']['score'] = '90' if final else '0'
    return data


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class ExperimentAcquisitionSQL(PregameFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        with self.connect() as db:
            db.execute('TRUNCATE ev_experiment_record,ev_experiment_game,ev_experiment_task,ev_experiment_accounting CASCADE')
            db.execute('INSERT INTO ev_experiment_accounting(singleton) VALUES(true)')
            db.execute('TRUNCATE research_record CASCADE')
        temporary = TemporaryDirectory(prefix='predict-experiment-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        memory = patch('app.collection.background_work.BACKGROUND', BackgroundWork(sampler=lambda:64*1024*1024))
        memory.start()
        self.addCleanup(memory.stop)

    def worker(self, data):
        import asyncio
        at = datetime.now(timezone.utc)
        ledger = ObjectLedger(self.directory/'ledger.sqlite3')
        reset = at+timedelta(days=10)
        ledger.create_window('account:window',limit=100000,initial_used=0,reserve=10000,
                             reset_at=reset,requests_per_minute=50)
        requested = []
        async def fetch(params, key):
            requested.append(params)
            return PageResponse(200,json.dumps(data).encode(),datetime.now(timezone.utc).isoformat(),None)
        async def usage():
            return dict(used=ledger.status('account:window')['charged'],limit=100000,reset_at=reset,
                        requests_per_minute=50,at=datetime.now(timezone.utc))
        service = SimpleNamespace(config=dict(enabled=True,aggregate_enabled=True,
            aggregate_provider='sportsgameodds',sports=['NBA']))
        worker=SimpleNamespace(service=service,controls=lambda:dict(stopped=False,source_paused=False),
            now=lambda:datetime.now(timezone.utc),ledger=ledger,window_id='account:window',
            collector=SimpleNamespace(account_usage=usage),transport=SimpleNamespace(fetch=fetch),
            request_lock=asyncio.Lock(),key='fixture-secret',metrics={},
            original_response_root=self.directory/'originals',experiment_late_waiting=False,
            experiment_reserved_objects=0,experiment_reserved_requests=0,page_in_progress=False)
        service.workers={'sportsgameodds':worker}
        return service,worker,requested

    def frame(self, data):
        parsed=parse_page(json.dumps(data).encode(),datetime.now(timezone.utc).isoformat())
        rows=prepare_page(parsed)
        with self.connect() as db,db.transaction():
            upsert_rows(db,rows)
            upsert_frames(db,prepare_frames(parsed,rows))
        return parsed

    async def test_automatic_early_capture_is_new_guarded_receipt_and_never_moves(self):
        data=source_data(datetime.now(timezone.utc)+timedelta(hours=1))
        original=self.frame(data)
        service,worker,requests=self.worker(data)
        scheduler=acquisition.ExperimentAcquisition(service,connector=self.connect)
        with patch.object(acquisition,'connect',self.connect):
            await scheduler.tick()
            self.assertEqual(scheduler.progress['state'],'ready')
            with self.connect() as db:
                game=db.execute('SELECT * FROM ev_experiment_game').fetchone()
                self.assertIsNotNone(game['early_id'])
                frozen=game['early_id']
                detail=experiment.detail(db,game['id'])
            self.assertEqual(detail['early']['status'],'captured')
            self.assertEqual(detail['early']['snapshot']['coverage']['requested']['bookmakers'],sorted(acquisition.BOOKS))
            self.assertTrue(detail['early']['snapshot']['coverage']['incomplete'])
            self.assertGreater(detail['early']['received_at'],original.events[0]['received_at'])
            self.assertLessEqual(detail['early']['requested_at'],detail['early']['received_at'])
            self.assertLessEqual(detail['early']['known_at'],detail['early']['persisted_at'])
            self.assertEqual(game['event']['discovery_kind'],'policy_activation_existing_game')
            await scheduler.tick()
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT early_id FROM ev_experiment_game').fetchone()['early_id'],frozen)
        self.assertEqual(len(requests),1)
        self.assertEqual(worker.ledger.status(worker.window_id)['charged'],1)

    def late_pair(self):
        at = datetime.now(timezone.utc)
        start = at + timedelta(minutes=10) - timedelta(seconds=2)
        first = source_data(start)
        second = deepcopy(first)
        second['data'][0]['eventID'] += '-second'
        bodies = {value['data'][0]['eventID']: value for value in (first, second)}
        events = []
        for body in bodies.values():
            parsed = self.frame(body)
            events.append(acquisition.event_metadata(parsed.events[0], parsed.receipt_sha256))

        known_early = at - timedelta(minutes=10)
        with self.connect() as db:
            experiment.discover(db, events, at=known_early)
            for claim in experiment.due(db, at=known_early, limit=2):
                experiment.fail_checkpoint(db, claim['game_id'], 'early', 'fixture_early_unavailable',
                                           token=claim['token'], at=known_early)
        return at, bodies

    async def test_simultaneous_late_tasks_exclude_ordinary_discovery_and_keep_stage_clocks(self):
        import asyncio

        from app.collection.activity_collector import ActivityBudgetDelayed
        from app.collection.experiment_depth import ExperimentDepth
        from app.collection.original_receipts import read
        from app.collection.sportsgameodds_worker import SportsGameOddsWorker
        from app.research import records
        from app.research.capture_forecast import late_capture_forecast
        from app.storage import acquisition_snapshot

        at, bodies = self.late_pair()
        with self.connect() as db:
            ordinary_request = dict(leagueID='NBA', oddID=','.join(sorted(acquisition.ODD_IDS)), limit=2)
            ordinary_pull = acquisition_snapshot.begin(db, ordinary_request, at=at)
            usage = records.retention_usage(db)
            cap = usage['total'] + usage['reserved'] + 2 * experiment.late_checkpoint_bytes('NBA') + 256 * 1024
            before = late_capture_forecast(db, at=at, headroom_bytes=100_000_000)
            self.assertEqual(len(before['windows']), 1)
            self.assertEqual(before['windows'][0]['planned_event_requests'], 1)
            self.assertEqual(before['windows'][0]['planned_batch_sizes'], [2])

        service, worker, _ = self.worker(next(iter(bodies.values())))
        service.activity_mode_enabled = True
        calls = []
        fetching = asyncio.Event()

        async def fetch(params, _credential):
            members = params['eventIDs'].split(',')
            calls.append(members)
            self.assertEqual(params['limit'], len(members))
            fetching.set()
            await asyncio.sleep(0.03)
            result = dict(success=True, data=[bodies[eid]['data'][0] for eid in members])
            return PageResponse(200, json.dumps(result).encode(), worker.now().isoformat(), None)

        worker.transport.fetch = fetch
        scheduler = acquisition.ExperimentAcquisition(service, connector=self.connect)
        optional = ExperimentDepth(service)

        async def missing_public_book(*_args):
            await fetching.wait()
            raise TimeoutError('fixture public venue timeout')

        async def other_venues(*_args):
            return {}

        with (patch.object(acquisition, 'connect', self.connect),
              patch.object(records, 'TOTAL_BYTE_CAP', cap),
              patch.object(optional, '_market_reads', missing_public_book),
              patch('app.collection.experiment_depth.failure')):
            running = asyncio.create_task(scheduler.tick())
            venue = asyncio.create_task(optional._observe(None, SimpleNamespace(read_native=other_venues),
                {}, {}, worker.now() + timedelta(seconds=1)))
            await asyncio.wait_for(fetching.wait(), timeout=5)
            with self.connect() as db:
                from app.storage import paper_result_queue

                usage = records.retention_usage(db)
                self.assertEqual(usage['market_page_reserved_bytes'], acquisition_snapshot.ORDINARY_PAGE_BYTES)
                self.assertLess(cap - usage['total'] - usage['reserved'], experiment.late_checkpoint_bytes('NBA'))
                with self.assertRaisesRegex(paper_result_queue.PublicationDeferred, 'protected_tminus10_capture_due'):
                    with db.transaction():
                        paper_result_queue._admit(db, 1024)
                self.assertTrue(acquisition_snapshot.renew_ordinary_page(db, ordinary_pull))
            with self.assertRaisesRegex(ActivityBudgetDelayed, 'protected_tminus10_capture_due'):
                await SportsGameOddsWorker._fetch(worker, {'leagueID': 'NCAAB'})
            self.assertEqual(await venue, ({}, {'novig': 'unavailable'}))
            self.assertTrue(await running)
            self.assertFalse(await scheduler.tick())

        self.assertEqual(len(calls), 1)
        self.assertCountEqual(calls[0], bodies)
        self.assertEqual(worker.ledger.status(worker.window_id)['charged'], 2)
        with self.connect() as db:
            pulls = list(db.execute("""SELECT p.request_scope,p.details,r.attempt_id,r.receipt_sha256,r.membership
                FROM market_pull p JOIN market_pull_receipt r USING (pull_id)
                WHERE p.state='complete' AND p.details ? 'timings'"""))
            states = list(db.execute("SELECT state,attempts FROM ev_experiment_task WHERE checkpoint='late'"))
            acquisition_snapshot.finish(db, ordinary_pull, 'cancelled')
            self.assertEqual(records.retention_usage(db)['market_page_reserved_bytes'], 0)
        self.assertEqual(states, [dict(state='captured', attempts=1)] * 2)
        self.assertEqual(len(pulls), 2)
        self.assertEqual(len({row['attempt_id'] for row in pulls}), 1)
        self.assertEqual(len({row['receipt_sha256'] for row in pulls}), 1)
        self.assertEqual(len({row['details']['original_response']['id'] for row in pulls}), 1)
        original, raw = read(pulls[0]['details']['original_response']['id'], root=worker.original_response_root)
        self.assertEqual(original['receipt_sha256'], pulls[0]['receipt_sha256'])
        self.assertCountEqual([event['eventID'] for event in json.loads(raw)['data']], bodies)
        for row in pulls:
            self.assertEqual(row['membership']['event_ids'], [row['request_scope']['eventIDs']])
            self.assertCountEqual(row['membership']['physical_event_ids'], bodies)
            clocks = row['details']['timings']
            ordered = [datetime.fromisoformat(clocks[key]) for key in (
                'claimed_at', 'lane_entered_at', 'manifest_ready_at', 'usage_requested_at',
                'response_received_at', 'original_retention_finished_at', 'parse_finished_at',
                'calculation_finished_at', 'projection_ready_at', 'checkpoint_recorded_at')]
            self.assertEqual(ordered, sorted(ordered))
            self.assertLessEqual(at - timedelta(seconds=2), ordered[0])
            self.assertLessEqual(datetime.fromisoformat(clocks['persistence_checked_at']), at + timedelta(seconds=58))

        with self.connect() as db:
            before = list(db.execute('SELECT late_id,comparison_id FROM ev_experiment_game ORDER BY id'))
        self.assertTrue(all(row['late_id'] and row['comparison_id'] is None for row in before))
        restarted = acquisition.ExperimentAcquisition(service, connector=self.connect)
        self.assertIsNone(restarted._compare_pending(worker))
        # Model the end of the protected period without changing either saved
        # checkpoint clock. A new scheduler drains the durable derived work.
        worker.experiment_late_windows = ()
        self.assertIsNotNone(restarted._compare_pending(worker))
        self.assertIsNotNone(restarted._compare_pending(worker))
        self.assertIsNone(restarted._compare_pending(worker))
        self.assertEqual(len(calls), 1)
        with self.connect() as db:
            after = list(db.execute('SELECT late_id,comparison_id FROM ev_experiment_game ORDER BY id'))
        self.assertEqual([row['late_id'] for row in before], [row['late_id'] for row in after])
        self.assertTrue(all(row['comparison_id'] for row in after))

    async def test_partial_batch_saves_exact_member_without_paid_retry_after_restart(self):
        _, bodies = self.late_pair()
        returned, missing = bodies
        partial = dict(bodies[returned], nextCursor='fixture-opaque-cursor')
        service, worker, requests = self.worker(partial)
        scheduler = acquisition.ExperimentAcquisition(service, connector=self.connect)
        with patch.object(acquisition, 'connect', self.connect):
            self.assertTrue(await scheduler.tick())
            resumed = acquisition.ExperimentAcquisition(service, connector=self.connect)
            self.assertFalse(await resumed.tick())
        self.assertEqual(len(requests), 1)
        self.assertCountEqual(requests[0]['eventIDs'].split(','), bodies)
        self.assertEqual(worker.ledger.status(worker.window_id)['charged'], 1)
        with self.connect() as db:
            rows = {row['source_event_id']:row for row in db.execute("""
                SELECT g.source_event_id,t.state,t.last_reason,t.attempts
                FROM ev_experiment_task t JOIN ev_experiment_game g ON g.id=t.game_id
                WHERE t.checkpoint='late'""")}
        self.assertEqual(rows[returned]['state'], 'captured')
        self.assertEqual(rows[missing]['state'], 'missed')
        self.assertEqual(rows[missing]['last_reason'], 'experiment_event_not_returned')
        self.assertEqual([row['attempts'] for row in rows.values()], [1, 1])

    async def test_batch_retains_uncertain_objects_and_does_not_redispatch_after_restart(self):
        from app.collection.sportsgameodds_transport import TransportFailure

        _, bodies = self.late_pair()
        service, worker, _ = self.worker(next(iter(bodies.values())))
        calls = []

        async def fail_after_dispatch(params, _key):
            calls.append(params['eventIDs'].split(','))
            raise TransportFailure('provider request outcome uncertain')

        worker.transport.fetch = fail_after_dispatch
        scheduler = acquisition.ExperimentAcquisition(service, connector=self.connect)
        with patch.object(acquisition, 'connect', self.connect):
            self.assertTrue(await scheduler.tick())
            resumed = acquisition.ExperimentAcquisition(service, connector=self.connect)
            self.assertFalse(await resumed.tick())
        self.assertEqual(len(calls), 1)
        self.assertCountEqual(calls[0], bodies)
        status = worker.ledger.status(worker.window_id)
        self.assertEqual((status['charged'], status['interrupted']), (0, 2))
        with self.connect() as db:
            states = list(db.execute("SELECT state,attempts,last_reason FROM ev_experiment_task WHERE checkpoint='late'"))
        self.assertEqual(states, [dict(state='missed', attempts=1, last_reason='provider request outcome uncertain')] * 2)

    async def test_paid_batch_storage_refusal_preserves_the_original_attempt(self):
        from app.collection import current_storage_policy
        from app.collection.original_receipts import read

        at, bodies = self.late_pair()
        response = dict(success=True, data=[body['data'][0] for body in bodies.values()])
        service, worker, requests = self.worker(response)
        scheduler = acquisition.ExperimentAcquisition(service, connector=self.connect)
        original_fetch = worker.transport.fetch

        async def fetch_with_later_storage_pressure(params, key):
            page = await original_fetch(params, key)
            with self.connect() as db:
                current_storage_policy.SQL_BYTE_CAP = current_storage_policy.sql_usage(db)
            return page

        worker.transport.fetch = fetch_with_later_storage_pressure
        with (patch.object(acquisition, 'connect', self.connect),
              patch.object(current_storage_policy, 'SQL_BYTE_CAP', current_storage_policy.SQL_BYTE_CAP)):
            self.assertTrue(await scheduler.tick())
            resumed = acquisition.ExperimentAcquisition(service, connector=self.connect)
            self.assertFalse(await resumed.tick())
        request, = requests
        self.assertCountEqual(request['eventIDs'].split(','), bodies)
        ledger = worker.ledger.status(worker.window_id)
        self.assertEqual((ledger['charged'], ledger['held'], ledger['interrupted']), (2, 0, 0))
        with self.connect() as db:
            pulls = list(db.execute("""SELECT details FROM market_pull WHERE state='failed'
                AND requested_at >= %s AND request_scope->>'eventIDs'=ANY(%s)""", (at, list(bodies))))
            tasks = list(db.execute('''SELECT t.state,t.attempts,t.last_reason,g.late_reserved_bytes
                FROM ev_experiment_task t JOIN ev_experiment_game g ON t.game_id=g.id
                WHERE t.checkpoint='late' '''))
        self.assertEqual(tasks, [dict(state='refused', attempts=1, last_reason='research_sql_runway',
                                      late_reserved_bytes=0)] * 2)
        self.assertEqual(len(pulls), 2)
        detail = pulls[0]['details']
        self.assertEqual({row['details']['attempt_id'] for row in pulls}, {detail['attempt_id']})
        self.assertEqual({row['details']['dispatch_at'] for row in pulls}, {detail['dispatch_at']})
        self.assertEqual(detail['batch']['charged_objects'], 2)
        self.assertEqual(detail['batch']['paid_event_requests'], 1)
        with worker.ledger._connect() as db:
            charge = db.execute('''SELECT status,charged,response_sha256 FROM sgo_object_reservation
                JOIN sgo_request_trace ON id=reservation_id WHERE id=?''', (detail['attempt_id'],)).fetchone()
        self.assertEqual(charge, ('resolved', 2, detail['receipt_sha256']))
        witness, raw = read(detail['original_response']['id'], root=worker.original_response_root)
        self.assertEqual(witness['receipt_sha256'], detail['receipt_sha256'])
        self.assertLessEqual(datetime.fromisoformat(detail['dispatch_at']), datetime.fromisoformat(witness['received_at']))
        self.assertEqual(json.loads(raw), response)

    async def test_rescheduled_member_cannot_publish_against_the_previous_deadline(self):
        _, bodies = self.late_pair()
        stable, revised = bodies
        moved = deepcopy(bodies[revised]['data'][0])
        old_start = datetime.fromisoformat(moved['status']['startsAt'])
        new_start = old_start + timedelta(minutes=15)
        moved['status']['startsAt'] = new_start.isoformat()
        data = dict(success=True, data=[bodies[stable]['data'][0], moved])
        service, worker, requests = self.worker(data)
        scheduler = acquisition.ExperimentAcquisition(service, connector=self.connect)
        with patch.object(acquisition, 'connect', self.connect):
            self.assertTrue(await scheduler.tick())
            self.assertFalse(await scheduler.tick())
        self.assertEqual(len(requests), 1)
        self.assertCountEqual(requests[0]['eventIDs'].split(','), bodies)
        with self.connect() as db:
            rows = {row['source_event_id']:row for row in db.execute("""
                SELECT g.source_event_id,g.late_id,t.state,t.target_at
                FROM ev_experiment_task t JOIN ev_experiment_game g ON g.id=t.game_id
                WHERE t.checkpoint='late'""")}
        self.assertEqual(rows[stable]['state'], 'captured')
        self.assertEqual(rows[revised]['state'], 'pending')
        self.assertIsNone(rows[revised]['late_id'])
        self.assertEqual(rows[revised]['target_at'], new_start - timedelta(minutes=10))

    async def test_batch_rechecks_stop_after_account_read_and_spends_nothing(self):
        _, bodies = self.late_pair()
        service, worker, requests = self.worker(next(iter(bodies.values())))
        stopped = False
        original_usage = worker.collector.account_usage

        async def stop_after_usage():
            nonlocal stopped
            usage = await original_usage()
            stopped = True
            return usage

        worker.controls = lambda:dict(stopped=stopped, source_paused=False)
        worker.collector.account_usage = stop_after_usage
        scheduler = acquisition.ExperimentAcquisition(service, connector=self.connect)
        with patch.object(acquisition, 'connect', self.connect):
            self.assertTrue(await scheduler.tick())
            self.assertTrue(stopped)
            await scheduler.tick()
        self.assertEqual(requests, [])
        status = worker.ledger.status(worker.window_id)
        self.assertEqual((status['charged'], status['held'], status['interrupted']), (0, 0, 0))
        self.assertEqual(scheduler.progress['state'], 'source_stopped_or_paused')

    async def test_storage_pressure_refuses_unreserved_member_without_starving_reserved_game(self):
        from app.research import records

        _, bodies = self.late_pair()
        reserved, unreserved = bodies
        with self.connect() as db:
            db.execute('UPDATE ev_experiment_game SET late_reserved_bytes=%s WHERE source_event_id=%s',
                       (experiment.late_checkpoint_bytes('NBA'), reserved))
            usage = records.retention_usage(db)
        cap = usage['total'] + usage['reserved'] + experiment.MIN_CHECKPOINT_RUNWAY - 1

        service, worker, requests = self.worker(bodies[reserved])
        scheduler = acquisition.ExperimentAcquisition(service, connector=self.connect)
        with patch.object(acquisition, 'connect', self.connect), patch.object(records, 'TOTAL_BYTE_CAP', cap):
            self.assertTrue(await scheduler.tick())
        self.assertEqual([scope['eventIDs'] for scope in requests], [reserved])
        self.assertEqual(worker.ledger.status(worker.window_id)['charged'], 1)
        with self.connect() as db:
            states = {row['source_event_id']:row['state'] for row in db.execute("""
                SELECT g.source_event_id,t.state FROM ev_experiment_task t
                JOIN ev_experiment_game g ON t.game_id=g.id WHERE t.checkpoint='late'""")}
        self.assertEqual(states, {reserved:'captured', unreserved:'refused'})

    async def test_ordinary_paid_membership_reservation_expires_and_transfers_at_capacity(self):
        from dataclasses import replace
        from app.research import records
        from app.storage import acquisition_snapshot as snapshots

        now = datetime.now(timezone.utc)
        data = source_data(now + timedelta(hours=1))
        supplied = parse_page(json.dumps(data).encode(), now.isoformat())
        params = dict(leagueID='NBA', oddID=','.join(sorted(acquisition.ODD_IDS)), limit=1)
        with self.connect() as db:
            base = records.retention_usage(db)
            cap = base['total'] + base['reserved'] + snapshots.ORDINARY_PAGE_BYTES + 4096
            with patch.object(records, 'TOTAL_BYTE_CAP', cap):
                pull_id = snapshots.begin(db, params, at=now)
                with self.assertRaisesRegex(ValueError, 'research_retention_capacity'):
                    snapshots.begin(db, params, at=now)
                db.execute('''UPDATE market_pull SET details=jsonb_build_object(
                    'ordinary_page_lease_until',clock_timestamp()-interval '1 second') WHERE pull_id=%s''', (pull_id,))
                self.assertFalse(snapshots.renew_ordinary_page(db, pull_id))
                self.assertEqual(records.retention_usage(db)['market_page_reserved_bytes'], 0)
                pull_id = snapshots.begin(db, params, at=now)
                self.assertTrue(snapshots.renew_ordinary_page(db, pull_id))
                received = replace(supplied, pull_id=pull_id, attempt_id='paid-page', received_at=now.isoformat(),
                                   request_scope=params, next_cursor='fixture-cursor')
                snapshots.accept_ordinary_page(db, received, None)
                self.assertEqual(records.retention_usage(db)['market_page_reserved_bytes'], 0)
                self.assertEqual(snapshots.begin(db, dict(params, cursor='fixture-cursor'), at=now), pull_id)
                self.assertEqual(records.retention_usage(db)['market_page_reserved_bytes'], snapshots.ORDINARY_PAGE_BYTES)
                self.assertEqual(db.execute('SELECT count(*) AS n FROM market_pull_receipt WHERE pull_id=%s',
                                            (pull_id,)).fetchone()['n'], 1)

    async def test_ordinary_ingress_first_shares_physical_capacity_with_native(self):
        await self.race_ordinary_and_native(native_first=False)

    async def test_native_first_protects_ordinary_ingress_and_the_opening_checkpoint(self):
        await self.race_ordinary_and_native(native_first=True)

    async def race_ordinary_and_native(self, *, native_first):
        import asyncio
        from threading import Event
        from unittest.mock import AsyncMock

        from app.collection import current_database, current_storage_policy, mens_d1_jobs
        from app.collection.current_ingress import Ingress
        from app.collection.current_policy import DEFAULT
        from app.collection.native_trading import NativeTrading
        from app.collection.runtime_status import RuntimeState
        from app.collection.sportsgameodds_collector import GuardedPageCollector
        from app.collection.sportsgameodds_worker import SportsGameOddsWorker
        from app.research import records
        from app.storage import acquisition_snapshot, native_trading, sportsgameodds_reference
        from tests.test_native_trading_sql import native_book

        now = experiment.utc
        at = now()
        self.at = at
        target = at + timedelta(seconds=3)
        ordinary = source_data(at + timedelta(hours=2))
        ordinary_id = ordinary['data'][0]['eventID'] = 'ordinary-headroom-page'
        late = source_data(target + timedelta(seconds=experiment.LATE_SECONDS))
        late_id = late['data'][0]['eventID'] = 'protected-headroom-checkpoint'
        late_topup = deepcopy(late)
        topup_id = late_topup['data'][0]['eventID'] = 'protected-headroom-topup'
        checkpoints = {late_id: late, topup_id: late_topup}
        context = page()
        context['data'][0]['eventID'] = 'native-headroom-anchor'
        context['data'][0]['status']['startsAt'] = (at + timedelta(hours=1)).isoformat()
        with self.connect() as db:
            self.ingest(db, context)
        sources = [self.frame(body) for body in checkpoints.values()]
        games = [acquisition.event_metadata(source.events[0], source.receipt_sha256) for source in sources]
        game = games[0]
        with self.connect() as db:
            db.execute('TRUNCATE native_trading_offer,native_trading_snapshot,native_trading_sgo_game')
            _, book = native_book(db, at)
            observed = target - timedelta(minutes=2)
            experiment.discover(db, games, at=observed)
            claims = {row['event']['source_event_id']: row for row in experiment.due(db, at=observed, limit=2)}
            early = claims[late_id]
            missed_early = claims[topup_id]
            experiment.fail_checkpoint(db, missed_early['game_id'], 'early', 'fixture_early_unavailable',
                                       token=missed_early['token'], at=observed)
            snapshot = dict(event=dict(home=game['home'], away=game['away'], competition='NBA',
                scheduled_start=game['starts_at']), times=dict(received_at=observed.isoformat(),
                known_at=observed.isoformat()), offers=[], coverage={})
            # Exercise the real adaptive early-to-late reservation, including a
            # paired market publication estimate near native's static floor.
            paired = 4 * (19 * current_storage_policy.MIB) // 5
            saved = experiment.capture(db, early['game_id'], 'early', snapshot,
                token=early['token'], requested_at=observed, received_at=observed, known_at=observed,
                market_publication_bytes=paired)
            self.assertEqual(saved['state'], 'captured')
            reserved = {row['source_event_id']: row['late_reserved_bytes'] for row in db.execute(
                'SELECT source_event_id,late_reserved_bytes FROM ev_experiment_game')}
            protected = reserved[late_id]
            self.assertEqual(reserved[topup_id], 0)
            deadline, = {row['deadline_at'] for row in db.execute(
                "SELECT deadline_at FROM ev_experiment_task WHERE checkpoint='late'")}

        fetch_started = asyncio.Event()
        finish_fetch = asyncio.Event()
        late_storage = {}
        requests = []

        async def fetch(params, _key):
            requests.append(params)
            if 'leagueID' in params:
                fetch_started.set()
                await finish_fetch.wait()
                body = ordinary
            else:
                event_id = params['eventIDs']
                self.assertIn(event_id, checkpoints)
                with self.connect() as db:
                    late_storage[event_id] = db.execute('''SELECT t.state,g.late_reserved_bytes
                        FROM ev_experiment_task t JOIN ev_experiment_game g ON t.game_id=g.id
                        WHERE t.checkpoint='late' AND g.source_event_id=%s''', (event_id,)).fetchone()
                body = checkpoints[event_id]
            received = now()
            return PageResponse(200, json.dumps(body).encode(), received.isoformat(), None)

        service = SimpleNamespace(database_mode=True, runtime_id='fixture-headroom', dispatch=True,
            globally_stopped=False, paused_sources=set(), states={}, status=lambda: {},
            config=dict(DEFAULT, enabled=True, aggregate_enabled=True,
                        aggregate_provider='sportsgameodds', sports=['NBA']))
        RuntimeState(self.connect).write(service)
        service.sink = current_database.DatabaseIngressSink(SimpleNamespace(provider=service), service.config)
        service.sink.finish = lambda prepared, _states: dict(current_rows_changed=prepared[2])
        service.ingress = Ingress(service)
        worker = SportsGameOddsWorker(service, transport=SimpleNamespace(fetch=fetch),
            now=now, ledger_path=self.directory / 'headroom.sqlite3')
        worker.key = 'fixture-key'
        worker.window_id = 'fixture-window'
        worker.ledger = ObjectLedger(worker.ledger_path)
        reset = at.replace(microsecond=0) + timedelta(days=1)
        worker.ledger.create_window(worker.window_id, limit=1000, initial_used=0, reserve=100,
            reset_at=reset, requests_per_minute=50)
        worker.state = AsyncMock()
        async def usage():
            return dict(used=worker.ledger.status(worker.window_id)['charged'], limit=1000,
                reset_at=reset, requests_per_minute=50, at=now())
        worker.collector = GuardedPageCollector(worker.ledger, worker.window_id, worker.transport,
            controls=worker.controls, account_usage=usage, eligible=worker.request_in_scope_async,
            eligible_after_reservation=worker.dispatch_in_scope, receipt_retainer=worker.retain_original)
        service.workers = {'sportsgameodds': worker}
        job = acquisition.ExperimentAcquisition(service, connector=self.connect)
        owner = SimpleNamespace(service=service, _near_checkpoint=lambda: False)
        # The real DB guard looks ahead 90 seconds. Use its injected native
        # priority clock to place both checks before that edge, then let the
        # normal scheduler and PostgreSQL finish using the actual deadline.
        priority_clock = target - mens_d1_jobs.PRESSURE_FLOOR - timedelta(milliseconds=1)
        trader = NativeTrading(owner, connector=self.connect, now=lambda: priority_clock)
        ingress_entered, native_entered, release = Event(), Event(), Event()
        original_upsert, original_publish = sportsgameodds_reference.upsert_rows, native_trading.publish
        seen = {}

        def block_ingress(db, rows):
            seen['ingress_entered'] = now()
            ingress_entered.set()
            if not native_first:
                self.assertTrue(release.wait(6), 'ordinary fixture release')
            return original_upsert(db, rows)

        def block_native(db, observations, **kwargs):
            seen['native_final_priority_check_passed'] = now()
            native_entered.set()
            if native_first:
                self.assertTrue(release.wait(6), 'native fixture release')
            return original_publish(db, observations, **dict(kwargs, at=now()))

        params = worker.params(league='NBA', starts_after=at.isoformat())
        with (patch('app.storage.store.connect', side_effect=self.connect),
              patch.object(acquisition, 'connect', side_effect=self.connect),
              patch.object(current_database, 'connect', side_effect=self.connect),
              patch.object(sportsgameodds_reference, 'upsert_rows', side_effect=block_ingress),
              patch.object(native_trading, 'publish', side_effect=block_native)):
            in_flight = asyncio.create_task(worker._fetch(params))
            self.addCleanup(in_flight.cancel)
            await asyncio.wait_for(fetch_started.wait(), 5)
            with self.connect() as db:
                physical_before = current_storage_policy.sql_usage(db)
                ordinary_reserved = records.retention_usage(db)['market_page_reserved_bytes']
            self.assertEqual(ordinary_reserved, acquisition_snapshot.ORDINARY_PAGE_BYTES)
            native_minimum = sportsgameodds_reference.HISTORY_RUNWAY + 2 * native_trading.MAX_SNAPSHOT_BYTES
            topup = experiment.late_checkpoint_bytes('NBA')
            late_minimum = experiment.sql_runway_bytes(protected)
            full_group = experiment.sql_runway_bytes(protected + topup)
            # One member fits with room for actual ingress growth. The combined
            # batch does not fit, and ignoring the top-up would admit native.
            cap = physical_before + max(native_minimum, late_minimum) + 2 * current_storage_policy.MIB
            self.assertLess(cap - physical_before, full_group)
            self.assertGreater(cap - physical_before, late_minimum + 2 * native_trading.MAX_SNAPSHOT_BYTES)
            with (patch.object(current_storage_policy, 'SQL_BYTE_CAP', cap),
                  patch.object(current_database, 'SQL_BYTE_CAP', cap)):
                try:
                    if native_first:
                        native_job = asyncio.create_task(asyncio.to_thread(trader.write, {'fixture': book}))
                        self.assertTrue(await asyncio.to_thread(native_entered.wait, 5))
                        finish_fetch.set()
                        await asyncio.sleep(max(0, (target - now()).total_seconds()))
                        late_job = asyncio.create_task(job.tick())
                        self.addCleanup(late_job.cancel)
                        async with asyncio.timeout(2):
                            while True:
                                with self.connect() as db:
                                    waiting = db.execute("""SELECT EXISTS (SELECT 1 FROM pg_locks
                                        WHERE database=(SELECT oid FROM pg_database WHERE datname=current_database())
                                          AND locktype='advisory' AND objid=%s AND NOT granted) AS waiting""",
                                        (records.LOCK,)).fetchone()['waiting']
                                if waiting:
                                    seen['late_claim_awaiting_admission'] = now()
                                    break
                                await asyncio.sleep(0.01)
                        self.assertFalse(in_flight.done())
                        seen['ingress_before_native_release'] = ingress_entered.is_set()
                        seen['native_release'] = now()
                        release.set()
                        native = await asyncio.wait_for(native_job, 6)
                    else:
                        finish_fetch.set()
                        self.assertTrue(await asyncio.to_thread(ingress_entered.wait, 5))
                        native = await asyncio.to_thread(trader.write, {'fixture': book})
                        release.set()
                    await asyncio.wait_for(in_flight, 6)
                    if not native_first:
                        await asyncio.sleep(max(0, (target - now()).total_seconds()))
                        late_job = asyncio.create_task(job.tick())
                    captured = await asyncio.wait_for(late_job, 12)
                finally:
                    release.set()

        with self.connect() as db:
            commit_function = db.execute("SELECT current_setting('track_commit_timestamp') enabled").fetchone()['enabled']
            clock = 'pg_xact_commit_timestamp(r.xmin)' if commit_function == 'on' else 'clock_timestamp()'
            results = {row['source_event_id']: row for row in db.execute(f'''
                SELECT g.source_event_id,t.state,t.result_id,t.last_reason,t.attempts,r.recorded_at,
                {clock} AS commit_at,g.late_reserved_bytes FROM ev_experiment_task t
                JOIN ev_experiment_game g ON t.game_id=g.id
                LEFT JOIN ev_experiment_record r ON t.result_id=r.id WHERE t.checkpoint='late' ''')}
            frame_clock = 'pg_xact_commit_timestamp(xmin)' if commit_function == 'on' else 'NULL'
            frame = db.execute(f'''SELECT {frame_clock} AS commit_at,facts->>'receipt_sha256' AS receipt
                FROM sgo_event_evidence WHERE kind='frame' AND event_id=%s''', (ordinary_id,)).fetchone()
            accepted = db.execute('''SELECT receipt_sha256 FROM market_pull_receipt
                WHERE membership->'event_ids'=%s::jsonb AND received_at >= %s''',
                (json.dumps([ordinary_id]), at)).fetchall()
            current_usage = records.retention_usage(db)
            physical_after = current_storage_policy.sql_usage(db)
        ledger = worker.ledger.status(worker.window_id)
        print(json.dumps(dict(order='native-first' if native_first else 'ordinary-first',
            cap=cap, physical_before=physical_before, physical_after=physical_after,
            protected_before=protected, pending_topup=topup, late_dispatch_minimum=late_minimum,
            full_group_minimum=full_group,
            native_admission_minimum=native_minimum, ordinary_reserved=ordinary_reserved,
            ordinary_reserved_after=current_usage['market_page_reserved_bytes'],
            target=target, deadline=deadline, native=native, late_storage=late_storage, ordinary_frame=frame,
            results=results, time_to_tminus9={key: (deadline-row['commit_at']).total_seconds()
                if row['commit_at'] else None for key, row in results.items()},
            commit_clock='pg_xact_commit_timestamp' if commit_function == 'on' else 'first_visible_sql_read',
            native_priority_clock=priority_clock if native_first else None, seen=seen,
            requests=len(requests), charged=ledger['charged'], held=ledger['held'],
            ingress_transaction_retries=service.sink.metrics.get('transaction_retries', 0)),
            default=str), flush=True)
        self.assertTrue(captured)
        if native_first:
            self.assertEqual(native, dict(state='deferred', reason='native_storage_capacity', published=0))
        else:
            self.assertEqual(native.get('reason'), 'native_storage_admission_busy')
        self.assertEqual(set(results), set(checkpoints))
        self.assertEqual(set(late_storage), set(checkpoints))
        for event_id, result in results.items():
            self.assertEqual(result['state'], 'captured', result)
            self.assertLessEqual(result['commit_at'], deadline)
            self.assertEqual((result['late_reserved_bytes'], result['attempts']), (0, 1))
            self.assertGreater(late_storage[event_id]['late_reserved_bytes'], 0)
            self.assertLessEqual(late_storage[event_id]['late_reserved_bytes'], protected if event_id == late_id else topup)
            self.assertEqual(late_storage[event_id]['state'], 'claimed')
        self.assertLess(physical_after, cap)
        self.assertEqual(current_usage['market_page_reserved_bytes'], 0)
        self.assertIsNotNone(frame)
        self.assertEqual(accepted, [dict(receipt_sha256=frame['receipt'])])
        self.assertCountEqual([request['eventIDs'] for request in requests if 'eventIDs' in request], checkpoints)
        self.assertEqual((len(requests),ledger['charged'],ledger['held'],ledger['interrupted']), (3,3,0,0))
        if native_first:
            self.assertLess(seen['native_final_priority_check_passed'], target)
            self.assertGreaterEqual(seen['late_claim_awaiting_admission'], target)
            self.assertFalse(seen['ingress_before_native_release'])
            self.assertGreater(service.sink.metrics.get('transaction_retries', 0), 0)

    async def test_postgame_followup_runs_without_browser_and_final_stops_future_requests(self):
        now=datetime.now(timezone.utc)
        start=now-timedelta(hours=4)+timedelta(seconds=1)
        data=source_data(start,final=True)
        parsed=self.frame(data)
        event=acquisition.event_metadata(parsed.events[0],parsed.receipt_sha256)
        with self.connect() as db:
            experiment.discover(db,[event],at=start-timedelta(minutes=20))
        # The fixture's fourth-hour window starts one second from now. Moving
        # just the declared target back is unnecessary: wait for its real clock.
        import asyncio
        await asyncio.sleep(1.05)
        service,worker,requests=self.worker(data)
        scheduler=acquisition.ExperimentAcquisition(service,connector=self.connect)
        with patch.object(acquisition,'connect',self.connect):
            await scheduler.tick()
            self.assertEqual(scheduler.progress['last_saved']['state'],'final')
            await scheduler.tick()
        with self.connect() as db:
            task=db.execute("SELECT state,attempts FROM ev_experiment_task WHERE checkpoint='outcome'").fetchone()
            self.assertEqual(task['state'],'final')
            self.assertEqual(task['attempts'],1)
        self.assertEqual(len(requests),1)
        self.assertNotIn('includeAltLines',requests[0])
        self.assertEqual(worker.ledger.status(worker.window_id)['charged'],1)

    async def test_activation_stops_old_nonfinal_cohort_poll_writes(self):
        data=source_data(datetime.now(timezone.utc)+timedelta(hours=1),scores=True)
        parsed=self.frame(data)
        with self.connect() as db:
            experiment.activate(db)
            before=db.execute('SELECT count(*) n FROM research_record').fetchone()['n']
        from app.collection.sgo_game_results import ingest
        with patch('app.storage.store.connect',self.connect), patch('app.research.records.import_sporting',side_effect=AssertionError('legacy polling resumed')):
            result=ingest(parsed,known_at=datetime.now(timezone.utc).isoformat())
        self.assertEqual(result['nonfinal'],1)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM research_record').fetchone()['n'],before)

    async def test_retained_recovery_requires_original_bytes_and_unique_ledger_attempt(self):
        from dataclasses import replace
        from app.research.ev_movement import build_snapshot, reproduce_checkpoint
        from app.storage.market_snapshot_recovery import recover
        from app.storage.acquisition_snapshot import read_snapshot
        from app.comparison import fee_mode
        data=source_data(datetime.now(timezone.utc)+timedelta(hours=1))
        self.frame(data)
        service,worker,requests=self.worker(data)
        scheduler=acquisition.ExperimentAcquisition(service,connector=self.connect)
        scheduler._prepare(worker.now())
        task=scheduler._claim(worker.now())
        with patch.object(acquisition,'connect',self.connect):
            acquired=await acquisition.acquire(worker,task)
        legacy_page=replace(acquired['page'],pull_id=None,attempt_id=None,request_scope=None,received_at=None)
        with self.connect() as db:
            fee_mode.set_enabled(db,False)
            legacy=build_snapshot(db,legacy_page,request_scope=acquired['request_scope'],
                dispatch_at=acquired['dispatch_at'].isoformat(),known_at=acquired['known_at'].isoformat())
            legacy['acquisition']={key:value for key,value in acquired['acquisition'].items()
                                   if key not in ('pull_id','attempt_id')}
            saved=experiment.capture(db,task['game_id'],task['checkpoint'],legacy,token=task['token'],
                requested_at=acquired['dispatch_at'],received_at=acquired['received_at'],
                known_at=worker.now(),scope=acquired['request_scope'])
            self.assertEqual(saved['state'],'captured')
            original=db.execute('SELECT payload FROM ev_experiment_record WHERE id=%s',(saved['id'],)).fetchone()['payload']
            db.execute('TRUNCATE public.market_pull CASCADE')
            result=recover(db,ledger_path=self.directory/'ledger.sqlite3',receipt_root=self.directory/'originals')
            self.assertEqual(result['linked'],1,result)
            pull=db.execute('SELECT * FROM public.market_pull').fetchone()
            self.assertLess(pull['started_order'],0)
            self.assertEqual(pull['state'],'complete')
            frozen=read_snapshot(db,pull['pull_id'])
            self.assertEqual([o.get('calculation_payload',{}).get('raw') if o.get('calculation_payload') else None for o in legacy['offers']],
                             [o.get('calculation_payload',{}).get('raw') if o.get('calculation_payload') else None for o in frozen['offers']])
            self.assertGreater(reproduce_checkpoint(frozen)['numeric_screen_results'],0)
            self.assertEqual(db.execute('SELECT payload FROM ev_experiment_record WHERE id=%s',(saved['id'],)).fetchone()['payload'],original)
            again=recover(db,ledger_path=self.directory/'ledger.sqlite3',receipt_root=self.directory/'originals')
            self.assertEqual(again['linked'],0)
        self.assertEqual(len(requests),1)

    async def test_retained_shared_attempt_recovers_each_missing_member_independently(self):
        from app.collection.original_receipts import checkpoint_page, read
        from app.storage import acquisition_snapshot
        from app.storage.market_snapshot_recovery import recover

        at = datetime.now(timezone.utc)
        begins = at + timedelta(minutes=10, seconds=-2)
        full = source_data(begins)
        first = full['data'][0]
        for suffix in ('-2', '-3'):
            other = deepcopy(first)
            other['eventID'] += suffix
            full['data'].append(other)
        parsed = self.frame(full)
        known_early = at - timedelta(minutes=12)
        with self.connect() as db:
            db.execute('TRUNCATE public.market_pull CASCADE')
            experiment.discover(db, [acquisition.event_metadata(event, parsed.receipt_sha256)
                                     for event in parsed.events], at=known_early)
            for claim in experiment.due(db, at=known_early, limit=3):
                experiment.fail_checkpoint(db, claim['game_id'], 'early', 'fixture_early_unavailable',
                                           token=claim['token'], at=known_early)

        service, worker, requests = self.worker(full)
        scheduler = acquisition.ExperimentAcquisition(service, connector=self.connect)
        with patch.object(acquisition, 'connect', self.connect):
            self.assertTrue(await scheduler.tick())
        self.assertEqual(len(requests), 1)

        with self.connect() as db:
            immutable = db.execute("""SELECT id,payload FROM public.ev_experiment_record
                WHERE kind='checkpoint' AND checkpoint='late' ORDER BY id""").fetchall()
            self.assertEqual(len(immutable), 3)
            captures = [experiment._value(record, experiment._closure(db, [record['id']]))['snapshot']
                        for record in immutable]
            db.execute('TRUNCATE public.market_pull CASCADE')
            for position, capture in enumerate(captures[:2]):
                provenance = capture['acquisition']
                params = capture['request_scope']
                manifest_order = 500 + position
                acquisition_snapshot.start(db, params, at=at, pull_id=provenance['pull_id'],
                                           started_order=manifest_order)
                if position == 0:
                    raw, body = read(provenance['original_response']['id'], root=self.directory/'originals')
                    page = checkpoint_page(body, raw, params, provenance['batch'], params['eventIDs'],
                        pull_id=provenance['pull_id'], attempt_id=provenance['attempt_id'],
                        venues=set(params['bookmakerID'].split(',')))
                    acquisition_snapshot.publish(db, page, capture)

            result = recover(db, ledger_path=self.directory/'ledger.sqlite3', receipt_root=self.directory/'originals')
            self.assertEqual(result, dict(linked=2, skipped=dict(already_linked=1), provider_requests=0))
            for position, capture in enumerate(captures):
                provenance = capture['acquisition']
                event = capture['source_event']['event_id']
                pull = db.execute("""SELECT p.started_order,r.attempt_id,r.membership,r.receipt_sha256
                    FROM public.market_pull p JOIN public.market_pull_receipt r USING(pull_id)
                    WHERE p.pull_id=%s""", (provenance['pull_id'],)).fetchone()
                if position < 2:
                    self.assertEqual(pull['started_order'], 500 + position)
                else:
                    self.assertLess(pull['started_order'], 0)
                self.assertEqual(pull['attempt_id'], provenance['attempt_id'])
                self.assertEqual(pull['receipt_sha256'], provenance['receipt_sha256'])
                self.assertEqual(pull['membership']['event_ids'], [event])
                self.assertCountEqual(pull['membership']['physical_event_ids'],
                                      [source['eventID'] for source in full['data']])
                retained = acquisition_snapshot.read_snapshot(db, provenance['pull_id'])
                self.assertEqual(retained['source_event']['event_id'], event)
            self.assertEqual(db.execute("""SELECT id,payload FROM public.ev_experiment_record
                WHERE kind='checkpoint' AND checkpoint='late' ORDER BY id""").fetchall(), immutable)
            again = recover(db, ledger_path=self.directory/'ledger.sqlite3', receipt_root=self.directory/'originals')
            self.assertEqual(again, dict(linked=0, skipped=dict(already_linked=3), provider_requests=0))
            self.assertEqual(len(requests), 1)

    async def test_restart_keeps_durable_last_receipt_separate_from_runtime_availability(self):
        from psycopg.types.json import Jsonb
        from app.collection.runtime_status import RuntimeState, read_runtime, HEARTBEAT_SECONDS
        from app.storage.acquisition_snapshot import start

        now=datetime.now(timezone.utc)
        received=now-timedelta(seconds=30)
        panel=dict(provider='sportsgameodds',metrics={},last_valid_receipt_at=None,
                   worker_behavior='waiting_for_cycle',status=dict(novig=dict(state='available')))
        state=RuntimeState(self.connect)
        snapshot=dict(runtime_id='before-restart',state='running',config=dict(enabled=True,
            aggregate_provider='sportsgameodds'),states=dict(sportsgameodds=dict(state='available')),
            dispatch=True,status=dict(sources=[panel]),fingerprint='before-restart',
            paused_sources=[],global_stopped=False)
        with self.connect() as db,patch('app.collection.runtime_status.clock',return_value=now):
            db.execute('TRUNCATE public.market_pull CASCADE')
            pull=start(db,dict(eventIDs='receipt-fixture',oddID=','.join(acquisition.ODD_IDS),
                bookmakerID=','.join(acquisition.BOOKS),includeAltLines=True),at=received)
            db.execute('''INSERT INTO public.market_pull_receipt
                (pull_id,attempt_id,receipt_sha256,received_at,membership) VALUES(%s,%s,%s,%s,%s)''',
                (pull,'accepted-before-restart','a'*64,received,
                 Jsonb(dict(event_ids=['receipt-fixture'],next_cursor_present=False))))
            state.write_snapshot(snapshot)
            # A new process publishes an empty diagnostic cache. Its healthy
            # heartbeat says nothing about whether a valid receipt existed.
            state.write_snapshot(dict(snapshot,runtime_id='after-restart',fingerprint='after-restart'))
            owner=read_runtime(db,at=now)
            self.assertTrue(owner['healthy'])
            self.assertEqual(owner['states']['sportsgameodds']['state'],'available')
            source=owner['status']['sources'][0]
            self.assertEqual(datetime.fromisoformat(source['last_valid_receipt_at']),received)
            self.assertEqual(source['last_valid_receipt_basis'],'accepted_acquisition_receipt')
            self.assertEqual(source['metrics'],{})
            expired=read_runtime(db,at=now+timedelta(seconds=HEARTBEAT_SECONDS+1))
            self.assertFalse(expired['healthy'])
            self.assertEqual(expired['states']['sportsgameodds']['state'],'unavailable')
            self.assertEqual(datetime.fromisoformat(expired['status']['sources'][0]['last_valid_receipt_at']),received)
            # This fallback is a passive read; it does not fabricate worker
            # metrics, renew a heartbeat or rewrite the committed source panel.
            stored=db.execute('SELECT status,heartbeat_at FROM data_runtime WHERE singleton').fetchone()
            self.assertEqual(stored['status']['sources'][0],panel)
            self.assertEqual(stored['heartbeat_at'],now)
