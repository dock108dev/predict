"""Clearly synthetic NBA ordinary-product browser harness. No network producer."""
from pathlib import Path
from aiohttp import web
from app.dashboard.multi_game_server import create_app
from tests.mlb_preview import Session as BaseSession, owner as base_owner
from tests.test_nba import fixture,reference
class Session(BaseSession):
    fixture=staticmethod(fixture)
    reference=staticmethod(reference)
    prefix='b5-nba-'
def owner(root):return base_owner(root,session_factory=Session)
if __name__=='__main__':
    import sys
    web.run_app(create_app(owner=owner(Path(sys.argv[1])),sessions={}),host='127.0.0.1',port=8799,access_log=None)
