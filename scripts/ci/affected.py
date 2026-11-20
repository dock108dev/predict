"""Conservative local subsystem selection; no prediction or result cache.

Unknown inputs broaden to all registered behavior lanes. Required CI is unchanged.
"""

import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SQL = [
    "tests/test_current_pregame_sql.py",
    "tests/test_pregame_cohorts_sql.py",
    "tests/test_activity_mode_sql.py",
    "tests/test_pregame_board_views_sql.py",
    "tests/test_bet_journal_monitor_sql.py",
    "tests/test_fee_pricing_sql.py",
    "tests/test_sgo_line_presence_sql.py",
    "tests/test_sgo_current_rows_sql.py",
    "tests/test_sgo_native_catalog_sql.py",
    "tests/test_broad_native_matrix_sql.py",
]
BOARD_BROWSER = [
    "browser_tests/test_pregame_current.py",
    "browser_tests/test_pregame_games_arbs.py",
    "browser_tests/test_bet_journal.py",
    "browser_tests/test_pregame_price_formats.py",
    "browser_tests/test_prism.py",
]


def imported_test_helpers(root, paths):
    """Test modules can also supply fixtures; do not treat those as isolated leaves."""
    changed = {
        p[:-3].replace("/", ".")
        for p in paths
        if p.endswith(".py") and p.startswith(("tests/", "browser_tests/"))
    }
    dependents = set()
    if not changed:
        return dependents
    for folder in ("app", "tests", "browser_tests"):
        for file in (root / folder).rglob("*.py"):
            # A parse error is uncertain impact, handled by a broad fallback.
            try:
                tree = ast.parse(file.read_text())
            except (SyntaxError, UnicodeError):
                return {"unparseable Python dependency"}
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        # Relative test-helper resolution is outside this bounded router.
                        if folder in ("tests", "browser_tests"):
                            return {"relative test dependency"}
                    names = [
                        node.module or "",
                        *[(node.module or "") + "." + a.name for a in node.names],
                    ]
                if any(name in changed for name in names):
                    dependents.add(str(file.relative_to(root)))
    return dependents


def changes(root, base=None):
    """HEAD plus index/worktree/untracked; an optional merge base adds branch work."""

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root)

    comparison = git("merge-base", base, "HEAD").decode().strip() if base else "HEAD"
    # Disable rename detection so both old and new paths participate.
    tracked = git("diff", "--name-only", "--no-renames", "-z", comparison, "--")
    untracked = git("ls-files", "--others", "--exclude-standard", "-z")
    return comparison, sorted(
        set(os.fsdecode(p) for p in (tracked + untracked).split(b"\0") if p)
    )


