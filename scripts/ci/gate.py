"""Same-workflow required gate; unexpected skips, missing jobs and failures fail."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from reporting import behavior_table, run_reference, safe, step_status

REQUIRED = ("offline", "quality", "postgres", "browser")
CHECKS = {
    "offline": (
        "Offline product and client suites",
        "Catches price, comparison and contract regressions",
        "Offline checks and its JUnit, coverage and client logs",
    ),
    "quality": (
        "Source validation, security and fresh package install",
        "Catches workflow errors, unsafe dependencies and missing distribution assets",
        "Source, security and package summary and artifact",
    ),
    "postgres": (
        "PostgreSQL migrations, admission and publication suites",
        "Protects durable data, current prices and rollback behavior",
        "SQL migrations and boards summaries for every shard",
    ),
    "browser": (
        "Ordinary browser and keyboard journeys",
        "Checks core tasks at desktop and mobile sizes",
        "Ordinary browser journey and its synthetic JUnit results",
    ),
}


def evaluate(needs):
    if not isinstance(needs, dict) or set(needs) != set(REQUIRED):
        return False, ["Required job set is missing or unexpected"]
    errors = []
    for name in REQUIRED:
        status = step_status(needs, name, "result")
        if status != "PASS":
            errors.append(f"{name} · {status}")
    return not errors, errors


def main():
    try:
        needs = json.loads(os.environ.get("NEEDS_JSON", "{}"))
        passed, errors = evaluate(needs)
    except ValueError:
        needs = None
        passed, errors = False, ["Required job results are malformed JSON"]
    output = Path("test-results/readiness")
    output.mkdir(parents=True, exist_ok=True)
    statuses = {name: step_status(needs, name, "result") for name in REQUIRED}
    value = dict(
        schema=1,
        overall="PASS" if passed else "FAIL",
        timestamp=datetime.now(timezone.utc).isoformat(),
        tested_sha=os.environ.get("GITHUB_SHA"),
        pr_head_sha=os.environ.get("PR_HEAD_SHA"),
        merge_queue_sha=os.environ.get("MERGE_QUEUE_SHA"),
        event=os.environ.get("GITHUB_EVENT_NAME"),
        ref=os.environ.get("GITHUB_REF"),
        run_url=os.environ.get("CI_RUN_URL"),
        run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
        checks={
            name: needs.get(name, {}).get("result", "NOT RUN")
            if isinstance(needs, dict) and isinstance(needs.get(name, {}), dict)
            else "NOT RUN"
            for name in REQUIRED
        },
        check_status=statuses,
        errors=errors,
        baseline=None,
    )
    (output / "metrics.json").write_text(json.dumps(value, indent=2) + "\n")
    text = "## CI readiness — " + value["overall"] + "\n\n"
    text += behavior_table(
        [(CHECKS[name][0], statuses[name], *CHECKS[name][1:]) for name in REQUIRED],
        "These are job conclusions. Case results and skipped cases are in the job reports. Browser and database tests use synthetic inputs. Provider coverage, installed performance and release acceptance require separate evidence.",
    )
    text += (
        f"Tested SHA `{safe(value['tested_sha'])}`. PR head `{safe(value['pr_head_sha'])}`. "
        f"Merge queue candidate `{safe(value['merge_queue_sha'])}`. Event {safe(value['event'])}, "
        f"ref `{safe(value['ref'])}`, attempt {safe(value['run_attempt'])}. {run_reference()}.\n"
    )
    if errors:
        text += (
            "\nRequired jobs to inspect in this run\n\n"
            + "\n".join("- " + safe(error) for error in errors)
            + "\n"
        )
    (output / "summary.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(text)
    print("CI readiness: " + ("PASS" if passed else "FAIL"))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
