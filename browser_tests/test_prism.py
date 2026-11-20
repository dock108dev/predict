"""Prism interactions over disposable preference and journal stores."""

from copy import deepcopy
from urllib.parse import urlparse, parse_qs

import pytest
from playwright.sync_api import sync_playwright, expect

from app.dashboard.appearance_api import Appearance, DEFAULT
from browser_tests.journal_fixture import JournalUI, prophetx_quote


@pytest.mark.parametrize("width", [1440, 390, 320])
def test_theme_preview_cancel_persistence_failure_and_semantic_contrast(
    width, tmp_path
):
    fixture = JournalUI(tmp_path / "bets.sqlite3", prophetx_quote())
    preferences = Appearance(tmp_path / "appearance.sqlite3")
    state = dict(failed=False)

    def serve(route):
        if urlparse(route.request.url).path == "/api/appearance":
            if route.request.method == "GET":
                route.fulfill(json=preferences.read())
            elif state["failed"]:
                route.fulfill(status=503, json=dict(error="failed"))
            else:
                route.fulfill(json=preferences.save(route.request.post_data_json))
        else:
            fixture.serve(route)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport=dict(width=width, height=900), reduced_motion="reduce"
        )
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", serve)
        page.goto("https://predict.fixture/")
        page.locator(".ticket").wait_for()
        theme = page.get_by_role("button", name="Theme")
        original = page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--accent')"
        )
        theme.click()
        expect(page.locator(".theme-palette")).to_have_count(15)
        page.locator(".theme-palette", has_text="Crimson").click()
        assert (
            page.evaluate(
                "getComputedStyle(document.documentElement).getPropertyValue('--accent')"
            )
            != original
        )
        page.get_by_role("button", name="Cancel", exact=True).click()
        assert preferences.read() == DEFAULT
        assert (
            page.evaluate(
                "getComputedStyle(document.documentElement).getPropertyValue('--accent')"
            )
            == original
        )
        expect(theme).to_be_focused()
        theme.click()
        page.get_by_label("Custom primary color").fill("#101010")
        page.get_by_label("Custom secondary color").fill("#ffffff")
        page.get_by_role("combobox", name="Appearance").select_option("light")
        state["failed"] = True
        page.get_by_role("button", name="Apply theme").click()
        expect(page.locator("#theme-dialog [role=status]")).to_contain_text(
            "could not be saved"
        )
        expect(page.locator("#theme-dialog")).to_be_visible()
        assert preferences.read() == DEFAULT
        state["failed"] = False
        page.get_by_role("button", name="Apply theme").click()
        expect(page.locator("#theme-dialog")).not_to_be_visible()
        assert preferences.read()["primary"] == "#101010"
        page.evaluate("localStorage.removeItem('predict-personal-appearance-v1')")
        page.reload()
        expect(page.locator("html")).to_have_attribute("data-appearance", "light")
        if width == 1440:
            contrast = page.evaluate("""async()=>{
              const {palettes,themeTokens}=await import('/view/current/prism-theme.js');
              const lum=c=>{const v=c.slice(1).match(/../g).map(x=>{const n=parseInt(x,16)/255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4;});return .2126*v[0]+.7152*v[1]+.0722*v[2];};
              const ratio=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
              let minimum=100,boundary=100;
              for(const theme of [...palettes,{primary:'#000000',secondary:'#ffffff'},{primary:'#ffffff',secondary:'#000000'}])for(const appearance of ['dark','light']){
                const {tokens:t}=themeTokens(theme,appearance);
                minimum=Math.min(minimum,ratio(t.fg,t.surface),ratio(t.muted,t.raised),ratio(t.accent,t.raised),ratio(t.positive,t['positive-bg']),ratio(t.negative,t['negative-bg']));
                boundary=Math.min(boundary,ratio(t['control-line'],t.raised));
                if(t.positive!==(appearance==='dark'?'#b2e8ce':'#155c42'))throw Error('Palette changed positive semantics');
              }
              return {minimum,boundary};
            }""")
            assert contrast["minimum"] >= 4.5
            assert contrast["boundary"] >= 3
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert not errors
        browser.close()


