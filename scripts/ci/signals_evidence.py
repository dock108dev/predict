"""Extract scoped, comparable CI measurements from existing artifacts."""

from collections import defaultdict
import hashlib
import json
from math import isfinite
from pathlib import Path
import re
from statistics import median
import subprocess
from xml.etree.ElementTree import ParseError

from reporting import case_status, junit


CONTRACTS = {
    "Stale native prices lose current authority": (
        (
            "storage",
            "tests.test_ordinary_publication_sql.OrdinarySQL",
            "test_posted_native_quote_survives_rotation_and_loses_execution_authority",
        ),
    ),
    "Unsupported fee or settlement inputs withhold finance": (
        (
            "ci-offline",
            "tests.test_f07_desk",
            "test_stale_terms_keep_supported_leg_and_withhold_net_payoff",
        ),
        (
            "ci-offline",
            "tests.test_f07_desk",
            "test_native_census_distinguishes_unobserved_incompatible_stale_and_pending_peers",
        ),
    ),
    "Ranked pairs use exact opposing markets": (
        (
            "ci-offline",
            "tests.test_f07_desk",
            "test_ordinary_ready_and_pending_publish_only_exact_native_pairs",
        ),
        (
            "ci-offline",
            "tests.test_trade_desk.TradeDesk",
            "test_ev_groups_exact_lines_and_keeps_unknowns_out_of_rank",
        ),
    ),
    "Recovery preserves provider holds and avoids repeat dispatch": (
        (
            "ci-offline",
            "tests.test_sportsgameodds_ledger",
            "test_holds_survive_restart_and_only_evidence_resolves",
        ),
        (
            "storage",
            "tests.test_sportsgameodds_ingress_sql.SportsGameOddsAtomicIngress",
            "test_sql_timeout_after_frame_retries_the_settled_page_without_another_request",
        ),
    ),
    "Desk shows last-known prices and recovers": (
        (
            "storage",
            "tests.test_broad_native_matrix_sql.BroadNativeMatrixSQL",
            "test_desk_keeps_last_polymarket_price_during_sql_stall_and_reconnect",
        ),
        (
            "ci-browser",
            "browser_tests.test_ranked_opportunities",
            "test_desk_renders_last_known_polymarket_quote_and_recovers_on_first_poll",
        ),
    ),
}


def read_json(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def artifacts(root, sha, run, attempt, inherited_attempts):
    """Bind each lane to its actual execution attempt and tested commit."""
    selected = {}
    if not sha or not str(attempt).isdigit():
        return selected
    for path in root.glob("*"):
        match = re.fullmatch(
            r"(ci-offline|ci-quality|ci-browser|storage)-(\d+)-(\d+)(?:-(\d+))?",
            path.name,
        )
        if not match:
            continue
        lane, number, version, shard = match.groups()
        key = (lane, shard)
        if (
            number != str(run)
            or int(version) != inherited_attempts.get(key, int(attempt))
            or (lane == "storage") != bool(shard)
        ):
            continue
        metadata = read_json(
            path / ("quality/metrics.json" if lane == "ci-quality" else "metrics.json")
        )
        if (
            metadata.get("tested_sha"),
            str(metadata.get("run_id")),
            str(metadata.get("run_attempt")),
        ) != (sha, number, version):
            continue
        selected[key] = dict(path=path, report=metadata, attempt=int(version))
    return selected


def contract_results(selected):
    cases = defaultdict(list)
    wanted = {case for group in CONTRACTS.values() for case in group}
    for (lane, _), artifact in selected.items():
        if lane == "ci-quality":
            continue
        for path in sorted(
            artifact["path"].glob("*.xml" if lane == "ci-offline" else "junit.xml")
        ):
            if path.name == "coverage.xml":
                continue
            try:
                rows, _, _ = junit(path)
            except (OSError, ValueError, ParseError):
                continue
            for row in rows:
                name = row.get("name", "")
                key = (lane, row.get("classname"), name.split("[", 1)[0])
                if key in wanted:
                    cases[key].append(
                        dict(
                            case=name,
                            status=case_status(row),
                            artifact=artifact["path"].name,
                            report=path.name,
                        )
                    )
    priority = ("FAIL", "MISSING", "SKIPPED", "PASS")
    out = {}
    for label, checks in CONTRACTS.items():
        evidence = [
            dict(lane=key[0], test=f"{key[1]}::{key[2]}", cases=cases.get(key, []))
            for key in checks
        ]
        statuses = {case["status"] for entry in evidence for case in entry["cases"]} | (
            {"MISSING"} if any(not entry["cases"] for entry in evidence) else set()
        )
        out[label] = dict(
            status=next(status for status in priority if status in statuses),
            evidence=evidence,
        )
    return out


def ratio(covered, total):
    if type(covered) is int and type(total) is int and 0 <= covered <= total:
        return dict(
            covered=covered,
            total=total,
            percent=round(100 * covered / total, 2) if total else None,
        )
    return None


def totals(summary):
    return {
        "lines": ratio(summary.get("covered_lines"), summary.get("num_statements")),
        "branches": ratio(summary.get("covered_branches"), summary.get("num_branches")),
    }


def git(root, *args):
    return subprocess.check_output(
        ["git", "--literal-pathspecs", "-C", str(root), *args],
        stderr=subprocess.DEVNULL,
        timeout=15,
    )


def patch_lines(root, base, sha):
    """Use tested-tree line numbers and distinguish deletion from missing diff."""
    if not all(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value)
        for value in (base, sha)
    ):
        return None
    opts = ("diff", "--no-ext-diff", "--no-textconv", "--no-renames")
    try:
        names = git(
            root,
            *opts,
            "--name-only",
            "--diff-filter=ACMT",
            "-z",
            base,
            sha,
            "--",
            "app",
        )
        changes = {}
        for raw in names.split(b"\0"):
            path = raw.decode()
            if not path.endswith(".py"):
                continue
            patch = git(root, *opts, "--unified=0", base, sha, "--", path)
            changes[path] = [
                (int(line), int(length) if length else 1)
                for line, length in re.findall(
                    rb"(?m)^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", patch
                )
            ]
        return changes
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def changed_coverage(files, changes):
    if changes is None:
        return None
    measured = []
    unmeasured = []
    for path, hunks in sorted(changes.items()):
        if not any(length for _, length in hunks):
            continue
        detail = files.get(path)
        fields = (
            "executed_lines",
            "missing_lines",
            "executed_branches",
            "missing_branches",
        )
        if not isinstance(detail, dict) or any(
            not isinstance(detail.get(key), list) for key in fields
        ):
            unmeasured.append(path)
            continue

        def changed(line):
            return type(line) is int and any(
                start <= line < start + length for start, length in hunks
            )

        hit, miss = (
            sorted(line for line in detail[key] if changed(line)) for key in fields[:2]
        )
        taken, missed = (
            sorted(
                arc
                for arc in detail[key]
                if isinstance(arc, list) and len(arc) == 2 and changed(arc[0])
            )
            for key in fields[2:]
        )
        measured.append(
            dict(
                path=path,
                missing_lines=miss,
                missing_branches=missed,
                lines=ratio(len(hit), len(hit) + len(miss)),
                branches=ratio(len(taken), len(taken) + len(missed)),
            )
        )
    return dict(
        files=measured,
        unmeasured=unmeasured,
        **{
            kind: ratio(
                sum(row[kind]["covered"] for row in measured),
                sum(row[kind]["total"] for row in measured),
            )
            for kind in ("lines", "branches")
        },
    )


