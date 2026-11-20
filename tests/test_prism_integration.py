"""Persistence and financial boundaries introduced by the approved UI handoff."""

from copy import deepcopy
from fractions import Fraction
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from app.dashboard.appearance_api import Appearance, DEFAULT, mount
from app.dashboard.bet_journal import Journal, Conflict
from app.dashboard.request_guard import dashboard_guard
from browser_tests.test_pregame_current import offer


class AppearanceHTTP(IsolatedAsyncioTestCase):
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
