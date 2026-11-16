"""Advisory, machine-readable evidence and an Actions summary for readiness."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import quote

from reporting import safe
from signals_context import collect, commit
from signals_evidence import (
    artifacts,
    changed_coverage,
    contract_results,
    coverage_scope,
    number,
    patch_lines,
    read_json,
    timing,
    timing_scope,
    totals,
)


COMPONENTS = {
    "Fees and settlement": (
        "app/fees/",
        "app/comparison/inspection_settlement",
        "app/comparison/snapshot_pair_fees",
    ),
    "Matching and market identity": (
        "app/matching/",
        "app/normalization/",
        "app/comparison/snapshot_identity",
    ),
    "Quote authority and desk delivery": (
        "app/dashboard/desk_",
        "app/dashboard/snapshot_api",
        "app/storage/ordinary_projection",
        "app/storage/current_native_desk",
    ),
    "Provider accounting": (
        "app/collection/sportsgameodds_ledger",
        "app/collection/accounting",
        "app/storage/aggregate_receipts",
    ),
}
SCAN_NAMES = {
    "secrets": "Publishable-tree secret scan",
    "audit": "Pinned dependencies",
    "uv_audit": "Alternate runtime lock",
}
BROWSER_PAINT = "Browser navigation to first fallback quote"
EXPECTED_TIMINGS = (
    "Selected quote HTTP read",
    "Two ordinary pages during held selection",
    BROWSER_PAINT,
    "First desk response",
    "Warm desk response",
    "Desk fallback during held SQL read",
    "Desk response after SQL resumes",
    "Desk response with SQL unavailable after app restart",
)


def artifact_for(selected, lane):
    return selected.get((lane, None), {})


def failed_checks(selected):
    failures = []
    for artifact in selected.values():
        for check in artifact["report"].get("checks", []):
            if check.get("status") != "FAIL":
                continue
            details = check.get("failing_tests") or (
                check.get("measurements") or {}
            ).get("failing_tests")
            failures.append(
                dict(
                    artifact=artifact["path"].name,
                    check=check.get("name"),
                    tests=details or [],
                )
            )
    return sorted(failures, key=lambda row: (row["artifact"], row["check"] or ""))


def coverage_metrics(root, selected, changes):
    offline = artifact_for(selected, "ci-offline")
    if not offline:
        return {}
    coverage = read_json(offline["path"] / "coverage.json")
    files, overall = coverage.get("files"), coverage.get("totals")
    if not isinstance(files, dict) or not isinstance(overall, dict):
        return {}
    components = {}
    for label, prefixes in COMPONENTS.items():
        members = [file for path, file in files.items() if path.startswith(prefixes)]
        summaries = [
            file["summary"]
            for file in members
            if isinstance(file, dict) and isinstance(file.get("summary"), dict)
        ]
        components[label] = totals(
            {
                key: sum(summary.get(key, 0) for summary in summaries)
                for key in (
                    "covered_lines",
                    "num_statements",
                    "covered_branches",
                    "num_branches",
                )
            }
        )
    report = offline["report"]
    return dict(
        totals(overall),
        scope=coverage_scope(root, report, coverage),
        offline=report.get("overall"),
        components=components,
        changed=changed_coverage(files, changes),
    )


def quality_metrics(selected):
    quality = artifact_for(selected, "ci-quality")
    if not quality:
        return {}, {}
    security = {}
    for check in quality["report"].get("checks", []):
        name = check.get("name")
        if name in SCAN_NAMES:
            metrics = check.get("measurements") or {}
            security[name] = dict(
                status=check["status"],
                **{
                    key: metrics.get(key) if type(metrics.get(key)) is int else None
                    for key in ("findings", "unavailable")
                },
            )
            if name in ("audit", "uv_audit") and security[name]["unavailable"] == 0:
                filename = "audit.json" if name == "audit" else "uv-audit.json"
                dependencies = read_json(quality["path"] / "quality" / filename).get(
                    "dependencies"
                )
                if (
                    isinstance(dependencies, list)
                    and dependencies
                    and all(
                        isinstance(dep, dict)
                        and isinstance(dep.get("name"), str)
                        and isinstance(dep.get("vulns"), list)
                        for dep in dependencies
                    )
                ):
                    ids = {
                        f"{dep['name']} · {finding['id']}"
                        for dep in dependencies
                        for finding in dep["vulns"]
                        if isinstance(finding, dict)
                        and isinstance(finding.get("id"), str)
                    }
                    if ids or security[name]["findings"] == 0:
                        security[name]["ids"] = sorted(ids)
    code = read_json(quality["path"] / "quality/code-signals.json")
    return security, code if code.get("schema") == 1 else {}


def build(root, inputs, sha, run, attempt, context):
    selected = artifacts(
        inputs, sha, run, attempt, context.get("inherited_attempts", {})
    )
    base = context["base_sha"]
    changes = patch_lines(root, base, sha)
    coverage = coverage_metrics(root, selected, changes)
    security, code = quality_metrics(selected)
    baseline = context["baseline"]
    reference = (baseline or {}).get("coverage") or {}
    comparable = bool(
        coverage.get("scope")
        and coverage["scope"] == reference.get("scope")
        and coverage.get("offline") == "PASS"
        and reference.get("offline") == "PASS"
    )
    measurements = timing(selected)
    browser = artifact_for(selected, "ci-browser")
    if browser:
        sample = read_json(browser["path"] / "desk-paint.json")
        tools = browser["report"].get("tools")
        if (
            sample.get("fixture") == "desk-browser-intercept-v1"
            and (seconds := number(sample.get("seconds"))) is not None
        ):
            measurements[BROWSER_PAINT] = dict(
                seconds=seconds,
                fixture=sample["fixture"],
                samples=1,
                artifact=browser["path"].name,
                scope=timing_scope(
                    browser,
                    "playwright",
                    tools.get("playwright") if isinstance(tools, dict) else None,
                ),
            )
    return dict(
        schema=1,
        sampled_at=datetime.now(timezone.utc).isoformat(),
        tested_sha=sha,
        run_id=run,
        run_attempt=attempt,
        requested_base_sha=base,
        baseline={key: baseline[key] for key in ("tested_sha", "run_id", "run_attempt")}
        if baseline
        else None,
        coverage_comparable=comparable,
        coverage=coverage,
        security=security,
        maintainability=code,
        changed_python_files=sorted(changes) if changes is not None else None,
        timings=measurements,
        contracts=contract_results(selected),
        failed_checks=failed_checks(selected),
        slowest_job=context["slowest"],
        health=(context["health"] or {}).get("events", {}),
        artifacts=sorted(entry["path"].name for entry in selected.values()),
        reused_artifacts=sorted(
            entry["path"].name
            for entry in selected.values()
            if str(entry["attempt"]) != str(attempt)
        ),
    )


def fraction(metric):
    if not metric or metric["percent"] is None:
        return "—"
    return f"{metric['percent']:.1f}% ({metric['covered']:,}/{metric['total']:,})"


def change_label(current, previous):
    if (
        current
        and previous
        and current["percent"] is not None
        and previous["percent"] is not None
    ):
        return f"{current['percent'] - previous['percent']:+.2f} pp vs base"
    return "—"


def source_location(path, line, sha):
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    label = safe(f"{path}:{line}")
    if commit(sha) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return f"[{label}](https://github.com/{repo}/blob/{sha}/{quote(path)}#L{line})"
    return label


def render(value, baseline):
    text = [
        "### Validation signals",
        "",
        "Advisory measurements. Required job conclusions determine CI readiness.",
        f"Exact comparison base `{safe(value['requested_base_sha'])}`. "
        + (
            "Successful base artifact found."
            if value["baseline"]
            else "Comparable base artifact unavailable."
        ),
        "",
        "#### Critical fixture checks",
        "",
        "| Behavior | Outcome | Evidence |",
        "|---|---|---|",
    ]
    for label, row in value["contracts"].items():
        cases = [case for item in row["evidence"] for case in item["cases"]]
        gaps = [
            item["test"].split("::")[-1]
            for item in row["evidence"]
            if not item["cases"]
        ]
        failures = [case["case"] for case in cases if case["status"] != "PASS"]
        detail = f"{len(cases)} JUnit case" + ("s" if len(cases) != 1 else "")
        if gaps or failures:
            detail += " · " + ", ".join(
                [*(f"Missing {name}" for name in gaps), *failures][:4]
            )
        text.append(f"| {safe(label)} | **{row['status']}** | {safe(detail)} |")
    if value["failed_checks"]:
        text += ["", "#### Failed checks to inspect", ""]
        for failure in value["failed_checks"][:6]:
            tests = ", ".join(failure["tests"][:3])
            extra = f" · {safe(tests)}" if tests else ""
            text.append(
                f"- {safe(failure['artifact'])} · {safe(failure['check'])}{extra}"
            )

    current = value["coverage"]
    reference = (
        (baseline or {}).get("coverage", {}) if value["coverage_comparable"] else {}
    )
    text += [
        "",
        "#### Python coverage",
        "",
        "| Scope | Lines | Branches | Lines vs base | Branches vs base |",
        "|---|---:|---:|---:|---:|",
    ]
    changed = current.get("changed")
    for label, counts, base in [
        ("Offline suite", current, reference),
        *(
            (label, counts, reference.get("components", {}).get(label, {}))
            for label, counts in current.get("components", {}).items()
        ),
        ("Changed executable code", changed or {}, {}),
    ]:
        text.append(
            "| "
            + " | ".join(
                (
                    safe(label),
                    *(fraction(counts.get(k)) for k in ("lines", "branches")),
                    *(
                        change_label(counts.get(k), base.get(k))
                        for k in ("lines", "branches")
                    ),
                )
            )
            + " |"
        )
    if changed is None:
        text.append(
            "\nChanged-code coverage unavailable without an exact diff and coverage report."
        )
    elif changed["unmeasured"]:
        text.append(
            f"\n{len(changed['unmeasured'])} changed Python files have no instrumentation record."
        )
    elif not changed["lines"]["total"]:
        text.append("\nThis diff has no measured executable Python lines.")
    if current and current.get("offline") != "PASS":
        text.append(
            "\nCoverage came from an unsuccessful offline suite. Deltas are withheld."
        )
    elif current and value["baseline"] and not value["coverage_comparable"]:
        text.append(
            "\nThe base and candidate have different measurement scope or tools. Deltas are withheld."
        )
    if changed:
        hotspots = sorted(
            changed["files"],
            key=lambda row: len(row["missing_lines"]) + len(row["missing_branches"]),
            reverse=True,
        )
        for row in hotspots[:5]:
            if not (row["missing_lines"] or row["missing_branches"]):
                continue
            line = (
                row["missing_lines"] or [arc[0] for arc in row["missing_branches"]]
            )[0]
            link = source_location(row["path"], line, value["tested_sha"])
            text.append(
                f"\n- {link} · {len(row['missing_lines'])} missed changed lines, {len(row['missing_branches'])} missed branch exits"
            )

    previous = (baseline or {}).get("timings", {})
    text += [
        "",
        "#### Performance and recovery",
        "",
        "| Measurement | Seconds | Δ vs base | Evidence |",
        "|---|---:|---:|---|",
    ]
    for name in EXPECTED_TIMINGS:
        now, old = value["timings"].get(name), previous.get(name)
        if not now:
            text.append(f"| {name} | — | — | Unavailable |")
            continue
        comparable_timing = (
            isinstance(old, dict)
            and number(old.get("seconds")) is not None
            and now.get("scope")
            and all(
                now.get(key) == old.get(key)
                for key in ("fixture", "response_budget", "samples", "scope")
            )
        )
        delt = f"{now['seconds'] - old['seconds']:+.3f}" if comparable_timing else "—"
        detail = f"{now['fixture']} · n={now['samples']}"
        if now.get("response_budget") is not None:
            detail += f" · test response budget {now['response_budget']:g} s"
        text.append(f"| {name} | {now['seconds']:.3f} | {delt} | {safe(detail)} |")

    text += [
        "",
        "Timing samples use disposable or intercepted fixtures. Deltas require matching fixtures, sample counts, runner class and toolchain.",
        "",
        "#### Security and maintainability",
        "",
        "| Scan | Outcome | Findings | New vs base | Unavailable dependencies |",
        "|---|---|---:|---:|---:|",
    ]
    for name, label in SCAN_NAMES.items():
        scan = value["security"].get(name, {})
        prior = (baseline or {}).get("security", {}).get(name, {})
        new = (
            len(set(scan["ids"]) - set(prior["ids"]))
            if "ids" in scan and "ids" in prior
            else "—"
        )
        text.append(
            f"| {label} | {safe(scan.get('status'))} | {safe(scan.get('findings'))} | {new} | {safe(scan.get('unavailable'))} |"
        )
    text.append(
        "\nDependency findings can change as advisory databases update. Severity is unavailable in these reports. CodeQL and Dependabot retain their own results."
    )
    code = value["maintainability"]
    if code:
        groups, complexity = code["duplicates"], code["complexity"]
        text.append(
            f"\nPython app code has **{len(groups)} exact duplicate body groups** across "
            f"{code['eligible_functions']:,} eligible functions and **{len(complexity)} Ruff C901 findings**."
        )
        old = (baseline or {}).get("maintainability") or {}
        if old.get("schema") == code["schema"]:
            text.append(
                f" Base had {len(old['duplicates'])} duplicate groups and {len(old['complexity'])} C901 findings."
            )
        affected = [
            member
            for group in groups
            for member in group["functions"]
            if member["path"] in (value["changed_python_files"] or [])
        ]
        affected_c901 = [
            item
            for item in complexity
            if item["path"] in (value["changed_python_files"] or [])
        ]
        if value["changed_python_files"] is not None:
            text.append(
                f" Changed files contain {len(affected)} duplicate functions and {len(affected_c901)} C901 findings."
            )
        for member in (affected + affected_c901)[:5]:
            link = source_location(member["path"], member["line"], value["tested_sha"])
            text.append(
                f"\n- {link} · {safe(member.get('message', 'Exact duplicate body'))}"
            )
        text.append(
            "\nExact duplicate bodies use Python syntax trees and at least five statements. Ruff uses its default McCabe threshold."
        )
    else:
        text.append("\nPython duplication and complexity evidence unavailable.")

    text += ["", "#### CI health", ""]
    if job := value["slowest_job"]:
        text.append(
            f"Slowest completed job in this run was **{safe(job['name'])}** at {job['seconds']:.0f} s ({safe(job['conclusion'])})."
        )
    else:
        text.append("Slowest completed job unavailable.")
    for key, label in (("pull_request", "Pull requests"), ("push", "Pushes")):
        sample = value["health"].get(key, {})
        rate = sample.get("first_attempt_pass_rate")
        if rate is not None:
            text.append(
                f"\n{label} had **{rate:.0%} first-attempt success** across "
                f"{sample['first_attempt_observed']} observed first attempts in the recent 30-day sample. "
                f"Rerun first attempts unavailable here: {sample['unavailable_first_attempts']}."
            )
        elif value["health"]:
            text.append(f"\n{label} first-attempt pass rate unavailable in the sample.")
    if not value["health"]:
        text.append("\nFirst-attempt history unavailable.")
    text += [
        "",
        "Prior attempts contribute evidence only for jobs GitHub reports as inherited. A missing report for a rerun job leaves its case evidence unavailable.",
        (
            "Inherited reports: "
            + ", ".join(map(safe, value["reused_artifacts"]))
            + "."
            if value["reused_artifacts"]
            else "No inherited reports were used."
        ),
        "Full case identities, coverage gaps, timing samples and source artifacts are indexed in `signals.json`.",
        "Coverage measures the offline Python instrumentation. Fixture checks measure the cases listed above.",
        "",
    ]
    return "\n".join(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inputs", type=Path, default=Path("test-results/signals-inputs/current")
    )
    parser.add_argument("--output", type=Path, default=Path("test-results/readiness"))
    args = parser.parse_args()
    sha, run, attempt = (
        os.environ.get(key)
        for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")
    )
    root = Path.cwd()
    context = collect(root, sha, run, args.inputs.parent / "base")
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    value = build(root, args.inputs, sha, run, attempt, context)
    (output / "signals.json").write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n"
    )
    text = render(value, context["baseline"])
    for path in [
        output / "summary.md",
        *(
            [Path(os.environ["GITHUB_STEP_SUMMARY"])]
            if os.environ.get("GITHUB_STEP_SUMMARY")
            else []
        ),
    ]:
        with path.open("a") as stream:
            stream.write("\n" + text)
    print(text)


if __name__ == "__main__":
    main()
