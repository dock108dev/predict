"""Disposable PostgreSQL to durable personal journal integration."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless

from app.dashboard import bet_journal_monitor as monitor
from app.storage.store import stamp
from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import AT, PregameFixture, page
from tests.test_bet_journal_monitor import Journal


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
