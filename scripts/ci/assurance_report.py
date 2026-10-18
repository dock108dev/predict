"""Keep requested assurance gates strict and intentional scope skips explicit."""

import html
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path

SCOPES = {
    "all": {"compatibility", "postgres", "security"},
    "compatibility": {"compatibility"},
    "postgres": {"postgres"},
    "security": {"security"},
}


def evaluate(scope, needs):
    if (
        scope not in SCOPES
        or not isinstance(needs, dict)
        or set(needs) != {"compatibility", "postgres", "security", "health"}
    ):
        return False, [
            dict(
                name="contract",
                status="FAIL",
                reason="Unknown scope or incomplete job set",
            )
        ]
    records = []
    for name in ("compatibility", "postgres", "security"):
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
    passed, records = evaluate(scope, json.loads(os.environ.get("NEEDS_JSON", "{}")))
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

    def safe(value):
        return (
            html.escape(str(value))
            .replace("|", "&#124;")
            .replace("`", "&#96;")
            .replace("\n", " ")
        )

    text = f"## Scheduled assurance — {value['overall']}\n\nScope: {safe(scope)}; tested SHA: {safe(value['tested_sha'])}; run: {safe(value['run_url'])}.\n\n| Job | Outcome | Reason |\n|---|---|---|\n"
    text += "\n".join(
        f"| {r['name']} | {r['status']} | {safe(r['reason'])}; execution: {safe(r.get('job_result'))} |"
        for r in records
    )
    text += "\n\nA scheduled pass never replaces a pull-request gate. Resolve the first failed requested job; inspect its same-run artifact.\n"
    (output / "summary.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(text)
    print("Assurance: " + value["overall"])
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
