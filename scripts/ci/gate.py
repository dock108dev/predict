"""Same-workflow required gate; unexpected skips, missing jobs and failures fail."""

from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path

REQUIRED = ("offline", "quality", "postgres", "browser")


def evaluate(needs):
    if not isinstance(needs, dict) or set(needs) != set(REQUIRED):
        return False, ["Required job set is missing or unexpected"]
    errors = []
    for name in REQUIRED:
        value = needs[name]
        result = (
            value.get("result", "NOT RUN") if isinstance(value, dict) else "malformed"
        )
        if result != "success":
            errors.append(name + ": " + str(result))
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
        errors=errors,
        baseline=None,
    )
    (output / "metrics.json").write_text(json.dumps(value, indent=2) + "\n")
    text = "## CI readiness — " + ("PASS" if passed else "FAIL") + "\n\n"
    text += (
        "Tested SHA: `"
        + html.escape(os.environ.get("GITHUB_SHA", "unavailable"))
        + "`.\n\n"
    )
    text += (
        "All four required jobs succeeded."
        if passed
        else "\n".join("- " + html.escape(error) for error in errors)
    )
    text += "\n\nInspect each job summary and its run/attempt artifact; no stale scheduled result enters this gate.\n"
    (output / "summary.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(text)
    print("CI readiness: " + ("PASS" if passed else "FAIL"))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
