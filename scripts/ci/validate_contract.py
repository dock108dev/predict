"""Fail on unclassified, duplicate, missing or accidentally excluded test inputs."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def validate(root):
    groups = json.loads((root / "scripts/ci/suites.json").read_text())
    policy = json.loads((root / "scripts/ci/python-policy.json").read_text())
    names = [g["name"] for g in groups]
    selected = [name for g in groups for name in g["tests"]]
    if not groups or any(not g["tests"] for g in groups):
        raise ValueError("Empty required Python suite")
    if len(set(names)) != len(names) or len(set(selected)) != len(selected):
        raise ValueError("Duplicate required suite or Python input")
    categories = [set(selected), set(policy["deferred"]), set(policy["quality"])]
    if any(a & b for i, a in enumerate(categories) for b in categories[i + 1 :]):
        raise ValueError("Test module has multiple dispositions")
    actual = {str(p.relative_to(root)) for p in (root / "tests").glob("test_*.py")}
    known = set().union(*categories)
    if actual != known:
        raise ValueError(
            f"Python test classification drift: new={sorted(actual - known)}, missing={sorted(known - actual)}"
        )
    for node, reason in policy["archival_nodes"].items():
        file, *parts = node.split("::")
        if file not in categories[0] or not reason.strip():
            raise ValueError(
                "Archival node must be explained inside a required suite: " + node
            )
        children = ast.parse((root / file).read_text()).body
        for part in parts:
            match = next(
                (n for n in children if getattr(n, "name", None) == part), None
            )
            if match is None:
                raise ValueError("Stale archival node: " + node)
            children = getattr(match, "body", [])
    if any(not reason.strip() for reason in policy["deferred"].values()):
        raise ValueError("Unexplained Python omission")
    browser = json.loads((root / "scripts/ci/browser-suites.json").read_text())
    active, deferred = set(browser["required"]), set(browser["deferred"])
    actual_browser = {p.name for p in (root / "tests").glob("test_*.cjs")}
    if active & deferred or active | deferred != actual_browser or not active:
        raise ValueError("Browser test classification drift")
    print(
        f"PASS: {len(selected)} required Python modules, {len(active)} browser suites; all archival omissions explicit"
    )


if __name__ == "__main__":
    validate(ROOT)
