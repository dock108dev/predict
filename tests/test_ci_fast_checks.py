"""Personal beta checks select working data and deployment behavior."""

from io import BytesIO
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

import pytest

from tests.ci_support import load

ROOT = Path(__file__).resolve().parents[1]


def selected(path):
    return load("fast_checks").plan(ROOT, [path])


def command(selection, name):
    return next(args for title, args in selection["commands"] if title == name)


def test_personal_checks_cover_exact_probability_cashflow_and_movement():
    pure = command(selected("README.md"), "portable")
    assert "tests/test_current_pregame_reference_policy.py" in pure
    assert "tests/test_pregame_valuation.py" in pure
    assert "tests/test_ev_movement.py" in pure


def test_migration_checks_fresh_schema_checkpoint_export_and_sql_health():
    sql = command(
        selected("app/storage/migrations/115_ev_first_observation_correction.sql"),
        "postgres",
    )
    assert "scripts/ci/postgres.py" in sql
    assert any(
        "both_checkpoints_share_dependencies_and_export_reproduces_offline" in arg
        for arg in sql
    )
    assert any(
        "test_http_health_checks_supported_sql_without_calculation" in arg
        for arg in sql
    )


def test_shared_sql_fixture_change_preserves_workspace_checks_and_clone_isolation():
    result = command(selected("tests/latest_board_fixture.py"), "postgres")
    for target in (
        "tests/test_current_pregame_sql.py::CurrentPregameSQL::test_http_health_checks_supported_sql_without_calculation",
        "tests/test_data_workspace_sql.py",
        "tests/test_ev_experiment_sql.py::ExperimentSQL::test_both_checkpoints_share_dependencies_and_export_reproduces_offline",
        "tests/test_ev_experiment_sql.py::ExperimentSQL::test_reference_scope_transition_preserves_old_policy_and_declared_checkpoint_requests",
        "tests/test_experiment_acquisition_sql.py",
        "tests/test_fee_mode_sql.py",
        "tests/test_fee_pricing_sql.py",
        "tests/test_market_board_sql.py",
        "tests/test_market_snapshot_arbs_sql.py",
        "tests/test_research_catalog_sql.py",
        "tests/test_sql_fixture_template.py",
    ):
        assert target in result


def test_collection_changes_check_financial_guards_and_automatic_acquisition():
    result = selected("app/collection/experiment_acquisition.py")
    pure = command(result, "portable")
    assert "tests/test_sportsgameodds_ledger.py" in pure
    assert "tests/test_experiment_acquisition.py" in pure
    assert "tests/test_experiment_acquisition_sql.py" in command(result, "postgres")


@pytest.mark.parametrize(
    "path", ("app/collection/original_receipts.py", "tests/test_original_receipts.py")
)
def test_original_receipt_changes_check_retention(path):
    assert "tests/test_original_receipts.py" in command(selected(path), "portable")


def test_research_changes_check_immutable_inputs_and_reproducible_export():
    pure = command(selected("app/research/experiment_evidence.py"), "portable")
    assert "tests/test_ev_experiment_evidence.py" in pure
    assert "tests/test_experiment_api.py" in pure


@pytest.mark.parametrize(
    "path", ["app/collection/sgo_nhl_scoring.py", "app/research/paper_results.py"]
)
def test_nhl_scoring_changes_check_exact_scores_and_later_period_proof(path):
    result = selected(path)
    assert "tests/test_sgo_nhl_scoring.py" in command(result, "portable")
    assert any(
        "test_same_score_nhl_outcomes_retain_new_period_proof" in target
        for target in command(result, "postgres")
    )


@pytest.mark.parametrize(
    "path",
    (
        "app/dashboard/research_workspace_api.py",
        "app/research/workspace.py",
        "app/research/market_census.py",
        "app/storage/store.py",
        "tests/test_research_offer_export_api.py",
    ),
)
def test_dated_offer_export_changes_check_streaming_and_digest(path):
    assert "tests/test_research_offer_export_api.py" in command(
        selected(path), "portable"
    )