def plan(root, paths, *, full=False):
    groups = json.loads((root / "scripts/ci/suites.json").read_text())
    by_name = {g["name"]: g["tests"] for g in groups}
    portable = {p for g in groups for p in g["tests"]}
    policy = json.loads((root / "scripts/ci/python-policy.json").read_text())
    unit, sql, browser, reasons = set(), set(), set(), []
    docs = False
    broad = full
    consumers = imported_test_helpers(root, paths)
    if consumers:
        # Known shared fixture consumers; unfamiliar dependencies broaden safely.
        known = set(SQL + BOARD_BROWSER + by_name["personal-bet-journal"])
        if consumers - known:
            broad = True
            reasons.append(
                "Changed test module supplies shared helpers: "
                + ", ".join(sorted(consumers))
            )
        else:
            unit.update(consumers & portable)
            sql.update(consumers & set(SQL))
            browser.update(consumers & set(BOARD_BROWSER))
            reasons.append(
                "Include inspected test-helper consumers: "
                + ", ".join(sorted(consumers))
            )
    if full:
        reasons.append(
            "Explicit --full: all registered behavior lanes plus quality tests"
        )
    for path in paths:
        p = Path(path)
        if p.name == "AGENTS.md":
            broad = True
            reasons.append(
                f"Execution requirements changed in {path}: all behavior lanes"
            )
        elif path.startswith("docs/") or (len(p.parts) == 1 and p.suffix == ".md"):
            docs = True
            continue
        if not (root / path).is_file():
            broad = True
            reasons.append(f"Deleted/renamed input {path}: dependency reach uncertain")
        elif path in portable:
            unit.add(path)
            reasons.append(f"Changed portable test {path}")
        elif path in policy["quality"] or (
            path.startswith("tests/test_ci_") and p.suffix == ".py"
        ):
            unit.add(path)
            reasons.append(f"Changed quality test {path}")
        elif path == "scripts/ci/affected.py":
            unit.update(policy["quality"])
            reasons.append(
                "Selector tooling: quality tests (including selector qualification)"
            )
        elif path.startswith("browser_tests/test_") and p.suffix == ".py":
            browser.add(path)
            reasons.append(f"Changed browser test {path}")
        elif path in SQL:
            sql.add(path)
            reasons.append(f"Changed SQL test {path}")
        elif (
            path.startswith("tests/test_")
            and p.suffix == ".py"
            and path not in policy["deferred"]
        ):
            # New test: never omit it merely because the manifest is not updated yet.
            # Unknown storage/setup requirements force the registered lanes too.
            unit.add(path)
            broad = True
            reasons.append(f"Unclassified new test {path}: include it and broaden")
        elif path.startswith(
            (
                "app/dashboard/bet_journal",
                "app/comparison/journal_",
                "app/dashboard/appearance_api",
            )
        ):
            unit.update(by_name["personal-bet-journal"])
            sql.add("tests/test_bet_journal_monitor_sql.py")
            browser.update(BOARD_BROWSER)
            reasons.append(f"Journal subsystem and consumers: {path}")
        elif path.startswith(
            (
                "app/storage/current_pregame",
                "app/storage/pregame_",
                "app/comparison/current_pregame",
                "app/dashboard/opportunity_static/current/",
            )
        ):
            unit.update(by_name["ordinary-fee-coverage"])
            unit.update(by_name["personal-bet-journal"])
            sql.update(SQL)
            browser.update(BOARD_BROWSER)
            reasons.append(f"Pregame calculation/storage/UI consumers: {path}")
        elif path.startswith(
            ("app/collection/sportsgameodds_", "app/storage/sportsgameodds_")
        ):
            unit.update(by_name["sportsgameodds"])
            unit.update(by_name["personal-bet-journal"])
            sql.update(SQL)
            browser.update(BOARD_BROWSER)
            reasons.append(f"SGO admission and downstream consumers: {path}")
        else:
            broad = True
            reasons.append(
                f"Unmodeled source/helper/configuration {path}: all behavior lanes"
            )
    python = sys.executable
    commands = []
    if broad:
        commands = [
            [python, "scripts/ci/run_checks.py"],
            [python, "scripts/ci/postgres.py"],
            [python, "-m", "pytest", "-q", "browser_tests"],
            [
                python,
                "-m",
                "pytest",
                "-q",
                *policy["quality"],
                *sorted(unit - portable - set(policy["quality"])),
            ],
        ]
        docs = True
    else:
        if unit:
            # Preserve the portable lane's explicit historical exclusions.
            exclusions = [
                "--deselect=" + n
                for n in policy["archival_nodes"]
                if n.split("::")[0] in unit
            ]
            commands.append([python, "-m", "pytest", "-q", *exclusions, *sorted(unit)])
        if sql:
            commands.append([python, "scripts/ci/postgres.py", "--tests", *sorted(sql)])
        if browser:
            commands.append([python, "-m", "pytest", "-q", *sorted(browser)])
    if docs:
        commands.append([python, "scripts/ci/docs.py"])
    return dict(
        mechanism="conservative subsystem routing; no dependency graph or result reuse",
        paths=paths,
        fallback=broad,
        reasons=reasons
        or ["Documentation only" if docs else "No working changes; no tests executed"],
        commands=commands,
    )


def execute(commands, root):
    for command in commands:
        result = subprocess.run(command, cwd=root)
        if result.returncode:
            return result.returncode  # Includes pytest's zero-collection exit 5.
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Include changes since merge-base(BASE, HEAD)")
    parser.add_argument(
        "--plan", action="store_true", help="Print the plan without executing"
    )
    parser.add_argument(
        "--full", action="store_true", help="All registered behavior lanes"
    )
    args = parser.parse_args(argv)
    comparison, paths = changes(ROOT, args.base)
    selected = dict(comparison=comparison, **plan(ROOT, paths, full=args.full))
    # Diagnostic only, never trusted as selection input or proof of a pass.
    output = ROOT / ".local/test-affected"
    output.mkdir(parents=True, exist_ok=True)
    if not args.plan and selected["commands"]:
        report = Path(tempfile.mkdtemp(prefix="run-", dir=output))
        selected["report_dir"] = str(report)
        for index, command in enumerate(selected["commands"]):
            if "scripts/ci/postgres.py" in command:
                command.extend(["--report-dir", str(report / "postgres")])
            elif command[1:3] == ["-m", "pytest"]:
                command.append(f"--junitxml={report / f'pytest-{index}.xml'}")
            elif "scripts/ci/run_checks.py" in command:
                command.extend(["--output", str(report / "portable")])
    print(json.dumps(selected, indent=2), flush=True)
    (output / "last-plan.json").write_text(json.dumps(selected, indent=2) + "\n")
    return 0 if args.plan else execute(selected["commands"], ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
