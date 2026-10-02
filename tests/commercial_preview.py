"""Isolated read-only browser acceptance server; no provider or start path."""
import asyncio
from pathlib import Path
import json
from aiohttp import web
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from app.collection.transport_session import ObservationJournal
from tests.test_commercial_engineering import qualified_fixture

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'evidence/commercial-engineering-20260929/browser'
REAL=ROOT/'evidence/live-freshness-run-b2391410-91d5-4c1a-aa19-cf5c94f6ae87/b2391410-91d5-4c1a-aa19-cf5c94f6ae87'

class ReadOnly(CoverageOwner):
    async def start(self,**kwargs):raise ValueError('Read-only local acceptance preview; collection disabled')
    def status(self):return dict(super().status(),start_available=False,operating_mode='read-only-acceptance')
    def history_paths(self):return {'b2-fixture':OUTPUT/'b2-fixture',REAL.name:REAL}

async def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    folder=OUTPUT/'b2-fixture';folder.mkdir(exist_ok=True)
    if not (folder/'b2-fixture.jsonl').exists():
        j=ObservationJournal(folder/'b2-fixture.jsonl')
        for r in qualified_fixture():j.save(r)
        j.close()
    owner=ReadOnly(OUTPUT/'legacy',pilot_output=OUTPUT/'sessions',product_mode=True)
    app=create_app(owner=owner,sessions={},watch_path=OUTPUT/'watchlists.json')
    runner=web.AppRunner(app);await runner.setup();await web.TCPSite(runner,'127.0.0.1',8794).start()
    print('Read-only acceptance preview: http://127.0.0.1:8794/?capture=b2-fixture',flush=True)
    try:await asyncio.Event().wait()
    finally:await runner.cleanup()

if __name__=='__main__':asyncio.run(main())