@pytest.mark.parametrize(
    "path",
    (
        "app/collection/current_database.py",
        "app/collection/sportsgameodds_worker.py",
        "app/storage/sportsgameodds_reference.py",
        "app/comparison/reference_scope.py",
        "app/storage/migrations/071_sportsgameodds_reference.sql",
    ),
)
def test_sgo_admission_and_reference_changes_check_both_sql_contracts(path):
    sql = command(selected(path), "postgres")
    assert "tests/test_sportsgameodds_ingress_sql.py" in sql
    assert "tests/test_sportsgameodds_reference_sql.py" in sql


def test_prose_filenames_do_not_select_runtime_sql():
    module = load("fast_checks")
    paths = [
        "docs/engineering/mens-d1-coverage.md",
        "docs/market_census.md",
        "docs/issue_dispositions.md",
        "docs/nov23_audit.md",
        "mens_d1-follow-up.md",
    ]
    plan = module.plan(ROOT, paths)
    assert plan["paths"] == paths
    assert plan["scopes"] == []
    assert [name for name, _ in plan["commands"]] == [
        "lint",
        "workflow",
        "secrets",
        "portable",
    ]


def test_projection_migration_keeps_monitor_recovery_in_the_sql_plan():
    result = selected("app/storage/migrations/124_pregame_projection_recovery.sql")
    assert "tests/test_pregame_cohorts_sql.py" in command(result, "postgres")


def test_guarded_dispatch_includes_failed_application_commit_and_test_followup(
    monkeypatch,
):
    module = load("fast_checks")
    base = "77a0db899c7fbe19e63f3c3dcfae1cd18fe485df"
    failed = "c92208480a48709e7be5cf495811d8630ad4b2e7"
    followup = "c8793a5a76384f60be8c92188c4f8f68e8dcbda3"
    original = {
        "app/collection/experiment_acquisition.py",
        "app/collection/experiment_depth_stage.py",
        "app/collection/native_trading.py",
        "app/dashboard/opportunity_static/current/dashboard.js",
        "app/storage/migrations/129_experiment_depth_receipt_capacity.sql",
        "browser_tests/test_dashboard_workspace.py",
        "tests/test_experiment_depth_sql.py",
    }
    followup_path = "tests/test_catalog_admission.py"
    # Run 46107061746 failed focused checks on c9220848. The last completed
    # installation was 46092622283. Guarded dispatch 46107349422 previously
    # validated only c8793a5a's catalog fixture before deploying both commits.
    runs = [
        {"id": 46107061746, "head_sha": failed, "run_attempt": 1},
        {"id": 46092622283, "head_sha": base, "run_attempt": 1},
    ]
    receipts = {
        15247819391: dict(
            sha=failed,
            status="FAIL",
            deployed=False,
            publish_only=False,
            phases={"checks": 1},
        ),
        15241348428: dict(
            sha=base,
            status="PASS",
            deployed=True,
            publish_only=False,
            phases={"deploy": 1},
        ),
    }

    def github(path):
        if "workflows/ci.yml/runs" in path:
            assert "branch=main&status=completed" in path
            return json.dumps({"workflow_runs": runs}).encode()
        if "/runs/46107061746/artifacts" in path:
            return json.dumps(
                {
                    "artifacts": [
                        {
                            "id": 15247819391,
                            "name": "personal-beta-46107061746-1",
                            "expired": False,
                        }
                    ]
                }
            ).encode()
        if "/runs/46092622283/artifacts" in path:
            return json.dumps(
                {
                    "artifacts": [
                        {
                            "id": 15241348428,
                            "name": "personal-beta-46092622283-1",
                            "expired": False,
                        }
                    ]
                }
            ).encode()
        if path.endswith("/zip"):
            artifact = int(path.split("/")[-2])
            raw = BytesIO()
            with ZipFile(raw, "w") as archive:
                archive.writestr("release/metrics.json", json.dumps(receipts[artifact]))
            return raw.getvalue()
        head = path.split("...", 1)[1].split("?", 1)[0]
        assert f"/compare/{base}..." in path
        paths = original if head == failed else original | {followup_path}
        return json.dumps(
            {
                "status": "ahead",
                "merge_base_commit": {"sha": base},
                "files": [{"filename": p, "status": "modified"} for p in sorted(paths)],
            }
        ).encode()

    monkeypatch.setattr(module, "github", github)
    first = module.release_input("dock108dev/predict", failed, "46107061746")
    second = module.release_input("dock108dev/predict", followup, "46107349422")
    assert first["base"] == second["base"] == base
    assert second["base_run"] == 46092622283 and not second["broad"]
    assert set(first["paths"]) == original
    assert set(second["paths"]) == original | {followup_path}
    plan = module.plan(ROOT, second["paths"])
    assert plan["browser"] == ["browser_tests/test_dashboard_workspace.py"]
    assert followup_path in command(plan, "portable")
    assert "tests/test_experiment_depth_stage.py" in command(plan, "portable")
    assert "tests/test_experiment_acquisition_sql.py" in command(plan, "postgres")
    assert "tests/test_experiment_depth_sql.py" in command(plan, "postgres")
    assert module.HYBRID_REPLAY in command(plan, "postgres")

    # The fast push of c8793a5a also tried SSH and returned a failure. Its
    # metrics alone cannot establish pre-mutation refusal. The guarded
    # dispatch still selects the application and migration contracts.
    runs.insert(0, {"id": 46107344514, "head_sha": followup, "run_attempt": 1})
    receipts[15247968836] = dict(
        sha=followup,
        status="FAIL",
        deployed=False,
        publish_only=False,
        phases={"deploy": 1},
    )

    def attempted_prior_deploy(path):
        if "/runs/46107344514/artifacts" in path:
            return json.dumps(
                {
                    "artifacts": [
                        {
                            "id": 15247968836,
                            "name": "personal-beta-46107344514-1",
                            "expired": False,
                        }
                    ]
                }
            ).encode()
        return github(path)

    monkeypatch.setattr(module, "github", attempted_prior_deploy)
    ambiguous = module.release_input("dock108dev/predict", followup, "46107349422")
    assert ambiguous["broad"] and "46107344514" in ambiguous["reason"]
    plan = module.plan(ROOT, ambiguous["paths"], broad=True)
    assert "tests/test_experiment_acquisition_sql.py" in command(plan, "postgres")
    assert "tests/test_experiment_depth_sql.py" in command(plan, "postgres")
    assert "tests/test_paper_campaigns_sql.py" in command(plan, "postgres")


