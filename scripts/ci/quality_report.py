"""Render fixed-schema tool reports without evaluating report contents."""

import importlib.metadata
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import sys
import xml.etree.ElementTree as ET

from reporting import (
    behavior_table,
    case_id,
    case_status,
    junit,
    run_reference,
    safe,
    step_status,
)


BROWSER_BEHAVIOR = (
    (
        "Setup and first use without credentials",
        "Keeps ordinary pages accessible on desktop and mobile",
        "browser_tests.test_first_run",
        (
            "test_first_use_without_credentials[1440]",
            "test_first_use_without_credentials[390]",
        ),
    ),
    (
        "Ranked odds remain in place as prices refresh",
        "Preserves the reader’s place and inspection while newer prices arrive",
        "browser_tests.test_ranked_opportunities",
        (
            "test_ev_updates_prices_without_reranking_or_displacing_a_reader[1440]",
            "test_ev_updates_prices_without_reranking_or_displacing_a_reader[390]",
        ),
    ),
    (
        "Fee desk, pinned details and Admin at desktop and mobile widths",
        "Keeps fee assumptions, recovery notices and coverage visible",
        "browser_tests.test_fee_desk",
        ("test_ordinary_fee_desk[1440]", "test_ordinary_fee_desk[390]"),
    ),
)

STORAGE_BEHAVIOR = (
    (
        "Pregame sportsbook EV is withdrawn at kickoff with Live off",
        "Keeps started games out of the pregame desk while preserving captured inputs",
        "tests.test_sportsgameodds_ingress_sql.SportsGameOddsPregameDeskSQL",
        (
            "test_admitted_pregame_estimates_rank_before_publication_and_leave_at_kickoff",
        ),
    ),
    (
        "Retry a settled page after SQL timeout without fetching it again",
        "Prevents duplicate provider calls and partial writes on admission retry",
        "tests.test_sportsgameodds_ingress_sql.SportsGameOddsAtomicIngress",
        (
            "test_sql_timeout_after_frame_retries_the_settled_page_without_another_request",
        ),
    ),
    (
        "Archive staging rolls back with admission and preserves exact quotes",
        "Protects retained odds from partial writes and redundant observations",
        "tests.test_odds_archive_sql",
        ("test_stage_rolls_back_with_admission_and_compacts_unchanged_quotes",),
    ),
    (
        "Signed-format Novig admission, withdrawal and frozen detail",
        "Keeps current stream authority separate from retained fee evidence",
        "tests.test_novig_current_admission.NovigCurrentAdmission",
        (
            "test_signed_source_ingress_fee_and_archive_survive_disconnect_without_legacy_ev",
        ),
    ),
)

CHECK_BEHAVIOR = {
    "source": (
        "CI reporter failure and recovery tests",
        "Keeps missing, failed and skipped reports visible",
    ),
    "audit": (
        "Vulnerability scan of Python CI and browser locks",
        "Finds reported advisories or unavailable package evidence",
    ),
    "uv_audit": (
        "Vulnerability scan of the alternate runtime lock",
        "Covers locked runtime inputs used outside CI’s primary installer",
    ),
    "package": (
        "Fresh wheel build, isolated install and app startup",
        "Exposes missing tracked code, migrations and UI assets",
    ),
    "lint": (
        "Source lint and CI support formatting",
        "Catches invalid names and unsupported source patterns",
    ),
    "workflow": (
        "Actions-aware workflow and shell validation",
        "Catches invalid trigger, expression and orchestration configuration",
    ),
    "docs": (
        "Maintained documentation links",
        "Keeps commands and in-repository references usable",
    ),
    "secrets": (
        "Redacted publishable-tree secret scan",
        "Detects suspicious credentials without including their values",
    ),
}


def case_behavior(cases, scenarios, report_name, step):
    rows = []
    for title, purpose, module, names in scenarios:
        outcomes = set()
        for name in names:
            matches = [
                case_status(case)
                for case in cases
                if case.get("classname") == module and case.get("name") == name
            ]
            outcomes.update(
                ["FAIL"]
                if len(matches) > 1
                else matches
                or [step if step in ("SKIPPED", "CANCELLED") else "NOT RUN"]
            )
        identifiers = ", ".join(f"{module}::{name}" for name in names)
        rows.append(
            (
                title,
                " / ".join(sorted(outcomes)),
                purpose,
                f"{report_name} · {identifiers}",
            )
        )
    return rows


def unproven_browser_cases(cases):
    outcomes = defaultdict(list)
    for case in cases:
        outcomes[case.get("classname"), case.get("name")].append(case_status(case))
    return [
        name
        for _, _, module, names in BROWSER_BEHAVIOR
        for name in names
        if outcomes.get((module, name)) != ["PASS"]
    ]


def read(path, expected):
    value = json.loads(path.read_text())
    if not isinstance(value, expected):
        raise ValueError("Unexpected report schema")
    return value


