"""JUnit, quality-result and failed-command reporting."""

import ast
import json
from pathlib import Path
import tempfile
import unittest

from tests.ci_support import load


def browser_cases():
    return [
        (f"browser_tests.{module}", f"{name}[{width}]")
        for module, name in (
            ("test_first_run", "test_first_use_without_credentials"),
            (
                "test_ranked_opportunities",
                "test_ev_updates_prices_without_reranking_or_displacing_a_reader",
            ),
            ("test_fee_desk", "test_ordinary_fee_desk"),
        )
        for width in (1440, 390)
    ]


class ReportingTests(unittest.TestCase):
    def test_behavior_rows_name_existing_test_cases(self):
        module = load("quality_report")
        root = Path(__file__).resolve().parents[1]
        for _, _, location, cases in module.BROWSER_BEHAVIOR + module.STORAGE_BEHAVIOR:
            package, file, *classes = location.split(".")
            nodes = ast.parse((root / package / f"{file}.py").read_text()).body
            for class_name in classes:
                nodes = next(
                    node.body
                    for node in nodes
                    if isinstance(node, ast.ClassDef) and node.name == class_name
                )
            defined = {
                node.name
                for node in nodes
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            self.assertEqual(
                {case for case in cases if case.partition("[")[0] not in defined},
                set(),
                location,
            )

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

    def test_interruption_preserves_existing_result_when_workflow_disagrees(self):
        module = load("interrupted")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            path = output / "metrics.json"
            original = '{"overall":"PASS"}'
            path.write_text(original)
            (output / "summary.md").write_text("original summary")
            self.assertFalse(
                module.ensure_report(output, {"offline": {"outcome": "cancelled"}})
            )
            self.assertEqual(path.read_text(), original)
            report = json.loads((output / "interruption.json").read_text())
            self.assertEqual(report["checks"][0]["status"], "CANCELLED")
            self.assertIn(
                "outcome and retained report disagree",
                (output / "interruption.md").read_text(),
            )

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
                '<testsuite><testcase classname="storage" name="roundtrip&lt;bad&gt;"><failure/></testcase></testsuite>'
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
            self.assertIn("storage::roundtrip&lt;bad&gt;", output.getvalue())
            self.assertNotIn("roundtrip<bad>", output.getvalue())
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

    def test_junit_declared_subtests_and_missing_failure_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "junit.xml"
            # pytest emits a single case for multiple unittest subtest outcomes.
            report.write_text(
                '<testsuites><testsuite tests="5" errors="0" failures="2" skipped="1">'
                "<testcase><failure/><failure/><skipped/></testcase>"
                '<testcase time="0.05"/>'
                "</testsuite></testsuites>"
            )
            _, counts, declared = load("reporting").junit(report)
            self.assertEqual(
                counts, {"tests": 2, "failed": 1, "skipped": 0, "seconds": None}
            )
            self.assertEqual(
                declared, {"tests": 5, "failures": 2, "errors": 0, "skipped": 1}
            )
            report.write_text(
                '<testsuite tests="1" failures="1"><testcase/></testsuite>'
            )
            with self.assertRaisesRegex(ValueError, "conflicts with the case evidence"):
                load("run_checks").junit_counts(report)
            report.write_text("<report><testcase/></report>")
            with self.assertRaisesRegex(ValueError, "Unexpected JUnit root"):
                load("run_checks").junit_counts(report)

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
                (
                    '<testsuite><testcase classname="storage" name="roundtrip&lt;bad&gt;"><failure/></testcase></testsuite>',
                    True,
                ),
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

    def test_offline_child_cannot_inherit_a_libpq_target(self):
        import os
        import sys
        from unittest.mock import patch

        command = [
            sys.executable,
            "-c",
            """
import os
from pathlib import Path
expected = Path(os.environ['TMPDIR']) / 'no-postgres'
assert os.environ['PREDICT_DB_SOCKET'] == os.environ['PGHOST'] == str(expected)
assert not expected.exists()
assert 'PGSERVICE' not in os.environ and 'PGHOSTADDR' not in os.environ
""",
        ]
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(
                os.environ,
                {
                    "PREDICT_DB_SOCKET": "/not-the-fixture",
                    "PGHOST": "other-host",
                    "PGSERVICE": "other-service",
                    "PGHOSTADDR": "192.0.2.1",
                },
            ),
        ):
            result = load("run_checks").execute("fixture", command, Path(folder))
        self.assertEqual(result["status"], "PASS")


