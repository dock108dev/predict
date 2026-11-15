"""Retain an explicit failed report when setup never reached the offline runner."""

import json
import os
from pathlib import Path

from reporting import behavior_table, run_reference, safe, step_status


def ensure_report(output, outcomes=None):
    path = output / "metrics.json"
    status = step_status(outcomes, "offline")
    step = next(
        (
            name
            for name in ("setup", "poppler", "offline")
            if step_status(outcomes, name) in ("FAIL", "CANCELLED")
        ),
        "offline",
    )
    reason = "Setup or execution interrupted before offline reporting"
    destination = path
    if path.exists():
        destination = output / "interruption.json"
        try:
            value = json.loads(path.read_text())
            if not isinstance(value, dict) or value.get("overall") not in (
                "PASS",
                "FAIL",
                "NOT RUN",
            ):
                raise ValueError("Malformed offline outcome")
            if not (output / "summary.md").is_file():
                raise ValueError("Required offline summary missing")
            if outcomes is None or (value["overall"] == "PASS") == (status == "PASS"):
                return value["overall"] == "PASS"
            reason = "Offline step outcome and retained report disagree"
        except (OSError, ValueError) as error:
            reason = (
                "Required offline report unreadable or malformed"
                if isinstance(error, OSError)
                else str(error)
            )
    output.mkdir(parents=True, exist_ok=True)
    value = dict(
        schema=1,
        overall="FAIL",
        counts=None,
        coverage=None,
        baseline=None,
        tested_sha=os.environ.get("GITHUB_SHA"),
        pr_head=os.environ.get("PR_HEAD_SHA"),
        merge_queue_sha=os.environ.get("MERGE_QUEUE_SHA"),
        ref=os.environ.get("GITHUB_REF"),
        event=os.environ.get("GITHUB_EVENT_NAME"),
        run_url=os.environ.get("CI_RUN_URL"),
        run_id=os.environ.get("GITHUB_RUN_ID"),
        run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
        checks=[dict(name="offline", status=status, reason=reason)],
    )
    destination.write_text(json.dumps(value, indent=2) + "\n")
    text = "## Offline contract — FAIL\n\n" + behavior_table(
        [
            (
                "Offline product and client suites",
                status if status != "PASS" else "FAIL",
                "Keeps incomplete execution from qualifying the candidate",
                reason,
            )
        ],
        "No verified final case counts or coverage are available for this execution.",
    )
    text += f"Tested SHA `{safe(value['tested_sha'])}`. Event {safe(value['event'])}. {run_reference()}. Inspect the {safe(step)} step.\n"
    (output / ("interruption.md" if destination != path else "summary.md")).write_text(
        text
    )
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(text)
    return False


if __name__ == "__main__":
    try:
        outcomes = json.loads(os.environ["CHECK_OUTCOMES"])
    except (KeyError, ValueError):
        outcomes = {}
    raise SystemExit(int(not ensure_report(Path("test-results/ci"), outcomes)))
