"""Disposable SQL witnesses for retention-triggered paper grading."""

from datetime import timedelta
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from psycopg.types.json import Jsonb

from app.research import experiment, paper_result_worker, paper_results, records, workspace
from app.storage import mens_d1_coverage, paper_result_queue as queue
from app.storage.store import hashed, stamp
from tests.latest_board_fixture import SOCKET
from tests.test_mens_d1_coverage_sql import DAY, MORNING, game, persist
from tests.test_paper_experiments_sql import ResearchWorkspaceFixture


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class PaperResultQueueSQL(ResearchWorkspaceFixture):
    async def asyncSetUp(self):
        with self.connect() as db:
            db.execute("""TRUNCATE public.research_workspace_run,public.ev_experiment_record,
                public.mens_d1_job,public.research_record,public.paper_result_input CASCADE""")
            db.execute("INSERT INTO public.ev_experiment_accounting(singleton) VALUES (true)")
        self.at = stamp("2026-11-23T17:00:00Z")
        clock = patch.object(experiment, "_dbclock", side_effect=lambda db: self.at)
        clock.start()
        self.addCleanup(clock.stop)

    def advance(self, db, at):
        self.at = at

    def discover(self, db):
        event = self.game("retained-finals-fixture", "2026-11-23T18:00:00Z")
        experiment.discover(db, [event], at=self.at)
        return event

    def finish(self, db, event, *, home_score=90):
        self.advance(db, max(self.at + timedelta(minutes=1), stamp("2026-11-23T20:00:00Z")))
        observed = self.at.isoformat()
        result = dict(event, source="sportsgameodds", final=True, result="completed", home_score=home_score,
                      away_score=82, received_at=observed, knowledge_at=observed,
                      receipt_sha256=hashed([event["source_event_id"], home_score]))
        return experiment.observe_outcomes(db, [result], at=self.at)

    def save(self, db, registration=None):
        return workspace.replay(db, "2026-11-23", workspace.PILOT_VERSION, {},
                                registration=registration)["run"]["id"]

    @staticmethod
    def hash_run(db, run_id):
        original = workspace._run(db, run_id)
        return hashed([original["payload"], original["summary"], original["report_revision"]])

    def test_both_orderings_and_duplicate_deliveries_through_normal_retention(self):
        with self.connect() as db:
            event = self.discover(db)
            first = self.save(db)
            original = self.hash_run(db, first)
            self.assertEqual(queue.read(db, first, status_only=True)["state"], "update_pending")
            pending = queue.process_one(db)
            self.assertEqual(queue.read(db, first)["report"]["games"][0]["result"]["state"], "pending")
            self.assertEqual(self.finish(db, event)["matched"], 1)
            self.assertTrue(queue.read(db, first, status_only=True)["pending"])
            self.assertEqual(self.finish(db, event)["unchanged"], 1)
            second = self.save(db, dict(title="Same final, independent experiment", question="Does grading share inputs?",
                                        claim_ids=["positive-net-returns"]))
            original_second = self.hash_run(db, second)
            self.assertEqual(queue.dispatch(db), 1)
            self.assertEqual(queue.dispatch(db), 0)
            published = {queue.process_one(db), queue.process_one(db)}
            one, two = queue.read(db, first), queue.read(db, second)
            self.assertEqual(published, {one["version"]["id"], two["version"]["id"]})
            self.assertNotEqual(one["version"]["id"], two["version"]["id"])
            self.assertEqual(one["version"]["supersedes"], pending)
            self.assertEqual(one["version"]["evidence_revision"], two["version"]["evidence_revision"])
            self.assertEqual(one["report"]["games"][0]["result"]["state"], "final")
            self.assertEqual(two["report"]["games"][0]["result"], one["report"]["games"][0]["result"])
            self.assertEqual(queue.read(db, first, pending)["report"]["games"][0]["result"]["state"], "pending")
            self.assertEqual(self.hash_run(db, first), original)
            self.assertEqual(self.hash_run(db, second), original_second)
            self.assertEqual(queue.process_one(db), None)

    def test_rollback_retry_and_restart_preserve_last_publication(self):
        with self.connect() as db:
            event = self.discover(db)
            run_id = self.save(db)
            # Rolled-back source writes must not leak work.
            with self.assertRaisesRegex(ValueError, "rollback fixture"):
                with db.transaction():
                    self.finish(db, event)
                    raise ValueError("rollback fixture")
            self.assertEqual(queue.dispatch(db), 0)
            self.finish(db, event)
            self.assertEqual(queue.dispatch(db), 1)
            before = queue.process_one(db)
            self.assertEqual(queue.read(db, run_id)["version"]["id"], before)
            self.finish(db, event, home_score=84)
            self.assertTrue(queue.read(db, run_id, status_only=True)["pending"])
            queue.dispatch(db)
            with patch.object(paper_results, "build", side_effect=ValueError("authored processing failure")):
                self.assertIsNone(queue.process_one(db))
            failed = queue.read(db, run_id)
            self.assertEqual((failed["state"], failed["pending"], failed["version"]["id"]), ("failed", True, before))
            db.execute("UPDATE public.paper_result_job SET due_at=clock_timestamp() WHERE run_id=%s", (run_id,))
            abandoned = queue.claim(db)
            self.assertIsNotNone(abandoned)
        with self.connect() as restarted:
            self.assertIsNone(queue.process_one(restarted))
            restarted.execute("""UPDATE public.paper_result_job SET lease_until=clock_timestamp()-interval '1 second'
                WHERE run_id=%s""", (run_id,))
            after = queue.process_one(restarted)
            fresh = queue.read(restarted, run_id)
            self.assertIsNotNone(after)
            self.assertNotEqual(before, after)
            self.assertEqual((fresh["pending"], fresh["error"], fresh["version"]["supersedes"]), (False, None, before))
            self.assertEqual(queue.read(restarted, run_id, before)["report"]["games"][0]["result"]["state"], "final")

    def test_prior_day_and_official_retention_and_repair_invalidate_result(self):
        with self.connect() as db:
            run_id = workspace.replay(db, str(DAY), workspace.PILOT_VERSION, {})["run"]["id"]
            before = queue.process_one(db)
            source = game("official-fixture", ("Duke", "Dartmouth"))
            persist(db, MORNING, [source], purpose="schedule_fixture")
            self.assertTrue(queue.read(db, run_id, status_only=True)["pending"])
            self.assertEqual(queue.dispatch(db), 1)
            self.assertEqual(queue.process_one(db), before)
            completed = dict(source, status="final")
            persist(db, MORNING + timedelta(minutes=1), [completed], kind="results", purpose="results_corrections")
            self.assertTrue(queue.read(db, run_id, status_only=True)["pending"])
            result_event = db.execute("""SELECT id FROM public.paper_result_input
                WHERE dispatched_at IS NULL AND id LIKE 'daily:%%'""").fetchone()["id"]
            db.execute("DELETE FROM public.paper_result_input WHERE id=%s", (result_event,))
            self.assertFalse(queue.read(db, run_id, status_only=True)["pending"])
            queue.repair(db, paper_results.VERSION)
            self.assertTrue(queue.read(db, run_id, status_only=True)["pending"])
            self.assertEqual(queue.dispatch(db), 1)
            queue.process_one(db)
            revision = db.execute("SELECT id FROM public.mens_d1_revision WHERE kind='schedule'").fetchone()["id"]
            official = dict(kind=mens_d1_coverage.OFFICIAL_CORROBORATION_VERSION,
                            source_game_id=source["source_game_id"], status="final",
                            observed_at=MORNING.isoformat())
            db.execute("""INSERT INTO public.mens_d1_binding(id,schedule_revision_id,facts)
                VALUES ('official-fixture',%s,%s)""", (revision, Jsonb(official)))
            self.assertTrue(queue.read(db, run_id, status_only=True)["pending"])
            self.assertEqual(queue.dispatch(db), 1)

    def test_analysis_only_run_and_protected_capture_have_no_publication(self):
        with self.connect() as db:
            self.discover(db)
            run_id = self.save(db)
            db.execute("""INSERT INTO public.research_workspace_run
                (id,definition_version,game_date,report_revision,observed_at,summary,payload_bytes,payload)
                VALUES ('analysis','ncaab-t10-paper-v1','2026-11-23','analysis',clock_timestamp(),'{}',70,
                        '{"report": {"games": [], "policy": {"execution": "analysis_only"},
                        "portfolios": {"best_venue": {"tickets": []}, "all_venues": {"tickets": []}}}}')""")
            self.assertIsNone(queue.read(db, "analysis"))
            now = queue.utc()
            db.execute("""UPDATE public.ev_experiment_task SET target_at=%s,deadline_at=%s WHERE checkpoint='late'""",
                       (now + timedelta(seconds=30), now + timedelta(seconds=90)))
            self.assertIsNone(queue.process_one(db))
            self.assertIsNone(queue.read(db, run_id)["report"])
            db.execute("UPDATE public.ev_experiment_task SET state='captured' WHERE checkpoint='late'")
            self.assertIsNotNone(queue.process_one(db))
            self.assertIsNone(queue.read(db, "analysis"))

    def test_declared_result_capture_and_worker_ignore_stale_in_flight_generation(self):
        class OnePass(Event):
            def wait(self, timeout=None):
                self.set()
                return True

        with self.connect() as db:
            event = self.discover(db)
            run_id = self.save(db)
            paper_result_worker.run(OnePass(), connector=self.connect)
            pending = queue.read(db, run_id)
            db.execute("""UPDATE public.paper_result_job SET generation=generation+1, due_at=clock_timestamp()
                WHERE run_id=%s""", (run_id,))
            lease = queue.claim(db)
            self.assertIsNotNone(lease)
            self.advance(db, stamp("2026-11-23T20:00:00Z"))
            observed = self.at.isoformat()
            result = dict(event, source="sportsgameodds", final=True, result="completed", home_score=90,
                          away_score=82, received_at=observed, knowledge_at=observed,
                          receipt_sha256=hashed(["declared-legacy-result", event["source_event_id"]]))
            # An authored cohort is not required. The collector retains exact
            # source-event evidence with an unmatched cohort disposition.
            self.assertEqual(records.import_sporting(db, [result])["unmatched"], 1)
            self.assertTrue(queue.read(db, run_id, status_only=True)["pending"])
            self.assertIsNone(queue.publish(db, lease, pending["report"], paper_results.VERSION))
            paper_result_worker.run(OnePass(), connector=self.connect)
            fresh = queue.read(db, run_id)
            self.assertEqual(fresh["version"]["supersedes"], pending["version"]["id"])
            self.assertEqual(fresh["report"]["games"][0]["result"]["state"], "final")
            self.assertFalse(fresh["pending"])

    def test_worker_grades_two_due_reports_before_starting_next_replay(self):
        stop = Event()
        with self.connect() as db:
            self.discover(db)
            first = self.save(db)
            second = self.save(db, dict(title="Paired report scheduling", question="When did the grades publish?",
                                       claim_ids=["positive-net-returns"]))

        def next_replay(db):
            for identity in (first, second):
                self.assertFalse(queue.read(db, identity, status_only=True)["pending"])
            stop.set()

        with patch.object(paper_result_worker.paper_campaigns, "tick", side_effect=next_replay):
            paper_result_worker.run(stop, connector=self.connect)
