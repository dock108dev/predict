"""Required gates, assurance artifacts and observed workflow health."""

import json
from pathlib import Path
import tempfile
import unittest

from tests.ci_support import load
from tests.test_ci_reporting import browser_cases


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

    def test_elapsed_measurement_excludes_delayed_rerun_but_counts_recovery(self):
        from datetime import datetime, timezone

        module = load("health")
        run = dict(
            name="CI",
            status="completed",
            event="pull_request",
            conclusion="success",
            run_attempt=2,
            first_attempt_conclusion="failure",
            created_at="2026-10-06T00:00:00Z",
            run_started_at="2026-10-06T00:00:01Z",
            job_completed_at="2026-10-06T00:00:11Z",
        )
        metrics = module.analyze([run], datetime(2026, 10, 7, tzinfo=timezone.utc))
        values = metrics["events"]["pull_request"]
        self.assertIsNone(values["median_elapsed_seconds"])
        self.assertEqual(values["observed_rerun_recoveries"], 1)
        summary = module.render_summary(dict(metrics, status="PASS"))
        self.assertIn("What was tested and why it matters", summary)
        self.assertIn("1 / 1", summary)


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
                "<testsuite>"
                + "".join(
                    f'<testcase classname="{group}" name="{name}"/>'
                    for group, name in browser_cases()
                )
                + "</testsuite>"
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

    def test_project_docs_reject_links_to_an_ignored_local_artifact(self):
        from subprocess import run
        from unittest.mock import patch

        module = load("docs")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = "diagnostics.json"
            (root / ".gitignore").write_text(f"/{artifact}\n")
            (root / artifact).write_text("{}\n")
            (root / "guide.md").write_text(f"[Diagnostics]({artifact})\n")
            run(["git", "init", "-q"], cwd=root, check=True)
            run(["git", "add", "-f", "--", artifact], cwd=root, check=True)

            with patch.object(module, "DOCUMENTS", ("guide.md",)):
                module.validate(root)
                run(
                    ["git", "rm", "-q", "--cached", "--", artifact],
                    cwd=root,
                    check=True,
                )
                self.assertTrue((root / artifact).is_file())
                with self.assertRaisesRegex(ValueError, "Local-only.*diagnostics.json"):
                    module.validate(root)


