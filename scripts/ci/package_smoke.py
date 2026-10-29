"""Build and install fresh output, then check imports/assets outside the checkout."""

import argparse
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
        and (
            p.suffix in {".py", ".json", ".js", ".css", ".html", ".sql"}
            or p.suffix in {".pdf", ".txt", ".md", ".gz"}
            and source / "app/fixtures" in p.parents
        )
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


def copy_source(root, source):
    """Match a publishable checkout; ignored local catalogs cannot qualify a build."""
    names = (
        subprocess.check_output(
            [
                "git",
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                "app",
                "pyproject.toml",
                "README.md",
            ],
            cwd=root,
            timeout=15,
        )
        .decode()
        .split("\0")
    )
    for name in set(names) - {""}:
        path = root / name
        if path.is_symlink():
            raise ValueError("Package input must be an ordinary file: " + name)
        if not path.is_file():
            continue  # A tracked deletion is absent from the candidate.
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", default="test-results/package")
    report = Path(parser.parse_args().report_dir)
    if report.exists() and any(report.iterdir()):
        parser.error(
            "Use an empty package report directory; existing evidence is preserved"
        )
    report.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="predict-package-") as folder:
        root = Path(folder)
        source = root / "source"
        source.mkdir()
        copy_source(Path.cwd(), source)
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
import app.comparison.scanner_summaries
import app.dashboard
root = Path(app.dashboard.__file__).parent
for name in ('index.html', 'current.js', 'arbs.html', 'arbs.js', 'admin.html', 'admin.js',
             'ev.html', 'ev.js', 'coverage.html', 'coverage.js', 'comparison-board.js',
             'comparison-view.js', 'scanner.html', 'scanner.js',
             'scanner.css', 'scanner-runtime.json'):
    assert (root / 'opportunity_static/current' / name).is_file(), name
assert '/env/' in str(root), root
# Imports alone do not prove that current model evidence survived packaging.
from app.comparison.conditional_benchmark import basis
from app.comparison.current_dependencies import instant
for venue in ('novig', 'polymarket_us'):
    assert basis(venue)['sha256']
    assert basis(venue, at=instant('2026-10-29T01:00:00Z'))['sha256']
from app.comparison.native_scoring_scope import source_rules
rules=source_rules()
for native_type in ('KXNBAGAME', 'KXNHLSPREAD', 'KXNHLTOTAL'):
    assert any(r['native_type']==native_type and r['evidence_available'] for r in rules), native_type
import asyncio, aiohttp
from aiohttp import web
from types import SimpleNamespace
async def smoke():
    async def close(): pass
    owner=SimpleNamespace(close=close, session=None)
    from app.dashboard.current_state import CurrentStateProvider
    provider=CurrentStateProvider()
    provider.database_mode = True  # Serve ordinary SQL-mode assets without starting SQL or sources.
    provider.closing = False
    provider.dispatch = False  # No acquisition is permitted by this smoke provider.
    app=app_module.create_app(owner=owner, sessions={},current_provider=provider)
    runner=web.AppRunner(app)
    await runner.setup()
    try:
        site=web.TCPSite(runner,'127.0.0.1',0)
        await site.start()
        url='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as client:
            for path in ('/','/odds','/ev','/arbs','/admin','/current/coverage','/api/scanner/client',
                         '/api/scanner/summaries',
                         '/current/assets/scanner.js','/current/assets/scanner.css',
                         '/current/assets/comparison-board.js','/current/assets/board.js',
                         '/current/assets/stored.js','/current/assets/stored.css','/current/assets/board-client.js',
                         '/current/assets/board-contract.js','/current/assets/board-values.js'):
                async with client.get(url+path) as response:
                    assert response.status==200,(path,response.status)
                    await response.read()
            for path in ('/api/current', '/api/current/details',
                         '/api/comparison',
                         '/api/stored/games', '/api/stored/result', '/api/boards/history'):
                async with client.get(url+path) as response:
                    assert response.status==410,(path,response.status)
                    state=await response.json()
                    assert state['provider_requests']==0,(path,state)
            # These routes are supported SQL reads, not retired transports.
            # This installed-package smoke deliberately provisions no SQL owner.
            for path in ('/api/coverage', '/api/boards/games'):
                async with client.get(url+path) as response:
                    assert response.status==503,(path,response.status)
                    state=await response.json()
                    assert state['error']=='database_unavailable',(path,state)
                    assert state['provider_requests']==0,(path,state)
            async with client.get(url+'/') as response:
                assert '/current/assets/stored.js' in await response.text()
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
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "installed_dependencies": json.loads(inventory),
            "smoke": "installed HTTP routes and empty current provider; no acquisition",
            "asset_contract": "all declared application source/data/assets; no stale wheel inputs",
        }
        (report / "metrics.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
