"""Owner can configure a week, compare EV screens and revise it without a CLI."""

import os
import re
from fractions import Fraction
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

from app.research.paper import money
from app.research.paper_campaigns import analysis, configuration
from app.research.paper_results import _summary
from browser_tests.test_paper_results import FIRST, report
from browser_tests.test_research_workspace import research_http_fixture
from browser_tests.test_pregame_current import ASSETS
from tests.test_paper_campaigns import config, ticket


def test_schedule_week_ev_comparisons_and_revision_form():
    identity, revision, older = "a" * 64, "c" * 64, "d" * 64
    cfg = configuration(config())
    results = analysis([ticket("trade", ".08")], cfg["bucket_edges"], "best_venue")
    saved = []
    errors = []

    def serve(route):
        path = urlsplit(route.request.url).path
        if path == "/research":
            route.fulfill(path=ASSETS / "research-workspace.html")
        elif path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(path).name)
        elif path == "/api/research/workspace":
            route.fulfill(json=dict(definitions=[], runs=[], campaigns=[]))
        elif path == "/api/workspace/status":
            route.fulfill(json={})
        elif (
            path == "/api/research/workspace/campaigns"
            and route.request.method == "POST"
        ):
            saved.append(route.request.post_data_json)
            route.fulfill(json=dict(id=revision if len(saved) > 1 else identity, **cfg))
        elif path in {
            f"/api/research/workspace/campaigns/{campaign}"
            for campaign in (identity, revision)
        }:
            selected = path.rsplit("/", 1)[-1]
            route.fulfill(
                json=dict(
                    id=selected,
                    config=dict(cfg, supersedes=identity)
                    if selected == revision
                    else cfg,
                    weekly=results,
                    reported_days=1,
                    days=[
                        dict(
                            date="2026-11-23",
                            state="published",
                            result_state="graded",
                            run_id="b" * 64,
                            retrospective=True,
                            captures=dict(captured=1),
                            analysis=results,
                            snapshots=[
                                dict(id=older, recorded_at="2026-11-23T22:40:00Z")
                            ],
                        ),
                        dict(date="2026-11-29", state="scheduled"),
                    ],
                )
            )
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        page = browser.new_page(viewport=dict(width=390, height=820))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/research?section=experiments")
        page.get_by_role("link", name="Create experiment", exact=True).click()
        page.get_by_label("Experiment name", exact=True).fill("NCAAB week")
        page.get_by_label("First game date").fill("2026-11-23")
        page.get_by_label("Last game date").fill("2026-11-29")
        expect(page.get_by_label("Target win profit ($)")).to_have_value("10")
        expect(page.get_by_label("Full Kelly used (%)")).to_be_hidden()
        page.get_by_label("Sizing method").select_option("kelly")
        expect(page.get_by_label("Target win profit ($)")).to_be_hidden()
        expect(page.get_by_label("Full Kelly used (%)")).to_have_value("2.5")
        page.get_by_role("button", name="Review", exact=True).click()
        expect(page.get_by_role("region", name="Review experiment")).to_contain_text(
            "2.5% of full Kelly"
        )
        page.get_by_role("button", name="Save and run").click()
        expect(
            page.get_by_role("heading", name="Daily results", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role("navigation", name="Report period").get_by_role(
                "link", name="Weekly"
            )
        ).to_have_attribute("aria-current", "page")
        assert saved[0]["kelly_multiplier"] == "0.025"
        assert saved[0]["bucket_edges"] == ["0.04", "0.08", "0.15", "0.25"]
        expect(
            page.get_by_role("heading", name="EV buckets", exact=True)
        ).to_be_visible()
        expect(
            page.get_by_role(
                "heading", name="What if the minimum EV changed?", exact=True
            )
        ).to_be_visible()
        expect(
            page.get_by_role("link", name="2026-11-23", exact=True)
        ).to_have_attribute("href", re.compile("run="))
        expect(page.get_by_role("row").filter(has_text="2026-11-29")).to_contain_text(
            "Awaiting evidence"
        )
        page.get_by_role("link", name="2026-11-29", exact=True).click()
        expect(
            page.get_by_role("navigation", name="Report period").get_by_role(
                "link", name="Daily"
            )
        ).to_have_attribute("aria-current", "page")
        expect(
            page.get_by_role("status").filter(
                has_text="Awaiting retained capture evidence"
            )
        ).to_be_visible()
        expect(page.get_by_label("Game date (Eastern)")).to_have_value("2026-11-29")
        page.reload()
        expect(page.get_by_label("Game date (Eastern)")).to_have_value("2026-11-29")
        page.get_by_role("link", name="Weekly", exact=True).click()
        expect(
            page.get_by_role("heading", name="Daily results", exact=True)
        ).to_be_visible()
        expect(page.get_by_role("link", name="Daily", exact=True)).to_have_attribute(
            "href", re.compile("date=2026-11-29")
        )
        page.get_by_text("Previous snapshots (1)", exact=True).click()
        expect(page.get_by_role("link", name=re.compile(older[:12]))).to_have_attribute(
            "href", re.compile(f"run={older}")
        )
        page.get_by_role("link", name="All qualifying venues", exact=True).click()
        expect(
            page.get_by_role("link", name="All qualifying venues", exact=True)
        ).to_have_attribute("aria-current", "true")
        page.get_by_role("button", name="Edit as a new version").click()
        expect(page.get_by_label("Full Kelly used (%)")).to_have_value("2.5")
        page.reload()
        expect(page.get_by_label("Full Kelly used (%)")).to_have_value("2.5")
        page.get_by_label("Minimum EV (%)").fill("4.19")
        page.get_by_label("EV bucket boundaries (%)").fill("4.19, 8, 15, 25")
        page.get_by_role("button", name="Review", exact=True).click()
        page.get_by_role("button", name="Save and run").click()
        expect(
            page.get_by_role("link", name="Open previous experiment version")
        ).to_have_attribute(
            "href", re.compile(f"campaign={identity}.*variant=all_venues")
        )
        assert saved[1]["supersedes"] == identity
        assert saved[1]["minimum_ev"] == saved[1]["bucket_edges"][0] == "0.0419"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors
        browser.close()


def test_create_fixed_profit_compare_same_bet_and_repeat_with_another_target():
    endpoint = "/api/research/workspace"
    first_id, second_id, next_version = "a" * 64, "b" * 64, "c" * 64
    fixed_run, kelly_run, other_run, revised_run = (letter * 64 for letter in "def0")
    first_date, other_date = "2026-11-23", "2026-11-20"
    configs, posts, exports, errors = {}, [], [], []
    unavailable_fee = "captured_fee_inputs_unavailable"
    unavailable_increment = "fixed_profit_quantity_increment_unavailable"
    change_counts = {
        "jointly_qualifying_quotes": 0,
        "fixed_profit_only_qualifying_quotes": 1,
        "kelly_only_qualifying_quotes": 1,
        "jointly_selected_quotes": 0,
        "fixed_profit_only_selected_quotes": 1,
        "kelly_only_selected_quotes": 1,
        "venue_changes": 1,
    }

    def selected_trade(cfg, mode):
        selected = report(FIRST)["portfolios"]["best_venue"]["tickets"][0]
        target = Fraction(cfg["target_profit_usd"])
        stake = Fraction("75.32")
        if mode == "fixed_profit":
            ideal = target / 3
            stake = Fraction(round(ideal * 1000), 1000)
            achieved = stake * 3
            selected["posted_odds"] = "+300"
            selected["sizing"] = dict(
                mode=mode,
                rule="nearest-positive-net-win-lower-commitment-1",
                target_profit_usd=str(target),
                modeled_win_profit_usd=str(achieved),
                profit_difference_usd=str(achieved - target),
                ideal_purchase_usd=str(ideal),
            )
        ev = Fraction(2, 25)
        selected.update(
            id=mode + "-selected",
            equivalent_bet_id="same-bet",
            screen_ev=str(ev),
            ev=str(ev),
            frozen_quote_id=mode + "-quote",
            venue="novig" if mode == "fixed_profit" else "kalshi",
            stake_exact_usd=str(stake),
            stake_usd=money(stake),
            pnl_exact_usd=str(-stake),
            pnl_usd=money(-stake),
            return_exact_usd="0",
            expected_profit_exact_usd=str(ev * stake),
            expected_profit_usd=money(ev * stake),
        )
        return selected

    def excluded_quote(run):
        if run in (fixed_run, kelly_run):
            return dict(
                frozen_quote_id="unpriced-in-both-modes",
                offer_index=2,
                reason=unavailable_fee,
            )
        return dict(
            frozen_quote_id="missing-increment",
            offer_index=2,
            reason=unavailable_increment,
        )

    def serve(route):
        target = urlsplit(route.request.url)
        path = target.path
        query = {key: values[0] for key, values in parse_qs(target.query).items()}
        if path == "/research":
            route.fulfill(path=ASSETS / "research-workspace.html")
        elif path.startswith("/view/current/"):
            route.fulfill(path=ASSETS / Path(path).name)
        elif path == endpoint:
            route.fulfill(
                json=dict(definitions=[], runs=[], campaigns=list(configs.values()))
            )
        elif path == "/api/workspace/status":
            route.fulfill(json={})
        elif path == f"{endpoint}/campaigns" and route.request.method == "POST":
            body = dict(route.request.post_data_json)
            posts.append(body)
            identity = (first_id, second_id, next_version)[len(posts) - 1]
            origin = body.get("supersedes")
            cfg = configuration(
                {key: value for key, value in body.items() if key != "supersedes"}
            )
            if origin:
                cfg["supersedes"] = origin
            configs[identity] = dict(id=identity, **cfg)
            route.fulfill(json=configs[identity])
        elif path.startswith(f"{endpoint}/campaigns/"):
            identity = path.rsplit("/", 1)[-1]
            cfg = configs[identity]
            variant = query["variant"]
            mode = query.get("mode", "fixed_profit")
            result = analysis([selected_trade(cfg, mode)], cfg["bucket_edges"], variant)
            if query.get("export"):
                exports.append((identity, mode, variant))
            run_id = {
                first_id: kelly_run if mode == "kelly" else fixed_run,
                second_id: other_run,
                next_version: revised_run,
            }[identity]
            days = [
                dict(
                    date=cfg["start_date"],
                    state="published",
                    result_state="graded",
                    run_id=run_id,
                    captures=dict(captured=1),
                    analysis=result,
                )
            ]
            if cfg["start_date"] != cfg["end_date"]:
                days.append(dict(date=cfg["end_date"], state="scheduled"))
            route.fulfill(
                json=dict(
                    id=identity,
                    variant=variant,
                    mode=mode,
                    config=cfg,
                    weekly=result,
                    reported_days=1,
                    days=days,
                    available_modes=["fixed_profit", "kelly"]
                    if cfg["kelly_comparison"]
                    else ["fixed_profit"],
                    comparison=change_counts if cfg["kelly_comparison"] else None,
                )
            )
        elif path.startswith(f"{endpoint}/runs/"):
            identity = path.split("/")[5]
            mode = "kelly" if identity == kelly_run else "fixed_profit"
            cfg = configs[
                {other_run: second_id, revised_run: next_version}.get(
                    identity, first_id
                )
            ]
            saved_report = report(FIRST)
            selected = selected_trade(cfg, mode)
            for portfolio in saved_report["portfolios"].values():
                portfolio.update(tickets=[selected], summary=_summary([selected]))
            definition = dict(
                version="fixture",
                campaign_id=cfg["id"],
                sizing_mode=mode,
                kelly_comparison=cfg["kelly_comparison"],
            )
            if path.endswith("/results"):
                data = dict(
                    report=saved_report, status=dict(state="graded", stale=False)
                )
                route.fulfill(json=data)
            elif path.endswith("/offers"):
                excluded = excluded_quote(identity)
                route.fulfill(
                    json=dict(
                        run_id=identity,
                        games=[
                            dict(
                                offers=[
                                    dict(
                                        offer_index=excluded["offer_index"],
                                        sizing=dict(
                                            state="excluded",
                                            frozen_quote_id=excluded["frozen_quote_id"],
                                            reason=excluded["reason"],
                                        ),
                                    ),
                                ]
                            )
                        ],
                    ),
                    headers={
                        "Content-Disposition": 'attachment; filename="offers.json"'
                    },
                )
            elif "/tickets/" in path:
                route.fulfill(
                    json=dict(
                        ticket=selected,
                        evidence=dict(trade=dict(sizing=selected.get("sizing"))),
                    )
                )
            else:
                changes = [
                    dict(
                        frozen_quote_id=selected["frozen_quote_id"],
                        equivalent_bet_id=selected["equivalent_bet_id"],
                        label=selected["label"],
                        family=selected["family"],
                        line=selected["line"],
                        venue=selected["venue"],
                        **{
                            mode: dict(
                                qualifies=True,
                                selected=True,
                                ev=selected["ev"],
                                venue=selected["venue"],
                                ticket_id=selected["id"],
                            ),
                            "kelly" if mode == "fixed_profit" else "fixed_profit": dict(
                                qualifies=False, reason="sized_ev_below_minimum"
                            ),
                        },
                    )
                ]
                views = {
                    variant: dict(counts=change_counts, changes=changes)
                    for variant in cfg["portfolios"]
                }
                route.fulfill(
                    json=dict(
                        run=dict(
                            id=identity, date=cfg["start_date"], title=cfg["name"]
                        ),
                        definition=definition,
                        report=dict(
                            policy=dict(
                                execution="paper_only",
                                sizing_mode=mode,
                                target_profit_usd=cfg["target_profit_usd"],
                            ),
                            portfolios=saved_report["portfolios"],
                            games=[
                                dict(
                                    status="captured",
                                    sizing_exclusions=[excluded_quote(identity)],
                                ),
                                dict(
                                    status="captured",
                                    sizing_exclusions=[
                                        dict(
                                            excluded_quote(identity),
                                            frozen_quote_id="second-quote-with-same-reason",
                                        )
                                    ],
                                ),
                            ],
                        ),
                        sizing_runs=dict(fixed_profit=fixed_run, kelly=kelly_run)
                        if cfg["kelly_comparison"]
                        else {mode: identity},
                        sizing_comparison=views if cfg["kelly_comparison"] else {},
                    )
                )
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base, sync_playwright() as runtime:
        browser = runtime.chromium.launch(
            executable_path=os.getenv("PREDICT_CI_CHROMIUM")
        )
        page = browser.new_page(viewport={"width": 1280, "height": 850})
        page.on("pageerror", lambda error: errors.append(str(error)))

        def create(name, start, end, target):
            page.get_by_role("link", name="Experiments", exact=True).click()
            page.get_by_role("link", name="Create experiment", exact=True).click()
            page.get_by_label("Experiment name").fill(name)
            page.get_by_label("First game date").fill(start)
            page.get_by_label("Last game date").fill(end)
            expect(page.get_by_label("Game scope")).to_have_value("mens-d1")
            expect(page.get_by_label("Target win profit ($)")).to_have_value("10")
            page.get_by_label("Target win profit ($)").fill(target)

        def review_and_save():
            page.get_by_role("button", name="Review", exact=True).click()
            expect(page.get_by_role("region", name="Review experiment")).to_be_visible()
            page.get_by_role("button", name="Save and run").click()

        def inspect_exclusions(reason, run, code):
            disclosure = page.get_by_text("Sizing exclusions", exact=True)
            container = disclosure.locator("..")
            row = container.get_by_role("row", name=re.compile(reason))
            expect(row).to_be_hidden()
            disclosure.click()
            expect(row.get_by_role("cell", name="2", exact=True)).to_be_visible()
            destination = container.get_by_role(
                "link", name="Export dated offer ledger"
            ).get_attribute("href")
            assert destination == f"{endpoint}/runs/{run}/offers"
            ledger = page.request.get(base + destination)
            assert ledger.ok
            assert ledger.json()["games"][0]["offers"][0]["sizing"]["reason"] == code

        page.goto(base + "/research?section=experiments")
        create("Men’s D1 Win $10", first_date, "2026-11-29", "10")
        page.get_by_label("Compare with Kelly").check()
        expect(page.get_by_label("Reference bankroll ($)")).to_have_value("10000")
        expect(page.get_by_label("Full Kelly used (%)")).to_have_value("2.5")
        review_and_save()
        modes = page.get_by_role("navigation", name="Sizing mode")
        expect(modes.get_by_role("link", name="Win $10", exact=True)).to_have_attribute(
            "aria-current", "page"
        )
        expect(
            page.get_by_role("heading", name="Win profit and Kelly comparison")
        ).to_be_visible()
        page.get_by_role("link", name="All qualifying venues", exact=True).click()
        page.get_by_role("link", name=first_date, exact=True).click()
        inspect_exclusions(
            "Captured fee inputs unavailable", fixed_run, unavailable_fee
        )
        page.get_by_role("link", name="East Carolina -14.5").click()
        page.get_by_label("Grade", exact=True).select_option("loss")
        inspector = page.get_by_role("complementary", name="Trade inspector")
        expect(inspector).to_contain_text("-1/1000 USD exact")
        page.get_by_text("Sizing qualification and venue changes", exact=True).click()
        expect(page.get_by_role("cell", name="sized ev below minimum")).to_be_visible()
        modes.get_by_role("link", name="Kelly", exact=True).click()
        expect(page.get_by_label("Game date (Eastern)")).to_have_value(first_date)
        assert f"run={kelly_run}" in page.url
        expect(page.get_by_label("Grade", exact=True)).to_have_value("loss")
        expect(inspector).to_contain_text("Kalshi")
        expect(inspector).to_contain_text(
            "Showing a different venue for the same exact bet"
        )
        inspect_exclusions(
            "Captured fee inputs unavailable", kelly_run, unavailable_fee
        )
        page.reload()
        expect(modes.get_by_role("link", name="Kelly", exact=True)).to_have_attribute(
            "aria-current", "page"
        )
        expect(
            page.get_by_role("link", name="All qualifying venues", exact=True)
        ).to_have_attribute("aria-current", "true")
        expect(inspector).to_contain_text("Kalshi")
        page.go_back()
        expect(modes.get_by_role("link", name="Win $10", exact=True)).to_have_attribute(
            "aria-current", "page"
        )
        expect(inspector).to_contain_text("Novig")
        expect(page.get_by_label("Grade", exact=True)).to_have_value("loss")
        assert posts[0]["kelly_comparison"] and posts[0]["kelly_multiplier"] == "0.025"

        create("Controlled $7.50 replay", other_date, other_date, "7.50")
        page.get_by_label("Best venue only").uncheck()
        review_and_save()
        expect(
            page.get_by_role("heading", name="Controlled $7.50 replay")
        ).to_be_visible()
        expect(
            page.get_by_role("heading", name="Week / experiment total")
        ).to_be_visible()
        expect(
            page.get_by_role("article").filter(has_text="Week / experiment total")
        ).to_contain_text("$2.50")
        expect(modes).to_have_count(0)
        expect(
            page.get_by_role("link", name="Best venue only", exact=True)
        ).to_have_count(0)
        week_export = page.get_by_role(
            "link", name="Export daily, weekly and EV analysis"
        ).get_attribute("href")
        assert page.request.get(base + week_export).ok
        assert exports == [(second_id, "fixed_profit", "all_venues")]
        page.get_by_role("link", name=other_date, exact=True).click()
        inspect_exclusions(
            "Captured quantity increment unavailable", other_run, unavailable_increment
        )
        page.get_by_role("link", name="Weekly", exact=True).click()
        page.get_by_role("button", name="Edit as a new version").click()
        expect(page.get_by_label("Target win profit ($)")).to_have_value("7.5")
        page.reload()
        expect(page.get_by_label("First game date")).to_have_value(other_date)
        page.get_by_label("Target win profit ($)").fill("8.25")
        review_and_save()
        expect(
            page.get_by_role("link", name="Open previous experiment version")
        ).to_have_attribute("href", re.compile(second_id))
        assert posts[1]["portfolios"] == ["all_venues"]
        assert posts[1]["target_profit_usd"] == "7.50"
        assert "kelly_multiplier" not in posts[1]
        assert (
            posts[2]["target_profit_usd"] == "8.25"
            and posts[2]["supersedes"] == second_id
        )
        page.set_viewport_size({"width": 390, "height": 820})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors
        browser.close()
