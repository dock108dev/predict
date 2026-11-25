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
            monitor_phase_seconds=1200,
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
            effective_mode="monitor",
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
                    json=dict(
                        changed=q.get("after") not in (None, str(self.revision)),
                        activity_mode=self.status(),
                    )
                )
                return
            self.reads.append((url.path, q))
            kind = q.get("data_type") or (
                "all" if q.get("browse") == "1" else self.status()["effective_mode"]
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


def test_settings_can_retry_stop_after_watchdog_revokes_dispatch():
    from playwright.async_api import async_playwright, expect

    async def journey():
        mode = ModeFixture(owner=True)
        requests = []
        status = dict(
            dispatch_enabled=False,
            cleanup_complete=False,
            cleanup_errors=["source_publication_cleanup_failed"],
            config={"enabled": True},
            service_state="blocked",
            recovery={"reason": "cleanup_safety_unresolved"},
            data_runtime={"healthy": True},
        )

        async def serve(route):
            path = urlparse(route.request.url).path
            if path == "/settings":
                await route.fulfill(path=ASSETS / "settings.html")
            elif path == "/api/admin/status":
                await route.fulfill(json=status)
            elif path == "/api/admin/current":
                requests.append(route.request.post_data_json)
                if len(requests) == 1:
                    await route.fulfill(
                        status=409,
                        json={
                            "reason": "Acquisition is withdrawn. Retry Stop to confirm cleanup."
                        },
                    )
                else:
                    status.update(
                        cleanup_complete=True,
                        cleanup_errors=[],
                        service_state="stopped",
                        recovery={},
                    )
                    await route.fulfill(json=status)
            elif path.startswith("/api/") and path != "/api/admin/activity-mode":
                await route.fulfill(status=503, json={"error": "fixture_not_available"})
            else:
                await mode.serve(route)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page()
            await page.route("**/*", serve)
            await page.goto("https://predict.fixture/settings")
            retry = page.get_by_role("button", name="Retry Stop")
            await expect(retry).to_be_visible()
            await expect(page.locator("#collection-state")).to_contain_text(
                "Stop cleanup unconfirmed"
            )
            async with page.expect_response("**/api/admin/current") as failed:
                await retry.click()
            assert (await failed.value).status == 409
            await expect(retry).to_be_enabled()
            await retry.click()
            await expect(page.locator("#control-result")).to_have_text(
                "Collection stopped. Stored data remains available."
            )
            await expect(retry).to_have_count(0)
            assert requests == [{"action": "stop"}, {"action": "stop"}]
            await browser.close()

    asyncio.run(journey())


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
                page.get_by_role("button", name="Save settings", exact=True)
            ).to_be_disabled()
            await expect(
                page.get_by_label("Discovery interval (minutes)", exact=True)
            ).to_be_disabled()
            await expect(
                page.get_by_label("Discovery timing offset (minutes)", exact=True)
            ).to_be_disabled()
            assert state.authorizations == 1 and not state.writes
            await expect(
                page.locator(".mode-run-summary:not(#mode-monitor-schedule)")
            ).to_contain_text("waiting for budget")
            await expect(
                page.locator(".mode-run-summary:not(#mode-monitor-schedule)")
            ).to_contain_text("partial update")
            await expect(page.locator('a[href*="dataset=practice"]')).to_have_count(0)
            await expect(page.locator("[data-caution]")).to_have_count(0)
            assert not errors, errors
            await browser.close()

    asyncio.run(journey())


