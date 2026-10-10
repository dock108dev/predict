"""Build and install fresh output, then check imports/assets outside the checkout."""

import json
import os
import platform
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile


def validate_wheel(names, source):
    expected = {
        p.relative_to(source).as_posix()
        for p in (source / "app").rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix in {".py", ".json", ".js", ".css", ".html", ".sql"}
    }
    actual = {n for n in names if n.startswith("app/")}
    if expected - actual:
        raise ValueError(
            "Missing package inputs: " + ", ".join(sorted(expected - actual))
        )
    if actual - expected:
        raise ValueError(
            "Unexpected/stale package inputs: " + ", ".join(sorted(actual - expected))
        )
    if any(n.startswith(("tests/", "evidence/", ".env", ".local/")) for n in names):
        raise ValueError("Private/check-out-only inputs entered wheel")


def main():
    report = Path("test-results/package")
    report.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="predict-package-") as folder:
        root = Path(folder)
        source = root / "source"
        source.mkdir()
        shutil.copy2("pyproject.toml", source / "pyproject.toml")
        shutil.copy2("README.md", source / "README.md")
        shutil.copytree(
            "app", source / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        subprocess.run(
            [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(root)],
            check=True,
            timeout=120,
            cwd=source,
        )
        (wheel,) = root.glob("*.whl")
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            validate_wheel(names, source)
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
for name in ('index.html', 'current.js', 'arbs.html', 'arbs.js', 'admin.html', 'admin.js',
             'ev.html', 'ev.js', 'coverage.html', 'coverage.js', 'comparison-board.js',
             'comparison-view.js', 'comparison.css'):
    assert (root / 'opportunity_static/current' / name).is_file(), name
assert '/env/' in str(root), root
import asyncio, aiohttp
from aiohttp import web
from types import SimpleNamespace
async def smoke():
    async def close(): pass
    owner=SimpleNamespace(close=close, session=None)
    app=app_module.create_app(owner=owner, sessions={})
    runner=web.AppRunner(app)
    await runner.setup()
    try:
        site=web.TCPSite(runner,'127.0.0.1',0)
        await site.start()
        url='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as client:
            for path in ('/','/ev','/arbs','/current/coverage','/admin',
                         '/current/assets/comparison-board.js','/current/assets/board.js',
                         '/api/comparison','/api/coverage'):
                async with client.get(url+path) as response:
                    assert response.status==200,(path,response.status)
                    await response.read()
            async with client.get(url+'/api/current') as response:
                state=await response.json()
                assert state['mode']=='current' and not state['events']
            assert app[current_key].provider.__class__.__name__=='CurrentStateProvider'
    finally:
        await runner.cleanup()
from app.dashboard import multi_game_server as app_module
from app.dashboard.current_state import CURRENT_KEY as current_key
asyncio.run(smoke())
"""
        subprocess.run([str(python), "-c", code], cwd=root, check=True, timeout=30)
        subprocess.run(
            [str(python), "-m", "app.dashboard", "--help"],
            cwd=root,
            check=True,
            timeout=30,
        )
        inventory = subprocess.check_output(
            [
                str(python),
                "-c",
                "import importlib.metadata as m,json; print(json.dumps(sorted([dict(name=d.metadata['Name'],version=d.version,license_expression=d.metadata.get('License-Expression')) for d in m.distributions()],key=lambda d:d['name'].lower())))",
            ],
            cwd=root,
            text=True,
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
            "installed_dependencies": json.loads(inventory),
            "smoke": "installed HTTP routes and empty current provider; no acquisition",
            "asset_contract": "all declared application source/data/assets; no stale wheel inputs",
        }
        (report / "metrics.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
