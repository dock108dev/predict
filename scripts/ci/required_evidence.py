"""Fail-closed readiness evidence, bound to the run, candidate and job attempt."""

import json
from pathlib import Path
import re
import subprocess
from xml.etree.ElementTree import ParseError

from reporting import junit
from signals_context import actions, inherited_artifact_attempts
from signals_evidence import artifacts

# These are the established CI lanes, independently of any local test selector.
EXPECTED = {
    ("ci-quality", None): "quality",
    ("ci-offline", None): "offline",
    ("ci-browser", None): "browser",
    **{("storage", str(index)): "postgres" for index in range(1, 5)},
}
QUALITY_CHECKS = {
    "source",
    "audit",
    "uv_audit",
    "package",
    "lint",
    "workflow",
    "docs",
    "secrets",
}
ROOT = Path(__file__).resolve().parents[2]


def offline_inventory():
    groups = json.loads((ROOT / "scripts/ci/suites.json").read_text())
    browser = json.loads((ROOT / "scripts/ci/browser-suites.json").read_text())
    policy = json.loads((ROOT / "scripts/ci/python-policy.json").read_text())
    required = {"suite-contract", "compile", "coverage-json", "coverage-xml"}
    required.update(
        group["name"] + "__" + Path(source).stem
        for group in groups
        for source in group["tests"]
    )
    required.update(
        "syntax-" + path.relative_to(ROOT).as_posix().replace("/", "-")
        for path in (ROOT / "app/dashboard").rglob("*.js")
    )
    required.update(Path(name).stem for name in browser["required"])
    optional = (
        set(browser["deferred"])
        | set(policy["deferred"])
        | set(policy["archival_nodes"])
    )
    return required, optional


def inherited(repo, run, attempt):
    """Query only on partial reruns; unavailable/truncated history grants no reuse."""
    if attempt == "1":
        return {}
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Repository identity unavailable for rerun evidence")
    data = actions(repo, f"runs/{run}/jobs", filter="latest", per_page=100)
    if not isinstance(data, dict):
        raise ValueError("Rerun job inventory is malformed")
    jobs = data.get("jobs")
    if (
        not isinstance(jobs, list)
        or data.get("total_count") != len(jobs)
        or any(not isinstance(job, dict) for job in jobs)
    ):
        raise ValueError("Rerun job inventory missing or truncated")
    return inherited_artifact_attempts(data, run, attempt)


def passing_junit(path):
    _, counts, _ = junit(path)
    if counts["tests"] <= 0 or counts["failed"] or counts["skipped"] == counts["tests"]:
        raise ValueError("JUnit has failed or no executed cases")
    return counts


def validate(artifact, lane, shard):
    report, path = artifact["report"], artifact["path"]
    if (
        type(report.get("schema")) is not int
        or report["schema"] != 1
        or report.get("overall") != "PASS"
    ):
        raise ValueError("Required report is malformed or did not pass")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("Required report has no checks")
    if any(not isinstance(check, dict) for check in checks):
        raise ValueError("Required check record is malformed")
    names = [check.get("name") for check in checks]
    if any(not isinstance(name, str) or not name for name in names) or len(
        set(names)
    ) != len(names):
        raise ValueError("Required check names missing or duplicated")
    required = set(names)
    if lane == "ci-offline":
        required, optional = offline_inventory()
        if not required <= set(names) or set(names) - required - optional:
            raise ValueError(
                "Registered offline check inventory is incomplete or unexpected"
            )
    for check in checks:
        if check["name"] in required and (
            check.get("required", True) is not True or check.get("status") != "PASS"
        ):
            raise ValueError("Required check did not pass: " + check["name"])
    if lane == "ci-quality":
        if set(names) != QUALITY_CHECKS:
            raise ValueError("Quality check inventory changed or incomplete")
        passing_junit(path / "quality/junit.xml")
    elif lane in {"ci-browser", "storage"}:
        if names != ["browser" if lane == "ci-browser" else "postgres"]:
            raise ValueError("Behavior report check inventory is incomplete")
        passing_junit(path / "junit.xml")
        if lane == "storage":
            toolchain = json.loads((path / "toolchain.json").read_text())
            if not isinstance(toolchain, dict) or (
                toolchain.get("shard_index"),
                toolchain.get("shard_count"),
                toolchain.get("suite"),
            ) != (int(shard), 4, "registered-sql"):
                raise ValueError("SQL shard identity or registered suite differs")
    else:
        measured = 0
        for check in checks:
            if check.get("required", True) is False:
                continue
            name = check["name"]
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                raise ValueError("Unsafe offline check name")
            if "__" in name:
                counts = passing_junit(path / (name + ".xml"))
                reported = check.get("tests")
                if not isinstance(reported, dict) or any(
                    reported.get(key) != counts[key]
                    for key in ("tests", "failed", "skipped")
                ):
                    raise ValueError("Offline counts differ from JUnit")
                measured += counts["tests"]
        if measured <= 0:
            raise ValueError("Offline report contains no executed suites")


def evaluate(root, sha, run, attempt, repo, fetch_inherited=inherited):
    errors, selected = [], {}
    if not re.fullmatch(r"[0-9a-f]{40}", sha or "") or not all(
        re.fullmatch(r"[1-9][0-9]*", str(value or "")) for value in (run, attempt)
    ):
        return ["Required evidence candidate/run identity is unavailable"], {}
    current = artifacts(root, sha, run, attempt, {})
    reuse = {}
    # Complete current-attempt evidence needs no API access, even on a full rerun.
    if set(current) != set(EXPECTED) and str(attempt) != "1":
        try:
            reuse = fetch_inherited(repo, run, str(attempt))
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            errors.append(
                "Retained successful jobs could not be verified; no older evidence reused"
            )
    # A current report, even malformed, must never be hidden by older success
    # (including when the API inventory lags artifact publication).
    reuse = dict(reuse)
    for lane, shard in EXPECTED:
        name = f"{lane}-{run}-{attempt}" + (f"-{shard}" if shard else "")
        if (root / name).exists():
            reuse.pop((lane, shard), None)
    selected = artifacts(root, sha, run, attempt, reuse)
    if set(selected) != set(EXPECTED):
        errors.append("Required artifact/shard inventory is missing or unexpected")
    validity = {}
    for key, artifact in selected.items():
        validity[key] = "PASS"
        try:
            validate(artifact, *key)
        except (OSError, ValueError, KeyError, TypeError, ParseError) as error:
            validity[key] = "FAIL"
            errors.append(f"{artifact['path'].name}: {error}")
    return errors, {
        key[0] + ("-" + key[1] if key[1] else ""): dict(
            artifact=value["path"].name,
            attempt=value["attempt"],
            lane=EXPECTED.get(key),
            status=validity[key],
        )
        for key, value in selected.items()
    }