def coverage_scope(root, report, coverage):
    if (
        not report.get("tools")
        or coverage.get("meta", {}).get("branch_coverage") is not True
    ):
        return None
    files = ("scripts/ci/suites.json", "scripts/ci/python-policy.json")
    fingerprint = hashlib.sha256(
        b"\0".join((root / name).read_bytes() for name in files)
    ).hexdigest()
    return dict(
        manifest=fingerprint,
        tools=report["tools"],
        platform=str(report.get("platform", "")).split("-", 1)[0],
        python=str(report.get("python", "")).split(" ", 1)[0],
    )


def number(value):
    return (
        value
        if type(value) in (int, float) and isfinite(value) and value >= 0
        else None
    )


def timing_scope(artifact, tool, version):
    report = artifact["report"]
    runner = report.get("runner")
    fields = ("environment", "os", "arch", "image")
    if (
        not isinstance(runner, dict)
        or not all(isinstance(runner.get(key), str) and runner[key] for key in fields)
        or not isinstance(report.get("python"), str)
        or not isinstance(version, str)
        or not version
    ):
        return None
    return dict(
        runner={key: runner[key] for key in fields},
        python=report["python"],
        **{tool: version},
    )


def timing(selected):
    measurements = {}
    for (lane, _), artifact in selected.items():
        if lane != "storage":
            continue
        path = artifact["path"]
        scope = timing_scope(
            artifact, "postgres", read_json(path / "toolchain.json").get("postgres")
        )
        values = read_json(path / "selected-input-latency.json")
        if (
            values.get("evidence")
            == "authored 60 games, real native ingress, disposable PostgreSQL"
        ):
            selected_read = values.get("selected")
            if isinstance(selected_read, dict) and selected_read.get("status") == 200:
                for label, value in (
                    ("Selected quote HTTP read", selected_read.get("seconds")),
                    (
                        "Two ordinary pages during held selection",
                        values.get("two_page_ordinary_seconds"),
                    ),
                ):
                    if (seconds := number(value)) is not None:
                        measurements[label] = dict(
                            seconds=seconds,
                            fixture="selected-input-60-games-v1",
                            samples=1,
                            artifact=path.name,
                            scope=scope,
                        )
        recovery = read_json(path / "desk-recovery.json")
        if recovery.get("fixture") == "desk-polymarket-nba-v1":
            budget = number(recovery.get("fallback_budget_seconds"))
            samples = recovery.get("fallback_samples")
            if (
                isinstance(samples, list)
                and samples
                and all(number(sample) is not None for sample in samples)
            ):
                measurements["Desk fallback during held SQL read"] = dict(
                    seconds=median(samples),
                    fixture=recovery["fixture"],
                    samples=len(samples),
                    artifact=path.name,
                    response_budget=budget,
                    scope=scope,
                )
            for label, key in (
                ("First desk response", "first_seconds"),
                ("Warm desk response", "warm_seconds"),
                ("Desk response after SQL resumes", "resumed_seconds"),
                (
                    "Desk response with SQL unavailable after app restart",
                    "restart_seconds",
                ),
            ):
                if (seconds := number(recovery.get(key))) is not None:
                    measurements[label] = dict(
                        seconds=seconds,
                        fixture=recovery["fixture"],
                        samples=1,
                        artifact=path.name,
                        scope=scope,
                    )
    return measurements
