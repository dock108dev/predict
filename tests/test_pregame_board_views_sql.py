"""Game grouping and reference-free two-sided prices on disposable PostgreSQL."""

from copy import deepcopy
from datetime import timedelta
from fractions import Fraction
from unittest import skipUnless
from unittest.mock import patch
from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import AT, page, PregameFixture
from app.storage.store import stamp
from app.storage import current_pregame as board


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class PregameBoardViewsSQL(PregameFixture):
    async def test_games_page_orders_start_time_and_keeps_all_main_lines_before_paging(
        self,
    ):
        data = page()
        original = deepcopy(data["data"][0])
        data["data"] = []
        for index in range(3):
            event = deepcopy(original)
            event["eventID"] += "-game-" + str(index)
            event["status"]["startsAt"] = (
                stamp(original["status"]["startsAt"]) + timedelta(minutes=15 * index)
            ).isoformat()
            for odd in event["odds"].values():
                odd["byBookmaker"]["prophetx"]["odds"] = "+" + str(110 + index * 30)
                for book in odd["byBookmaker"].values():
                    book["altLines"] = [
                        dict(book, spread="-2.5" if odd["sideID"] == "home" else "2.5")
                    ]
            data["data"].append(event)
        with self.connect() as db:
            self.ingest(db, data)
            self.process(db)
            all_games = board.read(
                db, dict(view="games", lines="all", limit="3"), at=stamp(AT)
            )
            self.assertEqual(all_games["total"], 3)
            games = all_games["games"]
            self.assertEqual(
                [r["kickoff"] for r in games], sorted(r["kickoff"] for r in games)
            )
            for game in games:
                self.assertEqual(len(game["rows"]), 2)
                self.assertTrue(all(r["main"] for r in game["rows"]))
            next_page = board.read(
                db, dict(view="games", offset="1", limit="1"), at=stamp(AT)
            )
            self.assertEqual(next_page["games"], [games[1]])
            expanded = board.read(
                db, dict(view="game", game_key=games[0]["game_key"]), at=stamp(AT)
            )
            self.assertEqual(expanded["total"], 4)
            self.assertTrue(any(not r["main"] for r in expanded["rows"]))
            ranked = board.read(db, {}, at=stamp(AT))
            self.assertNotEqual(ranked["rows"][0]["game_key"], games[0]["game_key"])
            with self.assertRaises(ValueError):
                board.read(db, dict(view="game"), at=stamp(AT))

    async def test_fee_qualified_arbs_survive_missing_sportsbook_reference(self):
        from app.fees import pricing
        from tests.test_fee_pricing import rule
        from app.storage.pregame_arbs import read as arb_read

        data = page()
        for odd in data["data"][0]["odds"].values():
            template = dict(odd["byBookmaker"]["prophetx"], odds="+120")
            odd["byBookmaker"] = {"novig": template, "prophetx": deepcopy(template)}
        with self.connect() as db:
            for venue in ("novig", "prophetx"):
                pricing.write(db, venue, [rule(venue)])
            self.ingest(db, data)
            self.process(db)
            self.assertEqual(board.read(db, {}, at=stamp(AT))["total"], 0)
            self.assertEqual(
                db.execute("SELECT count(*) n FROM current_pregame_price").fetchone()[
                    "n"
                ],
                4,
            )
            before = list(
                db.execute("SELECT * FROM current_pregame_price ORDER BY contract_id")
            )
            pairs = arb_read(db, {}, at=stamp(AT))
            self.assertEqual(pairs["total"], 2)
            for pair in pairs["rows"]:
                self.assertEqual(pair["category"], "market_market")
                self.assertGreater(Fraction(pair["minimum_profit_usd"]), 0)
                self.assertLessEqual(Fraction(pair["committed_usd"]), 100)
                self.assertFalse(pair["execution_qualified"])
                self.assertIsNone(pair["instant_fill_max_usd"])
                for leg in pair["legs"]:
                    self.assertNotIn("reference", leg)
                    self.assertNotIn("net_ev", leg["raw"])
            self.assertEqual(
                before,
                list(
                    db.execute(
                        "SELECT * FROM current_pregame_price ORDER BY contract_id"
                    )
                ),
            )
            # A source withdrawal suppresses the price before the owner rebuilds.
            db.execute(
                "UPDATE current_offer_storage SET facts=jsonb_set(facts,'{state}','\"unavailable\"'::jsonb),revision=revision||'-withdrawn'"
            )
            self.assertEqual(arb_read(db, {}, at=stamp(AT))["total"], 0)

    async def test_market_to_book_arbs_use_actual_opposing_price_without_book_ev(self):
        from app.fees import pricing
        from tests.test_fee_pricing import rule
        from app.storage.pregame_arbs import read as arb_read

        data = page()
        for odd in data["data"][0]["odds"].values():
            for name, quote in odd["byBookmaker"].items():
                quote["odds"] = "+125" if name == "fanduel" else "+120"
        with self.connect() as db:
            pricing.write(db, "prophetx", [rule("prophetx")])
            self.ingest(db, data)
            self.process(db)
            pairs = arb_read(db, {"category": "market_book"}, at=stamp(AT))
            self.assertGreater(pairs["total"], 0)
            for pair in pairs["rows"]:
                self.assertEqual(pair["category"], "market_book")
                self.assertEqual(len(pair["legs"]), 2)
                self.assertEqual(len({r["side"] for r in pair["legs"]}), 2)
                book = next(r for r in pair["legs"] if r["venue"] != "prophetx")
                self.assertIn(book["posted"]["value"], ("+125", "+120"))
                self.assertEqual(
                    book["display"]["posted_odds"], book["display"]["after_fees"]
                )
                self.assertNotIn("net_ev", book["raw"])

    async def test_reference_free_fee_deadline_expires_cache_and_recovers_without_ev(
        self,
    ):
        from app.fees import pricing
        from tests.test_fee_pricing import rule
        from app.storage.pregame_arbs import read as arb_read

        at = stamp(AT)
        deadline = at + timedelta(seconds=30)
        data = page()
        for odd in data["data"][0]["odds"].values():
            quote = dict(odd["byBookmaker"]["prophetx"], odds="+120")
            odd["byBookmaker"] = {"novig": quote, "prophetx": deepcopy(quote)}
        with self.connect() as db:
            for venue in ("novig", "prophetx"):
                pricing.write(
                    db, venue, [dict(rule(venue), effective_to=deadline.isoformat())]
                )
            self.ingest(db, data)
            self.process(db)
            first = arb_read(db, {}, at=at)
            self.assertEqual(first["total"], 2)
            self.assertEqual(stamp(first["refresh_at"]), deadline)
            self.assertEqual(arb_read(db, {}, at=at)["rows"], first["rows"])
            # No write or sportsbook EV change occurs while the clock advances.
            expired = arb_read(db, {}, at=deadline)
            self.assertEqual(expired["total"], 0)
            changed = board.read(
                db, {"updates": "1", "after": first["cursor"]}, at=deadline
            )
            self.assertTrue(changed["changed"])
            board.enqueue_due(db, at=deadline)
            self.assertEqual(
                db.execute("SELECT count(*) n FROM current_pregame_work").fetchone()[
                    "n"
                ],
                1,
            )
            with patch("app.storage.current_rows.utc", return_value=AT):
                board.process(db, at=deadline)
            self.assertEqual(
                db.execute("SELECT count(*) n FROM current_pregame_price").fetchone()[
                    "n"
                ],
                0,
            )
            self.assertEqual(
                db.execute("SELECT count(*) n FROM current_pregame_work").fetchone()[
                    "n"
                ],
                0,
            )

    async def test_book_role_attachment_refreshes_fee_price_without_a_new_offer(self):
        from app.fees import pricing
        from tests.test_fee_pricing import rule
        from app.comparison.sgo_reference import OPPOSITE

        with self.connect() as db:
            pricing.write(db, "prophetx", [rule("prophetx")])
            self.ingest(db, page())
            self.process(db)
            before = db.execute(
                "SELECT payload FROM current_pregame_price ORDER BY contract_id LIMIT 1"
            ).fetchone()["payload"]
            source = before["source"]
            job = dict(
                provider=source["provider"], native_event_id=source["native_event_id"]
            )
            events, observations, occurrence = board.affected(db, job, stamp(AT))
            for entries in observations.values():
                for entry in entries:
                    entry["facts"]["canonical_side"] = OPPOSITE[entry["facts"]["side"]]
            db.execute(
                "SELECT pregame_enqueue(%s,%s)",
                (job["provider"], job["native_event_id"]),
            )
            with patch.object(
                board, "affected", return_value=(events, observations, occurrence)
            ):
                self.process(db)
            after = db.execute(
                "SELECT payload FROM current_pregame_price ORDER BY contract_id LIMIT 1"
            ).fetchone()["payload"]
            self.assertNotEqual(before["input_revision"], after["input_revision"])
            self.assertEqual(before["posted"], after["posted"])
            self.assertEqual(before["times"], after["times"])
            self.assertTrue(all(after["sportsbook_sides_reversed"].values()))
