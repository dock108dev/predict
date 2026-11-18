"""Current pregame ingestion, coherent values, retention and pure read coverage."""

from copy import deepcopy
from datetime import timedelta
from fractions import Fraction
from time import monotonic
from unittest import skipUnless
from unittest.mock import patch

from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_sportsgameodds_adapter import response
from app.collection.sportsgameodds_adapter import parse_page
import json
import asyncio

AT = "2026-11-17T20:00:00Z"


def parse(data):
    return parse_page(json.dumps(data).encode(), AT)


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


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class CurrentPregameSQL(LatestBoardFixture):
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

    async def test_atomic_current_values_under_one_second_and_read_only(self):
        with self.connect() as db:
            started = monotonic()
            records = self.ingest(db, page())
            result = self.process(db)
            elapsed = monotonic() - started
            self.assertLess(elapsed, 1, result)
            out = board.read(db, {}, at=stamp(AT))
            self.assertEqual(
                out["total"],
                1,
                (
                    result,
                    list(db.execute("SELECT reason FROM current_pregame_calculation")),
                ),
            )
            row = out["rows"][0]
            self.assertEqual(row["reference"]["book"], "fanduel")
            self.assertEqual(Fraction(row["reference"]["probability"]), Fraction(1, 2))
            self.assertEqual(row["posted"]["value"], "+120")
            self.assertGreater(Fraction(row["raw"]["net_ev"]), 0)
            self.assertEqual(
                Fraction(row["raw"]["after_fee_decimal"]), Fraction(272, 125)
            )
            self.assertEqual(
                row["fee"]["cashflows"]["win"]["settlement_fee_usd"], "2.4"
            )
            pending = db.execute(
                "SELECT count(*) n FROM current_pregame_work"
            ).fetchone()["n"]
            with patch(
                "app.storage.current_pregame.process",
                side_effect=AssertionError("read scheduled work"),
            ):
                self.assertEqual(board.read(db, {}, at=stamp(AT))["rows"], out["rows"])
                comparison = board.read(db, {"bet_id": row["bet_id"]}, at=stamp(AT))
                self.assertEqual(comparison["rows"][0], row)
            self.assertEqual(
                pending,
                db.execute("SELECT count(*) n FROM current_pregame_work").fetchone()[
                    "n"
                ],
            )
            print(
                "current pregame admission-to-queryable seconds",
                elapsed,
                "offers",
                len(records),
            )

    async def test_http_updates_watch_committed_prices_without_publication(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        from app.dashboard import snapshot_api

        with self.connect() as db:
            data = page()
            self.ingest(db, data)
            self.process(db)
        app = web.Application()
        snapshot_api.mount(app)
        with (
            patch.object(snapshot_api, "connect", self.connect),
            patch.object(board, "utc", return_value=stamp(AT)),
        ):
            async with TestClient(TestServer(app)) as client:
                query = dict(layout="desk", browse_odds="1")
                first = await (
                    await client.get("/api/comparison-current", params=query)
                ).json()
                self.assertTrue(first["rows"])
                update_query = dict(layout="desk", after=first["cursor"])
                with patch(
                    "app.storage.ordinary_publication.published_dependencies",
                    side_effect=AssertionError("Update decoded publication"),
                ):
                    same = await (
                        await client.get(
                            "/api/comparison-current/updates", params=update_query
                        )
                    ).json()
                    self.assertFalse(same["changed"])
                    changed = deepcopy(data)
                    for odd in changed["data"][0]["odds"].values():
                        odd["byBookmaker"]["prophetx"]["odds"] = "+130"
                        odd["byBookmaker"]["prophetx"]["lastUpdatedAt"] = (
                            "2026-11-17T19:59:59Z"
                        )
                    with self.connect() as db:
                        self.ingest(db, changed)
                    pending = await (
                        await client.get("/api/comparison-current", params=query)
                    ).json()
                    self.assertEqual(pending["rows"], first["rows"])
                    with self.connect() as db:
                        self.process(db)
                    signal = await (
                        await client.get(
                            "/api/comparison-current/updates", params=update_query
                        )
                    ).json()
                    self.assertTrue(signal["changed"])
                    self.assertEqual(signal["scheduled_calculations"], 0)
                    latest = await (
                        await client.get("/api/comparison-current", params=query)
                    ).json()
                    self.assertTrue(
                        any(row["posted"]["value"] == "+130" for row in latest["rows"])
                    )
                with patch.object(
                    board, "utc", return_value=stamp(first["rows"][0]["kickoff"])
                ):
                    kicked_off = await (
                        await client.get("/api/comparison-current", params=query)
                    ).json()
                    self.assertEqual(kicked_off["rows"], [])

    async def test_dense_game_keeps_exact_lines_and_complete_atomic_rows(self):
        from app.fees import pricing
        from tests.test_fee_pricing import rule

        data = page()
        venues = ("kalshi", "polymarket_us", "novig", "prophetx")
        for side, odd in enumerate(data["data"][0]["odds"].values()):
            template = deepcopy(odd["byBookmaker"]["prophetx"])
            for venue in ("kalshi", "polymarket", "novig"):
                odd["byBookmaker"][venue] = deepcopy(template)
            for book in odd["byBookmaker"].values():
                book["altLines"] = [
                    dict(book, spread=str((1 if side else -1) * (n + 2.5)))
                    for n in range(50)
                ]
        with self.connect() as db:
            for venue in venues:
                pricing.write(db, venue, [rule(venue)])
            started = monotonic()
            with patch.object(
                board,
                "configured_routes",
                return_value={v: "sportsgameodds" for v in venues},
            ):
                records = self.ingest(db, data)
                result = self.process(db)
                complete = board.read(
                    db, dict(lines="all", browse="1", limit="100"), at=stamp(AT)
                )
            self.assertEqual(len(records), 408)
            self.assertEqual(sum(row["complete"] for row in result), 408)
            self.assertEqual(complete["total"], 102)
            self.assertEqual(len({row["bet_id"] for row in complete["rows"]}), 100)
            self.assertEqual(
                db.execute(
                    "SELECT count(*) n FROM current_pregame_calculation WHERE reason IS NULL"
                ).fetchone()["n"],
                408,
            )
            print(
                "dense current game: 408 offers, 102 exact bets, admission-through-read seconds",
                monotonic() - started,
            )

    async def test_shared_reference_does_not_mask_one_venues_scoring_conflict(self):
        from app.fees import pricing
        from tests.test_fee_pricing import rule

        data = page()
        for odd in data["data"][0]["odds"].values():
            odd["byBookmaker"]["novig"] = deepcopy(odd["byBookmaker"]["prophetx"])
        with self.connect() as db:
            for venue in ("novig", "prophetx"):
                pricing.write(db, venue, [rule(venue)])
            self.ingest(db, data)
            self.process(db)
            chosen = next(
                row
                for row in board.read(db, dict(venue="prophetx"), at=stamp(AT))["rows"]
            )
            db.execute(
                "UPDATE current_contract_storage SET facts=jsonb_set(facts,'{comparison_source_metadata,scoring_scope}',%s::jsonb),revision=revision||'-conflict' WHERE id=%s",
                ('{"conflicts":["overtime"]}', chosen["id"]),
            )
            self.process(db)
            compared = board.read(db, dict(bet_id=chosen["bet_id"]), at=stamp(AT))[
                "rows"
            ]
            self.assertEqual({row["venue"] for row in compared}, {"novig"})
            self.assertEqual(
                db.execute(
                    "SELECT reason FROM current_pregame_calculation WHERE contract_id=%s",
                    (chosen["id"],),
                ).fetchone()["reason"],
                "reference_scoring_scope_conflict",
            )

    async def test_inactive_direct_route_recovers_without_dropping_source_offers(self):
        from tests.broad_pipeline_fixtures import captured_partial
        from tests.multisport_fixtures import source_case

        case = dict(
            source_case("NBA", "spread", "inactive-direct", clock=stamp(AT)),
            period="full_game",
        )
        records, excluded, book, _ = await captured_partial(case, "kalshi")
        self.assertEqual(excluded, [])
        with self.connect() as db:
            CurrentRowStore(db).upsert_records(records, now=AT)
            CurrentRowStore(db).replace_native_books([book])
            before = db.execute("SELECT count(*) n FROM current_offer").fetchone()["n"]
            with patch.object(
                board,
                "configured_routes",
                return_value={
                    v: "sportsgameodds"
                    for v in ("kalshi", "polymarket_us", "novig", "prophetx")
                },
            ):
                result = self.process(db)
            self.assertTrue(result)
            self.assertTrue(all("error" not in row for row in result), result)
            self.assertEqual(
                db.execute("SELECT count(*) n FROM current_offer").fetchone()["n"],
                before,
            )
            self.assertEqual(
                db.execute("SELECT count(*) n FROM current_pregame_work").fetchone()[
                    "n"
                ],
                0,
            )

    async def test_http_health_checks_supported_sql_without_calculation(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        from app.dashboard import current_pregame_api

        application = web.Application()
        current_pregame_api.mount(application)
        with (
            patch.object(current_pregame_api, "connect", self.connect),
            patch.object(
                board,
                "process",
                side_effect=AssertionError("health scheduled calculation"),
            ),
        ):
            async with TestClient(TestServer(application)) as client:
                response = await client.get("/api/health")
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.json(), dict(read_available=True))
                with patch.object(
                    current_pregame_api, "connect", side_effect=OSError("SQL offline")
                ):
                    failed = await client.get("/api/health")
                    self.assertEqual(failed.status, 503)

    async def test_partial_page_old_update_failure_and_kickoff(self):
        with self.connect() as db:
            data = page()
            self.ingest(db, data)
            self.process(db)
            first = board.read(db, {}, at=stamp(AT))
            self.assertEqual(first["total"], 1)
            partial = deepcopy(data)
            odd = next(iter(partial["data"][0]["odds"].values()))
            odd["byBookmaker"] = {"fanduel": odd["byBookmaker"]["fanduel"]}
            partial["data"][0]["odds"] = {odd["oddID"]: odd}
            self.ingest(db, partial)
            self.process(db)
            self.assertEqual(board.read(db, {}, at=stamp(AT))["rows"], first["rows"])
            older = deepcopy(data)
            for odd in older["data"][0]["odds"].values():
                for quote in odd["byBookmaker"].values():
                    quote.update(lastUpdatedAt="2026-11-17T19:58:00Z", odds="+500")
            self.ingest(db, older)
            self.process(db)
            self.assertEqual(board.read(db, {}, at=stamp(AT))["rows"], first["rows"])
            # No collector response is needed to remove a started occurrence.
            self.assertEqual(
                board.read(db, {}, at=stamp("2026-11-17T21:00:00Z"))["total"], 0
            )

    async def test_withdrawal_exact_main_line_and_failure_isolation(self):
        with self.connect() as db:
            data = page()
            self.ingest(db, data)
            self.process(db)
            row = board.read(db, {}, at=stamp(AT))["rows"][0]
            event = db.execute(
                "SELECT e.id,e.facts FROM current_event e JOIN current_contract c ON c.event_id=e.id WHERE c.id=%s",
                (row["id"],),
            ).fetchone()
            from psycopg.types.json import Jsonb

            cancelled = dict(event["facts"], status=dict(status="cancelled"))
            db.execute(
                "UPDATE current_event SET facts=%s WHERE id=%s",
                (Jsonb(cancelled), event["id"]),
            )
            self.assertEqual(board.read(db, {}, at=stamp(AT))["total"], 0)
            db.execute(
                "UPDATE current_event SET facts=%s WHERE id=%s",
                (Jsonb(event["facts"]), event["id"]),
            )
            db.execute(
                "UPDATE sgo_quote_revision SET facts=jsonb_set(facts,'{available}','false') WHERE is_current AND bookmaker_id='fanduel'"
            )
            self.assertEqual(board.read(db, {}, at=stamp(AT))["total"], 0)
            self.process(db)
            # The next eligible complete same-book reference is selected.
            self.assertEqual(
                board.read(db, {"browse": "1"}, at=stamp(AT))["rows"][0]["reference"][
                    "book"
                ],
                "draftkings",
            )
            db.execute(
                "UPDATE current_contract_storage SET facts=jsonb_set(facts,'{comparison_source_metadata,alternate}','true'),revision='alternate' WHERE id=%s",
                (row["id"],),
            )
            self.process(db)
            self.assertEqual(board.read(db, {}, at=stamp(AT))["total"], 0)
            self.assertGreater(
                board.read(db, {"lines": "all", "browse": "1"}, at=stamp(AT))["total"],
                0,
            )
            db.execute("SELECT pregame_enqueue('kalshi','broken-game')")
            db.execute("SELECT pregame_enqueue('kalshi','healthy-game')")
            original = board.calculate_game

            def fail_one(db, job, context, **kwargs):
                if job["native_event_id"] == "broken-game":
                    raise ValueError("authored isolated failure")
                return original(db, job, context, **kwargs)

            with patch.object(board, "calculate_game", side_effect=fail_one):
                result = self.process(db)
            self.assertTrue(any(r.get("error") for r in result))
            self.assertFalse(
                db.execute(
                    "SELECT 1 FROM current_pregame_work WHERE native_event_id='healthy-game'"
                ).fetchone()
            )
            self.assertTrue(
                db.execute(
                    "SELECT 1 FROM current_pregame_work WHERE native_event_id='broken-game'"
                ).fetchone()
            )

    async def test_restart_recovers_admitted_work_without_replaying_sources(self):
        with self.connect() as db:
            self.ingest(db, page())
            self.assertTrue(db.execute("SELECT 1 FROM current_pregame_work").fetchone())
        with self.connect() as reopened:
            self.process(reopened)
            self.assertEqual(board.read(reopened, {}, at=stamp(AT))["total"], 1)
            self.assertFalse(
                reopened.execute("SELECT 1 FROM current_pregame_work").fetchone()
            )

    async def test_exact_reference_priority_alternate_285_and_confirmation_clocks(self):
        with self.connect() as db:
            data = page()
            odds = data["data"][0]["odds"]
            home, away = list(odds.values())
            home["byBookmaker"]["prophetx"]["altLines"] = [
                dict(home["byBookmaker"]["prophetx"], spread="28.5", odds="-4000")
            ]
            away["byBookmaker"]["prophetx"]["altLines"] = [
                dict(away["byBookmaker"]["prophetx"], spread="-28.5", odds="+3000")
            ]
            for book in ("fanduel", "draftkings"):
                home["byBookmaker"][book]["altLines"] = [
                    dict(home["byBookmaker"][book], spread="28.5", odds="-4000")
                ]
                away["byBookmaker"][book]["altLines"] = [
                    dict(away["byBookmaker"][book], spread="-28.5", odds="+3000")
                ]
            self.ingest(db, data)
            self.process(db)
            default = board.read(db, {"browse": "1"}, at=stamp(AT))
            self.assertTrue(default["rows"])
            self.assertTrue(
                all(
                    r["main"] and r["selection"]["signed_line"] not in ("28.5", "-28.5")
                    for r in default["rows"]
                )
            )
            alternates = board.read(db, {"browse": "1", "lines": "all"}, at=stamp(AT))
            alternate = next(
                r for r in alternates["rows"] if r["selection"]["signed_line"] == "28.5"
            )
            self.assertFalse(alternate["main"])
            self.assertEqual(alternate["reference"]["book"], "fanduel")
            self.assertEqual(
                board.read(db, {"id": alternate["id"]}, at=stamp(AT))["rows"][0],
                alternate,
            )
            clocks = {r["id"]: r["times"] for r in alternates["rows"]}
            self.ingest(db, data)
            self.process(db)
            self.assertEqual(
                clocks,
                {
                    r["id"]: r["times"]
                    for r in board.read(
                        db, {"browse": "1", "lines": "all"}, at=stamp(AT)
                    )["rows"]
                },
            )

    async def test_delayed_calculation_cannot_overwrite_newer_admission(self):
        from threading import Event
        from concurrent.futures import ThreadPoolExecutor

        entered, release = Event(), Event()
        original = board.calculate_game
        with self.connect() as db:
            self.ingest(db, page())

        def paused(db, job, context, **kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return original(db, job, context, **kwargs)

        def work():
            with self.connect() as db:
                return self.process(db)

        newer = page()
        home = next(iter(newer["data"][0]["odds"].values()))
        home["byBookmaker"]["prophetx"].update(
            odds="+150", lastUpdatedAt="2026-11-17T19:59:30Z"
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            with patch.object(board, "calculate_game", side_effect=paused):
                old = executor.submit(work)
                self.assertTrue(entered.wait(2))

                def admit_new():
                    with self.connect() as db:
                        self.ingest(db, newer)

                admitted = executor.submit(admit_new)
                release.set()
                old.result(timeout=3)
                admitted.result(timeout=3)
        with self.connect() as db:
            self.process(db)
            row = board.read(db, {}, at=stamp(AT))["rows"][0]
            self.assertEqual(row["posted"]["value"], "+150")
            self.assertEqual(row["times"]["source_at"], "2026-11-17T19:59:30Z")

    async def test_novig_posted_normalization_uses_payout_cent_grid(self):
        from app.comparison import current_pregame as arithmetic
        from app.comparison.cashflows import exact_wire

        records = None
        with self.connect() as db:
            data = page()
            for odd in data["data"][0]["odds"].values():
                odd["byBookmaker"]["novig"] = odd["byBookmaker"].pop("prophetx")
            records = self.ingest(db, data)
            record = next(
                r for r in records if r["quote"]["original"]["value"] == "+120"
            )
            refs = prepare_page(parse(data))
            ref = arithmetic.reference(record, {"event": refs}, at=stamp(AT))

            # Authored zero fee isolates the legal payout grid from applicability proof.
            def fee_adapter(*_):
                return (
                    (lambda levels, stake: (Fraction(0), Fraction(0), {}, [])),
                    {"fixture": "grid"},
                    Fraction(0),
                )

            with patch.object(arithmetic, "retail_order", side_effect=fee_adapter):
                row = arithmetic.calculate(
                    record,
                    ref,
                    dict(classification="synthetic"),
                    at=stamp(AT),
                    game_key="grid",
                )
            winning = Fraction(row["fee"]["cashflows"]["win"]["net_receipt_usd"])
            self.assertEqual((winning * 100).denominator, 1)
            self.assertLessEqual(Fraction(row["fee"]["committed_usd"]), 100)
            self.assertEqual(row["fee"]["entry_usd"], exact_wire(Fraction(0)))
