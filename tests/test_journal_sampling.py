"""Web and collector share successful captures without overlapping journal scans."""

from datetime import timedelta
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from unittest import TestCase
from unittest.mock import patch

from app.dashboard import bet_journal_monitor as monitor
from app.dashboard.bet_journal import Journal
from app.dashboard.journal_sampling import sampling_lease
from tests.test_bet_journal_monitor import Database, NOW


class SharedJournalSampling(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "journal.sqlite3"
        self.journals = [Journal(self.path), Journal(self.path)]
        self.elapsed = 0
        self.owners = [monitor.Monitor(timer=lambda: self.elapsed) for _ in range(2)]
        self.db = Database(revision=1)
        self.calls = []

        def capture(*, journal, include_arbs, **kwargs):
            self.calls.append(include_arbs)
            journal.status(capture_succeeded=True)
            return dict(revision=self.db.revision)

        self.capture = capture

    def poll(self, owner, *, journal=None):
        return self.owners[owner].poll(
            journal=journal or self.journals[owner],
            connector=lambda: self.db,
            at=NOW + timedelta(seconds=self.elapsed),
        )

    def test_two_owners_share_revision_and_fifteen_second_expiry(self):
        self.journals[0].status(unrelated="preserved")
        with patch.object(monitor, "sample", side_effect=self.capture):
            self.assertIsNotNone(self.poll(0))
            self.assertIsNone(self.poll(1))
            self.elapsed = 1
            self.db.revision = 2
            self.assertIsNotNone(self.poll(1))
            self.assertIsNone(self.poll(0))
            self.elapsed = 14
            self.assertIsNone(self.poll(0))
            self.elapsed = 15
            self.assertIsNotNone(self.poll(1))
            self.assertIsNone(self.poll(0))
        self.assertEqual(self.calls, [True, False, True])
        state = self.journals[0].status()
        self.assertEqual(state["unrelated"], "preserved")
        self.assertTrue(state["capture_succeeded"])
        self.assertEqual(state["sampling_gate"]["revision"], 2)
        self.assertTrue(
            all(
                query.startswith(("SET TRANSACTION READ ONLY", "SELECT"))
                for query, _ in self.db.queries
            )
        )

    def test_new_source_or_journal_cannot_reuse_another_success_gate(self):
        with patch.object(monitor, "sample", side_effect=self.capture):
            self.poll(0)
            self.db.info.dbname = "other-source"
            self.assertIsNotNone(self.poll(1))
            self.elapsed = 1
            self.assertIsNotNone(
                self.poll(0, journal=Journal(self.path.with_name("other.sqlite3")))
            )
        self.assertEqual(self.calls, [True, True, True])

    def test_active_sample_excludes_other_owner_then_success_suppresses_repeat(self):
        entered, release = Event(), Event()
        results = []

        def blocked_capture(**kwargs):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test sample was not released")
            return self.capture(**kwargs)

        with patch.object(monitor, "sample", side_effect=blocked_capture):
            worker = Thread(target=lambda: results.append(self.poll(0)))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertIsNone(self.poll(1))
                self.assertEqual(self.calls, [])
            finally:
                release.set()
                worker.join(2)
            self.assertFalse(worker.is_alive())
            self.elapsed = 1
            self.assertIsNone(self.poll(1))
        self.assertEqual(results, [dict(revision=1)])
        self.assertEqual(self.calls, [True])

    def test_lease_is_nonblocking_across_processes_and_releases_on_exception(self):
        code = (
            "import sys; from app.dashboard.bet_journal import Journal; "
            "from app.dashboard.journal_sampling import sampling_lease; "
            "lease=sampling_lease(Journal(sys.argv[1])); print(lease.__enter__()); "
            "lease.__exit__(None,None,None)"
        )
        with self.assertRaisesRegex(RuntimeError, "failure"):
            with sampling_lease(self.journals[0]) as acquired:
                self.assertTrue(acquired)
                child = subprocess.run(
                    [sys.executable, "-c", code, str(self.path)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(child.stdout.strip(), "False")
                raise RuntimeError("failure")
        with sampling_lease(self.journals[1]) as acquired:
            self.assertTrue(acquired)

    def test_failure_preserves_gate_and_other_owner_can_retry(self):
        with patch.object(monitor, "sample", side_effect=self.capture):
            self.poll(0)
        gate = self.journals[0].status()["sampling_gate"]
        self.elapsed = 15
        with patch.object(monitor, "sample", side_effect=RuntimeError("source failed")):
            self.assertIsNone(self.poll(1))
        self.assertEqual(self.journals[0].status()["sampling_gate"], gate)
        with patch.object(monitor, "sample", side_effect=self.capture):
            self.assertIsNotNone(self.poll(0))
        self.assertEqual(self.calls, [True, True])

    def test_error_publication_retains_lease_until_other_owner_can_retry(self):
        original_status = self.journals[0].status
        attempts, during_error = [], []

        def capture(**kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("source failed")
            kwargs["journal"].status(monitor_state="running", monitor_error=None)
            return dict(revision=self.db.revision)

        def publish_status(**fields):
            if fields.get("monitor_state") == "error":
                during_error.append(self.poll(1))
            return original_status(**fields)

        with (
            patch.object(monitor, "sample", side_effect=capture),
            patch.object(self.journals[0], "status", side_effect=publish_status),
        ):
            self.assertIsNone(self.poll(0))
            self.assertEqual(during_error, [None])
            self.assertEqual(len(attempts), 1)
            self.assertEqual(original_status()["monitor_state"], "error")
            self.elapsed = 1
            self.assertIsNotNone(self.poll(1))
        state = original_status()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(state["monitor_state"], "running")
        self.assertIsNone(state["monitor_error"])
        self.assertEqual(state["sampling_gate"]["revision"], self.db.revision)

    def test_future_or_malformed_shared_clock_samples_conservatively(self):
        with patch.object(monitor, "sample", side_effect=self.capture):
            self.poll(0)
            good = self.journals[0].status()["sampling_gate"]
            for bad in (
                None,
                {},
                dict(good, arb_at="invalid"),
                dict(good, arb_at=(NOW + timedelta(days=1)).isoformat()),
                dict(good, revision=True),
            ):
                with self.subTest(gate=bad):
                    self.elapsed += 1
                    self.journals[0].status(sampling_gate=bad)
                    self.assertIsNotNone(self.poll(1))
        self.assertEqual(self.calls, [True] * 6)

    def test_local_clock_rollback_does_not_suppress_changed_source(self):
        self.elapsed = 100
        with patch.object(monitor, "sample", side_effect=self.capture):
            self.poll(0)
            self.elapsed = 90
            self.db.revision = 2
            self.assertIsNotNone(self.poll(0))
        self.assertEqual(self.calls, [True, True])
