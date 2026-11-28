"""Native offers never mutate acquired source quotes or frozen paper evidence."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from psycopg.types.json import Jsonb

from app.collection.native_trading import NativeTrading
from app.collection.native_trading_identity import native_event, record, expected
from app.storage import native_trading
from app.storage.store import stamp
from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import AT, PregameFixture, page
from tests.test_liquidity_execution import admitted


def native_book(db, at):
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
    return source, book


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class NativeTradingSQL(PregameFixture):
    async def test_coverage_reports_empty_venues_and_scoped_access_gaps(self):
        at = stamp(AT)
        with self.connect() as db:
            status = dict(background_work=dict(progress=dict(dashboard_depth=dict(
                access_gaps={"prophetx": "prophetx_market_data_entitlement_denied"},
                league_access_gaps={"prophetx": {"NBA": "prophetx_tournament_id_unverified"}},
            ))))
            with db.transaction(force_rollback=True):
                db.execute("DELETE FROM data_runtime")
                db.execute("""INSERT INTO data_runtime
                    (runtime_id,owner_pid,started_at,heartbeat_at,state,config,source_status,dispatch,
                     status,fingerprint,paused_sources,global_stopped)
                    VALUES ('coverage-test',1,%s,%s,'running','{}','{}',true,%s,'fixture','["kalshi"]',false)""",
                    (at, at, Jsonb(status)))
                all_venues = native_trading.coverage(db, at=at, sport="NBA")
                self.assertEqual(len(all_venues["coverage"]), 4)
                self.assertTrue(all(row["opportunities"] == 0 and row["ev_eligible"] == 0
                                    for row in all_venues["coverage"]))
                self.assertEqual(all_venues["access"]["kalshi"]["collection"], "source_paused")
                self.assertEqual(all_venues["access"]["prophetx"], dict(
                    reason="prophetx_market_data_entitlement_denied", collection=None,
                    leagues={"NBA": "prophetx_tournament_id_unverified"},
                ))
                selected = native_trading.coverage(db, at=at, sport="NFL", venue="prophetx")
                self.assertEqual([row["venue"] for row in selected["coverage"]], ["prophetx"])
                self.assertEqual(selected["access"]["prophetx"]["leagues"], {})
                self.assertEqual(selected["provider_requests"], 0)
                self.ingest(db, page())
                _, book = native_book(db, at)
                observations = {}
                for state, changes in {
                    "stale": dict(valid_until=at.isoformat(), received_at=(at - timedelta(seconds=1)).isoformat()),
                    "unobserved": dict(levels=[], complete=False, received_at=None, valid_until=None),
                    "empty": dict(levels=[], complete=True),
                    "fee": dict(fee={"reason": "fee_schedule_unverified"}),
                }.items():
                    marked = deepcopy(book)
                    marked.update(market_id=state, **changes)
                    marked["_record"]["quote"]["source"]["native_market_id"] = state
                    observations[state] = marked
                self.assertEqual(native_trading.publish(db, observations, at=at)["published"], 4)
                (live,) = native_trading.coverage(db, at=at, venue="novig")["coverage"]
                self.assertEqual((live["opportunities"], live["exact_matches"], live["fresh_books"]), (4, 4, 2))
                for reason in ("stale_book", "book_unobserved", "confirmed_empty", "fee_schedule_unverified"):
                    self.assertEqual(live["reasons"][reason], 1)

    async def test_novig_links_retained_spread_roles_with_matching_kickoff(self):
        from app.collection.native_trading_identity import link
        from app.comparison.sgo_native_binding import capture_catalog
        from app.storage import sgo_native_catalog
        from tests.test_sgo_native_binding import AWAY, EVENT, EVENT_PATH, HOME, MARKETS_PATH, fixture, receipt

        observed = stamp(AT)
        at = observed + timedelta(minutes=50)
        source_id = 'fixture-college-typed-roles'
        data = page()
        game = data['data'][0]
        game.update(eventID=source_id, leagueID='NCAAB', links={'bookmakers': {
            'novig': f'https://novig.com/event-markets/{EVENT}/sportsgameodds',
        }})
        game['teams']['home']['names']['long'] = 'San Diego State'
        game['teams']['away']['names']['long'] = 'Texas Tech Red Raiders'
        for odd in game['odds'].values():
            outcome = HOME if odd['sideID'] == 'home' else AWAY
            odd['byBookmaker']['novig'] = dict(odd['byBookmaker']['fanduel'],
                deeplink=f'https://novig.com/events/{outcome}/sportsgameodds')
        _, official, spread = fixture()
        official.update(league='NCAAB', startsTs=int(stamp(game['status']['startsAt']).timestamp() * 1000))
        spread.update(startsTs=official['startsTs'], strike='-1.5')
        spread['outcomes'][0]['name'] = 'TTU +1.5'
        spread['outcomes'][1]['name'] = 'SDSU -1.5'

        with self.connect() as db:
            self.ingest(db, data)
            (sgo_id, native_id, linked_outcomes, frame), = sgo_native_catalog.targets(db, at=observed)
            witness = capture_catalog(sgo_id, native_id, official, receipt(EVENT_PATH, AT),
                [(dict(items=[spread]), receipt(MARKETS_PATH, AT))], linked_outcomes, sgo_frame=frame)
            self.assertLess(stamp(witness['expires_at']), at)
            sgo_native_catalog.write(db, source_id, witness)
            source, book = native_book(db, at)
            subjects = witness['subject_roles']
            self.assertEqual(set(subjects), {'home', 'away'})
            event = native_event('novig', EVENT, 'NCAAB', source['scheduled_start'],
                {role: 'novig:team:' + subject for role, subject in subjects.items()},
                dict(home='SDSU', away='TTU'),
                proof=dict(method='documented_home_handicap_and_both_native_subject_ids', subjects=subjects))
            row = record('novig', event, spread['marketId'], HOME, 'buy', 'spread', 'home', '-1.5', settlement={})
            book.update(event_id=EVENT, market_id=spread['marketId'], outcome_id=HOME,
                        opposite_outcome_id=AWAY, _record=row)
            book['contract'] = dict(book['contract'], **expected(row))
            self.assertEqual(native_trading.publish(db, {'retained': book}, at=at)['published'], 1)

            def saved():
                return db.execute('''SELECT game_link,book,net_ev,reference_valid_until
                    FROM native_trading_offer WHERE native_event_id=%s''', (EVENT,)).fetchone()

            without_prices = saved()
            self.assertEqual(without_prices['game_link']['sgo_event_id'], source_id)
            self.assertIsNone(without_prices['net_ev'])
            self.assertIsNone(without_prices['reference_valid_until'])
            fresh = deepcopy(data)
            for odd in fresh['data'][0]['odds'].values():
                for price in odd['byBookmaker'].values():
                    price['lastUpdatedAt'] = (at - timedelta(seconds=2)).isoformat()
            with patch('tests.pregame_fixture.AT', at.isoformat()):
                self.ingest(db, fresh)
            self.assertEqual(native_trading.publish(db, {'retained': book}, at=at)['published'], 1)
            valued = saved()
            self.assertGreater(valued['net_ev'], 0)
            self.assertGreater(valued['reference_valid_until'], at)
            self.assertEqual(valued['book'], without_prices['book'])
            self.assertEqual(valued['game_link']['sgo_start'], source['scheduled_start'])
            self.assertEqual(valued['game_link']['method'], 'typed_source_event_and_retained_subject_roles')
            self.assertEqual(valued['game_link']['evidence']['novig_subject_roles']['sgo_frame'], frame)
            (shown,) = native_trading.dashboard(db, at=at, until=at + timedelta(hours=1),
                                                venue='novig', sport='NCAAB')['rows']
            self.assertEqual(shown['calculation']['status'], 'positive')

            (anchor,) = native_trading.anchors(db, at, novig_events={EVENT})
            swapped = deepcopy(event)
            swapped.update(home=event['away'], away=event['home'])
            swapped['native_role_evidence']['subjects'] = dict(home=subjects['away'], away=subjects['home'])
            wrong_team = dict(event, home='NCAAB:M:D1:NCAA306')
            wrong_date = dict(event, scheduled_start=(stamp(source['scheduled_start']) + timedelta(minutes=1)).isoformat())
            for contradictory in (swapped, wrong_team, wrong_date):
                rejected = link(contradictory, [anchor])
                self.assertEqual(rejected['reason'], 'occurrence_identity_conflict')
                self.assertEqual(rejected['evidence']['candidate_rejections'], {source_id: 'team_role_conflict'})
            missing_link = deepcopy(anchor)
            missing_link['event'].pop('shared_provider_ids')
            self.assertEqual(link(event, [missing_link])['reason'], 'occurrence_unmatched')
            duplicate = deepcopy(anchor)
            duplicate['event']['id'] = 'other-sgo-event'
            duplicate['novig_subject_roles']['sgo_event_id'] = 'other-sgo-event'
            duplicate['canonical_game_id'] = 'source:sportsgameodds:other-sgo-event'
            self.assertEqual(link(event, [anchor, duplicate])['reason'], 'ambiguous_occurrence')

    async def test_native_commit_is_independent_of_sgo_writer_and_orders_waiting_books(self):
        at = stamp(AT)
        original = page()
        for odd in original["data"][0]["odds"].values():
            odd["byBookmaker"].pop("draftkings", None)
        with self.connect() as db:
            self.ingest(db, original)
            source, older = native_book(db, at)
        newer_at = at + timedelta(seconds=1)
        newer = dict(
            older,
            sequence=11,
            source_at=(newer_at - timedelta(seconds=2)).isoformat(),
            received_at=newer_at.isoformat(),
        )
        owner = SimpleNamespace(
            service=SimpleNamespace(dispatch=True, globally_stopped=False, paused_sources=[]),
            _near_checkpoint=lambda: False,
        )
        trader = NativeTrading(owner, connector=self.connect, now=lambda: newer_at)

        async with asyncio.timeout(5):
            with self.connect() as native:
                native.execute(
                    "SELECT pg_advisory_lock(%s)", (native_trading.PUBLICATION_LOCK,)
                )
                with self.connect() as sgo, sgo.transaction():
                    sgo.execute("SELECT pg_advisory_xact_lock(901095)")
                    waiting = asyncio.create_task(trader.save({"older": older}))
                    while not native.execute(
                        "SELECT EXISTS (SELECT FROM pg_locks WHERE locktype='advisory' "
                        "AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
                        "AND objid=%s AND NOT granted) AS waiting",
                        (native_trading.PUBLICATION_LOCK,),
                    ).fetchone()["waiting"]:
                        await asyncio.sleep(0.01)
                    self.assertEqual(
                        native_trading.publish(native, {"newer": newer}, at=newer_at)["published"], 1
                    )
                    # Publish an SGO reference change before the older writer
                    # can enter. Only the current book may revalue against it.
                    self.ingest(sgo, page())
            self.assertTrue(await waiting)
            with self.connect() as reader:
                current = reader.execute(
                    "SELECT book,game_link,book_valid_until,reference_valid_until "
                    "FROM public.native_trading_offer"
                ).fetchone()
                self.assertEqual(current["book"]["sequence"], 11)
                self.assertEqual(current["book_valid_until"], stamp(newer["valid_until"]))
                self.assertEqual(current["game_link"]["sgo_event_id"], source["id"])
                self.assertEqual(current["game_link"]["status"], "matched")
                self.assertEqual(
                    reader.execute("SELECT count(*) AS n FROM public.native_trading_snapshot").fetchone()["n"], 1
                )
                self.assertIsNone(current["reference_valid_until"])
            self.assertTrue(await trader.save({"current": newer}))
            self.assertTrue(await trader.save({"duplicate": newer}))
            with self.connect() as reader:
                self.assertEqual(
                    reader.execute("SELECT count(*) AS n FROM public.native_trading_snapshot").fetchone()["n"], 2
                )
                self.assertIsNotNone(reader.execute(
                    "SELECT reference_valid_until FROM public.native_trading_offer"
                ).fetchone()["reference_valid_until"])

    async def test_native_publication_defers_to_pending_late_checkpoint(self):
        at = stamp(AT)
        due = at + timedelta(seconds=30)
        owner = SimpleNamespace(
            service=SimpleNamespace(dispatch=True, globally_stopped=False, paused_sources=[]),
            _near_checkpoint=lambda: False,
        )
        trader = NativeTrading(owner, connector=self.connect, now=lambda: at)
        with self.connect() as db:
            self.ingest(db, page())
            _, book = native_book(db, at)
            db.execute("""INSERT INTO public.ev_experiment_record(id,kind,refs,payload,payload_bytes)
                VALUES('native-lock-policy','policy','{}','{}',2),
                      ('native-lock-schedule','schedule','{}','{}',2)""")
            db.execute("""INSERT INTO public.ev_experiment_game
                (id,policy_id,provider,source_event_id,event,discovered_at,first_observed_at,schedule_id)
                VALUES('native-lock-game','native-lock-policy','sportsgameodds','event','{}',%s,%s,'native-lock-schedule')""",
                (at, at))
            db.execute("""INSERT INTO public.ev_experiment_task(game_id,checkpoint,schedule_id,target_at,deadline_at)
                VALUES('native-lock-game','late','native-lock-schedule',%s,%s)""",
                (due, due + timedelta(minutes=1)))
        self.assertFalse(await trader.save({"book": book}))
        self.assertEqual(trader.progress["reason"], "protected_checkpoint")
        with self.connect() as db:
            task = db.execute("SELECT state,target_at,result_id FROM public.ev_experiment_task "
                              "WHERE game_id='native-lock-game'").fetchone()
            self.assertEqual(task, dict(state="pending", target_at=due, result_id=None))
            self.assertEqual(db.execute("SELECT count(*) AS n FROM public.native_trading_offer").fetchone()["n"], 0)

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
            db.execute(
                "DELETE FROM public.delivery_clock WHERE provider='sportsgameodds'"
            )

    async def test_later_monitor_page_revalues_same_book_after_deferred_publication(
        self,
    ):
        from app.collection.native_reference_refresh import targets
        from app.storage.delivery_clocks import sgo_admitted

        at = stamp(AT)
        now = at + timedelta(seconds=3)
        fixture = page()
        for odd in fixture["data"][0]["odds"].values():
            odd["byBookmaker"].pop("draftkings", None)
        with self.connect() as db:
            self.ingest(db, fixture)
            source, book = native_book(db, at)
            native_trading.publish(db, {"book": book}, at=at)
            original = db.execute("SELECT * FROM native_trading_offer").fetchone()
            self.assertIsNone(original["reference_valid_until"])
            (refresh_target,) = targets(
                db, at=at, until=stamp(source["scheduled_start"])
            )
            self.assertEqual(refresh_target["event_id"], source["id"])
            self.assertEqual(refresh_target["book_until"], original["book_valid_until"])
            with db.transaction():
                for pull, requested, received in (
                    (
                        "monitor-first",
                        at - timedelta(minutes=1),
                        at - timedelta(seconds=3),
                    ),
                    (
                        "checkpoint-newer",
                        at - timedelta(seconds=2),
                        at - timedelta(seconds=1),
                    ),
                ):
                    db.execute(
                        """INSERT INTO market_pull(pull_id,requested_at,request_scope,state)
                        VALUES(%s,%s,'{}','in_progress')""",
                        (pull, requested),
                    )
                    db.execute(
                        """INSERT INTO market_pull_receipt
                        (pull_id,attempt_id,receipt_sha256,received_at,membership)
                        VALUES(%s,%s,'fixture',%s,'{}')""",
                        (pull, pull, received),
                    )

        owner = SimpleNamespace(
            service=SimpleNamespace(
                dispatch=True, globally_stopped=False, paused_sources=[]
            )
        )
        trader = NativeTrading(owner, connector=self.connect, now=lambda: now)
        trader.protected = lambda: False
        cursor, _ = trader.reference_changes(None)
        with self.connect() as db, db.transaction():
            self.ingest(db, page())
            sgo_admitted(db, [source["competition"]], now)
            db.execute(
                """INSERT INTO market_pull_receipt
                (pull_id,attempt_id,receipt_sha256,received_at,membership)
                VALUES('monitor-first','monitor-later','fixture',%s,'{}')""",
                (now,),
            )
        overrides = [{"state": "deferred", "reason": "protected_checkpoint"}]

        def write(books):
            if overrides:
                return overrides.pop()
            with self.connect() as db:
                return native_trading.publish(db, books, at=now)

        trader.write = write
        self.assertEqual(await trader.revalue_references(cursor), cursor)
        self.assertEqual(trader.progress["reason"], "protected_checkpoint")
        after = await trader.revalue_references(cursor)
        self.assertNotEqual(after, cursor)
        self.assertEqual(trader.reference_changes(after), (after, {}))
        with self.connect() as db:
            updated = db.execute("SELECT * FROM native_trading_offer").fetchone()
            newest_pull = db.execute(
                "SELECT pull_id FROM market_pull ORDER BY started_order DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(newest_pull["pull_id"], "checkpoint-newer")
            self.assertEqual(updated["book"], original["book"])
            self.assertEqual(updated["book_valid_until"], original["book_valid_until"])
            self.assertGreater(updated["reference_valid_until"], now)
            self.assertGreater(updated["net_ev"], 0)
            (shown,) = native_trading.dashboard(
                db, at=now, until=now + timedelta(hours=24)
            )["rows"]
            self.assertEqual(shown["times"]["source_at"], book["source_at"])

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
            source, book = native_book(db, at)
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

                expired = stamp(shown["eligible_until"])
                stale_board = native_trading.dashboard(
                    db, at=expired, until=expired + timedelta(hours=24), view="all"
                )
                (stale,) = stale_board["rows"]
                self.assertEqual(stale["book_status"], "stale")
                self.assertIsNone(stale["posted"]["value"])
                self.assertIsNone(stale["calculation"]["net_ev_ratio"])
                live_board = native_trading.dashboard(
                    db,
                    at=expired,
                    until=expired + timedelta(hours=24),
                    view="unavailable",
                )
                self.assertEqual(live_board["stored_offers"], 1)
                self.assertEqual(live_board["rows"], [])

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
            preview_at = later + timedelta(seconds=1)
            updated = native_trading.detail(
                db, dict(query, amount="25"), at=preview_at, stake="25"
            )
            self.assertEqual(updated["native_offer"]["book"]["sequence"], 10)
            self.assertEqual(updated["liquidity_evidence"]["sequence"], 11)
            self.assertEqual(stamp(updated["liquidity"]["published_at"]), later)
            self.assertEqual(stamp(updated["liquidity"]["as_of"]), preview_at)
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
