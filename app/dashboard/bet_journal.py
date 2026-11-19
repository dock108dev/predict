"""Durable personal decisions, corrections and pregame quotes, outside source snapshots."""

from contextlib import contextmanager
from datetime import datetime, timezone
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[2]


def clock():
    return datetime.now(timezone.utc).isoformat()


def instant(value):
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if parsed.utcoffset() is None:
        raise ValueError("A timestamp with a timezone is required")
    return parsed


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(encoded(value).encode()).hexdigest()


class Conflict(ValueError):
    pass


def legs(snapshot, kind):
    return snapshot["legs"] if kind == "arb" else [snapshot]


def validate_snapshot(kind, snapshot):
    if kind not in ("ev", "arb") or not isinstance(snapshot, dict):
        raise ValueError("Choose an EV opportunity or arbitrage pair")
    if not snapshot.get("id") or not snapshot.get("kickoff"):
        raise ValueError("The original opportunity identity and kickoff are required")
    if kind == "arb" and (
        not isinstance(snapshot.get("legs"), list) or len(snapshot["legs"]) != 2
    ):
        raise ValueError("An arbitrage record needs both legs")
    for row in legs(snapshot, kind):
        if not isinstance(row, dict) or any(
            not isinstance(row.get(key), dict)
            for key in ("selection", "posted", "times")
        ):
            raise ValueError("The original quote is incomplete")
        for key in (
            "id",
            "game_key",
            "kickoff",
            "venue",
            "selection",
            "posted",
            "times",
        ):
            if not row.get(key):
                raise ValueError("The original quote is incomplete")
        instant(row["kickoff"])
        instant(row["times"]["received_at"])
    if len(encoded(snapshot)) > 200_000:
        raise ValueError("The opportunity snapshot is too large")


def number(value, *, positive=False, probability=False, signed=False):
    if isinstance(value, bool) or value is None or len(str(value)) > 100:
        raise ValueError("Enter finite numbers for prices, amounts and fees")
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        raise ValueError("Enter finite numbers for prices, amounts and fees") from None
    if abs(result) > 1_000_000_000 or (
        not signed and (result <= 0 if positive else result < 0)
    ):
        raise ValueError("Amounts must be positive and fees cannot be negative")
    if probability and result >= 1:
        raise ValueError("Contract prices must be between 0 and 1")
    return result


def validate_trade(trade, entry, decision):
    if trade is None:
        if decision == "placed":
            raise ValueError("Enter the actual trade before marking it placed")
        return
    if not isinstance(trade, dict) or set(trade) - {"legs", "placed_at", "result"}:
        raise ValueError("Unknown trade fields")
    rows = trade.get("legs", [])
    original = legs(entry["snapshot"], entry["kind"])
    if not isinstance(rows, list) or len(rows) != len(original):
        raise ValueError("Record the price and cashflows for every original leg")
    for actual, quoted in zip(rows, original):
        if not isinstance(actual, dict) or set(actual) - {
            "quote_id",
            "stake",
            "price",
            "units",
            "entry_fee",
            "win_fee",
            "loss_fee",
            "fee_basis",
        }:
            raise ValueError("Unknown trade leg fields")
        if actual.get("quote_id") != quoted["id"]:
            raise ValueError("The trade must retain its original selections and venues")
        for key in ("stake", "price", "units", "entry_fee", "win_fee", "loss_fee"):
            value = actual.get(key)
            if value in (None, ""):
                if decision == "placed" and not (
                    key in ("entry_fee", "win_fee", "loss_fee")
                    and actual.get("fee_basis") == "unavailable"
                ):
                    raise ValueError(
                        "Placed trades need actual prices, stakes and explicit fees"
                    )
                continue
            if key == "units":
                if value not in ("american_odds", "probability"):
                    raise ValueError(
                        "Use American odds or a contract price between 0 and 1"
                    )
            elif key == "price":
                if actual.get("units") == "american_odds":
                    try:
                        price = Fraction(str(value))
                    except (ValueError, ZeroDivisionError):
                        raise ValueError("Invalid American odds") from None
                    if not 100 <= abs(price) <= 1_000_000:
                        raise ValueError(
                            "American odds must be at least +100 or at most -100"
                        )
                else:
                    number(value, positive=True, probability=True)
            else:
                number(value, positive=key == "stake")
    placed_at = trade.get("placed_at")
    if decision == "placed" and not placed_at:
        raise ValueError("Record when the trade was placed")
    if placed_at:
        if instant(placed_at) > instant(clock()):
            raise ValueError("Placement cannot be in the future")
    result = trade.get("result")
    if result is not None:
        if (
            decision != "placed"
            or not isinstance(result, dict)
            or set(result) - {"receipts_usd", "settled_at", "notes"}
        ):
            raise ValueError("Results belong to placed trades")
        receipts = result.get("receipts_usd")
        if not isinstance(receipts, list) or len(receipts) != len(original):
            raise ValueError("Record net returned cash for each leg")
        for receipt in receipts:
            number(receipt, signed=True)
        if not result.get("settled_at"):
            raise ValueError("Record the settlement time")
        settled = instant(result["settled_at"])
        if not placed_at or not instant(placed_at) <= settled <= instant(clock()):
            raise ValueError(
                "Settlement must follow placement and cannot be in the future"
            )
        if len(str(result.get("notes", ""))) > 4000:
            raise ValueError("Result notes are limited to 4000 characters")


