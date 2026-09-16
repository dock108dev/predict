from pathlib import Path
from unittest.mock import patch
from aiohttp import web
from tests.personal_beta_mock import owner,verify_local_replay
from app.dashboard.multi_game_server import create_app
if __name__=='__main__':
    out=Path('evidence/concise-dashboard/local-sessions');out.mkdir(exist_ok=True)
    with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials forbidden')),patch('app.collection.native_replay.verify_native_saved',verify_local_replay):
        web.run_app(create_app(owner=owner(out)),host='127.0.0.1',port=8785,access_log=None)
