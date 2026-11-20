"""Durable appearance for this single-owner, same-origin personal app."""

import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3

from aiohttp import web

from .local_security import read_json

DEFAULT = dict(
    palette="prism", primary="#b69ae8", secondary="#edb8dc", appearance="dark"
)


class Appearance:
    def __init__(self, path=None):
        self.path = Path(
            path
            or os.environ.get("PREDICT_PREFERENCES_PATH")
            or Path(__file__).resolve().parents[2]
            / ".local/predict-personal/preferences.sqlite3"
        )
        if not self.path.is_absolute():
            raise ValueError("The personal preferences path must be absolute")

    def read(self):
        if not self.path.exists():
            return dict(DEFAULT)
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            row = db.execute(
                "SELECT value FROM appearance WHERE singleton=1"
            ).fetchone()
        return json.loads(row[0]) if row else dict(DEFAULT)

    def save(self, value):
        if (
            not isinstance(value, dict)
            or set(value) != set(DEFAULT)
            or value.get("appearance") not in ("dark", "light", "system")
            or not isinstance(value.get("palette"), str)
            or not re.fullmatch(r"[a-z]{1,20}", value["palette"])
            or any(
                not isinstance(value.get(k), str)
                or not re.fullmatch(r"#[a-fA-F0-9]{6}", value[k])
                for k in ("primary", "secondary")
            )
        ):
            raise ValueError("Choose an appearance and two six-digit colors")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            os.chmod(self.path, 0o600)
            db.execute(
                "CREATE TABLE IF NOT EXISTS appearance (singleton INTEGER PRIMARY KEY CHECK(singleton=1), value TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO appearance VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET value=excluded.value",
                (json.dumps(value),),
            )
        return dict(value)


def mount(app, *, store=None):
    store = store or Appearance()

    async def preferences(request):
        if request.method == "GET":
            value = await asyncio.to_thread(store.read)
        else:
            body = await read_json(request)
            try:
                value = await asyncio.to_thread(store.save, body)
            except ValueError as exc:
                return web.json_response(dict(error=str(exc)), status=422)
        return web.json_response(value)

    app.router.add_get("/api/appearance", preferences)
    app.router.add_post("/api/appearance", preferences)
