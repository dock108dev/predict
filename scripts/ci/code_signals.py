"""Advisory Python complexity and exact function-body duplication."""

import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def duplicates(root):
    bodies = defaultdict(list)
    functions = 0
    for path in sorted((root / "app").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("app/fixtures/"):
            continue
        for node in ast.walk(ast.parse(path.read_bytes(), filename=relative)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            statements = node.body
            if (
                isinstance(statements[0], ast.Expr)
                and isinstance(statements[0].value, ast.Constant)
                and isinstance(statements[0].value.value, str)
            ):
                statements = statements[1:]
            body = ast.Module(body=statements, type_ignores=[])
            # Tiny wrappers are common even when their owners are unrelated.
            if sum(isinstance(part, ast.stmt) for part in ast.walk(body)) < 5:
                continue
            functions += 1
            fingerprint = hashlib.sha256(ast.dump(body).encode()).hexdigest()
            bodies[fingerprint].append(
                dict(path=relative, line=node.lineno, name=node.name)
            )
    return functions, [
        dict(fingerprint=fingerprint, functions=locations)
        for fingerprint, locations in sorted(bodies.items())
        if len(locations) > 1
    ]


def main():
    root = Path.cwd()
    functions, groups = duplicates(root)
    # Ruff's default McCabe threshold is 10. This separate invocation has no
    # effect on the lint step or the required checks.
    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--isolated",
        "--select",
        "C901",
        "--output-format",
        "json",
        "--exit-zero",
        "--exclude",
        "app/fixtures",
        "app",
    ]
    findings = json.loads(subprocess.check_output(command, text=True, timeout=30))
    complexity = [
        dict(
            path=Path(item["filename"]).relative_to(root).as_posix(),
            line=item["location"]["row"],
            message=item["message"],
        )
        for item in findings
    ]
    output = root / "test-results/quality/code-signals.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema": 1,
                "eligible_functions": functions,
                "duplicates": groups,
                "complexity": complexity,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
