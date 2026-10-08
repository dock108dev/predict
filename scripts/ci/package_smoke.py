"""Build and install fresh output, then check imports/assets outside the checkout."""

import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile


def main():
    report = Path("test-results/package")
    report.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="predict-package-") as folder:
        root = Path(folder)
        subprocess.run(
            [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(root)],
            check=True,
            timeout=120,
        )
        (wheel,) = root.glob("*.whl")
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            for required in [
                "app/fixtures",
                "app/storage/migrations",
                "app/dashboard/opportunity_static/current",
                "app/normalization/registry-v1.json",
            ]:
                if not any(n.startswith(required) for n in names):
                    raise ValueError(f"Missing package asset {required}")
            if any(
                n.startswith(("tests/", "evidence/", ".env", ".local/")) for n in names
            ):
                raise ValueError("Private/check-out-only inputs entered wheel")
        subprocess.run(
            [sys.executable, "-m", "venv", str(root / "env")],
            check=True,
            timeout=60,
        )
        python = root / "env/bin/python"
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "-r",
                str(Path("requirements-ci.txt").resolve()),
            ],
            check=True,
            timeout=180,
        )
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--force-reinstall",
                str(wheel),
            ],
            check=True,
            timeout=60,
        )
        code = """
from pathlib import Path
import app.dashboard.current_contract, app.collection.current_service
import app.dashboard.multi_game_server, app.normalization, app.storage
import app.dashboard
root = Path(app.dashboard.__file__).parent
for name in ('index.html', 'current.js', 'arbs.html', 'arbs.js', 'admin.html', 'admin.js'):
    assert (root / 'opportunity_static/current' / name).is_file(), name
assert '/env/' in str(root), root
"""
        subprocess.run([str(python), "-c", code], cwd=root, check=True, timeout=30)
        subprocess.run(
            [str(python), "-m", "app.dashboard", "--help"],
            cwd=root,
            check=True,
            timeout=30,
        )
        result = {
            "status": "PASS",
            "wheel_bytes": wheel.stat().st_size,
            "files": len(names),
            "seconds": round(time.monotonic() - started, 3),
            "baseline": None,
            "tested_sha": os.environ.get("GITHUB_SHA"),
            "python": platform.python_version(),
            "platform": platform.platform(),
        }
        (report / "metrics.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
