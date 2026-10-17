"""Actual SC05 browser journey; portable authored finance, SQL in postgres lane."""

import os
from pathlib import Path
import subprocess
import sys

import playwright


def test_sc05_browser():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(
        PYTHON=sys.executable,
        PREDICT_PLAYWRIGHT_MODULE=str(
            Path(playwright.__file__).parent / "driver/package"
        ),
        PREDICT_SC05_REPORT=str(root / "test-results/browser/sc05"),
        SC05_PORTABLE="1",
    )
    subprocess.run(
        ["node", "browser_tests/sc05_browser.cjs"],
        cwd=root,
        env=env,
        check=True,
        timeout=240,
    )
