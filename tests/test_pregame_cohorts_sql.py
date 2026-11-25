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


def arbs(db, query, *, at):
    from app.storage.pregame_arbs import read_cohort

    # These fixtures own cohort rows. The ordinary SportsGameOdds selector
    # reads acquisition snapshots and has a separate disposable-SQL contract.
    return read_cohort(db, dict(provider="sportsgameodds", reference_scope="selected", **query), at=at)


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class PregameCohortsSQL(PregameFixture):
    async def test_committed_sgo_receipt_recovers_monitor_after_projection_timeout(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import AsyncMock
        from psycopg.errors import QueryCanceled
        from app.collection.current_database import (
            DatabaseIngressSink,
            DatabasePipeline,
        )
        from app.collection.current_policy import DEFAULT
        from app.collection.current_service import CurrentService
        from app.collection.local_ownership import LocalOwnership
        from app.collection.sportsgameodds_worker import SportsGameOddsWorker
        from app.dashboard.current_state import CurrentStore
        from app.storage import pregame_cohorts

        def offers(db):
            return db.execute("""SELECT o.contract_id,o.revision,o.source_at,o.received_at
                FROM public.current_offer_storage o JOIN public.current_contract c ON c.id=o.contract_id
                JOIN public.current_event e ON e.id=c.event_id
                WHERE e.provider='sportsgameodds' ORDER BY o.contract_id""").fetchall()

        def revision(db):
            return db.execute(
                "SELECT revision FROM pregame_monitor.current_pregame_revision"
            ).fetchone()["revision"]

        def restore_baseline(initialized):
            with self.connect() as db:
                db.execute("UPDATE pregame_monitor.current_pregame_revision SET baseline_initialized=%s", (initialized,))

        def monitor(db):
            with db.transaction():
                select(db, "monitor")
                return board.read(db, {}, at=stamp(AT))

        def cancel_sql(db, *_args, **_kwargs):
            with db.transaction():
                db.execute("SET LOCAL statement_timeout='20ms'")
                try:
                    db.execute("SELECT pg_sleep(1)")
                except QueryCanceled as exc:
                    self.assertEqual(exc.sqlstate, "57014")
                    raise

        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = dict(
                DEFAULT,
                aggregate_provider="sportsgameodds",
                sports=["NBA"],
                families=["spread"],
                direct_novig_enabled=False,
            )
            service = CurrentService(
                config,
                directory=root / "state",
                ownership=LocalOwnership(root / "owner"),
                database_mode=True,
            )
            service.dispatch = True
            service.store = CurrentStore(service)
            service.sink = DatabaseIngressSink(service.store, service.config)
            requester = AsyncMock()
            worker = SportsGameOddsWorker(
                service,
                transport=SimpleNamespace(request=requester),
                ledger_path=root / "ledger",
                study_path=root / "study",
                now=lambda: stamp(AT),
            )
            worker.collection_run = dict(id="monitor-timeout-recovery", kind="monitor")
            incoming = parse(page())
            with self.connect() as db:
                db.execute("TRUNCATE public.pregame_cohort_work")
                # The one-time adoption of old rows cannot stand in for recovery.
                initialized = db.execute("SELECT baseline_initialized FROM pregame_monitor.current_pregame_revision").fetchone()["baseline_initialized"]
                self.addCleanup(restore_baseline, initialized)
                db.execute(
                    "UPDATE pregame_monitor.current_pregame_revision SET baseline_initialized=true"
                )
                before = revision(db)
            self.enterContext(
                patch(
                    "app.collection.current_database.connect", side_effect=self.connect
                )
            )
            self.enterContext(
                patch("app.collection.current_database.utc", return_value=AT)
            )
            self.enterContext(patch("app.storage.current_rows.utc", return_value=AT))
            self.enterContext(
                patch("app.storage.current_pregame.utc", return_value=stamp(AT))
            )
            self.enterContext(
                patch("app.storage.odds_archive.enabled", return_value=False)
            )

            with patch.object(
                pregame_cohorts, "capture", side_effect=cancel_sql
            ) as failed_capture:
                await worker._publish(incoming)
            failed_capture.assert_called_once()
            self.assertEqual(service.sink.metrics["admitted_observations"], 1)
            self.assertEqual(service.sink.metrics["rejected_observations"], 0)
            self.assertEqual(service.sink.metrics.get("transaction_retries", 0), 0)
            self.assertEqual(
                service.sink.metrics["cohort_projection"]["reason"],
                "cohort_projection_failed",
            )
            with self.connect() as db:
                committed = offers(db)
                self.assertTrue(committed)
                self.assertEqual(monitor(db)["rows"], [])
                self.assertEqual(revision(db), before)
                self.assertEqual(
                    db.execute(
                        "SELECT last_error,snapshot IS NOT NULL staged FROM public.pregame_cohort_work"
                    ).fetchall(),
                    [dict(last_error="cohort_projection_failed", staged=True)],
                )
                receipts = db.execute(
                    "SELECT provider,league,received_at,admitted_at FROM public.delivery_clock"
                    " WHERE provider='sportsgameodds' AND received_at=%s",
                    (AT,),
                ).fetchall()
                self.assertEqual(len(receipts), 1)

            # A later Live page can replace the shared current quote. It cannot
            # stand in for the failed Monitor page when the collector restarts.
            from app.collection.sportsgameodds_adapter import parse_page

            live_at = (stamp(AT) + timedelta(minutes=1)).isoformat()
            live_raw = page()
            for odd in live_raw["data"][0]["odds"].values():
                for book, quote in odd["byBookmaker"].items():
                    quote["lastUpdatedAt"] = live_at
                    if book == "prophetx":
                        quote["odds"] = "+180" if odd["sideID"] == "home" else "-170"
            worker.collection_run = dict(id="live-after-monitor-timeout", kind="live")
            with patch("app.collection.current_database.utc", return_value=live_at):
                await worker._publish(
                    parse_page(json.dumps(live_raw).encode(), live_at)
                )
            with self.connect() as db:
                newest = offers(db)
                self.assertNotEqual(newest, committed)
                live_prices = db.execute(
                    "SELECT payload#>>'{posted,value}' price FROM pregame_live.current_pregame_price"
                ).fetchall()
                self.assertIn(dict(price="+180"), live_prices)

            # A fresh pipeline gets all recovery inputs from PostgreSQL. It
            # never constructs or replays a SportsGameOdds request.
            restarted = DatabasePipeline(SimpleNamespace(config=service.config))
            await restarted.start()
            try:
                self.assertEqual(
                    restarted.cohort_projection, dict(completed=1, pending=[])
                )
                restarted.recover_cohorts()
                with self.connect() as db:
                    rows = monitor(db)["rows"]
                    self.assertTrue(rows)
                    self.assertEqual(
                        {row["collection"]["run_id"] for row in rows},
                        {"monitor-timeout-recovery"},
                    )
                    self.assertIn("+120", {row["posted"]["value"] for row in rows})
                    self.assertNotIn("+180", {row["posted"]["value"] for row in rows})
                    self.assertEqual(offers(db), newest)
                    self.assertEqual(revision(db), before + 1)
                    self.assertEqual(
                        db.execute(
                            "SELECT id FROM public.pregame_cohort_work"
                        ).fetchall(),
                        [],
                    )
                    self.assertEqual(
                        db.execute(
                            "SELECT provider,league,received_at,admitted_at FROM public.delivery_clock"
                            " WHERE provider='sportsgameodds' AND received_at=%s",
                            (AT,),
                        ).fetchall(),
                        receipts,
                    )
                requester.assert_not_called()
                self.assertEqual(worker.metrics["requests"], 0)
            finally:
                await restarted.close()
                await service.store.close()

    async def test_reference_scope_covers_eligible_ev_and_reference_free_arb_prices(
        self,
    ):
        with self.connect() as writer:
            self.seed_quoted_cohort(writer)
            for schema in ("pregame_monitor", "pregame_combined"):
                from psycopg import sql

                self.assertEqual(
                    writer.execute(
                        sql.SQL("""SELECT count(*) n FROM {}.current_pregame_price
                    WHERE payload->'reference' IS DISTINCT FROM 'null'::jsonb""").format(
                            sql.Identifier(schema)
                        )
                    ).fetchone()["n"],
                    0,
                )
                self.assertEqual(
                    writer.execute(
                        sql.SQL("""SELECT count(*) n
                    FROM {}.current_pregame_calculation p
                    CROSS JOIN LATERAL jsonb_array_elements(p.payload#>'{{reference,prices}}') r
                    LEFT JOIN {}.current_sgo_reference s ON s.id=r->>'input_id'
                    WHERE p.reason IS NULL AND s.id IS NULL""").format(
                            sql.Identifier(schema), sql.Identifier(schema)
                        )
                    ).fetchone()["n"],
                    0,
                )
            with self.connect() as reader, reader.transaction():
                select(reader, "monitor")
                before = board.read(reader, {}, at=stamp(AT))
            self.assertTrue(before["rows"])
            # Retained/legacy calculations may outlive a reference row. Their
            # existing positive eligibility guard already rejects them, so an
            # absent reference cannot be an uncaptured withdrawal dependency.
            writer.execute("DELETE FROM pregame_monitor.current_sgo_reference")
            writer.execute(
                "UPDATE pregame_monitor.current_pregame_revision SET revision=revision+1"
            )
            with self.connect() as reader, reader.transaction():
                select(reader, "monitor")
                missing = board.read(reader, {}, at=stamp(AT))
            self.assertEqual(missing["rows"], [])
            self.assertNotEqual(missing["cursor"], before["cursor"])

    async def test_public_positive_changes_keep_cross_transaction_filter_cache(self):
        from app.storage.pregame_arbs import ordered_pairs

        heavy = []

        class Traced:
            def __init__(self, db):
                self.db, self.info = db, db.info

            def transaction(self):
                return self.db.transaction()

            def execute(self, query, parameters=None):
                if query.startswith(
                    (
                        "SELECT p.",
                        "WITH requested",
                        "SELECT contract_id,game_key,valid_until,payload,record,fee_input",
                    )
                ):
                    heavy.append(query[:35])
                return self.db.execute(query, parameters)

        def read(query):
            with self.connect() as reader, reader.transaction():
                reader.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                select(reader, "monitor")
                return arbs(
                    Traced(reader),
                    dict(data_type="monitor", limit="100", **query),
                    at=stamp(AT),
                )

        with self.connect() as writer:
            self.seed_quoted_cohort(writer)
            before = read({})
            self.assertTrue(before["rows"])
            self.assertTrue(heavy)
            heavy.clear()
            writer.execute("""UPDATE public.sgo_quote_revision SET facts=jsonb_set(
                facts,'{price_american}','\"+180\"') WHERE is_current""")
            writer.execute(
                "UPDATE public.current_pregame_revision SET revision=revision+1"
            )
            changed = read(dict(sort="start"))
            self.assertEqual(changed["cursor"], before["cursor"])
            self.assertEqual(changed["rows"], ordered_pairs(before["rows"], "start"))
            filtered = read(dict(league=before["rows"][0]["league"]))
            self.assertEqual(filtered["rows"], before["rows"])
            writer.execute("""INSERT INTO public.sgo_quote_revision
                (id,event_id,bookmaker_id,source_order,received_order,expires_at,revision,facts,is_current)
                SELECT id||'-unrelated','unrelated',bookmaker_id,source_order,received_order,
                  expires_at,revision,jsonb_set(facts,'{available}','false'),true
                FROM public.sgo_quote_revision WHERE is_current LIMIT 1""")
            writer.execute("""INSERT INTO public.sgo_line_presence
                (quote_id,event_id,bookmaker_id,odd_id,last_seen,scope_received,expired)
                VALUES('unrelated','unrelated','fanduel','unrelated',0,0,true)""")
            unrelated = read(dict(sort="start"))
            self.assertEqual(unrelated["cursor"], before["cursor"])
            self.assertEqual(unrelated["rows"], changed["rows"])
            self.assertEqual(heavy, [])

    async def test_cohort_authority_additions_and_removals_invalidate_cursor(self):
        def cursor(at=stamp(AT)):
            with self.connect() as reader, reader.transaction():
                select(reader, "monitor")
                return board.read(reader, dict(updates="1"), at=at)

        with self.connect() as writer:
            self.seed_quoted_cohort(writer)
            writer.execute("""INSERT INTO public.sgo_line_presence
                (quote_id,event_id,bookmaker_id,odd_id,last_seen,scope_received,expired)
                SELECT id,event_id,bookmaker_id,facts->>'odd_id',0,0,false
                FROM public.sgo_quote_revision WHERE is_current LIMIT 1""")
            baseline = cursor()["cursor"]
            changes = [
                (
                    "UPDATE public.current_contract_storage SET active=false",
                    "UPDATE public.current_contract_storage SET active=true",
                ),
                (
                    "UPDATE public.current_offer_storage SET facts=jsonb_set(facts,'{state}','\"unavailable\"')",
                    "UPDATE public.current_offer_storage SET facts=jsonb_set(facts,'{state}','\"available\"')",
                ),
                (
                    "UPDATE public.sgo_quote_revision SET facts=jsonb_set(facts,'{available}','false') WHERE is_current",
                    "UPDATE public.sgo_quote_revision SET facts=jsonb_set(facts,'{available}','true') WHERE is_current",
                ),
                (
                    "UPDATE public.sgo_line_presence SET expired=true",
                    "UPDATE public.sgo_line_presence SET expired=false",
                ),
                (
                    "UPDATE public.current_event SET facts=jsonb_set(facts,'{status}','{\"started\":true}')",
                    "UPDATE public.current_event SET facts=jsonb_set(facts,'{status}','{}')",
                ),
                (
                    "INSERT INTO pregame_monitor.current_pregame_work(provider,native_event_id,revision,admitted_at) VALUES('sportsgameodds','event',1,now())",
                    "DELETE FROM pregame_monitor.current_pregame_work",
                ),
            ]
            for add, remove in changes:
                with self.subTest(change=add):
                    writer.execute(add)
                    withdrawn = cursor()["cursor"]
                    self.assertNotEqual(withdrawn, baseline)
                    writer.execute(remove)
                    self.assertEqual(cursor()["cursor"], baseline)
            writer.execute("""INSERT INTO data_runtime VALUES(true,'fixture',1,now(),now(),
                'running','{\"direct_kalshi_enabled\":false}','{}',true,'{}',1,'fixture','[]',false)""")
            self.assertNotEqual(cursor()["cursor"], baseline)
            writer.execute("DELETE FROM data_runtime")
            self.assertEqual(cursor()["cursor"], baseline)
            from app.fees import pricing
            from tests.test_fee_pricing import rule

            pricing.write(writer, "novig", [dict(rule("novig"), rate="0.01")])
            self.assertNotEqual(cursor()["cursor"], baseline)

    async def test_earlier_public_kickoff_changes_deadline_and_expires_cohort(self):
        at = stamp(AT)
        with self.connect() as writer:
            self.seed_quoted_cohort(writer)
            before, _ = self.monitor_reads(writer)
            earlier = at + timedelta(minutes=1)
            writer.execute(
                "UPDATE public.current_event SET scheduled_start=%s",
                (earlier.isoformat(),),
            )
            with self.connect() as reader, reader.transaction():
                select(reader, "monitor")
                approaching = board.read(reader, dict(browse="1"), at=at)
            self.assertNotEqual(approaching["cursor"], before["cursor"])
            self.assertEqual(stamp(approaching["refresh_at"]), earlier)
            with self.connect() as reader, reader.transaction():
                select(reader, "monitor")
                expired = board.read(reader, dict(browse="1"), at=earlier)
            self.assertNotEqual(expired["cursor"], approaching["cursor"])
            self.assertEqual(expired["rows"], [])

    async def test_lookahead_window_entry_invalidates_empty_cached_view(self):
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
        from app.collection.sportsgameodds_current_rows import source_bookmaker
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
                SET payload=jsonb_set(jsonb_set(jsonb_set(payload,'{main}','false'::jsonb),
                    '{coherent_probability}','{"probability":"0.99"}'::jsonb),
                    '{alternative_probabilities}','{}'::jsonb)""")

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
            cohort_observations = {}
            for entry in db.execute("SELECT id,revision,event_id,facts FROM pregame_monitor.current_sgo_reference"):
                cohort_observations.setdefault(entry["event_id"], []).append(entry)
            inputs = math.ReferenceInputs(cohort_observations,
                books=math.COHERENT_POLICIES[math.EXPANSION_POLICY])
            original_prices = {r["contract_id"]: r["payload"] for r in rows}
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
                expected["coherent_probability"] = math.coherent_reference(row["record"], inputs, at=stamp(AT))
                expected["alternative_probabilities"] = {
                    math.EXPANSION_POLICY: math.coherent_reference(row["record"], inputs,
                        at=stamp(AT), policy=math.EXPANSION_POLICY,
                        evaluated_book=source_bookmaker(row["record"])),
                }
                self.assertEqual(actual, expected)
                self.assertEqual(actual["fee"], original_prices[actual["id"]]["fee"])
                self.assertEqual(actual["times"], original_prices[actual["id"]]["times"])
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
            self.assertEqual(live["data_type"], "monitor")
            self.assertEqual(live["rows"], monitor["rows"])
            self.assertEqual(live["activity_mode"]["requested_mode"], "live")
            self.assertEqual(live["activity_mode"]["effective_mode"], "monitor")
            historical = json.loads(
                (
                    await response(
                        SimpleNamespace(
                            path="/api/pregame", query={"data_type": "live"}
                        ),
                        connector=self.connect,
                    )
                ).text
            )
            self.assertEqual(historical["data_type"], "live")
            self.assertEqual(historical["rows"], [])
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
