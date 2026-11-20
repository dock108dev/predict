"""Durable personal decisions, corrections and pregame quotes, outside source snapshots."""

from contextlib import contextmanager, closing
from datetime import timezone
from fractions import Fraction
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from app.comparison.scanner_readiness import EXECUTION_VENUES
from .bet_journal_trade import (
    automatic_trade,
    validate_trade,
    clock,
    instant,
    legs,
    number,
)

ROOT = Path(__file__).resolve().parents[2]
MARKET_VENUES = ",".join("'" + venue + "'" for venue in EXECUTION_VENUES)
MARKET_PAIR = (
    "(kind='arb' AND json_array_length(snapshot,'$.legs')=2"
    " AND json_extract(snapshot,'$.legs[0].venue') IN (" + MARKET_VENUES + ")"
    " AND json_extract(snapshot,'$.legs[1].venue') IN (" + MARKET_VENUES + "))"
)
ELIGIBLE = (
    "(decision IN ('saved','placed') OR ("
    + MARKET_PAIR
    + " AND journal_positive_arb(snapshot)))"
)


def automatic_arb(snapshot):
    rows = snapshot.get("legs")
    return (
        isinstance(rows, list)
        and len(rows) == 2
        and all(row.get("venue") in EXECUTION_VENUES for row in rows)
        and positive_arb(snapshot)
    )


