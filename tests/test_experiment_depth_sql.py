"""Schedule identity and public-depth storage against the disposable database."""
from datetime import timedelta
from unittest import skipUnless

import psycopg
from psycopg.types.json import Jsonb

from app.collection import experiment_depth as collector
from app.research import experiment
from app.storage import experiment_depth as depth
from app.storage.store import encoded, hashed
from tests.latest_board_fixture import LatestBoardFixture, SOCKET


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
