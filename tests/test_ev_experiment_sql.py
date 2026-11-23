"""Disposable SQL: checkpoint freezing, scheduling, shared budget and exports."""
from copy import deepcopy
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

import psycopg
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.research import experiment as owner, records
from app.storage.store import encoded, hashed
from tests.latest_board_fixture import SOCKET, LatestBoardFixture
from tests.test_ev_movement import offer


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class ExperimentSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        with self.connect() as db:
            db.execute("TRUNCATE public.ev_experiment_record CASCADE")
            db.execute("INSERT INTO public.ev_experiment_accounting(singleton) VALUES(true)")
            db.execute("TRUNCATE public.research_record CASCADE")
            db.execute("CREATE TABLE IF NOT EXISTS public.experiment_fixture_clock(at timestamptz NOT NULL)")
            db.execute("DELETE FROM public.experiment_fixture_clock")
            self.now=db.execute("SELECT clock_timestamp() now").fetchone()["now"]
            db.execute("INSERT INTO public.experiment_fixture_clock VALUES(%s)",(self.now,))
            db.execute("CREATE OR REPLACE FUNCTION public.experiment_fixture_now() RETURNS timestamptz LANGUAGE SQL AS 'SELECT at FROM public.experiment_fixture_clock'")
            # This disposable database supplies a controllable persistence clock;
            # production keeps clock_timestamp() from the unchanged migration.
            db.execute("ALTER TABLE public.ev_experiment_record ALTER COLUMN recorded_at SET DEFAULT public.experiment_fixture_now()")
        source_clock=patch.object(owner,"utc",side_effect=lambda:self.now)
        database_clock=patch.object(owner,"_dbclock",side_effect=lambda db:db.execute("SELECT public.experiment_fixture_now() now").fetchone()["now"])
        source_clock.start();database_clock.start()
        self.addCleanup(source_clock.stop);self.addCleanup(database_clock.stop)

    def advance(self, at):
        self.now=at
        with self.connect() as db:
            db.execute("UPDATE public.experiment_fixture_clock SET at=%s",(at,))

    def event(self, *, starts=None, key="source-game"):
        now = owner.utc()
        return dict(provider="sportsgameodds",source_event_id=key,event_id=hashed([key,"canonical"]),
            title="Away at Home",league="NBA",home="home",away="away",
            starts_at=owner.clock(starts or now+timedelta(hours=1)),status={},
            source_received_at=owner.clock(now-timedelta(minutes=5)))

    def snapshot(self, event, *, positive=True):
        now = owner.utc()
        row = offer("220" if positive else "180")
        row["record"]["event"]["scheduled_start"] = event["starts_at"]
        row["record"]["quote"]["source"]["native_event_id"] = event["source_event_id"]
        return dict(event=dict(home=event["home"],away=event["away"],competition=event["league"],
                    scheduled_start=event["starts_at"]),source_event=dict(event_id=event["source_event_id"]),
            offers=[row],references=[],coverage=dict(incomplete=True,scope="authored_SQL_fixture"),
            times=dict(received_at=owner.clock(now),known_at=owner.clock(now)),
            request_scope=dict(includeAltLines=True,bookmakerID="kalshi,fanduel,draftkings"))

    def setup_game(self, db, *, positive=True):
        event = self.event()
        self.assertEqual(owner.discover(db,[event])["discovered"],1)
        tasks = {task["checkpoint"]:task for task in owner.due(db,limit=2)}
        self.assertEqual(list(tasks),["early"])
        for label in ("early","late"):
            if label=="late":
                self.advance(owner.stamp(event["starts_at"])-timedelta(seconds=600))
                tasks["late"]=owner.due(db)[0]
            value = self.snapshot(event,positive=positive)
            task = tasks[label]
            saved = owner.capture(db,task["game_id"],label,value,token=task["token"],
                requested_at=task["requested_at"],received_at=value["times"]["received_at"],known_at=value["times"]["known_at"])
            self.assertEqual(saved["state"],"captured")
        return tasks["early"]["game_id"],event

    async def test_activation_freezes_transition_preserving_old_research(self):
        with self.connect() as db:
            now=owner.utc()
            old=records.declare(db,name="old-primary",cases=[dict(case_key="old",event_id="old-event",starts_at=owner.clock(now+timedelta(hours=3)),family="moneyline",period="full_game",line=None)],at=now)
            before=db.execute("SELECT * FROM research_record WHERE id=%s",(old["id"],)).fetchone()
            first=owner.activate(db); second=owner.activate(db)
            self.assertEqual(first["id"],second["id"])
            self.assertEqual(first["late"]["window_end_offset_seconds"],60)
            self.assertEqual(first["scheduling_transition"]["from_default_horizon_seconds"],3600)
            self.assertEqual(before,db.execute("SELECT * FROM research_record WHERE id=%s",(old["id"],)).fetchone())

    async def test_reference_scope_transition_preserves_old_policy_and_declared_checkpoint_requests(self):
        from app.collection.experiment_acquisition import LEGACY_BOOKS, request_scope
        from app.comparison.reference_scope import REQUEST_BOOKS
        with self.connect() as db:
            with patch.object(owner, 'REQUEST_BOOKS', LEGACY_BOOKS), \
                    patch.object(owner, 'REFERENCE_SCOPE_VERSION', 'legacy-nine-book-request-scope'):
                old_game, _ = self.setup_game(db)
                old_policy = owner.activate(db)
                pending_event = self.event(key='old-pending')
                owner.discover(db, [pending_event])
            original = {row['id']:row['payload'] for row in db.execute('SELECT id,payload FROM ev_experiment_record')}
            old_revision = owner._revision(db, db.execute('SELECT * FROM ev_experiment_game WHERE id=%s', (old_game,)).fetchone())
            current = owner.activate(db)
            self.assertNotEqual(current['id'], old_policy['id'])
            self.assertEqual(current['activated_at'], old_policy['activated_at'])
            self.assertEqual(current['scheduling_transition'], old_policy['scheduling_transition'])
            self.assertEqual(current['requested_scope']['bookmakers'], list(REQUEST_BOOKS))
            self.assertEqual(owner.activate(db)['id'], current['id'])
            for identity,payload in original.items():
                self.assertEqual(payload, db.execute('SELECT payload FROM ev_experiment_record WHERE id=%s', (identity,)).fetchone()['payload'])
            historical = owner.detail(db, old_game, revision=old_revision)
            self.assertEqual(historical['policy']['requested_scope']['bookmakers'], list(LEGACY_BOOKS))
            exported = owner.export_game(db, old_game, revision=old_revision)
            self.assertEqual(owner.reproduce_export(exported)['provider_requests'], 0)
            owner.discover(db, [self.event(key='new-pending')])
            tasks = owner.due(db, limit=2)
            requests = {task['event']['source_event_id']:request_scope(task)['bookmakerID'].split(',') for task in tasks}
            self.assertEqual(requests['old-pending'], list(LEGACY_BOOKS))
            self.assertEqual(requests['new-pending'], list(REQUEST_BOOKS))

    async def test_fee_mode_transition_appends_policy_without_rewriting_old_evidence(self):
        from app.comparison.fee_mode import state
        with self.connect() as db:
            with patch.object(owner, 'read_fee_mode', return_value=state(True, 1)):
                old_game, _ = self.setup_game(db)
                previous = owner.activate(db)
            original = {row['id']:row['payload'] for row in db.execute('SELECT id,payload FROM ev_experiment_record')}
            old_revision = owner._revision(db, db.execute('SELECT * FROM ev_experiment_game WHERE id=%s', (old_game,)).fetchone())
            with patch.object(owner, 'read_fee_mode', return_value=state(False, 2)):
                current = owner.activate(db)
                self.assertEqual(owner.activate(db)['id'], current['id'])
            self.assertNotEqual(current['id'], previous['id'])
            self.assertFalse(current['fee_mode']['enabled'])
            self.assertEqual(current['activated_at'], previous['activated_at'])
            for identity,payload in original.items():
                self.assertEqual(payload, db.execute('SELECT payload FROM ev_experiment_record WHERE id=%s', (identity,)).fetchone()['payload'])
            detail = owner.detail(db, old_game, revision=old_revision)
            self.assertTrue(detail['policy']['fee_mode']['enabled'])
            bundle = owner.export_game(db, old_game, revision=old_revision)
            with patch.object(owner, 'read_fee_mode', side_effect=AssertionError('offline settings read')):
                self.assertEqual(owner.reproduce_export(bundle)['provider_requests'], 0)

    async def test_both_checkpoints_share_dependencies_and_export_reproduces_offline(self):
        with self.connect() as db:
            game_id,event=self.setup_game(db)
            catalog=owner.catalog(db)
            self.assertEqual(len(catalog["cases"]),1)
            revision=catalog["games"][0]["revision"]
            detail=owner.detail(db,game_id,revision=revision)
            self.assertEqual(detail["cases"][0]["transition"],"positive_to_positive")
            with patch.object(owner,"_closure",side_effect=AssertionError("status_must_not_decode_snapshots")):
                completed=owner.status(db)
            self.assertEqual(completed["complete_checkpoint_games"],1)
            self.assertEqual(completed["storage"]["mean_complete_game_payload_bytes"],detail["game"]["unique_payload_bytes"])
            self.assertEqual(detail["early"]["discovery_kind"],"policy_activation_existing_game")
            self.assertEqual(detail["early"]["snapshot"]["event"]["scheduled_start"],event["starts_at"])
            early_ids=set(owner._closure(db,[detail["early"]["id"]]))
            late_ids=set(owner._closure(db,[detail["late"]["id"]]))
            self.assertTrue(early_ids & late_ids)
            before=list(db.execute("SELECT id,payload FROM ev_experiment_record ORDER BY id"))
            bundle=owner.export_game(db,game_id,revision=revision)
            self.assertEqual(before,list(db.execute("SELECT id,payload FROM ev_experiment_record ORDER BY id")))
            self.assertEqual(db.execute("SELECT late_reserved_bytes FROM ev_experiment_game WHERE id=%s",(game_id,)).fetchone()["late_reserved_bytes"],0)
            with self.assertRaises(psycopg.Error),db.transaction():
                db.execute("DELETE FROM ev_experiment_record WHERE id=%s",(detail["early"]["id"],))
        proof=owner.reproduce_export(deepcopy(bundle))
        self.assertEqual(proof["counts"]["retained_cases"],1)
        self.assertEqual(proof["provider_requests"],0)
        changed=deepcopy(bundle);changed["records"][0]["payload"]["kind"]="changed"
        with self.assertRaisesRegex(ValueError,"export_integrity"):
            owner.reproduce_export(changed)

    async def test_negative_context_does_not_create_case_or_default_attention(self):
        with self.connect() as db:
            game_id,_=self.setup_game(db,positive=False)
            self.assertEqual(owner.catalog(db)["games"],[])
            context=owner.catalog(db,include_context=True)
            self.assertEqual(context["total_games"],1)
            self.assertEqual(context["cases"],[])
            self.assertEqual(len(owner.detail(db,game_id)["context"]),1)

    async def test_early_baseline_does_not_move_and_stale_export_is_explicit(self):
        with self.connect() as db:
            event=self.event();owner.discover(db,[event]);tasks=owner.due(db,limit=2)
            early=next(task for task in tasks if task["checkpoint"]=="early")
            first=owner.capture(db,early["game_id"],"early",self.snapshot(event),token=early["token"])
            revision=owner.catalog(db)["games"][0]["revision"]
            with self.assertRaisesRegex(ValueError,"not_claimed_or_superseded"):
                owner.capture(db,early["game_id"],"early",self.snapshot(event,positive=False),token=early["token"])
            self.advance(owner.stamp(event["starts_at"])-timedelta(seconds=600))
            late=owner.due(db)[0]
            owner.capture(db,late["game_id"],"late",self.snapshot(event,positive=False),token=late["token"])
            self.assertEqual(owner.detail(db,early["game_id"])["early"]["id"],first["id"])
            with self.assertRaisesRegex(ValueError,"revision_changed"):
                owner.export_game(db,early["game_id"],revision=revision)

    async def test_retention_failure_counts_refusal_without_refetch_or_partial_evidence(self):
        with self.connect() as db:
            event=self.event();owner.discover(db,[event]);tasks=owner.due(db,limit=2)
            early=next(task for task in tasks if task["checkpoint"]=="early")
            before=list(db.execute("SELECT id FROM ev_experiment_record ORDER BY id"))
            usage=records.retention_usage(db)
            with patch.object(records,"TOTAL_BYTE_CAP",usage["total"]+usage["reserved"]):
                result=owner.capture(db,early["game_id"],"early",self.snapshot(event),token=early["token"])
            self.assertEqual(result["state"],"refused")
            self.assertEqual(before,list(db.execute("SELECT id FROM ev_experiment_record ORDER BY id")))
            task=db.execute("SELECT * FROM ev_experiment_task WHERE game_id=%s AND checkpoint='early'",(early["game_id"],)).fetchone()
            self.assertEqual(task["refusals"],1)
            self.assertIsNone(db.execute("SELECT early_id FROM ev_experiment_game WHERE id=%s",(early["game_id"],)).fetchone()["early_id"])
            self.assertFalse(any(row["checkpoint"]=="early" for row in owner.due(db)))

    async def test_late_first_discovery_keeps_one_positive_incomplete_early(self):
        with self.connect() as db:
            event=self.event(starts=self.now+timedelta(minutes=5))
            owner.discover(db,[event])
            tasks=owner.due(db,limit=2)
            self.assertEqual([task["checkpoint"] for task in tasks],["early"])
            task=tasks[0]
            owner.capture(db,task["game_id"],"early",self.snapshot(event),token=task["token"])
            detail=owner.detail(db,task["game_id"])
            self.assertEqual(detail["cases"][0]["transition"],"timing_incomplete")
            self.assertTrue(detail["cases"][0]["retain_case"])
            self.assertTrue(detail["cases"][0]["incomplete"])
            self.assertEqual(detail["late"]["reason"],"late_discovery_no_pre_target_baseline")
            self.assertEqual(detail["game"]["late_reserved_bytes"],0)
            self.assertEqual(owner.due(db),[])

    async def test_delayed_early_response_after_target_does_not_buy_second_checkpoint(self):
        with self.connect() as db:
            event=self.event(starts=self.now+timedelta(seconds=601))
            owner.discover(db,[event]);task=owner.due(db)[0]
            self.advance(self.now+timedelta(seconds=2))
            self.assertEqual(owner.due(db,limit=8),[])
            owner.capture(db,task["game_id"],"early",self.snapshot(event),token=task["token"])
            detail=owner.detail(db,task["game_id"])
            self.assertEqual(detail["late"]["reason"],"early_baseline_after_target")
            self.assertEqual(detail["cases"][0]["transition"],"timing_incomplete")
            self.assertTrue(detail["cases"][0]["retain_case"])
            self.assertEqual(owner.due(db),[])

    async def test_predeclared_early_backlog_is_not_bypassed_by_late_priority(self):
        with self.connect() as db:
            event=self.event();owner.discover(db,[event])
            self.advance(owner.stamp(event["starts_at"])-timedelta(seconds=590))
            tasks=owner.due(db,limit=8)
            self.assertEqual([task["checkpoint"] for task in tasks],["early"])
            task=tasks[0]
            owner.capture(db,task["game_id"],"early",self.snapshot(event),token=task["token"])
            detail=owner.detail(db,task["game_id"])
            self.assertEqual(detail["late"]["status"],"missed")
            self.assertEqual(detail["late"]["reason"],"early_baseline_after_target")
            self.assertEqual(owner.due(db),[])

    async def test_terminal_missing_early_still_allows_positive_incomplete_late(self):
        with self.connect() as db:
            event=self.event();owner.discover(db,[event]);early=owner.due(db)[0]
            owner.fail_checkpoint(db,early["game_id"],"early","source_guard_refused",token=early["token"])
            self.advance(owner.stamp(event["starts_at"])-timedelta(seconds=600))
            late=owner.due(db)[0]
            self.assertEqual(late["checkpoint"],"late")
            owner.capture(db,late["game_id"],"late",self.snapshot(event),token=late["token"])
            row=owner.detail(db,late["game_id"])["cases"][0]
            self.assertIsNone(row["early"])
            self.assertTrue(row["retain_case"])
            self.assertTrue(row["incomplete"])

    async def test_late_first_bootstrap_correction_aliases_original_page_without_backdating(self):
        with self.connect() as db:
            event=self.event();owner.discover(db,[event])
            game=db.execute("SELECT * FROM ev_experiment_game").fetchone()
            target=owner.stamp(event["starts_at"])-timedelta(seconds=600)
            history=[]
            # Recreate the deployed old ordering as immutable v1 records. This
            # bypass is only authored fixture evidence, never scheduler behavior.
            for label,at in (("late",target+timedelta(seconds=51)),("early",target+timedelta(seconds=72))):
                self.advance(at)
                task=db.execute("SELECT * FROM ev_experiment_task WHERE game_id=%s AND checkpoint=%s",(game["id"],label)).fetchone()
                value=dict(status="captured",checkpoint=label,schedule_id=game["schedule_id"],
                    target_at=owner.clock(task["target_at"]),deadline_at=owner.clock(task["deadline_at"]),
                    requested_at=owner.clock(target),received_at=owner.clock(at),known_at=owner.clock(at),
                    observed_at=owner.clock(game["first_observed_at"]),snapshot=self.snapshot(event))
                with db.transaction():
                    owner._lock(db)
                    with patch.object(owner,"pack_checkpoint",owner.pack):
                        identity,size=owner._write(db,"checkpoint",value,game_id=game["id"],checkpoint=label,
                            summary=dict(received_at=value["received_at"],known_at=value["known_at"],
                                         target_at=value["target_at"],deadline_at=value["deadline_at"]))
                    db.execute("UPDATE ev_experiment_game SET "+label+"_id=%s,unique_payload_bytes=unique_payload_bytes+%s WHERE id=%s",(identity,size,game["id"]))
                    db.execute("UPDATE ev_experiment_task SET state='captured',result_id=%s WHERE game_id=%s AND checkpoint=%s",(identity,game["id"],label))
                history.append(identity)
            first_id,advanced_id=history
            self.assertEqual(owner.status(db)["complete_checkpoint_games"],0)
            before=list(db.execute("SELECT * FROM ev_experiment_record WHERE kind='checkpoint' ORDER BY id"))
            self.advance(owner.stamp(event["starts_at"])+timedelta(minutes=1))
            corrected=owner.correct_first_observation(db,game["id"],reason="old_late_priority_bypassed_pending_early",
                evidence_reference="authored fixture original receipt/knowledge/persistence clocks")
            self.assertEqual(corrected["state"],"corrected")
            self.assertEqual(corrected["first_observation_id"],first_id)
            self.assertEqual(before,list(db.execute("SELECT * FROM ev_experiment_record WHERE kind='checkpoint' ORDER BY id")))
            detail=owner.detail(db,game["id"])
            self.assertEqual(detail["early"]["id"],first_id)
            self.assertEqual(detail["early"]["original_checkpoint"],"late")
            self.assertEqual(detail["early"]["received_at"],owner.clock(target+timedelta(seconds=51)))
            self.assertGreater(owner.stamp(detail["early"]["corrected_at"]),owner.stamp(event["starts_at"]))
            self.assertEqual(detail["late"]["status"],"not_comparable_baseline_correction")
            self.assertEqual(detail["later_observation_context"]["id"],advanced_id)
            self.assertTrue(detail["cases"][0]["incomplete"])
            completed=owner.status(db)
            self.assertEqual(completed["complete_checkpoint_games"],0)
            self.assertIsNone(completed["storage"]["mean_complete_game_payload_bytes"])
            self.assertIsNone(completed["storage"]["estimated_remaining_games"])
            bundle=owner.export_game(db,game["id"])
            proof=owner.reproduce_export(bundle)
            self.assertEqual(proof["checkpoint_history_reproduced"],2)
            self.assertEqual(set(proof["checkpoints"]),{"early"})
            self.assertEqual(owner.correct_first_observation(db,game["id"],reason="idempotent retry",evidence_reference="same original facts")["state"],"unchanged")

    async def test_status_excludes_missed_and_rescheduled_pairs_with_both_records_present(self):
        with self.connect() as db:
            game_id,event=self.setup_game(db)
            self.assertEqual(owner.status(db)["complete_checkpoint_games"],1)
            db.execute("UPDATE ev_experiment_task SET state='missed' WHERE game_id=%s AND checkpoint='late'",(game_id,))
            self.assertEqual(owner.status(db)["complete_checkpoint_games"],0)
            self.assertIsNone(owner.status(db)["storage"]["mean_complete_game_payload_bytes"])
            db.execute("UPDATE ev_experiment_task SET state='captured' WHERE game_id=%s AND checkpoint='late'",(game_id,))
            self.assertEqual(owner.status(db)["complete_checkpoint_games"],1)
            event["starts_at"]=owner.clock(owner.stamp(event["starts_at"])+timedelta(hours=1))
            owner.discover(db,[event])
            state=owner.status(db)
            game=db.execute("SELECT early_id,late_id FROM ev_experiment_game WHERE id=%s",(game_id,)).fetchone()
            self.assertTrue(game["early_id"] and game["late_id"])
            self.assertEqual(state["complete_checkpoint_games"],0)
            self.assertIsNone(state["storage"]["mean_complete_game_payload_bytes"])

    async def test_reschedules_cannot_reopen_exhausted_game_outcome_budget(self):
        with self.connect() as db:
            now=self.now;event=self.event(starts=now-timedelta(hours=4))
            owner.discover(db,[event],at=now-timedelta(hours=8))
            game_id=db.execute("SELECT id FROM ev_experiment_game").fetchone()["id"]
            db.execute("UPDATE ev_experiment_task SET attempts=5 WHERE game_id=%s AND checkpoint='outcome'",(game_id,))
            self.assertEqual(owner.due(db),[])
            state=db.execute("SELECT state,last_reason FROM ev_experiment_task WHERE game_id=%s AND checkpoint='outcome'",(game_id,)).fetchone()
            self.assertEqual(state["state"],"exhausted")
            self.assertEqual(state["last_reason"],"outcome_request_budget_exhausted")

    async def test_actual_persistence_after_deadline_rolls_back_and_records_miss(self):
        with self.connect() as db:
            event=self.event();owner.discover(db,[event])
            early=owner.due(db)[0]
            owner.capture(db,early["game_id"],"early",self.snapshot(event),token=early["token"])
            self.advance(owner.stamp(event["starts_at"])-timedelta(seconds=600))
            late=next(task for task in owner.due(db,limit=2) if task["checkpoint"]=="late")
            now=owner.utc();value=self.snapshot(event)
            with patch.object(owner,"_dbclock",side_effect=[now+timedelta(seconds=1),now+timedelta(seconds=1),now+timedelta(minutes=2)]):
                result=owner.capture(db,late["game_id"],"late",value,token=late["token"])
            self.assertEqual(result["state"],"missed")
            self.assertIn("persistence_after_deadline",result["reason"])
            self.assertIsNone(db.execute("SELECT late_id FROM ev_experiment_game WHERE id=%s",(late["game_id"],)).fetchone()["late_id"])

    async def test_reserved_late_space_survives_zero_unreserved_headroom(self):
        with self.connect() as db:
            event=self.event();owner.discover(db,[event]);early=owner.due(db)[0]
            owner.capture(db,early["game_id"],"early",self.snapshot(event),token=early["token"])
            game=db.execute("SELECT * FROM ev_experiment_game WHERE id=%s",(early["game_id"],)).fetchone()
            self.assertGreaterEqual(game["late_reserved_bytes"],owner.MIN_CHECKPOINT_RUNWAY)
            usage=records.retention_usage(db)
            self.advance(owner.stamp(event["starts_at"])-timedelta(seconds=600))
            with patch.object(records,"TOTAL_BYTE_CAP",usage["total"]+usage["reserved"]):
                late=owner.due(db)[0]
                self.assertEqual(late["checkpoint"],"late")
                result=owner.capture(db,late["game_id"],"late",self.snapshot(event),token=late["token"])
                self.assertEqual(result["state"],"captured")
                current=records.retention_usage(db)
                self.assertLessEqual(current["total"]+current["reserved"],records.TOTAL_BYTE_CAP)

    async def test_no_reserved_or_free_space_refuses_late_before_paid_claim(self):
        with self.connect() as db:
            event=self.event();owner.discover(db,[event])
            early=owner.due(db)[0]
            owner.fail_checkpoint(db,early["game_id"],"early","source_guard_refused",token=early["token"])
            self.advance(owner.stamp(event["starts_at"])-timedelta(seconds=600))
            usage=records.retention_usage(db)
            with patch.object(records,"TOTAL_BYTE_CAP",usage["total"]+usage["reserved"]):
                self.assertEqual(owner.due(db,limit=2),[])
            task=db.execute("SELECT * FROM ev_experiment_task WHERE checkpoint='late'").fetchone()
            self.assertEqual(task["state"],"refused")
            self.assertEqual(task["attempts"],0)
            self.assertEqual(task["refusals"],1)
            self.assertIn("before_dispatch",task["last_reason"])

    async def test_inflight_reschedule_and_cancellation_preserve_first_early(self):
        with self.connect() as db:
            event=self.event();owner.discover(db,[event]);tasks=owner.due(db,limit=2)
            early=next(task for task in tasks if task["checkpoint"]=="early")
            event["starts_at"]=owner.clock(owner.utc()+timedelta(hours=2))
            self.assertEqual(owner.discover(db,[event])["rescheduled"],1)
            self.assertTrue(owner.task_authorized(db,early["token"]))
            owner.capture(db,early["game_id"],"early",self.snapshot(event),token=early["token"])
            first=owner.detail(db,early["game_id"])["early"]["id"]
            event["status"]["cancelled"]=True
            self.assertEqual(owner.discover(db,[event])["cancelled"],1)
            detail=owner.detail(db,early["game_id"])
            self.assertEqual(detail["early"]["id"],first)
            self.assertEqual(detail["late"]["status"],"cancelled")
            self.assertEqual(owner.reserved_late_objects(db),0)

    async def test_outcome_followup_skips_old_windows_and_semantically_deduplicates_final(self):
        with self.connect() as db:
            now=owner.utc();event=self.event(starts=now-timedelta(hours=4))
            owner.discover(db,[event],at=now-timedelta(hours=8))
            task=next(task for task in owner.due(db,at=now) if task["checkpoint"]=="outcome")
            self.assertEqual(task["outcome_slot_index"],1)
            result=dict(source="sportsgameodds",event_id=event["source_event_id"],league="NBA",home="home",away="away",
                starts_at=event["starts_at"],received_at=owner.clock(now),knowledge_at=owner.clock(now),
                final=False,home_score=None,away_score=None,reason="sporting_result_not_final")
            self.assertEqual(owner.capture_outcome(db,task["game_id"],result,token=task["token"])["state"],"not_final")
            self.assertEqual(owner.due(db,at=now),[])
            result.update(final=True,home_score="100",away_score="90",reason=None)
            self.assertEqual(owner.observe_outcomes(db,[result],at=owner.utc())["matched"],1)
            self.advance(now+timedelta(seconds=2))
            result["received_at"]=owner.clock(self.now);result["knowledge_at"]=result["received_at"]
            self.assertEqual(owner.observe_outcomes(db,[result],at=self.now)["unchanged"],1)
            state=db.execute("SELECT state FROM ev_experiment_task WHERE game_id=%s AND checkpoint='outcome'",(task["game_id"],)).fetchone()["state"]
            self.assertEqual(state,"final")

    async def test_real_http_catalog_detail_export_are_passive_and_revision_bound(self):
        from app.dashboard import research_api
        with self.connect() as db:
            game_id,_=self.setup_game(db)
            before=list(db.execute("SELECT id,payload FROM ev_experiment_record ORDER BY id"))
        app=web.Application()
        with patch.object(research_api,"connect",self.connect):
            research_api.mount(app)
            async with TestClient(TestServer(app)) as client:
                response=await client.get('/api/research/experiment?include_context=1')
                self.assertEqual(response.status,200);catalog=await response.json()
                revision=catalog['games'][0]['revision']
                response=await client.get('/api/research/experiment',params=dict(id=game_id,revision=revision))
                self.assertEqual(response.status,200)
                detail=await response.json();self.assertEqual(detail['revision'],revision)
                response=await client.get('/api/research/experiment',params=dict(id=game_id,revision=revision,export='1'))
                self.assertEqual(response.status,200);bundle=await response.json()
                self.assertEqual(owner.reproduce_export(bundle)['provider_requests'],0)
        with self.connect() as db:
            self.assertEqual(before,list(db.execute("SELECT id,payload FROM ev_experiment_record ORDER BY id")))