@pytest.mark.parametrize("width", [1280, 390])
def test_owner_discovery_settings_survive_passive_refresh(width):
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
            field = page.get_by_label("Discovery interval (minutes)", exact=True)
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
                monitor_phase_seconds=1200,
                monitor_horizon_seconds=86400,
                live_interval_seconds=60,
                live_window_seconds=3600,
                inactivity_seconds=900,
            )
            assert state.writes == [
                (
                    "/api/admin/activity-mode",
                    {
                        "settings": {
                            "monitor_interval_seconds": 2700,
                            "monitor_phase_seconds": 1200,
                            "monitor_horizon_seconds": 86400,
                        }
                    },
                )
            ]
            state.now += 15001
            await page.clock.fast_forward(15001)
            await expect(field).to_have_value("45")
            await page.mouse.move(20, 20)
            # Same-tab navigation re-verifies permission through a read.
            async with page.expect_response("**/api/admin/activity-mode"):
                await page.goto("https://predict.fixture/browse-odds")
            await expect(page.locator(".mode-badge")).to_have_text("Settings")
            assert state.authorizations >= 2
            assert len(state.writes) == 1
            assert state.status()["mode"] == "monitor"
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
            async with page.expect_response(
                lambda response: (
                    "bet_id=" in response.url and "data_type=monitor" in response.url
                )
            ):
                await page.clock.fast_forward(501)
            await expect(
                page.locator('#results .row-open[data-quote-id="monitor-quote"]')
            ).to_have_count(1)
            await expect(page.locator(".mode-badge")).to_have_text("Settings")
            await expect(
                page.locator(".exchange-prices tbody td").nth(1)
            ).to_contain_text("45.45%")
            await expect(page.locator(".exchange-prices")).not_to_contain_text("38.46%")
            assert all(
                q.get("data_type") == "monitor"
                for _, q in state.reads[prior_reads:]
                if q.get("bet_id")
            )
            await expect(page.locator(".collection-badge")).to_have_count(0)
            await page.get_by_role("button", name="Close comparison").tap()
            await page.locator("#board-advanced > summary").tap()
            await page.locator("#data-type").select_option("live")
            await expect(
                page.locator('#results .row-open[data-quote-id="live-quote"]')
            ).to_have_count(1)
            await expect(page.locator("#results .posted .math-trigger")).to_have_text(
                "38.46%"
            )
            await page.locator(".row-open").tap()
            await expect(page.locator(".comparison-status")).to_contain_text("complete")
            await expect(
                page.locator(".exchange-prices tbody td").nth(1)
            ).to_contain_text("38.46%")
            assert state.reads[-1][1]["data_type"] == "live"
            await page.get_by_role("button", name="Close comparison").tap()
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


@pytest.mark.parametrize("gesture", ["pointer", "wheel-and-scroll"])
def test_passive_input_does_not_renew_legacy_live_or_change_monitor_evidence(gesture):
    from playwright.async_api import async_playwright, expect

    async def journey():
        state = ModeFixture(owner=True, mode="live")
        state.settings["inactivity_seconds"] = 1
        original_activity = state.status()["last_activity_at"]
        monitor = state.rows("monitor")[0]
        requests = []
        viewport = (
            {"width": 390, "height": 360}
            if gesture == "wheel-and-scroll"
            else {"width": 900, "height": 600}
        )
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport=viewport)
            await page.clock.install(
                time=datetime.fromtimestamp(CLOCK / 1000, timezone.utc)
            )
            page.on("request", lambda request: requests.append(request))
            await page.route("**/*", state.serve)
            await page.goto("https://predict.fixture/")
            row = page.locator('.ticket[data-quote-id="monitor-quote"]')
            await expect(row.locator(".posted .math-trigger")).to_have_text("45.45%")
            await page.locator(".mode-badge").click()
            await expect(
                page.get_by_role("button", name="Save settings")
            ).to_be_enabled()
            assert state.status()["mode"] == "live"
            assert state.authorizations == 1

            body = page.locator(".mode-settings-body")
            event_type = "pointermove" if gesture == "pointer" else "wheel"
            if gesture == "wheel-and-scroll":
                assert await body.evaluate(
                    "body => body.scrollHeight > body.clientHeight"
                )
                await body.hover(position={"x": 40, "y": 80})
            await page.evaluate(
                """type => {
                window.inputTrust = [];
                document.addEventListener(type, event => inputTrust.push(event.isTrusted), true);
            }""",
                event_type,
            )
            for step in range(3):
                state.now += 400
                await page.clock.fast_forward(400)
                if gesture == "pointer":
                    await page.mouse.move(15 + step * 10, 15)
                else:
                    await page.mouse.wheel(0, 120)
                await page.wait_for_function(
                    "count => inputTrust.length >= count", arg=step + 1
                )
            assert await page.evaluate("inputTrust") == [True] * 3
            if gesture == "wheel-and-scroll":
                await expect(body).not_to_have_js_property("scrollTop", 0)
                await body.evaluate("""body => {
                    body.scrollTop = 0;
                    body.dispatchEvent(new WheelEvent('wheel', {bubbles: true, deltaY: 120}));
                }""")
                await expect(body).to_have_js_property("scrollTop", 0)
                assert await page.evaluate("inputTrust") == [True, True, True, False]

            async with page.expect_response("**/api/pregame/updates?*") as polled:
                await page.clock.fast_forward(501)
            packet = await (await polled.value).json()
            activity = packet["activity_mode"]
            assert activity["requested_mode"] == "live"
            assert activity["mode"] == activity["effective_mode"] == "monitor"
            assert activity["reason"] == "inactivity"
            assert activity["last_activity_at"] == original_activity
            assert activity["revision"] == 1
            await expect(page.locator(".mode-badge")).to_have_text("Settings")

            await page.get_by_role("button", name="Close collection settings").click()
            await row.locator(".row-open").click()
            comparison = page.locator("#comparison")
            await expect(comparison.locator(".comparison-status")).to_contain_text(
                "complete"
            )
            await expect(comparison.locator(".exchange-prices")).to_contain_text(
                "45.45%"
            )
            evidence = comparison.locator(".calculation-evidence")
            await evidence.get_by_text("Fee and calculation details").click()
            source_time = evidence.locator('dt:text-is("Source timestamp") + dd')
            await expect(source_time).to_have_text(monitor["times"]["source_at"])
            assert state.reads[-1][1]["data_type"] == "monitor"
            assert state.writes == []

            passive_apis = {
                "/api/appearance",
                "/api/admin/activity-mode",
                "/api/pregame",
                "/api/pregame/updates",
            }
            assert requests
            for request in requests:
                address = urlparse(request.url)
                assert (address.netloc, request.method) == ("predict.fixture", "GET"), (
                    request.url
                )
                if address.path.startswith("/api/"):
                    assert address.path in passive_apis, request.url
            await browser.close()

    asyncio.run(journey())


