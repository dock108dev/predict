"""The signed-in workspace serves immutable result exports through passive reads."""

import asyncio
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.dashboard.request_guard import dashboard_guard
from app.dashboard.research_workspace_api import BASE, mount
from app.dashboard.workspace_routes import compatibility_middleware, mount as mount_workspace
from app.storage.store import hashed


def test_result_status_history_and_exact_variant_exports():
    run, latest, older, evidence = (character * 64 for character in "abce")
    url = f"{BASE}/runs/{run}/results"
    statements = []
    game = dict(game_id="game", evidence_id=evidence)
    missing = dict(game_id="missing", evidence_id=evidence, capture_status="missed")
    trade = dict(id="trade", state="loss", evidence_id=evidence)
    totals = dict(tickets=1, pnl_usd="-1.00")
    old_report = dict(games=[game, missing], portfolios={
        "best_venue": dict(by_game={"game": dict(tickets=0), "missing": dict(tickets=0)}, tickets=[]),
        "all_venues": dict(by_game={"game": totals, "missing": dict(tickets=0)}, tickets=[trade]),
    })

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def transaction(self):
            return nullcontext()

        def execute(self, statement, parameters=()):
            statements.append(statement)
            if parameters:
                assert parameters == (run,)
                self.campaign = "JOIN public.research_workspace_definition" in statement
                return self

        def fetchone(self):
            if self.campaign:
                return None
            return dict(id=run, report_revision="d" * 64, game_date=date(2026, 11, 23),
                        paper=True, policy=dict(execution="paper_only"))

    def read_queue(_db, run_id, *, result_id, status_only):
        assert run_id == run
        if result_id not in (None, latest, older):
            raise KeyError(result_id)
        return dict(state="graded", latest_result_id=latest, pending=True,
                    versions=[dict(id=latest), dict(id=older)], version=dict(id=result_id or latest),
                    report=None if status_only else old_report)

    async def check():
        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        mount(app)
        with patch("app.dashboard.research_workspace_api.connect", side_effect=Connection), \
                patch("app.dashboard.paper_results_view.paper_result_queue.read", side_effect=read_queue):
            async with TestClient(TestServer(app)) as client:
                response = await client.get(url + "?status=1")
                assert response.status == 200
                value = await response.json()
                assert value["status"]["stale"]
                assert value["status"]["state"] == "update_pending"
                assert value["status"]["latest_version"] == latest
                assert value["report"] is None
                assert (await client.get(url + "?export=report")).status == 409
                assert (await client.get(url + "?version=" + "f" * 64)).status == 404
                assert (await client.get(url + "?status=1&status=1")).status == 422
                assert (await client.get(url + "?variant=combined")).status == 422

                response = await client.get(url + f"?version={older}&variant=all_venues")
                history = await response.json()
                assert history["version"]["id"] == older and history["report"] == old_report
                assert history["provider_requests"] == history["orders_submitted"] == 0
                for kind in ("report", "games", "trades"):
                    response = await client.get(history["links"][kind])
                    assert response.status == 200
                    assert f'{older[:12]}-{kind}.json' in response.headers["Content-Disposition"]
                    exported = await response.json()
                    assert exported["version"]["id"] == older
                    assert exported["variant"] == "all_venues"
                    assert exported.pop("manifest")["bundle_sha256"] == hashed(exported)
                    if kind == "report":
                        assert exported["report"] == old_report
                    elif kind == "games":
                        assert exported["rows"] == [dict(game, totals=totals), dict(missing, totals=None)]
                    else:
                        assert exported["rows"] == [trade]
                assert statements.count("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY") == 7

    asyncio.run(check())


def test_direct_paper_game_and_trade_links_open_experiments():
    async def check():
        root = Path(__file__).resolve().parents[1] / "app/dashboard"
        app = web.Application(middlewares=[compatibility_middleware()])
        mount_workspace(app, root)
        query = "?section=experiments&run=paper-run&game=paper-game&trade=ticket&result=version"
        async with TestClient(TestServer(app)) as client:
            entered = await client.get("/research" + query, allow_redirects=False)
            destination = "/experiments" + query.replace("section=experiments&", "")
            assert entered.status == 302 and entered.headers["Location"] == destination
            followed = await client.get(destination)
            assert followed.status == 200 and 'id="experiments-main"' in await followed.text()
            slash = await client.get("/research/" + query, allow_redirects=False)
            assert slash.status == 302 and slash.headers["Location"] == destination
            legacy = await client.get("/research?game=legacy-catalog-game", allow_redirects=False)
            assert legacy.status == 302
            assert legacy.headers["Location"] == "/data?game=legacy-catalog-game"

    asyncio.run(check())
