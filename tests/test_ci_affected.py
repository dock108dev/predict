"""Local affected-test routing with disposable Git state and pytest processes."""

import json
from pathlib import Path
import tempfile
import unittest

from tests.ci_support import load


class AffectedSelection(unittest.TestCase):
    """Qualify routing with disposable Git state and real pytest exit semantics."""

    def setUp(self):
        import subprocess

        self.module = load("affected")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.git = lambda *args: subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                *args,
            ],
            cwd=self.root,
        )
        self.git("init", "-q")
        self.write(".gitignore", ".local/\n__pycache__/\n.pytest_cache/\n")
        groups = [
            dict(name=name, tests=["tests/test_" + leaf + ".py"])
            for name, leaf in (
                ("personal-bet-journal", "journal_leaf"),
                ("ordinary-fee-coverage", "board_leaf"),
                ("sportsgameodds", "source_leaf"),
            )
        ]
        self.write("scripts/ci/suites.json", json.dumps(groups))
        self.write(
            "scripts/ci/python-policy.json",
            json.dumps(
                dict(
                    quality=["tests/test_ci_fixture.py"],
                    deferred={},
                    archival_nodes={},
                )
            ),
        )
        for path in [p for g in groups for p in g["tests"]] + [
            "tests/test_ci_fixture.py"
        ]:
            self.write(path, "def test_authored():\n    assert 2 + 2 == 4\n")
        self.write("app/dashboard/bet_journal.py", "VALUE = 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Authored fixture baseline")

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_complete_diff_includes_staged_unstaged_untracked_and_both_rename_paths(
        self,
    ):
        self.write("app/dashboard/bet_journal.py", "VALUE = 2\n")
        self.git("add", "app/dashboard/bet_journal.py")
        self.write("tests/test_board_leaf.py", "def test_new(): assert True\n")
        self.write("tests/test_new.py", "def test_new(): assert True\n")
        self.git("mv", "tests/test_source_leaf.py", "tests/test_renamed.py")
        comparison, paths = self.module.changes(self.root)
        self.assertEqual(comparison, "HEAD")
        self.assertEqual(
            set(paths),
            {
                "app/dashboard/bet_journal.py",
                "tests/test_board_leaf.py",
                "tests/test_new.py",
                "tests/test_source_leaf.py",
                "tests/test_renamed.py",
            },
        )
        selected = self.module.plan(self.root, paths)
        self.assertTrue(selected["fallback"])
        self.assertTrue(any("Deleted/renamed" in r for r in selected["reasons"]))
        self.assertTrue(any("tests/test_new.py" in c for c in selected["commands"]))

    def test_merge_base_adds_committed_branch_work_and_local_edits(self):
        base = self.git("rev-parse", "HEAD").decode().strip()
        self.write("tests/test_journal_leaf.py", "def test_branch(): assert True\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Branch work")
        self.write("tests/test_board_leaf.py", "def test_local(): assert True\n")
        comparison, paths = self.module.changes(self.root, base)
        self.assertEqual(comparison, base)
        self.assertEqual(
            set(paths), {"tests/test_journal_leaf.py", "tests/test_board_leaf.py"}
        )

    def test_leaf_selects_one_module_and_matches_full_fixture_result(self):
        import sys

        selected = self.module.plan(self.root, ["tests/test_journal_leaf.py"])
        self.assertFalse(selected["fallback"])
        self.assertEqual(len(selected["commands"]), 1)
        self.assertEqual(selected["commands"][0][-1], "tests/test_journal_leaf.py")
        self.assertEqual(self.module.execute(selected["commands"], self.root), 0)
        # Representative full fixture comparison, not a whole-repository pass.
        self.assertEqual(
            self.module.execute(
                [[sys.executable, "-m", "pytest", "-q", "tests"]], self.root
            ),
            0,
        )

    def test_shared_fixture_and_noncode_inputs_broaden_visibly(self):
        for path in (
            "tests/conftest.py",
            "tests/pregame_fixture.py",
            "config/model.json",
            "requirements-ci.txt",
            "AGENTS.md",
        ):
            with self.subTest(path=path):
                self.write(path, "{}")
                selected = self.module.plan(self.root, [path])
                self.assertTrue(selected["fallback"])
                self.assertTrue(any(path in r for r in selected["reasons"]))
                self.assertTrue(
                    any("scripts/ci/run_checks.py" in c for c in selected["commands"])
                )
                self.assertTrue(
                    any("scripts/ci/postgres.py" in c for c in selected["commands"])
                )
                self.assertTrue(any("browser_tests" in c for c in selected["commands"]))

    def test_known_source_selects_consumers_and_new_tests_are_never_omitted(self):
        selected = self.module.plan(self.root, ["app/dashboard/bet_journal.py"])
        self.assertFalse(selected["fallback"])
        self.assertTrue(
            any("tests/test_journal_leaf.py" in c for c in selected["commands"])
        )
        self.assertTrue(
            any(
                "--tests" in c and "tests/test_bet_journal_monitor_sql.py" in c
                for c in selected["commands"]
            )
        )
        self.assertTrue(
            any("browser_tests/test_bet_journal.py" in c for c in selected["commands"])
        )
        self.assertTrue(
            any(
                "browser_tests/test_journal_opportunity_log.py" in c
                for c in selected["commands"]
            )
        )
        self.write("tests/test_added.py", "def test_added(): assert True\n")
        selected = self.module.plan(self.root, ["tests/test_added.py"])
        self.assertTrue(selected["fallback"])
        self.assertTrue(any("tests/test_added.py" in c for c in selected["commands"]))

    def test_sgo_changes_include_both_sql_contracts(self):
        for path in (
            "app/collection/sportsgameodds_worker.py",
            "app/storage/sportsgameodds_reference.py",
        ):
            with self.subTest(path=path):
                self.write(path, "")
                selected = self.module.plan(self.root, [path])
                self.assertFalse(selected["fallback"])
                sql = next(c for c in selected["commands"] if "--tests" in c)
                self.assertIn("tests/test_sportsgameodds_ingress_sql.py", sql)
                self.assertIn("tests/test_sportsgameodds_reference_sql.py", sql)

    def test_registered_dated_export_runs_in_the_portable_lane(self):
        root = Path(__file__).resolve().parents[1]
        path = "tests/test_research_offer_export_api.py"
        selected = self.module.plan(root, [path])
        self.assertFalse(selected["fallback"])
        self.assertEqual(selected["commands"][0][1:], ["-m", "pytest", "-q", path])

    def test_missing_stale_or_corrupt_diagnostic_data_cannot_change_selection(self):
        from unittest.mock import patch

        first = self.module.plan(self.root, ["tests/test_board_leaf.py"])
        for content in ("stale", "{broken", json.dumps(dict(commands=[]))):
            self.write(".local/test-affected/last-plan.json", content)
            self.assertEqual(
                self.module.plan(self.root, ["tests/test_board_leaf.py"]), first
            )
        self.assertEqual(self.module.changes(self.root)[1], [])
        # Every real invocation allocates a new SQL report directory; no stale
        # report from a preceding run can prevent the selected tests starting.
        self.write("app/dashboard/bet_journal.py", "VALUE = 2\n")
        with (
            patch.object(self.module, "ROOT", self.root),
            patch.object(self.module, "execute", return_value=0) as execute,
            patch("builtins.print"),
        ):
            self.assertEqual(self.module.main([]), 0)
            self.assertEqual(self.module.main([]), 0)
        reports = []
        for call in execute.call_args_list:
            sql = next(c for c in call.args[0] if "scripts/ci/postgres.py" in c)
            reports.append(sql[sql.index("--report-dir") + 1])
        self.assertNotEqual(*reports)
        self.assertTrue(all(Path(p).parent.is_dir() for p in reports))

    def test_test_module_exporting_a_helper_includes_consumers_or_broadens(self):
        self.write("browser_tests/test_pregame_current.py", "def offer(): return 1\n")
        self.write(
            "tests/test_journal_leaf.py",
            "from browser_tests.test_pregame_current import offer\n",
        )
        selected = self.module.plan(
            self.root, ["browser_tests/test_pregame_current.py"]
        )
        self.assertFalse(selected["fallback"])
        self.assertTrue(
            any("tests/test_journal_leaf.py" in c for c in selected["commands"])
        )
        self.write(
            "tests/support.py", "from tests.test_board_leaf import test_authored\n"
        )
        selected = self.module.plan(self.root, ["tests/test_board_leaf.py"])
        self.assertTrue(selected["fallback"])
        self.assertTrue(any("shared helpers" in r for r in selected["reasons"]))

    def test_docs_no_changes_full_override_and_archival_exclusions(self):
        self.write("docs/guide.md", "Authored guide")
        docs = self.module.plan(self.root, ["docs/guide.md"])
        self.assertEqual([c[1:] for c in docs["commands"]], [["scripts/ci/docs.py"]])
        self.assertEqual(self.module.plan(self.root, [])["commands"], [])
        self.assertTrue(self.module.plan(self.root, [], full=True)["fallback"])
        path = self.root / "scripts/ci/python-policy.json"
        policy = json.loads(path.read_text())
        policy["archival_nodes"] = {
            "tests/test_board_leaf.py::test_old": "Authored exclusion"
        }
        path.write_text(json.dumps(policy))
        command = self.module.plan(self.root, ["tests/test_board_leaf.py"])["commands"][
            0
        ]
        self.assertIn("--deselect=tests/test_board_leaf.py::test_old", command)

    def test_behavior_failure_and_zero_collection_propagate_and_stop_next_command(self):
        import sys

        self.write(
            "tests/test_journal_leaf.py",
            "def test_authored():\n    assert 2 + 2 == 5\n",
        )
        selected = self.module.plan(self.root, ["tests/test_journal_leaf.py"])
        marker = [
            sys.executable,
            "-c",
            "from pathlib import Path; Path('must-not-run').touch()",
        ]
        self.assertEqual(
            self.module.execute([*selected["commands"], marker], self.root), 1
        )
        self.assertFalse((self.root / "must-not-run").exists())
        self.write("tests/test_journal_leaf.py", "# No cases\n")
        self.assertEqual(self.module.execute(selected["commands"], self.root), 5)
