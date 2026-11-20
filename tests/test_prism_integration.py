"""Personal appearance persistence and exact journal financial boundaries."""

from copy import deepcopy
from fractions import Fraction
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
import sqlite3
from contextlib import contextmanager, closing
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from app.dashboard.appearance_api import Appearance, DEFAULT, mount
from app.dashboard.bet_journal import Journal, Conflict
from app.dashboard.request_guard import dashboard_guard
from browser_tests.test_pregame_current import offer


class AppearanceHTTP(IsolatedAsyncioTestCase):
    async def test_invalid_saved_appearance_is_unavailable_without_overwriting_it(self):
        with TemporaryDirectory() as directory:
            store = Appearance(Path(directory) / "preferences.sqlite3")
            store.save(DEFAULT)
            with sqlite3.connect(store.path) as db:
                db.execute("UPDATE appearance SET value='not valid JSON'")
            before = store.path.read_bytes()
            app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
            mount(app, store=store)
            async with TestClient(TestServer(app)) as client:
                response = await client.get("/api/appearance")
                assert response.status == 503
                assert (await response.json())["error"] == "Local data unavailable"
            assert store.path.read_bytes() == before

    async def test_appearance_persists_for_owner_and_rejects_cross_origin_and_invalid_colors(
        self,
    ):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.sqlite3"
            store = Appearance(path)
            app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
            mount(app, store=store)
            async with TestClient(TestServer(app)) as client:
                origin = str(client.make_url("/")).rstrip("/")
                assert await (await client.get("/api/appearance")).json() == DEFAULT
                selected = dict(
                    DEFAULT, palette="custom", primary="#124578", appearance="system"
                )

                denied = await client.post(
                    "/api/appearance",
                    json=selected,
                    headers={"Origin": "https://other.invalid"},
                )
                assert denied.status == 403
                bad = await client.post(
                    "/api/appearance",
                    json=dict(selected, primary="url(https://bad.invalid)"),
                    headers={"Origin": origin},
                )
                assert bad.status == 422
                saved = await client.post(
                    "/api/appearance", json=selected, headers={"Origin": origin}
                )
                assert saved.status == 200
                assert Appearance(path).read() == selected
                assert (
                    Appearance(Path(directory) / "another-owner.sqlite3").read()
                    == DEFAULT
                )


