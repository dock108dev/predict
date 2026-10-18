"""JUnit, quality-result and failed-command reporting."""

import json
from pathlib import Path
import tempfile
import unittest

from tests.ci_support import load


class ReportingTests(unittest.TestCase):
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