def render(
    outcomes,
    root,
    postgres=False,
    package=False,
    expanded=False,
    audit=False,
    browser=False,
):
    required = (
        {"browser": root / "browser/junit.xml"}
        if browser
        else {"audit": root / "quality/audit.json"}
        if audit
        else {"package": root / "package/metrics.json"}
        if package
        else {"postgres": root / "postgres/junit.xml"}
        if postgres
        else {
            "source": root / "quality/junit.xml",
            "audit": root / "quality/audit.json",
            "package": root / "package/metrics.json",
        }
    )
    if expanded or audit:
        required["uv_audit"] = root / "quality/uv-audit.json"
    if expanded:
        required.update(
            lint=None,
            workflow=None,
            docs=None,
            secrets=root / "quality/secret-metrics.json",
        )
    records = []
    errors = []
    cases = []
    for name, path in required.items():
        status = step_status(outcomes, name)
        record = {"name": name, "status": status, "measurements": None}
        try:
            if name == "postgres" and (path.parent / "failure.json").exists():
                failure = read(path.parent / "failure.json", dict)
                raise ValueError(failure["reason"])
            if path is None:
                pass  # Exit status is the evidence for source/static checks.
            elif path.suffix == ".xml":
                cases, counts, declared = junit(path)
                record["measurements"] = {
                    **counts,
                    "passed": counts["tests"] - counts["failed"] - counts["skipped"],
                    "junit_declared": declared,
                    "failing_tests": [
                        case_id(case) for case in cases if case_status(case) == "FAIL"
                    ][:10],
                }
                if counts["failed"] or counts["skipped"] == len(cases):
                    raise ValueError("failed or entirely skipped suite")
                if (
                    browser
                    and status == "PASS"
                    and (unproven := unproven_browser_cases(cases))
                ):
                    raise ValueError(
                        "Required browser cases missing, skipped or duplicated: "
                        + ", ".join(unproven)
                    )
            elif name in ("audit", "uv_audit"):
                data = read(path, dict)
                deps = data["dependencies"]
                if not isinstance(deps, list) or not deps:
                    raise ValueError("empty dependency report")
                if any(
                    not isinstance(d, dict)
                    or not isinstance(d.get("name"), str)
                    or not d.get("name")
                    or ("skip_reason" not in d and not isinstance(d.get("vulns"), list))
                    for d in deps
                ):
                    raise ValueError("missing or malformed dependency findings")
                findings = sum(len(d["vulns"]) for d in deps if "vulns" in d)
                unavailable = sum("skip_reason" in d for d in deps)
                record["measurements"] = {
                    "dependencies": len(deps),
                    "findings": findings,
                    "unavailable": unavailable,
                    "severity": "PyPI API does not consistently supply severity",
                }
                if findings or unavailable:
                    raise ValueError("vulnerabilities or unavailable dependencies")
            elif name == "secrets":
                data = read(path, dict)
                record["measurements"] = data
                if (
                    data.get("status") != "PASS"
                    or type(data.get("findings")) is not int
                    or data["findings"] != 0
                ):
                    raise ValueError(
                        data.get("reason")
                        or "Secret findings or unavailable scan evidence"
                    )
                record["measurements"] = data
            else:
                data = read(path, dict)
                if (
                    data["status"] != "PASS"
                    or type(data["wheel_bytes"]) is not int
                    or data["wheel_bytes"] <= 0
                ):
                    raise ValueError("invalid build measurement")
                record["measurements"] = data
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
            record["reason"] = str(error)
            if status == "PASS":
                record["status"] = "FAIL"
            errors.append(name)
        if status != "PASS":
            errors.append(name)
            record.setdefault("reason", "Required job step did not succeed")
        records.append(record)

    def display_measurement(record):
        value = record.get("measurements")
        if record["name"] != "package" or not isinstance(value, dict):
            return value
        inventory = value.get("installed_dependencies")
        return {
            **{
                k: value.get(k) for k in ("wheel_bytes", "files", "seconds", "baseline")
            },
            "dependencies": len(inventory) if isinstance(inventory, list) else None,
            "unknown_license_expressions": sum(
                not d.get("license_expression")
                for d in inventory
                if isinstance(d, dict)
            )
            if isinstance(inventory, list)
            else None,
            "inventory": "full package artifact metrics.json",
        }

    text = f"## {'Package' if package else 'Storage' if postgres else 'Browser' if browser else 'Quality'} results · {'FAIL' if errors else 'PASS'}\n\n"
    if browser or postgres:
        report_name = "browser/junit.xml" if browser else "postgres/junit.xml"
        measurements = records[0]["measurements"] or {}
        statuses = {records[0]["status"]}
        if measurements.get("skipped") or measurements.get("junit_declared", {}).get(
            "skipped"
        ):
            statuses.add("SKIPPED")
        rows = [
            (
                "Browser journey suite" if browser else "Disposable PostgreSQL shard",
                " / ".join(sorted(statuses)),
                "Exercises the product interactions and service boundaries listed in the current report",
                report_name,
            )
        ]
        rows += case_behavior(
            cases,
            BROWSER_BEHAVIOR if browser else STORAGE_BEHAVIOR,
            report_name,
            records[0]["status"],
        )
        text += behavior_table(
            rows,
            "Browser requests use authored fixtures or local loopback. Tests requiring an unavailable browser engine report a skip in JUnit. Native device behavior and live service are unmeasured."
            if browser
            else "Fixtures use an isolated PostgreSQL cluster and fake providers. Cases absent from this shard may be assigned to a different shard. Coverage and timing of the installed service are unmeasured.",
        )
    else:
        text += behavior_table(
            [
                (
                    CHECK_BEHAVIOR[r["name"]][0],
                    r["status"],
                    CHECK_BEHAVIOR[r["name"]][1],
                    f"Step {r['name']}"
                    + (
                        f" · {required[r['name']].relative_to(root)}"
                        if required[r["name"]]
                        else ""
                    ),
                )
                for r in records
            ],
            "Package startup uses a clean offline fixture and disables acquisition. Secret scanning covers the publishable tree. Dependency advisory coverage depends on the current service response. Product behavior is checked in separate jobs.",
        )
    text += f"Tested SHA: `{safe(os.environ.get('GITHUB_SHA', 'local'))}`. Event: {safe(os.environ.get('GITHUB_EVENT_NAME', 'local'))}. {safe(platform.platform())}. Python {platform.python_version()}.\n\n"
    text += "| Check | Status | Measurement / reason |\n|---|---|---|\n"
    text += "\n".join(
        f"| {r['name']} | {r['status']} | {safe(display_measurement(r))}; {safe(r.get('reason', ''))} |"
        for r in records
    )
    text += f"\n\nEvidence: {run_reference()}. JUnit counts represent serialized case records. Declared totals may also count subtests.\n"
    if errors:
        blocker = next(r for r in records if r["status"] != "PASS")
        earlier = next(
            (
                name
                for name in ("setup", "tools", "chromium", "binaries")
                if step_status(outcomes, name) in ("FAIL", "CANCELLED")
            ),
            None,
        )
        text += f"\nNext action: inspect the {safe(earlier or blocker['name'])} step and its artifact. {safe(blocker.get('reason'))}.\n"
    if "audit" in required:
        text += "Dependency findings use the current live database queried by pip-audit, with no comparable baseline.\n"
    identity = f"\nPR head: `{safe(os.environ.get('PR_HEAD_SHA'))}`; ref: `{safe(os.environ.get('GITHUB_REF'))}`; run: {safe(os.environ.get('CI_RUN_URL'))}.\n"
    text += identity
    text += f"Merge queue candidate: `{safe(os.environ.get('MERGE_QUEUE_SHA'))}`.\n"
    return text, records, bool(errors)


