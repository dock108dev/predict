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
