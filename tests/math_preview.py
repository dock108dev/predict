"""Read-only ordinary app preview, isolated from all retained evidence."""
import asyncio
from pathlib import Path
from aiohttp import web
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from tests.test_aggregate_ingestion import FOLDER

async def main():
    root=Path('evidence/math-package-20260929/browser')
    class Owner(CoverageOwner):
        def history_paths(self):return {FOLDER.name:FOLDER}
        async def start(self,**kwargs):raise ValueError('Read-only mathematical verification; collection disabled')
        def status(self):return dict(super().status(),start_available=False)
    owner=Owner(root/'legacy',pilot_output=root/'sessions',product_mode=True)
    runner=web.AppRunner(create_app(owner=owner,sessions={},watch_path=root/'watches.json'))
    await runner.setup();await web.TCPSite(runner,'127.0.0.1',8797).start()
    print('http://127.0.0.1:8797/?capture='+FOLDER.name,flush=True)
    try:await asyncio.Event().wait()
    finally:await runner.cleanup()

if __name__=='__main__':asyncio.run(main())
