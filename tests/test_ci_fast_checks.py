"""Personal beta checks select working data and deployment behavior."""

from pathlib import Path

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


def test_collection_changes_check_financial_guards_and_automatic_acquisition():
    result = selected("app/collection/experiment_acquisition.py")
    pure = command(result, "portable")
    assert "tests/test_sportsgameodds_ledger.py" in pure
    assert "tests/test_experiment_acquisition.py" in pure
    assert "tests/test_experiment_acquisition_sql.py" in command(result, "postgres")


def test_research_changes_check_immutable_inputs_and_reproducible_export():
    pure = command(selected("app/research/experiment_evidence.py"), "portable")
    assert "tests/test_ev_experiment_evidence.py" in pure
    assert "tests/test_experiment_api.py" in pure


def test_api_changes_check_passive_data_and_export_behavior():
    assert "tests/test_experiment_api.py" in command(
        selected("app/dashboard/experiment_api.py"), "portable"
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
