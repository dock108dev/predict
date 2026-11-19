"""Disposable PostgreSQL to durable personal journal integration."""

from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from app.dashboard import bet_journal_monitor as monitor
from app.storage.store import stamp
from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import AT, PregameFixture, page
from tests.test_bet_journal_monitor import Journal


# The previous reader is an independent result oracle for the projection/join
# optimization. Both paths still rebuild sportsbook legs from the same inputs.
LEGACY_PRICE_QUERY = """SELECT p.*, calculation.payload AS calculation
FROM current_pregame_price p
JOIN current_contract c ON c.id=p.contract_id
JOIN current_offer o ON o.contract_id=c.id
JOIN current_event e ON e.id=c.event_id
LEFT JOIN current_pregame_calculation calculation ON calculation.contract_id=p.contract_id
    AND calculation.reason IS NULL AND calculation.valid_until>%s
    AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(calculation.payload#>'{reference,prices}') r
        LEFT JOIN current_sgo_reference s ON s.id=r->>'input_id'
        WHERE s.id IS NULL OR s.facts->'available' IS DISTINCT FROM 'true'::jsonb)
WHERE p.start_at>%s AND p.valid_until>%s AND e.scheduled_start::timestamptz>%s
    AND o.facts->>'state' IS DISTINCT FROM 'unavailable'
    AND NOT EXISTS (SELECT 1 FROM current_pregame_work w
        WHERE w.provider=e.provider AND w.native_event_id=e.native_event_id)
    AND NOT EXISTS (SELECT 1 FROM current_pregame_work w
        WHERE w.provider='sportsgameodds' AND (p.payload->'sportsbook_event_ids') ? w.native_event_id)
    AND NOT (COALESCE(e.facts->'status','{}'::jsonb) @> '{"live":true}'::jsonb)
    AND NOT (COALESCE(e.facts->'status','{}'::jsonb) @> '{"ended":true}'::jsonb)
    AND COALESCE(e.facts#>>'{status,status}','') NOT IN
        ('cancelled','final','suspended','started','delayed')
ORDER BY p.game_key,p.contract_id"""


class LegacyRead:
    def __init__(self, db):
        self.db = db

    def execute(self, query, params=None):
        if "FROM current_pregame_price p" in query:
            query = LEGACY_PRICE_QUERY
        return self.db.execute(query, params)


def expire_line(db, quote_id):
    db.execute(
        """INSERT INTO sgo_line_presence
            (quote_id,event_id,bookmaker_id,odd_id,last_seen,scope_received,expired)
        SELECT id,event_id,bookmaker_id,facts->>'odd_id',received_order,received_order,true
        FROM sgo_quote_revision WHERE id=%s AND is_current
        ON CONFLICT(quote_id) DO UPDATE SET expired=true""",
        (quote_id,),
    )


