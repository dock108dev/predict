"""Disposable SQL: prospective populations, causal horizons and immutable evidence."""

from copy import deepcopy
from datetime import timedelta
from fractions import Fraction as F
from unittest import skipUnless

import psycopg

from app.research import records
from app.research.calculation import reproduce
from app.storage import current_pregame as board
from app.storage.store import stamp
from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import AT, PregameFixture, page


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class ResearchSQL(PregameFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        with self.connect() as db:
            db.execute("TRUNCATE public.research_record")

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
            value = reproduce(captured["snapshot"])
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
