"""Same-run readiness qualification, report identity and rerun evidence."""

import json
from pathlib import Path
import tempfile
import unittest

from tests.ci_support import load, readiness_evidence


class RequiredEvidenceTests(unittest.TestCase):
    def test_complete_candidate_passes_without_network(self):
        from unittest.mock import Mock

        for attempt in ("1", "2"):
            with self.subTest(attempt=attempt), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                readiness_evidence(root, attempt=attempt)
                fetch = Mock(side_effect=AssertionError("Unexpected API access"))
                errors, evidence = load("required_evidence").evaluate(
                    root, "a" * 40, "10", attempt, "owner/repo", fetch
                )
                self.assertEqual(errors, [])
                self.assertEqual(len(evidence), 7)
                fetch.assert_not_called()

    def test_missing_malformed_empty_failed_skipped_and_wrong_candidate_fail(self):
        import shutil

        for defect in (
            "missing",
            "malformed",
            "zero",
            "failed",
            "skipped",
            "sha",
            "run",
            "future",
            "shard",
            "missing-check",
            "hidden-failure",
            "missing-junit",
            "extra-shard",
        ):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                paths = readiness_evidence(root)
                sql = paths[("storage", "4")]
                metrics = sql / "metrics.json"
                report = json.loads(metrics.read_text())
                if defect == "missing":
                    shutil.rmtree(sql)
                elif defect == "malformed":
                    metrics.write_text("{broken")
                elif defect in ("zero", "failed", "skipped"):
                    case = (
                        ""
                        if defect == "zero"
                        else '<testcase name="x">'
                        + ("<failure/>" if defect == "failed" else "<skipped/>")
                        + "</testcase>"
                    )
                    (sql / "junit.xml").write_text(
                        "<testsuite>" + case + "</testsuite>"
                    )
                elif defect == "shard":
                    (sql / "toolchain.json").write_text(
                        '{"shard_index": 3, "shard_count": 4, "suite": "registered-sql"}'
                    )
                elif defect == "missing-check":
                    offline = paths[("ci-offline", None)] / "metrics.json"
                    data = json.loads(offline.read_text())
                    data["checks"].pop()
                    offline.write_text(json.dumps(data))
                elif defect == "hidden-failure":
                    report["checks"][0].update(required=False, status="FAIL")
                    metrics.write_text(json.dumps(report))
                elif defect == "missing-junit":
                    offline = paths[("ci-offline", None)]
                    next(offline.glob("*.xml")).unlink()
                elif defect == "extra-shard":
                    extra = root / "storage-10-1-5"
                    shutil.copytree(sql, extra)
                else:
                    report[
                        {"sha": "tested_sha", "run": "run_id", "future": "run_attempt"}[
                            defect
                        ]
                    ] = {"sha": "b" * 40, "run": "11", "future": "2"}[defect]
                    metrics.write_text(json.dumps(report))
                self.assertTrue(
                    load("required_evidence").evaluate(
                        root, "a" * 40, "10", "1", "owner/repo"
                    )[0]
                )

    def test_older_report_requires_retained_success_and_current_report_wins(self):
        from unittest.mock import Mock

        module = load("required_evidence")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = readiness_evidence(root)
            reuse = {key: 1 for key in module.EXPECTED}
            fetch = Mock(return_value=reuse)
            errors, evidence = module.evaluate(
                root, "a" * 40, "10", "2", "owner/repo", fetch
            )
            self.assertEqual(errors, [])
            self.assertTrue(all(row["attempt"] == 1 for row in evidence.values()))
            self.assertTrue(
                module.evaluate(
                    root, "a" * 40, "10", "2", "owner/repo", Mock(return_value={})
                )[0]
            )
            self.assertTrue(
                module.evaluate(
                    root,
                    "a" * 40,
                    "10",
                    "2",
                    "owner/repo",
                    Mock(side_effect=ValueError("unavailable")),
                )[0]
            )
            # A new failure wins even if the API still reports the old job.
            paths[("ci-browser", None)].rename(root / "ci-browser-10-2")
            path = root / "ci-browser-10-2/metrics.json"
            data = json.loads(path.read_text())
            data.update(run_attempt="2", overall="FAIL")
            path.write_text(json.dumps(data))
            self.assertTrue(
                module.evaluate(root, "a" * 40, "10", "2", "owner/repo", fetch)[0]
            )

    def test_rerun_inventory_truncation_or_duplicates_grants_no_reuse(self):
        from unittest.mock import patch

        module = load("required_evidence")
        job = dict(
            name="Ordinary browser journey",
            run_id=10,
            run_attempt=1,
            status="completed",
            conclusion="success",
        )
        for data in (
            None,
            dict(jobs=[None], total_count=1),
            dict(jobs=[job], total_count=2),
            dict(jobs=None, total_count=0),
        ):
            with (
                patch.object(module, "actions", return_value=data),
                self.assertRaises(ValueError),
            ):
                module.inherited("owner/repo", "10", "2")
        for conclusion in ("failure", "skipped", "cancelled"):
            with patch.object(
                module,
                "actions",
                return_value=dict(
                    jobs=[dict(job, conclusion=conclusion)], total_count=1
                ),
            ):
                self.assertEqual(module.inherited("owner/repo", "10", "2"), {})
        with patch.object(
            module, "actions", return_value=dict(jobs=[job, job], total_count=2)
        ):
            self.assertEqual(module.inherited("owner/repo", "10", "2"), {})

    def test_gate_rejects_successful_jobs_without_reports_and_preserves_diagnostics(
        self,
    ):
        import contextlib
        import os
        from unittest.mock import patch

        gate = load("gate")
        with (
            tempfile.TemporaryDirectory() as folder,
            contextlib.chdir(folder),
            patch.dict(
                os.environ,
                dict(
                    NEEDS_JSON=json.dumps(
                        {key: dict(result="success") for key in gate.REQUIRED}
                    ),
                    GITHUB_SHA="a" * 40,
                    GITHUB_RUN_ID="10",
                    GITHUB_RUN_ATTEMPT="1",
                ),
                clear=True,
            ),
        ):
            self.assertEqual(gate.main(), 1)
            report = json.loads(Path("test-results/readiness/metrics.json").read_text())
            self.assertEqual(report["overall"], "FAIL")
            self.assertIn("artifact/shard", report["errors"][0])

    def test_workflow_downloads_before_gate_and_retains_four_shard_contract(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (
            (root / ".github/workflows/ci.yml")
            .read_text()
            .split("  readiness:\n", 1)[1]
        )
        self.assertLess(
            workflow.index("actions/download-artifact@"),
            workflow.index("scripts/ci/gate.py"),
        )
        # Step labels are presentation. The always-run condition belongs to
        # the step that actually invokes the gate, whatever its label.
        gate_step = next(
            block
            for block in workflow.split("      - ")
            if "run: python3 scripts/ci/gate.py" in block
        )
        self.assertIn(
            "if: always()",
            gate_step,
        )
        self.assertIn(
            "shard: [1, 2, 3, 4]", (root / ".github/workflows/storage.yml").read_text()
        )
