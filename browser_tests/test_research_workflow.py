"""Normal Research navigation keeps claims, saved analyses and source evidence linked."""

from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

from browser_tests.test_pregame_current import ASSETS

BASE = "/api/research/workspace"
PILOT_DATE = "2026-11-23"
OTHER_DATE = "2026-11-24"
DEFINITION = "ncaab-t10-paper-v1"
PILOT = "College basketball T−10 pipeline pilot"
THEORY = "T−10 positive EV strategy"
CLAIM = "Capture coverage is auditable"


def test_research_evidence_and_versioned_replay():
    definition = {
        "title": PILOT,
        "version": DEFINITION,
        "designation": "retrospective_replay",
        "question": "Can retained T−10 captures be screened and traced?",
        "claim_ids": ["capture"],
        "evaluation_criteria": ["Trace every graded ticket."],
        "policy": {
            "minimum_ev": "1/25",
            "reference_bankroll_usd": "10000",
            "kelly_multiplier": "1/4",
        },
    }
    games = [
        {
            "game_id": "frozen-game",
            "title": "Away at Home",
            "status": "captured",
            "tickets": 1,
        },
        {
            "game_id": "refused-game",
            "title": "Visitor at Host",
            "status": "refused",
            "reason": "retention_limit",
            "tickets": 0,
        },
    ]
    ticket = {
        "id": "ticket-1",
        "game_id": "frozen-game",
        "title": "Away at Home",
        "label": "Away",
        "venue": "kalshi",
        "family": "moneyline",
        "posted_odds": "+120",
        "ev": "1/20",
        "probability": "1/2",
        "stake_usd": "100",
        "grading": {"state": "win", "pnl_usd": "120"},
    }
    variants = {
        "best_venue": {
            "count": 1,
            "tickets": [ticket],
            "unique_games": 1,
            "days_represented": 1,
            "resolved": 1,
            "unresolved": 0,
            "resolved_expected_profit_usd": "5",
            "modeled_resolved_pnl_usd": "120",
            "turnover_usd": "100",
            "peak_committed_usd": "100",
        },
        "all_venues": {
            "count": 1,
            "tickets": [ticket],
            "unique_games": 1,
            "days_represented": 1,
            "resolved": 1,
            "unresolved": 0,
            "resolved_expected_profit_usd": "5",
            "modeled_resolved_pnl_usd": "120",
            "turnover_usd": "100",
            "peak_committed_usd": "100",
        },
    }
    finding = {
        "id": "coverage-finding",
        "run_id": "monday",
        "title": "Capture coverage",
        "definition_version": DEFINITION,
        "disposition": "inconclusive",
        "statement": "One tracked game missed its required evidence.",
        "claim_ids": ["capture"],
        "evidence": [
            {"label": "Refused checkpoint evidence", "game_id": "refused-game"}
        ],
    }
    pilot = {
        "id": "monday",
        "title": PILOT,
        "date": PILOT_DATE,
        "definition_version": DEFINITION,
        "status": "incomplete",
        "validity": "incomplete_tracked_capture",
        "coverage": {
            "expected_games": None,
            "tracked_games": 2,
            "captured_games": 1,
            "missing_tracked_games": 1,
        },
    }
    report = {"policy": definition["policy"], "portfolios": variants, "games": games}
    state = {
        "pilot": {"title": PILOT, "date": PILOT_DATE, "definition_version": DEFINITION},
        "theories": [
            {
                "id": "t10",
                "title": THEORY,
                "statement": "Theoretical positive returns.",
                "claim_ids": ["capture"],
                "risk_objectives": [
                    {
                        "statement": "≤1% modeled probability of a losing 12-month period",
                        "missing_assumptions": ["Finite starting capital"],
                        "status": "not_established",
                        "estimate": None,
                    }
                ],
            }
        ],
        "claims": [
            {
                "id": "capture",
                "title": CLAIM,
                "type": "implementation_verification",
                "status": "under_examination",
                "statement": "Failed captures remain visible.",
                "challenge": "A failed capture appears complete.",
            }
        ],
        "definitions": [definition],
        "runs": [pilot],
        "findings": [finding],
        "available_dates": [
            {"date": PILOT_DATE, "captured_games": 1},
            {"date": OTHER_DATE, "captured_games": 0},
        ],
    }
    saved = {
        "monday": {
            "run": pilot,
            "definition": definition,
            "report": report,
            "findings": [finding],
        }
    }
    requests, errors = [], []

    def serve(route):
        path = urlsplit(route.request.url).path
        query = parse_qs(urlsplit(route.request.url).query)
        if path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / path.rsplit("/", 1)[1])
        elif path == "/research":
            route.fulfill(path=ASSETS / "research-workspace.html")
        elif path == "/data":
            route.fulfill(path=ASSETS / "data.html")
        elif path == "/api/workspace/status":
            route.fulfill(
                json={
                    "readiness": {
                        "state": "blocked",
                        "blockers": [
                            {
                                "code": "retention",
                                "message": "Retention guard refused capture.",
                                "settings_url": "/settings#storage",
                            },
                        ],
                    }
                }
            )
        elif path == BASE:
            route.fulfill(json=state)
        elif path == BASE + "/runs":
            payload = route.request.post_data_json
            requests.append(payload)
            changes = payload.get("assumptions")
            version = "new-assumptions" if changes else DEFINITION
            active_definition = next(
                (row for row in state["definitions"] if row["version"] == version), None
            )
            if changes and active_definition is None:
                active_definition = dict(
                    definition,
                    version=version,
                    supersedes=DEFINITION,
                    designation="exploratory_replay",
                    policy={**definition["policy"], **changes},
                )
                state["definitions"].append(active_definition)
            run_id = "new-version" if changes else "other-date"
            if run_id not in saved:
                run = dict(
                    pilot,
                    id=run_id,
                    date=payload["date"],
                    definition_version=version,
                    validity="no_valid_capture",
                    coverage={
                        "expected_games": None,
                        "tracked_games": 1,
                        "captured_games": 0,
                        "missing_tracked_games": 1,
                    },
                )
                state["runs"].append(run)
                saved[run_id] = {
                    "run": run,
                    "definition": active_definition,
                    "report": {"games": [games[1]]},
                    "findings": [],
                }
            route.fulfill(json=saved[run_id])
        elif path.startswith(BASE + "/runs/"):
            if "/tickets/" in path:
                route.fulfill(
                    json={
                        "ticket": ticket,
                        "evidence": {
                            "original_offer": {},
                            "sized_calculation": {},
                            "sporting_result": {
                                "known_at": "2026-11-24T02:00:00Z",
                                "data": {"final": True},
                            },
                        },
                    }
                )
            elif "/evidence/" in path:
                route.fulfill(
                    json={
                        "game": games[1],
                        "attempts": [{"state": "refused", "reason": "retention_limit"}],
                    }
                )
            else:
                route.fulfill(json=saved[path.rsplit("/", 1)[1]])
        elif path == "/api/research/paper/latest":
            pull = {
                "pull_id": "previous",
                "state": "complete",
                "requested_at": "2026-11-23T19:00:00Z",
            }
            latest = {
                "pull_id": "newest",
                "state": "failed",
                "requested_at": "2026-11-23T20:00:00Z",
            }
            value = {
                "recent_pulls": [latest, pull],
                "as_of": "2026-11-23T20:01:00Z",
                "pull": latest,
                "incomplete_reason": "Latest attempt is incomplete.",
            }
            if query.get("pull") == ["previous"]:
                value = dict(
                    value,
                    pull=pull,
                    incomplete_reason=None,
                    observations=[
                        {
                            "id": "negative",
                            "label": "Away",
                            "venue": "kalshi",
                            "family": "moneyline",
                            "screen_ev": "-1/20",
                            "available": True,
                            "received_at": "2026-11-23T19:00:00Z",
                            "starts_at": "2026-11-23T21:00:00Z",
                        },
                        {
                            "id": "unavailable",
                            "label": "Home",
                            "venue": "novig",
                            "family": "moneyline",
                            "available": False,
                        },
                    ],
                )
            route.fulfill(json=value)
        else:
            route.fulfill(status=404)

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 820})
        page.route("http://localhost:8891/**", serve)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://localhost:8891/research")
        expect(page.locator("[data-workspace-nav] a")).to_have_text(
            ["Research", "Data", "Settings"]
        )
        expect(page.get_by_text(THEORY, exact=True)).to_be_visible()
        expect(page.get_by_text(CLAIM, exact=True)).to_be_visible()
        expect(page.get_by_text("Retention guard refused capture.")).to_be_visible()

        page.get_by_role("link", name="Open pilot run").click()
        expect(page.get_by_text("Incomplete tracked population")).to_be_visible()
        expect(page.locator(".workspace-stats").first).to_contain_text(
            "Expected gamesUnknown"
        )
        page.get_by_role("link", name="All qualifying venues").click()
        expect(
            page.get_by_role("heading", name="All qualifying venues")
        ).to_be_visible()
        page.get_by_role("link", name="Inspect ticket").click()
        evidence = page.get_by_role("dialog")
        for heading in (
            "Frozen quote",
            "Probability and screening",
            "Paper sizing and fee treatment",
            "Sporting-result grading",
        ):
            expect(evidence.get_by_role("heading", name=heading)).to_be_visible()
        expect(evidence.get_by_text("$120.00")).to_be_visible()
        evidence.get_by_role("button", name="Close").click()

        page.get_by_role("link", name="Capture coverage", exact=True).click()
        page.get_by_role("link", name="Refused checkpoint evidence").click()
        expect(evidence.get_by_text("Capture refused")).to_be_visible()
        expect(evidence.get_by_text("retention limit").first).to_be_visible()
        evidence.get_by_role("button", name="Close").click()
        page.get_by_role("link", name="Results", exact=True).click()
        page.get_by_role("link", name=CLAIM, exact=True).click()
        expect(page.get_by_role("heading", name=CLAIM)).to_be_visible()

        page.get_by_role("link", name="Experiments", exact=True).click()
        page.get_by_label("Available evidence").select_option(OTHER_DATE)
        page.get_by_role("button", name="Save replay").click()
        expect(
            page.get_by_text(
                "Financial metrics are unavailable without a valid capture."
            )
        ).to_be_visible()
        page.reload()
        expect(page.get_by_text("No valid T−10 captures")).to_be_visible()
        assert len(requests) == 1
        page.get_by_role("link", name="Experiments and runs").click()
        page.get_by_text("Change assumptions for a new analysis version").click()
        page.get_by_label("Minimum unrounded EV (decimal or fraction)").fill("0.05")
        page.get_by_role("button", name="Save replay").click()
        expect(page.get_by_text("exploratory replay", exact=False)).to_be_visible()
        page.get_by_role("link", name="Open frozen definition").click()
        expect(page.get_by_text("Earlier version")).to_be_visible()
        assert requests[-1]["assumptions"] == {"minimum_ev": "0.05"}
        assert (
            len(saved["monday"]["report"]["portfolios"]["all_venues"]["tickets"]) == 1
        )

        page.goto("http://localhost:8891/data?evidence=pulls&date=" + PILOT_DATE)
        expect(page.get_by_text("Latest attempt is incomplete.").first).to_be_visible()
        page.get_by_label("Acquisition attempt").select_option("previous")
        expect(page.get_by_text("-5.00%")).to_be_visible()
        expect(page.get_by_text("Source observation unavailable")).to_be_visible()
        expect(page.get_by_text("Pre-start at receipt", exact=False)).to_be_visible()
        expect(
            page.get_by_role("link", name="Export exact pull and original evidence")
        ).to_have_attribute(
            "href",
            f"/api/research/paper/latest?date={PILOT_DATE}&pull=previous&export=1",
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors
        browser.close()
