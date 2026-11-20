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


def test_late_financial_inputs_require_the_same_complete_price_witness():
    from copy import deepcopy
    from types import SimpleNamespace
    import pytest
    from app.storage.pregame_arbs import hydrate_prices

    original = dict(
        contract_id="one",
        game_key="game",
        valid_until=stamp(AT),
        payload=dict(id="one"),
    )
    for replacement in (
        [],
        [dict(original, payload=dict(id="changed"))],
        [dict(original, valid_until=stamp(AT) + timedelta(seconds=1))],
        [dict(original, game_key="different-game")],
    ):
        row = deepcopy(original)
        db = SimpleNamespace(execute=lambda *args: replacement)
        with pytest.raises(TimeoutError, match="arbitrage_source_changed"):
            hydrate_prices(db, [row])
        assert "record" not in row and "fee_input" not in row


def test_late_hydration_keeps_newer_negative_native_alias_before_profit_bound():
    from types import SimpleNamespace
    from tests.test_pregame_arbs import entry
    from app.storage import pregame_arbs as arbs

    def native(cid, decimal, seconds):
        payload = entry("novig", "home", decimal)["payload"]
        payload.update(
            id=cid,
            input_revision=cid,
            source=dict(provider="sportsgameodds"),
            times=dict(
                source_at=(stamp(AT) + timedelta(seconds=seconds)).isoformat(),
                received_at=(stamp(AT) + timedelta(seconds=seconds)).isoformat(),
            ),
            sportsbook_event_ids=["event"],
        )
        return dict(
            contract_id=cid,
            game_key="game",
            valid_until=stamp(AT) + timedelta(hours=1),
            payload=payload,
        )

    older, newer = native("older", "3", -2), native("newer", "4/3", -1)
    book = entry("fanduel", "away", "2.1")
    book["payload"]["times"] = dict(source_at=AT, received_at=AT)
    fetched = []

    def execute(query, params=None):
        if query.startswith("SELECT p.contract_id,p.game_key,p.valid_until,p.payload"):
            return deepcopy([older, newer])
        if query.startswith(
            "SELECT contract_id,game_key,valid_until,payload,record,fee_input"
        ):
            fetched.extend(params[0])
            return [
                dict(
                    deepcopy(newer), record=dict(witness="newer negative"), fee_input={}
                )
            ]
        return []

    def reference_key(record):
        assert record["witness"] == "newer negative"
        return "spread", "home", Fraction("-1.5")

    db = SimpleNamespace(
        info=SimpleNamespace(host="alias-fixture", port=0, dbname="alias"),
        execute=execute,
    )
    arbs._CACHE.clear()
    arbs._SCAN_CACHE.clear()
    with (
        patch.object(
            arbs,
            "pregame_read",
            return_value=dict(cursor="native-alias", refresh_at=None),
        ),
        patch.object(
            arbs, "configured_routes", return_value=dict(novig="sportsgameodds")
        ),
        patch.object(arbs, "reference_key", side_effect=reference_key),
        patch.object(
            arbs,
            "read_book_quotes",
            return_value=[
                dict(
                    event_id="event",
                    market="spread",
                    line="1.5",
                    side="away",
                    available=True,
                    venue="fanduel",
                    _arb_groups=["same"],
                )
            ],
        ),
        patch.object(arbs, "book_entry", return_value=book),
        patch.object(
            arbs.math,
            "evaluate",
            side_effect=AssertionError("newest price cannot pass pre-fee test"),
        ),
    ):
        packet = arbs.read(db, {}, at=stamp(AT))
    assert packet["rows"] == [] and packet["evaluated_pairs"] == 1
    assert fetched == ["newer"]


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
    assert catalog["default"] == "edge"
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
    async def test_indexed_negative_authority_preserves_unknown_and_typed_flags(self):
        from psycopg.types.json import Jsonb
        from app.storage.pregame_known_withdrawals import reference_known_unavailable

        with self.connect() as db:
            self.ingest(db, page())
            quote = db.execute(
                "SELECT id,event_id,bookmaker_id,facts FROM sgo_quote_revision WHERE is_current LIMIT 1"
            ).fetchone()
            original = {
                k: v
                for k, v in quote["facts"].items()
                if k not in ("available", "provider_available")
            }
            predicate = (
                "SELECT " + reference_known_unavailable("%s") + " AS unavailable"
            )
            for flags, unavailable in [
                ({}, False),
                (dict(available=None), False),
                (dict(available="false"), False),
                (dict(available=True, provider_available="false"), False),
                (dict(available=True, provider_available=False), True),
                (dict(available=False, provider_available=None), True),
                (dict(available=False), True),
            ]:
                with self.subTest(flags=flags):
                    db.execute(
                        "UPDATE sgo_quote_revision SET facts=%s WHERE id=%s AND is_current",
                        (Jsonb(dict(original, **flags)), quote["id"]),
                    )
                    self.assertEqual(
                        db.execute(predicate, (quote["id"], quote["id"])).fetchone()[
                            "unavailable"
                        ],
                        unavailable,
                    )
            db.execute(
                "UPDATE sgo_quote_revision SET is_current=false WHERE id=%s",
                (quote["id"],),
            )
            self.assertFalse(
                db.execute(predicate, (quote["id"], quote["id"])).fetchone()[
                    "unavailable"
                ]
            )
            db.execute(
                """INSERT INTO sgo_line_presence(quote_id,event_id,bookmaker_id,odd_id,last_seen,scope_received,expired)
                VALUES(%s,%s,%s,%s,0,0,true)""",
                (
                    quote["id"],
                    quote["event_id"],
                    quote["bookmaker_id"],
                    quote["facts"]["odd_id"],
                ),
            )
            self.assertTrue(
                db.execute(predicate, (quote["id"], quote["id"])).fetchone()[
                    "unavailable"
                ]
            )
            db.execute(
                "UPDATE sgo_line_presence SET expired=false WHERE quote_id=%s",
                (quote["id"],),
            )
            self.assertFalse(
                db.execute(predicate, (quote["id"], quote["id"])).fetchone()[
                    "unavailable"
                ]
            )
            self.assertFalse(
                db.execute(predicate, ("never-observed", "never-observed")).fetchone()[
                    "unavailable"
                ]
            )

    async def test_negative_authority_predicates_match_partial_indexes(self):
        with self.connect() as db, db.transaction():
            self.ingest(db, page())
            # Tiny fixtures normally favor sequential scans. This proves index
            # eligibility, not a latency target or a production planner setting.
            db.execute("SET LOCAL enable_seqscan=off")

            def indexes(query):
                plan = db.execute(
                    "EXPLAIN (FORMAT JSON) " + query, ("fixture-id",)
                ).fetchone()["QUERY PLAN"][0]["Plan"]
                found = []

                def visit(node):
                    if node.get("Index Name"):
                        found.append(node["Index Name"])
                    for child in node.get("Plans", []):
                        visit(child)

                visit(plan)
                return found

            names = indexes("""SELECT id FROM public.sgo_quote_revision WHERE id=%s AND is_current
                AND (facts->'available'='false'::jsonb OR facts->'provider_available'='false'::jsonb)""")
            self.assertIn("sgo_quote_known_unavailable", names)
            self.assertIn(
                "sgo_line_known_expired",
                indexes(
                    "SELECT quote_id FROM public.sgo_line_presence WHERE quote_id=%s AND expired"
                ),
            )
            for schema in ("pregame_monitor", "pregame_live", "pregame_combined"):
                self.assertIn(
                    schema + "_line_expired",
                    indexes(
                        "SELECT quote_id FROM "
                        + schema
                        + ".sgo_line_presence WHERE quote_id=%s AND expired"
                    ),
                )
            names = indexes(
                "SELECT contract_id FROM public.current_offer_storage WHERE contract_id=%s AND facts->>'state'='unavailable'"
            )
            definitions = [
                db.execute(
                    "SELECT pg_get_indexdef(%s::regclass) definition", (name,)
                ).fetchone()["definition"]
                for name in names
            ]
            self.assertTrue(
                any("unavailable" in definition for definition in definitions)
            )

    async def test_completed_arb_scan_reuses_exact_filtered_pairs_and_counts(self):
        from app.storage import pregame_arbs as arbs
        from app.fees import pricing
        from tests.test_fee_pricing import rule

        data = page()
        for odd in data["data"][0]["odds"].values():
            odd["byBookmaker"]["novig"] = deepcopy(odd["byBookmaker"]["prophetx"])
        filters = [
            dict(sort="newest"),
            dict(sort="oldest"),
            dict(sort="start"),
            dict(league="NBA"),
            dict(league="NHL"),
            dict(family="spread"),
            dict(family="total"),
            dict(venue="novig"),
            dict(category="market_market"),
            dict(category="market_book"),
            dict(book="fanduel"),
            dict(book="draftkings"),
            dict(league="NBA", family="spread", book="fanduel", limit="1", offset="1"),
        ]

        def clear_views():
            arbs._CACHE.clear()
            arbs._SCAN_CACHE.clear()

        original = arbs.math.evaluate

        def one_unmodelled_pair(left, right, *, at):
            venues = {left["payload"]["venue"], right["payload"]["venue"]}
            if venues == {"novig", "fanduel"}:
                raise ValueError("fixture_pair_not_modelled")
            return original(left, right, at=at)

        with (
            self.connect() as db,
            patch.object(arbs.math, "evaluate", side_effect=one_unmodelled_pair),
        ):
            for venue in ("novig", "prophetx"):
                pricing.write(db, venue, [rule(venue)])
            self.ingest(db, data)
            self.process(db)
            arbs._PAIR_CACHE.clear()
            clear_views()
            arbs.read(db, dict(league="NBA"), at=stamp(AT))
            self.assertFalse(arbs._SCAN_CACHE)  # narrow first never seeds a wider scan
            expected = []
            for query in filters:
                clear_views()
                expected.append(arbs.read(db, query, at=stamp(AT)))
            clear_views()
            full = arbs.read(db, {}, at=stamp(AT))
            self.assertTrue(full["rows"])
            self.assertGreater(full["excluded_pairs"], 0)
            with patch.object(
                arbs,
                "read_book_quotes",
                side_effect=AssertionError("completed scan must be reused"),
            ):
                for query, packet in zip(filters, expected):
                    with self.subTest(query=query):
                        self.assertEqual(arbs.read(db, query, at=stamp(AT)), packet)

    async def test_paired_amount_research_uses_both_owners_without_writes(self):
        from app.storage import pregame_arbs as arbs
        from app.storage.pregame_research import research
        from app.dashboard.bet_journal import Journal

        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            arbs._CACHE.clear()
            arbs._SCAN_CACHE.clear()
            pairs = arbs.read(db, {}, at=stamp(AT))["rows"]
            self.assertTrue(pairs)
            pair = pairs[0]
            before = list(
                db.execute("SELECT * FROM current_pregame_price ORDER BY contract_id")
            )
            with db.transaction():
                db.execute("SET TRANSACTION READ ONLY")
                with patch.object(
                    Journal,
                    "observe",
                    side_effect=AssertionError("research wrote journal"),
                ):
                    for amount in ("25", "100", "500", "25.13"):
                        result = research(
                            db,
                            dict(kind="arb", snapshot=pair, amount=amount),
                            at=stamp(AT),
                        )["result"]
                        self.assertLessEqual(
                            Fraction(result["committed_usd"]), Fraction(amount)
                        )
                        self.assertEqual(result["basis_usd"], amount)
                        self.assertEqual(len(result["legs"]), 2)
                        for leg in result["legs"]:
                            self.assertNotIn("reference", leg)
                            self.assertEqual(leg["available_size"]["status"], "unknown")
                        self.assertEqual(
                            Fraction(result["minimum_profit_usd"]),
                            min(map(Fraction, result["profits_usd"])),
                        )
            self.assertEqual(
                before,
                list(
                    db.execute(
                        "SELECT * FROM current_pregame_price ORDER BY contract_id"
                    )
                ),
            )

    async def test_arb_filter_reuse_preserves_scope_age_cohort_and_withdrawals(self):
        from app.storage import pregame_arbs as arbs
        from app.storage.pregame_cohorts import select

        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            arbs._CACHE.clear()
            arbs._SCAN_CACHE.clear()
            with db.transaction():
                select(db, "monitor")
                full = arbs.read(db, {}, at=stamp(AT))
                self.assertTrue(full["rows"])
                self.assertEqual(
                    arbs.read(
                        db, dict(_scope_seconds="1800", sort="start"), at=stamp(AT)
                    )["rows"],
                    [],
                )
                self.assertEqual(
                    arbs.read(
                        db,
                        dict(search="unmatched fixture", sort="newest"),
                        at=stamp(AT),
                    )["rows"],
                    [],
                )
                aged = arbs.read(db, dict(max_age_minutes="2"), at=stamp(AT))
                self.assertTrue(aged["rows"])
                projected = arbs.read(
                    db, dict(max_age_minutes="2", sort="oldest"), at=stamp(AT)
                )
                self.assertEqual(projected["total"], aged["total"])
                expired = arbs.read(
                    db,
                    dict(max_age_minutes="2", sort="start"),
                    at=stamp(aged["refresh_at"]) + timedelta(microseconds=1),
                )
                self.assertEqual(expired["rows"], [])
            with db.transaction():
                select(db, "live")
                self.assertEqual(
                    arbs.read(db, dict(sort="newest"), at=stamp(AT))["rows"], []
                )
            db.execute("""UPDATE public.current_offer_storage SET
                facts=jsonb_set(facts,'{state}','"unavailable"'),revision=revision||'-withdrawn'""")
            with db.transaction():
                select(db, "monitor")
                withdrawn = arbs.read(db, dict(sort="newest"), at=stamp(AT))
                self.assertNotEqual(withdrawn["cursor"], full["cursor"])
                self.assertEqual(withdrawn["rows"], [])

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

    async def test_edge_default_and_all_rankings_precede_pagination(self):
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
            self.assertEqual(all_rows["sort"], "edge")
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
            growth = board.read(db, dict(sort="growth"), at=stamp(AT))["rows"]
            self.assertNotEqual([r["id"] for r in legacy], [r["id"] for r in growth])
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

    async def test_profit_bound_keeps_latest_and_tied_cross_event_aliases(self):
        from app.fees import pricing
        from tests.test_fee_pricing import rule
        from app.storage.pregame_arbs import read as arb_read
        from psycopg.types.json import Jsonb

        data = page()
        for odd in data["data"][0]["odds"].values():
            odd["byBookmaker"] = {
                "prophetx": dict(odd["byBookmaker"]["prophetx"], odds="+150"),
                "fanduel": dict(odd["byBookmaker"]["fanduel"], odds="+200"),
            }
        with self.connect() as db:
            pricing.write(db, "prophetx", [rule("prophetx")])
            self.ingest(db, data)
            self.process(db)
            self.assertGreater(arb_read(db, {}, at=stamp(AT))["total"], 0)
            db.execute("""UPDATE current_pregame_price SET payload=jsonb_set(
                payload,'{sportsbook_event_ids}','["event","alias"]')""")
            # Newer unprofitable evidence wins over an older attractive alias.
            db.execute(
                """INSERT INTO sgo_quote_revision
                (id,event_id,bookmaker_id,source_order,received_order,expires_at,revision,facts,is_current)
                SELECT id||'-alias','alias',bookmaker_id,source_order,received_order,expires_at,revision,
                  facts||%s,true FROM sgo_quote_revision
                WHERE is_current AND bookmaker_id='fanduel'""",
                (
                    Jsonb(
                        dict(
                            event_id="alias",
                            price_american="-200",
                            source_at="2026-11-17T19:59:30Z",
                        )
                    ),
                ),
            )
            self.process(db)
            self.assertEqual(arb_read(db, {}, at=stamp(AT))["total"], 0)
            original = db.execute(
                "SELECT facts->>'source_at' AS original_clock FROM sgo_quote_revision WHERE event_id='event' AND bookmaker_id='fanduel' LIMIT 1"
            ).fetchone()["original_clock"]
            # Equal-clock conflicts stay ambiguous even when one price is good.
            db.execute(
                "UPDATE sgo_quote_revision SET facts=jsonb_set(facts,'{source_at}',%s) WHERE event_id='alias'",
                (Jsonb(original),),
            )
            self.process(db)
            self.assertEqual(arb_read(db, {}, at=stamp(AT))["total"], 0)
            db.execute("DELETE FROM sgo_quote_revision WHERE event_id='alias'")
            self.process(db)
            self.assertGreater(arb_read(db, {}, at=stamp(AT))["total"], 0)

    async def test_book_quote_fetch_filters_exact_numeric_lines_before_json_decode(
        self,
    ):
        from app.storage.pregame_arbs import read_book_quotes
        from psycopg.types.json import Jsonb

        def request(family="spread", numerator=3, denominator=2):
            return [
                dict(
                    event_id="event",
                    family=family,
                    numerator=numerator,
                    denominator=denominator,
                )
            ]

        with self.connect() as db:
            self.ingest(db, page())
            # Same exact 1.5-point line in source-supported representations.
            for home, away in (
                ("-3/2", "3/2"),
                ("-1.5E+0", "1.5E+0"),
                ("-15/1_0", "15/1_0"),
            ):
                db.execute(
                    """UPDATE sgo_quote_revision SET facts=jsonb_set(facts,'{line}',
                    to_jsonb(CASE WHEN facts->>'side'='home' THEN %s::text ELSE %s::text END))
                    WHERE is_current AND bookmaker_id=ANY(%s)""",
                    (home, away, ["fanduel", "draftkings"]),
                )
                quotes = read_book_quotes(db, request())
                self.assertEqual(len(quotes), 4)
                self.assertEqual(
                    {q["venue"] for q in quotes}, {"fanduel", "draftkings"}
                )
            # A large alternate request set and repeated witnesses must retain
            # exactly the same original bodies, once per quote identity.
            import json

            many_lines = request() * 2 + [
                dict(event_id="event", family="spread", numerator=n, denominator=1)
                for n in range(256)
            ]
            self.assertEqual(
                sorted(
                    json.dumps(q, sort_keys=True)
                    for q in read_book_quotes(db, many_lines)
                ),
                sorted(json.dumps(q, sort_keys=True) for q in quotes),
            )
            # Invalid and out-of-range retained numbers stay excluded rather
            # than turning a harmless old quote into a failed board request.
            for value in ("not-a-line", "1e-10000000", "1/0"):
                db.execute(
                    "UPDATE sgo_quote_revision SET facts=jsonb_set(facts,'{line}',%s) WHERE is_current",
                    (Jsonb(value),),
                )
                self.assertEqual(read_book_quotes(db, request()), [])
            db.execute(
                "UPDATE sgo_quote_revision SET facts=jsonb_set(facts,'{market}','\"moneyline\"') WHERE is_current"
            )
            # Moneyline identity never depends on a source's irrelevant line.
            self.assertEqual(
                len(read_book_quotes(db, request("moneyline", None, 1))), 4
            )
            db.execute("""UPDATE sgo_quote_revision SET facts=jsonb_set(
                jsonb_set(facts,'{market}','\"total\"'),'{line}','\"1E+2\"') WHERE is_current""")
            self.assertEqual(len(read_book_quotes(db, request("total", 100, 1))), 4)
            self.assertEqual(read_book_quotes(db, request("total", 101, 1)), [])
            from app.comparison.sgo_reference import american_probability

            scope = request("total", 100, 1)
            scope[0].update(
                cost_numerator=2,
                cost_denominator=5,
                group_key="unparsed-price",
                canonical_side="home",
            )
            # The SQL fast parser cannot prove these prices impossible. Keep
            # their witnesses for the ordinary validator rather than inventing
            # an absence (including its accepted Unicode-decimal spelling).
            self.assertEqual(american_probability("+١٠٠"), Fraction(1, 2))
            with self.assertRaises(ValueError):
                american_probability("+100.0000000000001")
            for value in ("+١٠٠", "+100.0000000000001"):
                db.execute(
                    "UPDATE sgo_quote_revision SET facts=jsonb_set(facts,'{price_american}',%s) WHERE is_current",
                    (Jsonb(value),),
                )
                self.assertEqual(len(read_book_quotes(db, scope)), 4)

    async def test_book_query_restores_jit_in_autocommit_and_outer_transactions(self):
        from app.storage.pregame_arbs import book_query
        from psycopg.errors import DivisionByZero

        with self.connect() as db:
            for outer in (False, True):
                from contextlib import nullcontext

                with (
                    self.subTest(outer_transaction=outer),
                    db.transaction() if outer else nullcontext(),
                ):
                    db.execute("SELECT set_config('jit','on',false)")
                    self.assertEqual(
                        book_query(
                            db, "SELECT current_setting('jit') AS jit", None
                        ).fetchone()["jit"],
                        "off",
                    )
                    self.assertEqual(db.execute("SHOW jit").fetchone()["jit"], "on")
                    with self.assertRaises(DivisionByZero):
                        book_query(db, "SELECT 1/0", None)
                    self.assertEqual(db.execute("SHOW jit").fetchone()["jit"], "on")
                    db.execute("SELECT set_config('jit','off',false)")
                    book_query(db, "SELECT 1", None)
                    self.assertEqual(db.execute("SHOW jit").fetchone()["jit"], "off")

    async def test_book_projection_preserves_strict_json_flags_and_original_facts(self):
        from app.storage.pregame_arbs import read_book_quotes
        from psycopg.types.json import Jsonb

        request = [dict(event_id="event", family="spread", numerator=3, denominator=2)]
        with self.connect() as db:
            self.ingest(db, page())
            for field in ("available", "provider_available"):
                for present, value, expected in (
                    (True, True, 4),
                    (True, False, 0),
                    (True, "true", 0),
                    (True, None, 0),
                    (False, None, 4 if field == "provider_available" else 0),
                ):
                    with self.subTest(field=field, present=present, value=value):
                        db.execute("""UPDATE sgo_quote_revision SET facts=
                            jsonb_set(jsonb_set(facts,'{available}','true'),
                            '{provider_available}','true') WHERE is_current""")
                        db.execute(
                            "UPDATE sgo_quote_revision SET facts=(facts-%s) || %s WHERE is_current",
                            (field, Jsonb({field: value} if present else {})),
                        )
                        rows = read_book_quotes(db, request)
                        self.assertEqual(len(rows), expected)
                        if expected:
                            originals = [
                                r["facts"]
                                for r in db.execute(
                                    "SELECT facts FROM current_sgo_reference WHERE event_id='event'"
                                )
                                if r["facts"].get("venue") in ("fanduel", "draftkings")
                            ]
                            self.assertCountEqual(rows, originals)
            db.execute(
                "UPDATE sgo_quote_revision SET facts='\"malformed\"' WHERE is_current"
            )
            self.assertEqual(read_book_quotes(db, request), [])

    async def test_pending_reference_job_suppresses_pairs_before_recalculation(self):
        from app.fees import pricing
        from tests.test_fee_pricing import rule
        from app.storage.pregame_arbs import read as arb_read

        data = page()
        for odd in data["data"][0]["odds"].values():
            quote = dict(odd["byBookmaker"]["prophetx"], odds="+120")
            odd["byBookmaker"] = {"novig": quote, "prophetx": deepcopy(quote)}
        with self.connect() as db:
            for venue in ("novig", "prophetx"):
                pricing.write(db, venue, [rule(venue)])
            self.ingest(db, data)
            self.process(db)
            # A separate sportsbook event is attached to the market entries.
            # Its pending job must suppress pairs even with no price-source job.
            db.execute("""UPDATE current_pregame_price SET payload=jsonb_set(
                payload,'{sportsbook_event_ids}','["pending-reference-event"]'::jsonb)""")
            before = arb_read(db, {}, at=stamp(AT))
            self.assertGreater(before["total"], 0)
            db.execute(
                "SELECT pregame_enqueue('sportsgameodds','pending-reference-event')"
            )
            self.assertEqual(arb_read(db, {}, at=stamp(AT))["total"], 0)
            self.process(db)
            restored = arb_read(db, {}, at=stamp(AT))
            self.assertEqual(restored["rows"], before["rows"])

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
