"""Run the bounded offline contract; keep RSS-sensitive suites in fresh processes."""

import argparse
import importlib.metadata
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def junit_counts(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if not cases:
        raise ValueError("Required test report contains zero test cases")
    return {
        "tests": len(cases),
        "failed": sum(
            c.find("failure") is not None or c.find("error") is not None for c in cases
        ),
        "skipped": sum(c.find("skipped") is not None for c in cases),
        "seconds": sum(float(c.get("time", "0")) for c in cases),
    }


def execute(name, command, output, timeout=900, junit=False):
    started = time.monotonic()
    record = {"name": name, "command": command, "status": "NOT RUN", "tests": None}
    print(f"::group::{name}", flush=True)
    try:
        with (output / f"{name}.log").open("w") as log:
            result = subprocess.run(
                command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=timeout
            )
        record["exit_code"] = result.returncode
        record["status"] = "PASS" if result.returncode == 0 else "FAIL"
        if junit:
            record["tests"] = junit_counts(output / f"{name}.xml")
            if (
                record["tests"]["failed"]
                or record["tests"]["skipped"] == record["tests"]["tests"]
            ):
                record["status"] = "FAIL"
        if record["status"] == "FAIL":
            print((output / f"{name}.log").read_text()[-6000:], flush=True)
    except (OSError, ValueError, ET.ParseError, subprocess.TimeoutExpired) as error:
        record.update(status="FAIL", reason=type(error).__name__ + ": " + str(error))
        print(record["reason"], flush=True)
    record["seconds"] = round(time.monotonic() - started, 3)
    print(
        f"{name}: {record['status']} ({record['seconds']}s)\n::endgroup::", flush=True
    )
    return record


def safe(value):
    import html

    return html.escape(str(value)).replace("|", "&#124;").replace("\n", " ")


def write_report(output, records, started):
    totals = {
        k: sum(r["tests"][k] for r in records if r.get("tests"))
        for k in ("tests", "failed", "skipped")
    }
    totals["passed"] = totals["tests"] - totals["failed"] - totals["skipped"]
    overall = (
        "FAIL"
        if any(r["status"] == "FAIL" for r in records)
        else "NOT RUN"
        if any(r["status"] in ("NOT RUN", "CANCELLED") for r in records)
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
        "event": os.environ.get("GITHUB_EVENT_NAME", "local"),
        "ref": os.environ.get("GITHUB_REF"),
        "run_url": os.environ.get("CI_RUN_URL"),
        "python": sys.version,
        "platform": platform.platform(),
        "seconds": round(time.monotonic() - started, 3),
        "checks": records,
        "counts": totals,
        "coverage": None,
        "baseline": None,
    }
    try:
        report["coverage"] = json.loads((output / "coverage.json").read_text())[
            "totals"
        ]
    except (OSError, ValueError, KeyError):
        pass
    (output / "metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    summary = [
        f"## Offline contract — {overall}",
        f"Candidate: `{safe(report['tested_sha'])}`; PR head: `{safe(report['pr_head'])}`; event: {safe(report['event'])}",
        f"{safe(report['platform'])}; Python {safe(platform.python_version())}; tools: {safe(report['tools'])}",
        f"Ref: `{safe(report['ref'])}`; run: {safe(report['run_url'])}",
        f"Tests: {totals['tests']}; passed: {totals['passed']}; failed: {totals['failed']}; skipped: {totals['skipped']}. Elapsed: {report['seconds']} s.",
        "| Check | Outcome | Seconds | Reason |",
        "|---|---|---:|---|",
    ]
    summary += [
        f"| {safe(r['name'])} | {r['status']} | {r.get('seconds', 'unavailable')} | {safe(r.get('reason', ''))} |"
        for r in records
    ]
    if report["coverage"]:
        c = report["coverage"]
        summary.append(
            f"Coverage: {c['percent_covered']:.2f}% (combined line/branch); covered lines {c['covered_lines']}/{c['num_statements']}, branches {c['covered_branches']}/{c['num_branches']}. No comparable baseline yet."
        )
    summary.append(
        "Diagnostics: this run’s `ci-*` artifact (JUnit, coverage, logs, metrics). A failing check requires inspecting its log; NOT RUN requires fixing the earlier blocker. Existing optional-catalog skips are listed in JUnit. These checks do not establish live provider or owner acceptance."
    )
    text = "\n\n".join(summary[:5]) + "\n\n" + "\n".join(summary[5:]) + "\n"
    (output / "summary.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(text)


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
    commands = [
        (
            "compile",
            [sys.executable, "-m", "compileall", "-q", "app", "tests", "scripts/ci"],
            False,
        )
    ]
    for source in sorted((ROOT / "app/dashboard").rglob("*.js")):
        commands.append(
            (
                "syntax-" + source.relative_to(ROOT).as_posix().replace("/", "-"),
                ["node", "--check", str(source)],
                False,
            )
        )
    subprocess.run([sys.executable, "-m", "coverage", "erase"], cwd=ROOT, check=True)
    for group in groups:
        name = group["name"]
        commands.append(
            (
                name,
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "--cov=app",
                    "--cov-branch",
                    "--cov-append",
                    "--cov-report=",
                    f"--junitxml={output / (name + '.xml')}",
                    *group["tests"],
                ],
                True,
            )
        )
    deferred = json.loads((ROOT / "scripts/ci/browser-suites.json").read_text())[
        "deferred"
    ]
    for source in sorted((ROOT / "tests").glob("test_*.cjs")):
        if source.name in deferred:
            continue
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
        {"name": name, "status": "SKIPPED", "tests": None, "reason": reason}
        for name, reason in deferred.items()
    )
    write_report(output, records, started)
    failed = False
    for index, (name, command, junit) in enumerate(commands):
        # Continue independent suites after failures, bounded by job and process limits.
        record = execute(name, command, output, junit=junit)
        records[index] = record
        failed |= record["status"] != "PASS"
        write_report(output, records, started)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
