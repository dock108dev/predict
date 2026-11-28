"""Personal beta data, calculation, checkpoint and deployment checks."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from zipfile import BadZipFile, ZipFile

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
SQL_SGO = {
    "tests/test_sportsgameodds_ingress_sql.py",
    "tests/test_sportsgameodds_reference_sql.py",
}
SQL_DATABASE_ROLES = "tests/test_database_roles_sql.py"
SQL_MONITOR = "tests/test_pregame_cohorts_sql.py"
OFFER_EXPORT = "tests/test_research_offer_export_api.py"
ASSET_ALLOWLIST = "tests/test_ev09_asset_delivery.py::Assets::test_workspace_asset_route_serves_only_registered_files"
DEPTH_SPOOL = "tests/test_experiment_depth_stage.py"
NOVIG_BINDING = {
    "tests/test_native_trading.py::test_novig_native_discovery_binds_both_roles_and_enumerates_unrepresented_lines",
    "tests/test_native_trading.py::test_five_minute_difference_needs_both_roles_and_exact_event_link_and_keeps_paper_clock",
}
HYBRID_REPLAY = "tests/test_paper_campaigns_sql.py::CampaignSQL::test_all_sports_replays_original_books_then_collects_at_the_future_cutoff"
MIXED_SQL = {
    "tests/test_market_census.py": ("MarketCensusSQL",),
    "tests/test_mens_d1_coverage_api.py": ("MensD1CoverageSQL",),
    "tests/test_native_experiment_depth.py": ("NativeReplacementSQL",),
    "tests/test_t10_recovery.py": ("DatedD1RecoverySQL", "RecoverySQL"),
}
BASELINE_BROWSER = {
    "browser_tests/test_dashboard_workspace.py",
    "browser_tests/test_experiment_workspace.py",
    "browser_tests/test_personal_data_workspace.py",
    "browser_tests/test_paper_campaign_integration.py",
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


def plan(root, paths, *, broad=False):
    pure, sql, scopes, notes = set(CORE), set(), set(), []
    browser = set(BASELINE_BROWSER) if broad else set()
    policy = json.loads((root / "scripts/ci/python-policy.json").read_text())
    contracted_portable = {
        test
        for suite in json.loads((root / "scripts/ci/suites.json").read_text())
        for test in suite["tests"]
    } | set(policy["quality"])
    archived = policy["deferred"]
    # A missing base runs each focused application selector. The historical Full
    # suite remains separately registered with its own execution contract.
    inputs = set(paths)
    if broad:
        inputs.update(
            git_paths(
                root, "ls-files", "-z", "--", "app", "deploy", ".github", "scripts/ci"
            )
        )
    for path in sorted(inputs):
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("Changed paths must remain inside the checkout")
        if path.startswith("docs/") or (
            len(candidate.parts) == 1 and candidate.suffix == ".md"
        ):
            continue
        if (
            path.startswith(("tests/test_", "browser_tests/test_"))
            and candidate.suffix == ".py"
            and (root / path).is_file()
        ):
            if path.startswith("browser_tests/"):
                browser.add(path)
            elif path in MIXED_SQL:
                pure.add(path)
                sql.update(path + "::" + node for node in MIXED_SQL[path])
            elif archived.get(path, "").startswith("Required") or (
                path.endswith("_sql.py") and path not in archived
            ):
                sql.add(path)
            elif path in contracted_portable or path not in archived:
                pure.add(path)
            else:
                notes.append(
                    "Changed test remains optional under the suite manifest: " + path
                )
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
        if path in (
            "app/collection/current_native.py",
            "app/collection/current_native_publication.py",
        ):
            pure.add("tests/test_current_native.py")
        if path in (
            "app/dashboard/workspace_routes.py",
            "app/dashboard/workspace_app.py",
            "app/dashboard/multi_game_server.py",
        ):
            pure.add(ASSET_ALLOWLIST)
        if path in (
            "app/collection/experiment_depth_stage.py",
            "app/collection/experiment_depth.py",
            "app/storage/migrations/129_experiment_depth_receipt_capacity.sql",
        ):
            pure.add(DEPTH_SPOOL)
        if path in (
            "app/collection/native_trading.py",
            "app/collection/novig_experiment_depth.py",
            "app/storage/native_trading.py",
        ):
            pure.update(NOVIG_BINDING)
        if path in (
            "app/collection/native_trading_identity.py",
            "app/comparison/sgo_native_binding.py",
            "app/storage/sgo_native_catalog.py",
        ):
            pure.add("tests/test_sgo_native_binding.py")
            sql.update(
                {
                    "tests/test_sgo_native_catalog_sql.py",
                    "tests/test_native_trading_sql.py",
                }
            )
        if path in (
            "app/dashboard/opportunity_static/current/dashboard.js",
            "app/dashboard/opportunity_static/current/research-tools.js",
        ):
            browser.add("browser_tests/test_dashboard_workspace.py")
        if path in (
            "app/research/paper_campaigns.py",
            "app/research/paper_depth.py",
            "app/research/paper.py",
            "app/collection/experiment_depth.py",
            "app/collection/experiment_depth_stage.py",
            "app/storage/experiment_depth.py",
            "app/storage/migrations/129_experiment_depth_receipt_capacity.sql",
        ):
            sql.add(HYBRID_REPLAY)
        if path in (
            "app/collection/original_receipts.py",
            "tests/test_original_receipts.py",
        ):
            pure.add("tests/test_original_receipts.py")
        if path in (
            "app/collection/current_service.py",
            "app/collection/data_runtime.py",
            "app/dashboard/current_state.py",
            "tests/test_data_runtime_unit.py",
        ):
            pure.add("tests/test_data_runtime_unit.py")
        if path in (
            "app/storage/database_roles.py",
            "app/storage/store.py",
            "deploy/compose.yml",
            "deploy/managed-config.py",
            "deploy/release.sh",
            SQL_DATABASE_ROLES,
        ):
            scopes.add("deploy")
            sql.add(SQL_DATABASE_ROLES)
        if path.startswith(("app/research/", "app/storage/")):
            scopes.add("research")
            sql.update(SQL_CORE)
        if path.startswith(
            (
                "app/collection/native_trading",
                "app/collection/native_reference_refresh",
                "app/storage/native_trading",
                "app/comparison/native_observation",
                "tests/test_native_trading",
                "tests/test_native_observation",
            )
        ) or path.endswith("128_native_trading_offers.sql"):
            pure.update(
                {
                    "tests/test_native_trading.py",
                    "tests/test_native_trading_prophetx.py",
                    "tests/test_native_observation.py",
                }
            )
            sql.add("tests/test_native_trading_sql.py")
        if path.startswith(("app/", "tests/")) and any(
            topic in candidate.name
            for topic in (
                "experiment_depth",
                "paper_depth",
                "experiment_public_depth",
                "execution_contract",
                "liquidity_execution",
                "dashboard_depth",
                "dashboard_kalshi",
                "dashboard_pmus",
            )
        ):
            pure.update(
                {
                    "tests/test_experiment_depth_execution.py",
                    "tests/test_liquidity_execution.py",
                    "tests/test_dashboard_pmus.py",
                    "tests/test_native_experiment_depth.py",
                    "tests/test_novig_experiment_depth.py",
                }
            )
            sql.update(
                {
                    "tests/test_experiment_depth_sql.py",
                    "tests/test_native_experiment_depth.py::NativeReplacementSQL",
                }
            )
        if (
            path.startswith("app/research/paper")
            or path == "app/dashboard/paper_api.py"
        ):
            sql.add("tests/test_paper_experiments_sql.py")
        if path.startswith(
            (
                "app/research/paper_result",
                "app/research/paper_campaign",
                "tests/test_paper_campaign",
                "app/storage/paper_result",
                "app/dashboard/paper_result",
                "tests/test_paper_result",
            )
        ) or path in (
            "app/dashboard/research_workspace_api.py",
            "app/storage/migrations/120_paper_results.sql",
            "app/storage/migrations/121_paper_campaigns.sql",
            "app/storage/migrations/126_paper_campaign_retirement.sql",
        ):
            pure.update(
                {"tests/test_paper_results.py", "tests/test_paper_results_api.py"}
            )
            sql.add("tests/test_paper_result_queue_sql.py")
            pure.add("tests/test_paper_campaigns.py")
            sql.add("tests/test_paper_campaigns_sql.py")
        if path in (
            "app/collection/sgo_game_results.py",
            "app/collection/sportsgameodds_worker.py",
            "app/research/experiment.py",
        ):
            pure.add("tests/test_sgo_game_results.py")
            sql.add(
                "tests/test_ev_experiment_sql.py::ExperimentSQL::test_ordinary_terminal_dispute_supersedes_a_final_until_corrected"
            )
        if path in (
            "app/collection/sgo_game_results.py",
            "app/collection/sgo_nhl_scoring.py",
            "app/collection/sportsgameodds_adapter.py",
            "app/research/experiment.py",
            "app/research/paper_results.py",
            "tests/test_sgo_nhl_scoring.py",
            "tests/test_paper_results.py",
        ):
            pure.add("tests/test_sgo_nhl_scoring.py")
            sql.add(
                "tests/test_ev_experiment_sql.py::ExperimentSQL::test_same_score_nhl_outcomes_retain_new_period_proof_without_losing_it_on_repeats"
            )
        if path in ("app/research/recovery.py", "tests/test_t10_recovery.py"):
            pure.add("tests/test_t10_recovery.py")
            sql.add("tests/test_t10_recovery.py::RecoverySQL")
        if path.startswith(("app/", "tests/")) and (
            "mens_d1" in candidate.name or "mens-d1" in candidate.name
        ):
            pure.update(
                {
                    "tests/test_mens_d1_source.py",
                    "tests/test_mens_d1_daily_jobs.py",
                    "tests/test_mens_d1_coverage_api.py::test_coverage_reads_and_downloads_do_not_dispatch",
                }
            )
            sql.update(
                {
                    "tests/test_mens_d1_coverage_sql.py",
                    "tests/test_mens_d1_coverage_api.py::MensD1CoverageSQL",
                    "tests/test_paper_experiments_sql.py",
                }
            )
        if path.startswith(("app/", "tests/")) and any(
            topic in candidate.name
            for topic in ("market_census", "issue_dispositions", "nov23_audit")
        ):
            pure.add(
                "tests/test_market_census.py::test_no_provider_odds_requires_affirmative_exact_return"
            )
            sql.update(
                {
                    "tests/test_market_census.py::MarketCensusSQL",
                    "tests/test_mens_d1_coverage_api.py::MensD1CoverageSQL",
                }
            )
        if path in (
            "app/dashboard/research_workspace_api.py",
            "app/research/workspace.py",
            "app/research/market_census.py",
            "app/storage/store.py",
            OFFER_EXPORT,
        ):
            pure.add(OFFER_EXPORT)
        if (
            path.startswith(
                ("app/collection/sportsgameodds_", "app/storage/sportsgameodds_")
            )
            or (
                path.startswith("app/storage/migrations/")
                and "_sportsgameodds_" in candidate.name
            )
            or path
            in (
                "app/collection/current_database.py",
                "app/comparison/reference_scope.py",
                *SQL_SGO,
            )
        ):
            sql.update(SQL_SGO)
        if path.startswith("app/storage/pregame_cohort") or path in (
            "app/collection/current_database.py",
            "app/collection/current_ingress.py",
            "app/storage/migrations/124_pregame_projection_recovery.sql",
            SQL_MONITOR,
        ):
            sql.add(SQL_MONITOR)
        if path in (
            "app/collection/sportsgameodds_adapter.py",
            "app/collection/sportsgameodds_worker.py",
        ):
            pure.update(
                {
                    "tests/test_sportsgameodds_discovery.py::test_discovery_retains_unique_members_through_mixed_overlaps",
                    "tests/test_sportsgameodds_worker.py::test_exact_id_refresh_retains_omissions_and_excludes_unrequested_members",
                }
            )
        if path.startswith(("app/fees/", "app/comparison/", "app/settlement")):
            scopes.add("fees")
        if path == "app/fees/public_reasons.py":
            pure.update(
                {"tests/test_public_fee_schedule.py", "tests/test_paper_campaigns.py"}
            )
        if path.startswith("app/dashboard/"):
            scopes.add("dashboard")
        if path in (
            "tests/latest_board_fixture.py",
            "tests/pregame_fixture.py",
            "tests/test_sql_fixture_template.py",
        ):
            # Preserve the complete workspace SQL selection when its shared
            # database setup changes; template reuse never narrows checks.
            sql.update(SQL_WORKSPACE)
            sql.add("tests/test_sql_fixture_template.py")
        if path == "app/dashboard/multi_game_server.py":
            pure.add("tests/test_ev09_asset_delivery.py::Assets")
        if path in ("app/storage/research_catalog.py", "app/dashboard/research_api.py"):
            sql.update(
                {
                    "tests/test_data_workspace_sql.py",
                    "tests/test_research_catalog_sql.py",
                }
            )
        if path in (
            "app/storage/market_board.py",
            "app/storage/acquisition_snapshot.py",
            "app/dashboard/research_api.py",
            "tests/test_market_board_sql.py",
        ):
            sql.add("tests/test_market_board_sql.py")
        if path in (
            "app/storage/market_snapshot_arbs.py",
            "app/comparison/pregame_arbs.py",
            "app/storage/pregame_arbs.py",
            "tests/test_market_snapshot_arbs_sql.py",
        ):
            sql.add("tests/test_market_snapshot_arbs_sql.py")
        if path in (
            "app/comparison/fee_mode.py",
            "app/comparison/current_pregame.py",
            "app/storage/current_pregame.py",
            "app/storage/current_pregame_read.py",
        ):
            sql.update({"tests/test_fee_mode_sql.py", "tests/test_fee_pricing_sql.py"})
        if path in ("app/comparison/fee_mode.py", "app/research/experiment.py"):
            sql.add(
                "tests/test_ev_experiment_sql.py::ExperimentSQL::test_fee_mode_transition_appends_policy_without_rewriting_old_evidence"
            )
        if path in (
            "app/research/experiment.py",
            "app/collection/experiment_acquisition.py",
            "app/comparison/reference_scope.py",
        ):
            sql.add(
                "tests/test_ev_experiment_sql.py::ExperimentSQL::test_reference_scope_transition_preserves_old_policy_and_declared_checkpoint_requests"
            )
        if path in (
            "app/research/experiment.py",
            "app/collection/experiment_acquisition.py",
            "app/storage/acquisition_snapshot.py",
        ):
            sql.add(
                "tests/test_ev_experiment_sql.py::ExperimentSQL::test_late_pull_manifest_spends_its_own_reserved_bytes"
            )
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
    pure = {
        node for node in pure if "::" not in node or node.split("::", 1)[0] not in pure
    }
    sql = {
        node for node in sql if "::" not in node or node.split("::", 1)[0] not in sql
    }
    missing = [path for path in pure if not (root / path.split("::", 1)[0]).is_file()]
    if missing:
        raise ValueError(
            "Missing fast-check contract files: " + ", ".join(sorted(missing))
        )
    portable_modules = {path.split("::", 1)[0] for path in pure}
    deselected = {
        path + "::" + node
        for path in portable_modules & MIXED_SQL.keys()
        for node in MIXED_SQL[path]
    }
    deselected.update(
        node
        for node in policy["archival_nodes"]
        if node.split("::", 1)[0] in portable_modules
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
                *("--deselect=" + node for node in sorted(deselected)),
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
        browser=sorted(browser),
        scopes=sorted(scopes),
        commands=commands,
        notes=notes,
        coverage="Personal beta data/math, ledger, checkpoint/export and deployment guards. Broader historical diagnostics are manual-only and are not deployment gates.",
    )


def git_paths(root, *args):
    raw = subprocess.check_output(["git", *args], cwd=root)
    return {os.fsdecode(path) for path in raw.split(b"\0") if path}


def changed_paths(root):
    return sorted(
        git_paths(root, "diff", "--name-only", "--no-renames", "-z", "HEAD", "--")
        | git_paths(root, "ls-files", "--others", "--exclude-standard", "-z")
    )


def github(path):
    return subprocess.check_output(
        ["gh", "api", path], stderr=subprocess.PIPE, timeout=10
    )


def installed_release(repository, run_id):
    # Environment success alone includes publish-only runs and skipped releases.
    # Only the host receipt in the matching CI attempt proves deployment.
    prefix = f"repos/{repository}/actions"
    history = json.loads(
        github(
            f"{prefix}/workflows/ci.yml/runs?branch=main&status=completed&per_page=10"
        )
    )
    for run in history["workflow_runs"]:
        if str(run["id"]) == run_id:
            continue
        name = f"personal-beta-{run['id']}-{run['run_attempt']}"
        artifacts = json.loads(
            github(f"{prefix}/runs/{run['id']}/artifacts?name={name}")
        )["artifacts"]
        matches = [
            item for item in artifacts if item["name"] == name and not item["expired"]
        ]
        if len(matches) != 1:
            # The newest evidence is ambiguous. An older completion might omit
            # files reverted after this release, so select the broad baseline.
            raise ValueError(f"CI run {run['id']} has no usable deployment receipt")
        data = github(f"{prefix}/artifacts/{matches[0]['id']}/zip")
        with ZipFile(BytesIO(data)) as archive:
            receipt = json.loads(archive.read("release/metrics.json"))
        sha = run["head_sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", sha) or receipt["sha"] != sha:
            raise ValueError("Deployment receipt revision does not match its CI run")
        if (
            receipt["status"] == "PASS"
            and receipt["deployed"] is True
            and receipt["publish_only"] is False
        ):
            return sha, run["id"]
        if receipt["deployed"] is not False or "deploy" in receipt["phases"]:
            raise ValueError(
                f"CI run {run['id']} attempted a deployment without a confirmed result"
            )
    raise ValueError("No recent CI run confirmed a hosted deployment")


def release_input(repository, head, run_id, *, force_broad=False):
    selection = dict(head=head, paths=[], base=None, base_run=None, broad=True)
    if force_broad:
        return selection | {
            "reason": "Manual dispatch requested the broad release plan"
        }
    try:
        base, base_run = installed_release(repository, run_id)
        paths = set()
        if base != head:
            comparison = json.loads(
                github(f"repos/{repository}/compare/{base}...{head}?page=1&per_page=1")
            )
            if (
                comparison["status"] != "ahead"
                or comparison["merge_base_commit"]["sha"] != base
            ):
                raise ValueError("Installed revision is outside the candidate history")
            if len(comparison["files"]) >= 300:
                raise ValueError(
                    "Candidate comparison reached GitHub's 300-file response limit"
                )
            if not comparison["files"]:
                raise ValueError("Candidate comparison has no file evidence")
            for item in comparison["files"]:
                paths.add(item["filename"])
                if item["status"] == "renamed":
                    paths.add(item["previous_filename"])
        selection.update(paths=sorted(paths), base=base, base_run=base_run, broad=False)
    except (KeyError, TypeError, BadZipFile, OSError, subprocess.SubprocessError):
        selection["reason"] = (
            "Hosted deployment receipt or candidate comparison is unavailable"
        )
    except ValueError as error:
        selection["reason"] = str(error)
    return selection


def run_checks(commands, *, root=ROOT):
    """Pass lint and workflow checks, then join independent validation.

    Each subprocess retains its own reports. A validation failure never abandons
    its sibling: both results and elapsed times are collected before returning.
    """
    checks = []
    validation_names = {"secrets", "portable", "postgres"}

    def measured(item):
        name, command = item
        before = time.monotonic()
        error = None
        try:
            code = subprocess.run(command, cwd=root).returncode
        except (OSError, subprocess.SubprocessError) as exc:
            code = 1
            error = str(exc)
        result = dict(
            name=name,
            status="PASS" if code == 0 else "FAIL",
            seconds=round(time.monotonic() - before, 3),
            returncode=code,
        )
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
    parser.add_argument("--ci-input", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--paths", nargs="*")
    args = parser.parse_args(argv)
    decision = None
    if args.ci_input:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if head != os.environ["GITHUB_SHA"]:
            raise ValueError("Release planning must use the exact candidate revision")
        decision = release_input(
            os.environ["GITHUB_REPOSITORY"],
            head,
            os.environ["GITHUB_RUN_ID"],
            force_broad=os.environ.get("RELEASE_BROADEN_VALIDATION") == "true",
        )
    elif raw := os.environ.get("RELEASE_SELECTION"):
        decision = json.loads(raw)
        if decision["head"] != os.environ["GITHUB_SHA"]:
            raise ValueError(
                "Release validation must match the planned candidate revision"
            )
    elif os.environ.get("GITHUB_EVENT_PATH") and args.paths is None:
        raise ValueError(
            "GitHub release validation requires its prepared candidate selection"
        )
    paths = (
        decision["paths"]
        if decision
        else changed_paths(ROOT)
        if args.paths is None
        else args.paths
    )
    selected = plan(ROOT, paths, broad=bool(decision and decision["broad"]))
    if decision:
        selected["base"] = decision["base"]
        selected["base_run"] = decision["base_run"]
        selected["broad"] = decision["broad"]
        if decision["broad"]:
            selected["notes"].append("Broadened focused checks: " + decision["reason"])
        else:
            selected["notes"].append(
                f"Installed release comparison: {decision['base']} (CI run {decision['base_run']}) through {decision['head']}"
            )
    if args.ci_input:
        print(json.dumps(decision | {"browser": bool(selected["browser"])}))
        return 0
    if args.plan:
        print(json.dumps(selected, indent=2))
        return 0
    if args.browser:
        if not selected["browser"]:
            return 0
        output = ROOT / "test-results/fast-browser" / str(time.time_ns())
        return subprocess.run(
            [
                sys.executable,
                "scripts/ci/postgres.py",
                "--report-dir",
                str(output),
                "--fail-fast",
                "--tests",
                *selected["browser"],
            ],
            cwd=ROOT,
        ).returncode
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
