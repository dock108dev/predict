"""Disposable SQL for acquisition previews and saved paper research."""
from asyncio import gather
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


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class ResearchWorkspaceSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        from app.research import experiment

        self.at = stamp("2026-11-23T17:00:00Z")
        with self.connect() as db:
            db.execute("CREATE TABLE public.workspace_fixture_clock(at timestamptz NOT NULL)")
            db.execute("INSERT INTO public.workspace_fixture_clock VALUES (%s)", (self.at,))
            db.execute("""CREATE FUNCTION public.workspace_fixture_now() RETURNS timestamptz
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
