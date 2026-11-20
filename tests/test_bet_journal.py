"""Personal history survives corrections and changing source snapshots."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from tempfile import TemporaryDirectory
from pathlib import Path
from fractions import Fraction
from unittest import TestCase
from unittest.mock import patch, Mock

from app.dashboard.bet_journal import Journal, Conflict, digest
from browser_tests.test_pregame_current import offer


class PersonalJournal(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "personal/bets.sqlite3"
        self.journal = Journal(self.path)
        self.row = offer()

    def state(self, **fields):
        return dict(revision=1, decision="saved", notes="", trade=None, **fields)

    def test_permission_failure_closes_the_opened_connection(self):
        connection = Mock()
        with (
            patch("sqlite3.connect", return_value=connection),
            patch("os.chmod", side_effect=PermissionError("fixture permissions")),
        ):
            with self.assertRaises(PermissionError):
                self.journal.status()
        connection.close.assert_called_once()

    def test_original_and_corrections_survive_reopen_and_source_socket_change(self):
        original = deepcopy(self.row)
        key = self.journal.observe("ev", self.row, manual=True)
        self.row["posted"]["value"] = "+105"
        self.journal.update(
            key, dict(revision=1, decision="passed", notes="Price moved", trade=None)
        )
        with patch.dict("os.environ", PREDICT_DB_SOCKET="/nonexistent/new-snapshot"):
            record = Journal(self.path).get(key, history=True)
        self.assertEqual(record["entry"]["snapshot"], original)
        self.assertEqual(record["entry"]["decision"], "passed")
        self.assertEqual([event["revision"] for event in record["history"]], [1, 2])
        self.assertEqual(record["history"][0]["decision"], "saved")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_duplicate_observations_and_manual_snapshots_have_distinct_intent(self):
        key = self.journal.observe("ev", self.row)
        changed = deepcopy(self.row)
        changed["posted"]["value"] = "+110"
        self.assertEqual(key, self.journal.observe("ev", changed))
        saved = self.journal.observe("ev", changed, manual=True)
        self.assertNotEqual(saved, key)
        self.assertEqual(saved, self.journal.observe("ev", changed, manual=True))
        packet = self.journal.list()
        self.assertEqual(packet["total"], 2)
        self.assertEqual(packet["summary"]["counts"], dict(observed=1, saved=1))

    def test_stale_tab_cannot_overwrite_a_correction(self):
        key = self.journal.observe("ev", self.row, manual=True)
        self.journal.update(key, dict(revision=1, notes="First correction"))
        with self.assertRaises(Conflict):
            self.journal.update(key, dict(revision=1, notes="Old tab"))
        self.assertEqual(self.journal.get(key)["entry"]["notes"], "First correction")

    def test_manual_save_ignores_ranking_view_but_keeps_material_quote_changes(self):
        self.row["ranking"] = dict(method="growth", value="1.234")
        key = self.journal.observe("ev", self.row, manual=True)
        other = dict(deepcopy(self.row), ranking=dict(method="ev", value="8.80"))
        self.assertEqual(key, self.journal.observe("ev", other, manual=True))
        self.assertEqual(self.journal.get(key)["entry"]["snapshot"], self.row)
        other["posted"]["value"] = "+130"
        self.assertNotEqual(key, self.journal.observe("ev", other, manual=True))
        typed = deepcopy(self.row)
        typed["main"] = 1  # JSON number is not the original boolean.
        self.assertNotEqual(key, self.journal.observe("ev", typed, manual=True))

    def test_legacy_ranked_save_keeps_its_id_and_corrections(self):
        self.row["ranking"] = dict(method="growth", value="1.234")
        key = self.journal.observe("ev", self.row, manual=True)
        self.journal.update(key, dict(revision=1, notes="Keep this correction"))
        legacy = digest(["browser_snapshot", "ev", self.row])
        with self.journal.database() as db:
            db.execute("UPDATE entries SET id=? WHERE id=?", (legacy, key))
            db.execute("UPDATE events SET entry_id=? WHERE entry_id=?", (legacy, key))
        other = dict(deepcopy(self.row), ranking=dict(method="score", value="748"))
        self.assertEqual(legacy, self.journal.observe("ev", other, manual=True))
        record = self.journal.get(legacy, history=True)
        self.assertEqual(record["entry"]["revision"], 2)
        self.assertEqual(record["entry"]["notes"], "Keep this correction")
        self.assertEqual(len(record["history"]), 2)

    def test_actual_price_fee_and_net_return_case(self):
        source = (datetime.now(timezone.utc) - timedelta(minutes=4)).isoformat()
        self.row["times"] = dict(source_at=source, received_at=source)
        for quote in self.row["reference"]["prices"]:
            quote["source_at"] = source
        key = self.journal.observe(
            "ev",
            self.row,
            manual=True,
            at=datetime.now(timezone.utc) - timedelta(minutes=3),
        )
        placed = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        settled = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        trade = dict(
            placed_at=placed,
            legs=[
                dict(
                    quote_id=self.row["id"],
                    stake="50",
                    price="+110",
                    units="american_odds",
                    entry_fee="1",
                    win_fee="2",
                    loss_fee="0",
                )
            ],
        )
        entry = self.journal.update(
            key, dict(revision=1, decision="placed", trade=trade)
        )["entry"]
        self.assertEqual(entry["metrics"]["entry_cost_usd"], "51")
        # +110 at $50 returns $105, less $2 win charge; 50% reference.
        self.assertEqual(Fraction(entry["metrics"]["entry_ev_usd"]), Fraction(1, 2))
        trade["result"] = dict(
            receipts_usd=["103"], settled_at=settled, notes="Net cash reported"
        )
        entry = self.journal.update(
            key, dict(revision=2, decision="placed", trade=trade)
        )["entry"]
        self.assertEqual(entry["metrics"]["realized_profit_usd"], "52")
        self.assertEqual(entry["snapshot"]["posted"]["value"], "+120")
        trade["result"]["receipts_usd"] = ["-1"]
        entry = self.journal.update(
            key, dict(revision=3, decision="placed", trade=trade)
        )["entry"]
        self.assertEqual(entry["metrics"]["realized_profit_usd"], "-52")

    def test_unknown_fees_and_wrong_leg_cannot_be_recorded_as_placed(self):
        key = self.journal.observe("ev", self.row, manual=True)
        leg = dict(
            quote_id=self.row["id"],
            stake="50",
            price="+110",
            units="american_odds",
            entry_fee="",
            win_fee="0",
            loss_fee="0",
        )
        trade = dict(legs=[leg], placed_at=datetime.now(timezone.utc).isoformat())
        with self.assertRaisesRegex(ValueError, "explicit fees"):
            self.journal.update(key, dict(revision=1, decision="placed", trade=trade))
        leg.update(entry_fee="0", quote_id="another-selection")
        with self.assertRaisesRegex(ValueError, "original selections"):
            self.journal.update(key, dict(revision=1, decision="placed", trade=trade))

    def test_outcome_corrections_recalculate_and_keep_history_and_legacy_results(self):
        row = deepcopy(self.row)
        row.update(venue="prophetx", posted=dict(value="+495", units="american_odds"))
        row["raw"]["posted_decimal"] = "5.95"
        row["raw"]["after_fee_decimal"] = "5.851"
        row["fee"]["evidence"] = dict(
            database_fee_rule=dict(formula="prophetx_commission", rate="0.02")
        )
        key = self.journal.observe("ev", row, manual=True)
        trade = dict(
            automatic=True,
            legs=[dict(quote_id=row["id"], stake="100")],
            result=dict(outcomes=["win"]),
        )
        first = self.journal.update(
            key, dict(revision=1, decision="placed", trade=trade)
        )["entry"]
        self.assertEqual(first["trade"]["legs"][0]["price"], "495")
        self.assertEqual(first["trade"]["legs"][0]["win_fee"], "9.9")
        self.assertEqual(first["metrics"]["realized_profit_usd"], "485.1")
        self.assertNotIn("receipts_usd", first["trade"]["result"])
        edited = dict(
            automatic=True,
            legs=[
                dict(
                    quote_id=row["id"], stake="200", price="+100", units="american_odds"
                )
            ],
        )
        second = self.journal.update(key, dict(revision=2, trade=edited))["entry"]
        self.assertEqual(second["trade"]["result"], first["trade"]["result"])
        self.assertEqual(second["metrics"]["realized_profit_usd"], "196")
        edited["result"] = dict(outcomes=["loss"])
        third = self.journal.update(key, dict(revision=3, trade=edited))["entry"]
        self.assertEqual(third["metrics"]["realized_profit_usd"], "-200")
        edited["result"] = dict(receipts_usd=["203"])
        fourth = self.journal.update(key, dict(revision=4, trade=edited))["entry"]
        self.assertEqual(fourth["metrics"]["realized_profit_usd"], "3")
        with self.assertRaises(Conflict):
            self.journal.update(key, dict(revision=4, trade=edited))
        reopened = Journal(self.path).get(key, history=True)
        self.assertEqual(len(reopened["history"]), 5)
        self.assertEqual(reopened["history"][1]["trade"]["result"]["outcomes"], ["win"])
        self.assertEqual(reopened["entry"]["snapshot"], row)

    def test_outcome_report_rejects_ambiguous_or_incomplete_leg_results(self):
        key = self.journal.observe("ev", self.row, manual=True)
        for result in (
            dict(outcomes=[]),
            dict(outcomes=["tie"]),
            dict(outcomes=[True]),
            dict(outcomes=["win"], receipts_usd=["0"]),
        ):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.journal.update(
                    key,
                    dict(
                        revision=1,
                        decision="placed",
                        trade=dict(
                            automatic=True,
                            legs=[dict(quote_id=self.row["id"], stake="100")],
                            result=result,
                        ),
                    ),
                )
        self.assertEqual(self.journal.get(key)["entry"]["revision"], 1)

    def test_saved_entry_charge_survives_win_loss_push_and_explicit_refund(self):
        row = deepcopy(self.row)
        row.update(venue="prophetx", posted=dict(value="+109", units="american_odds"))
        row["raw"]["posted_decimal"] = "2.09"
        row["fee"]["evidence"] = dict(
            database_fee_rule=dict(formula="prophetx_nhl_taker", rate="0.035")
        )
        key = self.journal.observe("ev", row, manual=True)
        trade = dict(automatic=True, legs=[dict(quote_id=row["id"], stake="100")])
        for revision, outcome, receipt, profit in (
            (1, "win", "209", "107.17"),
            (2, "loss", "0", "-101.83"),
            (3, "push", "100", "-1.83"),
        ):
            with self.subTest(outcome=outcome):
                trade["result"] = dict(outcomes=[outcome])
                saved = self.journal.update(
                    key, dict(revision=revision, decision="placed", trade=trade)
                )["entry"]
                self.assertEqual(saved["trade"]["legs"][0]["entry_fee"], "1.83")
                self.assertEqual(
                    saved["metrics"]["settlement"]["receipts_usd"], [receipt]
                )
                self.assertEqual(saved["metrics"]["realized_profit_usd"], profit)
        # A reported adjustment is authority for refunded entry charges; an
        # ordinary push cannot silently invent that additional cash credit.
        trade["result"] = dict(receipts_usd=["101.83"])
        refund = self.journal.update(key, dict(revision=4, trade=trade))["entry"]
        self.assertEqual(refund["metrics"]["realized_profit_usd"], "0")
        self.assertEqual(refund["metrics"]["settlement"]["basis"], "reported_receipts")

    def test_known_loss_cost_enters_summary_even_when_unused_win_fee_is_unknown(self):
        key = self.journal.observe("ev", self.row, manual=True)
        now = datetime.now(timezone.utc)
        trade = dict(
            legs=[
                dict(
                    quote_id=self.row["id"],
                    stake="50",
                    price="+110",
                    units="american_odds",
                    entry_fee="1",
                    win_fee=None,
                    loss_fee="1",
                    fee_basis="unavailable",
                )
            ],
            placed_at=(now - timedelta(seconds=1)).isoformat(),
            result=dict(outcomes=["loss"], settled_at=now.isoformat()),
        )
        self.journal.update(key, dict(revision=1, decision="placed", trade=trade))
        summary = self.journal.list()["summary"]
        self.assertEqual(summary["realized_profit_usd"], "-52")
        self.assertEqual(summary["settled_cost_usd"], "51")

    def test_last_quote_not_renewed_by_polling_and_postkickoff_is_rejected(self):
        kickoff = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.row["kickoff"] = kickoff.isoformat()
        at = kickoff - timedelta(minutes=4)
        self.row["times"] = dict(source_at=at.isoformat(), received_at=at.isoformat())
        self.journal.observe("ev", self.row, at=at)
        self.assertEqual(self.journal.quotes([self.row], at=at), 1)
        self.assertEqual(
            self.journal.quotes([self.row], at=at + timedelta(seconds=30)), 0
        )
        changed = deepcopy(self.row)
        changed["posted"]["value"] = "+100"
        self.assertEqual(self.journal.quotes([changed], at=kickoff), 0)
        with self.journal.database() as db:
            quote = db.execute("SELECT * FROM quotes").fetchone()
            self.assertEqual(quote["observed_at"], at.isoformat())
            self.assertEqual(json.loads(quote["payload"])["posted"]["value"], "+120")

    def test_parallel_creates_are_idempotent(self):
        # Warm schema before racing independent web/collector connections.
        self.journal.status()
        with ThreadPoolExecutor(max_workers=4) as pool:
            keys = list(
                pool.map(lambda _: self.journal.observe("ev", self.row), range(12))
            )
        self.assertEqual(len(set(keys)), 1)
        self.assertEqual(self.journal.list()["total"], 1)

    def test_parallel_manual_ranking_views_save_one_quote(self):
        self.journal.status()

        def save(index):
            row = dict(
                deepcopy(self.row),
                ranking=dict(method="growth" if index % 2 else "ev", value=str(index)),
            )
            return self.journal.observe("ev", row, manual=True)

        with ThreadPoolExecutor(max_workers=4) as pool:
            keys = list(pool.map(save, range(12)))
        self.assertEqual(len(set(keys)), 1)
        self.assertEqual(self.journal.list()["total"], 1)

    def test_failed_batch_and_failed_correction_roll_back_records_and_history(self):
        invalid = deepcopy(self.row)
        invalid.pop("id")
        with self.assertRaises(ValueError):
            self.journal.capture([self.row, invalid], [], [])
        self.assertEqual(self.journal.list()["total"], 0)
        key = self.journal.observe("ev", self.row, manual=True)
        with patch.object(
            self.journal,
            "_metrics",
            side_effect=RuntimeError("injected metrics failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected metrics"):
                self.journal.update(key, dict(revision=1, notes="Must roll back"))
        record = self.journal.get(key, history=True)
        self.assertEqual(record["entry"]["revision"], 1)
        self.assertEqual(record["entry"]["notes"], "")
        self.assertEqual(len(record["history"]), 1)
        self.assertEqual(
            self.journal.update(key, dict(revision=1, notes="Retry succeeds"))["entry"][
                "revision"
            ],
            2,
        )

    def test_sqlite_backup_restores_committed_wal_and_corrections(self):
        import sqlite3

        self.journal.status()
        keeper = sqlite3.connect(self.path)
        self.addCleanup(keeper.close)
        keeper.execute("PRAGMA journal_mode=WAL").fetchone()
        keeper.execute("SELECT count(*) FROM entries").fetchone()
        keeper.execute("PRAGMA wal_autocheckpoint=0")
        key = self.journal.observe("ev", self.row, manual=True)
        self.journal.update(key, dict(revision=1, notes="Retained correction"))
        self.assertEqual(self.journal.quotes([self.row]), 1)
        self.assertGreater(Path(str(self.path) + "-wal").stat().st_size, 0)
        destination = Path(self.directory.name) / "restored.sqlite3"
        with sqlite3.connect(destination) as restored:
            keeper.backup(restored)
        self.assertEqual(
            self.journal.get(key, history=True),
            Journal(destination).get(key, history=True),
        )

    def test_equivalent_kickoff_offsets_retain_the_same_quote_identity(self):
        row = deepcopy(self.row)
        row["kickoff"] = "2026-11-19T00:00:00Z"
        at = "2026-11-18T15:00:00Z"
        row["times"] = dict(source_at=at, received_at=at)
        key = self.journal.observe("ev", row, at=at)
        later = deepcopy(row)
        later["kickoff"] = "2026-11-18T19:00:00-05:00"
        later["posted"]["value"] = "+110"
        self.assertEqual(Journal.identity(row), Journal.identity(later))
        self.journal.quotes([later], at=at)
        self.assertEqual(
            self.journal.get(key, history=True)["quotes"][0]["posted"]["value"], "+110"
        )

    def test_deleted_automatic_opportunity_stays_deleted_and_manual_save_is_allowed(
        self,
    ):
        key = self.journal.observe("ev", self.row)
        saved = self.journal.observe("ev", self.row, manual=True)
        self.journal.delete(key, 1)
        self.journal.capture([self.row], [], [self.row])
        self.assertEqual([e["id"] for e in self.journal.list()["entries"]], [saved])
        self.assertEqual(self.journal.get(saved)["entry"]["snapshot"], self.row)
        self.assertEqual(self.journal.observe("ev", self.row, manual=True), saved)

    def test_failed_delete_rolls_back_the_record_and_its_corrections(self):
        import sqlite3

        key = self.journal.observe("ev", self.row, manual=True)
        self.journal.update(key, dict(revision=1, notes="Keep my correction"))
        with self.journal.database(write=True) as db:
            db.execute("""CREATE TRIGGER failed_delete BEFORE DELETE ON entries
                BEGIN SELECT RAISE(ABORT, 'authored delete failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.journal.delete(key, 2)
        record = self.journal.get(key, history=True)
        self.assertEqual(record["entry"]["notes"], "Keep my correction")
        self.assertEqual([e["revision"] for e in record["history"]], [1, 2])
        with self.journal.database() as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM deleted_entries").fetchone()[0], 0
            )

    def test_stake_only_note_correction_keeps_explicit_actual_fees(self):
        key = self.journal.observe("ev", self.row, manual=True)
        actual = dict(
            quote_id=self.row["id"],
            stake="100",
            price="+120",
            units="american_odds",
            entry_fee="0.37",
            win_fee="1.11",
            loss_fee="0",
        )
        first = self.journal.update(
            key,
            dict(
                revision=1,
                decision="placed",
                trade=dict(legs=[actual], placed_at=self.row["times"]["received_at"]),
            ),
        )
        changed = self.journal.update(
            key,
            dict(
                revision=2,
                notes="Keep my actual fees",
                trade=dict(
                    automatic=True,
                    legs=[
                        dict(
                            quote_id=self.row["id"],
                            stake="100.00",
                            price="120",
                            units="american_odds",
                        )
                    ],
                ),
            ),
        )
        self.assertEqual(
            changed["entry"]["trade"]["placed_at"], first["entry"]["trade"]["placed_at"]
        )
        for field in ("entry_fee", "win_fee", "loss_fee"):
            self.assertEqual(changed["entry"]["trade"]["legs"][0][field], actual[field])
