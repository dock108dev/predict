"""Ordinary installed routes must serve each module their pages import."""

import re
import importlib.util
import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path
from urllib.parse import urljoin
from aiohttp.test_utils import TestClient, TestServer
from app.dashboard.multi_game_server import create_app
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner


class Assets(unittest.IsolatedAsyncioTestCase):
    async def test_three_ordinary_pages_deliver_their_module_graph(self):
        provider = InjectedTestProvider()
        provider.database_mode = True
        app = create_app(owner=owner(), sessions={}, current_provider=provider)
        async with TestClient(TestServer(app)) as client:
            binding = await (await client.get('/api/scanner/client')).json()
            self.assertTrue(binding['assets_valid'])
            for page in ("/", "/ev", "/arbs", "/odds", "/scanner"):
                response = await client.get(page)
                self.assertEqual(response.status, 200)
                html = await response.text()
                script = re.search(r'<script[^>]+src="([^"]+)"', html).group(1)
                styles = re.findall(r'<link[^>]+href="([^"]+\.css(?:\?[^"]*)?)"', html)
                pending = [script, *styles]
                seen = set()
                while pending:
                    path = pending.pop()
                    if path in seen:
                        continue
                    seen.add(path)
                    response = await client.get(path)
                    self.assertEqual(response.status, 200, path)
                    source = await response.text()
                    self.assertIn(
                        "css" if path.split("?")[0].endswith(".css") else "javascript",
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
                    imports = (
                        re.findall(r"@import\s+url\([\"\']([^\"\']+)[\"\']\)", source)
                        if path.split("?")[0].endswith(".css")
                        else re.findall(r"from\s+['\"]([^'\"]+)['\"]", source)
                    )
                    if path == script and "scanner.js" not in path:
                        self.assertTrue(imports)
                    pending.extend(urljoin(path, module) for module in imports)
                self.assertTrue(
                    {"board-client.js", "board-contract.js", "board-values.js", "board-read.js"}
                    <= {Path(path.split("?")[0]).name for path in seen}
                )
                self.assertTrue(
                    (
                        {"scanner.css", "scanner.js"} if page == "/scanner"
                        else {"stored.css", "stored.js", "board-client.js"}
                    )
                    <= {Path(path.split("?")[0]).name for path in seen}
                )
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
            for name in (*builder.JAVASCRIPT, *builder.SCANNER_JAVASCRIPT, *builder.STYLES, "scanner-shell.html"):
                (assets / name).write_bytes((builder.ASSETS / name).read_bytes())
            builder.ASSETS = assets
            for name, body in builder.outputs().items():
                (assets / name).write_text(body)
            self.assertEqual(
                re.findall(
                    r"from\s+[\"\']([^\"\']+)[\"\']", (assets / "stored.js").read_text()
                ),
                ["./board-client.js"],
            )
            self.assertNotIn("@import", (assets / "stored.css").read_text())
            with patch("sys.argv", ["build_stored_frontend.py", "--check"]):
                builder.main()
                (assets / "stored.css").write_text("body {color: red}")
                with self.assertRaisesRegex(ValueError, "Generated asset drift"):
                    builder.main()
