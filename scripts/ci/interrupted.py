"""Retain an explicit failed report when setup never reached the offline runner."""

import html
import json
import os
from pathlib import Path


def ensure_report(output):
    path = output / "metrics.json"
    if path.exists():
        value = json.loads(path.read_text())
        if value.get("overall") not in ("PASS", "FAIL", "NOT RUN"):
            raise ValueError("Malformed offline outcome")
        if not (output / "summary.md").exists():
            raise ValueError("Required offline summary missing")
        return value["overall"] == "PASS"
    output.mkdir(parents=True, exist_ok=True)
    reason = (
        "Setup or execution interrupted before offline reporting; inspect step logs"
    )
    value = dict(
        schema=1,
        overall="FAIL",
        counts=None,
        coverage=None,
        baseline=None,
        tested_sha=os.environ.get("GITHUB_SHA"),
        event=os.environ.get("GITHUB_EVENT_NAME"),
        run_url=os.environ.get("CI_RUN_URL"),
        checks=[dict(name="offline", status="NOT RUN", reason=reason)],
    )
    path.write_text(json.dumps(value, indent=2) + "\n")
    text = (
        "## Offline contract — FAIL\n\n"
        + reason
        + ".\n\nTested SHA: "
        + html.escape(str(value["tested_sha"]))
        + ".\n"
    )
    (output / "summary.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(text)
    return False


if __name__ == "__main__":
    raise SystemExit(int(not ensure_report(Path("test-results/ci"))))