def test_preference_reads_handle_first_save_before_its_schema_commits(tmp_path):
    store = Appearance(tmp_path / "preferences.sqlite3")
    assert store.read() == DEFAULT
    assert not store.path.exists()
    with sqlite3.connect(store.path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE appearance (singleton INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        assert store.read() == DEFAULT
    selected = dict(DEFAULT, appearance="light")
    store.save(selected)
    assert Appearance(store.path).read() == selected


def test_preference_permission_failure_is_not_an_empty_store(tmp_path, monkeypatch):
    store = Appearance(tmp_path / "preferences.sqlite3")
    original = Path.stat

    def denied(path, *args, **kwargs):
        if path == store.path:
            raise PermissionError("injected inaccessible preference path")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)
    with pytest.raises(PermissionError):
        store.read()


def test_actual_venue_fees_and_save_retries_keep_one_correction_and_original_quote(
    tmp_path,
):
    journal = Journal(tmp_path / "bets.sqlite3")
    quote = offer()
    key = journal.observe("ev", quote, manual=True)
    assert journal.observe("ev", deepcopy(quote), manual=True) == key
    original = journal.get(key)["entry"]
    change = dict(
        revision=original["revision"],
        request_id="retry-the-same-save",
        decision="placed",
        trade=dict(
            automatic=True,
            legs=[
                dict(
                    quote_id=quote["id"],
                    stake="50",
                    price="+120",
                    units="american_odds",
                    venue="fanduel",
                    entry_fee="2",
                    win_fee="0",
                    loss_fee="0",
                )
            ],
            result=dict(outcomes=["win"]),
        ),
    )
    saved = journal.update(key, change)
    assert journal.update(key, deepcopy(change)) == saved
    reopened = Journal(journal.path).get(key, history=True)
    assert reopened["entry"]["snapshot"] == quote
    assert len(reopened["history"]) == 2  # initial snapshot plus one correction
    assert reopened["entry"]["trade"]["legs"][0]["venue"] == "fanduel"
    metrics = reopened["entry"]["metrics"]
    assert Fraction(metrics["realized_profit_usd"]) == 58
    assert Fraction(metrics["realized_roi"]) == Fraction(58, 52)
    with pytest.raises(Conflict):
        journal.update(key, dict(change, notes="different request"))
    assert journal.get(key)["entry"] == saved["entry"]


def test_changed_actual_venue_requires_explicit_fees_and_cannot_rewrite_snapshot(
    tmp_path,
):
    journal = Journal(tmp_path / "bets.sqlite3")
    quote = offer()
    key = journal.observe("ev", quote, manual=True)
    revision = journal.get(key)["entry"]["revision"]
    change = dict(
        revision=revision,
        decision="placed",
        trade=dict(
            automatic=True,
            legs=[dict(quote_id=quote["id"], stake="50", venue="fanduel")],
        ),
    )
    with pytest.raises(ValueError, match="actual fees"):
        journal.update(key, change)
    for invalid in ("-2", "NaN", None):
        change["trade"]["legs"][0].update(entry_fee=invalid, win_fee="0", loss_fee="0")
        with pytest.raises(ValueError):
            journal.update(key, change)
    assert journal.get(key)["entry"]["snapshot"] == quote
    assert journal.get(key)["entry"]["trade"] is None


def test_concurrent_identical_request_ids_commit_one_correction(tmp_path):
    journal = Journal(tmp_path / "bets.sqlite3")
    key = journal.observe("ev", offer(), manual=True)
    before = journal.get(key)["entry"]
    changes = dict(
        revision=before["revision"], notes="one decision", request_id="shared-retry"
    )
    ready = Barrier(2)

    def save():
        ready.wait()
        return Journal(journal.path).update(key, changes)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: save(), range(2)))
    assert first == second
    record = journal.get(key, history=True)
    assert record["entry"]["revision"] == before["revision"] + 1
    assert len(record["history"]) == 2


def test_request_receipt_failure_rolls_back_both_correction_and_history(tmp_path):
    journal = Journal(tmp_path / "bets.sqlite3")
    key = journal.observe("ev", offer(), manual=True)
    before = journal.get(key, history=True)

    class FailedReceipt(Journal):
        @contextmanager
        def database(self, *, write=False):
            with super().database(write=write) as db:
                db.execute("""CREATE TEMP TRIGGER fail_request BEFORE INSERT ON journal_requests
                              BEGIN SELECT RAISE(ABORT, 'injected request receipt failure'); END""")
                yield db

    changes = dict(
        revision=before["entry"]["revision"],
        notes="must roll back",
        request_id="failed-receipt",
    )
    with pytest.raises(
        sqlite3.IntegrityError, match="injected request receipt failure"
    ):
        FailedReceipt(journal.path).update(key, changes)
    after = journal.get(key, history=True)
    assert after["entry"]["revision"] == before["entry"]["revision"]
    assert after["entry"]["notes"] == before["entry"]["notes"]
    assert after["history"] == before["history"]
    with journal.database() as db:
        assert db.execute("SELECT count(*) FROM journal_requests").fetchone()[0] == 0
    assert journal.update(key, changes)["entry"]["notes"] == "must roll back"


def test_prior_sqlite_schema_upgrade_and_backup_preserve_request_replay(tmp_path):
    journal = Journal(tmp_path / "before.sqlite3")
    key = journal.observe("ev", offer(), manual=True)
    before = journal.update(key, dict(revision=1, notes="existing correction"))
    # The preceding supported schema had entries/events but no request table.
    with journal.database(write=True) as db:
        db.execute("DROP TABLE journal_requests")
    reopened = Journal(journal.path)
    assert reopened.get(key)["entry"] == before["entry"]
    request = dict(revision=2, notes="new correction", request_id="durable-retry")
    committed = reopened.update(key, request)
    backup = tmp_path / "restored.sqlite3"
    with (
        closing(sqlite3.connect(journal.path)) as source,
        closing(sqlite3.connect(backup)) as destination,
    ):
        source.backup(destination)
    restored = Journal(backup)
    assert restored.update(key, request) == committed
    record = restored.get(key, history=True)
    assert record["entry"]["snapshot"] == before["entry"]["snapshot"]
    assert len(record["history"]) == 3
    restored.delete(key, committed["entry"]["revision"])
    with restored.database() as db:
        assert db.execute("SELECT count(*) FROM journal_requests").fetchone()[0] == 0