def test_manual_recovery_can_select_broad_checks_without_using_a_stale_receipt(
    monkeypatch,
):
    module = load("fast_checks")
    monkeypatch.setattr(module, "github", lambda path: pytest.fail(path))
    result = module.release_input(
        "dock108dev/predict", "b" * 40, "42", force_broad=True
    )
    assert result["broad"] and "Manual dispatch" in result["reason"]


@pytest.mark.parametrize(
    "comparison,expected",
    [
        (None, "unavailable"),
        ({"status": "diverged", "merge_base_commit": {"sha": "0" * 40}}, "outside"),
        (
            {
                "status": "ahead",
                "merge_base_commit": {"sha": "b" * 40},
                "files": [{}] * 300,
            },
            "limit",
        ),
    ],
)
def test_release_broadens_if_the_installed_diff_is_unavailable(
    monkeypatch, comparison, expected
):
    module = load("fast_checks")
    monkeypatch.setattr(module, "installed_release", lambda *_: ("b" * 40, 42))

    def github(path):
        assert "/compare/" in path
        if comparison is None:
            raise subprocess.TimeoutExpired("gh", 10)
        return json.dumps(comparison).encode()

    monkeypatch.setattr(module, "github", github)
    result = module.release_input("dock108dev/predict", "c" * 40, "43")
    assert result["broad"] and result["base"] is None and expected in result["reason"]
    plan = module.plan(ROOT, result["paths"], broad=True)
    assert "tests/test_experiment_depth_stage.py" in command(plan, "portable")
    assert "tests/test_experiment_depth_sql.py" in command(plan, "postgres")
    assert "browser_tests/test_dashboard_workspace.py" in plan["browser"]


