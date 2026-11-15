"""Run the bounded offline contract; keep RSS-sensitive suites in fresh processes."""

import argparse
import importlib.metadata
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import tempfile
import xml.etree.ElementTree as ET

from reporting import (
    behavior_table,
    case_id,
    case_status,
    junit as read_junit,
    run_reference,
    safe,
)

ROOT = Path(__file__).resolve().parents[2]


def coverage_totals(path):
    value = json.loads(path.read_text())["totals"]
    for name in ("covered_lines", "num_statements", "covered_branches", "num_branches"):
        if type(value[name]) is not int or value[name] < 0:
            raise ValueError("Invalid coverage count")
    if (
        not value["num_statements"]
        or value["covered_lines"] > value["num_statements"]
        or value["covered_branches"] > value["num_branches"]
    ):
        raise ValueError("Empty or conflicting coverage counts")
    percent = value["percent_covered"]
    if (
        type(percent) not in (int, float)
        or not math.isfinite(percent)
        or not 0 <= percent <= 100
    ):
        raise ValueError("Invalid coverage percentage")
    return value


def junit_counts(path):
    return read_junit(path)[1]


def require_client_report(path):
    if not re.search(r"\bpass(?:ed)?\b", path.read_text(), re.I):
        raise ValueError(
            "Required client suite has no completion result; empty execution cannot pass"
        )


def execute(name, command, output, timeout=300, junit=False):
    started = time.monotonic()
    record = {"name": name, "command": command, "status": "NOT RUN", "tests": None}
    print(f"::group::{name}", flush=True)
    try:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("PG") and key != "PREDICT_DB_SOCKET"
        }
        # Client fixtures must use this locked interpreter, including in a clean
        # hosted checkout with no developer .venv directory.
        environment["PYTHON"] = sys.executable
        environment["PREDICT_CI_ISOLATED_ROOT"] = str(ROOT)
        environment["PREDICT_CI_REPORT_ROOT"] = str(output)
        environment["PYTHONPATH"] = (
            str(ROOT / "scripts/ci") + os.pathsep + environment.get("PYTHONPATH", "")
        )
        environment["NODE_OPTIONS"] = (
            environment.get("NODE_OPTIONS", "")
            + " --require "
            + str(ROOT / "scripts/ci/node-isolation.cjs")
        ).strip()
        # Pytest otherwise shares a per-user temporary root with unrelated
        # checkouts and may prune another project's retained test directories.
        with (
            tempfile.TemporaryDirectory(prefix="predict-ci-check-") as temporary,
            (output / f"{name}.log").open("w") as log,
        ):
            socket = str(Path(temporary) / "no-postgres")
            environment.update(
                TMPDIR=temporary,
                TEMP=temporary,
                TMP=temporary,
                PREDICT_DB_SOCKET=socket,
                PGHOST=socket,
            )
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        record["exit_code"] = result.returncode
        record["status"] = "PASS" if result.returncode == 0 else "FAIL"
        if junit:
            cases, record["tests"], record["junit_declared"] = read_junit(
                output / f"{name}.xml"
            )
            record["failing_tests"] = [
                case_id(case) for case in cases if case_status(case) == "FAIL"
            ][:10]
            if (
                record["tests"]["failed"]
                or record["tests"]["skipped"] == record["tests"]["tests"]
            ):
                record["status"] = "FAIL"
        if (
            record["status"] == "PASS"
            and command[0] == "node"
            and command[1].endswith((".cjs", ".mjs"))
        ):
            require_client_report(output / f"{name}.log")
        if record["status"] == "PASS" and name == "coverage-json":
            coverage_totals(output / "coverage.json")
        if record["status"] == "PASS" and name == "coverage-xml":
            tree = ET.parse(output / "coverage.xml").getroot()
            if tree.tag != "coverage" or int(tree.attrib["lines-valid"]) <= 0:
                raise ValueError("Required coverage XML is empty or malformed")
        if record["status"] == "FAIL":
            print((output / f"{name}.log").read_text()[-6000:], flush=True)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ET.ParseError,
        subprocess.TimeoutExpired,
    ) as error:
        record.update(status="FAIL", reason=type(error).__name__ + ": " + str(error))
        print(record["reason"], flush=True)
    record["seconds"] = round(time.monotonic() - started, 3)
    print(
        f"{name}: {record['status']} ({record['seconds']}s)\n::endgroup::", flush=True
    )
    return record