class AssuranceContractTests(unittest.TestCase):
    def test_selected_jobs_require_success_and_only_unselected_jobs_may_skip(self):
        module = load("assurance_report")
        for scope, selected in module.SCOPES.items():
            needs = {
                name: {"result": "success" if name in selected else "skipped"}
                for name in ("postgres", "security")
            }
            needs["health"] = {"result": "failure"}
            passed, records = module.evaluate(scope, needs)
            self.assertTrue(passed)
            self.assertEqual(
                sum(r["status"] == "N/A" for r in records), 2 - len(selected)
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
                needs = {name: {"result": "skipped"} for name in ("postgres", "health")}
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


class ReadinessSignalsTests(unittest.TestCase):
    def test_changed_coverage_keeps_missing_branches_and_unmeasured_files_distinct(
        self,
    ):
        evidence = load("signals_evidence")
        changes = {
            "app/a.py": [(8, 3)],
            "app/new.py": [(1, 2)],
            "app/removed.py": [(8, 0)],
        }
        info = {
            "executed_lines": [1, 8, 20],
            "missing_lines": [9, 15],
            "executed_branches": [[8, 9], [1, 2]],
            "missing_branches": [[8, 10], [15, 16]],
        }
        result = evidence.changed_coverage({"app/a.py": info}, changes)
        self.assertEqual(result["lines"], {"covered": 1, "total": 2, "percent": 50})
        self.assertEqual(result["branches"], {"covered": 1, "total": 2, "percent": 50})
        self.assertEqual(result["files"][0]["missing_branches"], [[8, 10]])
        self.assertEqual(result["unmeasured"], ["app/new.py"])
        self.assertIsNone(evidence.changed_coverage({}, None))

    def test_evidence_uses_same_commit_and_reports_skipped_missing_and_failed_cases(
        self,
    ):
        signals = load("readiness_signals")
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for lane, attempt, suffix, tested in (
                ("ci-browser", 1, "", sha),
                ("ci-browser", 2, "", "b" * 40),
                ("storage", 2, "-2", sha),
            ):
                folder = root / f"{lane}-19-{attempt}{suffix}"
                folder.mkdir()
                (folder / "metrics.json").write_text(
                    json.dumps(
                        dict(tested_sha=tested, run_id="19", run_attempt=str(attempt))
                    )
                )
            browser = root / "ci-browser-19-1" / "junit.xml"
            browser.write_text(
                '<testsuite tests="1"><testcase classname="browser_tests.test_ranked_opportunities" '
                'name="test_desk_reports_outage_without_old_quotes_then_recovers_on_refresh"><skipped/>'
                "</testcase></testsuite>"
            )
            storage = root / "storage-19-2-2" / "junit.xml"
            storage.write_text(
                '<testsuite tests="2"><testcase classname="tests.test_broad_native_matrix_sql.BroadNativeMatrixSQL" '
                'name="test_desk_withholds_prices_during_sql_stall_and_reconnects"/>'
                '<testcase classname="tests.test_ordinary_publication_sql.OrdinarySQL" '
                'name="test_posted_native_quote_survives_rotation_and_loses_execution_authority"><failure/>'
                "</testcase></testsuite>"
            )
            context = dict(base_sha=None, baseline=None, slowest=None, health=None)
            missing = signals.build(root, root, sha, "19", "2", context)
            self.assertEqual(missing["artifacts"], ["storage-19-2-2"])
            self.assertEqual(
                missing["contracts"][
                    "Desk withholds prices during outages and recovers"
                ]["status"],
                "MISSING",
            )

            browser_job = dict(
                name="Ordinary browser journey",
                run_id=19,
                run_attempt=1,
                status="completed",
                conclusion="success",
            )
            jobs = dict(jobs=[browser_job])
            inherited = load("signals_context").inherited_artifact_attempts
            context["inherited_attempts"] = inherited(jobs, "19", "2")
            result = signals.build(root, root, sha, "19", "2", context)
            self.assertEqual(result["artifacts"], ["ci-browser-19-1", "storage-19-2-2"])
            self.assertEqual(result["reused_artifacts"], ["ci-browser-19-1"])
            checks = result["contracts"]
            self.assertEqual(
                checks["Desk withholds prices during outages and recovers"]["status"],
                "SKIPPED",
            )
            self.assertEqual(
                checks["Stale native prices lose current authority"]["status"], "FAIL"
            )
            self.assertEqual(
                checks["Ranked pairs use exact opposing markets"]["status"], "MISSING"
            )
            text = signals.render(result, None)
            self.assertIn("Comparable base artifact unavailable", text)
            self.assertIn("Changed-code coverage unavailable", text)
            browser.write_text(browser.read_text().replace("<skipped/>", ""))
            self.assertEqual(
                signals.build(root, root, sha, "19", "2", context)["contracts"][
                    "Desk withholds prices during outages and recovers"
                ]["status"],
                "PASS",
            )
            jobs["jobs"] = [dict(browser_job, run_attempt=2, conclusion="failure")]
            context["inherited_attempts"] = inherited(jobs, "19", "2")
            self.assertEqual(
                signals.build(root, root, sha, "19", "2", context)["contracts"][
                    "Desk withholds prices during outages and recovers"
                ]["status"],
                "MISSING",
            )

            scope = dict(runner={"os": "Linux"}, python="3.14.5", playwright="1.61")
            measurement = dict(
                fixture="desk-browser-intercept-v1", samples=1, seconds=2.0, scope=scope
            )
            result["timings"][signals.BROWSER_PAINT] = measurement
            base = dict(timings={signals.BROWSER_PAINT: dict(measurement, seconds=1.0)})
            self.assertIn("| 2.000 | +1.000 |", signals.render(result, base))
            base["timings"][signals.BROWSER_PAINT]["scope"] = dict(
                scope, python="3.11.9"
            )
            self.assertIn("| 2.000 | — |", signals.render(result, base))
            self.assertNotIn(signals.RECOVERY_PAINT, signals.render(result, base))
            result["timings"] = {
                signals.RECOVERY_PAINT: dict(
                    measurement, fixture="desk-browser-intercept-recovery-v2"
                ),
                signals.OUTAGE_RESPONSE: dict(
                    measurement, fixture="desk-polymarket-nba-v2"
                ),
            }
            text = signals.render(result, base)
            self.assertNotIn(signals.BROWSER_PAINT, text)
            self.assertNotIn(signals.FALLBACK_RESPONSE, text)
            self.assertIn("Desk paint after manual recovery | 2.000 | — |", text)
            self.assertIn("First desk response | — | — | Unavailable", text)

    def test_duplicate_detection_ignores_wrappers_and_docstring_differences(self):
        code = load("code_signals")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "app"
            app.mkdir()
            body = "\n    a = x\n    b = a\n    c = b\n    d = c\n    return d\n"
            (app / "one.py").write_text(
                'def first(x):\n    """first"""' + body + "\ndef a(x): return x\n"
            )
            (app / "two.py").write_text(
                'def second(x):\n    """second"""' + body + "\ndef b(x): return x\n"
            )
            functions, groups = code.duplicates(root)
            self.assertEqual(functions, 2)
            self.assertEqual(len(groups), 1)
            self.assertEqual(
                [f["name"] for f in groups[0]["functions"]], ["first", "second"]
            )


class ReadinessArtifactTests(unittest.TestCase):
    def test_gate_retains_identity_and_failure_even_for_malformed_input(self):
        import os
        from unittest.mock import patch

        gate = load("gate")
        passing = {name: {"result": "success"} for name in gate.REQUIRED}
        for raw, expected in (
            (json.dumps(passing), "PASS"),
            ("{broken", "FAIL"),
            ("{}", "FAIL"),
            ("null", "FAIL"),
        ):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as folder:
                with patch.dict(
                    os.environ,
                    {
                        "NEEDS_JSON": raw,
                        "GITHUB_SHA": "merge-candidate",
                        "PR_HEAD_SHA": "pr-head",
                        "GITHUB_STEP_SUMMARY": "summary.md",
                    },
                ):
                    before = Path.cwd()
                    try:
                        os.chdir(folder)
                        self.assertEqual(gate.main(), int(expected == "FAIL"))
                    finally:
                        os.chdir(before)
                result = json.loads(
                    (Path(folder) / "test-results/readiness/metrics.json").read_text()
                )
                self.assertEqual(result["overall"], expected)
                self.assertEqual(result["tested_sha"], "merge-candidate")
                self.assertEqual(result["pr_head_sha"], "pr-head")
                self.assertTrue(
                    (Path(folder) / "test-results/readiness/summary.md").exists()
                )
                self.assertNotIn("{broken", (Path(folder) / "summary.md").read_text())

    def test_wheel_requires_noncode_financial_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            names = [
                "app/fixtures/fee.md",
                "app/fixtures/native-scoring-scope/rule.txt",
                "app/fixtures/college-identity-20261028/source.html.gz",
            ]
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("authored evidence")
            validate = load("package_smoke").validate_wheel
            validate(names, root)
            for missing in names:
                with self.assertRaises(ValueError):
                    validate([name for name in names if name != missing], root)

    def test_wheel_requires_declared_ui_assets_but_rejects_unknown_assets(self):
        package = load("package_smoke")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            names = sorted(package.UI_ASSETS)
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"authored asset fixture")
            package.validate_wheel(names, root)
            for missing in names:
                with (
                    self.subTest(missing=missing),
                    self.assertRaisesRegex(ValueError, "Missing package inputs"),
                ):
                    package.validate_wheel(
                        [name for name in names if name != missing], root
                    )
            with self.assertRaisesRegex(ValueError, "Unexpected/stale package inputs"):
                package.validate_wheel(
                    names + ["app/dashboard/opportunity_static/current/unknown.ttf"],
                    root,
                )
