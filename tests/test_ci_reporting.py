"""Fail-closed reporting contracts, independent of provider/product state."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[1] / "scripts/ci" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReportingTests(unittest.TestCase):
    def test_primary_sql_rejects_accidental_older_postgres_selection(self):
        from unittest.mock import patch

        module = load("postgres")
        for allow_other in (False, True):
            with (
                self.subTest(allow_other=allow_other),
                patch.object(
                    module.subprocess,
                    "check_output",
                    side_effect=[
                        "/chosen/postgres/bin\n",
                        "postgres (PostgreSQL) 14.20\n",
                    ],
                ) as invoke,
            ):
                if allow_other:
                    binary, version, major = module.postgres_tools(
                        "/chosen/pg_config", allow_other=True
                    )
                    self.assertEqual(binary, Path("/chosen/postgres/bin"))
                    self.assertEqual(major, 14)
                    self.assertIn("14.20", version)
                else:
                    with self.assertRaisesRegex(
                        ValueError, "No cluster was initialized"
                    ):
                        module.postgres_tools("/chosen/pg_config")
                self.assertEqual(
                    invoke.call_args_list[0].args[0][0], "/chosen/pg_config"
                )

    def test_project_postgres_requires_tools_matching_existing_cluster(self):
        import os
        import shutil
        import subprocess

        source = Path(__file__).resolve().parents[1] / "scripts/project-postgres"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            (root / ".local/postgres").mkdir(parents=True)
            (root / ".local/postgres/PG_VERSION").write_text("14\n")
            launcher = root / "scripts/project-postgres"
            shutil.copyfile(source, launcher)
            for major in (14, 16):
                binary = root / str(major)
                binary.mkdir()
                for tool in ("postgres", "initdb", "pg_ctl", "psql", "createdb"):
                    output = (
                        f"postgres (PostgreSQL) {major}.1"
                        if tool == "postgres"
                        else f"{major}:{tool}"
                    )
                    executable = binary / tool
                    executable.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n")
                    executable.chmod(0o755)
                result = subprocess.run(
                    ["sh", str(launcher), "status"],
                    env=os.environ | {"PREDICT_PG_BIN": str(binary)},
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                with self.subTest(major=major):
                    if major == 14:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout.strip(), "14:pg_ctl")
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(result.stdout, "")
                        self.assertIn("No process changed", result.stderr)

    def test_client_fixture_uses_ci_interpreter_without_checkout_venv(self):
        from unittest.mock import patch
        import os
        import sys

        module = load("run_checks")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            source = output / "client.cjs"
            source.write_text(
                "const {execFileSync}=require('node:child_process');"
                "process.stdout.write(execFileSync(process.env.PYTHON,"
                "['-c','import sys; print(sys.executable)'],{encoding:'utf8'}));"
                "console.log('PASS');"
            )
            with patch.dict(os.environ, PYTHON="/missing/developer/.venv/bin/python"):
                result = module.execute("client", ["node", str(source)], output)
            self.assertEqual(result["status"], "PASS", result)
            self.assertIn(sys.executable, (output / "client.log").read_text())

    def test_empty_client_execution_cannot_qualify_as_a_passing_suite(self):
        module = load("run_checks")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            source = output / "test_empty.cjs"
            source.write_text("")
            record = module.execute(
                "test_empty", ["node", str(source)], output, timeout=10
            )
            self.assertEqual(record["status"], "FAIL")
            self.assertEqual(record["exit_code"], 0)
            self.assertIn("no completion result", record["reason"])

    def test_optional_resource_outage_preserves_unavailable_values(self):
        module = load("health")

        def failed(_path):
            raise OSError("telemetry unavailable")

        value = module.resource_sample(failed)
        self.assertIsNone(value["cache_bytes"])
        self.assertIsNone(value["artifact_sample_bytes"])
        self.assertEqual(set(value["resource_unavailable"]), {"cache", "artifacts"})

        def partial(path):
            return (
                {"active_caches_count": 2, "active_caches_size_in_bytes": 100}
                if path.endswith("usage")
                else {"total_count": 40, "artifacts": [{"size_in_bytes": 20}]}
            )

        value = module.resource_sample(partial)
        self.assertEqual(value["artifact_sample_bytes"], 20)
        self.assertEqual(value["artifact_total_count"], 40)
        self.assertEqual(value["cache_bytes"], 100)

    def test_interrupted_setup_retains_failure_without_invented_counts(self):
        module = load("interrupted")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            self.assertFalse(module.ensure_report(output))
            value = json.loads((output / "metrics.json").read_text())
            self.assertEqual(value["checks"][0]["status"], "NOT RUN")
            self.assertIsNone(value["counts"])
            self.assertFalse(module.ensure_report(output))

    def test_isolation_path_preserves_standard_library_secrets(self):
        import os
        import subprocess
        import sys

        root = Path(__file__).resolve().parents[1]
        environment = os.environ | {"PYTHONPATH": str(root / "scripts/ci")}
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import secrets; assert len(secrets.token_bytes(16)) == 16",
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_dependency_findings_cannot_report_zero_vulnerabilities(self):
        module = load("quality_report")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "quality").mkdir()
            (root / "package").mkdir()
            (root / "quality/junit.xml").write_text(
                "<testsuite><testcase/></testsuite>"
            )
            (root / "package/metrics.json").write_text(
                '{"status":"PASS","wheel_bytes":42}'
            )
            outcomes = {
                name: {"outcome": "success"} for name in ("source", "audit", "package")
            }
            for dependency in (
                {"name": "example"},
                {"name": "example", "vulns": {}},
                None,
            ):
                with self.subTest(dependency=dependency):
                    (root / "quality/audit.json").write_text(
                        json.dumps({"dependencies": [dependency]})
                    )
                    _, records, failed = module.render(outcomes, root)
                    self.assertTrue(failed)
                    self.assertEqual(records[1]["status"], "FAIL")

    def test_package_summary_preserves_measurement_and_reports_missing_setup(self):
        import contextlib
        import io
        import os
        from unittest.mock import patch

        module = load("quality_report")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "test-results/package/metrics.json"
            path.parent.mkdir(parents=True)
            measurement = {"status": "PASS", "wheel_bytes": 42}
            path.write_text(json.dumps(measurement))
            for exists, expected in [(True, 0), (False, 1)]:
                if not exists:
                    path.unlink()
                output = io.StringIO()
                with (
                    contextlib.chdir(root),
                    contextlib.redirect_stdout(output),
                    patch.object(
                        module.sys, "argv", ["quality_report.py", "--package"]
                    ),
                    patch.dict(
                        os.environ,
                        {"CHECK_OUTCOMES": '{"package":{"outcome":"success"}}'},
                        clear=True,
                    ),
                    patch.object(
                        module.importlib.metadata,
                        "version",
                        side_effect=module.importlib.metadata.PackageNotFoundError(
                            "missing setup"
                        ),
                    ),
                ):
                    self.assertEqual(module.main(), expected)
                metrics = json.loads(
                    (root / "test-results/package-summary/metrics.json").read_text()
                )
                self.assertEqual(
                    metrics["checks"][0]["status"], "PASS" if exists else "FAIL"
                )
                self.assertTrue(
                    all(value is None for value in metrics["tools"].values())
                )
                self.assertIn("## Package results", output.getvalue())
                if exists:
                    self.assertEqual(json.loads(path.read_text()), measurement)

    def test_quality_main_prints_failure_reason_and_retains_reports(self):
        import contextlib
        import io
        import os
        from unittest.mock import patch

        module = load("quality_report")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "test-results/postgres").mkdir(parents=True)
            (root / "test-results/postgres/junit.xml").write_text(
                "<testsuite><testcase><failure/></testcase></testsuite>"
            )
            output = io.StringIO()
            with (
                contextlib.chdir(root),
                contextlib.redirect_stdout(output),
                patch.object(module.sys, "argv", ["quality_report.py", "--postgres"]),
                patch.dict(
                    os.environ,
                    {"CHECK_OUTCOMES": '{"postgres": {"outcome": "failure"}}'},
                    clear=True,
                ),
                patch.object(module.importlib.metadata, "version", return_value="test"),
            ):
                self.assertEqual(module.main(), 1)
            self.assertIn("| postgres | FAIL |", output.getvalue())
            self.assertIn("failed or entirely skipped suite", output.getvalue())
            self.assertEqual(
                output.getvalue(),
                (root / "test-results/postgres/summary.md").read_text(),
            )
            metrics = json.loads(
                (root / "test-results/postgres/metrics.json").read_text()
            )
            self.assertEqual(metrics["checks"][0]["status"], "FAIL")

    def test_junit_counts_failures_skips_and_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "report.xml"
            p.write_text(
                '<testsuites><testsuite><testcase time="1"/><testcase time="2"><failure/></testcase><testcase time="0"><skipped/></testcase></testsuite></testsuites>'
            )
            self.assertEqual(
                load("run_checks").junit_counts(p),
                {"tests": 3, "failed": 1, "skipped": 1, "seconds": 3},
            )
            p.write_text("<testsuites/>")
            with self.assertRaises(ValueError):
                load("run_checks").junit_counts(p)
            p.write_text("bad")
            with self.assertRaises(Exception):
                load("run_checks").junit_counts(p)

    def test_quality_missing_failed_skipped_and_cancelled_cannot_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            for status in ("success", "failure", "skipped", "cancelled"):
                _, records, failed = load("quality_report").render(
                    {"postgres": {"outcome": status}}, Path(folder), True
                )
                self.assertTrue(failed)
                self.assertNotEqual(records[0]["status"], "PASS")

    def test_quality_pass_and_failed_junit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "postgres").mkdir()
            path = root / "postgres/junit.xml"
            for contents, expected in [
                ("<testsuite><testcase/></testsuite>", False),
                ("<testsuite><testcase><failure/></testcase></testsuite>", True),
                ("<testsuite><testcase><skipped/></testcase></testsuite>", True),
            ]:
                path.write_text(contents)
                self.assertEqual(
                    load("quality_report").render(
                        {"postgres": {"outcome": "success"}}, root, True
                    )[2],
                    expected,
                )

    def test_audit_outage_or_findings_remain_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "quality").mkdir()
            (root / "quality/junit.xml").write_text(
                "<testsuite><testcase/></testsuite>"
            )
            (root / "package").mkdir()
            (root / "package/metrics.json").write_text(
                json.dumps({"status": "PASS", "wheel_bytes": 1})
            )
            outcomes = {
                k: {"outcome": "success"} for k in ("source", "audit", "package")
            }
            p = root / "quality/audit.json"
            for deps, failed in [
                ([{"name": "x", "vulns": []}], False),
                ([{"name": "x", "vulns": [{"id": "injected"}]}], True),
                ([{"name": "x", "skip_reason": "outage"}], True),
                ([], True),
            ]:
                p.write_text(json.dumps({"dependencies": deps}))
                self.assertEqual(
                    load("quality_report").render(outcomes, root)[2], failed
                )
            p.write_text("malformed")
            self.assertTrue(load("quality_report").render(outcomes, root)[2])

    def test_summary_escapes_untrusted_fields(self):
        self.assertEqual(
            load("run_checks").safe("<script>|\n"), "&lt;script&gt;&#124; "
        )

    def test_nonzero_command_preserved_even_with_junit(self):
        import sys

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "injected.xml").write_text("<testsuite><testcase/></testsuite>")
            r = load("run_checks").execute(
                "injected",
                [sys.executable, "-c", "raise SystemExit(7)"],
                root,
                junit=True,
            )
            self.assertEqual(r["exit_code"], 7)
            self.assertEqual(r["status"], "FAIL")


class HealthTests(unittest.TestCase):
    def test_events_reruns_and_cancellations_do_not_fabricate_rate(self):
        from datetime import datetime, timezone

        base = dict(
            name="CI",
            status="completed",
            created_at="2026-10-06T00:00:00Z",
            run_started_at="2026-10-06T00:00:01Z",
            job_completed_at="2026-10-06T00:00:11Z",
        )
        rows = [
            dict(base, event="push", conclusion="success", run_attempt=1),
            dict(base, event="push", conclusion="failure", run_attempt=1),
            dict(base, event="push", conclusion="success", run_attempt=2),
            dict(base, event="push", conclusion="cancelled", run_attempt=1),
            dict(base, event="pull_request", conclusion="success", run_attempt=1),
        ]
        result = load("health").analyze(
            rows, datetime(2026, 10, 7, tzinfo=timezone.utc)
        )
        self.assertEqual(result["events"]["push"]["first_attempt_pass_rate"], 0.5)
        self.assertEqual(result["events"]["push"]["rerun_runs"], 1)
        self.assertEqual(result["events"]["push"]["cancelled"], 1)
        self.assertEqual(result["events"]["pull_request"]["first_attempt_pass_rate"], 1)
        self.assertIsNone(result["events"]["push"]["p95_elapsed_seconds"])
        self.assertIsNone(result["queue_seconds"])

    def test_empty_or_old_sample_stays_unavailable(self):
        from datetime import datetime, timezone

        result = load("health").analyze([], datetime(2026, 10, 7, tzinfo=timezone.utc))
        self.assertIsNone(result["events"]["push"]["first_attempt_pass_rate"])


class MetricsTests(unittest.TestCase):
    def test_unreached_required_check_cannot_make_overall_pass(self):
        import time

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = [
                dict(
                    name="required", status="NOT RUN", tests=None, reason="not reached"
                )
            ]
            load("run_checks").write_report(root, records, time.monotonic())
            result = json.loads((root / "metrics.json").read_text())
            self.assertEqual(result["overall"], "NOT RUN")
            self.assertIsNone(result["coverage"])
            self.assertIsNone(result["baseline"])
            self.assertIn("pytest", result["tools"])
            records[0].update(status="FAIL")
            load("run_checks").write_report(root, records, time.monotonic())
            self.assertEqual(
                json.loads((root / "metrics.json").read_text())["overall"], "FAIL"
            )


class IsolationTests(unittest.TestCase):
    def test_child_interpreters_reject_archive_owner_state_and_remote_network(self):
        import os
        import subprocess
        import sys

        scripts = Path(__file__).resolve().parents[1] / "scripts/ci"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = os.environ.copy()
            env["PREDICT_CI_ISOLATED_ROOT"] = str(root)
            env["PYTHONPATH"] = str(scripts)
            env.pop("PREDICT_CI_REPORT_ROOT", None)
            attempts = [
                "open('evidence/missing.json')",
                "open('examples/missing.json')",
                "open('.env')",
                "open('.local/owner-state.json')",
                "import socket; socket.socket().connect(('192.0.2.1', 443))",
            ]
            for code in attempts:
                with self.subTest(code=code):
                    result = subprocess.run(
                        [sys.executable, "-c", code],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("PermissionError", result.stderr)
                    self.assertIn("CI", result.stderr)
            for code in [
                "open('authored.json','w').write('{}')",
                "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); s.close()",
            ]:
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_node_browser_boundary_blocks_archive_and_private_reads(self):
        import os
        import subprocess

        scripts = Path(__file__).resolve().parents[1] / "scripts/ci"
        with tempfile.TemporaryDirectory() as directory:
            env = os.environ.copy()
            env["PREDICT_CI_ISOLATED_ROOT"] = directory
            for file in [
                "evidence/missing.json",
                "examples/missing.json",
                ".env",
                ".local/state.json",
            ]:
                with self.subTest(file=file):
                    result = subprocess.run(
                        [
                            "node",
                            "--require",
                            str(scripts / "node-isolation.cjs"),
                            "-e",
                            'require("node:fs").readFileSync(' + json.dumps(file) + ")",
                        ],
                        cwd=directory,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Offline CI", result.stderr)


class SuiteContractTests(unittest.TestCase):
    def test_unclassified_test_and_stale_archive_selector_fail(self):
        module = load("validate_contract")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts/ci").mkdir(parents=True)
            (root / "tests").mkdir()
            (root / "tests/test_unit.py").write_text(
                "class Cases:\n def test_existing(self): pass\n"
            )
            (root / "tests/test_unit.cjs").write_text("")
            (root / "scripts/ci/suites.json").write_text(
                json.dumps([dict(name="unit", tests=["tests/test_unit.py"])])
            )
            policy = dict(deferred={}, quality=[], archival_nodes={})
            path = root / "scripts/ci/python-policy.json"
            path.write_text(json.dumps(policy))
            (root / "scripts/ci/browser-suites.json").write_text(
                json.dumps(dict(required=["test_unit.cjs"], deferred={}))
            )
            module.validate(root)
            added = root / "tests/test_new.py"
            added.write_text("")
            with self.assertRaisesRegex(ValueError, "classification drift"):
                module.validate(root)
            added.unlink()
            policy["archival_nodes"]["tests/test_unit.py::Cases::test_missing"] = (
                "old oracle"
            )
            path.write_text(json.dumps(policy))
            with self.assertRaisesRegex(ValueError, "Stale archival node"):
                module.validate(root)


class EnforcementTests(unittest.TestCase):
    def test_successful_command_with_missing_or_bad_coverage_is_failure(self):
        import sys

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            module = load("run_checks")
            for text in (None, "{}", '{"totals":{"percent_covered":NaN}}'):
                if text is not None:
                    (root / "coverage.json").write_text(text)
                result = module.execute(
                    "coverage-json", [sys.executable, "-c", "pass"], root
                )
                self.assertEqual(result["status"], "FAIL")
                self.assertEqual(result["exit_code"], 0)
            result = module.execute(
                "coverage-xml", [sys.executable, "-c", "pass"], root
            )
            self.assertEqual(result["status"], "FAIL")

    def test_required_skip_fails_and_explained_archival_skip_is_allowed(self):
        import time

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            module = load("run_checks")
            for required, expected in ((True, "FAIL"), (False, "PASS")):
                records = [
                    dict(
                        name="skip",
                        status="SKIPPED",
                        required=required,
                        tests=None,
                        reason="archival",
                    )
                ]
                module.write_report(root, records, time.monotonic())
                self.assertEqual(
                    json.loads((root / "metrics.json").read_text())["overall"], expected
                )

    def test_expanded_quality_requires_each_static_step(self):
        with tempfile.TemporaryDirectory() as folder:
            _, records, failed = load("quality_report").render(
                {}, Path(folder), expanded=True
            )
            self.assertTrue(failed)
            self.assertEqual(
                [r["name"] for r in records][-4:],
                ["lint", "workflow", "docs", "secrets"],
            )
            self.assertTrue(all(r["status"] == "NOT RUN" for r in records))

    def test_package_asset_contract_rejects_missing_new_assets_and_stale_code(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            asset = root / "app/dashboard/current/ev.js"
            asset.parent.mkdir(parents=True)
            asset.write_text("")
            validate = load("package_smoke").validate_wheel
            validate(["app/dashboard/current/ev.js"], root)
            for names in (
                [],
                ["app/dashboard/current/ev.js", "app/dashboard/u0_preview.py"],
            ):
                with self.assertRaises(ValueError):
                    validate(names, root)

    def test_health_fetches_only_current_window_and_exact_attempt_jobs(self):
        from datetime import datetime, timezone

        now = datetime(2026, 10, 10, tzinfo=timezone.utc)
        base = dict(
            name="CI",
            status="completed",
            event="push",
            conclusion="success",
            run_attempt=2,
            created_at="2026-10-09T00:00:00Z",
            run_started_at="2026-10-09T00:00:01Z",
            id=1,
        )
        paths = []

        def fetch(path):
            paths.append(path)
            if path.startswith("/actions/workflows/ci.yml/runs?"):
                return dict(
                    workflow_runs=[
                        base,
                        dict(base, id=2, created_at="2026-08-01T00:00:00Z"),
                    ]
                )
            if path == "/actions/runs/1/attempts/1":
                return dict(id=1, run_attempt=1, conclusion="failure")
            return dict(
                total_count=2,
                jobs=[
                    dict(
                        started_at="2026-10-09T00:00:01Z",
                        completed_at="2026-10-09T00:00:11Z",
                        steps=[],
                    )
                ],
            )

        metrics, _ = load("health").collect(fetch, now)
        self.assertEqual(
            paths,
            [
                "/actions/workflows/ci.yml/runs?per_page=30&status=completed&created=%3E%3D2026-09-10",
                "/actions/runs/1/attempts/1",
                "/actions/runs/1/attempts/2/jobs?per_page=100",
            ],
        )
        self.assertEqual(metrics["ci_runs"], 1)
        self.assertEqual(metrics["incomplete_job_samples"], 1)
        self.assertIsNone(metrics["runner_minutes"])
        self.assertEqual(metrics["events"]["push"]["duration_sample"], 0)

    def test_advisory_outage_retains_unavailable_report_without_failing_correctness(
        self,
    ):
        import contextlib
        import os
        from unittest.mock import patch

        with (
            tempfile.TemporaryDirectory() as folder,
            contextlib.chdir(folder),
            patch.dict(os.environ, {}, clear=True),
        ):
            load("health").main()
            metrics = json.loads(Path("test-results/health/metrics.json").read_text())
            self.assertEqual(metrics["status"], "UNAVAILABLE")
            self.assertIsNone(metrics["runner_minutes"])


class ProgressSummaryTests(unittest.TestCase):
    def test_progress_replaces_step_summary_and_keeps_final_failure(self):
        import os
        import time
        from unittest.mock import patch

        module = load("run_checks")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            summary = root / "github-summary.md"
            records = [{"name": "behavior", "status": "NOT RUN", "tests": None}]
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
                module.write_report(root, records, time.monotonic())
                records[0].update(status="FAIL", reason="bounded fixture failure")
                module.write_report(root, records, time.monotonic())
            self.assertEqual(summary.read_text(), (root / "summary.md").read_text())
            self.assertEqual(summary.read_text().count("## Offline contract"), 1)
            self.assertIn("bounded fixture failure", summary.read_text())
            self.assertIn("Offline contract — FAIL", summary.read_text())


class ScheduledAuditTests(unittest.TestCase):
    def test_audit_only_summary_requires_findings_and_preserves_outcomes(self):
        module = load("quality_report")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "quality").mkdir()
            path = root / "quality/audit.json"
            path.write_text(
                json.dumps({"dependencies": [{"name": "fixture", "vulns": []}]})
            )
            for outcome, expected in (
                ("success", "PASS"),
                ("skipped", "SKIPPED"),
                ("cancelled", "CANCELLED"),
            ):
                with self.subTest(outcome=outcome):
                    _, records, failed = module.render(
                        {"audit": {"outcome": outcome}}, root, audit=True
                    )
                    self.assertEqual(len(records), 1)
                    self.assertEqual(records[0]["status"], expected)
                    self.assertEqual(failed, outcome != "success")
            path.unlink()
            _, records, failed = module.render(
                {"audit": {"outcome": "success"}}, root, audit=True
            )
            self.assertTrue(failed)
            self.assertEqual(records[0]["status"], "FAIL")


class RequiredGateTests(unittest.TestCase):
    def test_same_run_failures_skips_cancellation_missing_and_malformed_fail(self):
        gate = load("gate")
        passing = {name: {"result": "success"} for name in gate.REQUIRED}
        self.assertTrue(gate.evaluate(passing)[0])
        for status in ("failure", "skipped", "cancelled", "NOT RUN"):
            with self.subTest(status=status):
                self.assertFalse(
                    gate.evaluate(dict(passing, browser={"result": status}))[0]
                )
        self.assertFalse(gate.evaluate({})[0])
        self.assertFalse(gate.evaluate(dict(passing, browser=None))[0])

    def test_browser_report_failure_and_missing_cannot_pass(self):
        report = load("quality_report")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertTrue(
                report.render({"browser": {"outcome": "success"}}, root, browser=True)[
                    2
                ]
            )
            (root / "browser").mkdir()
            (root / "browser/junit.xml").write_text(
                "<testsuite><testcase/></testsuite>"
            )
            self.assertFalse(
                report.render({"browser": {"outcome": "success"}}, root, browser=True)[
                    2
                ]
            )
            self.assertTrue(
                report.render({"browser": {"outcome": "skipped"}}, root, browser=True)[
                    2
                ]
            )

    def test_lock_root_drift_and_missing_backend_are_explicit_failures(self):
        import shutil
        from unittest.mock import patch

        module = load("validate_lock")
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            temp = Path(folder)
            for name in (
                "pyproject.toml",
                "requirements-ci.in",
                "requirements-ci.txt",
                "requirements-browser.in",
                "requirements-browser.txt",
            ):
                shutil.copy2(root / name, temp / name)
            module.validate(temp)
            lock = temp / "requirements-ci.txt"
            lock.write_text(
                lock.read_text().replace("setuptools==", "missing-backend==")
            )
            with self.assertRaisesRegex(ValueError, "setuptools"):
                module.validate(temp)
            shutil.copy2(root / "requirements-ci.txt", lock)
            browser = temp / "requirements-browser.txt"
            browser.write_text(
                browser.read_text().replace("playwright==", "missing-browser==")
            )
            with self.assertRaisesRegex(ValueError, "playwright"):
                module.validate(temp)

    def test_project_docs_reject_missing_private_and_escaping_links(self):
        module = load("docs")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            guide = root / "guide.md"
            from unittest.mock import patch

            with patch.object(module, "DOCUMENTS", ("guide.md",)):
                guide.write_text("[source](missing.py)")
                with self.assertRaisesRegex(ValueError, "Missing/escaping"):
                    module.validate(root)
                (root / "missing.py").write_text("")
                module.validate(root)
                guide.write_text("[project](.) [source](missing.py)")
                module.validate(root)
                (root / "test-results").mkdir()
                (root / "test-results/old.json").write_text("{}")
                guide.write_text("[local](test-results/old.json)")
                with self.assertRaisesRegex(ValueError, "Local-only"):
                    module.validate(root)
                guide.write_text("[outside](../README.md)")
                with self.assertRaisesRegex(ValueError, "Missing/escaping"):
                    module.validate(root)
                guide.write_text("Use /Users/someone/Desktop/tool.py")
                with self.assertRaisesRegex(ValueError, "Personal filesystem"):
                    module.validate(root)
                guide.write_text("[guide](notes.md)")
                (root / "notes.md").write_text("private notes")
                with self.assertRaisesRegex(ValueError, "Local-only"):
                    module.validate(root)


class AssuranceContractTests(unittest.TestCase):
    def test_selected_jobs_require_success_and_only_unselected_jobs_may_skip(self):
        module = load("assurance_report")
        for scope, selected in module.SCOPES.items():
            needs = {
                name: {"result": "success" if name in selected else "skipped"}
                for name in ("compatibility", "postgres", "security")
            }
            needs["health"] = {"result": "failure"}
            passed, records = module.evaluate(scope, needs)
            self.assertTrue(passed)
            self.assertEqual(
                sum(r["status"] == "N/A" for r in records), 3 - len(selected)
            )
            for name in selected:
                for failure in ("failure", "cancelled", "skipped", None):
                    changed = dict(needs, **{name: {"result": failure}})
                    self.assertFalse(module.evaluate(scope, changed)[0])
            self.assertFalse(module.evaluate(scope, {})[0])
        self.assertFalse(module.evaluate("untrusted", {})[0])

    def test_invalid_junit_durations_cannot_publish_a_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "browser/junit.xml"
            path.parent.mkdir()
            for duration in ("NaN", "inf", "-1", "invalid"):
                path.write_text(f'<testsuite><testcase time="{duration}"/></testsuite>')
                with self.assertRaises(ValueError):
                    load("run_checks").junit_counts(path)
                _, records, failed = load("quality_report").render(
                    {"browser": {"outcome": "success"}}, root, browser=True
                )
                self.assertTrue(failed)
                self.assertEqual(records[0]["status"], "FAIL")

    def test_reviewed_pdf_is_required_but_unrelated_pdf_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pdf = root / "app/fixtures/native-scoring-scope/rules.pdf"
            pdf.parent.mkdir(parents=True)
            pdf.write_bytes(b"%PDF-test")
            validate = load("package_smoke").validate_wheel
            validate([pdf.relative_to(root).as_posix()], root)
            for names in ([], [pdf.relative_to(root).as_posix(), "app/unreviewed.pdf"]):
                with self.assertRaises(ValueError):
                    validate(names, root)


class PartialHealthTests(unittest.TestCase):
    def test_one_jobs_api_outage_preserves_other_measurements(self):
        from datetime import datetime, timezone

        base = dict(
            name="CI",
            status="completed",
            event="push",
            conclusion="failure",
            run_attempt=1,
            created_at="2026-10-09T00:00:00Z",
            run_started_at="2026-10-09T00:00:01Z",
        )

        def fetch(path):
            if "workflows/ci.yml/runs?" in path:
                return {"workflow_runs": [dict(base, id=1), dict(base, id=2)]}
            if "/runs/1/" in path:
                raise TimeoutError("unavailable")
            return dict(
                total_count=1,
                jobs=[
                    dict(
                        started_at="2026-10-09T00:00:02Z",
                        completed_at="2026-10-09T00:00:12Z",
                        steps=[],
                    )
                ],
            )

        metrics, runs = load("health").collect(
            fetch, datetime(2026, 10, 10, tzinfo=timezone.utc)
        )
        self.assertEqual(metrics["incomplete_job_samples"], 1)
        self.assertAlmostEqual(metrics["runner_minutes"], 10 / 60)
        self.assertEqual(metrics["queue_seconds"]["median"], 2)
        self.assertEqual(runs[0]["jobs_unavailable"], "TimeoutError")

    def test_recovered_rerun_counts_observed_failed_first_attempt(self):
        from datetime import datetime, timezone

        run = dict(
            name="CI",
            status="completed",
            event="pull_request",
            conclusion="success",
            run_attempt=2,
            first_attempt_conclusion="failure",
            created_at="2026-10-09T00:00:00Z",
        )
        metric = load("health").analyze(
            [run], datetime(2026, 10, 10, tzinfo=timezone.utc)
        )["events"]["pull_request"]
        self.assertEqual(metric["first_attempt_pass_rate"], 0)
        self.assertEqual(metric["observed_rerun_recoveries"], 1)


class AssuranceArtifactTests(unittest.TestCase):
    def test_summary_persists_scoped_na_and_failed_requested_job(self):
        import contextlib
        import os
        from unittest.mock import patch

        for outcome, expected in (("success", 0), ("failure", 1)):
            with tempfile.TemporaryDirectory() as folder, contextlib.chdir(folder):
                needs = {
                    name: {"result": "skipped"}
                    for name in ("compatibility", "postgres", "health")
                }
                needs["security"] = {"result": outcome}
                with patch.dict(
                    os.environ,
                    {
                        "ASSURANCE_SCOPE": "security",
                        "NEEDS_JSON": json.dumps(needs),
                        "GITHUB_SHA": "candidate",
                        "CI_RUN_URL": "<unsafe>|`text`",
                        "GITHUB_STEP_SUMMARY": "summary.md",
                    },
                    clear=True,
                ):
                    self.assertEqual(load("assurance_report").main(), expected)
                value = json.loads(
                    Path("test-results/assurance/metrics.json").read_text()
                )
                text = Path("summary.md").read_text()
                self.assertEqual(value["tested_sha"], "candidate")
                self.assertIn("N/A", text)
                self.assertNotIn("<unsafe>", text)
                self.assertIn("&lt;unsafe&gt;&#124;&#96;text&#96;", text)
                self.assertEqual(
                    text, Path("test-results/assurance/summary.md").read_text()
                )


class SecretControlIsolationTests(unittest.TestCase):
    def test_controls_do_not_read_application_or_retained_fixture_files(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch

        with patch.dict(sys.modules, {"export": SimpleNamespace(export=None)}):
            module = load("secret_scan")
        original_read = Path.read_text

        def read_report_only(path, *args, **kwargs):
            self.assertEqual(path.name, "report.json")
            return original_read(path, *args, **kwargs)

        def scan(command, **kwargs):
            source = Path(command[2])
            files = sorted(p for p in source.rglob("*") if p.is_file())
            self.assertEqual(len(files), 3)
            report = Path(command[command.index("--report-path") + 1])
            report.write_text(
                json.dumps([dict(File=str(p), StartLine=2) for p in files])
            )
            return SimpleNamespace(returncode=1)

        with (
            patch.object(module.subprocess, "run", side_effect=scan),
            patch.object(Path, "read_text", read_report_only),
        ):
            module.verify_rules(Path("gitleaks"), Path(".gitleaks.toml"))
