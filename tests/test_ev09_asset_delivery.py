"""Ordinary installed routes must serve each module their pages import."""

import re
import importlib.util
import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
from aiohttp.test_utils import TestClient, TestServer
from app.dashboard.multi_game_server import create_app
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner


PUBLIC_DESK_PAGES = ("/research", "/data", "/settings")


class Assets(unittest.IsolatedAsyncioTestCase):
    def app(self):
        provider = InjectedTestProvider()
        provider.database_mode = True
        return create_app(owner=owner(), sessions={}, current_provider=provider)

    async def test_research_landing_preserves_selected_legacy_links(self):
        async with TestClient(TestServer(self.app())) as client:
            for path, expected, values in (
                ('/', '/research', {}),
                ('/?id=exact-existing-contract', '/data', {'id':['exact-existing-contract']}),
                ('/experiments', '/research', {'section':['experiments']}),
                ('/experiments?context=1&offset=10', '/data', {'evidence':['checkpoints'],'context':['1'],'offset':['10']}),
                ('/research?id=experiment-one&revision=revision-one', '/data', {'id':['experiment-one'],'revision':['revision-one'],'evidence':['checkpoints']}),
                ('/game?game_key=combined%3Aevent%3Aone&game_capture=captured-one&line=exact-winner', '/data', {'game_key':['combined:event:one'],'game_capture':['captured-one'],'line':['exact-winner']}),
                ('/arbs?game=one&capture=early', '/data', {'view':['arbitrage'],'game':['one'],'capture':['early']}),
                ('/admin?section=inspection&bet=exact-bet', '/data', {'bet':['exact-bet']}),
                ('/admin?section=sources', '/settings', {}),
                ('/raw-odds?original_bookmaker_id=pinnacle', '/data', {'original_bookmaker_id':['pinnacle'],'reference_scope':['all']}),
                ('/view/current/research.html?book=pinnacle', '/data', {'book':['pinnacle'],'original_bookmaker_id':['pinnacle'],'reference_scope':['all']}),
                ('/browse-odds?venue=draftkings&reference_scope=all', '/data', {'venue':['draftkings'],'original_bookmaker_id':['draftkings'],'reference_scope':['all']}),
            ):
                response = await client.get(path, allow_redirects=False)
                self.assertEqual(response.status, 302, path)
                location=urlparse(response.headers['Location'])
                self.assertEqual(location.path, expected, path)
                self.assertEqual(parse_qs(location.query), values, path)
                page=await client.get(response.headers['Location'])
                self.assertEqual(page.status, 200, path)
                self.assertIn('data-workspace-nav', await page.text())

    async def test_static_bookmarks_resolve_to_workspace_context(self):
        async with TestClient(TestServer(self.app())) as client:
            for path, target in (
                ('/view/current/research.html?id=game-one&revision=frozen', '/data'),
                ('/view/current/pregame.html?game=canonical&bet=exact&capture=early', '/data'),
                ('/view/current/pregame-arbs.html?game=canonical', '/data'),
                ('/view/current/admin.html?section=usage', '/settings'),
                ('/view/dashboard.html?capture=retained-one', '/data'),
                ('/current/coverage', '/settings'),
                ('/admin/retained?capture=retained-one', '/data'),
            ):
                response=await client.get(path,allow_redirects=False)
                self.assertEqual(response.status,302,path)
                destination=urlparse(response.headers['Location'])
                self.assertEqual(destination.path,target,path)
                context=parse_qs(urlparse(path).query)
                for key in ('id','revision','game','bet','capture'):
                    if key in context:self.assertEqual(parse_qs(destination.query)[key],context[key])
                page=await client.get(response.headers['Location'])
                self.assertEqual(page.status,200,path)
                self.assertIn('data-workspace-nav',await page.text())

    async def test_retired_bookmarks_have_working_workspace_navigation(self):
        app=self.app()
        async with TestClient(TestServer(app)) as client:
            for path in ('/scanner','/my-bets','/about','/trading-fees','/view/current/scanner.html','/view/current/bet-journal.html'):
                response=await client.get(path)
                self.assertEqual(response.status,410,path)
                html=await response.text()
                self.assertIn('This page is retired',html)
                self.assertIn('href="/data"',html)
                self.assertIn('data-workspace-nav',html)
            # The journal owns more than its retired HTML: retain APIs/sampler.
            routes={route.resource.canonical for route in app.router.routes()}
            self.assertIn('/api/bet-journal',routes)
            self.assertIn('/api/bet-journal/{id}',routes)
            self.assertGreaterEqual(len(app.cleanup_ctx),3)

    async def test_public_desk_declares_the_packaged_browser_icon(self):
        async with TestClient(TestServer(self.app())) as client:
            for path in PUBLIC_DESK_PAGES:
                html=await (await client.get(path)).text()
                icons=re.findall(r'<link rel="(?:icon|apple-touch-icon)"[^>]+href="([^"]+)"',html)
                self.assertEqual(icons,['/view/current/predict-icon.png']*2,path)
            response=await client.get('/view/current/predict-icon.png')
            self.assertTrue((await response.read()).startswith(b"\x89PNG\r\n\x1a\n"))

    async def test_ordinary_pages_deliver_their_module_graph(self):
        async with TestClient(TestServer(self.app())) as client:
            for page in PUBLIC_DESK_PAGES:
                response=await client.get(page)
                self.assertEqual(response.status,200)
                html=await response.text()
                pending=[*re.findall(r'<script[^>]+src="([^"]+)"',html),*re.findall(r'<link[^>]+href="([^"]+\.css(?:\?[^"]*)?)"',html)]
                seen=set()
                while pending:
                    path=pending.pop()
                    if path in seen:continue
                    seen.add(path)
                    response=await client.get(path)
                    self.assertEqual(response.status,200,path)
                    suffix=Path(path.split('?')[0]).suffix
                    self.assertIn({'.css':'css','.js':'javascript','.ttf':'font'}[suffix],response.headers['Content-Type'])
                    if suffix=='.ttf':continue
                    source=await response.text()
                    imports=(re.findall(r"url\([\"\']([^\"\']+)[\"\']\)",source) if suffix=='.css' else re.findall(r"(?:from\s+|import\s*)['\"]([^'\"]+)['\"]",source))
                    pending.extend(urljoin(path,module) for module in imports)
                self.assertTrue({'pregame.css','research.css','workspace-nav.js','manrope.ttf'} <= {Path(path.split('?')[0]).name for path in seen},page)
            self.assertEqual((await client.get('/current/assets/unknown.js')).status,404)


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
                (assets / "stored.css").write_text(builder.outputs()["stored.css"])
                for name in ("pregame-ranking.js", "appearance-policy.js"):
                    (assets / name).write_text("// stale generated metadata")
                    with self.assertRaisesRegex(ValueError, "Generated asset drift: " + name):
                        builder.main()
                    (assets / name).write_text(builder.outputs()[name])

    def test_ranking_catalog_output_tracks_the_python_owner(self):
        from app.storage.pregame_ranking import catalog
        import json

        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("ranking_builder", root / "scripts/build_stored_frontend.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)

        def emitted():
            return json.loads(builder.ranking_javascript().split("export const rankingCatalog = ")[1].rstrip(";\n"))

        self.assertEqual(emitted(), catalog())
        changed = dict(default="fixture", methods=dict(fixture=dict(label="Authored method")))
        with patch.object(builder, "run_path", return_value={"catalog": lambda: changed}):
            self.assertEqual(emitted(), changed)
