"""Exercise authoring, the real API, retained repricing and grading with controlled quotes."""

import json
import os
import re
from contextlib import ExitStack
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import psycopg
from aiohttp import web
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect

from app.comparison import current_pregame, fee_mode
from app.dashboard.request_guard import dashboard_guard
from app.dashboard.research_workspace_api import BASE, mount
from app.research import experiment, paper_campaigns
from app.storage import database_roles
from app.storage import paper_result_queue as queue
from app.storage.payload_codec import payload_row
from app.storage.store import connect, hashed, stamp
from browser_tests.test_pregame_current import ASSETS
from tests.test_paper_experiments import priced
from tests.test_paper_experiments_sql import ResearchWorkspaceFixture, SOCKET


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class ControlledWorkbench(ResearchWorkspaceFixture):
    async def test_ui_save_drives_automatic_replay_before_and_after_result(self):
        day = "2026-11-20"
        self.at = stamp(day + "T17:00:00Z")
        event = self.game("control", day + "T18:00:00Z")
        fixture_pop = dict(
            kind="reconciled_occurrences",
            source="control fixture",
            membership_version="control-d1",
            revision="r" * 64,
            observed_at=self.at.isoformat(),
            expected_games=None,
            games=[
                dict(
                    scope_state="eligible",
                    paper_eligible=True,
                    provider_event_id="control",
                    occurrence_id="control",
                    title="Away at control",
                    starts_at=event["starts_at"],
                )
            ],
        )
        with self.connect() as db:
            self.advance(db, self.at)
            experiment.discover(db, [event], at=self.at)
            for label, clock in [("early", "17:00:00"), ("late", "17:50:00")]:
                self.advance(db, stamp(f"{day}T{clock}Z"))
                task = experiment.due(db, at=self.at)[0]
                assert task["checkpoint"] == label
                offer = priced(odds="+300", ev="0.08", venue="prophetx", line="-3.5")
                offer["record"]["event"].update(
                    competition="NCAAB", scheduled_start=event["starts_at"]
                )
                offer["record"]["market_identity"]["rules"] = (
                    "sportsgameodds-unverified-1"
                )
                offer["record"]["result_policy"] = "sportsgameodds-unverified-1:spread"
                offer["record"]["quote"]["source"].update(
                    native_event_id="control",
                    native_market_id="control-spread",
                    native_outcome_id="points-home-game-sp-home",
                    native_line="-3.5",
                )
                offer["record"]["quote"]["times"].update(
                    source_at=self.at.isoformat(), received_at=self.at.isoformat()
                )
                fee = fee_mode.zero_fee(offer["record"], fee_mode.state())
                probability = offer["calculation_payload"]["reference"]["probability"]
                reference = dict(
                    probability=probability,
                    fair_decimal_odds=str(1 / F(probability)),
                    fair_odds="+270",
                    selection_policy=current_pregame.REFERENCE_POLICY,
                    market=dict(family="spread", period="full_game", line="-3.5"),
                    book="fixture-a",
                    prices=[],
                )
                offer["fee_input"] = fee
                offer["calculation_payload"] = current_pregame.calculate(
                    offer["record"],
                    reference,
                    fee,
                    at=self.at,
                    game_key=task["game_id"],
                )
                missing_fee = deepcopy(offer)
                missing_fee["record"]["quote"]["venue"] = "kalshi"
                missing_fee["fee_input"] = None
                snapshot = dict(
                    event=dict(
                        home="home",
                        away="away",
                        competition="NCAAB",
                        scheduled_start=event["starts_at"],
                    ),
                    source_event=dict(event_id="control"),
                    offers=[offer, missing_fee],
                    coverage=dict(incomplete=False),
                    fee_mode=fee_mode.state(),
                )
                capture = experiment.capture(
                    db,
                    task["game_id"],
                    label,
                    snapshot,
                    token=task["token"],
                    requested_at=self.at,
                    received_at=self.at,
                    known_at=self.at,
                )
                assert capture["state"] == "captured"
            self.advance(db, stamp(f"{day}T23:00:00Z"))
            database_roles.enable(db)

        def connect_web():
            return connect(self.name)

        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        mount(app)

        async def experiments(_request):
            return web.FileResponse(ASSETS / "experiment-workspace.html")

        async def status(_request):
            return web.json_response({})

        app.router.add_get("/experiments", experiments)
        app.router.add_get("/api/workspace/status", status)
        app.router.add_static("/view/current/", ASSETS)
        server = TestServer(app)
        await server.start_server()
        self.addAsyncCleanup(server.close)
        with ExitStack() as stack:
            stack.enter_context(
                patch.dict(os.environ, {"PREDICT_DB_ROLE": database_roles.WEB})
            )
            stack.enter_context(
                patch(
                    "app.dashboard.research_workspace_api.connect",
                    side_effect=connect_web,
                )
            )
            stack.enter_context(
                patch.object(queue, "_late_capture_due", return_value=False)
            )
            stack.enter_context(
                patch.object(
                    paper_campaigns.mens_d1,
                    "daily_population",
                    side_effect=lambda db, date: fixture_pop if date == day else None,
                )
            )
            stack.enter_context(
                patch.object(paper_campaigns.mens_d1, "daily_recovery", return_value={})
            )
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    executable_path=os.getenv("PREDICT_CI_CHROMIUM")
                )
                page = await browser.new_page(viewport=dict(width=390, height=820))
                await page.goto(str(server.make_url(
                    f"/experiments?view=create&from=data&date={day}&provider=sportsgameodds&family=spread"
                )))
                await expect(page.get_by_label("First game date (Eastern)")).to_have_value(day)
                await expect(page.get_by_label("Last game date (Eastern)")).to_have_value(day)
                await expect(page.get_by_label("Game scope", exact=True)).to_have_value("")
                await expect(page.get_by_text("sportsgameodds",exact=True)).to_be_visible()
                await page.get_by_label("Game scope", exact=True).select_option("mens-d1")
                await page.get_by_label("Use the experiment’s game scope and dates").check()
                await page.get_by_label("Experiment name").fill(
                    "Controlled $7.51 replay"
                )
                await page.get_by_label("First game date (Eastern)").fill(day)
                await page.get_by_label("Last game date (Eastern)").fill("2026-11-21")
                await page.get_by_label("Target win profit ($)").fill("7.51")
                await page.get_by_label("Compare with Kelly").check()
                await page.get_by_role("button", name="Review", exact=True).click()
                async with page.expect_response(
                    lambda res: (
                        res.request.method == "POST"
                        and res.url.endswith(BASE + "/campaigns")
                    )
                ) as saved:
                    await page.get_by_role(
                        "button", name="Save and run", exact=True
                    ).click()
                response = await saved.value
                assert response.ok, response.status
                await page.wait_for_url(re.compile(r"[?&]campaign=[0-9a-f]{64}"))
                campaign = parse_qs(urlsplit(page.url).query)["campaign"][0]

                # Publication precedes the fixture's final. A different connection
                # processes the sport input and the same saved run after the final.
                with connect_web() as db:
                    assert db.info.user == database_roles.WEB
                    run = paper_campaigns.tick(db)
                    assert run, db.execute(
                        "SELECT state,last_error FROM public.paper_campaign_day"
                    ).fetchall()
                    queue.process_one(db)
                    queue.process_one(db)
                    pending = queue.read(db, run)["version"]["id"]
                    assert pending, db.execute(
                        "SELECT last_error FROM public.paper_result_job"
                    ).fetchall()
                with self.connect() as db:
                    self.advance(db, stamp(f"{day}T23:10:00Z"))
                with psycopg.connect(
                    host=SOCKET,
                    port=55432,
                    user=database_roles.COLLECTOR,
                    dbname=self.name,
                    autocommit=True,
                    row_factory=payload_row,
                ) as db:
                    result = dict(
                        event_id="control",
                        league="NCAAB",
                        starts_at=event["starts_at"],
                        home="home",
                        away="away",
                        final=True,
                        result="completed",
                        home_score=80,
                        away_score=70,
                        source="sportsgameodds",
                        received_at=self.at.isoformat(),
                        knowledge_at=self.at.isoformat(),
                        receipt_sha256=hashed(
                            ["controlled-final", event["source_event_id"]]
                        ),
                    )
                    assert (
                        experiment.observe_outcomes(db, [result], at=self.at)["matched"]
                        == 1
                    )
                with connect_web() as restarted:
                    queue.dispatch(restarted)
                    grades = [queue.process_one(restarted) for _ in range(3)]
                    graded = queue.read(restarted, run)["version"]["id"]
                    assert graded and graded != pending
                    assert graded in grades
                await page.reload(wait_until="domcontentloaded")
                await expect(
                    page.get_by_role("heading", name="Controlled $7.51 replay", exact=True)
                ).to_be_visible()
                await expect(page.get_by_role("heading", name="Campaign to date")).to_be_visible()
                await expect(page.locator(".experiment-comparison table").first.get_by_role(
                    "row", name="ROI")).to_contain_text("300.00% on $2.50 graded stake")
                await page.get_by_role("link", name="By day", exact=True).click()
                await page.get_by_label("Game date (Eastern)").select_option(day)
                await page.get_by_label("Portfolio", exact=True).select_option("all_venues")
                comparison=page.locator(".experiment-comparison table")
                await expect(comparison.get_by_role("columnheader", name="Win $7.51")).to_be_visible()
                await expect(comparison.get_by_role("columnheader", name="Kelly")).to_be_visible()
                await expect(comparison.get_by_role("row", name="ROI")).to_contain_text("300.00% on $2.50 graded stake")
                await comparison.get_by_role("link", name="Inspect games and trades").first.click()
                await expect(
                    page.locator(".result-ledger-table tbody tr")
                ).to_have_count(1)
                await expect(
                    page.locator(".result-ledger-table tbody tr")
                ).to_contain_text("$2.50")
                await page.locator(".result-ledger-table tbody tr a").click()
                await page.get_by_text("Trade calculation and frozen evidence", exact=True).click()
                await expect(page.get_by_role("heading", name="Paper sizing and fee treatment")).to_be_visible()
                api = str(
                    server.make_url(f"{BASE}/runs/{run}/results?variant=all_venues")
                )
                report = await (await page.request.get(api)).json()
                data = report["report"]["portfolios"]["all_venues"]
                ticket = data["tickets"][0]
                assert F(ticket["stake_exact_usd"]) == F("2.50")
                assert F(ticket["return_exact_usd"]) == 10
                assert F(ticket["pnl_exact_usd"]) == F("7.50")
                assert data["summary"]["roi"] == "3"
                async with page.expect_download() as trade_file:
                    await page.get_by_role("link", name="Export trade rows").click()
                trades = json.loads(
                    Path(await (await trade_file.value).path()).read_text()
                )
                assert trades["version"]["id"] == graded
                assert trades["variant"] == "all_venues"
                assert trades["rows"] == [ticket]

                await page.get_by_text("Sizing exclusions", exact=True).click()
                async with page.expect_download() as offer_file:
                    await page.get_by_role(
                        "link", name="Export dated offer ledger"
                    ).click()
                offers = json.loads(
                    Path(await (await offer_file.value).path()).read_text()
                )
                digest = offers.pop("evidence_sha256")
                assert digest == hashed(offers)
                qualified, excluded = offers["games"][0]["offers"]
                assert F(offers["sizing"]["target_profit_usd"]) == F("7.51")
                assert (
                    qualified["sizing"]["frozen_quote_id"] == ticket["frozen_quote_id"]
                )
                assert excluded["sizing"]["reason"] == "captured_fee_inputs_unavailable"
                assert report["provider_requests"] == report["orders_submitted"] == 0
                await expect(page).to_have_url(re.compile(f"campaign={campaign}.*"))
                await browser.close()
