"""Bind scanner compatibility to the actual served files and runtime protocol."""
from hashlib import sha256
import json
from pathlib import Path
from aiohttp import web
from app.comparison.scanner_projection import VERSION


def mount(app):
    async def client(req):
        root = Path(__file__).parent / 'opportunity_static/current'
        try:
            manifest = json.loads((root / 'scanner-runtime.json').read_text())
            valid = set(manifest['assets']) == {'scanner.js', 'scanner.css', 'scanner.html'} and all(
                sha256((root / name).read_bytes()).hexdigest() == expected
                for name, expected in manifest['assets'].items()
            )
            value = dict(protocol=VERSION, asset_revision=manifest['asset_revision'], assets_valid=valid)
        except (OSError, ValueError, KeyError):
            value = dict(protocol=VERSION, asset_revision=None, assets_valid=False)
        return web.json_response(value, headers={'Cache-Control': 'no-store'})
    app.router.add_get('/api/scanner/client', client)
