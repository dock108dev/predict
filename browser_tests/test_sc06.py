"""SC06 actual Chromium/500-event SQL qualification; no portable substitute."""

import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4


def test_sc06_browser():
    root = Path(__file__).resolve().parents[1]
    default_report = (
        root
        / "test-results/sc06-repair/browser"
        / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid4().hex[:8]
        )
    )
    report = Path(os.environ.get("PREDICT_SC06_REPORT", default_report))
    if os.environ.get("SC06_SQL_PROVISIONED") != "1":
        subprocess.run(
            [
                sys.executable,
                "scripts/ci/postgres.py",
                "--sc06-browser",
                "--report-dir",
                str(report / "postgres"),
            ],
            cwd=root,
            env={**os.environ, "PREDICT_SC06_REPORT": str(report)},
            check=True,
            timeout=1000,
        )
        return
    import playwright

    env = os.environ.copy()
    env.update(
        PYTHON=sys.executable,
        PREDICT_PLAYWRIGHT_MODULE=str(
            Path(playwright.__file__).parent / "driver/package"
        ),
        PREDICT_SC06_REPORT=str(report),
        PREDICT_SC06_MATERIAL_FEED=env.get("PREDICT_SC06_MATERIAL_FEED", "1"),
    )
    results = []
    for suite, timeout in (("sc06_browser.cjs", 800), ("sc06_burst.cjs", 150)):
        results.append(
            subprocess.run(
                ["node", "--max-old-space-size=256", "browser_tests/" + suite],
                cwd=root,
                env=env,
                check=False,
                timeout=timeout,
            )
        )
    for result in results:
        result.check_returncode()
