"""Disposable SQL for acquisition previews and saved paper research."""
from asyncio import gather
from copy import deepcopy
from unittest import skipUnless
from unittest.mock import patch

import psycopg
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.research.paper_latest import latest
from app.storage import acquisition_snapshot as acquisition
from app.storage.store import encoded, hashed, stamp
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests import test_market_board_sql as fixtures
from tests.test_paper_experiments import linear, priced


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class PaperSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        with self.connect() as db:
            db.execute("TRUNCATE public.market_pull CASCADE")

    def start(self,db):
        return acquisition.start(db,fixtures.SCOPE,at=stamp(fixtures.AT),
            event=dict(title="Away at Home",league="NCAAB",starts_at="2026-11-23T01:00:00Z"))

    async def test_successful_latest_pull_and_newer_failure_never_fall_back(self):
        with self.connect() as db:
            old=self.start(db)
            unavailable=priced(line="-6")
            unavailable["record"]["quote"]["state"]="unavailable"
            original=fixtures.MarketBoardSQL.publish(self,db,old,priced(),priced(venue="polymarket_us"),
                                                     priced(ev="-.01",line="-5"),unavailable)
            first=latest(db,"2026-11-22")
            self.assertEqual(first["pull"]["pull_id"],old)
            self.assertEqual(len(first["rows"]),2)
            self.assertEqual({item["line"]:item["screen_ev"] for item in first["observations"]},
                             {"-3":"0.04","-5":"-0.01","-6":None})
            self.assertEqual([item["line"] for item in first["observations"] if item["meets_pilot_screen"]],
                             ["-3","-3"])
            self.assertEqual(first["observations"][-1]["reason"],"price_withdrawn")
            new=self.start(db)
            acquisition.finish(db,new,"failed",details=dict(reason="authored_failure"))
            second=latest(db,"2026-11-22")
            self.assertEqual(second["pull"]["pull_id"],new)
            self.assertEqual(second["rows"],[])
            self.assertIsNone(second["preview_portfolios"])
            self.assertIn("incomplete",second["incomplete_reason"])
            self.assertIsNone(latest(db,"2026-11-23")["pull"])
            self.assertIsNone(latest(db,"2026-11-23",selected=old)["pull"])
            self.assertEqual([item["pull_id"] for item in second["recent_pulls"]],[new,old])
            pinned=latest(db,"2026-11-22",selected=old)
            self.assertEqual(pinned["observations"],first["observations"])
            exported=latest(db,"2026-11-22",selected=old,evidence=True)
            self.assertEqual(exported["snapshot"],original)
            self.assertEqual(exported["evidence_identity"]["sha256"],hashed(original))
            self.assertEqual(exported["receipts"][0]["receipt_sha256"],"fixture-receipt:"+old)
            self.assertTrue(encoded(exported))
            failed=latest(db,"2026-11-22",selected=new,evidence=True)
            self.assertIsNone(failed["snapshot"])
            self.assertEqual(failed["pull"]["details"]["reason"],"authored_failure")