def test_no_host_acknowledgment_uses_broad_focused_checks(monkeypatch):
    module = load("fast_checks")
    monkeypatch.setattr(
        module,
        "github",
        lambda path: (
            b'{"workflow_runs":[]}'
            if "workflows/ci.yml/runs" in path
            else pytest.fail(path)
        ),
    )
    result = module.release_input("dock108dev/predict", "b" * 40, "42")
    assert result["broad"] and result["paths"] == []
    assert "No recent CI run confirmed a hosted deployment" in result["reason"]


def test_exact_audit_path_mappings_run_in_the_owning_lane():
    module = load("fast_checks")
    assert module.ASSET_ALLOWLIST in command(
        selected("app/dashboard/workspace_app.py"), "portable"
    )
    assert "tests/test_experiment_depth_stage.py" in command(
        selected("app/collection/experiment_depth_stage.py"), "portable"
    )
    assert module.NOVIG_BINDING <= set(
        command(selected("app/collection/novig_experiment_depth.py"), "portable")
    )
    assert module.HYBRID_REPLAY in command(
        selected("app/research/paper_depth.py"), "postgres"
    )
    identity = selected("app/comparison/sgo_native_binding.py")
    assert "tests/test_sgo_native_binding.py" in command(identity, "portable")
    assert {
        "tests/test_sgo_native_catalog_sql.py",
        "tests/test_native_trading_sql.py",
    } <= set(command(identity, "postgres"))
    assert selected("app/dashboard/opportunity_static/current/dashboard.js")[
        "browser"
    ] == ["browser_tests/test_dashboard_workspace.py"]


def test_changed_test_files_use_correct_lanes():
    module = load("fast_checks")
    portable = "tests/test_catalog_admission.py"
    postgres = "tests/test_native_trading_sql.py"
    browser = "browser_tests/test_paper_campaign_integration.py"
    mixed = "tests/test_native_experiment_depth.py"
    plan = module.plan(ROOT, [portable, postgres, browser, mixed])
    assert portable in command(plan, "portable")
    assert mixed in command(plan, "portable")
    assert "--deselect=" + mixed + "::NativeReplacementSQL" in command(plan, "portable")
    assert postgres in command(plan, "postgres")
    assert mixed + "::NativeReplacementSQL" in command(plan, "postgres")
    assert postgres not in command(plan, "portable")
    assert plan["browser"] == [browser]


def test_local_focused_scope_includes_new_nonignored_files(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True)

    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    git("init", "-q")
    (tmp_path / ".gitignore").write_text(".local/\n")
    (tmp_path / "README.md").write_text("Initial\n")
    git("add", ".")
    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "Initial",
    )
    (tmp_path / "README.md").write_text("Edited\n")
    (tmp_path / "new source.py").touch()
    (tmp_path / ".local").mkdir()
    (tmp_path / ".local" / "private.json").touch()
    assert load("fast_checks").changed_paths(tmp_path) == ["README.md", "new source.py"]


def test_database_role_changes_check_sql_permissions_and_release_guards():
    result = selected("app/storage/database_roles.py")
    assert "tests/test_database_roles_sql.py" in command(result, "postgres")
    assert "tests/test_ci_fast_release.py" in command(result, "portable")


def test_api_changes_check_passive_data_and_export_behavior():
    assert "tests/test_experiment_api.py" in command(
        selected("app/dashboard/experiment_api.py"), "portable"
    )
    assert "tests/test_data_workspace_client.py" in command(
        selected("app/dashboard/opportunity_static/current/data.js"), "portable"
    )


