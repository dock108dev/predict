"""Required gates, assurance artifacts and observed workflow health."""

import json
from pathlib import Path
import tempfile
import unittest

from tests.ci_support import load


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
