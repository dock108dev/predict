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


def test_ranking_wire_is_canonical_and_preserves_unrounded_digits():
    from decimal import Decimal, localcontext
    from app.storage.pregame_ranking import present

    for zero in ("0.00000000000000000000", Decimal("0E-64"), "-0.000"):
        assert present({}, zero, "growth")["ranking"]["value"] == "0"
    exact = "0.123456789012345678901234567890123456789012345678901"
    with localcontext() as context:
        context.prec = 12
        assert present({}, Decimal(exact), "growth")["ranking"]["value"] == exact


def test_ranking_catalog_owns_presented_metadata_and_rejects_missing_calculation():
    import pytest
    from app.storage import pregame_ranking as ranking

    catalog = ranking.catalog()
    assert catalog["default"] == "growth"
    for method, info in catalog["methods"].items():
        shown = ranking.present({}, None, method)["ranking"]
        assert {key: shown[key] for key in ("label", "column", "unit")} == {
            key: info[key] for key in ("label", "column", "unit")
        }
    # A future metadata entry must not silently run growth's calculation.
    with patch.dict(ranking.METHODS, future=dict(ranking.METHODS["growth"])):
        with pytest.raises(ValueError, match="Unsupported.*calculation"):
            ranking.expression("future")
    with patch.object(ranking, "DEFAULT", "unsupported"):
        with pytest.raises(ValueError, match="Unknown opportunity ranking"):
            ranking.catalog()


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class PregameBoardViewsSQL(PregameFixture):
    async def test_authored_cashflows_rank_longshot_above_larger_kelly_fraction(self):
        """Fixed wealth factors, independent of the valuation packet/oracle below."""
        import json
        from decimal import Decimal
        from app.storage.pregame_ranking import expression

        # +500 at p=1/3: optimal f=1/5, wealth factors 2 and 4/5.
        # +100 at p=13/20: optimal f=3/10, factors 13/10 and 7/10.
        # Growth = log of their probability-weighted geometric means.
        def payload(p, score, receipt, ev):
            return json.dumps(
                dict(
                    reference=dict(probability=p),
                    raw=dict(opportunity_score=score, net_ev=ev),
                    fee=dict(
                        committed_usd="100",
                        cashflows=dict(
                            win=dict(net_receipt_usd=receipt),
                            loss=dict(net_receipt_usd="0"),
                        ),
                    ),
                )
            )

        rows = [
            ("longshot", payload("1/3", "2000", "600", "1")),
            ("even", payload("13/20", "3000", "200", "3/10")),
        ]
        with self.connect() as db:

            def ranked(method):
                return list(
                    db.execute(
                        "SELECT name," + expression(method) + " AS value FROM "
                        "(VALUES (%s,%s::jsonb),(%s,%s::jsonb)) AS q(name,payload) "
                        "ORDER BY value DESC NULLS LAST,name",
                        (*rows[0], *rows[1]),
                    )
                )

            growth = ranked("growth")
            self.assertEqual([r["name"] for r in growth], ["longshot", "even"])
            self.assertLess(
                abs(growth[0]["value"] - Decimal("822.866926438419326282")),
                Decimal("1e-12"),
            )
            self.assertLess(
                abs(growth[1]["value"] - Decimal("457.005415253128512036")),
                Decimal("1e-12"),
            )
            self.assertEqual([r["name"] for r in ranked("score")], ["even", "longshot"])
            self.assertEqual([r["value"] for r in ranked("ev")], [100, 30])
            self.assertLess(
                abs(ranked("edge")[0]["value"] - Decimal("16.666666666666666667")),
                Decimal("1e-12"),
            )
            self.assertLess(
                abs(
                    ranked("balanced")[0]["value"] - Decimal("4472.135954999579392818")
                ),
                Decimal("1e-12"),
            )
            # A certain win permits full allocation despite zero losing wealth;
            # any positive chance of ruin must remain undefined, never an error.
            for p, expected in (("1", "6931.471805599453094172"), ("1/2", None)):
                value = db.execute(
                    "SELECT "
                    + expression("growth")
                    + " AS value FROM (SELECT %s::jsonb AS payload) q",
                    (payload(p, "10000", "200", "1"),),
                ).fetchone()["value"]
                if expected is None:
                    self.assertIsNone(value)
                else:
                    self.assertLess(abs(value - Decimal(expected)), Decimal("1e-12"))

    async def test_growth_default_and_all_rankings_precede_pagination(self):
        from decimal import Decimal, localcontext
        from app.storage.pregame_ranking import METHODS

        data = page()
        original = deepcopy(data["data"][0])
        data["data"] = []
        for index, offered in enumerate(("+108", "+525", "+116")):
            event = deepcopy(original)
            event["eventID"] += "-rank-" + str(index)
            event["status"]["startsAt"] = (
                stamp(original["status"]["startsAt"]) + timedelta(minutes=15 * index)
            ).isoformat()
            for odd in event["odds"].values():
                home = odd["sideID"] == "home"
                odd["byBookmaker"]["prophetx"]["odds"] = offered if home else "-2000"
                for book, pair in {
                    "fanduel": ("+450", "-600"),
                    "draftkings": ("+400", "-550"),
                }.items():
                    odd["byBookmaker"][book]["odds"] = (
                        pair[not home] if index == 1 else "-110"
                    )
            data["data"].append(event)
        with self.connect() as db:
            self.ingest(db, data)
            self.process(db)
            before = list(
                db.execute(
                    "SELECT * FROM current_pregame_calculation ORDER BY contract_id"
                )
            )
            all_rows = board.read(db, dict(limit="100"), at=stamp(AT))
            self.assertEqual(all_rows["sort"], "growth")
            self.assertEqual(all_rows["total"], 3)

            def number(value):
                value = Fraction(value)
                return Decimal(value.numerator) / Decimal(value.denominator)

            def value(row, selected):
                p = number(row["reference"]["probability"])
                ev = number(row["raw"]["net_ev"])
                f = number(row["raw"]["opportunity_score"]) / 10000
                cash = row["fee"]["cashflows"]
                committed = number(row["fee"]["committed_usd"])
                win = number(cash["win"]["net_receipt_usd"]) / committed - 1
                loss = number(cash["loss"]["net_receipt_usd"]) / committed - 1
                if selected == "growth":
                    return 10000 * (
                        p * (1 + f * win).ln() + (1 - p) * (1 + f * loss).ln()
                    )
                return {
                    "score": f * 10000,
                    "ev": ev * 100,
                    "balanced": ev / win.sqrt() * 10000,
                    "edge": (p + loss / (win - loss)) * 100,
                }[selected]

            with localcontext() as context:
                context.prec = 50
                for selected in METHODS:
                    expected = sorted(
                        all_rows["rows"],
                        key=lambda r: (
                            -value(r, selected),
                            -number(r["raw"]["net_ev"]),
                            r["bet_id"],
                        ),
                    )
                    actual = []
                    for offset in range(3):
                        packet = board.read(
                            db,
                            dict(sort=selected, limit="1", offset=str(offset)),
                            at=stamp(AT),
                        )
                        (row,) = packet["rows"]
                        actual.append(row["id"])
                        self.assertEqual(row["ranking"]["method"], selected)
                        self.assertLess(
                            abs(
                                Decimal(row["ranking"]["value"]) - value(row, selected)
                            ),
                            Decimal("1e-9"),
                        )
                    self.assertEqual(actual, [r["id"] for r in expected])
            legacy = board.read(db, dict(sort="score"), at=stamp(AT))["rows"]
            self.assertNotEqual(
                [r["id"] for r in legacy], [r["id"] for r in all_rows["rows"]]
            )
            with self.assertRaises(ValueError):
                board.read(db, dict(sort="unknown; DROP TABLE"), at=stamp(AT))
            self.assertEqual(
                before,
                list(
                    db.execute(
                        "SELECT * FROM current_pregame_calculation ORDER BY contract_id"
                    )
                ),
            )

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

    async def test_browse_and_exact_comparison_keep_authentic_prices_without_ev(self):
        from app.fees import pricing
        from tests.test_fee_pricing import rule

        data = page()
        for odd in data["data"][0]["odds"].values():
            quote = dict(odd["byBookmaker"]["prophetx"], odds="+120")
            odd["byBookmaker"] = {"novig": quote, "prophetx": deepcopy(quote)}
        at = stamp(AT)
        with self.connect() as db:
            for venue in ("novig", "prophetx"):
                pricing.write(db, venue, [rule(venue)])
            self.ingest(db, data)
            self.process(db)
            before = list(
                db.execute("SELECT * FROM current_pregame_price ORDER BY contract_id")
            )
            browse = board.read(db, {"browse": "1"}, at=at)
            self.assertGreater(browse["total"], 0)
            row = browse["rows"][0]
            self.assertEqual(
                row["ev_unavailable_reason"], "reference_exact_pair_unavailable"
            )
            self.assertIsNone(row["reference"])
            self.assertIsNone(row["raw"]["net_ev"])
            self.assertIsNone(row["display"]["net_ev"])
            self.assertIsNone(row["ranking"]["value"])
            self.assertEqual(board.read(db, {}, at=at)["total"], 0)
            exact = board.read(db, {"bet_id": row["bet_id"], "browse": "1"}, at=at)
            self.assertEqual({r["venue"] for r in exact["rows"]}, {"novig", "prophetx"})
            self.assertEqual(exact["sportsbooks"], [])
            again = board.read(
                db,
                {"bet_id": row["bet_id"], "browse": "1"},
                at=at + timedelta(seconds=2),
            )
            self.assertEqual(
                [r["times"] for r in exact["rows"]], [r["times"] for r in again["rows"]]
            )
            self.assertEqual(
                before,
                list(
                    db.execute(
                        "SELECT * FROM current_pregame_price ORDER BY contract_id"
                    )
                ),
            )
            # Attach exact source revisions as the ordinary aggregate ingress
            # does; this fixture's generic upsert otherwise stores inline prices.
            db.execute("""UPDATE current_offer_storage o SET price_value=NULL,
                sgo_quote_id=q.id,sgo_quote_revision=q.revision,
                facts=o.facts#-'{original,value}'
                FROM sgo_quote_revision q,current_contract c
                WHERE c.id=o.contract_id AND q.is_current AND q.bookmaker_id=c.venue
                  AND q.facts->>'odd_id'=c.native_outcome_id
                  AND q.facts->>'line'=o.facts#>>'{source,native_line}'""")
            linked = db.execute(
                "SELECT count(*) n FROM current_offer_storage WHERE sgo_quote_id IS NOT NULL"
            ).fetchone()["n"]
            self.assertEqual(linked, 4)
            db.execute("""INSERT INTO sgo_line_presence
                (quote_id,event_id,bookmaker_id,odd_id,last_seen,scope_received,expired)
                SELECT id,event_id,bookmaker_id,facts->>'odd_id',received_order,received_order,true
                FROM sgo_quote_revision WHERE is_current""")
            # Same line-omission authority as the original current_offer view.
            self.assertEqual(board.read(db, {"browse": "1"}, at=at)["total"], 0)

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
