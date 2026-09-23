"""Ordinary dashboard over immutable B6 and prior saved packages. No Start."""
from pathlib import Path
import sys
from aiohttp import web
from app.dashboard.coverage_owner import CoverageOwner
from app.dashboard.multi_game_server import create_app
from app.dashboard import session_history

ROOT=Path(__file__).resolve().parents[1]

class SavedOwner(CoverageOwner):
    def history_paths(self):
        roots=[ROOT/'evidence/b6-offline-20260923/timed-final/sessions',
               ROOT/'evidence/b6-offline-20260923/browser/sessions',
               ROOT/'evidence/b4-pinnacle-sample-20260921/sessions']
        roots += list((ROOT/'evidence/b5-independent-20260922').glob('browser-*/sessions'))
        found=session_history.list_sessions(roots)
        folder=ROOT/'evidence/b6-offline-20260923/faults/b2-fixture'
        if folder.exists():found[folder.name]=folder
        return found
    async def start(self,**kw):raise ValueError('Read-only retained review; no collection')
    def status(self):
        value=super().status();value.update(start_available=False,pilot_allowance='Read-only retained review; no collection')
        return value

if __name__=='__main__':
    root=Path(sys.argv[1]);owner=SavedOwner(root/'legacy',pilot_output=root/'unused',product_mode=True)
    web.run_app(create_app(owner=owner,sessions={}),host='127.0.0.1',port=8818,access_log=None)