def test_appearance_browser_and_server_enforce_the_same_saved_value_contract():
    import json
    import subprocess

    from app.dashboard.appearance_policy import PALETTES, MODES, validate

    cases = [(dict(DEFAULT), True)]
    # Named palettes store colors, not names; palette display metadata is not
    # part of the durable four-field preference contract.
    for palette in PALETTES:
        for mode in MODES:
            cases.append(
                (
                    dict(
                        palette=palette["id"],
                        primary=palette["primary"],
                        secondary=palette["secondary"],
                        appearance=mode,
                    ),
                    True,
                )
            )
    cases += [
        (dict(DEFAULT, palette="custom", primary="#ABC123", appearance="system"), True),
        (dict(DEFAULT, palette="olderlabel"), True),
        ({key: value for key, value in DEFAULT.items() if key != "palette"}, False),
        (dict(DEFAULT, extra="ignored"), False),
        (dict(DEFAULT, palette=None), False),
        (dict(DEFAULT, palette=""), False),
        (dict(DEFAULT, palette="UPPER"), False),
        (dict(DEFAULT, palette="a" * 21), False),
        (dict(DEFAULT, palette="prism\n"), False),
        (dict(DEFAULT, primary="#ffffff\n"), False),
        (dict(DEFAULT, primary=" #ffffff"), False),
        (dict(DEFAULT, primary="url(https://fixture.invalid)"), False),
        (dict(DEFAULT, secondary=123456), False),
        (dict(DEFAULT, appearance="automatic"), False),
        (dict(DEFAULT, appearance=True), False),
        (None, False),
        ([], False),
        ("theme", False),
    ]
    expected = [valid for _, valid in cases]
    accepted = []
    for value, _ in cases:
        try:
            validate(value)
            accepted.append(True)
        except ValueError:
            accepted.append(False)
    assert accepted == expected
    source = (
        Path(__file__).resolve().parents[1]
        / "app/dashboard/opportunity_static/current/prism-theme.js"
    )
    script = "import {validAppearance} from " + json.dumps(source.as_uri()) + ";\n"
    script += "const cases=" + json.dumps([value for value, _ in cases]) + ";\n"
    script += "process.stdout.write(JSON.stringify(cases.map(validAppearance)));"
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == expected


def test_theme_tokens_own_accent_text_contrast_including_custom_colors():
    import json
    import subprocess

    source = (
        Path(__file__).resolve().parents[1]
        / "app/dashboard/opportunity_static/current/prism-theme.js"
    )
    script = "import {palettes,themeTokens} from " + json.dumps(source.as_uri()) + ";\n"
    script += """
    const themes=[...palettes,{primary:'#000000',secondary:'#ffffff'},{primary:'#ffffff',secondary:'#000000'}];
    const rows=[];
    for(const theme of themes)for(const appearance of ['dark','light']){
      const {tokens}=themeTokens(theme,appearance);
      rows.push({accent:tokens.accent,foreground:tokens['on-accent']});
    }
    process.stdout.write(JSON.stringify(rows));
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    def luminance(color):
        rgb = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in rgb
        ]
        return sum(
            weight * value for weight, value in zip((0.2126, 0.7152, 0.0722), linear)
        )

    rows = json.loads(result.stdout)
    assert len(rows) == 34
    for row in rows:
        assert row["foreground"] in ("#000000", "#ffffff")
        light, dark = sorted((luminance(row["accent"]), luminance(row["foreground"])))
        assert (dark + 0.05) / (light + 0.05) >= 4.5