def write_report(output, records, started):
    required = [r for r in records if r.get("required", True)]
    totals = {
        k: sum(r["tests"][k] for r in records if r.get("tests"))
        for k in ("tests", "failed", "skipped")
    }
    totals["passed"] = totals["tests"] - totals["failed"] - totals["skipped"]
    overall = (
        "FAIL"
        if not required
        or any(r["status"] in ("FAIL", "SKIPPED", "CANCELLED") for r in required)
        else "NOT RUN"
        if any(r["status"] == "NOT RUN" for r in required)
        else "PASS"
    )
    report = {
        "overall": overall,
        "schema": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tools": {
            name: importlib.metadata.version(name)
            for name in ("pytest", "pytest-cov", "coverage")
        },
        "tested_sha": os.environ.get("GITHUB_SHA"),
        "pr_head": os.environ.get("PR_HEAD_SHA"),
        "merge_queue_sha": os.environ.get("MERGE_QUEUE_SHA"),
        "event": os.environ.get("GITHUB_EVENT_NAME", "local"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "ref": os.environ.get("GITHUB_REF"),
        "run_url": os.environ.get("CI_RUN_URL"),
        "python": sys.version,
        "platform": platform.platform(),
        "seconds": round(time.monotonic() - started, 3),
        "checks": records,
        "counts": totals if any(r.get("tests") for r in records) else None,
        "coverage": None,
        "baseline": None,
    }
    try:
        report["coverage"] = coverage_totals(output / "coverage.json")
    except (OSError, ValueError, KeyError, TypeError) as error:
        for record in records:
            if record["name"] == "coverage-json" and record["status"] == "PASS":
                record.update(
                    status="FAIL",
                    reason="Required coverage unavailable: " + type(error).__name__,
                )
                report["overall"] = "FAIL"
                overall = "FAIL"
    (output / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    fee_checks = [
        r
        for r in records
        if r["name"].startswith("ordinary-fee-coverage__")
        or r["name"] == "test_f07_desk_ui"
    ]
    sgo_checks = [
        r
        for r in records
        if r["name"].startswith("sportsgameodds__") or r["name"] == "test_sgo_drawer"
    ]
    scanner_checks = [
        r for r in records if r["name"].startswith("scanner-native-finance__")
    ]
    behavior = []
    for checks, title, purpose, evidence in (
        (
            fee_checks,
            "Fee applicability, renewal, rounding and coverage",
            "Keeps unsupported fees out of current estimates and preserves the denominator",
            "Fixtures and simulated HTTP. Check results below.",
        ),
        (
            sgo_checks,
            "SportsGameOdds collection, recovery and reference qualification",
            "Protects budget holds, original prices and the exact inputs used in EV",
            "Fixtures and simulated HTTP. Check results below.",
        ),
        (
            scanner_checks,
            "Scanner venue fees, payout terms and observed-depth allocation",
            "Keeps unbound venue terms out of estimates and unknown terminal cashflows out of ranked results",
            "Authored receipts and allocation. See `scanner-native-finance__*.xml` in this run’s artifact.",
        ),
    ):
        if not checks:
            continue
        outcomes = {r["status"] for r in checks}
        if any(
            (r.get("tests") or {}).get("skipped")
            or r.get("junit_declared", {}).get("skipped")
            for r in checks
        ):
            outcomes.add("SKIPPED")
        behavior.append((title, " / ".join(sorted(outcomes)), purpose, evidence))
    if not behavior:
        behavior.append(
            (
                "Offline suite as configured",
                overall,
                "Surfaces contract failures before integration",
                "Metrics and check details below",
            )
        )
    summary = [
        f"## Offline contract — {overall}",
        f"Candidate: `{safe(report['tested_sha'])}`; PR head: `{safe(report['pr_head'])}`; event: {safe(report['event'])}",
        f"{safe(report['platform'])}; Python {safe(platform.python_version())}; tools: {safe(report['tools'])}",
        f"Ref: `{safe(report['ref'])}`; {run_reference()}; merge queue candidate: `{safe(report['merge_queue_sha'])}`",
        (
            f"JUnit case records: {totals['tests']}; passed: {totals['passed']}; failed: {totals['failed']}; skipped: {totals['skipped']}."
            if report["counts"] is not None
            else "JUnit case counts unavailable."
        )
        + f" Elapsed: {report['seconds']} s.",
        "| Check | Outcome | Seconds | Reason |",
        "|---|---|---:|---|",
    ]
    summary += [
        f"| {safe(r['name'])} | {r['status']} | {r.get('seconds', 'unavailable')} | {safe(r.get('reason', ''))} |"
        for r in records
    ]
    failing = [test for record in records for test in record.get("failing_tests", [])][
        :10
    ]
    if failing:
        summary.append(
            "\nFirst failing case records: "
            + ", ".join(f"`{safe(test)}`" for test in failing)
            + "."
        )
    if report["coverage"]:
        c = report["coverage"]
        summary.append(
            f"Coverage: {c['percent_covered']:.2f}% (combined line/branch); covered lines {c['covered_lines']}/{c['num_statements']}, branches {c['covered_branches']}/{c['num_branches']}. No comparable baseline yet."
        )
    summary.append(
        "Diagnostics: this run’s `ci-*` artifact (JUnit, coverage, logs, metrics). A failing check requires inspecting its log; NOT RUN requires fixing the earlier blocker. Existing optional-catalog skips are listed in JUnit. These checks do not establish live provider or owner acceptance."
    )
    text = (
        summary[0]
        + "\n\n"
        + behavior_table(
            behavior,
            "Provider collection, live fee renewal and installed full-slate publication require separate validation. JUnit case records do not include a separate row for every subtest. Explicit archive exclusions are listed below.",
        )
    )
    text += "\n\n".join(summary[1:4]) + "\n\n"
    text += "### Why these tests ran\n\nThis command runs the registered offline suites in fresh processes. No changed-file selection or cached test outcome enters this report.\n\n"
    text += summary[4] + "\n\n" + "\n".join(summary[5:]) + "\n"
    (output / "summary.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        # The command file belongs to this step. Replace progress snapshots so
        # repeated updates cannot overflow GitHub's 1 MiB summary limit.
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(text)
    return overall


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="test-results/ci")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        parser.error(
            "Use an empty report directory; stale reports must never qualify this run"
        )
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    groups = json.loads((ROOT / "scripts/ci/suites.json").read_text())
    policy = json.loads((ROOT / "scripts/ci/python-policy.json").read_text())
    commands = [
        (
            "suite-contract",
            [sys.executable, "scripts/ci/validate_contract.py"],
            False,
        ),
        (
            "compile",
            [sys.executable, "-m", "compileall", "-q", "app", "tests", "scripts/ci"],
            False,
        ),
    ]
    for source in sorted((ROOT / "app/dashboard").rglob("*.js")):
        commands.append(
            (
                "syntax-" + source.relative_to(ROOT).as_posix().replace("/", "-"),
                ["node", "--check", str(source)],
                False,
            )
        )
    # Each invocation owns its coverage DB; parallel/local checks cannot erase
    # or inherit a prior measurement from the checkout.
    os.environ["COVERAGE_FILE"] = str(output / ".coverage")
    for group in groups:
        for source in group["tests"]:
            name = group["name"] + "__" + Path(source).stem
            commands.append(
                (
                    name,
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        "--tb=short",
                        "-o",
                        "faulthandler_timeout=30",
                        "--cov=app",
                        "--cov-branch",
                        "--cov-append",
                        "--cov-report=",
                        f"--junitxml={output / (name + '.xml')}",
                        *[
                            "--deselect=" + node
                            for node in policy["archival_nodes"]
                            if node.split("::")[0] == source
                        ],
                        source,
                    ],
                    True,
                )
            )
    browser = json.loads((ROOT / "scripts/ci/browser-suites.json").read_text())
    for name in browser["required"]:
        source = ROOT / "tests" / name
        commands.append((source.stem, ["node", str(source)], False))
    commands += [
        (
            "coverage-json",
            [
                sys.executable,
                "-m",
                "coverage",
                "json",
                "-o",
                str(output / "coverage.json"),
            ],
            False,
        ),
        (
            "coverage-xml",
            [
                sys.executable,
                "-m",
                "coverage",
                "xml",
                "-o",
                str(output / "coverage.xml"),
            ],
            False,
        ),
    ]
    records = [
        {
            "name": name,
            "status": "NOT RUN",
            "tests": None,
            "reason": "Runner has not reached this check",
        }
        for name, _, _ in commands
    ]
    records.extend(
        {
            "name": name,
            "status": "SKIPPED",
            "required": False,
            "tests": None,
            "reason": reason,
        }
        for name, reason in browser["deferred"].items()
    )
    records.extend(
        {
            "name": name,
            "status": "SKIPPED",
            "required": False,
            "tests": None,
            "reason": reason,
        }
        for name, reason in {**policy["deferred"], **policy["archival_nodes"]}.items()
    )
    write_report(output, records, started)
    for index, (name, command, junit) in enumerate(commands):
        # Continue independent suites after failures, bounded by job and process limits.
        record = execute(name, command, output, junit=junit)
        records[index] = record
        overall = write_report(output, records, started)
    failed = overall != "PASS"
    failures = [r for r in records if r["status"] == "FAIL"]
    print(
        f"Offline contract: {'FAIL' if failed else 'PASS'}; {len(failures)} failed checks",
        flush=True,
    )
    for record in failures:
        print(
            f"FAIL: {record['name']} — inspect {output / (record['name'] + '.log')}",
            flush=True,
        )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