def automatic_trade(trade, entry, decision):
    """Resolve a stake-only report using its frozen book price and fee terms."""
    if not isinstance(trade, dict) or trade.get("automatic") is not True:
        return trade
    if set(trade) - {"automatic", "legs", "placed_at", "result"}:
        raise ValueError("Unknown trade fields")
    from .bet_journal_metrics import decimal_price, posted_decimal
    from app.comparison.cashflows import exact_wire
    from app.comparison.sportsbooks import SPORTSBOOKS
    from app.fees.engine import posted_fee

    originals = legs(entry["snapshot"], entry["kind"])
    reports = trade.get("legs")
    if not isinstance(reports, list) or len(reports) != len(originals):
        raise ValueError("Enter the stake for each leg")
    previous = entry.get("trade") or {}
    result = dict(
        legs=[], placed_at=trade.get("placed_at") or previous.get("placed_at")
    )
    if decision == "placed" and not result["placed_at"]:
        result["placed_at"] = clock()
    for i, (report, row) in enumerate(zip(reports, originals)):
        if not isinstance(report, dict) or set(report) - {
            "quote_id",
            "stake",
            "price",
            "units",
        }:
            raise ValueError("Supply the stake and optional actual odds for each leg")
        if report.get("quote_id") != row["id"]:
            raise ValueError("The trade must retain its original selections and venues")
        stake = number(report.get("stake"), positive=True)
        decimal = posted_decimal(row)
        units = (
            "probability"
            if row["venue"] in ("kalshi", "polymarket_us")
            else "american_odds"
        )
        price = (
            1 / decimal
            if units == "probability"
            else (100 * (decimal - 1) if decimal >= 2 else -100 / (decimal - 1))
        )
        if report.get("price") not in (None, ""):
            price, units = report["price"], report.get("units", units)
            number(price, signed=True)
            decimal = decimal_price(price, units)
        actual = dict(
            quote_id=row["id"], stake=exact_wire(stake), price=str(price), units=units
        )
        old = (previous.get("legs") or [])[i : i + 1]
        if old and (
            all(old[0].get(k) not in (None, "") for k in ("stake", "price", "units"))
            and old[0].get("quote_id") == row["id"]
            and Fraction(str(old[0].get("stake"))) == stake
            and decimal_price(old[0].get("price"), old[0].get("units")) == decimal
            and (
                old[0].get("fee_basis") == "unavailable"
                or all(
                    old[0].get(k) not in (None, "")
                    for k in ("entry_fee", "win_fee", "loss_fee")
                )
            )
        ):
            # Keep explicitly recorded charges when only notes/result change.
            actual.update(
                {
                    k: old[0].get(k)
                    for k in ("entry_fee", "win_fee", "loss_fee", "fee_basis")
                    if k in old[0]
                }
            )
        else:
            fee = row.get("fee") or {}
            rule = (fee.get("evidence") or {}).get("database_fee_rule")
            actual.update(
                entry_fee=None, win_fee=None, loss_fee=None, fee_basis="unavailable"
            )
            if rule:
                try:
                    entry_fee, winning, _ = posted_fee(
                        rule, price=1 / decimal, quantity=stake * decimal, stake=stake
                    )
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    # Older saved schedules can be incomplete or unsupported.
                    # Recording a stake still succeeds with unknown charges.
                    pass
                else:
                    actual.update(
                        entry_fee=exact_wire(entry_fee),
                        win_fee=exact_wire(winning),
                        loss_fee="0",
                        fee_basis="saved_book_schedule",
                    )
            elif row["venue"] in SPORTSBOOKS or (
                fee.get("classification") == "exact_public"
                and row["venue"] == "novig"
                and all(
                    Fraction(str(value)) == 0
                    for value in (
                        fee.get("entry_usd", "-1"),
                        fee.get("cashflows", {})
                        .get("win", {})
                        .get("total_fee_usd", "-1"),
                        fee.get("cashflows", {})
                        .get("loss", {})
                        .get("total_fee_usd", "-1"),
                    )
                )
            ):
                actual.update(
                    entry_fee="0",
                    win_fee="0",
                    loss_fee="0",
                    fee_basis="saved_book_schedule",
                )
        result["legs"].append(actual)
    if trade.get("result") is not None:
        result["result"] = dict(trade["result"])
        if not result["result"].get("settled_at"):
            result["result"]["settled_at"] = clock()
    return result