@pytest.mark.parametrize("width", [1440, 390, 320])
def test_individual_picks_context_comparison_and_grouped_negative_browse(
    width, tmp_path
):
    selected = prophetx_quote()
    other = deepcopy(selected)
    other.update(
        id="b" * 64,
        bet_id="total-pick",
        family="total",
        selection=dict(predicate="over", signed_line="154.5"),
    )
    fixture = JournalUI(tmp_path / "bets.sqlite3", selected)
    state = dict(failed=False)

    def serve(route):
        url = urlparse(route.request.url)
        query = parse_qs(url.query)
        if url.path == "/api/pregame" and not query.get("mode_status"):
            if state["failed"]:
                route.fulfill(status=503, json={})
                return
            rows = [selected, other]
            if query.get("bet_id"):
                rows = [r for r in rows if r["bet_id"] == query["bet_id"][0]]
            data = dict(
                rows=rows,
                total=len(rows),
                cursor="one",
                sportsbooks=[],
                refresh_at=selected["kickoff"],
            )
            if query.get("view") == ["games"]:
                negative = deepcopy(other)
                negative["display"]["net_ev"] = "-2.10%"
                negative["raw"]["net_ev"] = "-0.021"
                data.update(
                    rows=[],
                    total=1,
                    games=[
                        dict(
                            game_key=selected["game_key"],
                            game=selected["game"],
                            league=selected["league"],
                            kickoff=selected["kickoff"],
                            rows=[selected, negative],
                        )
                    ],
                )
            route.fulfill(json=data)
        else:
            fixture.serve(route)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=dict(width=width, height=900))
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", serve)
        page.goto("https://predict.fixture/")
        expect(page.locator(".ticket")).to_have_count(2)
        expect(page.locator(".ticket .posted").first).to_contain_text(
            "Native format unavailable"
        )
        expect(page.locator("#league")).not_to_be_visible()
        page.locator(".row-open").first.click()
        expect(page.locator("#comparison")).to_be_visible()
        expect(page.locator(".selected-summary")).to_contain_text(
            "Effective after fees"
        )
        expect(page.locator(".selected-summary")).to_contain_text(
            "Fair / no-vig reference"
        )
        if width >= 1100:
            board = page.locator("#results").bounding_box()
            panel = page.locator("#comparison").bounding_box()
            assert board["x"] + board["width"] <= panel["x"]
            assert page.locator("#comparison").evaluate('e=>!e.matches(":modal")')
            page.locator(".row-open").nth(1).click()
            expect(page.locator("#comparison-title")).to_have_text("Over 154.5")
            page.set_viewport_size(dict(width=390, height=900))
            expect(page.locator("#comparison")).to_have_attribute(
                "data-presentation", "modal"
            )
            assert page.locator("#comparison").evaluate('e=>e.matches(":modal")')
            page.set_viewport_size(dict(width=1440, height=900))
            expect(page.locator("#comparison")).to_have_attribute(
                "data-presentation", "dock"
            )
            assert page.evaluate('document.body.style.position!=="fixed"')
        else:
            assert page.locator("#comparison").evaluate('e=>e.matches(":modal")')
        page.locator(".selected-summary .math-trigger").first.click()
        expect(page.locator(".math-popover:popover-open")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator(".math-popover:popover-open")).to_have_count(0)
        expect(page.locator("#comparison")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator("#comparison")).not_to_be_visible()
        expect(page.locator(".row-open").nth(1 if width >= 1100 else 0)).to_be_focused()
        if width >= 1100:
            page.locator(".game").first.click()
            expect(page.locator("#game-lines")).to_be_visible()
            page.locator("#game-lines .line-open").first.click()
            expect(page.locator("#comparison")).to_be_visible()
            expect(page.locator("dialog[open]")).to_have_count(1)
            assert page.evaluate('document.body.style.position!=="fixed"')
            page.locator("#comparison-back").click()
            expect(page.locator("#game-lines")).to_be_visible()
            expect(page.locator("dialog[open]")).to_have_count(1)
            assert page.evaluate('document.body.style.position==="fixed"')
            page.locator("#game-close").click()
            expect(page.locator("body")).not_to_have_css("position", "fixed")
        state["failed"] = True
        page.locator("#refresh").click()
        expect(page.locator("#error")).to_contain_text("preserved")
        expect(page.locator(".ticket")).to_have_count(2)
        state["failed"] = False
        page.goto("https://predict.fixture/browse-odds")
        expect(page.locator(".game-card")).to_have_count(1)
        expect(page.locator(".game-bet")).to_have_count(2)
        expect(page.locator("#results")).to_contain_text("-2.10%")
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert not errors
        browser.close()


