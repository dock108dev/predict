"""Clearly synthetic NCAAB ordinary-product browser harness. No network producer."""
from pathlib import Path
from aiohttp import web
from app.dashboard.multi_game_server import create_app
from tests.b5_mlb_preview import Session as BaseSession, owner as base_owner
from tests.test_b5_ncaab import coverage_fixture,reference
class Session(BaseSession):
    fixture=staticmethod(coverage_fixture)
    reference=staticmethod(reference)
    prefix='b5-ncaab-'
def owner(root):return base_owner(root,session_factory=Session)
if __name__=='__main__':
    import sys
    web.run_app(create_app(owner=owner(Path(sys.argv[1])),sessions={}),host='127.0.0.1',port=8801,access_log=None)