class Journal:
    def __init__(self, path=None):
        self.path = Path(
            path
            or os.environ.get("PREDICT_BET_JOURNAL_PATH")
            or ROOT / ".local/predict-personal/bets.sqlite3"
        )
        if not self.path.is_absolute():
            raise ValueError("The personal journal path must be absolute")

    @contextmanager
    def database(self, *, write=False):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(self.path, timeout=5)
        try:
            os.chmod(self.path, 0o600)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS entries (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, origin TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    decision TEXT NOT NULL, revision INTEGER NOT NULL,
                    snapshot TEXT NOT NULL, notes TEXT NOT NULL, trade TEXT
                );
                CREATE INDEX IF NOT EXISTS entries_created ON entries(created_at DESC, id);
                CREATE INDEX IF NOT EXISTS entries_kickoff ON entries(julianday(json_extract(snapshot,'$.kickoff')));
                CREATE TABLE IF NOT EXISTS events (
                    entry_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL, state TEXT NOT NULL,
                    PRIMARY KEY(entry_id, revision)
                );
                CREATE TABLE IF NOT EXISTS tracked (
                    quote_id TEXT PRIMARY KEY, identity TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tracked_identity ON tracked(identity);
                CREATE TABLE IF NOT EXISTS quotes (
                    quote_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    identity TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(quote_id, fingerprint)
                );
                CREATE INDEX IF NOT EXISTS quotes_identity ON quotes(identity, observed_at);
                CREATE TABLE IF NOT EXISTS monitor (singleton INTEGER PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS deleted_entries (id TEXT PRIMARY KEY);
            """)
            with db:
                # Pin reads to one WAL snapshot; writers reserve before any
                # read/modify/write step rather than upgrading a stale reader.
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield db
        finally:
            db.close()

    @staticmethod
    def identity(row):
        # Exact signed selection + occurrence + venue, including schedule changes.
        return digest(
            [
                row.get("game_key"),
                row.get("family"),
                row.get("period"),
                row.get("selection"),
                row["venue"],
                instant(row["kickoff"]).astimezone(timezone.utc).isoformat(),
            ]
        )

    @staticmethod
    def unpack(row):
        if row is None:
            raise KeyError("Unknown journal entry")
        value = dict(row)
        for key in ("snapshot", "trade"):
            value[key] = json.loads(value[key]) if value[key] else None
        return value

    def observe(self, kind, snapshot, *, at=None, manual=False):
        with self.database(write=True) as db:
            return self._observe(db, kind, snapshot, at=at, manual=manual)

    @staticmethod
    def _manual_snapshot(kind, snapshot):
        # Ranking is a read-time view of the same immutable quote, not another
        # trading decision. Retain the original snapshot, but omit it from keys.
        result = {key: value for key, value in snapshot.items() if key != "ranking"}
        if kind == "arb":
            result["legs"] = [
                {key: value for key, value in row.items() if key != "ranking"}
                for row in snapshot["legs"]
            ]
        return result

    def _observe(self, db, kind, snapshot, *, at=None, manual=False):
        validate_snapshot(kind, snapshot)
        at = instant(at or clock()).isoformat()
        origin = "browser_snapshot" if manual else "automatic"
        key = digest(
            [
                origin,
                kind,
                self._manual_snapshot(kind, snapshot)
                if manual
                else [self.identity(r) for r in legs(snapshot, kind)],
            ]
        )
        if (
            manual
            and not db.execute("SELECT 1 FROM entries WHERE id=?", (key,)).fetchone()
        ):
            canonical = encoded(self._manual_snapshot(kind, snapshot))
            # Keep IDs and corrections from saves made before ranking metadata
            # was excluded. Never rekey, merge or delete existing decisions.
            for prior in db.execute(
                """SELECT id,snapshot FROM entries WHERE origin='browser_snapshot'
                   AND kind=? AND json_extract(snapshot,'$.id')=? ORDER BY created_at,id""",
                (kind, snapshot["id"]),
            ):
                if (
                    encoded(self._manual_snapshot(kind, json.loads(prior["snapshot"])))
                    == canonical
                ):
                    key = prior["id"]
                    break
        decision = "saved" if manual else "observed"
        # Automatic discovery must not resurrect a deliberately deleted log row.
        # A new manual save is an explicit decision and remains allowed.
        if (
            not manual
            and db.execute(
                "SELECT 1 FROM deleted_entries WHERE id=?", (key,)
            ).fetchone()
        ):
            return key
        inserted = db.execute(
            "INSERT OR IGNORE INTO entries VALUES (?,?,?,?,?,?,?,?,?,?)",
            (key, kind, origin, at, at, decision, 1, encoded(snapshot), "", None),
        ).rowcount
        if inserted:
            db.execute(
                "INSERT INTO events VALUES (?,?,?,?)",
                (key, 1, at, encoded(dict(decision=decision, notes="", trade=None))),
            )
        for row in legs(snapshot, kind):
            db.execute(
                "INSERT OR IGNORE INTO tracked VALUES (?,?)",
                (row["id"], self.identity(row)),
            )
        return key

    def capture(self, ev, arbs, quotes, *, at=None):
        """One source sample has one SQLite transaction, independent of its size."""
        at = instant(at or clock()).isoformat()
        with self.database(write=True) as db:
            for kind, snapshots in (("ev", ev), ("arb", arbs)):
                for snapshot in snapshots:
                    self._observe(db, kind, snapshot, at=at)
            return sum(self._quote(db, row, at) for row in quotes)

    @staticmethod
    def compact_quote(row):
        # Keep the evidence used by comparisons, without repeating every native
        # reference's catalog/consensus metadata in every price observation.
        keys = (
            "id",
            "bet_id",
            "game_key",
            "game",
            "league",
            "kickoff",
            "family",
            "period",
            "selection",
            "selection_label",
            "venue",
            "side",
            "arb_key",
            "posted",
            "source",
            "times",
            "reference",
            "raw",
            "fee",
            "version",
            "calculated_at",
            "input_revision",
        )
        quote = {key: row[key] for key in keys if key in row}
        if row.get("journal_reference_only"):
            quote["journal_reference_only"] = True
        reference = row.get("reference")
        if reference:
            quote["reference"] = {
                key: reference[key]
                for key in (
                    "book",
                    "probability",
                    "market",
                    "conditioning",
                    "selected_outcome",
                    "selection_policy",
                    "candidate_probabilities",
                    "required_trusted_books",
                    "trusted_book_count",
                )
                if key in reference
            }
            for key in (
                "closing_basis",
                "target_line",
                "bound_line",
                "estimate_note",
                "alternate_lines",
                "probability_range",
                "estimated_posted_odds",
            ):
                if key in reference:
                    quote["reference"][key] = reference[key]
            quote["reference"]["prices"] = [
                {
                    key: price[key]
                    for key in (
                        "side",
                        "line",
                        "price_american",
                        "source_at",
                        "received_at",
                        "input_id",
                        "input_revision",
                    )
                    if key in price
                }
                for price in reference.get("prices", [])
            ]
        quote["_journal_basis"] = "source_comparison"
        return quote

    def _quote(self, db, row, at):
        identity = self.identity(row)
        tracked = db.execute(
            "SELECT 1 FROM tracked WHERE quote_id=? OR identity=? LIMIT 1",
            (row["id"], identity),
        ).fetchone()
        if not tracked:
            return 0
        # Receipt/knowledge after kickoff is never promoted into a closing observation.
        kickoff = instant(row["kickoff"])
        times = row["times"]
        received = instant(times["received_at"])
        source = instant(times.get("source_at") or times["received_at"])
        if not source <= received <= instant(at) < kickoff:
            return 0
        row = self.compact_quote(row)
        return db.execute(
            "INSERT OR IGNORE INTO quotes VALUES (?,?,?,?,?)",
            (row["id"], digest(row), identity, at, encoded(row)),
        ).rowcount

    def quotes(self, rows, *, at=None):
        at = instant(at or clock()).isoformat()
        with self.database(write=True) as db:
            return sum(self._quote(db, row, at) for row in rows)

    def targets(self, *, at):
        with self.database() as db:
            originals = {}
            for row in db.execute(
                "SELECT kind,snapshot FROM entries WHERE julianday(json_extract(snapshot,'$.kickoff'))>julianday(?)",
                (instant(at).isoformat(),),
            ):
                for leg in legs(json.loads(row["snapshot"]), row["kind"]):
                    if instant(leg["kickoff"]) > instant(at):
                        originals[leg["id"]] = leg
            return list(originals.values())

    def status(self, **fields):
        with self.database(write=bool(fields)) as db:
            state = self._status(db)
            if fields:
                state.update(fields)
                db.execute(
                    "INSERT INTO monitor VALUES (1,?) ON CONFLICT(singleton) DO UPDATE SET state=excluded.state",
                    (encoded(state),),
                )
        return state

    @staticmethod
    def _status(db):
        row = db.execute("SELECT state FROM monitor WHERE singleton=1").fetchone()
        return json.loads(row[0]) if row else {"monitor_state": "starting"}

    def _quotes(self, db, entry):
        originals = legs(entry["snapshot"], entry["kind"])
        identities = [self.identity(row) for row in originals]
        ids = [row["id"] for row in originals]
        marks = ",".join("?" for _ in identities)
        rows = db.execute(
            f"SELECT payload,observed_at FROM quotes WHERE identity IN ({marks}) OR quote_id IN ({marks}) ORDER BY observed_at",
            [*identities, *ids],
        ).fetchall()
        return [
            dict(json.loads(row["payload"]), observed_at=row["observed_at"])
            for row in rows
        ]

    def _metrics(self, db, entry, *, quotes=None):
        from .bet_journal_metrics import analyze

        entry["metrics"] = analyze(
            entry, self._quotes(db, entry) if quotes is None else quotes
        )
        opportunity = digest(
            [
                "automatic",
                entry["kind"],
                [self.identity(row) for row in legs(entry["snapshot"], entry["kind"])],
            ]
        )
        entry["opportunity_id"] = (
            opportunity
            if db.execute("SELECT 1 FROM entries WHERE id=?", (opportunity,)).fetchone()
            else None
        )
        return entry

    def get(self, key, *, history=False):
        with self.database() as db:
            return self._record(
                db,
                db.execute("SELECT * FROM entries WHERE id=?", (key,)).fetchone(),
                history=history,
            )

    def _record(self, db, row, *, history=False):
        entry = self.unpack(row)
        quotes = self._quotes(db, entry)
        result = dict(entry=self._metrics(db, entry, quotes=quotes))
        if history:
            result["history"] = [
                dict(
                    revision=row["revision"],
                    recorded_at=row["recorded_at"],
                    **json.loads(row["state"]),
                )
                for row in db.execute(
                    "SELECT * FROM events WHERE entry_id=? ORDER BY revision",
                    (entry["id"],),
                )
            ]
            result["quotes"] = quotes
        return result

    def export(self, *, history=True):
        """All records and revisions from one read snapshot, on one connection."""
        with self.database() as db:
            rows = db.execute(
                "SELECT * FROM entries ORDER BY created_at DESC,id"
            ).fetchall()
            return dict(
                entries=[self._record(db, row, history=history) for row in rows],
                monitor=self._status(db),
            )

    def delete(self, key, revision):
        with self.database(write=True) as db:
            entry = self.unpack(
                db.execute("SELECT * FROM entries WHERE id=?", (key,)).fetchone()
            )
            if type(revision) is not int or revision != entry["revision"]:
                raise Conflict("This entry changed. Reload it before deleting it.")
            db.execute("INSERT OR IGNORE INTO deleted_entries VALUES (?)", (key,))
            db.execute("DELETE FROM events WHERE entry_id=?", (key,))
            db.execute("DELETE FROM entries WHERE id=?", (key,))

    def update(self, key, changes):
        if not isinstance(changes, dict) or set(changes) - {
            "revision",
            "decision",
            "notes",
            "trade",
        }:
            raise ValueError("Unknown journal update fields")
        with self.database(write=True) as db:
            entry = self.unpack(
                db.execute("SELECT * FROM entries WHERE id=?", (key,)).fetchone()
            )
            if (
                type(changes.get("revision")) is not int
                or changes["revision"] != entry["revision"]
            ):
                raise Conflict(
                    "This entry changed. Reload it before saving your correction."
                )
            state = {
                k: changes.get(k, entry[k]) for k in ("decision", "notes", "trade")
            }
            if state["decision"] not in ("observed", "saved", "passed", "placed"):
                raise ValueError("Unknown decision")
            if not isinstance(state["notes"], str) or len(state["notes"]) > 4000:
                raise ValueError("Notes are limited to 4000 characters")
            state["trade"] = automatic_trade(state["trade"], entry, state["decision"])
            validate_trade(state["trade"], entry, state["decision"])
            at, revision = clock(), entry["revision"] + 1
            db.execute(
                "UPDATE entries SET decision=?,notes=?,trade=?,updated_at=?,revision=? WHERE id=?",
                (
                    state["decision"],
                    state["notes"],
                    encoded(state["trade"]) if state["trade"] else None,
                    at,
                    revision,
                    key,
                ),
            )
            db.execute(
                "INSERT INTO events VALUES (?,?,?,?)",
                (key, revision, at, encoded(state)),
            )
            return self._record(
                db, db.execute("SELECT * FROM entries WHERE id=?", (key,)).fetchone()
            )

    def list(self, *, limit=100, offset=0, view="log", kind="", decision="", search=""):
        limit, offset = max(1, min(500, int(limit))), max(0, int(offset))
        if (
            view not in ("bets", "log")
            or kind not in ("", "ev", "arb")
            or decision not in ("", "observed", "saved", "passed", "placed")
        ):
            raise ValueError("Unknown journal filter")
        if len(search) > 150:
            raise ValueError("Search is limited to 150 characters")
        conditions, params = [], []
        if view == "bets":
            conditions.append("decision IN ('saved','placed')")
        for column, value in (("kind", kind), ("decision", decision)):
            if value:
                conditions.append(column + "=?")
                params.append(value)
        if search:
            conditions.append(
                "(instr(lower(COALESCE(json_extract(snapshot,'$.game'),'')),lower(?))>0 OR instr(lower(notes),lower(?))>0 OR instr(lower(COALESCE(json_extract(snapshot,'$.selection_label'),json_extract(snapshot,'$.selection.label'),'')),lower(?))>0)"
            )
            params.extend([search, search, search])
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.database() as db:
            total = db.execute(
                "SELECT count(*) FROM entries" + where, params
            ).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM entries"
                + where
                + " ORDER BY created_at DESC,id LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            entries = [self._metrics(db, self.unpack(row)) for row in rows]
            counts = dict(
                db.execute(
                    "SELECT decision,count(*) FROM entries GROUP BY decision"
                ).fetchall()
            )
            placed = [
                self._metrics(db, self.unpack(row))
                for row in db.execute("SELECT * FROM entries WHERE decision='placed'")
            ]
            opportunities = db.execute(
                "SELECT count(*) FROM entries WHERE origin='automatic'"
            ).fetchone()[0]
            monitor = self._status(db)
        settled = [
            e for e in placed if e["metrics"].get("realized_profit_usd") is not None
        ]
        profit = sum(
            (Fraction(e["metrics"]["realized_profit_usd"]) for e in settled),
            Fraction(0),
        )
        cost = sum(
            (Fraction(e["metrics"]["entry_cost_usd"]) for e in settled), Fraction(0)
        )
        expected = [e for e in placed if e["metrics"].get("entry_ev_usd") is not None]
        matched = [e for e in settled if e["metrics"].get("entry_ev_usd") is not None]
        settled_expected = sum(
            (Fraction(e["metrics"]["entry_ev_usd"]) for e in matched), Fraction(0)
        )
        matched_realized = sum(
            (Fraction(e["metrics"]["realized_profit_usd"]) for e in matched),
            Fraction(0),
        )
        clv = [
            Fraction(leg["clv"])
            for e in placed
            for leg in e["metrics"]["legs"]
            if leg.get("clv") is not None
        ]
        close_due = [
            e for e in placed if instant(e["snapshot"]["kickoff"]) <= instant(clock())
        ]
        return dict(
            entries=entries,
            total=total,
            offset=offset,
            limit=limit,
            summary=dict(
                counts=counts,
                placed=len(placed),
                opportunities=opportunities,
                settled=len(settled),
                realized_profit_usd=str(profit) if settled else None,
                realized_roi=str(profit / cost) if cost else None,
                settled_cost_usd=str(cost),
                summary_scope="all_entries",
                expected_profit_usd=str(
                    sum(
                        (Fraction(e["metrics"]["entry_ev_usd"]) for e in expected),
                        Fraction(0),
                    )
                )
                if expected
                else None,
                expected_count=len(expected),
                matched_settled_count=len(matched),
                realized_minus_expected_usd=str(matched_realized - settled_expected)
                if matched
                else None,
                average_price_clv=str(sum(clv) / len(clv)) if clv else None,
                clv_leg_count=len(clv),
                closes_due=len(close_due),
                closes_captured=sum(
                    e["metrics"]["close_state"] == "closed" for e in close_due
                ),
            ),
            monitor=monitor,
        )
