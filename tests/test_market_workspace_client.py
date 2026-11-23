"""Exercise the real market renderer without provider access or owner state."""
from pathlib import Path
import subprocess


def test_market_offer_evidence_journey():
    result = subprocess.run(['node', 'tests/market_workspace_client.cjs'],
                            cwd=Path(__file__).resolve().parents[1],
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