def main():
    root = Path("test-results")
    root.mkdir(exist_ok=True)
    try:
        outcomes = json.loads(os.environ.get("CHECK_OUTCOMES", "{}"))
    except ValueError:
        outcomes = {}
    text, records, failed = render(
        outcomes,
        root,
        "--postgres" in sys.argv,
        "--package" in sys.argv,
        "--expanded" in sys.argv,
        "--audit" in sys.argv,
        "--browser" in sys.argv,
    )
    name = (
        "browser"
        if "--browser" in sys.argv
        else "package-summary"
        if "--package" in sys.argv
        else "postgres"
        if "--postgres" in sys.argv
        else "quality"
    )

    def version(tool):
        try:
            return importlib.metadata.version(tool)
        except importlib.metadata.PackageNotFoundError:
            return None

    (root / name).mkdir(exist_ok=True)
    (root / name / "summary.md").write_text(text)
    (root / name / "metrics.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "tested_sha": os.environ.get("GITHUB_SHA"),
                "merge_queue_sha": os.environ.get("MERGE_QUEUE_SHA"),
                "platform": platform.platform(),
                "python": platform.python_version(),
                "runner": {
                    "environment": os.environ.get("RUNNER_ENVIRONMENT"),
                    "os": os.environ.get("RUNNER_OS"),
                    "arch": os.environ.get("RUNNER_ARCH"),
                    "image": os.environ.get("ImageOS"),
                },
                "overall": "FAIL" if failed else "PASS",
                "pr_head": os.environ.get("PR_HEAD_SHA"),
                "ref": os.environ.get("GITHUB_REF"),
                "run_url": os.environ.get("CI_RUN_URL"),
                "event": os.environ.get("GITHUB_EVENT_NAME"),
                "run_id": os.environ.get("GITHUB_RUN_ID"),
                "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                "checks": records,
                "baseline": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tools": {
                    name: version(name)
                    for name in ("ruff", "pip-audit", "build", "pytest", "playwright")
                },
            },
            indent=2,
        )
        + "\n"
    )
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(text)
    print(text, end="")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
