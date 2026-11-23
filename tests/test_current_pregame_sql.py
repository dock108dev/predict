"""Current pregame ingestion, coherent values, retention and pure read coverage."""

from copy import deepcopy
from fractions import Fraction
from time import monotonic
from unittest import skipUnless
from unittest.mock import patch

from tests.latest_board_fixture import SOCKET

from tests.pregame_fixture import AT, page, parse, PregameFixture


from app.storage.current_rows import CurrentRowStore
from app.storage.sportsgameodds_reference import (
    prepare_page,
)
from app.storage.store import stamp
from app.storage import current_pregame as board


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class CurrentPregameSQL(PregameFixture):
    async def test_research_amounts_are_read_only_and_bind_price_fee_reference(self):
        from app.storage.pregame_research import research, ChangedInputs
        from app.storage.pregame_quote_evidence import enrich
        from app.dashboard.bet_journal import Journal
        from app.dashboard import current_pregame_api
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        from psycopg.types.json import Jsonb

        at = stamp(AT)
        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            row = board.read(db, {}, at=at)["rows"][0]
            enriched = enrich(db, [row])[0]
            self.assertEqual(enriched["available_size"]["status"], "unknown")
            before = list(
                db.execute(
                    "SELECT * FROM current_pregame_calculation ORDER BY contract_id"
                )
            )
            request = dict(kind="ev", snapshot=row, amount="25")
            with db.transaction():
                db.execute("SET TRANSACTION READ ONLY")
                with patch.object(
                    Journal,
                    "observe",
                    side_effect=AssertionError("research wrote journal"),
                ):
                    for amount in ("25", "100", "500", "25.13"):
                        request["amount"] = amount
                        result = research(db, request, at=at)
                        self.assertEqual(result["journal_writes"], 0)
                        modeled = result["result"]
                        self.assertLessEqual(
                            Fraction(modeled["fee"]["committed_usd"]), Fraction(amount)
                        )
                        self.assertEqual(modeled["reference"], row["reference"])
                        cash = modeled["fee"]["cashflows"]
                        p = Fraction(row["reference"]["probability"])
                        expected = (
                            p * Fraction(cash["win"]["net_receipt_usd"])
                            + (1 - p) * Fraction(cash["loss"]["net_receipt_usd"])
                            - Fraction(modeled["fee"]["committed_usd"])
                        )
                        self.assertEqual(
                            Fraction(modeled["raw"]["expected_profit_usd"]), expected
                        )
            self.assertEqual(
                before,
                list(
                    db.execute(
                        "SELECT * FROM current_pregame_calculation ORDER BY contract_id"
                    )
                ),
            )
            altered = deepcopy(row)
            altered["reference"]["probability"] = "0.99"
            with self.assertRaises(ChangedInputs):
                research(db, dict(request, snapshot=altered), at=at)
            altered = deepcopy(row)
            altered["posted"]["value"] = "+999"
            with self.assertRaises(ChangedInputs):
                research(db, dict(request, snapshot=altered), at=at)
            # Missing probability still supports price/fee amount research.
            db.execute(
                "UPDATE current_pregame_calculation SET payload=NULL,net_ev=NULL,opportunity_score=NULL,reason=%s WHERE contract_id=%s",
                ("reference_unavailable", row["id"]),
            )
            missing = dict(row, reference=None)
            missing["ev_unavailable_reason"] = "reference_unavailable"
            result = research(db, dict(request, snapshot=missing), at=at)["result"]
            self.assertIsNone(result["raw"]["expected_profit_usd"])
            self.assertIsNone(result["display"]["net_ev"])

        application = web.Application()
        current_pregame_api.mount(application)
        with (
            patch.object(current_pregame_api, "connect", self.connect),
            patch.object(board, "utc", return_value=at),
        ):
            async with TestClient(TestServer(application)) as client:
                response = await client.post(
                    "/api/pregame/research?data_type=all",
                    json=dict(request, snapshot=row),
                )
                self.assertEqual(response.status, 200, await response.text())
                invalid = await client.post(
                    "/api/pregame/research?data_type=all",
                    json=dict(request, amount="0.001"),
                )
                self.assertEqual(invalid.status, 422)

    async def test_maximum_source_age_checks_reference_clocks_and_earliest_deadline(
        self,
    ):
        from datetime import timedelta
        from psycopg.types.json import Jsonb

        at = stamp(AT)
        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            original = board.read(db, {}, at=at)["rows"][0]
            payload = deepcopy(original)
            payload["times"]["source_at"] = at.isoformat()
            payload["reference"]["prices"][0]["source_at"] = (
                at - timedelta(minutes=5)
            ).isoformat()
            for clock in (
                (at - timedelta(minutes=5)).isoformat(),
                (at - timedelta(minutes=11)).isoformat(),
                None,
                (at + timedelta(seconds=1)).isoformat(),
            ):
                payload["reference"]["prices"][0]["source_at"] = clock
                db.execute(
                    "UPDATE current_pregame_calculation SET payload=%s WHERE contract_id=%s",
                    (Jsonb(payload), original["id"]),
                )
                self.assertEqual(board.read(db, {}, at=at)["total"], 1)
                filtered = board.read(db, {"max_age_minutes": "10"}, at=at)
                expected = clock == (at - timedelta(minutes=5)).isoformat()
                self.assertEqual(filtered["total"], int(expected))
                if expected:
                    self.assertEqual(
                        stamp(filtered["refresh_at"]), at + timedelta(minutes=5)
                    )

    async def test_early_started_and_live_notices_withdraw_without_admitting_prices(
        self,
    ):
        import json
        from dataclasses import replace
        from datetime import timedelta
        from app.collection.sportsgameodds_adapter import parse_page
        from app.storage.sportsgameodds_reference import (
            prepare_frames,
            upsert_frames,
            apply_event_lifecycle,
        )

        with self.connect() as db:
            for index, live in enumerate((False, True)):
                with self.subTest(live=live):
                    data = page()
                    event = data["data"][0]
                    event["eventID"] += "-early-" + str(index)
                    event["status"]["startsAt"] = (
                        stamp(event["status"]["startsAt"])
                        + timedelta(minutes=index * 5)
                    ).isoformat()
                    self.ingest(db, data)
                    self.process(db)
                    self.assertEqual(board.read(db, {}, at=stamp(AT))["total"], 1)
                    received = stamp(AT) + timedelta(minutes=1)
                    event["status"].update(started=True, live=live)
                    closed = replace(
                        parse_page(json.dumps(data).encode(), received.isoformat()),
                        quotes=(),
                    )
                    frames = prepare_frames(closed, [])
                    before_quotes = list(
                        db.execute(
                            "SELECT * FROM sgo_quote_revision ORDER BY id,revision"
                        )
                    )
                    with self.assertRaisesRegex(RuntimeError, "injected rollback"):
                        with db.transaction():
                            upsert_frames(db, frames)
                            changed, records = apply_event_lifecycle(db, frames, [], [])
                            self.assertGreater(changed, 0)
                            self.assertEqual(records, [])
                            raise RuntimeError("injected rollback")
                    self.assertEqual(board.read(db, {}, at=received)["total"], 1)
                    with db.transaction():
                        upsert_frames(db, frames)
                        changed, records = apply_event_lifecycle(db, frames, [], [])
                        self.assertGreater(changed, 0)
                        self.assertEqual(records, [])
                    # Withdrawal is visible even before queued recalculation.
                    self.assertEqual(board.read(db, {}, at=received)["total"], 0)
                    self.assertEqual(
                        before_quotes,
                        list(
                            db.execute(
                                "SELECT * FROM sgo_quote_revision ORDER BY id,revision"
                            )
                        ),
                    )
                    with db.transaction():
                        upsert_frames(db, frames)
                        changed, _ = apply_event_lifecycle(db, frames, [], [])
                        self.assertEqual(changed, 0)

    async def test_source_transaction_coalesces_jobs_and_browser_revision(self):
        with self.connect() as db:
            before = db.execute(
                "SELECT revision FROM current_pregame_revision"
            ).fetchone()["revision"]
            with db.transaction():
                for _ in range(100):
                    db.execute("SELECT pregame_enqueue('sportsgameodds','coalesced')")
                first = db.execute(
                    "SELECT revision,admitted_at FROM current_pregame_work"
                ).fetchone()
                self.assertEqual(first["revision"], 1)
                self.assertEqual(
                    db.execute(
                        "SELECT revision FROM current_pregame_revision"
                    ).fetchone()["revision"],
                    before + 1,
                )
                db.execute("SELECT pregame_enqueue('sportsgameodds','unrelated')")
                self.assertEqual(
                    db.execute(
                        "SELECT count(*) n FROM current_pregame_work"
                    ).fetchone()["n"],
                    2,
                )
            with db.transaction():
                db.execute("SELECT pregame_enqueue('sportsgameodds','coalesced')")
                newer = db.execute(
                    "SELECT revision,admitted_at FROM current_pregame_work WHERE native_event_id='coalesced'"
                ).fetchone()
                self.assertEqual(newer["revision"], 2)
                self.assertGreaterEqual(newer["admitted_at"], first["admitted_at"])
                db.execute(
                    "UPDATE current_pregame_work SET error='retry' WHERE native_event_id='coalesced'"
                )
                db.execute("SELECT pregame_enqueue('sportsgameodds','coalesced')")
                recovered = db.execute(
                    "SELECT revision,error FROM current_pregame_work WHERE native_event_id='coalesced'"
                ).fetchone()
                self.assertEqual(recovered, dict(revision=3, error=None))

    async def test_inactive_route_does_not_resolve_or_recalculate_active_game(self):
        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            before = list(db.execute("SELECT * FROM current_pregame_calculation"))
            with db.transaction():
                db.execute(
                    "INSERT INTO current_pregame_work(provider,native_event_id) VALUES('oddslink_public_board','inactive')"
                )
            with patch.object(
                board,
                "affected",
                side_effect=AssertionError("inactive route loaded game"),
            ):
                result = self.process(db)
            self.assertEqual(result[0]["offers"], 0)
            self.assertEqual(
                before, list(db.execute("SELECT * FROM current_pregame_calculation"))
            )
            self.assertEqual(
                db.execute("SELECT count(*) AS n FROM current_pregame_work").fetchone()[
                    "n"
                ],
                0,
            )

    async def test_recovery_yields_between_games_without_claiming_ingress_work(self):
        with self.connect() as db:
            self.ingest(db, page())
            with db.transaction():
                db.execute(
                    "INSERT INTO current_pregame_work(provider,native_event_id) VALUES('oddslink_public_board','inactive')"
                )
            self.assertEqual(self.process(db, can_continue=lambda: False), [])
            self.assertEqual(
                db.execute("SELECT count(*) n FROM current_pregame_work").fetchone()[
                    "n"
                ],
                2,
            )
            turns = iter((True, False))
            self.assertEqual(len(self.process(db, can_continue=lambda: next(turns))), 1)
            self.assertEqual(
                db.execute("SELECT count(*) n FROM current_pregame_work").fetchone()[
                    "n"
                ],
                1,
            )
            self.assertEqual(len(self.process(db)), 1)
            self.assertEqual(
                db.execute("SELECT count(*) n FROM current_pregame_work").fetchone()[
                    "n"
                ],
                0,
            )

    async def test_restart_seed_only_configured_price_routes(self):
        from app.collection.pregame_owner import PregameOwner

        with self.connect() as db:
            self.ingest(db, page())
            with db.transaction():
                db.execute("DELETE FROM current_pregame_work")
                db.execute(
                    "UPDATE current_event SET expires_order=extract(epoch FROM clock_timestamp())+60"
                )
                db.execute("UPDATE current_event SET provider='oddslink_public_board'")
            with patch("app.collection.pregame_owner.connect", self.connect):
                PregameOwner(None).seed()
            self.assertEqual(
                db.execute("SELECT count(*) AS n FROM current_pregame_work").fetchone()[
                    "n"
                ],
                0,
            )
            with db.transaction():
                db.execute("UPDATE current_event SET provider='sportsgameodds'")
            with patch("app.collection.pregame_owner.connect", self.connect):
                PregameOwner(None).seed()
            self.assertEqual(
                db.execute("SELECT count(*) AS n FROM current_pregame_work").fetchone()[
                    "n"
                ],
                1,
            )

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
                prices = {
                    q["book"]: q["posted_odds"] for q in comparison["sportsbooks"]
                }
                self.assertEqual(prices, {"fanduel": "-110", "draftkings": "-130"})
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
                update_query = dict(
                    layout="desk", after=first["cursor"], data_type=first["data_type"]
                )
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
                beyond = board.read(
                    db, dict(lines="all", browse="1", offset="102"), at=stamp(AT)
                )
                expanded = board.read(
                    db,
                    dict(view="game", game_key=complete["rows"][0]["game_key"]),
                    at=stamp(AT),
                )
                self.assertEqual(len(expanded["rows"]), 102)
            self.assertEqual(len(records), 408)
            # SGO's original polymarket alias cannot borrow US venue fees.
            self.assertEqual(sum(row["complete"] for row in result), 306)
            self.assertEqual(complete["total"], 102)
            self.assertEqual(beyond["total"], 102)
            self.assertEqual(beyond["rows"], [])
            self.assertEqual(len({row["bet_id"] for row in complete["rows"]}), 100)
            self.assertEqual(
                db.execute(
                    "SELECT count(*) n FROM current_pregame_calculation WHERE reason IS NULL"
                ).fetchone()["n"],
                306,
            )
            print(
                "dense current game: 408 offers, 306 fee-bound calculations, 102 exact bets, admission-through-read seconds",
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
            partial.pop('_fixture_acquisition', None)
            odd = next(iter(partial["data"][0]["odds"].values()))
            odd["byBookmaker"] = {"fanduel": odd["byBookmaker"]["fanduel"]}
            partial["data"][0]["odds"] = {odd["oddID"]: odd}
            self.ingest(db, partial)
            self.process(db)
            # This new partial receipt cannot manufacture a same-pull reference
            # from the prior response. Current numeric EV is withheld.
            self.assertEqual(board.read(db, {}, at=stamp(AT))["rows"], [])
            older = deepcopy(data)
            for odd in older["data"][0]["odds"].values():
                for quote in odd["byBookmaker"].values():
                    quote.update(lastUpdatedAt="2026-11-17T19:58:00Z", odds="+500")
            self.ingest(db, older)
            self.process(db)
            self.assertEqual(board.read(db, {}, at=stamp(AT))["rows"], [])
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
            # DraftKings alone cannot replace the two-book EV reference; the
            # authentic prices remain inspectable with the actual missing input.
            browse = board.read(db, {"browse": "1"}, at=stamp(AT))
            self.assertGreater(browse["total"], 0)
            self.assertTrue(all(r["raw"]["net_ev"] is None for r in browse["rows"]))
            self.assertTrue(
                all(
                    r["ev_unavailable_reason"] == "reference_two_trusted_books_required"
                    for r in browse["rows"]
                )
            )
            self.assertEqual(board.read(db, {}, at=stamp(AT))["total"], 0)
            db.execute(
                "UPDATE sgo_quote_revision SET facts=jsonb_set(facts,'{available}','true') WHERE is_current AND bookmaker_id='fanduel'"
            )
            self.process(db)
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

    async def test_conservative_reference_shared_by_venues_and_snapshot_revalue(self):
        from app.comparison import current_pregame as math
        from app.storage.pregame_snapshot import revalue
        from psycopg.types.json import Jsonb

        data = page()
        home, away = list(data["data"][0]["odds"].values())
        home["byBookmaker"]["draftkings"]["odds"] = "-105"
        away["byBookmaker"]["draftkings"]["odds"] = "-115"
        home["byBookmaker"]["betmgm"] = dict(home["byBookmaker"]["draftkings"])
        away["byBookmaker"]["betmgm"] = dict(away["byBookmaker"]["draftkings"])
        home["byBookmaker"]["novig"] = dict(
            home["byBookmaker"]["prophetx"], odds="+115"
        )
        away["byBookmaker"]["novig"] = dict(away["byBookmaker"]["prophetx"])
        with self.connect() as db:
            from app.fees import pricing
            from tests.test_fee_pricing import rule

            pricing.write(db, "novig", [rule("novig")])
            records = self.ingest(db, data)
            self.process(db)
            selected = board.read(db, {}, at=stamp(AT))["rows"][0]
            rows = board.read(db, {"bet_id": selected["bet_id"]}, at=stamp(AT))["rows"]
            self.assertEqual({r["venue"] for r in rows}, {"prophetx", "novig"})
            self.assertTrue(all(r["reference"]["book"] == "draftkings" for r in rows))
            self.assertTrue(
                all(
                    Fraction(r["reference"]["probability"]) == Fraction(903, 1846)
                    for r in rows
                )
            )
            novig = next(r for r in rows if r["venue"] == "novig")
            self.assertEqual(novig["display"]["net_ev"], "+5.17%")
            self.assertEqual(novig["display"]["opportunity_score"], "450")
            record = next(
                r
                for r in records
                if r["quote"]["venue"] == "novig"
                and r["selection"]["signed_line"] == "-1.5"
            )
            refs = [
                q for q in prepare_page(parse(data)) if q["facts"]["venue"] == "fanduel"
            ]
            # Construct a historical one-book record explicitly; the current
            # selector must now reject it even at the same calculation version.
            old_ref = dict(
                novig["reference"],
                book="fanduel",
                probability="0.5",
                fair_decimal_odds="2",
                fair_odds="+100",
                prices=[q["facts"] for q in refs],
                candidate_probabilities={"fanduel": "0.5"},
                selection_policy="lowest-no-vig-probability-1",
            )
            old = math.revalue_reference(novig, old_ref, at=stamp(AT))
            old["version"] = math.VERSION
            db.execute(
                "UPDATE current_pregame_calculation SET version=%s,payload=%s WHERE contract_id=%s",
                (old["version"], Jsonb(old), novig["id"]),
            )
            source_before = list(
                db.execute("SELECT id,revision FROM current_sgo_reference ORDER BY id")
            )
            with patch("app.storage.current_rows.utc", return_value=AT):
                report = revalue(db, at=stamp(AT))
            self.assertEqual(report["revalued"], 1)
            self.assertEqual(report["excluded"], {})
            actual = board.read(db, {"id": novig["id"]}, at=stamp(AT))["rows"][0]
            self.assertEqual(actual["reference"]["book"], "draftkings")
            for key in ("fee", "times", "posted", "source"):
                self.assertEqual(actual[key], old[key])
            self.assertEqual(actual["display"]["net_ev"], "+5.17%")
            self.assertEqual(
                list(
                    db.execute(
                        "SELECT id,revision FROM current_sgo_reference ORDER BY id"
                    )
                ),
                source_before,
            )
            self.assertEqual(revalue(db, at=stamp(AT))["examined"], 0)
            db.execute(
                "UPDATE current_pregame_calculation SET version='future-unknown' WHERE contract_id=%s",
                (novig["id"],),
            )
            with self.assertRaisesRegex(ValueError, "full calculation upgrade"):
                revalue(db, at=stamp(AT))

    async def test_single_trusted_book_has_no_ev_but_keeps_source_prices(self):
        data = page()
        for odd in data["data"][0]["odds"].values():
            other = odd["byBookmaker"].pop("draftkings")
            odd["byBookmaker"]["casumo"] = other
        with self.connect() as db:
            self.ingest(db, data)
            self.process(db)
            rows = board.read(db, dict(browse="1", lines="all"), at=stamp(AT))["rows"]
            self.assertTrue(rows)
            self.assertTrue(
                all(
                    r["ev_unavailable_reason"] == "reference_two_trusted_books_required"
                    for r in rows
                )
            )
            self.assertTrue(all(r["raw"]["net_ev"] is None for r in rows))
            self.assertEqual(board.read(db, {}, at=stamp(AT))["total"], 0)
            self.assertGreater(
                db.execute("SELECT count(*) n FROM current_pregame_price").fetchone()[
                    "n"
                ],
                0,
            )
            reasons = {
                r["reason"]
                for r in db.execute("SELECT reason FROM current_pregame_calculation")
            }
            self.assertIn("reference_two_trusted_books_required", reasons)
