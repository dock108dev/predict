"""Disposable current-pregame source/fee fixtures shared by SQL scenarios."""

from copy import deepcopy
import asyncio
import json
from tests.latest_board_fixture import LatestBoardFixture
from tests.test_sportsgameodds_adapter import response
from app.collection.sportsgameodds_adapter import parse_page
from app.collection.sportsgameodds_current_rows import current_rows
from app.storage.current_rows import CurrentRowStore
from app.storage.sportsgameodds_reference import (
    prepare_page,
    prepare_frames,
    upsert_rows,
    upsert_frames,
)
from app.storage.store import stamp
from app.storage import current_pregame as board
from unittest.mock import patch

AT = "2026-11-17T20:00:00Z"


def parse(data):
    return parse_page(json.dumps(data).encode(), AT)


def page():
    data = json.loads(json.dumps(response()).replace("2026-11-10", "2026-11-17"))
    event = data["data"][0]
    event["teams"]["home"]["names"]["long"] = "Orlando Magic"
    event["teams"]["away"]["names"]["long"] = "Milwaukee Bucks"
    odd = next(iter(event["odds"].values()))
    book = next(iter(odd["byBookmaker"].values()))
    odd["byBookmaker"] = {
        "prophetx": dict(book, odds="+120"),
        "fanduel": book,
        "draftkings": dict(book, odds="-130"),
    }
    other = deepcopy(odd)
    other.update(
        oddID=odd["opposingOddID"],
        opposingOddID=odd["oddID"],
        statEntityID="away",
        sideID="away",
    )
    other["byBookmaker"] = {
        k: dict(v, spread="1.5", odds="-110") for k, v in other["byBookmaker"].items()
    }
    event["odds"][other["oddID"]] = other
    return data


class PregameFixture(LatestBoardFixture):
    async def asyncSetUp(self):
        with self.connect() as db:
            db.execute(
                "TRUNCATE current_event,sgo_event_evidence,sgo_quote_revision,current_pregame_work CASCADE"
            )
            from tests.test_public_fee_schedule import attempt, PDF
            from hashlib import sha256
            from app.fees import schedule_lifecycle

            approved = dict(
                schedule_lifecycle.approved(), document_sha256=sha256(PDF).hexdigest()
            )
            schedule_lifecycle.write(
                db, await asyncio.to_thread(attempt, approved, at=stamp(AT))
            )

    def ingest(self, db, data):
        parsed = parse(data)
        refs = prepare_page(parsed)
        with db.transaction():
            upsert_rows(db, refs)
            upsert_frames(db, prepare_frames(parsed, refs))
            records = current_rows(parsed, parsed.receipt_sha256)[0]
            CurrentRowStore(db).upsert_records(records, now=AT)
        return records

    def process(self, db, **kwargs):
        with patch("app.storage.current_rows.utc", return_value=AT):
            return board.process(db, at=stamp(AT), **kwargs)
