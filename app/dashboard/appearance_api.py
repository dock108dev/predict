"""Durable appearance for this single-owner, same-origin personal app."""

import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from aiohttp import web

from .local_security import read_json

from .appearance_policy import DEFAULT, validate as validate_appearance


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
        try:
            self.path.stat()
        except FileNotFoundError:
            return dict(DEFAULT)
        # A first writer can create the file before committing its schema. Pin
        # the schema/value read together, and never recreate a vanished file.
        with closing(
            sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)
        ) as db:
            db.execute("BEGIN")
            if not db.execute(
                "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='appearance'"
            ).fetchone():
                return dict(DEFAULT)
            row = db.execute(
                "SELECT value FROM appearance WHERE singleton=1"
            ).fetchone()
        if not row:
            return dict(DEFAULT)
        try:
            value = json.loads(row[0])
            self.validate(value)
        except (ValueError, TypeError) as exc:
            # Invalid saved data is a storage failure, not bad GET input or a
            # reason to overwrite the owner's preference with defaults.
            raise RuntimeError("Saved appearance data is invalid") from exc
        return value

    validate = staticmethod(validate_appearance)

    def save(self, value):
        self.validate(value)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            os.chmod(self.path, 0o600)
            db.execute("BEGIN IMMEDIATE")
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
