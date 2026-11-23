"""Real Data controller navigation, bounded retries and URL-context regressions."""
from pathlib import Path
import subprocess

import pytest


ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('scenario',[
    'rapid_open', 'busy_token_read', 'busy_game_read', 'expired_token_once',
    'expired_game_once', 'direct_back_reload', 'back_during_read',
])
def test_data_navigation_request_lifecycle(scenario):
    result=subprocess.run(['node','tests/data_workspace_client.cjs',scenario],cwd=ROOT,
                          text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
