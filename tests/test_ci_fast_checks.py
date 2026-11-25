"""Personal beta checks select working data and deployment behavior."""

from pathlib import Path
import subprocess

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


def test_validation_dispatches_concurrently_only_after_serial_baseline(monkeypatch):
    from threading import Barrier, Lock
    from types import SimpleNamespace

    module = load("fast_checks")
    barrier = Barrier(2)
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
            if name in ("portable", "postgres"):
                assert events[:3] == ["lint", "workflow", "secrets"]
        if name in ("portable", "postgres"):
            # Neither command can finish until both have actually dispatched.
            barrier.wait(timeout=5)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    checks, code = module.run_checks(commands)
    assert code == 0
    assert [row["name"] for row in checks] == [name for name, _ in commands]
    assert all(row["status"] == "PASS" and row["seconds"] >= 0 for row in checks)


def test_failed_validation_waits_for_sibling_and_retains_both_reports(monkeypatch):
    from threading import Event, Thread
    from types import SimpleNamespace

    module = load("fast_checks")
    portable_finished = Event()
    postgres_started = Event()
    release_postgres = Event()
    postgres_finished = Event()
    returned = Event()
    result = []

    def run(args, *, cwd):
        (name,) = args
        if name == "portable":
            portable_finished.set()
            return SimpleNamespace(returncode=7)
        postgres_started.set()
        assert release_postgres.wait(timeout=5)
        postgres_finished.set()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)

    def execute():
        result.append(
            module.run_checks([("portable", ["portable"]), ("postgres", ["postgres"])])
        )
        returned.set()

    thread = Thread(target=execute)
    thread.start()
    try:
        assert portable_finished.wait(timeout=5)
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
        ("portable", "FAIL", 7),
        ("postgres", "PASS", 0),
    ]


def test_baseline_failure_refuses_validation_dispatch(monkeypatch):
    from types import SimpleNamespace

    module = load("fast_checks")
    ran = []

    def run(args, *, cwd):
        ran.append(args[0])
        return SimpleNamespace(returncode=3 if args[0] == "secrets" else 0)

    monkeypatch.setattr(module.subprocess, "run", run)
    checks, code = module.run_checks(
        [
            (name, [name])
            for name in ("lint", "workflow", "secrets", "portable", "postgres")
        ]
    )
    assert code == 3
    assert ran == ["lint", "workflow", "secrets"]
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
