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
