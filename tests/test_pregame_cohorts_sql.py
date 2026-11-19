"""Real SQL evidence for independent cohorts and read-only mode selection."""

from datetime import timedelta
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch
import json

from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import PregameFixture, AT, page, parse
from app.storage import current_pregame as board
from app.storage.pregame_cohorts import capture, select
from app.storage.store import stamp


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class PregameCohortsSQL(PregameFixture):
    async def test_lookahead_window_entry_invalidates_empty_cached_view(self):
        from app.storage.pregame_arbs import read as arbs

        with self.connect() as db:
            self.seed_quoted_cohort(db)
            with db.transaction():
                select(db, "monitor")
                query = dict(_scope_seconds="1800")
                first = arbs(db, query, at=stamp(AT))
                self.assertEqual(first["rows"], [])
                entrance = stamp(first["refresh_at"])
                self.assertEqual(entrance, stamp(AT) + timedelta(minutes=30))
                later = arbs(db, query, at=entrance + timedelta(microseconds=1))
                self.assertTrue(later["rows"])
                self.assertNotEqual(first["cursor"], later["cursor"])

    async def test_age_filter_expires_warm_arb_cache_and_schedules_board_refresh(self):
        from app.storage.pregame_arbs import read as arbs

        with self.connect() as db:
            self.seed_quoted_cohort(db)
            with db.transaction():
                select(db, "monitor")
                shown = board.read(
                    db, dict(browse="1", max_age_minutes="2"), at=stamp(AT)
                )
                first = arbs(db, dict(max_age_minutes="2"), at=stamp(AT))
                self.assertTrue(shown["rows"])
                self.assertTrue(first["rows"])
                cutoff = stamp(first["refresh_at"])
                self.assertLessEqual(cutoff, stamp(AT) + timedelta(minutes=2))
                self.assertLessEqual(
                    stamp(shown["refresh_at"]), stamp(AT) + timedelta(minutes=2)
                )
                expired = arbs(
                    db, dict(max_age_minutes="2"), at=cutoff + timedelta(microseconds=1)
                )
                self.assertEqual(expired["rows"], [])

    async def test_derive_reuses_qualified_cashflows_and_batches_references(self):
        from app.comparison import current_pregame as math
        from app.storage.pregame_cohorts import derive

        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            rows = list(
                db.execute("SELECT * FROM pregame_monitor.current_pregame_price")
            )
            self.assertGreater(len(rows), 1)
            # A price without a benchmark can carry a different main-line flag.
            # Revaluation must recompute it from the cohort's actual reference.
            db.execute("""UPDATE pregame_monitor.current_pregame_price
                SET payload=jsonb_set(payload,'{main}','false'::jsonb)""")

            class CountReferenceReads:
                references = 0

                def execute(self, query, params=()):
                    text = query.as_string(db) if hasattr(query, "as_string") else query
                    if (
                        text.lstrip().startswith("SELECT")
                        and "current_sgo_reference" in text
                    ):
                        self.references += 1
                    return db.execute(query, params)

            counted = CountReferenceReads()
            metadata = rows[0]["payload"]["collection"]
            with patch.object(
                math, "calculate", side_effect=AssertionError("price already qualified")
            ):
                derive(
                    counted,
                    "pregame_monitor",
                    [r["contract_id"] for r in rows],
                    stamp(AT),
                    metadata,
                )
            self.assertEqual(counted.references, 1)
            for row in db.execute("""SELECT p.record,p.fee_input,p.game_key,c.payload
                FROM pregame_monitor.current_pregame_price p
                JOIN pregame_monitor.current_pregame_calculation c USING(contract_id)"""):
                actual = row["payload"]
                expected = math.calculate(
                    row["record"],
                    actual["reference"],
                    row["fee_input"],
                    at=stamp(AT),
                    game_key=row["game_key"],
                )
                expected.update(
                    {
                        key: actual[key]
                        for key in (
                            "collection",
                            "input_revision",
                            "sportsbook_event_ids",
                            "sportsbook_sides_reversed",
                        )
                    }
                )
                self.assertEqual(actual, expected)
                self.assertTrue(actual["main"])
                self.assertEqual(actual["times"]["source_at"], "2026-11-17T19:59:00Z")

    async def test_fee_revision_does_not_skip_baseline_and_empty_later_cannot_readopt(
        self,
    ):
        from app.storage.pregame_cohorts import bootstrap, TABLES
        from psycopg import sql

        with self.connect() as db:
            self.ingest(db, page())
            with patch("app.storage.current_rows.utc", return_value=AT):
                board.process(db, at=stamp(AT))
            row = db.execute(
                "SELECT revision,baseline_initialized FROM pregame_monitor.current_pregame_revision"
            ).fetchone()
            self.assertGreater(row["revision"], 0)  # fee setup changed an empty cohort
            self.assertFalse(row["baseline_initialized"])
            self.assertEqual(
                db.execute(
                    "SELECT count(*) n FROM pregame_monitor.current_pregame_price"
                ).fetchone()["n"],
                0,
            )
            bootstrap(db, at=stamp(AT))
            adopted = db.execute(
                "SELECT payload FROM pregame_monitor.current_pregame_price LIMIT 1"
            ).fetchone()["payload"]
            self.assertEqual(adopted["collection"]["origin"], "legacy_retained")
            self.assertEqual(adopted["times"]["source_at"], "2026-11-17T19:59:00Z")
            for table in TABLES:
                db.execute(
                    sql.SQL("TRUNCATE {}").format(
                        sql.Identifier("pregame_monitor", table)
                    )
                )
            bootstrap(db, at=stamp(AT))
            self.assertEqual(
                db.execute(
                    "SELECT count(*) n FROM pregame_monitor.current_pregame_price"
                ).fetchone()["n"],
                0,
            )

    async def test_out_of_window_receipt_cannot_publish_live_cohort(self):
        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            run = dict(
                kind="live",
                id="out-of-window",
                scope_start_at=AT,
                scope_end_at=(stamp(AT) + timedelta(minutes=30)).isoformat(),
            )
            capture(db, run, ["event"], stamp(AT))
            self.assertEqual(
                db.execute(
                    "SELECT count(*) n FROM pregame_live.current_pregame_price"
                ).fetchone()["n"],
                0,
            )
            self.assertTrue(
                db.execute(
                    "SELECT count(*) n FROM public.current_pregame_price"
                ).fetchone()["n"]
            )

    async def test_live_cannot_borrow_omitted_monitor_book_or_venue(self):
        from app.storage.sportsgameodds_reference import prepare_page

        with self.connect() as db:
            data = page()
            self.ingest(db, data)
            self.process(db)
            for odd in data["data"][0]["odds"].values():
                odd["byBookmaker"].pop("draftkings")
            records = self.ingest(db, data)
            with patch("app.storage.current_rows.utc", return_value=AT):
                board.process(db, at=stamp(AT))
            # Global retention still has both books. The Live page has only one.
            self.assertTrue(board.read(db, {}, at=stamp(AT))["rows"])
            capture(
                db,
                dict(kind="live", id="omitted-book"),
                ["event"],
                stamp(AT),
                observed=dict(records=records, references=prepare_page(parse(data))),
            )
            with db.transaction():
                select(db, "live")
                self.assertEqual(board.read(db, {}, at=stamp(AT))["rows"], [])
                prices = board.read(db, {"browse": "1"}, at=stamp(AT))["rows"]
                self.assertTrue(prices)
                self.assertEqual(
                    prices[0]["ev_unavailable_reason"],
                    "reference_two_trusted_books_required",
                )
                self.assertIsNone(prices[0]["raw"]["net_ev"])

    async def test_live_does_not_replace_monitor_and_consolidated_uses_latest(self):
        with self.connect() as db:
            data = page()
            self.ingest(db, data)
            self.process(db)
            with db.transaction():
                select(db, "monitor")
                before = board.read(db, {"browse": "1"}, at=stamp(AT))["rows"]
            self.assertTrue(before)
            for odd in data["data"][0]["odds"].values():
                odd["byBookmaker"]["prophetx"].update(
                    odds="+130", lastUpdatedAt="2026-11-17T19:59:59Z"
                )
            self.ingest(db, data)
            with patch("app.storage.current_rows.utc", return_value=AT):
                board.process(db, at=stamp(AT))
            capture(
                db,
                dict(kind="live", id="live-1"),
                ["event"],
                stamp(AT) + timedelta(seconds=1),
            )
            with db.transaction():
                select(db, "monitor")
                monitor = board.read(
                    db, {"browse": "1"}, at=stamp(AT) + timedelta(seconds=2)
                )["rows"]
            with db.transaction():
                select(db, "live")
                live = board.read(
                    db, {"browse": "1"}, at=stamp(AT) + timedelta(seconds=2)
                )["rows"]
            with db.transaction():
                select(db, "all")
                combined = board.read(
                    db, {"browse": "1"}, at=stamp(AT) + timedelta(seconds=2)
                )["rows"]
            self.assertEqual(monitor, before)
            self.assertNotEqual(live[0]["posted"], monitor[0]["posted"])
            self.assertEqual(live, combined)
            self.assertEqual(live[0]["collection"]["kind"], "live")
            source = live[0]["times"]["source_at"]
            capture(
                db,
                dict(kind="live", id="live-2"),
                ["event"],
                stamp(AT) + timedelta(minutes=1),
            )
            with db.transaction():
                select(db, "live")
                unchanged = board.read(
                    db, {"browse": "1"}, at=stamp(AT) + timedelta(minutes=1)
                )["rows"][0]
            self.assertEqual(unchanged["times"]["source_at"], source)
            self.assertEqual(unchanged["collection"]["run_id"], "live-2")

    async def test_http_mode_defaults_expiry_and_reads_do_not_write(self):
        from app.dashboard.current_pregame_api import response
        from app.collection.activity_mode import patch as change_mode

        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
        query = SimpleNamespace(path="/api/pregame", query={})
        with (
            patch.object(board, "utc", return_value=stamp(AT)),
            patch("app.collection.activity_mode.clock", return_value=stamp(AT)),
        ):
            monitor = json.loads((await response(query, connector=self.connect)).text)
            self.assertEqual(monitor["data_type"], "monitor")
            self.assertTrue(monitor["rows"])
            change_mode(mode="live", at=stamp(AT), connector=self.connect)
            live = json.loads((await response(query, connector=self.connect)).text)
            self.assertEqual(live["data_type"], "live")
            self.assertEqual(live["rows"], [])
            browse = json.loads(
                (
                    await response(
                        SimpleNamespace(path="/api/pregame", query={"browse": "1"}),
                        connector=self.connect,
                    )
                ).text
            )
            self.assertEqual(browse["data_type"], "all")
            self.assertTrue(browse["rows"])
        with (
            patch.object(board, "utc", return_value=stamp(AT) + timedelta(minutes=16)),
            patch(
                "app.collection.activity_mode.clock",
                return_value=stamp(AT) + timedelta(minutes=16),
            ),
        ):
            expired = json.loads((await response(query, connector=self.connect)).text)
            self.assertEqual(expired["data_type"], "monitor")
            self.assertEqual(expired["activity_mode"]["reason"], "inactivity")
        with self.connect() as db:
            # Projection is read-only; scheduler persists expiry independently.
            self.assertEqual(
                db.execute("SELECT mode FROM activity_mode WHERE singleton").fetchone()[
                    "mode"
                ],
                "live",
            )

    def seed_quoted_cohort(self, db):
        from app.fees import pricing
        from tests.test_fee_pricing import rule

        data = page()
        for odd in data["data"][0]["odds"].values():
            quoted = next(iter(odd["byBookmaker"].values()))
            odd["byBookmaker"] = {
                venue: dict(
                    quoted,
                    odds="+125" if venue in ("fanduel", "draftkings") else "+120",
                )
                for venue in ("novig", "prophetx", "fanduel", "draftkings")
            }
        for venue in ("novig", "prophetx"):
            pricing.write(db, venue, [rule(venue)])
        self.ingest(db, data)
        self.process(db)
        return data

    def monitor_reads(self, db):
        from app.storage.pregame_arbs import read as arbs

        with db.transaction():
            select(db, "monitor")
            return (
                board.read(db, {"browse": "1"}, at=stamp(AT)),
                arbs(db, {"data_type": "monitor"}, at=stamp(AT)),
            )

    async def test_known_public_withdrawal_invalidates_warmed_monitor_cache(self):
        with self.connect() as db:
            self.seed_quoted_cohort(db)
            before, pairs = self.monitor_reads(db)
            self.assertTrue(before["rows"])
            self.assertTrue(pairs["rows"])
            self.assertEqual(self.monitor_reads(db)[1]["rows"], pairs["rows"])
            retained = db.execute(
                "SELECT count(*) n FROM pregame_monitor.current_pregame_price"
            ).fetchone()["n"]
            db.execute("""UPDATE public.current_offer_storage
                SET facts=jsonb_set(facts,'{state}','"unavailable"'),revision=revision||'-withdrawn'""")
            after, withdrawn = self.monitor_reads(db)
            self.assertNotEqual(before["cursor"], after["cursor"])
            self.assertEqual(after["rows"], [])
            self.assertEqual(withdrawn["rows"], [])
            self.assertEqual(
                db.execute(
                    "SELECT count(*) n FROM pregame_monitor.current_pregame_price"
                ).fetchone()["n"],
                retained,
            )

    async def test_known_reference_withdrawal_blocks_ev_and_book_leg_only(self):
        with self.connect() as db:
            self.seed_quoted_cohort(db)
            before, pairs = self.monitor_reads(db)
            self.assertTrue(before["rows"])
            self.assertTrue(any(p["category"] == "market_book" for p in pairs["rows"]))
            db.execute("""UPDATE public.sgo_quote_revision SET facts=jsonb_set(facts,'{available}','false')
                WHERE is_current AND bookmaker_id IN ('fanduel','draftkings')""")
            after, pairs = self.monitor_reads(db)
            self.assertEqual(after["rows"], [])
            self.assertTrue(pairs["rows"])
            self.assertTrue(
                all(p["category"] == "market_market" for p in pairs["rows"])
            )

    async def test_missing_public_offer_is_unknown_and_preserves_retained_cohort(self):
        with self.connect() as db:
            self.seed_quoted_cohort(db)
            before, pairs = self.monitor_reads(db)
            db.execute("DELETE FROM public.current_offer_storage")
            retained, retained_pairs = self.monitor_reads(db)
            self.assertEqual(
                [r["posted"] for r in retained["rows"]],
                [r["posted"] for r in before["rows"]],
            )
            self.assertEqual(retained_pairs["rows"], pairs["rows"])

    async def test_known_public_phase_change_invalidates_retained_monitor(self):
        with self.connect() as db:
            self.seed_quoted_cohort(db)
            before, pairs = self.monitor_reads(db)
            self.assertTrue(before["rows"] and pairs["rows"])
            db.execute(
                """UPDATE public.current_event SET facts=jsonb_set(facts,'{status}','{"started":true}'::jsonb),revision=revision||'-started'"""
            )
            after, after_pairs = self.monitor_reads(db)
            self.assertEqual(after["rows"], [])
            self.assertEqual(after_pairs["rows"], [])

    async def test_stale_monitor_capture_keeps_own_prior_and_newer_combined_live(self):
        from copy import deepcopy
        from app.storage.sportsgameodds_reference import prepare_page

        with self.connect() as db:
            monitor_data = self.seed_quoted_cohort(db)
            live_data = deepcopy(monitor_data)
            for odd in live_data["data"][0]["odds"].values():
                for venue in ("novig", "prophetx"):
                    odd["byBookmaker"][venue].update(
                        odds="+130", lastUpdatedAt="2026-11-17T19:59:59Z"
                    )
            live_records = self.ingest(db, live_data)
            with patch("app.storage.current_rows.utc", return_value=AT):
                board.process(db, at=stamp(AT))
            capture(
                db,
                dict(kind="live", id="newer-live"),
                ["event"],
                stamp(AT) + timedelta(seconds=1),
                observed=dict(
                    records=live_records, references=prepare_page(parse(live_data))
                ),
            )
            with db.transaction():
                select(db, "all")
                before_all = board.read(
                    db, {"browse": "1", "venue": "novig"}, at=stamp(AT)
                )["rows"]
            self.assertTrue(before_all)
            self.assertTrue(
                all(r["display"]["posted_odds"] == "+130" for r in before_all)
            )
            # The ordinary writer refuses the delayed old source observations.
            stale_records = self.ingest(db, monitor_data)
            with patch("app.storage.current_rows.utc", return_value=AT):
                board.process(db, at=stamp(AT))
            capture(
                db,
                dict(kind="monitor", id="stale-monitor"),
                ["event"],
                stamp(AT) + timedelta(seconds=2),
                observed=dict(
                    records=stale_records, references=prepare_page(parse(monitor_data))
                ),
            )
            with db.transaction():
                select(db, "all")
                after_all = board.read(
                    db, {"browse": "1", "venue": "novig"}, at=stamp(AT)
                )["rows"]
            with db.transaction():
                select(db, "monitor")
                after_monitor = board.read(
                    db, {"browse": "1", "venue": "novig"}, at=stamp(AT)
                )["rows"]
            self.assertEqual(
                [r["posted"] for r in after_all], [r["posted"] for r in before_all]
            )
            self.assertTrue(after_monitor)
            self.assertTrue(
                all(r["display"]["posted_odds"] == "+120" for r in after_monitor)
            )
            self.assertTrue(all(r["collection"]["kind"] == "live" for r in after_all))

    async def test_combined_keeps_monitor_venue_omitted_from_live_without_borrowing(
        self,
    ):
        from copy import deepcopy
        from app.storage.sportsgameodds_reference import prepare_page

        with self.connect() as db:
            live_data = deepcopy(self.seed_quoted_cohort(db))
            for odd in live_data["data"][0]["odds"].values():
                odd["byBookmaker"].pop("novig")
                odd["byBookmaker"]["prophetx"].update(
                    odds="+130", lastUpdatedAt="2026-11-17T19:59:59Z"
                )
            records = self.ingest(db, live_data)
            with patch("app.storage.current_rows.utc", return_value=AT):
                board.process(db, at=stamp(AT))
            capture(
                db,
                dict(kind="live", id="omitted-novig"),
                ["event"],
                stamp(AT) + timedelta(seconds=1),
                observed=dict(
                    records=records, references=prepare_page(parse(live_data))
                ),
            )
            with db.transaction():
                select(db, "live")
                self.assertEqual(
                    board.read(db, {"browse": "1", "venue": "novig"}, at=stamp(AT))[
                        "rows"
                    ],
                    [],
                )
            with db.transaction():
                select(db, "all")
                novig = board.read(db, {"browse": "1", "venue": "novig"}, at=stamp(AT))[
                    "rows"
                ]
                prophetx = board.read(
                    db, {"browse": "1", "venue": "prophetx"}, at=stamp(AT)
                )["rows"]
            self.assertTrue(novig and prophetx)
            self.assertTrue(
                all(
                    r["collection"]["kind"] == "monitor"
                    and r["display"]["posted_odds"] == "+120"
                    for r in novig
                )
            )
            self.assertTrue(
                all(
                    r["collection"]["kind"] == "live"
                    and r["display"]["posted_odds"] == "+130"
                    for r in prophetx
                )
            )

    async def test_update_cursor_is_mode_bound_even_when_revisions_and_deadlines_match(
        self,
    ):
        with self.connect() as db:
            for schema in ("pregame_monitor", "pregame_live"):
                from psycopg import sql

                db.execute(
                    sql.SQL(
                        "UPDATE {}.current_pregame_revision SET revision=5 WHERE singleton"
                    ).format(sql.Identifier(schema))
                )
            with db.transaction():
                select(db, "monitor")
                monitor = board.read(db, {"updates": "1"}, at=stamp(AT))
            with db.transaction():
                select(db, "live")
                live = board.read(
                    db, {"updates": "1", "after": monitor["cursor"]}, at=stamp(AT)
                )
            self.assertNotEqual(monitor["cursor"], live["cursor"])
            self.assertTrue(live["changed"])