@pytest.mark.parametrize("width", [390, 1280])
def test_monitor_wall_clock_phase_display_configuration_and_zero_offset(width):
    from playwright.async_api import async_playwright, expect

    class ScheduledFixture(ModeFixture):
        def status(self):
            status = super().status()
            # Authoritative API targets for this fixed 12:31 UTC scenario. The
            # backend's boundary tests own scheduling math; this checks that the
            # UI renders that status and sends offsets in seconds correctly.
            status["next_monitor_at"] = {
                1200: iso(CLOCK + 20 * 60000),
                300: iso(CLOCK + 5 * 60000),
                0: iso(CLOCK + 30 * 60000),
            }[self.settings["monitor_phase_seconds"]]
            return status

    async def journey():
        state = ScheduledFixture(owner=True)
        state.now = CLOCK + 60000
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": width, "height": 844})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.clock.install(
                time=datetime.fromtimestamp(state.now / 1000, timezone.utc)
            )
            await page.route("**/*", state.serve)
            await page.goto("https://predict.fixture/")
            await page.locator(".mode-badge").click()
            phase = page.get_by_label("Discovery timing offset (minutes)", exact=True)
            await expect(phase).to_be_enabled()
            await expect(phase).to_have_value("20")
            await expect(
                page.get_by_label("Discovery timing offset slider", exact=True)
            ).to_have_value("20")
            summary = page.locator(".mode-summary:not(#mode-acquisition-policy)")
            await expect(summary).to_have_text(
                "24/7 discovery · starts at :20 and :50 each hour"
            )
            next_start = page.locator("#mode-monitor-schedule")
            await expect(next_start).to_contain_text("7:50 AM EST")
            save = page.get_by_role("button", name="Save settings", exact=True)
            close = page.get_by_role(
                "button", name="Close collection settings", exact=True
            )
            original_y = [
                (control, (await control.bounding_box())["y"])
                for control in (save, close)
            ]
            await page.locator(".mode-settings-body").evaluate(
                "body=>body.scrollTop=body.scrollHeight"
            )
            for control, y in original_y:
                box = await control.bounding_box()
                assert abs(box["y"] - y) < 1
                assert 0 <= box["y"] and box["y"] + box["height"] <= 844
            await phase.fill("5")
            state.now += 15001
            await page.clock.fast_forward(15001)
            await expect(phase).to_have_value("5")
            # Unsaved input survives polling, but cannot claim a changed target.
            await expect(next_start).to_contain_text("7:50 AM EST")
            await save.click()
            await expect(page.locator(".mode-message")).to_contain_text("saved")
            assert state.settings["monitor_phase_seconds"] == 300
            assert state.settings["monitor_interval_seconds"] == 1800
            await expect(summary).to_have_text(
                "24/7 discovery · starts at :05 and :35 each hour"
            )
            await expect(next_start).to_contain_text("7:35 AM EST")
            await phase.fill("0")
            async with page.expect_response(
                lambda response: response.request.method == "PATCH"
            ):
                await save.click()
            await expect(phase).to_have_value("0")
            assert state.settings["monitor_phase_seconds"] == 0
            await expect(summary).to_have_text(
                "24/7 discovery · starts at :00 and :30 each hour"
            )
            await expect(next_start).to_contain_text("8:00 AM EST")
            assert len(state.writes) == 2
            assert [
                body["settings"]["monitor_phase_seconds"] for _, body in state.writes
            ] == [300, 0]
            assert all(
                path == "/api/admin/activity-mode" and set(body) == {"settings"}
                for path, body in state.writes
            )
            assert state.mode == "monitor"
            await close.click()
            await expect(page.locator("#mode-settings")).not_to_be_visible()
            await expect(page.locator(".mode-badge")).to_be_focused()
            assert not errors, errors
            await browser.close()

    asyncio.run(journey())
