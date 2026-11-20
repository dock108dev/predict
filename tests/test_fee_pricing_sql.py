"""Database fee edits reach complete SGO current rows without native collection."""

from copy import deepcopy
from fractions import Fraction
from datetime import timedelta
from unittest import skipUnless

from app.collection.sportsgameodds_current_rows import current_rows
from app.fees import pricing
from app.storage import current_pregame as board
from app.storage.current_rows import CurrentRowStore
from app.storage.sportsgameodds_reference import (
    prepare_page,
    prepare_frames,
    upsert_rows,
    upsert_frames,
)
from app.storage.store import stamp
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_current_pregame_sql import page, parse, AT
from tests.test_fee_pricing import rule


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class FeePricingSQL(LatestBoardFixture):
    def enqueue_deadlines(self, db, at):
        db.execute(
            """INSERT INTO current_pregame_work(provider,native_event_id)
            SELECT DISTINCT e.provider,e.native_event_id FROM current_pregame_calculation p
            JOIN current_contract c ON c.id=p.contract_id JOIN current_event e ON e.id=c.event_id
            WHERE p.valid_until<=%s AND p.start_at>%s
              AND (p.reason IS NULL OR p.reason='fee_rule_no_current_schedule')
            ON CONFLICT DO NOTHING""",
            (at, at),
        )

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.service.config.update(
            aggregate_provider="sportsgameodds",
            direct_kalshi_enabled=False,
            direct_polymarket_us_enabled=False,
        )
        self.state.write(self.service)
        with self.connect() as db:
            db.execute(
                "TRUNCATE current_event,sgo_event_evidence,sgo_quote_revision,current_pregame_work CASCADE"
            )
            db.execute("DELETE FROM public_fee_schedule")

    async def test_research_contract_quantities_and_entry_fees_are_amount_specific(
        self,
    ):
        from app.storage.pregame_research import research
        from app.fees import pricing
        from tests.test_fee_pricing import rule

        at = stamp(AT)
        data = page()
        for odd in data["data"][0]["odds"].values():
            for venue in ("kalshi", "polymarket"):
                odd["byBookmaker"][venue] = deepcopy(odd["byBookmaker"]["prophetx"])
        with self.connect() as db:
            for venue in ("kalshi", "polymarket_us"):
                pricing.write(db, venue, [rule(venue)])
            parsed = parse(data)
            refs = prepare_page(parsed)
            records, _ = current_rows(parsed, parsed.receipt_sha256)
            with db.transaction():
                upsert_rows(db, refs)
                upsert_frames(db, prepare_frames(parsed, refs))
                CurrentRowStore(db).upsert_records(records, now=AT)
            board.process(db, at=at)
            for venue in ("kalshi", "polymarket_us"):
                row = board.read(db, dict(venue=venue), at=at)["rows"][0]
                for amount in ("25", "100", "500", "25.13"):
                    modeled = research(
                        db, dict(kind="ev", snapshot=row, amount=amount), at=at
                    )["result"]
                    fee = modeled["fee"]
                    quantity, step = (
                        Fraction(fee["quantity"]),
                        Fraction(fee["quantity_increment"]),
                    )
                    self.assertEqual((quantity / step).denominator, 1)
                    self.assertGreater(Fraction(fee["entry_usd"]), 0)
                    self.assertEqual(
                        Fraction(fee["purchase_usd"])
                        + Fraction(fee["entry_usd"])
                        + Fraction(fee["reserve_usd"]),
                        Fraction(fee["committed_usd"]),
                    )
                    self.assertLessEqual(
                        Fraction(fee["committed_usd"]), Fraction(amount)
                    )
                    self.assertEqual(modeled["available_size"]["status"], "unknown")

    async def test_fee_edit_recalculates_sgo_kalshi_and_polymarket_with_original_clocks(
        self,
    ):
        data = page()
        for odd in data["data"][0]["odds"].values():
            for venue in ("kalshi", "polymarket"):
                odd["byBookmaker"][venue] = deepcopy(odd["byBookmaker"]["prophetx"])
        parsed = parse(data)
        references = prepare_page(parsed)
        records, _ = current_rows(parsed, parsed.receipt_sha256)
        with self.connect() as db:
            for venue in ("kalshi", "polymarket_us", "prophetx"):
                pricing.write(db, venue, [rule(venue)])
            with db.transaction():
                upsert_rows(db, references)
                upsert_frames(db, prepare_frames(parsed, references))
                CurrentRowStore(db).upsert_records(records, now=AT)
            board.process(db, at=stamp(AT))
            initial = {}
            for venue in ("kalshi", "polymarket_us"):
                result = board.read(db, dict(venue=venue), at=stamp(AT))
                self.assertTrue(
                    result["rows"],
                    list(
                        db.execute(
                            "SELECT venue,reason FROM current_pregame_calculation"
                        )
                    ),
                )
                row = result["rows"][0]
                self.assertEqual(row["source"]["provider"], "sportsgameodds")
                self.assertGreater(Fraction(row["fee"]["entry_usd"]), 0)
                self.assertLess(
                    Fraction(row["fee"]["committed_usd"]), Fraction("100.01")
                )
                initial[venue] = row
            updated = pricing.read(db)["kalshi"]
            updated[0]["rate"] = "0.1"
            pricing.write(db, "kalshi", updated)
            self.assertGreater(
                db.execute("SELECT count(*) n FROM current_pregame_work").fetchone()[
                    "n"
                ],
                0,
            )
            board.process(db, at=stamp(AT))
            after = board.read(db, dict(venue="kalshi"), at=stamp(AT))["rows"][0]
            self.assertLess(
                Fraction(after["raw"]["net_ev"]),
                Fraction(initial["kalshi"]["raw"]["net_ev"]),
            )
            self.assertEqual(after["posted"], initial["kalshi"]["posted"])
            self.assertEqual(after["times"], initial["kalshi"]["times"])
            self.assertEqual(
                after["fee"]["evidence"]["database_fee_rule"]["rate"], "0.1"
            )
            self.assertEqual(
                board.read(db, dict(venue="polymarket_us"), at=stamp(AT))["rows"][0],
                initial["polymarket_us"],
            )
            bad = deepcopy(updated)
            bad[0]["rate"] = "-1"
            with self.assertRaises(ValueError):
                pricing.write(db, "kalshi", bad)
            self.assertEqual(pricing.read(db)["kalshi"], updated)

    async def test_future_rules_and_account_failures_do_not_use_packaged_fallback(self):
        data = page()
        for odd in data["data"][0]["odds"].values():
            odd["byBookmaker"]["kalshi"] = deepcopy(odd["byBookmaker"]["prophetx"])
        parsed = parse(data)
        refs = prepare_page(parsed)
        records, _ = current_rows(parsed, parsed.receipt_sha256)
        at = stamp(AT)
        cutover = at + timedelta(minutes=10)
        base = rule()
        future = dict(
            base,
            id="NBA-next",
            league="NBA",
            effective_from=cutover.isoformat(),
            rate="0.1",
        )
        with self.connect() as db:
            pricing.write(db, "kalshi", [base, future])
            with db.transaction():
                upsert_rows(db, refs)
                upsert_frames(db, prepare_frames(parsed, refs))
                CurrentRowStore(db).upsert_records(records, now=AT)
            board.process(db, at=at)
            before = board.read(db, dict(venue="kalshi"), at=at)["rows"][0]
            deadline = db.execute(
                "SELECT valid_until FROM current_pregame_calculation WHERE contract_id=%s",
                (before["id"],),
            ).fetchone()["valid_until"]
            self.assertEqual(deadline, cutover)
            # Perform the timer's recovery selection at the controlled clock;
            # no source receipt or quote mutation occurs at this boundary.
            later = cutover + timedelta(seconds=1)
            self.enqueue_deadlines(db, later)
            board.process(db, at=later)
            after = board.read(db, dict(venue="kalshi"), at=later)["rows"][0]
            self.assertEqual(
                after["fee"]["evidence"]["database_fee_rule"]["id"], "NBA-next"
            )
            self.assertEqual(after["times"], before["times"])
            self.assertLess(
                Fraction(after["raw"]["net_ev"]), Fraction(before["raw"]["net_ev"])
            )
            configured = board.CalculationContext(db, later)
            record = next(r for r in records if r["quote"]["venue"] == "kalshi")
            configured.account_error = "kalshi_account_fact_expired_or_not_effective"
            self.assertFalse(configured.fee(record, later)["available"])
            configured.account_error = None
            pricing.write(
                db,
                "kalshi",
                [dict(base, effective_from=(later + timedelta(minutes=5)).isoformat())],
            )
            gap = board.CalculationContext(db, later).fee(record, later)
            self.assertEqual(gap["reason"], "fee_rule_no_current_schedule")
            self.assertFalse(gap["available"])
            board.process(db, at=later)
            self.assertEqual(board.read(db, dict(venue="kalshi"), at=later)["rows"], [])
            activate = later + timedelta(minutes=5, seconds=1)
            self.enqueue_deadlines(db, activate)
            board.process(db, at=activate)
            recovered = board.read(db, dict(venue="kalshi"), at=activate)["rows"][0]
            self.assertEqual(recovered["times"], before["times"])
