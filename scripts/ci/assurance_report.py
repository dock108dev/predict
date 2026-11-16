"""Keep requested assurance gates strict and intentional scope skips explicit."""

import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path

from reporting import behavior_table, run_reference, safe, step_status

SCOPES = {
    "all": {"postgres", "security"},
    "postgres": {"postgres"},
    "security": {"security"},
}
CHECKS = {
    "postgres": (
        "Migrations and transactions on disposable PostgreSQL",
        "Checks stored data and publication behavior",
        "SQL shard reports",
    ),
    "security": (
        "Refresh dependency advisory results",
        "Finds newly published advisories for locked Python packages",
        "Dependency refresh artifact",
    ),
    "health": (
        "Sample recent CI history",
        "Separates reruns, cancellations and unavailable measurements",
        "Advisory health artifact",
    ),
    "contract": (
        "Validate the requested assurance scope",
        "Keeps a missing or unexpected job from qualifying a run",
        "Workflow `needs` metadata",
    ),
}


def evaluate(scope, needs):
    if (
        scope not in SCOPES
        or not isinstance(needs, dict)
        or set(needs) != {"postgres", "security", "health"}
    ):
        return False, [
            dict(
                name="contract",
                status="FAIL",
                reason="Unknown scope or incomplete job set",
            )
        ]
    records = []
    for name in ("postgres", "security"):
        result = needs[name].get("result") if isinstance(needs[name], dict) else None
        required = name in SCOPES[scope]
        passed = result == ("success" if required else "skipped")
        records.append(
            dict(
                name=name,
                status="PASS" if passed and required else "N/A" if passed else "FAIL",
                required=required,
                job_result=result,
                reason="Requested assurance"
                if required
                else "Outside selected manual scope",
            )
        )
    health = (
        needs["health"].get("result") if isinstance(needs["health"], dict) else None
    )
    records.append(
        dict(
            name="health",
            status="ADVISORY",
            required=False,
            job_result=health,
            reason="Job execution only; sample availability and measurements are in its own report",
        )
    )
    return not any(r["status"] == "FAIL" for r in records), records


def main():
    scope = os.environ.get("ASSURANCE_SCOPE", "all")
    try:
        needs = json.loads(os.environ.get("NEEDS_JSON", "{}"))
    except ValueError:
        needs = None
    passed, records = evaluate(scope, needs)
    value = dict(
        schema=1,
        timestamp=datetime.now(timezone.utc).isoformat(),
        platform=platform.platform(),
        python=platform.python_version(),
        ref=os.environ.get("GITHUB_REF"),
        overall="PASS" if passed else "FAIL",
        scope=scope,
        checks=records,
        tested_sha=os.environ.get("GITHUB_SHA"),
        run_id=os.environ.get("GITHUB_RUN_ID"),
        run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
        event=os.environ.get("GITHUB_EVENT_NAME"),
        run_url=os.environ.get("CI_RUN_URL"),
        baseline=None,
    )
    output = Path("test-results/assurance")
    output.mkdir(parents=True, exist_ok=True)
    (output / "metrics.json").write_text(json.dumps(value, indent=2) + "\n")

    text = f"## Scheduled assurance — {value['overall']}\n\n"
    text += behavior_table(
        [
            (
                CHECKS[r["name"]][0],
                "SKIPPED (N/A)"
                if r["status"] == "N/A"
                else (
                    r["status"]
                    if r["name"] == "contract"
                    else step_status(needs, r["name"], "result")
                ),
                CHECKS[r["name"]][1],
                f"{CHECKS[r['name']][2]}. {r['reason']}.",
            )
            for r in records
        ],
        "Job outcomes apply only to the requested scope and this run. The health job conclusion describes execution. Its report identifies the history evidence available. Product tests use disposable inputs.",
    )
    text += (
        f"Scope {safe(scope)}. Tested SHA `{safe(value['tested_sha'])}`. "
        f"Event {safe(value['event'])}, ref `{safe(value['ref'])}`, attempt {safe(value['run_attempt'])}. "
        f"{run_reference()}.\n"
    )
    if not passed:
        text += "\nInspect the contract or first failed requested job in this run.\n"
    (output / "summary.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(text)
    print("Assurance: " + value["overall"])
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