class ResearchWorkspaceFixture(LatestBoardFixture):
    async def asyncSetUp(self):
        from app.research import experiment

        self.at = stamp("2026-11-23T17:00:00Z")
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS public.workspace_fixture_clock(at timestamptz NOT NULL)")
            db.execute("TRUNCATE public.workspace_fixture_clock")
            db.execute("INSERT INTO public.workspace_fixture_clock VALUES (%s)", (self.at,))
            db.execute("""CREATE OR REPLACE FUNCTION public.workspace_fixture_now() RETURNS timestamptz
                LANGUAGE SQL AS 'SELECT at FROM public.workspace_fixture_clock'""")
            db.execute("""ALTER TABLE public.ev_experiment_record ALTER COLUMN recorded_at
                SET DEFAULT public.workspace_fixture_now()""")
        clock = patch.object(experiment, "_dbclock", side_effect=lambda db: self.at)
        clock.start()
        self.addCleanup(clock.stop)

    def advance(self, db, at):
        self.at = at
        db.execute("UPDATE public.workspace_fixture_clock SET at=%s", (at,))

    def game(self, key, starts, *, cancelled=False):
        return dict(source_event_id=key, event_id=key, league="NCAAB",
                    title=f"Away at {key}", home="home", away="away",
                    starts_at=starts, status={"cancelled": cancelled})

    def capture(self, db, label, game):
        from app.research import experiment

        task = experiment.due(db, at=self.at)[0]
        self.assertEqual(task["checkpoint"], label)
        offers = [priced(), priced(ev=".05", venue="polymarket_us")]
        for offer in offers:
            quote = offer["record"]["quote"]
            quote["source"]["native_event_id"] = game["source_event_id"]
            offer["record"]["event"]["scheduled_start"] = game["starts_at"]
        event = dict(home="home", away="away", competition="NCAAB", scheduled_start=game["starts_at"])
        snapshot = dict(event=event, source_event=dict(event_id=game["source_event_id"]),
                        offers=offers, coverage=dict(incomplete=False))
        capture = experiment.capture(db, task["game_id"], label, snapshot, token=task["token"],
            requested_at=self.at, received_at=self.at, known_at=self.at)
        self.assertEqual(capture["state"], "captured")
        return capture


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class MensD1WorkspaceSQL(ResearchWorkspaceFixture):
    async def test_mens_d1_daily_replay_invalidates_on_source_change(self):
        from app.research import experiment, mens_d1, paper, workspace

        day = "2026-11-23"
        eligible = self.game("eligible", "2026-11-23T18:00:00Z")
        excluded = self.game("non-d1", "2026-11-23T18:00:00Z", cancelled=True)
        population = dict(kind="reconciled_occurrences", revision="schedule-1", membership_version="season-1",
                          expected_games=None, games=[
                              dict(occurrence_id="source:a", provider_event_id="eligible", scope_state="eligible"),
                              dict(occurrence_id="source:b", provider_event_id="non-d1", scope_state="excluded"),
                              dict(occurrence_id="source:c", provider_event_id=None, scope_state="eligible")])
        with self.connect() as db, patch.object(paper.math, "calculate", side_effect=linear):
            experiment.discover(db, [eligible, excluded], at=self.at)
            self.capture(db, "early", eligible)
            self.advance(db, stamp("2026-11-23T17:50:00Z"))
            self.capture(db, "late", eligible)
            original = workspace.replay(db, day, workspace.PILOT_VERSION, {})
            retained = dict(population, revision="provider-snapshot", kind="retained_provider_snapshot",
                            games=deepcopy(population["games"][:2]))
            with patch.object(mens_d1, "retained_provider_population", return_value=retained):
                old_snapshot = workspace.save_mens_d1_provider_snapshot(db, day)
            with patch.object(mens_d1, "daily_population", side_effect=lambda db, day: deepcopy(population)):
                first = workspace.replay(db, day, mens_d1.DAILY, {})
                with patch.object(paper, "report", side_effect=AssertionError("unchanged replay decoded checkpoints")):
                    self.assertEqual(workspace.replay(db, day, mens_d1.DAILY, {}), first)
                population["revision"] = "schedule-2"
                population["games"][2]["scope_state"] = "unresolved"
                population["membership_version"] = "season-2"
                next_run = workspace.replay(db, day, mens_d1.DAILY, {})
            self.assertNotEqual(next_run["run"]["id"], first["run"]["id"])
            self.assertIsNone(first["run"]["coverage"]["expected_games"])
            self.assertEqual(first["run"]["coverage"]["untracked_games"], 1)
            self.assertEqual(first["run"]["coverage"]["excluded_games"], 1)
            self.assertIsNone(next_run["run"]["coverage"]["expected_games"])
            self.assertEqual(next_run["run"]["coverage"]["unverified_membership_games"], 1)
            self.assertEqual(first["report"]["games"][0]["evaluated_offers"], 2)
            self.assertEqual(first["report"]["games"][1]["status"], "no_task")
            self.assertEqual(first["comparison"]["prior_run_id"], old_snapshot["run"]["id"])
            self.assertEqual(first["comparison"]["games"]["delta"], 1)
            self.assertEqual(first["comparison"]["offers"]["delta"], 0)
            self.assertEqual(next_run["comparison"]["prior_run_id"], first["run"]["id"])
            self.assertEqual(next_run["comparison"]["captures"]["no_task"]["delta"], -1)
            identity = first["run"]["id"]
            bundle = workspace.run_detail(db, identity, export=True)
            ticket = bundle["report"]["portfolios"]["all_venues"]["tickets"][0]
            stored = workspace._run(db, identity)["payload"]["witnesses"][ticket["id"]]
            self.assertIn("encoded_calculation", stored)
            inspected = workspace.ticket_detail(db, identity, ticket["id"])
            self.assertEqual(bundle["witnesses"][ticket["id"]]["sized_calculation"], inspected["evidence"]["sized_calculation"])
            exported = workspace.offer_export(db, first["run"]["id"])
            self.assertEqual([len(game["offers"] or []) for game in exported["games"]], [2, 0])
            offers = exported["games"][0]["offers"]
            self.assertEqual([offer["disposition"] for offer in offers], ["screen_passed", "screen_passed"])
            self.assertEqual(sum("best_venue" in offer["selected_tickets"] for offer in offers), 1)
            self.assertEqual(first["report"]["portfolios"]["all_venues"]["unresolved"], 2)
            self.assertEqual(workspace.run_detail(db, original["run"]["id"]), original)
            self.assertEqual(workspace.run_detail(db, first["run"]["id"]), first)


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class CorrectedRecoverySQL(ResearchWorkspaceFixture):
    async def test_scope_correction_leaves_original_capture_and_run_unchanged(self):
        from app.research import experiment, mens_d1, paper, workspace

        day = "2026-11-23"
        eligible = dict(self.game("eligible", "2026-11-23T18:00:00Z"),
                        title="Akron Zips at Wright State Raiders")
        excluded = dict(self.game("non-d1", "2026-11-23T19:00:00Z"),
                        title="Ecclesia Royals at Grambling St Tigers")
        with self.connect() as db, patch.object(paper.math, "calculate", side_effect=linear):
            experiment.discover(db, [eligible], at=self.at)
            self.capture(db, "early", eligible)
            self.advance(db, stamp("2026-11-23T17:50:00Z"))
            self.capture(db, "late", eligible)
            experiment.discover(db, [excluded], at=self.at)
            self.capture(db, "early", excluded)
            self.advance(db, stamp("2026-11-23T18:50:00Z"))
            self.capture(db, "late", excluded)
            original = workspace.replay(db, day, workspace.PILOT_VERSION, {})
            with patch.object(mens_d1, "ORIGINAL_RUN", original["run"]["id"]):
                corrected = workspace.correct_mens_d1_recovery(db)
                with patch.object(mens_d1, "replay_retained", side_effect=AssertionError("unchanged run repriced")):
                    self.assertEqual(workspace.correct_mens_d1_recovery(db), corrected)
                    zone = db.execute("SELECT current_setting('TimeZone') AS zone").fetchone()["zone"]
                    for alternate_zone in ("America/New_York", "UTC"):
                        db.execute("SELECT set_config('TimeZone',%s,false)", (alternate_zone,))
                        self.assertEqual(workspace.correct_mens_d1_recovery(db)["run"]["id"], corrected["run"]["id"])
                    db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
            coverage = corrected["run"]["coverage"]
            self.assertEqual(coverage["captured_games"], 1)
            self.assertIsNone(coverage["expected_games"])
            self.assertEqual(coverage["excluded_games"], 1)
            self.assertEqual(corrected["report"]["portfolios"]["all_venues"]["count"], 2)
            exclusion = next(row for row in corrected["report"]["population"]["games"] if row["scope_state"] == "excluded")
            self.assertEqual(exclusion["teams"][0]["division"], "non_d1")
            self.assertEqual(original["report"]["portfolios"]["all_venues"]["count"], 4)
            self.assertEqual(workspace.run_detail(db, original["run"]["id"]), original)


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class ResearchWorkspaceSQL(ResearchWorkspaceFixture):
    async def test_saved_replay_keeps_evidence_and_definition_history(self):
        from app.dashboard.request_guard import dashboard_guard
        from app.dashboard.research_workspace_api import BASE, mount
        from app.research import experiment, paper, workspace

        game = self.game("source-captured", "2026-11-23T18:00:00Z")
        with self.connect() as db:
            experiment.discover(db, [game], at=self.at)
            self.capture(db, "early", game)
            self.advance(db, stamp("2026-11-23T17:50:00Z"))
            late = self.capture(db, "late", game)
            missing = self.game("source-missed", "2026-11-23T18:00:00Z")
            experiment.discover(db, [missing], at=stamp("2026-11-23T17:50:15Z"))
            other = self.game("source-cancelled", "2026-11-24T01:00:00-05:00", cancelled=True)
            experiment.discover(db, [other], at=self.at)

        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        mount(app)
        client = TestClient(TestServer(app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        same_origin = {"Origin": str(client.make_url("/")).rstrip("/")}
        policy = dict(date="2026-11-23", definition_version=workspace.PILOT_VERSION)

        async def json_response(response):
            self.assertEqual(response.status, 200, await response.text())
            return await response.json()

        async def save(**options):
            return await json_response(await client.post(BASE + "/runs", headers=same_origin, json=dict(policy, **options)))

        with patch("app.dashboard.research_workspace_api.connect", side_effect=self.connect), \
             patch.object(paper.math, "calculate", side_effect=linear):
            before = await json_response(await client.get(BASE))
            self.assertEqual(before["definitions"][0]["policy"], paper.POLICY)
            self.assertEqual([row["date"] for row in before["available_dates"]], ["2026-11-24", "2026-11-23"])
            self.assertIsNone(before["theories"][0]["risk_objectives"][0]["estimate"])
            first, repeat = await gather(save(), save(assumptions={"minimum_ev": "0.040"}))
            self.assertEqual(first, repeat)
            run = first["run"]
            self.assertEqual(run["validity"], "incomplete_tracked_capture")
            self.assertEqual(run["coverage"]["captured_games"], 1)
            self.assertEqual(run["coverage"]["missing_tracked_games"], 1)
            self.assertIsNone(run["coverage"]["expected_games"])
            report = first["report"]
            self.assertEqual(report["portfolios"]["best_venue"]["count"], 1)
            self.assertEqual(report["portfolios"]["all_venues"]["count"], 2)
            self.assertEqual(report["portfolios"]["all_venues"]["unresolved"], 2)
            ticket = report["portfolios"]["all_venues"]["tickets"][0]
            path = f'{BASE}/runs/{run["id"]}'
            witness = await json_response(await client.get(path + "/tickets/" + ticket["id"]))
            self.assertEqual(witness["evidence"]["checkpoint"]["id"], late["id"])
            self.assertEqual(witness["evidence"]["original_offer"]["record"]["quote"]["original"]["value"], "-110")
            self.assertIsNone(witness["evidence"]["sporting_result"])
            bundle = await json_response(await client.get(witness["evidence"]["links"]["export"]))
            self.assertIn(late["id"], bundle["root_ids"])
            self.assertEqual(bundle["manifest"]["bundle_sha256"], hashed({k: v for k, v in bundle.items() if k != "manifest"}))
            finding = next(item for item in first["findings"] if "fee-sizing" in item["claim_ids"])
            self.assertEqual(finding["run_id"], run["id"])
            self.assertTrue(any(item.get("ticket_id") == ticket["id"] for item in finding["evidence"]))
            self.assertTrue(set(finding["claim_ids"]) <= {item["id"] for item in before["claims"]})

            with self.connect() as db:
                self.advance(db, stamp("2026-11-23T21:00:00Z"))
                result = dict(event_id=game["source_event_id"], league="NCAAB", starts_at=game["starts_at"],
                    home="home", away="away", final=True, home_score=80, away_score=70,
                    source="sportsgameodds", received_at=self.at.isoformat(), knowledge_at=self.at.isoformat())
                self.assertEqual(experiment.observe_outcomes(db, [result], at=self.at)["matched"], 1)
            revised = await save()
            self.assertNotEqual(revised["run"]["id"], run["id"])
            self.assertEqual(revised["run"]["supersedes"], run["id"])
            resolved = revised["report"]["portfolios"]["all_venues"]
            self.assertEqual(resolved["resolved"], 2)
            self.assertEqual(resolved["resolved_expected_profit_usd"], resolved["expected_profit_usd"])
            self.assertNotEqual(resolved["modeled_resolved_pnl_usd"], "0.00")
            self.assertEqual({item["id"] for item in resolved["tickets"]},
                             {item["id"] for item in report["portfolios"]["all_venues"]["tickets"]})
            graded_url = f'{BASE}/runs/{revised["run"]["id"]}/tickets/{ticket["id"]}'
            graded = await json_response(await client.get(graded_url))
            self.assertEqual(graded["evidence"]["sporting_result"]["data"]["home_score"], 80)
            self.assertEqual(await json_response(await client.get(path)), first)

            alternate = await save(assumptions={"minimum_ev": "1/20", "kelly_multiplier": "1/8"})
            self.assertEqual(alternate["definition"]["supersedes"], workspace.PILOT_VERSION)
            self.assertEqual(alternate["definition"]["designation"], "exploratory_replay")
            self.assertEqual(alternate["definition"]["policy"]["sizing_scale_usd"], "1250")
            self.assertEqual(alternate["report"]["portfolios"]["all_venues"]["count"], 1)
            question = dict(title="Sizing evidence review", question="Can a paper commitment reopen its sizing inputs?",
                            claim_ids=["fee-sizing"])
            independent = await save(experiment=question)
            independent_definition = independent["definition"]
            self.assertNotEqual(independent_definition["id"], first["definition"]["id"])
            self.assertEqual(independent_definition["template_version"], workspace.PILOT_VERSION)
            self.assertEqual(independent_definition["claim_versions"], ["fee-sizing-v1"])
            self.assertEqual([finding["claim_ids"] for finding in independent["findings"]], [["fee-sizing"]])
            self.assertEqual(await save(experiment=question), independent)
            dual = await json_response(await client.get(BASE))
            self.assertEqual(len({definition["id"] for definition in dual["definitions"]
                                  if "fee-sizing" in definition["claim_ids"]}), 2)
            separate = await save(date="2026-11-24")
            self.assertEqual(separate["run"]["validity"], "no_valid_capture")
            self.assertEqual(separate["run"]["coverage"]["dispositions"], {"cancelled": 1})
            self.assertEqual(await json_response(await client.get(path)), first)

            with self.connect() as db:
                self.assertEqual(db.execute("SELECT count(*) n FROM public.research_workspace_run").fetchone()["n"], 5)
                with self.assertRaisesRegex(psycopg.Error, "research_record_is_immutable"):
                    db.execute("UPDATE public.research_workspace_run SET summary='{}' WHERE id=%s", (run["id"],))