def test_deploy_changes_check_rollback_healthy_services_and_private_configuration():
    result = selected("deploy/predict.Caddyfile")
    pure = command(result, "portable")
    assert "tests/test_ci_fast_release.py" in pure
    assert "tests/test_ci_image_cleanup.py" in pure
    assert (
        "tests/test_ci_deploy.py::test_proxy_reload_failure_restores_files_and_rolls_back_changed_web"
        in pure
    )
    assert (
        "tests/test_ci_deploy.py::test_reused_unhealthy_service_cannot_produce_success"
        in pure
    )
    assert command(result, "secrets")[1] == "scripts/ci/secret_scan.py"


def test_personal_check_selection_rejects_paths_outside_checkout():
    with pytest.raises(ValueError):
        selected("../credentials")


def test_secret_and_fixture_checks_run_concurrently_after_lint_and_workflow(
    monkeypatch,
):
    from threading import Barrier, Lock
    from types import SimpleNamespace

    module = load("fast_checks")
    parallel = {"secrets", "portable", "postgres"}
    barrier = Barrier(len(parallel))
    lock = Lock()
    events = []
    commands = [
        (name, [name])
        for name in ("lint", "workflow", "secrets", "portable", "postgres")
    ]

    def run(args, *, cwd):
        (name,) = args
        with lock:
            events.append(name)
            if name in parallel:
                assert events[:2] == ["lint", "workflow"]
        if name in parallel:
            # No independent command can finish until all have dispatched.
            barrier.wait(timeout=5)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    checks, code = module.run_checks(commands)
    assert code == 0
    assert [row["name"] for row in checks] == [name for name, _ in commands]
    assert all(row["status"] == "PASS" and row["seconds"] >= 0 for row in checks)


def test_failed_secret_scan_waits_for_sql_and_keeps_both_reports(monkeypatch):
    from threading import Event, Thread
    from types import SimpleNamespace

    module = load("fast_checks")
    scanner_finished = Event()
    postgres_started = Event()
    release_postgres = Event()
    postgres_finished = Event()
    returned = Event()
    result = []

    def run(args, *, cwd):
        (name,) = args
        if name == "secrets":
            scanner_finished.set()
            return SimpleNamespace(returncode=7)
        postgres_started.set()
        assert release_postgres.wait(timeout=5)
        postgres_finished.set()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)

    def execute():
        result.append(
            module.run_checks([("secrets", ["secrets"]), ("postgres", ["postgres"])])
        )
        returned.set()

    thread = Thread(target=execute)
    thread.start()
    try:
        assert scanner_finished.wait(timeout=5)
        assert postgres_started.wait(timeout=5)
        assert not returned.is_set()
    finally:
        release_postgres.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert postgres_finished.is_set()
    checks, code = result[0]
    assert code == 7
    assert [(row["name"], row["status"], row["returncode"]) for row in checks] == [
        ("secrets", "FAIL", 7),
        ("postgres", "PASS", 0),
    ]


def test_baseline_failure_refuses_validation_dispatch(monkeypatch):
    from types import SimpleNamespace

    module = load("fast_checks")
    ran = []

    def run(args, *, cwd):
        ran.append(args[0])
        return SimpleNamespace(returncode=3 if args[0] == "workflow" else 0)

    monkeypatch.setattr(module.subprocess, "run", run)
    checks, code = module.run_checks(
        [
            (name, [name])
            for name in ("lint", "workflow", "secrets", "portable", "postgres")
        ]
    )
    assert code == 3
    assert ran == ["lint", "workflow"]
    assert checks[-1]["status"] == "FAIL"


def test_subprocess_launch_failure_is_recorded_and_sibling_is_joined(monkeypatch):
    from types import SimpleNamespace

    module = load("fast_checks")
    ran = []

    def run(args, *, cwd):
        ran.append(args[0])
        if args[0] == "portable":
            raise OSError("fixture could not start validation")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    checks, code = module.run_checks(
        [("portable", ["portable"]), ("postgres", ["postgres"])]
    )
    assert code == 1
    assert set(ran) == {"portable", "postgres"}
    assert checks[0]["status"] == "FAIL"
    assert checks[0]["error"] == "fixture could not start validation"
    assert checks[1]["status"] == "PASS"
