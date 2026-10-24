"""Disposable CI isolation, tool selection and repository enforcement."""

import json
from pathlib import Path
import tempfile
import unittest

from tests.ci_support import load


class EnvironmentTests(unittest.TestCase):
    def test_package_source_excludes_ignored_local_inputs(self):
        import subprocess

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "app").mkdir()
            (root / ".gitignore").write_text("app/local.json\n")
            (root / "app/module.py").write_text("pass\n")
            (root / "app/local.json").write_text("ignored local evidence")
            output = Path(folder) / "build-source"
            load("package_smoke").copy_source(root, output)
            self.assertTrue((output / "app/module.py").is_file())
            self.assertFalse((output / "app/local.json").exists())

    def test_alternate_lock_export_rejects_unreviewed_sources_and_empty_hashes(self):
        from copy import deepcopy

        export = load("uv_audit_requirements").requirements
        package = dict(
            name="example",
            version="1.0",
            source={"registry": "https://pypi.org/simple"},
            wheels=[dict(hash="sha256:" + "a" * 64)],
        )
        self.assertIn("example==1.0 --hash=sha256:", export(dict(package=[package])))
        for changes in (
            {"source": {"git": "https://invalid"}},
            {"wheels": []},
            {"name": "--index-url"},
        ):
            value = deepcopy(package)
            value.update(changes)
            with self.assertRaises(ValueError):
                export(dict(package=[value]))

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

    def test_sql_runner_preserves_existing_reports_before_starting_cluster(self):
        from unittest.mock import patch

        module = load("postgres")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            evidence = root / "junit.xml"
            evidence.write_text("prior evidence")
            with (
                patch.object(
                    module, "postgres_tools", return_value=(root, "PostgreSQL 16", 16)
                ),
                patch.object(module.os, "geteuid", return_value=501),
                patch.object(module.subprocess, "run") as run,
                self.assertRaises(SystemExit) as error,
            ):
                module.main(["--report-dir", str(root)])
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()
            self.assertEqual(evidence.read_text(), "prior evidence")

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
            client_policy = root / "scripts/ci/browser-suites.json"
            valid = client_policy.read_text()
            client_policy.write_text(
                json.dumps(
                    dict(required=["test_unit.cjs", "test_unit.cjs"], deferred={})
                )
            )
            with self.assertRaisesRegex(ValueError, "Duplicate client"):
                module.validate(root)
            client_policy.write_text(
                json.dumps(dict(required=[], deferred={"test_unit.cjs": " "}))
            )
            with self.assertRaisesRegex(ValueError, "unexplained client"):
                module.validate(root)
            client_policy.write_text(valid)
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
