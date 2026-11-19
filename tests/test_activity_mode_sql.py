"""Disposable SQL owner controls do not change acquisition Stop or accounting."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from psycopg.types.json import Jsonb

from app.collection import activity_mode as mode
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_activity_mode import AT


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class ActivityModeSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        with self.connect() as db:
            db.execute(
                "UPDATE activity_mode SET mode='monitor',settings=%s,last_activity_at=NULL,live_until=NULL,revision=1,reason='default'",
                (Jsonb(mode.DEFAULT_SETTINGS),),
            )
            db.execute(
                "TRUNCATE activity_collection_run,odds_archive_stage,odds_archive_feed_status CASCADE"
            )
            db.execute("UPDATE odds_archive_usage SET staged_bytes=0")

    async def test_owner_activity_renews_only_active_live_and_passive_reads_do_not(
        self,
    ):
        with self.connect() as db:
            protected = list(
                db.execute(
                    "SELECT global_stopped,paused_sources,config FROM data_runtime"
                )
            )
        selected = mode.patch(mode="live", at=AT, connector=self.connect)
        fresh = mode.read_control(at=AT, connector=self.connect)
        assert fresh["mode"] == "live" and fresh["settings"] == selected["settings"]
        assert (
            selected["mode"] == "live"
            and selected["live_until"] == (AT + timedelta(minutes=15)).isoformat()
        )
        for minutes in (1, 2, 3):
            status = mode.read_status(
                at=AT + timedelta(minutes=minutes), connector=self.connect
            )
            assert status["last_activity_at"] == AT.isoformat()
        active = mode.activity(at=AT + timedelta(minutes=14), connector=self.connect)
        assert active["live_until"] == (AT + timedelta(minutes=29)).isoformat()
        expired = mode.activity(at=AT + timedelta(minutes=29), connector=self.connect)
        assert expired["mode"] == "monitor" and expired["reason"] == "inactivity"
        assert expired["last_activity_at"] == (AT + timedelta(minutes=14)).isoformat()
        with self.connect() as db:
            assert (
                list(
                    db.execute(
                        "SELECT global_stopped,paused_sources,config FROM data_runtime"
                    )
                )
                == protected
            )
        changed = mode.patch(
            settings={
                "monitor_interval_seconds": 300,
                "live_window_seconds": 1200,
                "inactivity_seconds": 30,
            },
            at=AT + timedelta(minutes=30),
            connector=self.connect,
        )
        assert (
            changed["mode"] == "monitor"
            and changed["settings"]["monitor_interval_seconds"] == 300
        )

    async def test_run_lifecycle_and_retention_use_sql_evidence_without_paths(self):
        with self.connect() as db:
            status = mode.read_status(db, at=AT)
            assert status["retention"]["state"] == "awaiting_first_capture"
            run = mode.begin_run(db, "monitor", status, at=AT)
            mode.update_run(
                db,
                run,
                state="budget_delayed",
                reason="operational_object_budget",
                at=AT,
            )
            waiting = mode.read_status(db, at=AT)
            assert waiting["runs"]["monitor"]["state"] == "budget_delayed"
            mode.update_run(
                db, run, state="complete", event_count=2, at=AT + timedelta(seconds=1)
            )
            assert mode.read_status(db, at=AT)["runs"]["monitor"]["event_count"] == 2
            db.execute(
                "INSERT INTO odds_archive_feed_status(feed,verified,last_verified_at,last_verified_file) VALUES('sgo',12,%s,'private-path-not-for-output')",
                (AT,),
            )
            retention = mode.read_status(db, at=AT)["retention"]
            assert (
                retention["state"] == "retaining"
                and retention["verified_observations"] == 12
            )
            assert "private" not in str(retention)
            db.execute("UPDATE odds_archive_feed_status SET skipped=1")
            assert mode.read_status(db, at=AT)["retention"]["state"] == "gaps"

    async def test_http_settings_exact_payload_and_user_activity_only(self):
        from app.dashboard.activity_mode_api import mount

        app = web.Application()
        mount(app)
        with (
            patch.object(mode, "connect", self.connect),
            patch.object(mode, "clock", return_value=AT),
        ):
            async with TestClient(TestServer(app)) as client:
                assert (await client.get("/api/admin/activity-mode")).status == 200
                selected = await client.patch(
                    "/api/admin/activity-mode", json={"mode": "live"}
                )
                assert (
                    selected.status == 200 and (await selected.json())["mode"] == "live"
                )
                assert (
                    await client.patch(
                        "/api/admin/activity-mode", json={"settings": {"unknown": 1}}
                    )
                ).status == 400
                assert (
                    await client.post(
                        "/api/admin/activity-mode/activity", json={"passive": True}
                    )
                ).status == 400
                assert (
                    await client.post("/api/admin/activity-mode/activity", json={})
                ).status == 200
                assert (await client.get("/api/admin/activity-mode")).status == 200
