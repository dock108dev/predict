"""Disposable SQL: prospective populations, causal horizons and immutable evidence."""

from copy import deepcopy
from datetime import timedelta
from fractions import Fraction as F
import json
from unittest import skipUnless

import psycopg

from app.research import records
from app.research.calculation import reproduce
from app.storage import current_pregame as board
from app.storage.store import encoded, hashed, stamp
from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import AT, PregameFixture, page


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class ResearchSQL(PregameFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        with self.connect() as db:
            db.execute("TRUNCATE public.research_record CASCADE")
            db.execute("""UPDATE public.research_retention_accounting SET coverage_started_at=NULL,
                prior_first_observed_refusal_at=NULL,prior_evidence_reference=NULL,
                prior_refused_attempts=NULL,prior_affected_cases=NULL""")

    def setup_case(self, db, *, missing=False):
        self.ingest(db, page())
        self.process(db)
        row = db.execute("SELECT p.payload,p.record,p.fee_input,c.payload AS calculation FROM current_pregame_price p JOIN current_pregame_calculation c USING(contract_id) WHERE c.payload IS NOT NULL LIMIT 1").fetchone()
        payload = row["calculation"]
        case = records._case(records._current_population(db, stamp(AT))[0])
        cases = [case]
        if missing:
            cases.append(dict(case, case_key="missing", event_id="missing-event"))
        cohort = records.declare(db, name="portable-general-research", cases=cases,
            horizons=[3600], designation="synthetic_demonstration", at=stamp(AT)-timedelta(minutes=1))
        observed = records.observe(db, cohort["id"], case["case_key"], payload,
            known_at=stamp(AT), record=row["record"], fee_input=row["fee_input"])
        return cohort, case, observed, row

    async def test_current_inputs_to_reproducible_capture_and_population_accounting(self):
        with self.connect() as db:
            cohort, case, observation, row = self.setup_case(db, missing=True)
            self.assertEqual(row["calculation"]["reference"]["selection_policy"], "lowest-no-vig-two-trusted-books-2")
            self.assertEqual(row["calculation"]["coherent_probability"]["book"], "fanduel")
            self.assertIn("same-book-betonline-first-1", row["calculation"]["alternative_probabilities"])
            slots = records.capture_due(db, at=stamp(AT)+timedelta(seconds=1), cohort_id=cohort["id"])
            self.assertEqual({r["status"] for r in slots}, {"captured", "missing"})
            self.assertEqual(records.capture_due(db, at=stamp(AT)+timedelta(seconds=2), cohort_id=cohort["id"]), [])
            captured = next(r for r in slots if r["status"] == "captured")
            self.assertEqual(captured["observation_id"], observation["id"])
            self.assertNotIn("snapshot", captured)
            self.assertEqual(captured["snapshot_id"], observation["snapshot"]["id"])
            value = reproduce(records.capture_snapshot(captured, db=db))
            self.assertEqual(F(value["probability"]), F(1, 2))
            data = dict(source="fixture-final-score", published_at=None,
                observed_at="2026-11-17T23:00:00Z", final=True, result="completed", home_score=100, away_score=90)
            records.annotate(db, cohort["id"], case["case_key"], "sporting", data, at=stamp(data["observed_at"]))
            result = records.evaluate(db, cohort["id"], as_of=stamp(data["observed_at"]))
            self.assertEqual(result["population_records"], 2)
            self.assertEqual(result["distinct_events"], 2)
            self.assertEqual(result["scored_records"], 1)
            self.assertEqual(result["status_counts"], {"scored": 1, "missing": 1})
            self.assertEqual(F(result["mean_brier"]), F(1, 4))
            self.assertEqual(result["designation"], "synthetic_demonstration")
            comparison = result["policy_comparison"]
            self.assertEqual({r["population_records"] for r in comparison}, {2})
            self.assertEqual({r["scored_records"] for r in comparison}, {1})
            self.assertEqual({F(r["mean_brier"]) for r in comparison}, {F(1, 4)})

    async def test_causal_cutoff_excludes_late_candidates_and_future_input(self):
        with self.connect() as db:
            cohort, case, observation, row = self.setup_case(db)
            late = deepcopy(row["calculation"])
            late["times"]["received_at"] = "2026-11-17T20:01:00Z"
            with self.assertRaisesRegex(ValueError, "research_future_input"):
                records.observe(db, cohort["id"], case["case_key"], late, known_at=stamp(AT))
            changed = records.observe(db, cohort["id"], case["case_key"], late,
                known_at=stamp(AT)+timedelta(minutes=1))
            self.assertNotEqual(changed["id"], observation["id"])
            slots = records.capture_due(db, at=stamp(AT)+timedelta(minutes=2), cohort_id=cohort["id"])
            self.assertEqual(slots[0]["observation_id"], observation["id"])
            self.assertEqual(slots[0]["cutoff"], stamp(AT).isoformat())

    async def test_as_of_distinguishes_future_pending_from_missing_due_slots(self):
        with self.connect() as db:
            _, case, _, row = self.setup_case(db)
            cohort=records.declare(db,name="as-of-horizons",cases=[case],horizons=[3600,1800],
                designation="synthetic_demonstration",at=stamp(AT)-timedelta(minutes=1))
            records.observe(db,cohort["id"],case["case_key"],row["calculation"],known_at=stamp(AT))
            # Even a retained later synthetic capture must not enter an earlier
            # as-of report before its declared horizon is due.
            records.capture_due(db,cohort_id=cohort["id"],at=stamp("2026-11-17T20:31:00Z"))
            early=records.evaluate(db,cohort["id"],as_of=stamp(AT)-timedelta(seconds=1))
            self.assertEqual((early["due_records"],early["future_records"]),(0,2))
            self.assertEqual(early["status_counts"],{"pending":2})
            at=records.evaluate(db,cohort["id"],as_of=stamp(AT),persist=True)
            self.assertEqual((at["due_records"],at["future_records"]),(1,1))
            self.assertEqual(at["status_counts"],{"missing":1,"pending":1})
            pending=next(r for r in at["records"] if not r["due"])
            self.assertEqual(pending["reason"],"capture_horizon_not_due")
            self.assertIsNone(pending["capture_id"])
            self.assertTrue(all(p["population_records"]==2 and p["due_records"]==1 and p["future_records"]==1
                                and p["status_counts"]=={"missing":1,"pending":1} for p in at["policy_comparison"]))
            boundary=records.evaluate(db,cohort["id"],as_of=stamp("2026-11-17T20:30:00Z"))
            self.assertEqual((boundary["due_records"],boundary["future_records"]),(2,0))
            self.assertEqual(boundary["status_counts"],{"missing":2})
            outcome=dict(source="fixture score",published_at=None,observed_at="2026-11-17T23:00:00Z",
                final=True,result="completed",home_score=100,away_score=90)
            records.annotate(db,cohort["id"],case["case_key"],"sporting",outcome,at=stamp(outcome["observed_at"]))
            final=records.evaluate(db,cohort["id"],as_of=stamp("2026-11-17T23:01:00Z"))
            self.assertEqual((final["due_records"],final["future_records"],final["scored_records"]),(2,0,2))
            self.assertEqual(records._get(db,at["id"])["status_counts"],{"missing":1,"pending":1})

    async def test_outcome_corrections_append_and_preserve_old_evaluations(self):
        with self.connect() as db:
            cohort, case, observation, row = self.setup_case(db)
            records.capture_due(db, at=stamp(AT), cohort_id=cohort["id"])
            data = dict(source="fixture-final-score", published_at="2026-11-17T22:00:00Z",
                observed_at="2026-11-17T22:01:00Z", final=True, result="completed", home_score=100, away_score=90)
            first = records.annotate(db, cohort["id"], case["case_key"], "sporting", data, at=stamp(data["observed_at"]))
            before = records.evaluate(db, cohort["id"], as_of=stamp("2026-11-17T22:30:00Z"), persist=True)
            correction = dict(data, home_score=90, away_score=100, observed_at="2026-11-17T23:00:00Z")
            with self.assertRaisesRegex(ValueError, "requires_latest_and_reason"):
                records.annotate(db, cohort["id"], case["case_key"], "sporting", correction, at=stamp(correction["observed_at"]))
            second = records.annotate(db, cohort["id"], case["case_key"], "sporting", correction,
                supersedes_id=first["id"], reason="corrected final score", at=stamp(correction["observed_at"]))
            after = records.evaluate(db, cohort["id"], as_of=stamp("2026-11-17T23:01:00Z"), persist=True)
            self.assertNotEqual(before["id"], after["id"])
            self.assertEqual(before["records"][0]["outcome_id"], first["id"])
            self.assertEqual(after["records"][0]["outcome_id"], second["id"])
            again = records.evaluate(db, cohort["id"], as_of=stamp("2026-11-17T22:30:00Z"))
            self.assertEqual(again["records"][0]["outcome_id"], first["id"])
            with self.assertRaises(psycopg.Error), db.transaction():
                db.execute("DELETE FROM public.research_record WHERE id=%s", (first["id"],))
            self.assertEqual(records._get(db, before["id"])["records"], before["records"])

    async def test_complete_export_reproduces_offline_and_preserves_all_revisions(self):
        from unittest.mock import patch

        with self.connect() as db:
            cohort, case, observation, row = self.setup_case(db, missing=True)
            capture = records.capture_due(db, at=stamp(AT), cohort_id=cohort["id"])
            data = dict(source="fixture-final-score", published_at=None,
                observed_at="2026-11-17T22:01:00Z", final=True, result="completed", home_score=100, away_score=90)
            first = records.annotate(db, cohort["id"], case["case_key"], "sporting", data, at=stamp(data["observed_at"]))
            before = records.evaluate(db, cohort["id"], as_of=stamp("2026-11-17T22:30:00Z"), persist=True)
            correction = dict(data, home_score=90, away_score=100, observed_at="2026-11-17T23:00:00Z")
            second = records.annotate(db, cohort["id"], case["case_key"], "sporting", correction,
                supersedes_id=first["id"], reason="corrected final score", at=stamp(correction["observed_at"]))
            after = records.evaluate(db, cohort["id"], as_of=stamp("2026-11-17T23:01:00Z"), persist=True)
            unrelated = records.declare(db, name="outside-export", cases=[case],
                horizons=[3600], designation="synthetic_demonstration", at=stamp(AT))
            original = list(db.execute("SELECT * FROM public.research_record ORDER BY id"))
            with db.transaction():
                db.execute("SET TRANSACTION READ ONLY")
                with patch.object(records, "evaluate", side_effect=AssertionError("export recomputed evaluation")):
                    bundle = records.export_cohort(db, cohort["id"])
            self.assertEqual(original, list(db.execute("SELECT * FROM public.research_record ORDER BY id")))
            with patch.object(records, "TOTAL_BYTE_CAP", bundle["manifest"]["total_payload_bytes"]):
                near_cap = records.export_cohort(db, cohort["id"])
                self.assertEqual(near_cap["records"], bundle["records"])
                self.assertGreater(len(encoded(near_cap)), records.TOTAL_BYTE_CAP)
                self.assertLessEqual(len(encoded(near_cap))+1, near_cap["manifest"]["canonical_byte_cap"])
                self.assertEqual(near_cap["manifest"]["retained_payload_byte_cap"], records.TOTAL_BYTE_CAP)
            with patch.object(records, "TOTAL_BYTE_CAP", bundle["manifest"]["total_payload_bytes"]-1):
                with self.assertRaisesRegex(ValueError, "research_export_capacity"):
                    records.export_cohort(db, cohort["id"])
        # Close the database before reopening the exact exported JSON. Neither
        # source SQL nor current mutable policies are fetched to get these inputs.
        reopened = json.loads(encoded(bundle))
        self.assertEqual(reopened["provider_requests"], 0)
        self.assertEqual(reopened["schema"], "predict-research-cohort-export-1")
        self.assertLessEqual(len(encoded(reopened))+1, reopened["manifest"]["canonical_byte_cap"])
        exported = {r["id"]: r for r in reopened["records"]}
        self.assertNotIn(unrelated["id"], exported)
        self.assertIn(cohort["id"], exported)
        self.assertIn(observation["id"], exported)
        self.assertEqual(len(exported), len(original)-1)
        self.assertEqual(reopened["manifest"]["record_count"], len(exported))
        self.assertEqual(reopened["manifest"]["total_payload_bytes"], sum(r["payload_bytes"] for r in exported.values()))
        self.assertEqual(reopened["manifest"]["bundle_sha256"], hashed({k: v for k, v in reopened.items() if k != "manifest"}))
        for entry in exported.values():
            self.assertEqual(hashed(entry["payload"]), entry["id"])
            self.assertEqual(len(encoded(entry["payload"])), entry["payload_bytes"])
            self.assertIsNotNone(stamp(entry["recorded_at"]).tzinfo)
        snapshot = exported[observation["id"]]["payload"]["snapshot"]
        self.assertIsNotNone(snapshot["inputs"]["source_record"])
        self.assertIsNotNone(snapshot["inputs"]["fee_input"])
        self.assertEqual(reproduce(snapshot)["status"], "calculated")
        captured = next(r for r in capture if r["status"] == "captured")
        self.assertEqual(reproduce(records.capture_snapshot(exported[captured["id"]]["payload"], exported)), reproduce(snapshot))
        self.assertEqual(exported[second["id"]]["payload"]["supersedes_id"], first["id"])
        self.assertEqual(exported[before["id"]]["payload"]["records"][0]["outcome_id"], first["id"])
        self.assertEqual(exported[after["id"]]["payload"]["records"][0]["outcome_id"], second["id"])
        self.assertEqual(reopened["evaluation"]["latest_saved_id"], after["id"])
        self.assertFalse(reopened["evaluation"]["current_recomputed"])

    async def test_full_capacity_counts_gaps_without_mutating_evidence_and_recovers(self):
        from unittest.mock import patch
        with self.connect() as db:
            data = page()
            data["data"][0]["status"]["startsAt"] = "2026-11-17T23:00:00Z"
            self.ingest(db, data); self.process(db)
            row = db.execute("SELECT p.payload,p.record,p.fee_input,c.payload AS calculation FROM current_pregame_price p JOIN current_pregame_calculation c USING(contract_id) WHERE c.payload IS NOT NULL LIMIT 1").fetchone()
            case = records._case(records._current_population(db, stamp(AT))[0])
            cohort = records.declare(db, name="capacity-gaps", cases=[case, dict(case, case_key="missing", event_id="missing")],
                designation="synthetic_demonstration", horizons=[3600], at=stamp(AT))
            before = list(db.execute("SELECT * FROM research_record ORDER BY id"))
            full = records.status(db)["total_allocation_bytes"]
            with patch.object(records, "TOTAL_BYTE_CAP", full):
                with self.assertRaisesRegex(ValueError, "research_retention_capacity"):
                    records.observe(db, cohort["id"], case["case_key"], row["calculation"], known_at=stamp(AT))
                self.assertEqual(records.capture_due(db, at=stamp("2026-11-17T22:01:00Z"), cohort_id=cohort["id"]), [])
            self.assertEqual(before, list(db.execute("SELECT * FROM research_record ORDER BY id")))
            state = records.status(db)
            self.assertEqual(state["retention_dispositions"]["observation_refusals"], 1)
            self.assertEqual(state["retention_dispositions"]["capture_refusals"], 2)
            evaluated = records.evaluate(db, cohort["id"], as_of=stamp("2026-11-17T22:02:00Z"))
            self.assertEqual(evaluated["status_counts"], {"missing": 2})
            self.assertTrue(all(r["reason"].startswith("capture_retention_refused:") for r in evaluated["records"]))
            note = records.note_prior_retention_gap(db, first_observed_at="2026-11-17T19:00:00Z", evidence_reference="synthetic retained log fixture")
            self.assertIsNone(note["prior_refused_attempts"])
            self.assertIsNone(note["prior_affected_cases"])
            self.assertIsNotNone(note["coverage_started_at"])
            observed = records.observe(db, cohort["id"], case["case_key"], row["calculation"], known_at=stamp(AT)+timedelta(minutes=1), record=row["record"], fee_input=row["fee_input"])
            slots = records.capture_due(db, at=stamp("2026-11-17T22:03:00Z"), cohort_id=cohort["id"])
            self.assertEqual(len(slots), 2)
            self.assertEqual({s["status"] for s in slots}, {"captured", "missing"})
            state = records.status(db)
            self.assertEqual(state["retention_dispositions"]["observation_open_gaps"], 0)
            self.assertEqual(state["retention_dispositions"]["capture_open_gaps"], 0)
            bundle = records.export_cohort(db, cohort["id"])
        index = {r["id"]: r for r in bundle["records"]}
        captured = next(s for s in slots if s["status"] == "captured")
        self.assertEqual(reproduce(records.capture_snapshot(captured, index)), reproduce(observed["snapshot"]))
        self.assertEqual(captured["retention_gaps"]["observation_refusals"], 1)
        self.assertEqual(bundle["research_retention"]["retention_dispositions"]["capture_refusals"], 2)
        self.assertEqual(records.capture_snapshot(dict(snapshot=observed["snapshot"])), observed["snapshot"])

    async def test_automatic_retention_refusal_continues_other_cases_and_counts_retries(self):
        from unittest.mock import patch
        with self.connect() as db:
            data = page()
            data["data"][0]["status"]["startsAt"] = "2026-11-17T23:00:00Z"
            other = deepcopy(data["data"][0]); other["eventID"] = "second-event"
            other["status"]["startsAt"] = "2026-11-17T23:30:00Z"
            data["data"].append(other)
            self.ingest(db, data); self.process(db)
            cases = {records._case(r)["case_key"]: records._case(r) for r in records._current_population(db, stamp(AT))}
            second = cases[sorted(cases)[-1]]
            for event in data["data"]:
                if event["eventID"] in second["source_event_ids"]:
                    for odd in event["odds"].values():
                        for book in ("fanduel", "draftkings"):
                            odd["byBookmaker"][book].update(available=False, lastUpdatedAt="2026-11-17T19:59:30Z")
            self.ingest(db, data); self.process(db)
            db.execute("DELETE FROM current_pregame_price WHERE game_key=%s", (second["event_id"],))
            with patch.object(records, "OBSERVATION_BYTE_CAP", 4096):
                first = records.automatic_turn(db, at=stamp(AT))
                self.assertEqual(first["refused_observations"], 1)
                self.assertEqual(first["new_observations"], 1)
                again = records.automatic_turn(db, at=stamp(AT)+timedelta(seconds=30))
                self.assertEqual(again["new_observations"], 0)
                self.assertEqual(again["unchanged"], 1)
                self.assertEqual(again["retention_dispositions"]["observation_refusals"], 2)
                self.assertEqual(again["retention_dispositions"]["observation_affected_slots"], 1)
            recovered = records.automatic_turn(db, at=stamp(AT)+timedelta(minutes=1))
            self.assertEqual(recovered["new_observations"], 1)
            self.assertEqual(recovered["retention_dispositions"]["observation_refusals"], 2)
            self.assertEqual(recovered["retention_dispositions"]["observation_open_gaps"], 0)
            self.assertLessEqual(recovered["total_allocation_bytes"], records.TOTAL_BYTE_CAP)
            before_reaffirm = list(db.execute("SELECT * FROM research_record ORDER BY id"))
            db.execute("UPDATE research_retention_accounting SET coverage_started_at='2026-11-17T20:02:00Z'")
            records.note_prior_retention_gap(db, first_observed_at="2026-11-17T20:00:30Z", evidence_reference="synthetic prior-cap marker")
            # The supplied wall clock advances past the actual accounting
            # boundary before inputs are persisted, even on the first turn.
            with patch.object(records, "utc", side_effect=[stamp("2026-11-17T20:01:59Z"), stamp("2026-11-17T20:02:01Z")]):
                refreshed = records.automatic_turn(db)
            self.assertEqual(refreshed["new_observations"], 2)
            known = {r["id"] for r in before_reaffirm}
            new = [r for r in db.execute("SELECT * FROM research_record") if r["id"] not in known]
            self.assertEqual(len(new), 2)
            self.assertLess(sum(r["payload_bytes"] for r in new), 4096)
            for item in new:
                self.assertNotIn("snapshot", item["payload"])
                self.assertEqual(item["payload"]["known_at"], stamp("2026-11-17T20:02:01Z").isoformat())
                self.assertEqual(item["payload"]["observation_kind"], "reaffirmed_current_inputs")
                snapshot = records.observation_snapshot(item["payload"], db=db)
                self.assertIn(reproduce(snapshot)["status"], ("calculated", "probability_only", "unavailable"))
            stable = records.automatic_turn(db, at=stamp("2026-11-17T20:02:30Z"))
            self.assertEqual(stable["new_observations"], 0)
            self.assertEqual(stable["unchanged"], 2)

    async def test_migration_backfills_slots_and_preserves_old_inline_snapshots(self):
        from uuid import uuid4
        from psycopg import sql
        from app.storage.store import Store
        with self.connect() as db:
            cohort, case, observation, row = self.setup_case(db)
            original = list(db.execute("SELECT * FROM research_record ORDER BY recorded_at,id"))
            legacy_payload = dict(version=records.VERSION, kind="capture", cohort_id=cohort["id"], case_key=case["case_key"],
                horizon_seconds=3600, cutoff=AT, status="captured", reason=None,
                observation_id=observation["id"], snapshot=observation["snapshot"], historical_freshness="not_established")
            legacy = dict(id=hashed(legacy_payload), kind="capture", cohort_id=cohort["id"], case_key=case["case_key"],
                slot="3600", payload_bytes=len(encoded(legacy_payload)), payload=legacy_payload)
            name = "prediction_arb_research_upgrade_" + uuid4().hex[:10]
            db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            with self.connect(name) as upgraded:
                Store(upgraded).migrate(through="112_research_records.sql")
                for item in original:
                    Store(upgraded).immutable("research_record", item, ["id"])
                Store(upgraded).immutable("research_record", legacy, ["id"])
                before = list(upgraded.execute("SELECT * FROM research_record ORDER BY id"))
                Store(upgraded).migrate()
                self.assertEqual(before, list(upgraded.execute("SELECT * FROM research_record ORDER BY id")))
                self.assertEqual(len(records.retention_dispositions(upgraded, cohort["id"])), 1)
                self.assertIsNone(records.retention_accounting(upgraded)["coverage_started_at"])
                self.assertEqual(reproduce(records.capture_snapshot(legacy_payload, db=upgraded))["status"], "calculated")
                bundle = records.export_cohort(upgraded, cohort["id"])
                self.assertEqual(next(r for r in bundle["records"] if r["id"] == legacy["id"])["payload"], legacy_payload)
        finally:
            with self.connect() as db:
                db.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))

    async def test_prior_uncounted_window_excludes_legacy_capture_until_causal_recovery(self):
        from app.storage.store import Store
        with self.connect() as db:
            _, case, observation, _ = self.setup_case(db)
            # Author an explicit synthetic legacy timeline; inserts retain these
            # fixture persistence clocks rather than rewriting any existing row.
            declaration = dict(version=records.VERSION, kind="cohort", name="prior-window-fixture",
                declared_at="2026-11-17T19:50:00Z", designation="synthetic_demonstration",
                population=[case], horizons=[3600,2700,1800], probability_policy="first-complete-trusted-pair-proportional-1",
                probability_policies=["first-complete-trusted-pair-proportional-1"])
            cid = hashed(declaration)
            def insert(kind, payload, recorded_at, slot=None):
                identity = hashed(payload)
                Store(db).immutable("research_record", dict(id=identity, kind=kind,
                    cohort_id=None if kind=="cohort" else cid, case_key=None if kind=="cohort" else case["case_key"],
                    slot=slot, recorded_at=stamp(recorded_at), payload_bytes=len(encoded(payload)), payload=payload), ["id"])
                return identity
            insert("cohort", declaration, declaration["declared_at"])
            source = dict(observation)
            source.pop("id"); source["cohort_id"] = cid
            oid = insert("observation", source, AT)
            for horizon, cutoff in [(3600,AT),(2700,"2026-11-17T20:15:00Z"),(1800,"2026-11-17T20:30:00Z")]:
                db.execute("INSERT INTO research_retention_disposition(cohort_id,case_key,slot) VALUES(%s,%s,%s)", (cid,case["case_key"],str(horizon)))
                body = dict(version=records.VERSION,kind="capture",cohort_id=cid,case_key=case["case_key"],
                    cutoff=cutoff,horizon_seconds=horizon,status="captured",reason=None,
                    observation_id=oid,snapshot=source["snapshot"])
                insert("capture", body, (stamp(cutoff)+timedelta(seconds=1)).isoformat(), str(horizon))
            result = dict(source="synthetic score",published_at=None,observed_at="2026-11-17T23:00:00Z",
                final=True,result="completed",home_score=100,away_score=90)
            records.annotate(db,cid,case["case_key"],"sporting",result,at=stamp(result["observed_at"]))
            old = records.evaluate(db,cid,as_of=stamp("2026-11-17T23:01:00Z"),persist=True)
            self.assertEqual(old["scored_records"],3)
            captures = list(db.execute("SELECT * FROM research_record WHERE kind='capture' AND cohort_id=%s ORDER BY id", (cid,)))
            db.execute("UPDATE research_retention_accounting SET coverage_started_at='2026-11-17T20:20:00Z'")
            records.note_prior_retention_gap(db,first_observed_at="2026-11-17T20:05:00Z",evidence_reference="synthetic retained refusal log")
            audited = records.evaluate(db,cid,as_of=stamp("2026-11-17T23:01:00Z"))
            self.assertEqual(audited["status_counts"],{"scored":1,"excluded":2})
            self.assertEqual({r["reason"] for r in audited["records"] if r["status"]=="excluded"},{"prior_uncounted_retention_gap"})
            reaffirmation = dict(version=records.VERSION,kind="observation",cohort_id=cid,case_key=case["case_key"],
                known_at="2026-11-17T20:25:00Z",snapshot_observation_id=oid,snapshot_id=source["snapshot"]["id"],
                input_fingerprint=source["input_fingerprint"],reason=None,observation_kind="reaffirmed_current_inputs")
            insert("observation",reaffirmation,reaffirmation["known_at"])
            recovered = records.evaluate(db,cid,as_of=stamp("2026-11-17T23:01:00Z"))
            self.assertEqual(recovered["status_counts"],{"scored":2,"excluded":1})
            self.assertEqual(next(r for r in recovered["records"] if r["horizon_seconds"]==2700)["reason"],"prior_uncounted_retention_gap")
            self.assertEqual(captures,list(db.execute("SELECT * FROM research_record WHERE kind='capture' AND cohort_id=%s ORDER BY id", (cid,))))
            self.assertEqual(records._get(db,old["id"])["scored_records"],3)

    async def test_full_population_evaluation_has_scoped_record_allowance(self):
        from unittest.mock import patch
        with self.connect() as db:
            case=dict(case_key="",event_id="",starts_at="2026-11-17T23:00:00Z",family="moneyline",period="full_game",line=None)
            population=[dict(case,case_key=hashed(["market",i]),event_id="pregame:"+hashed(["event",i])) for i in range(1500)]
            cohort=records.declare(db,name="authored-missing-population",cases=population,horizons=[3600],
                designation="synthetic_demonstration",at=stamp(AT))
            report=records.evaluate(db,cohort["id"],as_of=stamp(AT))
            self.assertGreater(len(encoded(report)),records.RECORD_BYTE_CAP)
            before=list(db.execute("SELECT * FROM research_record ORDER BY id"))
            with patch.object(records,"EVALUATION_RECORD_BYTE_CAP",records.RECORD_BYTE_CAP):
                with self.assertRaisesRegex(ValueError,"research_record_capacity"):
                    records.evaluate(db,cohort["id"],as_of=stamp(AT),persist=True)
            self.assertEqual(before,list(db.execute("SELECT * FROM research_record ORDER BY id")))
            saved=records.evaluate(db,cohort["id"],as_of=stamp(AT),persist=True)
            self.assertEqual(saved["population_records"],1500)
            bundle=records.export_cohort(db,cohort["id"])
            self.assertEqual(next(r for r in bundle["records"] if r["id"]==saved["id"])["payload"]["records"],saved["records"])
            self.assertEqual(records.record_byte_cap("observation"),1024*1024)

    async def test_sporting_import_preserves_unknown_publication_and_unavailable_cases(self):
        with self.connect() as db:
            cohort, case, observation, row = self.setup_case(db)
            records.capture_due(db, at=stamp(AT), cohort_id=cohort["id"])
            source = dict(source="sportsgameodds", event_id=case["source_event_ids"][0],
                starts_at=case["starts_at"], home=case["home"], away=case["away"], league=case["league"],
                home_score=None, away_score="90", final=False, state="unavailable",
                reason="sporting_result_score_missing", published_at=None,
                received_at="2026-11-17T22:01:00Z", knowledge_at="2026-11-17T22:01:01Z", receipt_sha256="1"*64)
            result = records.import_sporting(db, [source])
            self.assertEqual(result["matched"], 1)
            evaluated = records.evaluate(db, cohort["id"], as_of=stamp(source["knowledge_at"]))
            self.assertEqual(evaluated["records"][0]["reason"], "sporting_outcome_not_final")
            source.update(home_score="100", final=True, state="available", reason=None,
                knowledge_at="2026-11-17T22:02:00Z")
            self.assertEqual(records.import_sporting(db, [source])["matched"], 1)
            self.assertEqual(records.import_sporting(db, [source])["unchanged"], 1)
            outcome = db.execute("SELECT payload FROM public.research_record WHERE kind='sporting' AND cohort_id=%s ORDER BY recorded_at DESC LIMIT 1", (cohort["id"],)).fetchone()["payload"]
            self.assertIsNone(outcome["data"]["published_at"])
            self.assertEqual(outcome["data"]["home_score"], 100)
            other = dict(source, event_id="unknown-event")
            self.assertEqual(records.import_sporting(db, [other])["unmatched"], 1)

    async def test_automatic_declaration_includes_negative_and_unavailable_without_ev_filter(self):
        with self.connect() as db:
            data = page()
            data["data"][0]["status"]["startsAt"] = "2026-11-17T23:00:00Z"
            self.ingest(db, data)
            self.process(db)
            # The source price is still available even when probability is not.
            db.execute("UPDATE current_pregame_calculation SET payload=NULL,net_ev=NULL,opportunity_score=NULL,reason='reference_unavailable'")
            result = records.automatic_turn(db, at=stamp(AT))
            self.assertIsNotNone(result["declared_cohort"])
            cohort = records._get(db, result["declared_cohort"])
            self.assertEqual(len(cohort["population"]), 1)
            self.assertEqual(cohort["horizons"], [3600])
            self.assertEqual(result["new_observations"], 1)
            repeated = records.automatic_turn(db, at=stamp(AT)+timedelta(seconds=30))
            self.assertEqual(repeated["new_observations"], 0)
            self.assertEqual(repeated["unchanged"], 1)
            # A fixture saved days after its logical clock cannot impersonate a
            # prospective receipt. Actual database knowledge time is enforced.
            slots = records.capture_due(db, at=stamp("2026-11-17T22:01:00Z"), cohort_id=cohort["id"])
            self.assertEqual(slots[0]["status"], "missing")

    async def test_budget_failure_is_explicit_and_no_evidence_is_evicted(self):
        from unittest.mock import patch
        with self.connect() as db:
            cohort, case, observation, row = self.setup_case(db)
            count = db.execute("SELECT count(*) n FROM public.research_record").fetchone()["n"]
            with patch.object(records, "OBSERVATION_BYTE_CAP", 1):
                with self.assertRaisesRegex(ValueError, "research_retention_capacity"):
                    records.observe(db, cohort["id"], case["case_key"], row["calculation"],
                        known_at=stamp(AT)+timedelta(seconds=1))
            self.assertEqual(count, db.execute("SELECT count(*) n FROM public.research_record").fetchone()["n"])

    async def test_unchanged_affected_turn_preserves_economic_and_probability_rows(self):
        from unittest.mock import patch
        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            before = list(db.execute("SELECT * FROM current_pregame_calculation ORDER BY contract_id"))
            prices = list(db.execute("SELECT * FROM current_pregame_price ORDER BY contract_id"))
            db.execute("SELECT pregame_enqueue('sportsgameodds','event')")
            later = stamp(AT)+timedelta(seconds=30)
            with patch("app.storage.current_rows.utc", return_value=later.isoformat()):
                result = board.process(db, at=later)
            self.assertTrue(result)
            self.assertEqual(before, list(db.execute("SELECT * FROM current_pregame_calculation ORDER BY contract_id")))
            self.assertEqual(prices, list(db.execute("SELECT * FROM current_pregame_price ORDER BY contract_id")))

    async def test_sgo_quarter_stake_remains_received_and_explicitly_unqualified(self):
        from unittest.mock import patch
        from app.comparison import current_pregame as math
        data = page()
        for i, odd in enumerate(data["data"][0]["odds"].values()):
            for book in odd["byBookmaker"].values():
                book["spread"] = "1.25" if i else "-1.25"
        with self.connect() as db:
            source = self.ingest(db, data)
            self.assertEqual({F(r["selection"]["signed_line"]) for r in source}, {F(-5,4), F(5,4)})
            self.process(db)
            self.assertTrue(list(db.execute("SELECT * FROM current_offer")))
            rows = list(db.execute("SELECT reason,payload FROM current_pregame_calculation"))
            self.assertTrue(rows)
            self.assertEqual({r["reason"] for r in rows}, {"posted_line_settlement_unestablished"})
            self.assertTrue(all(r["payload"] is None for r in rows))
            self.assertEqual(board.read(db, dict(browse="1", lines="all"), at=stamp(AT))["rows"], [])
            # Simulate an old conditional writer, then exercise immediate read
            # withholding, retained-source upgrade and unchanged historical math.
            with patch("app.comparison.current_pregame.posted_settlement_reason", return_value=None), patch(
                "app.comparison.current_pregame.qualified_coherent_reference", side_effect=math.coherent_reference
            ):
                db.execute("SELECT pregame_enqueue('sportsgameodds','event')")
                self.process(db)
            prior = db.execute("SELECT payload FROM current_pregame_calculation WHERE payload IS NOT NULL LIMIT 1").fetchone()["payload"]
            self.assertEqual(board.read(db, dict(browse="1", lines="all"), at=stamp(AT))["rows"], [])
            from app.storage.pregame_snapshot import revalue
            with patch("app.storage.current_rows.utc", return_value=AT):
                report = revalue(db, at=stamp(AT))
            self.assertGreater(report["examined"], 0, list(db.execute("SELECT facts FROM current_contract")))
            self.assertEqual(records.conditional_history(db, prior["id"])[0]["original_calculation"], prior)
            with patch("app.storage.current_rows.utc", return_value=AT):
                self.assertEqual(revalue(db, at=stamp(AT))["examined"], 0)

    async def test_polymarket_alias_stays_received_without_borrowing_us_fees(self):
        from unittest.mock import patch
        from app.fees import pricing
        from tests.test_fee_pricing import rule
        from app.comparison import current_pregame as math
        from app.research.calculation import freeze

        data = page()
        for odd in data["data"][0]["odds"].values():
            odd["byBookmaker"]["polymarket"] = deepcopy(odd["byBookmaker"]["prophetx"])
        with self.connect() as db:
            pricing.write(db, "polymarket_us", [rule("polymarket_us")])
            source = self.ingest(db, data)
            routes = dict(board.configured_routes(db), polymarket_us="sportsgameodds")
            with patch.object(board, "configured_routes", return_value=routes):
                self.process(db)
            alias = next(r for r in source if r["quote"]["venue"] == "polymarket_us")
            ctx = board.CalculationContext(db, stamp(AT))
            refused = ctx.fee(alias, stamp(AT))
            self.assertEqual(refused["reason"], "provider_venue_fee_applicability_unestablished")
            self.assertFalse(refused["available"])
            self.assertEqual(refused["evidence"]["provider_bookmaker_id"], "polymarket")
            self.assertEqual(db.execute("SELECT count(*) n FROM current_offer o JOIN current_contract c ON c.id=o.contract_id WHERE c.venue='polymarket_us'").fetchone()["n"], 2)
            self.assertEqual(board.read(db, dict(venue="polymarket_us", browse="1"), at=stamp(AT))["rows"], [])
            disposition = list(db.execute("SELECT payload,net_ev,reason FROM current_pregame_calculation WHERE venue='polymarket_us'"))
            self.assertEqual(len(disposition), 2)
            self.assertTrue(all(r["payload"] is None and r["net_ev"] is None for r in disposition))
            # Preserve the former arithmetic as an explicitly frozen conditional
            # witness; it no longer grants applicable current EV.
            with patch("app.storage.current_pregame.provider_venue_fee_reason", return_value=None):
                hypothetical_fee = ctx.fee(alias, stamp(AT))
            refs = {"event": list(db.execute("SELECT id,revision,facts FROM current_sgo_reference"))}
            screen = math.reference(alias, refs, at=stamp(AT))
            prior = math.calculate(alias, screen, hypothetical_fee, at=stamp(AT), game_key="old-conditional-game")
            prior["coherent_probability"] = math.coherent_reference(alias, refs, at=stamp(AT))
            saved = freeze(prior, record=alias, fee_input=hypothetical_fee)
            self.assertEqual(reproduce(saved)["status"], "calculated")
            self.assertEqual(ctx.fee(alias, stamp(AT))["reason"], refused["reason"])
            # Simulate the prior writer, then preserve its exact conditional
            # witness before replacing the generated row with a refusal.
            with patch.object(board, "configured_routes", return_value=routes):
                with patch("app.storage.current_pregame.provider_venue_fee_reason", return_value=None):
                    db.execute("SELECT pregame_enqueue('sportsgameodds','event')")
                    self.process(db)
                old = db.execute("SELECT payload FROM current_pregame_calculation WHERE contract_id=%s", (prior["id"],)).fetchone()["payload"]
                self.assertIsNotNone(old)
                self.assertEqual(board.read(db, dict(id=prior["id"]), at=stamp(AT))["rows"], [])
                with patch.object(records, "OBSERVATION_BYTE_CAP", 1):
                    db.execute("SELECT pregame_enqueue('sportsgameodds','event')")
                    failure = self.process(db)
                    self.assertTrue(any(r.get("error") == "RuntimeError" for r in failure))
                retained = db.execute("SELECT payload FROM current_pregame_calculation WHERE contract_id=%s", (prior["id"],)).fetchone()["payload"]
                self.assertEqual(retained, old)
                db.execute("SELECT pregame_enqueue('sportsgameodds','event')")
                self.process(db)
                history = records.conditional_history(db, prior["id"])
                self.assertEqual(history[0]["original_calculation"], old)
                self.assertEqual(records._get(db, history[0]["id"])["designation"], "historical_conditional_calculation")
                now = db.execute("SELECT payload,reason FROM current_pregame_calculation WHERE contract_id=%s", (prior["id"],)).fetchone()
                self.assertIsNone(now["payload"])
                self.assertEqual(now["reason"], refused["reason"])

    async def test_v6_fee_schema_reproduces_asserted_fields_without_inventing_nulls(self):
        from app.research.calculation import freeze
        with self.connect() as db:
            cohort, case, observation, row = self.setup_case(db)
            prior = deepcopy(row["calculation"])
            prior["version"] = "predict-current-pregame-6"
            for key in ("purchase_usd", "quantity", "quantity_increment"):
                prior["fee"].pop(key)
            untouched = deepcopy(prior)
            saved = freeze(prior, record=row["record"], fee_input=row["fee_input"])
            self.assertEqual(reproduce(saved)["status"], "calculated")
            self.assertEqual(prior, untouched)
            self.assertEqual(saved["inputs"]["calculation"]["fee"], untouched["fee"])
            prior["fee"]["quantity_increment"] = None
            with self.assertRaisesRegex(ValueError, "fee_cashflow_reproduction_mismatch"):
                reproduce(freeze(prior, record=row["record"], fee_input=row["fee_input"]))
