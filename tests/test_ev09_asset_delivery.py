"""Ordinary installed routes must serve each module their pages import."""

import re
import importlib.util
import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path
from urllib.parse import urljoin
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
from aiohttp.web import FileResponse
from app.dashboard.multi_game_server import create_app
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner


PUBLIC_DESK_PAGES = ("/", "/ev", "/arbs", "/browse-odds", "/game", "/replay")


class Assets(unittest.IsolatedAsyncioTestCase):
    async def test_preview_routes_keep_their_retained_shells(self):
        provider = InjectedTestProvider()
        app = create_app(owner=owner(), sessions={}, current_provider=provider)
        for path, shell in {
            '/': 'current/index.html', '/ev': 'current/ev.html',
            '/arbs': 'current/arbs.html', '/game': 'index.html',
        }.items():
            with self.subTest(path=path):
                match = await app.router.resolve(make_mocked_request('GET', path, app=app))
                request = make_mocked_request('GET', path, app=app, match_info=match)
                response = await match.handler(request)
                self.assertIsInstance(response, FileResponse)
                self.assertTrue(response._path.as_posix().endswith(f'/opportunity_static/{shell}'))

    async def test_public_desk_declares_the_packaged_browser_icon(self):
        provider = InjectedTestProvider()
        provider.database_mode = True
        app = create_app(owner=owner(), sessions={}, current_provider=provider)

        async def file_bytes(path):
            match = await app.router.resolve(make_mocked_request("GET", path, app=app))
            request = make_mocked_request("GET", path, app=app, match_info=match)
            response = await match.handler(request)
            self.assertIsInstance(response, FileResponse, path)
            return response._path.read_bytes()

        icon = "/view/current/predict-icon.png"
        for path in (*PUBLIC_DESK_PAGES, "/admin", "/odds", "/raw-odds", "/scanner"):
            html = (await file_bytes(path)).decode()
            icons = re.findall(r'<link rel="(?:icon|apple-touch-icon)"[^>]+href="([^"]+)"', html)
            self.assertEqual(icons, [icon, icon], path)
        self.assertTrue((await file_bytes(icon)).startswith(b"\x89PNG\r\n\x1a\n"))

    async def test_ordinary_pages_deliver_their_module_graph(self):
        provider = InjectedTestProvider()
        provider.database_mode = True
        app = create_app(owner=owner(), sessions={}, current_provider=provider)
        async with TestClient(TestServer(app)) as client:
            binding = await (await client.get('/api/scanner/client')).json()
            self.assertTrue(binding['assets_valid'])
            for page in (*PUBLIC_DESK_PAGES, "/odds", "/scanner"):
                response = await client.get(page)
                self.assertEqual(response.status, 200)
                html = await response.text()
                scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
                styles = re.findall(r'<link[^>]+href="([^"]+\.css(?:\?[^"]*)?)"', html)
                pending = [*scripts, *styles]
                seen = set()
                while pending:
                    path = pending.pop()
                    if path in seen:
                        continue
                    seen.add(path)
                    response = await client.get(path)
                    self.assertEqual(response.status, 200, path)
                    suffix = Path(path.split("?")[0]).suffix
                    self.assertIn(
                        {".css": "css", ".js": "javascript", ".ttf": "font"}[suffix],
                        response.headers["Content-Type"],
                    )
                    self.assertEqual(
                        await response.read(),
                        (
                            Path(__file__).resolve().parents[1]
                            / "app/dashboard/opportunity_static/current"
                            / Path(path.split("?")[0]).name
                        ).read_bytes(),
                    )
                    if suffix == ".ttf":
                        continue
                    source = await response.text()
                    imports = (
                        re.findall(r"url\([\"\']([^\"\']+)[\"\']\)", source)
                        if suffix == ".css"
                        else re.findall(r"(?:from\s+|import\s*)['\"]([^'\"]+)['\"]", source)
                    )
                    if path in scripts and "scanner.js" not in path:
                        endpoint = "/api/comparison-current" if page in PUBLIC_DESK_PAGES else "/api/comparison-snapshot"
                        self.assertIn(endpoint, source)
                        self.assertNotIn("new SavedReadPoller", source)
                    pending.extend(urljoin(path, module) for module in imports)
                expected = (
                    {"board-client.js", "board-contract.js", "board-values.js", "board-read.js", "scanner.css", "scanner.js"}
                    if page == "/scanner" else
                    {"desk.css", "desk-components.css", "desk-ticketboard.css", "desk-ticketboard.js",
                     "desk.js", "desk-bootstrap.js", "desk-drawer.js",
                     "desk-polling.js", "desk-preferences.js", "desk-quote-display.js", "ui-common.js",
                     "barlow-semi-condensed-600.ttf"}
                    if page in PUBLIC_DESK_PAGES else {"stored.css", "stored.js", "manrope.ttf"}
                )
                self.assertTrue(expected <= {Path(path.split("?")[0]).name for path in seen}, page)
            self.assertEqual(
                (await client.get("/current/assets/unknown.js")).status, 404
            )


class Composition(unittest.TestCase):
    def test_stable_loaded_asset_api_and_generated_drift_failure(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "build_stored_frontend", root / "scripts/build_stored_frontend.py"
        )
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as folder:
            assets = Path(folder)
            for name in (*builder.JAVASCRIPT, *builder.SCANNER_JAVASCRIPT, *builder.STYLES, "scanner-shell.html", "scanner-style.css"):
                (assets / name).write_bytes((builder.ASSETS / name).read_bytes())
            builder.ASSETS = assets
            for name, body in builder.outputs().items():
                (assets / name).write_text(body)
            self.assertEqual(
                re.findall(
                    r"from\s+[\"\']([^\"\']+)[\"\']", (assets / "stored.js").read_text()
                ),
                [],
            )
            self.assertNotIn("@import", (assets / "stored.css").read_text())
            with patch("sys.argv", ["build_stored_frontend.py", "--check"]):
                builder.main()
                (assets / "stored.css").write_text("body {color: red}")
                with self.assertRaisesRegex(ValueError, "Generated asset drift"):
                    builder.main()
