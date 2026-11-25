"""Personal beta data, calculation, checkpoint and deployment checks."""

import argparse
from concurrent.futures import ThreadPoolExecutor
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
    "tests/test_acquisition_membership.py",
    "tests/test_current_pregame_reference_policy.py",
    "tests/test_pregame_valuation.py",
    "tests/test_pregame_arbs.py",
    "tests/test_ev_movement.py",
    "tests/test_research_probability.py",
    "tests/test_current_storage_policy.py",
    "tests/test_market_snapshot_presentation.py",
}
SQL_CORE = {
    "tests/test_ev_experiment_sql.py::ExperimentSQL::test_both_checkpoints_share_dependencies_and_export_reproduces_offline",
    "tests/test_current_pregame_sql.py::CurrentPregameSQL::test_http_health_checks_supported_sql_without_calculation",
}
SQL_WORKSPACE = SQL_CORE | {
    "tests/test_data_workspace_sql.py",
    "tests/test_ev_experiment_sql.py::ExperimentSQL::test_reference_scope_transition_preserves_old_policy_and_declared_checkpoint_requests",
    "tests/test_experiment_acquisition_sql.py",
    "tests/test_fee_mode_sql.py",
    "tests/test_fee_pricing_sql.py",
    "tests/test_market_board_sql.py",
    "tests/test_market_snapshot_arbs_sql.py",
    "tests/test_research_catalog_sql.py",
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
        "tests/test_paper_experiments.py",
        "tests/test_ev_experiment_evidence.py",
        "tests/test_experiment_api.py",
    },
    "fees": {
        "tests/test_fee_pricing.py",
        "tests/test_fee_mode.py",
        "tests/test_fee_mode_experiments.py",
        "tests/test_fees.py",
        "tests/test_comparison_cashflows.py",
    },
    "dashboard": {
        "tests/test_paper_experiments.py",
        "tests/test_experiment_api.py",
        "tests/test_data_workspace_client.py",
        "tests/test_catalog_admission.py",
        "tests/test_workspace_fee_mode_api.py",
        "tests/test_workspace_capture_client.py",
        "tests/test_workspace_sessions.py",
        "tests/test_workspace_settings_accounting.py",
        "tests/test_market_workspace_client.py",
    },
    "deploy": {
        "tests/test_owner_remember_cookie.py",
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
        if path.startswith("app/research/paper") or path == "app/dashboard/paper_api.py":
            sql.add("tests/test_paper_experiments_sql.py")
        if path.startswith(
            (
                "app/research/paper_result",
                "app/storage/paper_result",
                "app/dashboard/paper_result",
                "tests/test_paper_result",
            )
        ) or path in (
            "app/dashboard/research_workspace_api.py",
            "app/storage/migrations/120_paper_results.sql",
        ):
            pure.update(
                {"tests/test_paper_results.py", "tests/test_paper_results_api.py"}
            )
            sql.add("tests/test_paper_result_queue_sql.py")
        if path in (
            "app/collection/sgo_game_results.py",
            "app/collection/sportsgameodds_worker.py",
            "app/research/experiment.py",
        ):
            pure.add("tests/test_sgo_game_results.py")
            sql.add(
                "tests/test_ev_experiment_sql.py::ExperimentSQL::test_ordinary_terminal_dispute_supersedes_a_final_until_corrected"
            )
        if path in ("app/research/recovery.py", "tests/test_t10_recovery.py"):
            pure.add("tests/test_t10_recovery.py")
            sql.add("tests/test_t10_recovery.py::RecoverySQL")
        if "mens_d1" in path or "mens-d1" in path:
            pure.update({"tests/test_mens_d1_source.py", "tests/test_mens_d1_daily_jobs.py",
                         "tests/test_mens_d1_coverage_api.py::test_coverage_reads_and_downloads_do_not_dispatch"})
            sql.update({"tests/test_mens_d1_coverage_sql.py",
                        "tests/test_mens_d1_coverage_api.py::MensD1CoverageSQL",
                        "tests/test_paper_experiments_sql.py"})
        if path.startswith(("app/fees/", "app/comparison/", "app/settlement")):
            scopes.add("fees")
        if path.startswith("app/dashboard/"):
            scopes.add("dashboard")
        if path in ("tests/latest_board_fixture.py", "tests/pregame_fixture.py", "tests/test_sql_fixture_template.py"):
            # Preserve the complete workspace SQL selection when its shared
            # database setup changes; template reuse never narrows checks.
            sql.update(SQL_WORKSPACE)
            sql.add("tests/test_sql_fixture_template.py")
        if path == "app/dashboard/multi_game_server.py":
            pure.add(
                "tests/test_ev09_asset_delivery.py::Assets"
            )
        if path in ("app/storage/research_catalog.py", "app/dashboard/research_api.py"):
            sql.update({"tests/test_data_workspace_sql.py", "tests/test_research_catalog_sql.py"})
        if path in ("app/storage/market_board.py", "app/storage/acquisition_snapshot.py",
                    "app/dashboard/research_api.py", "tests/test_market_board_sql.py"):
            sql.add("tests/test_market_board_sql.py")
        if path in ("app/storage/market_snapshot_arbs.py", "app/comparison/pregame_arbs.py",
                    "app/storage/pregame_arbs.py", "tests/test_market_snapshot_arbs_sql.py"):
            sql.add("tests/test_market_snapshot_arbs_sql.py")
        if path in ("app/comparison/fee_mode.py", "app/comparison/current_pregame.py", "app/storage/current_pregame.py", "app/storage/current_pregame_read.py"):
            sql.update({"tests/test_fee_mode_sql.py", "tests/test_fee_pricing_sql.py"})
        if path in ("app/comparison/fee_mode.py", "app/research/experiment.py"):
            sql.add("tests/test_ev_experiment_sql.py::ExperimentSQL::test_fee_mode_transition_appends_policy_without_rewriting_old_evidence")
        if path in ("app/research/experiment.py", "app/collection/experiment_acquisition.py", "app/comparison/reference_scope.py"):
            sql.add("tests/test_ev_experiment_sql.py::ExperimentSQL::test_reference_scope_transition_preserves_old_policy_and_declared_checkpoint_requests")
        if path in ("app/research/experiment.py", "app/collection/experiment_acquisition.py", "app/storage/acquisition_snapshot.py"):
            sql.add("tests/test_ev_experiment_sql.py::ExperimentSQL::test_late_pull_manifest_spends_its_own_reserved_bytes")
        if path == "app/dashboard/workspace_routes.py" or path.startswith(
            "app/dashboard/opportunity_static/current/"
        ):
            pure.add("tests/test_ev09_asset_delivery.py::Assets")
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



def run_checks(commands, *, root=ROOT):
    """Pass the serial baseline, then join independent portable/SQL validation.

    Each subprocess retains its own reports. A validation failure never abandons
    its sibling: both results and elapsed times are collected before returning.
    """
    checks = []
    validation_names = {"portable", "postgres"}

    def measured(item):
        name, command = item
        before = time.monotonic()
        error = None
        try:
            code = subprocess.run(command, cwd=root).returncode
        except (OSError, subprocess.SubprocessError) as exc:
            code = 1
            error = str(exc)
        result = dict(name=name, status="PASS" if code == 0 else "FAIL",
                      seconds=round(time.monotonic() - before, 3), returncode=code)
        if error is not None:
            result["error"] = error
        return result

    for item in commands:
        if item[0] in validation_names:
            continue
        result = measured(item)
        checks.append(result)
        if result["returncode"]:
            return checks, result["returncode"]

    independent = [item for item in commands if item[0] in validation_names]
    if independent:
        with ThreadPoolExecutor(max_workers=len(independent)) as pool:
            futures = [pool.submit(measured, item) for item in independent]
            # Keep report order deterministic and await every submitted owner.
            checks.extend(future.result() for future in futures)
    return checks, next((row["returncode"] for row in checks if row["returncode"]), 0)


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
    checks, code = run_checks(selected["commands"], root=ROOT)
    metrics = dict(
        schema=1,
        execution="serial_baseline_then_joined_parallel_portable_postgres",
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
    text += "\n\nLint, workflow and secret checks pass before portable and PostgreSQL validation run concurrently; both validation processes are joined."
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
