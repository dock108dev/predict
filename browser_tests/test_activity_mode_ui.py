"""Owner-authorized modes, passive expiry, and quiet cohort filters in ordinary UI."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from browser_tests.test_pregame_current import ASSETS, offer
from browser_tests.test_pregame_arb_recovery import pair_fixture

CLOCK = int(datetime(2026, 11, 18, 12, 30, tzinfo=timezone.utc).timestamp() * 1000)


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


class ModeFixture:
    def __init__(self, owner=False, mode="monitor"):
        self.owner = owner
        self.now = CLOCK
        self.mode = mode
        self.revision = 1
        self.last = CLOCK if mode == "live" else None
        self.settings = dict(
            monitor_interval_seconds=1800,
            monitor_horizon_seconds=86400,
            live_interval_seconds=60,
            live_window_seconds=3600,
            inactivity_seconds=900,
        )
        self.reads, self.writes, self.authorizations = [], [], 0
        self.runs = {}

    def status(self):
        until = (
            self.last + self.settings["inactivity_seconds"] * 1000
            if self.last
            else None
        )
        expired = self.mode == "live" and until <= self.now
        return dict(
            schema="predict-activity-mode-1",
            mode="monitor" if expired else self.mode,
            requested_mode=self.mode,
            revision=self.revision,
            settings=deepcopy(self.settings),
            last_activity_at=iso(self.last) if self.last else None,
            live_until=iso(until) if until else None,
            reason="inactivity" if expired else "selected",
            runs=deepcopy(self.runs),
        )

    def rows(self, kind):
        rows = []
        for mode in ("monitor", "live"):
            row = offer()
            at = CLOCK - (1800000 if mode == "monitor" else 60000)
            row.update(
                id=f"{mode}-quote",
                selection_label="Orlando Magic",
                kickoff=iso(CLOCK + 7200000),
                collection=dict(
                    kind=mode,
                    observed_at=iso(at),
                    run_id=mode + "-run",
                    origin="collected",
                ),
            )
            row["times"].update(source_at=iso(at), received_at=iso(at))
            for price in row["reference"]["prices"]:
                price["source_at"] = iso(at)
            row["raw"].update(posted_decimal="2.2", after_fee_decimal="2.176")
            if mode == "live":
                # The same exact line has a different collected price in each
                # cohort. A pinned inspection must not silently switch prices.
                row["posted"]["value"] = "+160"
                row["raw"].update(
                    posted_decimal="2.6", after_fee_decimal="2.568", net_ev="0.284"
                )
                row["display"].update(
                    posted_odds="+160", after_fees="+157", net_ev="+28.40%"
                )
                row["fee"]["cashflows"]["win"].update(
                    total_fee_usd="3.2", net_receipt_usd="256.8"
                )
            row["ranking"] = dict(
                method="edge",
                label="Probability edge",
                column="Edge",
                unit="pp",
                display="+4.000",
                value="4",
            )
            if kind in ("all", mode):
                rows.append(row)
        return rows

    async def serve(self, route):
        url = urlparse(route.request.url)
        q = {key: values[0] for key, values in parse_qs(url.query).items()}
        method = route.request.method
        if url.path.startswith("/api/admin/activity-mode"):
            if method == "GET":
                self.authorizations += 1
            else:
                self.writes.append((url.path, route.request.post_data_json))
            if not self.owner:
                await route.fulfill(status=401, json={"error": "unauthorized"})
                return
            if method == "PATCH":
                body = route.request.post_data_json
                self.settings.update(body.get("settings", {}))
                if "mode" in body:
                    self.mode = body["mode"]
                    self.last = self.now if self.mode == "live" else None
                self.revision += 1
            elif method == "POST" and self.status()["mode"] == "live":
                self.last = self.now
                self.revision += 1
            await route.fulfill(json=self.status())
        elif url.path.startswith("/api/pregame"):
            if q.get("mode_status") == "1":
                await route.fulfill(
                    json=dict(activity_mode=self.status(), provider_requests=0)
                )
                return
            if url.path.endswith("/updates"):
                await route.fulfill(
                    json=dict(changed=False, activity_mode=self.status())
                )
                return
            self.reads.append((url.path, q))
            kind = q.get("data_type") or (
                "all" if q.get("browse") == "1" else self.status()["mode"]
            )
            rows = self.rows(kind)
            if q.get("max_age_minutes"):
                rows = [
                    row
                    for row in rows
                    if (
                        self.now
                        - datetime.fromisoformat(row["times"]["source_at"]).timestamp()
                        * 1000
                    )
                    / 60000
                    <= int(q["max_age_minutes"])
                ]
            if q.get("order") == "newest":
                rows.reverse()
            packet = dict(
                cursor=str(self.revision),
                rows=rows,
                total=len(rows),
                data_type=kind,
                activity_mode=self.status(),
                sort="edge",
            )
            if q.get("view") == "games":
                base = offer()
                packet.update(
                    rows=[],
                    total=1,
                    games=[
                        dict(
                            game_key=base["game_key"],
                            game=base["game"],
                            league=base["league"],
                            kickoff=iso(CLOCK + 7200000),
                            rows=rows,
                        )
                    ],
                )
            if url.path.endswith("/arbs"):
                pair = pair_fixture()
                for leg in pair["legs"]:
                    leg["collection"] = dict(
                        kind=kind if kind != "all" else "monitor",
                        observed_at=iso(CLOCK),
                        origin="collected",
                    )
                packet.update(rows=[pair], total=1, sort=q.get("sort", "return"))
            await route.fulfill(json=packet)
        else:
            filename = (
                Path(url.path).name
                if url.path.startswith("/view/")
                else "pregame-arbs.html"
                if url.path == "/arbs"
                else "pregame.html"
            )
            await route.fulfill(
                path=ASSETS / filename,
                headers={
                    "Content-Security-Policy": "default-src 'self'; connect-src 'self'"
                },
            )


@pytest.mark.parametrize("path", ["/", "/browse-odds", "/arbs"])
def test_public_modes_are_read_only_and_settings_require_owner(path):
    from playwright.async_api import async_playwright, expect

    async def journey():
        state = ModeFixture()
        state.runs = {
            "monitor": {"state": "budget_delayed"},
            "live": {"state": "partial"},
        }
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.route("**/*", state.serve)
            await page.goto("https://predict.fixture" + path)
            await expect(page.locator(".mode-badge")).to_have_text("Settings")
            await expect(page.locator(".collection-badge")).to_have_count(0)
            await expect(page.locator("#count")).not_to_contain_text("Monitor")
            await expect(page.locator("#count")).not_to_contain_text("Live")
            assert state.authorizations == 0
            assert not state.writes
            await page.locator(".mode-badge").click()
            await expect(
                page.get_by_role("link", name="Sign in through Admin")
            ).to_be_visible()
            await expect(
                page.get_by_role("switch", name="Live mode", exact=True)
            ).to_be_disabled()
            await expect(
                page.get_by_label("Monitor refresh (minutes)", exact=True)
            ).to_be_disabled()
            assert state.authorizations == 1 and not state.writes
            await expect(page.locator(".mode-run-summary")).to_contain_text(
                "waiting for budget"
            )
            await expect(page.locator(".mode-run-summary")).to_contain_text(
                "partial update"
            )
            await expect(page.locator('a[href*="dataset=practice"]')).to_have_count(0)
            await expect(page.locator("[data-caution]")).to_have_count(0)
            assert not errors, errors
            await browser.close()

    asyncio.run(journey())


@pytest.mark.parametrize("width", [1280, 390])
def test_owner_settings_activity_and_passive_idle_fallback_use_fake_clock(width):
    from playwright.async_api import async_playwright, expect

    async def journey():
        state = ModeFixture(owner=True)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": width, "height": 844})
            await page.clock.install(
                time=datetime.fromtimestamp(CLOCK / 1000, timezone.utc)
            )
            await page.route("**/*", state.serve)
            await page.goto("https://predict.fixture/")
            await page.locator(".mode-badge").click()
            field = page.get_by_label("Monitor refresh (minutes)", exact=True)
            await expect(field).to_be_enabled()
            save = page.get_by_role("button", name="Save settings", exact=True)
            await expect(save).to_be_visible()
            assert await save.get_attribute("form") == "mode-settings-form"
            assert await save.evaluate("button=>button.closest('form')===null")
            save_y = (await save.bounding_box())["y"]
            await page.locator(".mode-settings-body").evaluate(
                "body=>body.scrollTop=body.scrollHeight"
            )
            assert abs((await save.bounding_box())["y"] - save_y) < 1
            bounds = await save.bounding_box()
            assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= 844
            await field.fill("45")
            state.now += 15001
            await page.clock.fast_forward(15001)
            await expect(field).to_have_value(
                "45"
            )  # A passive status poll preserves dirty settings.
            await page.get_by_role("button", name="Save settings").click()
            await expect(page.locator(".mode-message")).to_contain_text("saved")
            assert state.settings == dict(
                monitor_interval_seconds=2700,
                monitor_horizon_seconds=86400,
                live_interval_seconds=60,
                live_window_seconds=3600,
                inactivity_seconds=900,
            )
            await page.get_by_role("switch", name="Live mode", exact=True).check()
            await expect(page.locator(".mode-badge")).to_have_text("Live · Settings")
            assert state.status()["mode"] == "live"
            assert not [
                request for request in state.writes if request[0].endswith("/activity")
            ]
            state.now += 15001
            await page.clock.fast_forward(15001)
            assert not [
                request for request in state.writes if request[0].endswith("/activity")
            ]
            async with page.expect_response(
                lambda response: response.url.endswith("/activity")
            ):
                await page.mouse.move(15, 15)
            assert (
                len(
                    [
                        request
                        for request in state.writes
                        if request[0].endswith("/activity")
                    ]
                )
                == 1
            )
            await page.mouse.move(20, 20)
            assert (
                len(
                    [
                        request
                        for request in state.writes
                        if request[0].endswith("/activity")
                    ]
                )
                == 1
            )
            # Same-tab navigation re-verifies authorization; it does not itself renew Live.
            await page.goto("https://predict.fixture/browse-odds")
            await expect(page.locator(".mode-badge")).to_have_text("Live · Settings")
            assert state.authorizations >= 2
            activity_count = len(
                [
                    request
                    for request in state.writes
                    if request[0].endswith("/activity")
                ]
            )
            state.now += 900001
            await page.clock.fast_forward(900001)
            await expect(page.locator(".mode-badge")).to_have_text("Settings")
            await page.mouse.move(25, 25)
            assert (
                len(
                    [
                        request
                        for request in state.writes
                        if request[0].endswith("/activity")
                    ]
                )
                == activity_count
            )
            assert not [body for _, body in state.writes if body.get("mode") == "live"][
                1:
            ]
            await browser.close()

    asyncio.run(journey())


def test_cohort_age_order_controls_and_browse_combined_default():
    from playwright.async_api import async_playwright, expect

    async def journey():
        state = ModeFixture()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(
                viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
            )
            await page.clock.install(
                time=datetime.fromtimestamp(CLOCK / 1000, timezone.utc)
            )
            await page.route("**/*", state.serve)
            await page.goto("https://predict.fixture/")
            await expect(page.locator(".ticket")).to_have_count(1)
            await expect(page.locator("#ranking")).to_have_value("edge")
            await expect(page.locator(".collection-badge")).to_have_count(0)
            await expect(page.locator("#count")).to_have_text("1 opportunity")
            await expect(page.locator("#results .posted .math-trigger")).to_have_text(
                "45.45%"
            )
            await page.locator(".row-open").tap()
            await expect(page.locator(".comparison-status")).to_contain_text("complete")
            await expect(
                page.locator(".exchange-prices tbody td").nth(1)
            ).to_contain_text("45.45%")
            assert state.reads[-1][1]["data_type"] == "monitor"
            prior_reads = len(state.reads)
            state.mode, state.last = "live", state.now
            state.revision += 1
            await page.clock.fast_forward(501)
            await expect(
                page.locator('#results .row-open[data-quote-id="live-quote"]')
            ).to_have_count(1)
            await expect(page.locator("#results .posted .math-trigger")).to_have_text(
                "38.46%"
            )
            await expect(page.locator(".mode-badge")).to_have_text("Live · Settings")
            await expect(
                page.locator(".exchange-prices tbody td").nth(1)
            ).to_contain_text("45.45%")
            await expect(page.locator(".exchange-prices")).not_to_contain_text("38.46%")
            assert any(
                q.get("bet_id") and q.get("data_type") == "monitor"
                for _, q in state.reads[prior_reads:]
            )
            assert all(
                q.get("data_type") == "monitor"
                for _, q in state.reads[prior_reads:]
                if q.get("bet_id")
            )
            await expect(page.locator(".collection-badge")).to_have_count(0)
            await page.get_by_role("button", name="Close comparison").tap()
            await page.locator("#board-advanced > summary").tap()
            await page.locator("#data-type").select_option("all")
            await expect(page.locator(".ticket")).to_have_count(2)
            await page.locator("#order").select_option("newest")
            await expect(page.locator(".ticket .row-open").first).to_have_attribute(
                "data-quote-id", "live-quote"
            )
            await expect(
                page.locator(".ticket .posted .math-trigger").first
            ).to_have_text("38.46%")
            await page.locator("#max-age").fill("5")
            await page.clock.fast_forward(1)
            await expect(page.locator(".ticket")).to_have_count(1)
            assert state.reads[-1][1]["max_age_minutes"] == "5"
            assert state.reads[-1][1]["order"] == "newest"
            assert state.reads[-1][1]["data_type"] == "all"
            await page.goto("https://predict.fixture/browse-odds")
            await expect(page.locator(".game-card")).to_have_count(1)
            assert state.reads[-1][1]["data_type"] == "all"
            await expect(page.locator(".game-card .collection-badge")).to_have_count(0)
            await expect(page.locator("#count")).to_have_text("1 game")
            await expect(page.locator(".game-card")).to_contain_text("45.45%")
            await expect(page.locator(".game-card")).to_contain_text("38.46%")
            assert await page.evaluate(
                "document.documentElement.scrollWidth<=innerWidth"
            )
            assert not state.writes
            await browser.close()

    asyncio.run(journey())


def test_short_idle_window_reports_activity_before_its_deadline():
    from playwright.async_api import async_playwright, expect

    async def journey():
        state = ModeFixture(owner=True)
        state.settings["inactivity_seconds"] = 1
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page()
            await page.clock.install(
                time=datetime.fromtimestamp(CLOCK / 1000, timezone.utc)
            )
            await page.route("**/*", state.serve)
            await page.goto("https://predict.fixture/")
            await page.locator(".mode-badge").click()
            toggle = page.get_by_role("switch", name="Live mode", exact=True)
            await expect(toggle).to_be_enabled()
            await toggle.check()
            await expect(page.locator(".mode-badge")).to_have_text("Live · Settings")
            for step in range(4):
                state.now += 400
                await page.clock.fast_forward(400)
                async with page.expect_response(
                    lambda response: response.url.endswith("/activity")
                ):
                    await page.mouse.move(15 + step * 10, 15)
            assert state.status()["mode"] == "live"
            assert (
                len(
                    [
                        request
                        for request in state.writes
                        if request[0].endswith("/activity")
                    ]
                )
                == 4
            )
            await browser.close()

    asyncio.run(journey())


def test_stationary_wheel_renews_live_but_programmatic_scroll_does_not():
    from playwright.async_api import async_playwright, expect

    async def journey():
        state = ModeFixture(owner=True)
        state.settings["inactivity_seconds"] = 1
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 900, "height": 600})
            await page.clock.install(
                time=datetime.fromtimestamp(CLOCK / 1000, timezone.utc)
            )
            await page.route("**/*", state.serve)
            await page.goto("https://predict.fixture/")
            await page.locator(".mode-badge").click()
            toggle = page.get_by_role("switch", name="Live mode", exact=True)
            await expect(toggle).to_be_enabled()
            await toggle.check()
            await expect(page.locator(".mode-badge")).to_have_text("Live · Settings")
            await page.evaluate("""() => {
                window.activityInputs=[];
                for(const type of ['pointermove','pointerdown','keydown','wheel'])
                    document.addEventListener(type,event=>window.activityInputs.push(
                        {type,trusted:event.isTrusted}),true);
            }""")
            # Keep the pointer at its current position: wheel scrolling alone
            # must keep an actively reading owner Live beyond the first deadline.
            for _ in range(3):
                state.now += 400
                await page.clock.fast_forward(400)
                async with page.expect_response(
                    lambda response: response.url.endswith("/activity"), timeout=5000
                ):
                    await page.mouse.wheel(0, 120)
            await expect(page.locator(".mode-settings-body")).not_to_have_js_property(
                "scrollTop", 0
            )
            assert state.status()["mode"] == "live"
            inputs = await page.evaluate("window.activityInputs")
            assert inputs == [{"type": "wheel", "trusted": True}] * 3
            activity_count = len(
                [
                    request
                    for request in state.writes
                    if request[0].endswith("/activity")
                ]
            )
            assert activity_count == 3
            last_activity = state.last
            state.now += 400
            await page.clock.fast_forward(400)
            await page.evaluate("""() => {
                const body=document.querySelector('.mode-settings-body');
                body.scrollTop=0;
                body.dispatchEvent(new WheelEvent('wheel',{bubbles:true,deltaY:120}));
            }""")
            await page.clock.run_for(1)
            assert state.last == last_activity
            assert (
                len(
                    [
                        request
                        for request in state.writes
                        if request[0].endswith("/activity")
                    ]
                )
                == activity_count
            )
            state.now += 1001
            await page.clock.fast_forward(1001)
            await expect(page.locator(".mode-badge")).to_have_text("Settings")
            assert state.status()["reason"] == "inactivity"
            assert state.last == last_activity
            await browser.close()

    asyncio.run(journey())