class ProgressSummaryTests(unittest.TestCase):
    def test_fee_browser_summary_does_not_promote_missing_mobile_case(self):
        module = load("quality_report")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root / "browser/junit.xml"
            report.parent.mkdir()
            report.write_text(
                '<testsuite><testcase classname="browser_tests.test_fee_desk" '
                'name="test_ordinary_fee_desk[1440]"/></testsuite>'
            )
            summary, _, _ = module.render(
                {"browser": {"outcome": "success"}}, root, browser=True
            )
            self.assertIn("desktop and mobile widths | NOT RUN / PASS |", summary)
            report.write_text(
                '<testsuite><testcase classname="browser_tests.test_fee_desk" '
                'name="test_ordinary_fee_desk[1440]"/><testcase '
                'classname="browser_tests.test_fee_desk" name="test_ordinary_fee_desk[390]">'
                "<skipped/></testcase></testsuite>"
            )
            summary, _, _ = module.render(
                {"browser": {"outcome": "success"}}, root, browser=True
            )
            self.assertIn("desktop and mobile widths | PASS / SKIPPED |", summary)

    def test_required_browser_journey_rejects_duplicate_desktop_for_missing_mobile(
        self,
    ):
        module = load("quality_report")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root / "browser/junit.xml"
            report.parent.mkdir()
            cases = browser_cases()
            cases[-1] = cases[-2]
            report.write_text(
                "<testsuite>"
                + "".join(
                    f'<testcase classname="{group}" name="{name}"/>'
                    for group, name in cases
                )
                + "</testsuite>"
            )
            summary, records, failed = module.render(
                {"browser": {"outcome": "success"}}, root, browser=True
            )
            self.assertTrue(failed)
            self.assertEqual(records[0]["status"], "FAIL")
            self.assertIn("test_ordinary_fee_desk[390]", records[0]["reason"])
            self.assertIn("desktop and mobile widths | FAIL / NOT RUN |", summary)

    def test_duplicate_pass_cannot_mask_skipped_required_browser_case(self):
        module = load("quality_report")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root / "browser/junit.xml"
            report.parent.mkdir()
            cases = browser_cases()
            group, name = cases[-1]
            report.write_text(
                "<testsuite>"
                + f'<testcase classname="{group}" name="{name}"><skipped/></testcase>'
                + "".join(
                    f'<testcase classname="{group}" name="{name}"/>'
                    for group, name in cases
                )
                + "</testsuite>"
            )
            summary, records, failed = module.render(
                {"browser": {"outcome": "success"}}, root, browser=True
            )
            self.assertTrue(failed)
            self.assertIn("test_ordinary_fee_desk[390]", records[0]["reason"])
            self.assertIn("desktop and mobile widths | FAIL / PASS |", summary)

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
            alternate = root / "quality/uv-audit.json"
            alternate.write_text(path.read_text())
            for outcome, expected in (
                ("success", "PASS"),
                ("skipped", "SKIPPED"),
                ("cancelled", "CANCELLED"),
            ):
                with self.subTest(outcome=outcome):
                    _, records, failed = module.render(
                        {name: {"outcome": outcome} for name in ("audit", "uv_audit")},
                        root,
                        audit=True,
                    )
                    self.assertEqual(len(records), 2)
                    self.assertEqual(records[1]["status"], expected)
                    self.assertEqual(records[0]["status"], expected)
                    self.assertEqual(failed, outcome != "success")
            path.unlink()
            _, records, failed = module.render(
                {"audit": {"outcome": "success"}}, root, audit=True
            )
            self.assertTrue(failed)
            self.assertEqual(records[0]["status"], "FAIL")

            path.write_text(
                json.dumps({"dependencies": [{"name": "fixture", "vulns": []}]})
            )
            alternate.unlink()
            _, records, failed = module.render(
                {name: {"outcome": "success"} for name in ("audit", "uv_audit")},
                root,
                audit=True,
            )
            self.assertTrue(failed)
            self.assertEqual(records[1]["status"], "FAIL")