@pytest.mark.parametrize("width", [1440, 390])
def test_record_form_draft_discard_actual_fees_and_lost_response_retry(width, tmp_path):
    fixture = JournalUI(tmp_path / "bets.sqlite3", prophetx_quote())
    state = dict(lose_response=False)
    requests = []

    def serve(route):
        path = urlparse(route.request.url).path
        if (
            state["lose_response"]
            and route.request.method == "POST"
            and path.startswith("/api/bet-journal/")
            and not path.endswith("/preview")
        ):
            state["lose_response"] = False
            requests.append(route.request.post_data_json)
            fixture.journal.update(
                path.rsplit("/", 1)[-1], route.request.post_data_json
            )
            route.abort("failed")
        else:
            fixture.serve(route)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=dict(width=width, height=900))
        page.on("dialog", lambda d: d.accept())
        page.route("**/*", serve)
        page.goto("https://predict.fixture/")
        page.locator(".row-open").click()
        page.get_by_role("button", name="Record bet", exact=True).click()
        expect(page.locator("#editor")).to_be_visible()
        expect(page.locator("[name=stake-0]")).to_have_value("")
        page.locator("#save").click()
        expect(page.locator("[name=stake-0]")).to_be_focused()
        expect(page.locator(".field-error")).to_contain_text("greater than")
        page.locator("[name=stake-0]").fill("50")
        page.get_by_text("Actual venue & fees", exact=True).click()
        page.locator("[name=actual-venue-0]").select_option("fanduel")
        for key, value in [("entry_fee", "2"), ("win_fee", "0"), ("loss_fee", "0")]:
            page.locator(f"[name={key}-0]").fill(value)
        page.locator("[name=outcome-0][value=win]").check()
        page.locator("#cancel").click()
        expect(
            page.get_by_role("button", name="Keep editing", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Keep editing", exact=True).click()
        expect(page.locator("[name=stake-0]")).to_have_value("50")
        fixture.fail_save = True
        page.locator("#save").click()
        expect(page.locator("#edit-status")).to_contain_text("retry")
        page.reload()
        expect(
            page.get_by_role("button", name="Restore draft", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Restore draft", exact=True).click()
        expect(page.locator("[name=stake-0]")).to_have_value("50")
        expect(page.locator("[name=actual-venue-0]")).to_have_value("fanduel")
        fixture.fail_save = False
        state["lose_response"] = True
        page.locator("#save").click()
        expect(page.locator("#edit-status")).to_contain_text("preserved")
        page.locator("#save").click()
        expect(page.locator("#editor")).not_to_be_visible()
        expect(page.locator(".journal-entry")).to_contain_text("$58.00")
        entry = fixture.journal.list(view="placed")["entries"][0]
        assert entry["snapshot"] == fixture.quote
        history = fixture.journal.get(entry["id"], history=True)["history"]
        assert len(history) == 2
        assert requests[0]["request_id"] == fixture.updates[-1]["request_id"]
        browser.close()
