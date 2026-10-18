"""Copy tracked plus nonignored candidate files; never copy local owner state."""

from pathlib import Path
import shutil
import os
import subprocess
import sys
import json
from hashlib import sha256


def export(target, *, root=None, files=None, include_retained=True):
    root = Path(root or Path(__file__).resolve().parents[2]).resolve()
    files = (
        files
        if files is not None
        else (
            subprocess.check_output(
                ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                cwd=root,
            )
            .decode()
            .split("\0")
        )
    )
    retained = (
        json.loads((root / "config/ci-retained-resources.json").read_text())[
            "resources"
        ]
        if include_retained
        else {}
    )
    for name, expected in retained.items():
        relative = Path(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not name.startswith(
                (
                    "app/",
                    "docs/",
                    "evidence/public-contract-bindings-20260930-v1/public/",
                )
            )
        ):
            raise ValueError("Unsafe retained resource path")
        source = root / name
        if (
            source.is_symlink()
            or not source.is_file()
            or sha256(source.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("Missing or changed retained resource: " + name)
    files = set(files) | set(retained)
    if target.exists() and any(target.iterdir()):
        raise ValueError("Export destination must be empty")
    target.mkdir(parents=True, exist_ok=True)
    for name in set(files) - {""}:
        if (
            name.startswith((".local/", "test-results/", "evidence/"))
            and name not in retained
        ) or (
            Path(name).name.startswith(".env")
            and Path(name).name not in (".env.example", ".env.sample", ".env.template")
        ):
            raise ValueError("Private state must not be a publishable CI input")
        source = root / name
        if source.is_symlink():
            resolved = source.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(f"Export symlink escapes repository: {name}")
            if resolved.relative_to(root).parts[0] in (
                ".local",
                "test-results",
                "evidence",
            ):
                raise ValueError("Export symlink targets private state")
            dest = target / name
            link = os.path.relpath(target / resolved.relative_to(root), dest.parent)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(link)
            continue
        if source.is_file():
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)


if __name__ == "__main__":
    export(Path(sys.argv[1]).resolve())
