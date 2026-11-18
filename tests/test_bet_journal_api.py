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
