"""Run the maintained SC04 loopback Chromium journey in the browser CI lane."""

import os
from pathlib import Path
import subprocess
import sys

import playwright


def test_sc04_browser():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(
        PYTHON=sys.executable,
        PREDICT_PLAYWRIGHT_MODULE=str(
            Path(playwright.__file__).parent / "driver/package"
        ),
        PREDICT_SC04_REPORT=str(root / "test-results/browser/sc04"),
    )
    subprocess.run(
        ["node", "browser_tests/sc04_browser.cjs"],
        cwd=root,
        env=env,
        check=True,
        timeout=240,
    )
