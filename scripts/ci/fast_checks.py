"""Personal beta data, calculation, checkpoint and deployment checks."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
CORE = {
    "tests/test_current_pregame_reference_policy.py",
    "tests/test_pregame_valuation.py",
    "tests/test_pregame_arbs.py",
    "tests/test_ev_movement.py",
    "tests/test_research_probability.py",
    "tests/test_current_storage_policy.py",
}
SQL_CORE = {
    "tests/test_ev_experiment_sql.py::ExperimentSQL::test_both_checkpoints_share_dependencies_and_export_reproduces_offline",
    "tests/test_current_pregame_sql.py::CurrentPregameSQL::test_http_health_checks_supported_sql_without_calculation",
}
DOMAINS = {
    "collection": {
        "tests/test_sportsgameodds_adapter.py",
        "tests/test_sportsgameodds_ledger.py",
        "tests/test_activity_mode.py",
        "tests/test_discovery_checkpoint_policy.py",
        "tests/test_experiment_acquisition.py",
    },
    "research": {
        "tests/test_ev_experiment_evidence.py",
        "tests/test_experiment_api.py",
    },
    "fees": {
        "tests/test_fee_pricing.py",
        "tests/test_fees.py",
        "tests/test_comparison_cashflows.py",
    },
    "dashboard": {"tests/test_experiment_api.py"},
    "deploy": {
        "tests/test_ci_image_cleanup.py",
        "tests/test_ci_fast_release.py",
        "tests/test_ci_fast_checks.py",
        "tests/test_ci_deploy.py::test_failed_web_rolls_back_web_only",
        "tests/test_ci_deploy.py::test_forward_migration_backs_up_and_releases_together",
        "tests/test_ci_deploy.py::test_fast_release_refuses_pending_schema_before_touching_services",
        "tests/test_ci_deploy.py::test_fast_release_of_unchanged_schema_uses_no_backup",
        "tests/test_ci_deploy.py::test_wrong_image_label_fails_before_compose",
        "tests/test_ci_deploy.py::test_managed_bundle_refuses_a_different_owner_database_before_rollout",
        "tests/test_ci_deploy.py::test_success_installs_managed_configuration_after_all_service_health",
        "tests/test_ci_deploy.py::test_proxy_reload_failure_restores_files_and_rolls_back_changed_web",
        "tests/test_ci_deploy.py::test_archive_health_failure_is_a_failed_release_even_after_rollback",
        "tests/test_ci_deploy.py::test_reused_unhealthy_service_cannot_produce_success",
    },
}


def plan(root, paths):
    pure, sql, scopes, notes = set(CORE), set(), set(), []
    for path in paths:
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("Changed paths must remain inside the checkout")
        if path.startswith(("deploy/", ".github/", "scripts/ci/")) or path in (
            "Dockerfile",
            ".dockerignore",
            ".env.example",
            "pyproject.toml",
            "requirements-ci.txt",
            "requirements-ci.in",
            "requirements-browser.txt",
            "requirements-browser.in",
            "uv.lock",
        ):
            scopes.add("deploy")
        if path.startswith("app/collection/"):
            scopes.add("collection")
            sql.add("tests/test_experiment_acquisition_sql.py")
        if path.startswith(("app/research/", "app/storage/")):
            scopes.add("research")
            sql.update(SQL_CORE)
        if path.startswith(("app/fees/", "app/comparison/", "app/settlement")):
            scopes.add("fees")
        if path.startswith("app/dashboard/"):
            scopes.add("dashboard")
        if path.startswith("app/") and not path.startswith(
            (
                "app/collection/",
                "app/research/",
                "app/storage/",
                "app/fees/",
                "app/comparison/",
                "app/dashboard/",
            )
        ):
            notes.append(
                "Core data/math checks cover this edit; broader historical checks are optional manual diagnostics: "
                + path
            )
    for scope in scopes:
        pure.update(DOMAINS[scope])
    sql = {
        node for node in sql if "::" not in node or node.split("::", 1)[0] not in sql
    }
    missing = [path for path in pure if not (root / path.split("::", 1)[0]).is_file()]
    if missing:
        raise ValueError(
            "Missing fast-check contract files: " + ", ".join(sorted(missing))
        )
    commands = [
        (
            "lint",
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "app",
                "scripts/ci",
                *sorted({path.split("::", 1)[0] for path in pure}),
            ],
        ),
        ("workflow", [".local/ci-tools/actionlint", "-shellcheck="]),
        ("secrets", [sys.executable, "scripts/ci/secret_scan.py"]),
        (
            "portable",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--maxfail=1",
                *sorted(pure),
            ],
        ),
    ]
    if sql:
        commands.append(
            (
                "postgres",
                [
                    sys.executable,
                    "scripts/ci/postgres.py",
                    "--report-dir",
                    "test-results/fast/postgres",
                    "--fail-fast",
                    "--tests",
                    *sorted(sql),
                ],
            )
        )
    return dict(
        paths=paths,
        scopes=sorted(scopes),
        commands=commands,
        notes=notes,
        coverage="Personal beta data/math, ledger, checkpoint/export and deployment guards. Broader historical diagnostics are manual-only and are not deployment gates.",
    )


def changed_paths(root):
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    event = json.loads(Path(event_path).read_text()) if event_path else {}
    base = (
        event.get("before")
        or (event.get("pull_request") or {}).get("base", {}).get("sha")
        or (event.get("merge_group") or {}).get("base_sha")
    )
    if base and re.fullmatch(r"[a-f0-9]{40}", base) and set(base) != {"0"}:
        if subprocess.run(
            ["git", "cat-file", "-e", base + "^{commit}"], cwd=root, capture_output=True
        ).returncode:
            subprocess.run(
                ["git", "fetch", "--no-tags", "--depth=1", "origin", base],
                cwd=root,
                check=True,
                timeout=20,
            )
    else:
        base = "HEAD^" if event_path else "HEAD"
    raw = subprocess.check_output(
        ["git", "diff", "--name-only", "--no-renames", base, "HEAD", "--"],
        cwd=root,
        text=True,
    )
    if not event_path:
        raw += subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD", "--"], cwd=root, text=True
        )
    return sorted(set(raw.splitlines()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--paths", nargs="*")
    args = parser.parse_args(argv)
    selected = plan(ROOT, changed_paths(ROOT) if args.paths is None else args.paths)
    if args.plan:
        print(json.dumps(selected, indent=2))
        return 0
    output = ROOT / "test-results/fast"
    reports = output / (
        str(time.time_ns()) + "-" + str(os.environ.get("GITHUB_RUN_ATTEMPT", "local"))
    )
    reports.mkdir(parents=True)
    for name, command in selected["commands"]:
        if name == "secrets":
            command.extend(("--output", str(reports / "secrets")))
        elif name == "postgres":
            command[command.index("--report-dir") + 1] = str(reports / "postgres")
    started = time.monotonic()
    checks = []
    code = 0
    for name, command in selected["commands"]:
        before = time.monotonic()
        result = subprocess.run(command, cwd=ROOT)
        checks.append(
            dict(
                name=name,
                status="PASS" if result.returncode == 0 else "FAIL",
                seconds=round(time.monotonic() - before, 3),
            )
        )
        if result.returncode:
            code = result.returncode
            break
    metrics = dict(
        schema=1,
        overall="PASS" if code == 0 else "FAIL",
        tested_sha=os.environ.get("GITHUB_SHA"),
        run_id=os.environ.get("GITHUB_RUN_ID"),
        checked_at=datetime.now(timezone.utc).isoformat(),
        seconds=round(time.monotonic() - started, 3),
        checks=checks,
        selection=selected,
        full_assurance="Optional manual historical validation; not asserted by this personal-beta result",
        report_directory=str(reports.relative_to(ROOT)),
    )
    (reports / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    text = (
        "## Fast personal checks "
        + metrics["overall"]
        + "\n\n"
        + selected["coverage"]
        + "\n\n"
    )
    text += "\n".join(
        f"- {row['name']}: {row['status']} ({row['seconds']}s)" for row in checks
    )
    text += f"\n\nFocused checks took {metrics['seconds']}s. Setup, build, deployment and runner queue are measured separately.\n"
    if selected["notes"]:
        text += "\n" + "\n".join(selected["notes"]) + "\n"
    (output / "summary.md").write_text(text)
    (reports / "summary.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
            summary.write(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