def journal_history(journal):
    with journal.database() as db:
        return {
            table: {tuple(row) for row in db.execute("SELECT * FROM " + table)}
            for table in ("entries", "events", "tracked", "quotes")
        }


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class JournalMonitorSQL(PregameFixture):
    async def test_source_sample_persists_in_independent_real_personal_journal(self):
        from app.dashboard.bet_journal import Journal as DurableJournal

        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
        with TemporaryDirectory(prefix="predict-personal-test-") as folder:
            path = Path(folder) / "bets.sqlite3"
            journal = DurableJournal(path)
            first = monitor.sample(journal=journal, connector=self.connect, at=AT)
            self.assertGreater(first["ev"], 0)
            with journal.database() as db:
                entries = db.execute("SELECT count(*) FROM entries").fetchone()[0]
                quotes = db.execute("SELECT count(*) FROM quotes").fetchone()[0]
            self.assertGreater(quotes, 0)
            # A reopened journal and repeated stored source image do not invent
            # another discovery or another quote.
            reopened = DurableJournal(path)
            monitor.sample(journal=reopened, connector=self.connect, at=AT)
            with reopened.database() as db:
                self.assertEqual(
                    db.execute("SELECT count(*) FROM entries").fetchone()[0], entries
                )
                self.assertEqual(
                    db.execute("SELECT count(*) FROM quotes").fetchone()[0], quotes
                )
            self.assertEqual(reopened.status()["monitor_state"], "running")

    async def test_full_sample_reads_committed_sources_and_rejects_pending_rebuilds(
        self,
    ):
        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
        journal = Journal()
        result = monitor.sample(journal=journal, connector=self.connect, at=AT)
        self.assertGreater(result["quotes"], 0)
        self.assertGreater(result["ev"], 0)
        self.assertTrue(
            any(row["venue"] == "fanduel" for row in journal.received[-1][0])
        )
        self.assertTrue(
            all(at == stamp(AT).isoformat() for _, _, at in journal.observed)
        )
        # Queue an ordinary source change without running the calculation owner.
        # Those inputs cannot be observed as an admitted closing price yet.
        with self.connect() as db:
            db.execute(
                "INSERT INTO current_pregame_work(provider,native_event_id) SELECT provider,native_event_id FROM current_event ON CONFLICT DO NOTHING"
            )
        waiting = Journal()
        result = monitor.sample(journal=waiting, connector=self.connect, at=AT)
        self.assertEqual(result["quotes"], 0)
        self.assertEqual(result["ev"], 0)

    async def test_projected_physical_read_matches_all_legacy_prices_and_clocks(self):
        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            rows = monitor._quote_rows(db, stamp(AT))
            self.assertTrue(
                any(Fraction(r.get("raw", {}).get("net_ev") or "0") > 0 for r in rows)
            )
            self.assertTrue(
                any(Fraction(r.get("raw", {}).get("net_ev") or "0") < 0 for r in rows)
            )
            self.assertTrue(any(r["venue"] == "fanduel" for r in rows))
            self.assertEqual(rows, monitor._quote_rows(LegacyRead(db), stamp(AT)))
            # A valid price stays inspectable without a qualified EV model.
            target = db.execute(
                "SELECT contract_id,payload FROM current_pregame_price ORDER BY contract_id LIMIT 1"
            ).fetchone()
            db.execute(
                "DELETE FROM current_pregame_calculation WHERE contract_id=%s",
                (target["contract_id"],),
            )
            projected = monitor._quote_rows(db, stamp(AT))
            self.assertEqual(projected, monitor._quote_rows(LegacyRead(db), stamp(AT)))
            retained = next(r for r in projected if r["id"] == target["payload"]["id"])
            self.assertIsNone(retained.get("reference"))
            self.assertEqual(retained["posted"], target["payload"]["posted"])
            self.assertEqual(retained["times"], target["payload"]["times"])

    async def test_source_withdrawal_and_expired_line_preserve_real_journal_history(
        self,
    ):
        from app.dashboard.bet_journal import Journal as DurableJournal

        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            # Link the same aggregate revisions as ordinary source ingress; the
            # retained calculation deliberately remains present after withdrawal.
            db.execute("""UPDATE current_offer_storage o SET sgo_quote_id=q.id,sgo_quote_revision=q.revision,
                price_value=NULL,facts=o.facts#-'{original,value}'
                FROM sgo_quote_revision q,current_contract c
                WHERE c.id=o.contract_id AND q.is_current AND q.bookmaker_id=c.venue
                  AND q.facts->>'odd_id'=c.native_outcome_id
                  AND q.facts->>'line'=o.facts#>>'{source,native_line}'""")
            target = db.execute("""SELECT p.contract_id,p.payload,o.sgo_quote_id
                FROM current_pregame_price p JOIN current_offer_storage o USING(contract_id)
                WHERE o.sgo_quote_id IS NOT NULL AND p.payload->>'side'='home'
                ORDER BY p.contract_id LIMIT 1""").fetchone()
            self.assertIsNotNone(target)
        with TemporaryDirectory(prefix="predict-journal-withdrawal-") as folder:
            journal = DurableJournal(Path(folder) / "journal.sqlite3")
            first = monitor.sample(
                journal=journal, connector=self.connect, at=AT, include_arbs=False
            )
            self.assertGreater(first["ev"], 0)
            prior = journal_history(journal)
            self.assertTrue(prior["entries"] and prior["events"] and prior["quotes"])
            for kind in ("unavailable", "expired"):
                with self.subTest(kind=kind), self.connect() as db:
                    if kind == "unavailable":
                        db.execute(
                            "UPDATE current_offer_storage SET facts=jsonb_set(facts,'{state}','\"unavailable\"'::jsonb) WHERE contract_id=%s",
                            (target["contract_id"],),
                        )
                    else:
                        db.execute(
                            "UPDATE current_offer_storage SET facts=jsonb_set(facts,'{state}','\"available\"'::jsonb) WHERE contract_id=%s",
                            (target["contract_id"],),
                        )
                        expire_line(db, target["sgo_quote_id"])
                    rows = monitor._quote_rows(db, stamp(AT))
                    self.assertNotIn(target["payload"]["id"], {r["id"] for r in rows})
                    self.assertIsNotNone(
                        db.execute(
                            "SELECT contract_id FROM current_pregame_price WHERE contract_id=%s",
                            (target["contract_id"],),
                        ).fetchone()
                    )
                monitor.sample(
                    journal=journal, connector=self.connect, at=AT, include_arbs=False
                )
                after = journal_history(journal)
                for table, evidence in prior.items():
                    self.assertLessEqual(evidence, after[table], table)

    async def test_reference_withdrawal_revokes_ev_but_retains_valid_price(self):
        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            original = next(
                r
                for r in monitor._quote_rows(db, stamp(AT))
                if r["venue"] == "prophetx"
                and r.get("reference")
                and Fraction(r["raw"]["net_ev"]) > 0
            )
            reference_id = original["reference"]["prices"][0]["input_id"]
            for kind in ("unavailable", "expired"):
                with self.subTest(kind=kind):
                    db.execute(
                        "UPDATE sgo_quote_revision SET facts=jsonb_set(facts,'{available}',%s::jsonb) WHERE id=%s AND is_current",
                        ("false" if kind == "unavailable" else "true", reference_id),
                    )
                    if kind == "expired":
                        expire_line(db, reference_id)
                    # Ordinary reference ingress queues the owner; pending work
                    # correctly withholds all admission until it commits.
                    self.process(db)
                    packet = monitor._read(db, stamp(AT), include_arbs=False)
                    retained = next(
                        r for r in packet["quotes"] if r["id"] == original["id"]
                    )
                    self.assertIsNone(retained.get("reference"))
                    self.assertNotIn(original["id"], {r["id"] for r in packet["ev"]})
                    for field in ("posted", "times", "fee"):
                        self.assertEqual(retained[field], original[field], field)

    async def test_only_matching_pending_reference_work_withholds_prices(self):
        with self.connect() as db:
            self.ingest(db, page())
            self.process(db)
            db.execute("""UPDATE current_pregame_price SET payload=jsonb_set(payload,
                '{sportsbook_event_ids}','["other-reference","pending-reference","pending-reference"]'::jsonb)""")
            baseline = monitor._quote_rows(db, stamp(AT))
            self.assertTrue(baseline)
            for provider, event in (
                ("sportsgameodds", "unrelated-reference"),
                ("other-provider", "pending-reference"),
            ):
                db.execute(
                    "INSERT INTO current_pregame_work(provider,native_event_id) VALUES(%s,%s)",
                    (provider, event),
                )
            self.assertEqual(monitor._quote_rows(db, stamp(AT)), baseline)
            db.execute(
                "INSERT INTO current_pregame_work(provider,native_event_id) VALUES('sportsgameodds','pending-reference')"
            )
            waiting = monitor._read(db, stamp(AT), include_arbs=False)
            self.assertEqual(waiting["quotes"], [])
            self.assertEqual(waiting["ev"], [])
            db.execute(
                "DELETE FROM current_pregame_work WHERE provider='sportsgameodds' AND native_event_id='pending-reference'"
            )
            self.assertEqual(monitor._quote_rows(db, stamp(AT)), baseline)