def positive_arb(snapshot):
    try:
        return all(
            not isinstance(snapshot[key], bool)
            and number(snapshot[key], signed=True) > 0
            for key in ("return_rate", "minimum_profit_usd")
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return False


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(encoded(value).encode()).hexdigest()


class Conflict(ValueError):
    pass


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
            db.create_function(
                "journal_positive_arb",
                1,
                lambda value: int(positive_arb(json.loads(value))),
                deterministic=True,
            )
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
                CREATE TABLE IF NOT EXISTS quote_aliases (
                    quote_id TEXT NOT NULL, identity TEXT NOT NULL,
                    PRIMARY KEY(quote_id, identity)
                );
                CREATE INDEX IF NOT EXISTS quote_aliases_identity ON quote_aliases(identity, quote_id);
                CREATE TABLE IF NOT EXISTS quotes (
                    quote_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    identity TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(quote_id, fingerprint)
                );
                CREATE INDEX IF NOT EXISTS quotes_identity ON quotes(identity, observed_at);
                CREATE TABLE IF NOT EXISTS monitor (singleton INTEGER PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS deleted_entries (id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS journal_requests (
                    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, response TEXT NOT NULL,
                    PRIMARY KEY(entry_id, request_id)
                );
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
            return self._observe(
                db,
                kind,
                snapshot,
                at=at,
                manual=manual,
                automatic_index=self._automatic_index(db) if not manual else None,
            )

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

    def _observe(
        self, db, kind, snapshot, *, at=None, manual=False, automatic_index=None
    ):
        validate_snapshot(kind, snapshot)
        if not manual and (kind != "arb" or not automatic_arb(snapshot)):
            return None
        at = instant(at or clock()).isoformat()
        origin = "browser_snapshot" if manual else "automatic"
        key = digest(
            [
                origin,
                kind,
                self._manual_snapshot(kind, snapshot)
                if manual
                else self._automatic_identities(snapshot),
            ]
        )
        automatic_keys = self.automatic_keys(kind, snapshot) if not manual else [key]
        if not manual:
            if automatic_index is None:
                automatic_index = self._automatic_index(db)
            existing = automatic_index.get(key)
            marks = ",".join("?" for _ in automatic_keys)
            prior = db.execute(
                "SELECT id FROM entries WHERE id IN ("
                + marks
                + ") ORDER BY created_at,id LIMIT 1",
                automatic_keys,
            ).fetchone()
            if existing:
                key = existing
            elif prior:
                key = prior["id"]
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
                "SELECT 1 FROM deleted_entries WHERE id IN ("
                + ",".join("?" for _ in automatic_keys)
                + ")",
                automatic_keys,
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
        if automatic_index is not None and not manual:
            automatic_index.setdefault(automatic_keys[0], key)
        return key

    @classmethod
    def _economic_identity(cls, row):
        selection = row.get("selection")
        if not isinstance(selection, dict):
            return cls.identity(row)
        return cls.identity(
            dict(
                row,
                selection={
                    key: value
                    for key, value in row["selection"].items()
                    if key != "label"
                },
            )
        )

    @classmethod
    def _automatic_identities(cls, snapshot):
        # Display labels can change without changing an exact trading selection.
        return sorted(cls._economic_identity(row) for row in snapshot["legs"])

    @classmethod
    def _automatic_index(cls, db):
        index = {}
        for row in db.execute(
            "SELECT id,snapshot FROM entries WHERE origin='automatic' AND "
            + MARKET_PAIR
            + " ORDER BY created_at,id"
        ):
            snapshot = json.loads(row["snapshot"])
            index.setdefault(
                digest(["automatic", "arb", cls._automatic_identities(snapshot)]),
                row["id"],
            )
        return index

    @classmethod
    def automatic_keys(cls, kind, snapshot):
        identities = [cls.identity(row) for row in legs(snapshot, kind)]
        economic = cls._automatic_identities(snapshot) if kind == "arb" else identities
        return list(
            dict.fromkeys(
                digest(["automatic", kind, order])
                for order in (
                    economic,
                    sorted(identities),
                    identities,
                    list(reversed(identities)),
                )
            )
        )

    def capture(self, ev, arbs, quotes, *, at=None):
        """One source sample has one SQLite transaction, independent of its size."""
        at = instant(at or clock()).isoformat()
        with self.database(write=True) as db:
            index = self._automatic_index(db)
            for snapshot in arbs:
                self._observe(db, "arb", snapshot, at=at, automatic_index=index)
            tracking = self._active_tracking(db, at)
            return sum(self._quote(db, row, at, tracking) for row in quotes)

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

    def _quote(self, db, row, at, tracking):
        identity = self.identity(row)
        originals = tracking[2].get(self._economic_identity(row), ())
        if (
            row["id"] not in tracking[0]
            and identity not in tracking[1]
            and not originals
        ):
            return 0
        # Receipt/knowledge after kickoff is never promoted into a closing observation.
        kickoff = instant(row["kickoff"])
        times = row["times"]
        received = instant(times["received_at"])
        source = instant(times.get("source_at") or times["received_at"])
        if not source <= received <= instant(at) < kickoff:
            return 0
        # Learn aliases from every qualified tracked quote, including negative
        # comparisons after the original arb has disappeared. No discovery or
        # positive-EV condition renews the original record or source clocks.
        db.executemany(
            "INSERT OR IGNORE INTO quote_aliases VALUES (?,?)",
            [(row["id"], original) for original in originals],
        )
        row = self.compact_quote(row)
        return db.execute(
            "INSERT OR IGNORE INTO quotes VALUES (?,?,?,?,?)",
            (row["id"], digest(row), identity, at, encoded(row)),
        ).rowcount

    def quotes(self, rows, *, at=None):
        at = instant(at or clock()).isoformat()
        with self.database(write=True) as db:
            tracking = self._active_tracking(db, at)
            return sum(self._quote(db, row, at, tracking) for row in rows)

    def _active_tracking(self, db, at, *, eligible=ELIGIBLE):
        ids, identities = set(), set()
        economic = {}
        for entry in db.execute(
            "SELECT kind,snapshot FROM entries WHERE "
            + eligible
            + (
                " AND julianday(json_extract(snapshot,'$.kickoff'))>julianday(?)"
                if at
                else ""
            ),
            (at,) if at else (),
        ):
            for row in legs(json.loads(entry["snapshot"]), entry["kind"]):
                ids.add(row["id"])
                identities.add(self.identity(row))
                economic.setdefault(self._economic_identity(row), set()).add(
                    self.identity(row)
                )
        values = sorted(identities)
        for offset in range(0, len(values), 500):
            batch = values[offset : offset + 500]
            ids.update(
                row["quote_id"]
                for row in db.execute(
                    "SELECT quote_id FROM quote_aliases WHERE identity IN ("
                    + ",".join("?" for _ in batch)
                    + ")",
                    batch,
                )
            )
        return ids, identities, economic

    def targets(self, *, at):
        with self.database() as db:
            originals = {}
            for row in db.execute(
                "SELECT kind,snapshot FROM entries WHERE "
                + ELIGIBLE
                + " AND julianday(json_extract(snapshot,'$.kickoff'))>julianday(?)",
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
            f"""SELECT payload,observed_at FROM quotes WHERE identity IN ({marks}) OR quote_id IN ({marks})
                OR quote_id IN (SELECT quote_id FROM quote_aliases WHERE identity IN ({marks})) ORDER BY observed_at""",
            [*identities, *ids, *identities],
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
        candidates = self.automatic_keys(entry["kind"], entry["snapshot"])
        prior = db.execute(
            "SELECT id FROM entries WHERE origin='automatic' AND "
            + MARKET_PAIR
            + " AND id IN ("
            + ",".join("?" for _ in candidates)
            + ") ORDER BY created_at,id LIMIT 1",
            candidates,
        ).fetchone()
        entry["opportunity_id"] = prior["id"] if prior else None
        if not prior and entry["kind"] == "arb":
            entry["opportunity_id"] = self._automatic_index(db).get(candidates[0])
        return entry

    def get(self, key, *, history=False):
        with self.database() as db:
            return self._record(
                db,
                db.execute("SELECT * FROM entries WHERE id=?", (key,)).fetchone(),
                history=history,
            )

    def preview(self, key, changes):
        """Calculate a proposed fill against one read snapshot; persist nothing."""
        if (
            not isinstance(changes, dict)
            or "trade" not in changes
            or set(changes) - {"trade", "decision"}
        ):
            raise ValueError("Supply a proposed trade and optional decision")
        with self.database() as db:
            entry = self.unpack(
                db.execute("SELECT * FROM entries WHERE id=?", (key,)).fetchone()
            )
            decision = changes.get("decision", "placed")
            if decision not in ("observed", "saved", "passed", "placed"):
                raise ValueError("Unknown decision")
            trade = automatic_trade(changes["trade"], entry, decision, clock=clock)
            validate_trade(trade, entry, decision, clock=clock)
            entry.update(decision=decision, trade=trade)
            return dict(entry=self._metrics(db, entry))

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
                "SELECT * FROM entries WHERE "
                + ELIGIBLE
                + " ORDER BY created_at DESC,id"
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
            if entry["origin"] == "automatic" and entry["kind"] == "arb":
                db.executemany(
                    "INSERT OR IGNORE INTO deleted_entries VALUES (?)",
                    [
                        (value,)
                        for value in self.automatic_keys("arb", entry["snapshot"])
                    ],
                )
            db.execute("DELETE FROM events WHERE entry_id=?", (key,))
            db.execute("DELETE FROM entries WHERE id=?", (key,))

    def prune_unpicked_evs(self, *, backup_path=None):
        """Explicit maintenance only: back up, then remove EVs outside My Bets."""
        with self.database(write=True) as db:
            unwanted = list(
                db.execute(
                    "SELECT id,snapshot FROM entries WHERE kind='ev' AND decision NOT IN ('saved','placed')"
                )
            )
            result = dict(
                deleted_entries=0,
                deleted_events=0,
                deleted_tracking=0,
                deleted_quotes=0,
                deleted_aliases=0,
                preserved_bets=db.execute(
                    "SELECT count(*) FROM entries WHERE decision IN ('saved','placed')"
                ).fetchone()[0],
                backup_path=None,
            )
            result["counts"] = dict(
                db.execute(
                    "SELECT decision,count(*) FROM entries WHERE "
                    + ELIGIBLE
                    + " GROUP BY decision"
                )
            )
            if not unwanted:
                return result
            backup = Path(backup_path) if backup_path is not None else None
            if (
                backup is None
                or not backup.is_absolute()
                or backup.resolve() == self.path.resolve()
            ):
                raise ValueError("Provide a new absolute SQLite backup path")
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            # The writer reservation blocks concurrent corrections. A separate
            # read connection can back up the committed WAL state without trying
            # to back up our own uncommitted write transaction.
            with (
                closing(sqlite3.connect(self.path)) as source,
                closing(sqlite3.connect(backup)) as destination,
            ):
                source.backup(destination)
            result["backup_path"] = str(backup)
            candidate_ids, candidate_identities = set(), set()
            for row in unwanted:
                snapshot = json.loads(row["snapshot"])
                candidate_ids.add(snapshot["id"])
                candidate_identities.add(self.identity(snapshot))
                result["deleted_events"] += db.execute(
                    "DELETE FROM events WHERE entry_id=?", (row["id"],)
                ).rowcount
                result["deleted_entries"] += db.execute(
                    "DELETE FROM entries WHERE id=?", (row["id"],)
                ).rowcount
            keep_ids, keep_identities, _ = self._active_tracking(db, None, eligible="1")
            for name, values in [
                ("prune_ids", candidate_ids),
                ("prune_identities", candidate_identities),
                ("keep_ids", keep_ids),
                ("keep_identities", keep_identities),
            ]:
                db.execute("CREATE TEMP TABLE " + name + " (value TEXT PRIMARY KEY)")
                db.executemany(
                    "INSERT INTO " + name + " VALUES (?)",
                    [(value,) for value in values],
                )
            for table, field in [
                ("tracked", "deleted_tracking"),
                ("quotes", "deleted_quotes"),
                ("quote_aliases", "deleted_aliases"),
            ]:
                result[field] = db.execute(
                    "DELETE FROM "
                    + table
                    + """ WHERE
                    (quote_id IN (SELECT value FROM prune_ids) OR identity IN (SELECT value FROM prune_identities))
                    AND quote_id NOT IN (SELECT value FROM keep_ids)
                    AND identity NOT IN (SELECT value FROM keep_identities)"""
                ).rowcount
            result["counts"] = dict(
                db.execute(
                    "SELECT decision,count(*) FROM entries WHERE "
                    + ELIGIBLE
                    + " GROUP BY decision"
                )
            )
            return result

    def update(self, key, changes):
        if not isinstance(changes, dict) or set(changes) - {
            "revision",
            "decision",
            "notes",
            "trade",
            "request_id",
        }:
            raise ValueError("Unknown journal update fields")
        with self.database(write=True) as db:
            request_id = changes.get("request_id")
            if request_id is not None:
                if not isinstance(request_id, str) or not 1 <= len(request_id) <= 100:
                    raise ValueError("Use a bounded save request ID")
                previous = db.execute(
                    "SELECT fingerprint,response FROM journal_requests WHERE entry_id=? AND request_id=?",
                    (key, request_id),
                ).fetchone()
                if previous:
                    if previous["fingerprint"] != digest(changes):
                        raise Conflict(
                            "This save request was already used for different edits"
                        )
                    return json.loads(previous["response"])
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
            state["trade"] = automatic_trade(
                state["trade"], entry, state["decision"], clock=clock
            )
            validate_trade(state["trade"], entry, state["decision"], clock=clock)
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
            response = self._record(
                db, db.execute("SELECT * FROM entries WHERE id=?", (key,)).fetchone()
            )
            if request_id:
                db.execute(
                    "INSERT INTO journal_requests VALUES (?,?,?,?)",
                    (key, request_id, digest(changes), encoded(response)),
                )
            return response

    def list(
        self,
        *,
        limit=100,
        offset=0,
        view="log",
        kind="",
        decision="",
        search="",
        defer_observed=False,
    ):
        limit, offset = max(1, min(500, int(limit))), max(0, int(offset))
        if (
            view not in ("bets", "log", "placed", "research")
            or kind not in ("", "ev", "arb")
            or decision not in ("", "observed", "saved", "passed", "placed")
        ):
            raise ValueError("Unknown journal filter")
        if len(search) > 150:
            raise ValueError("Search is limited to 150 characters")
        if type(defer_observed) is not bool:
            raise ValueError("Choose whether to defer observed comparisons")
        conditions, params = [ELIGIBLE], []
        if view == "bets":
            conditions.append("decision IN ('saved','placed')")
        elif view in ("placed", "research"):
            conditions.append("decision=?")
            params.append("placed" if view == "placed" else "saved")
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
                + (
                    " ORDER BY (json_extract(trade,'$.result') IS NOT NULL),created_at DESC,id LIMIT ? OFFSET ?"
                    if view == "placed"
                    else " ORDER BY created_at DESC,id LIMIT ? OFFSET ?"
                ),
                [*params, limit, offset],
            ).fetchall()
            entries = []
            now = instant(clock())
            for row in rows:
                entry = self.unpack(row)
                if (
                    defer_observed
                    and entry["origin"] == "automatic"
                    and entry["decision"] == "observed"
                    and entry["trade"] is None
                ):
                    # Only unpicked cards without reported inputs defer. The
                    # unchanged first snapshot is enough until Details loads
                    # history; any recorded trade keeps its financial metrics.
                    entry["metrics"] = dict(
                        deferred=True,
                        close_state="closed"
                        if now >= instant(entry["snapshot"]["kickoff"])
                        else "tracking",
                    )
                    entry["opportunity_id"] = entry["id"]
                else:
                    self._metrics(db, entry)
                entries.append(entry)
            counts = dict(
                db.execute(
                    "SELECT decision,count(*) FROM entries WHERE "
                    + ELIGIBLE
                    + " GROUP BY decision"
                ).fetchall()
            )
            placed = [
                self._metrics(db, self.unpack(row))
                for row in db.execute("SELECT * FROM entries WHERE decision='placed'")
            ]
            opportunities = db.execute(
                "SELECT count(*) FROM entries WHERE origin='automatic' AND "
                + MARKET_PAIR
                + " AND journal_positive_arb(snapshot)"
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
