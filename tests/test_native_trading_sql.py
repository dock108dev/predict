"""Native offers never mutate acquired source quotes or frozen paper evidence."""

from copy import deepcopy
from datetime import timedelta
from unittest import skipUnless

from psycopg.types.json import Jsonb

from app.collection.native_trading_identity import native_event, record, expected
from app.storage import native_trading
from app.storage.store import stamp
from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import AT, PregameFixture, page
from tests.test_liquidity_execution import admitted


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class NativeTradingSQL(PregameFixture):
    async def test_storage_pressure_rotates_only_aged_superseded_evidence(self):
        at = stamp(AT)
        with self.connect() as db:
            db.execute(
                """INSERT INTO public.native_trading_snapshot
                (id,offer_id,created_at,payload_bytes,payload) VALUES
                ('expired','old',%s,%s,'{}'),('recent','current',%s,1024,'{}')""",
                (at - timedelta(minutes=3), native_trading.SNAPSHOT_BUDGET, at),
            )
            report = native_trading.publish(db, {"fixture": {}}, at=at)
            self.assertEqual(report["state"], "ready")
            self.assertEqual(
                db.execute("SELECT id FROM public.native_trading_snapshot").fetchall(),
                [{"id": "recent"}],
            )

    async def asyncSetUp(self):
        await super().asyncSetUp()
        with self.connect() as db:
            db.execute(
                "TRUNCATE native_trading_offer,native_trading_snapshot,native_trading_sgo_game"
            )

    async def test_sgo_anchor_keeps_first_valid_identity_and_separates_independent_events(
        self,
    ):
        at = stamp(AT)
        with self.connect() as db:
            self.ingest(db, page())

            def legacy(pull, event, state, game):
                db.execute(
                    """INSERT INTO market_pull(pull_id,requested_at,request_scope,state)
                    VALUES(%s,%s,'{}',%s)""",
                    (pull, at, state),
                )
                db.execute(
                    """INSERT INTO market_pull_scope(pull_id,event_id,family,state,coverage,snapshot)
                    VALUES(%s,%s,'spread',%s,'{}',%s)""",
                    (pull, event, state, Jsonb(dict(canonical_game_id=game))),
                )

            legacy("cancelled", "event", "cancelled", "canonical:discarded")
            legacy("original", "event", "complete", "canonical:original")
            legacy("rescheduled", "event", "complete", "canonical:new-clock")
            (first,) = native_trading.anchors(db, at)
            self.assertEqual(first["canonical_game_id"], "canonical:original")
            db.execute("""INSERT INTO native_trading_sgo_game(sgo_event_id,canonical_game_id)
                VALUES('event','canonical:original')""")
            same_teams = page()
            same_teams["data"][0]["eventID"] = "another-game"
            self.ingest(db, same_teams)
            legacy("legacy-collision", "another-game", "complete", "canonical:original")
            result = {
                r["event"]["id"]: r["canonical_game_id"]
                for r in native_trading.anchors(db, at)
            }
            self.assertEqual(
                result,
                {
                    "event": "canonical:original",
                    "another-game": "source:sportsgameodds:another-game",
                },
            )
            db.execute("""UPDATE public.current_event SET facts=jsonb_set(facts,'{status}','{"cancelled":true}')
                WHERE provider='sportsgameodds' AND native_event_id='event'""")
            self.assertEqual(
                [r["event"]["id"] for r in native_trading.anchors(db, at)],
                ["another-game"],
            )

    async def test_native_alternate_publication_is_idempotent_and_evidence_is_passive(
        self,
    ):
        at = stamp(AT)
        with self.connect() as db:
            self.ingest(db, page())
            source = db.execute(
                "SELECT facts FROM current_event WHERE provider='sportsgameodds' LIMIT 1"
            ).fetchone()["facts"]
            event = native_event(
                "novig",
                "native-fixture-event",
                source["competition"],
                source["scheduled_start"],
                {side: source[side] for side in ("home", "away")},
                {
                    side: next(
                        name
                        for name, cid in source["participants"].items()
                        if cid == source[side]
                    )
                    for side in ("home", "away")
                },
                proof={"fixture": "both-source-roles"},
            )
            row = record(
                "novig",
                event,
                "native-fixture-market",
                "native-fixture-outcome",
                "buy",
                "spread",
                "home",
                "-1.5",
                settlement={},
                main=False,
            )
            book = admitted((".25", 200000), league=source["competition"], line="-1.5")
            book.update(
                event_id=event["id"],
                market_id="native-fixture-market",
                outcome_id="native-fixture-outcome",
                native_side="buy",
                opposite_outcome_id="native-fixture-opposite",
                source_at=(at - timedelta(seconds=2)).isoformat(),
                received_at=at.isoformat(),
                valid_until=(at + timedelta(seconds=20)).isoformat(),
                _record=row,
                sequence=10,
            )
            book["contract"] = dict(book["contract"], **expected(row))
            before = db.execute(
                "SELECT id,revision FROM public.sgo_quote_revision ORDER BY id,revision"
            ).fetchall()
            self.assertEqual(
                native_trading.publish(db, {"one": book}, at=at)["published"], 1
            )
            self.assertEqual(
                db.execute(
                    "SELECT sgo_event_id,canonical_game_id FROM native_trading_sgo_game"
                ).fetchone(),
                dict(
                    sgo_event_id=source["id"],
                    canonical_game_id="source:sportsgameodds:" + source["id"],
                ),
            )
            self.assertEqual(
                native_trading.publish(db, {"one": deepcopy(book)}, at=at)["published"],
                0,
            )
            self.assertEqual(
                db.execute("SELECT count(*) n FROM native_trading_snapshot").fetchone()[
                    "n"
                ],
                1,
            )
            observed = db.execute("SELECT * FROM native_trading_offer").fetchone()
            changed = dict(
                book,
                sequence=9,
                source_at=(at - timedelta(seconds=3)).isoformat(),
                received_at=(at + timedelta(seconds=1)).isoformat(),
            )
            native_trading.publish(db, {"older": changed}, at=at + timedelta(seconds=1))
            current = db.execute("SELECT * FROM native_trading_offer").fetchone()
            self.assertEqual(current["book"], observed["book"])
            self.assertEqual(current["book_valid_until"], observed["book_valid_until"])
            with db.transaction():
                db.execute("SET TRANSACTION READ ONLY")
                board = native_trading.dashboard(
                    db, at=at, until=at + timedelta(hours=24), view="all"
                )
                (shown,) = board["rows"]
                self.assertEqual(shown["posted"]["value"], "0.0025")
                self.assertEqual(shown["native_source"]["provider"], "novig")
                query = {
                    key: shown[key] for key in ("market_id", "pull_id", "revision")
                }
                query["offer_id"] = shown["id"]
                detail = native_trading.detail(
                    db, dict(query, amount="25"), at=at, stake="25"
                )
                self.assertEqual(detail["liquidity"]["intended_stake_usd"], "25")
                self.assertEqual(
                    detail["native_offer"]["row"]["revision"], shown["revision"]
                )
                self.assertEqual(
                    detail["liquidity_evidence"]["outcome_id"], "native-fixture-outcome"
                )
                census = native_trading.coverage(db, at=at)
                self.assertEqual(census["total"], 1)
                self.assertEqual(census["coverage"][0]["unique_books"], 1)
                exported = native_trading.detail(db, query, at=at, frozen=True)

            later = at + timedelta(seconds=2)
            refreshed = dict(
                book,
                levels=[dict(price=".30", quantity="200000")],
                sequence=11,
                source_at=later.isoformat(),
                received_at=later.isoformat(),
            )
            self.assertEqual(
                native_trading.publish(db, {"newer": refreshed}, at=later)["published"],
                1,
            )
            updated = native_trading.detail(
                db, dict(query, amount="25"), at=later, stake="25"
            )
            self.assertEqual(updated["native_offer"]["book"]["sequence"], 10)
            self.assertEqual(updated["liquidity_evidence"]["sequence"], 11)
            self.assertEqual(
                updated["preview_offer"]["posted"]["native_price_probability"], "0.3"
            )
            self.assertEqual(updated["liquidity"]["best_level_purchase_usd"], "600")
            self.assertNotEqual(updated["preview_offer"]["revision"], query["revision"])
            self.assertEqual(
                native_trading.detail(db, query, at=later, frozen=True), exported
            )

            later += timedelta(seconds=1)
            changed_rules = deepcopy(refreshed)
            changed_rules.update(
                sequence=12, source_at=later.isoformat(), received_at=later.isoformat()
            )
            changed_rules["contract"]["settlement"]["rule_id"] = "changed-fixture-rule"
            self.assertEqual(
                native_trading.publish(db, {"changed_rules": changed_rules}, at=later)[
                    "published"
                ],
                1,
            )
            rejected = native_trading.detail(
                db, dict(query, amount="25"), at=later, stake="25"
            )
            self.assertEqual(rejected["liquidity"]["reason"], "native_identity_changed")
            self.assertIsNone(rejected["liquidity_evidence"])
            (now_shown,) = native_trading.dashboard(
                db, at=later, until=later + timedelta(hours=24), view="all"
            )["rows"]
            current_query = dict(
                query, revision=now_shown["revision"], pull_id=now_shown["pull_id"]
            )
            db.execute(
                """UPDATE public.current_event SET facts=jsonb_set(facts,'{status}','{"live":true}')
                WHERE provider='sportsgameodds' AND native_event_id=%s""",
                (exported["native_offer"]["game_link"]["sgo_event_id"],),
            )
            closed = native_trading.detail(
                db, dict(current_query, amount="25"), at=later, stake="25"
            )
            self.assertEqual(closed["liquidity"]["reason"], "native_game_started")
            self.assertNotIn("preview_offer", closed)
            later += timedelta(seconds=1)
            still_open_at_venue = dict(
                changed_rules,
                sequence=13,
                source_at=later.isoformat(),
                received_at=later.isoformat(),
            )
            self.assertEqual(
                native_trading.publish(
                    db, {"delayed_venue": still_open_at_venue}, at=later
                )["published"],
                1,
            )
            self.assertEqual(
                db.execute(
                    "SELECT game_link->>'sgo_event_id' AS event FROM native_trading_offer"
                ).fetchone()["event"],
                source["id"],
            )
            self.assertEqual(
                native_trading.dashboard(
                    db, at=later, until=later + timedelta(hours=24), view="all"
                )["rows"],
                [],
            )
            self.assertEqual(
                native_trading.detail(db, query, at=later, frozen=True), exported
            )
            self.assertEqual(
                before,
                db.execute(
                    "SELECT id,revision FROM public.sgo_quote_revision ORDER BY id,revision"
                ).fetchall(),
            )
