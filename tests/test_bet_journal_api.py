"""Real HTTP persistence, browser boundary, correction conflicts and export."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from copy import deepcopy
import json

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.dashboard.bet_journal import Journal
from app.dashboard.bet_journal_api import mount
from app.dashboard.request_guard import dashboard_guard
from browser_tests.test_pregame_current import offer


class JournalHTTP(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.journal = Journal(Path(self.directory.name) / "bets.sqlite3")
        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        mount(app, journal=self.journal, monitor=False)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.origin = str(self.client.make_url("/")).rstrip("/")

    async def asyncTearDown(self):
        await self.client.close()
        self.directory.cleanup()

    async def create(self, row=None):
        response = await self.client.post(
            "/api/bet-journal",
            json=dict(kind="ev", snapshot=row or offer()),
            headers={"Origin": self.origin},
        )
        self.assertEqual(response.status, 201, await response.text())
        return (await response.json())["entry"]

    async def test_read_only_preview_uses_saved_fee_math_without_creating_history(self):
        row = offer()
        row.update(venue="prophetx", posted=dict(value="+495", units="american_odds"))
        row["raw"].update(posted_decimal="5.95", after_fee_decimal="5.851")
        row["fee"]["evidence"] = dict(
            database_fee_rule=dict(formula="prophetx_commission", rate="0.02")
        )
        entry = await self.create(row)
        before = self.journal.get(entry["id"], history=True)
        trade = dict(
            automatic=True,
            legs=[dict(quote_id=row["id"], stake="100")],
            result=dict(outcomes=["win"]),
        )
        path = "/api/bet-journal/" + entry["id"] + "/preview"
        response = await self.client.post(
            path, json=dict(trade=trade), headers={"Origin": self.origin}
        )
        self.assertEqual(response.status, 200, await response.text())
        proposed = (await response.json())["entry"]
        self.assertEqual(proposed["trade"]["legs"][0]["price"], "495")
        self.assertEqual(
            proposed["metrics"]["legs"][0]["cashflows"]["win_receipt_usd"], "585.1"
        )
        self.assertEqual(proposed["metrics"]["realized_profit_usd"], "485.1")
        self.assertEqual(
            proposed["metrics"]["settlement"]["basis"], "reported_outcomes"
        )
        self.assertEqual(self.journal.get(entry["id"], history=True), before)
        trade["legs"][0]["stake"] = "sensitive-invalid-input"
        response = await self.client.post(
            path, json=dict(trade=trade), headers={"Origin": self.origin}
        )
        self.assertEqual(response.status, 422)
        self.assertEqual(
            (await response.json())["error"],
            "Enter valid stakes, pre-fee prices and one outcome for each leg.",
        )
        self.assertEqual(self.journal.get(entry["id"], history=True), before)
        denied = await self.client.post(path, json=dict(trade=trade))
        self.assertEqual(denied.status, 403)

    async def test_http_outcome_result_settles_and_clears_without_losing_history(self):
        row = offer()
        row.update(venue="fanduel")
        entry = await self.create(row)
        trade = dict(
            automatic=True,
            legs=[dict(quote_id=row["id"], stake="100")],
            result=dict(outcomes=["push"]),
        )
        response = await self.client.post(
            "/api/bet-journal/" + entry["id"],
            json=dict(revision=1, decision="placed", trade=trade),
            headers={"Origin": self.origin},
        )
        self.assertEqual(response.status, 200, await response.text())
        saved = (await response.json())["entry"]
        self.assertEqual(saved["metrics"]["realized_profit_usd"], "0")
        self.assertEqual(saved["trade"]["result"]["outcomes"], ["push"])
        trade["result"] = None
        response = await self.client.post(
            "/api/bet-journal/" + entry["id"],
            json=dict(revision=2, decision="placed", trade=trade),
            headers={"Origin": self.origin},
        )
        self.assertEqual(response.status, 200, await response.text())
        self.assertIsNone(
            (await response.json())["entry"]["metrics"]["realized_profit_usd"]
        )
        self.assertEqual(len(self.journal.get(entry["id"], history=True)["history"]), 3)

    async def test_save_edit_conflict_reopen_and_export(self):
        entry = await self.create()
        response = await self.client.post(
            "/api/bet-journal/" + entry["id"],
            json=dict(
                revision=1,
                decision="passed",
                notes="=unsafe spreadsheet expression",
                trade=None,
            ),
            headers={"Origin": self.origin},
        )
        self.assertEqual(response.status, 200)
        conflict = await self.client.post(
            "/api/bet-journal/" + entry["id"],
            json=dict(revision=1, notes="stale"),
            headers={"Origin": self.origin},
        )
        self.assertEqual(conflict.status, 409)
        response = await self.client.get("/api/bet-journal/" + entry["id"])
        data = await response.json()
        self.assertEqual(len(data["history"]), 2)
        self.assertEqual(data["entry"]["snapshot"], entry["snapshot"])
        export = await self.client.get("/api/bet-journal?download=json")
        self.assertEqual(
            (await export.json())["entries"][0]["history"][1]["decision"], "passed"
        )
        export = await self.client.get("/api/bet-journal?download=csv")
        self.assertIn("'=unsafe spreadsheet expression", await export.text())

    async def test_same_origin_required_and_large_snapshot_is_bounded(self):
        denied = await self.client.post(
            "/api/bet-journal", json=dict(kind="ev", snapshot=offer())
        )
        self.assertEqual(denied.status, 403)
        self.assertEqual(self.journal.list()["total"], 0)
        row = offer()
        row["fee"]["evidence"] = dict(note="fixture " * 1000)
        await self.create(row)
        oversized = await self.client.post(
            "/api/bet-journal",
            data="x" * (256 * 1024 + 1),
            headers={"Origin": self.origin, "Content-Type": "application/json"},
        )
        self.assertEqual(oversized.status, 413)

    async def test_filters_and_paging_apply_before_limiting(self):
        saved = await self.create()
        for i in range(5):
            row = offer()
            row["id"] = str(i)
            row["game_key"] = "other-" + str(i)
            self.journal.observe("ev", row)
        response = await self.client.get("/api/bet-journal?view=bets&limit=1")
        data = await response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["entries"][0]["id"], saved["id"])
        response = await self.client.get("/api/bet-journal?view=log&limit=2&offset=2")
        data = await response.json()
        self.assertEqual(data["total"], 6)
        self.assertEqual(len(data["entries"]), 2)
        response = await self.client.get("/api/bet-journal?kind=arb")
        self.assertEqual((await response.json())["total"], 0)
        response = await self.client.get("/api/bet-journal?search=Milwaukee")
        self.assertEqual((await response.json())["total"], 6)
        response = await self.client.get("/api/bet-journal/unknown")
        self.assertEqual(response.status, 404)

    async def test_invalid_read_filters_are_rejected_without_server_errors(self):
        await self.create()
        for query in (
            "limit=bad",
            "offset=Infinity",
            "view=unknown",
            "kind=other",
            "decision=other",
        ):
            with self.subTest(query=query):
                response = await self.client.get("/api/bet-journal?" + query)
                self.assertEqual(response.status, 422, await response.text())
                self.assertIn("error", await response.json())
        self.assertEqual(self.journal.list()["total"], 1)

    async def test_export_does_not_mix_revisions_during_a_concurrent_correction(self):
        entry = await self.create()
        metrics = self.journal._metrics
        changed = False

        def correction(db, row, **kwargs):
            nonlocal changed
            if not changed:
                changed = True
                writer = Journal(self.journal.path)
                # Both changes commit together: there is never a state containing
                # revision 2 without the newly inserted entry.
                with writer.database() as write:
                    write.execute(
                        "UPDATE entries SET revision=2,notes='Newer correction' WHERE id=?",
                        (entry["id"],),
                    )
                    write.execute(
                        "INSERT INTO events VALUES (?,?,?,?)",
                        (
                            entry["id"],
                            2,
                            entry["updated_at"],
                            json.dumps(
                                dict(
                                    decision="saved",
                                    notes="Newer correction",
                                    trade=None,
                                )
                            ),
                        ),
                    )
                    newer = deepcopy(entry["snapshot"])
                    newer["id"] = "concurrent-new-quote"
                    writer._observe(write, "ev", newer, manual=True)
            return metrics(db, row, **kwargs)

        with patch.object(self.journal, "_metrics", side_effect=correction):
            response = await self.client.get("/api/bet-journal?download=json")
        self.assertEqual(response.status, 200)
        records = (await response.json())["entries"]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["entry"]["revision"], 1)
        self.assertEqual([r["revision"] for r in record["history"]], [1])
        self.assertEqual(self.journal.get(entry["id"])["entry"]["revision"], 2)
        self.assertEqual(self.journal.list()["total"], 2)

    async def test_delete_checks_origin_and_revision_and_preserves_other_records(self):
        entry = await self.create()
        other = deepcopy(entry["snapshot"])
        other["id"] = "another-saved-quote"
        survivor = await self.create(other)
        self.journal.update(entry["id"], dict(revision=1, notes="Newer correction"))
        url = "/api/bet-journal/" + entry["id"]
        denied = await self.client.delete(url, json=dict(revision=2))
        self.assertEqual(denied.status, 403)
        stale = await self.client.delete(
            url, json=dict(revision=1), headers={"Origin": self.origin}
        )
        self.assertEqual(stale.status, 409)
        invalid = await self.client.delete(
            url, json=dict(revision=True), headers={"Origin": self.origin}
        )
        self.assertEqual(invalid.status, 409)
        deleted = await self.client.delete(
            url, json=dict(revision=2), headers={"Origin": self.origin}
        )
        self.assertEqual(deleted.status, 200)
        self.assertEqual(await deleted.json(), dict(deleted=True))
        self.assertEqual((await self.client.get(url)).status, 404)
        exported = await self.client.get("/api/bet-journal?download=json")
        self.assertEqual(
            [r["entry"]["id"] for r in (await exported.json())["entries"]],
            [survivor["id"]],
        )
        with self.journal.database() as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM events WHERE entry_id=?", (entry["id"],)
                ).fetchone()[0],
                0,
            )
        # Saving the same quote again is an explicit new intent, not a resurrection.
        self.assertEqual((await self.create(entry["snapshot"]))["revision"], 1)

    async def test_stake_only_placement_uses_saved_odds_and_exact_book_fees(self):
        cases = [
            (
                "novig",
                "+108",
                "100",
                dict(formula="novig_pregame", rate="0"),
                ("0", "0"),
            ),
            (
                "prophetx",
                "+110",
                "200",
                dict(formula="prophetx_commission", rate="0.02"),
                ("0", "4.4"),
            ),
            (
                "kalshi",
                "-300",
                "75",
                dict(
                    formula="kalshi_taker",
                    rate="0.07",
                    multiplier="1",
                    balance_precision="0.01",
                ),
                ("1.32", "0"),
            ),
        ]
        for venue, odds, stake, rule, fees in cases:
            with self.subTest(venue=venue):
                row = offer()
                row.update(
                    id=venue,
                    venue=venue,
                    posted=dict(value=odds, units="american_odds"),
                )
                row["fee"]["evidence"] = dict(database_fee_rule=rule)
                entry = await self.create(row)
                response = await self.client.post(
                    "/api/bet-journal/" + entry["id"],
                    json=dict(
                        revision=1,
                        decision="placed",
                        trade=dict(
                            automatic=True, legs=[dict(quote_id=venue, stake=stake)]
                        ),
                    ),
                    headers={"Origin": self.origin},
                )
                self.assertEqual(response.status, 200, await response.text())
                saved = (await response.json())["entry"]
                trade = saved["trade"]
                actual = trade["legs"][0]
                self.assertEqual((actual["entry_fee"], actual["win_fee"]), fees)
                self.assertEqual(actual["loss_fee"], "0")
                self.assertEqual(actual["fee_basis"], "saved_book_schedule")
                self.assertTrue(trade["placed_at"])
                self.assertEqual(saved["snapshot"], row)

    async def test_missing_fee_schedule_still_records_stake_without_inventing_ev(self):
        row = offer()
        # An old/incomplete pinned rule must not look like a missing record or
        # force users to type fees before they can log the stake.
        row["fee"]["evidence"] = dict(
            database_fee_rule=dict(formula="unknown", rate="0.02")
        )
        entry = await self.create(row)
        response = await self.client.post(
            "/api/bet-journal/" + entry["id"],
            json=dict(
                revision=1,
                decision="placed",
                trade=dict(
                    automatic=True,
                    legs=[dict(quote_id=entry["snapshot"]["id"], stake="100")],
                ),
            ),
            headers={"Origin": self.origin},
        )
        self.assertEqual(response.status, 200, await response.text())
        saved = (await response.json())["entry"]
        self.assertEqual(saved["trade"]["legs"][0]["fee_basis"], "unavailable")
        self.assertIsNone(saved["trade"]["legs"][0]["entry_fee"])
        self.assertIsNone(saved["metrics"]["entry_ev"])
        self.assertIsNotNone(saved["trade"]["placed_at"])
