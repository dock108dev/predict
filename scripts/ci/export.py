"""Copy tracked plus nonignored candidate files; never copy local owner state."""

from pathlib import Path
import shutil
import os
import subprocess
import sys


def export(target):
    root = Path(__file__).resolve().parents[2]
    files = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    if target.exists() and any(target.iterdir()):
        raise ValueError("Export destination must be empty")
    target.mkdir(parents=True, exist_ok=True)
    for name in set(files) - {""}:
        source = root / name
        if source.is_symlink():
            resolved = source.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError(f"Export symlink escapes repository: {name}")
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
