"""Same-workflow required gate; unexpected skips, missing jobs and failures fail."""

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
    passed, errors = evaluate(json.loads(os.environ.get("NEEDS_JSON", "{}")))
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
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(text)
    print("CI readiness: " + ("PASS" if passed else "FAIL"))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
