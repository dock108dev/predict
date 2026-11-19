"""Observe committed local prices without collecting or depending on a browser.

The personal journal owns its durable storage. This reader never writes to the
source PostgreSQL database, including when that database is a frozen dev snapshot.
"""

from collections import defaultdict
from contextlib import ExitStack
from datetime import datetime, timezone
from fractions import Fraction
from threading import Lock
from time import monotonic

from app.storage.store import connect, hashed, stamp


def utc():
    return datetime.now(timezone.utc)


def _journal(value):
    if value is not None:
        return value
    from .bet_journal import Journal

    return Journal()


def _clock_valid(row, at):
    """Keep source clocks unchanged; a new inspection is not a new quote."""
    try:
        received = stamp(row["times"]["received_at"])
        start = stamp(row["kickoff"])
        source = row["times"].get("source_at")
        return received <= at < start and (source is None or stamp(source) <= received)
    except (KeyError, ValueError, TypeError):
        return False


def _quote_rows(db, at):
    """Include negative EV and reference-free legs after an arb disappears."""
    from app.storage.current_pregame import configured_routes
    from app.storage.pregame_arbs import book_entry
    from app.comparison.pregame_arbs import reprice

    routes = configured_routes(db)
    entries = list(
        db.execute(
            """SELECT p.payload,p.record,calculation.payload AS calculation
            FROM current_pregame_price p
            JOIN current_contract c ON c.id=p.contract_id
            JOIN current_offer_storage o ON o.contract_id=c.id
            JOIN current_event e ON e.id=c.event_id
            LEFT JOIN current_pregame_calculation calculation ON calculation.contract_id=p.contract_id
                AND calculation.reason IS NULL AND calculation.valid_until>%s
                AND NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(calculation.payload#>'{reference,prices}') r
                    LEFT JOIN current_sgo_reference s ON s.id=r->>'input_id'
                    WHERE s.id IS NULL OR s.facts->'available' IS DISTINCT FROM 'true'::jsonb)
            WHERE p.start_at>%s AND p.valid_until>%s AND e.scheduled_start::timestamptz>%s
                AND o.facts->>'state' IS DISTINCT FROM 'unavailable'
                AND NOT EXISTS (SELECT 1 FROM sgo_line_presence lp
                    WHERE lp.quote_id=o.sgo_quote_id AND lp.expired)
                AND NOT EXISTS (SELECT 1 FROM current_pregame_work w
                    WHERE w.provider=e.provider AND w.native_event_id=e.native_event_id)
                AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(p.payload->'sportsbook_event_ids') ref(event_id)
                    JOIN current_pregame_work w ON w.provider='sportsgameodds' AND w.native_event_id=ref.event_id)
                AND NOT (COALESCE(e.facts->'status','{}'::jsonb) @> '{"live":true}'::jsonb)
                AND NOT (COALESCE(e.facts->'status','{}'::jsonb) @> '{"ended":true}'::jsonb)
                AND COALESCE(e.facts#>>'{status,status}','') NOT IN
                    ('cancelled','final','suspended','started','delayed')
            ORDER BY p.game_key,p.contract_id""",
            (at, at, at, at),
        )
    )
    entries = [
        entry
        for entry in entries
        if entry["payload"]["source"]["provider"]
        == routes.get(entry["payload"]["venue"])
        and _clock_valid(entry["payload"], at)
    ]
    rows = []
    for entry in entries:
        payload = entry["payload"]
        calculation = entry.get("calculation")
        if calculation and _clock_valid(calculation, at):
            payload = dict(payload, **calculation)
        rows.append(payload)
    references = defaultdict(dict)
    for row in rows:
        if row.get("reference"):
            reference = row["reference"]
            references[(row.get("arb_key"), row.get("side"))][hashed(reference)] = (
                reference
            )

    # Sportsbook legs are not current_pregame_price rows. Rebuild their exact
    # identity from the same stored quote matching used by the arb board, even
    # when the latest prices no longer produce a profitable pair.
    by_event = defaultdict(list)
    event_ids = sorted(
        {
            event_id
            for entry in entries
            for event_id in entry["payload"].get("sportsbook_event_ids", ())
        }
    )
    if event_ids:
        for result in db.execute(
            "SELECT facts FROM current_sgo_reference WHERE event_id=ANY(%s)",
            (event_ids,),
        ):
            quote = result["facts"]
            by_event[quote.get("event_id")].append(quote)
    books = {}
    visited = set()
    for entry in entries:
        payload = entry["payload"]
        key = payload.get("arb_key")
        if key in visited:
            continue
        visited.add(key)
        for event_id in payload.get("sportsbook_event_ids", ()):
            for quote in by_event[event_id]:
                book = book_entry(quote, entry, at=at)
                if not book:
                    continue
                row = reprice(book, Fraction(100), at=at)
                available_refs = references[(row.get("arb_key"), row.get("side"))]
                if len(available_refs) == 1:
                    # Copy only a qualified model for this exact same outcome.
                    # Do not fabricate a complement across different benchmarks.
                    row["reference"] = next(iter(available_refs.values()))
                row["input_revision"] = hashed([row["id"], row["posted"], row["times"]])
                prior = books.get(row["id"])
                if prior is None or stamp(row["times"]["source_at"]) > stamp(
                    prior["times"]["source_at"]
                ):
                    books[row["id"]] = row
                elif (
                    stamp(row["times"]["source_at"])
                    == stamp(prior["times"]["source_at"])
                    and row["posted"] != prior["posted"]
                ):
                    # Do not pick one of two conflicting simultaneous prices.
                    books[row["id"]] = dict(prior, _ambiguous=True)
    rows.extend(row for row in books.values() if not row.get("_ambiguous"))
    return rows


def _read(db, at, include_arbs):
    from app.storage.pregame_arbs import read as arb_read

    revision = db.execute(
        "SELECT revision FROM current_pregame_revision WHERE singleton"
    ).fetchone()["revision"]
    quotes = _quote_rows(db, at)
    ev = [
        row
        for row in quotes
        if row.get("main") is True
        and row.get("reference")
        and Fraction(row.get("raw", {}).get("net_ev") or "0") > 0
    ]
    arbs = []
    if include_arbs:
        offset = 0
        while True:
            packet = arb_read(db, dict(limit="100", offset=str(offset)), at=at)
            arbs.extend(packet["rows"])
            offset += len(packet["rows"])
            if not packet["rows"] or offset >= packet["total"]:
                break
    return dict(revision=revision, quotes=quotes, ev=ev, arbs=arbs)


def sample(*, journal=None, connector=connect, at=None, include_arbs=True):
    """Capture one consistent committed view; the caller can run this in a thread."""
    journal = _journal(journal)
    at = stamp(at) if at is not None else utc()
    targets = (
        journal.targets(at=at) if callable(getattr(journal, "targets", None)) else []
    )
    with connector() as db, db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        packet = _read(db, at, include_arbs)
        if callable(getattr(journal, "targets", None)):
            targets = {r["id"]: r for r in targets}
            for pair in packet["arbs"]:
                for leg in pair["legs"]:
                    targets.setdefault(leg["id"], leg)
            for row in packet["ev"]:
                targets[row["id"]] = row
            targets = list(targets.values())
        if targets:
            from .journal_closing_reference import capture

            packet["quotes"].extend(capture(db, targets, at=at))
    # The source transaction is released before any personal journal write.
    recorded_at = at.isoformat()
    if callable(getattr(journal, "capture", None)):
        journal.capture(packet["ev"], packet["arbs"], packet["quotes"], at=recorded_at)
    else:
        for row in packet["ev"]:
            journal.observe("ev", row, at=recorded_at)
        for pair in packet["arbs"]:
            journal.observe("arb", pair, at=recorded_at)
        journal.quotes(packet["quotes"], at=recorded_at)
    result = dict(
        revision=packet["revision"],
        quotes=len(packet["quotes"]),
        ev=len(packet["ev"]),
        arbs=len(packet["arbs"]),
        provider_requests=0,
    )
    journal.status(
        monitor_state="running",
        monitor_checked_at=at.isoformat(),
        monitor_error=None,
        source_revision=packet["revision"],
        provider_requests=0,
    )
    return result


class Monitor:
    """Share a cheap revision gate across requests; source failures stay nonfatal."""

    def __init__(self, *, timer=monotonic):
        self.timer = timer
        self.lock = Lock()
        self.last_sample = float("-inf")
        self.last_arb = float("-inf")
        self.revision = None

    def poll(self, *, journal=None, connector=connect, at=None):
        if not self.lock.acquire(blocking=False):
            return None
        journal_value = journal
        leases = ExitStack()
        try:
            now = self.timer()
            if 0 <= now - self.last_sample < 1:
                return None
            self.last_sample = now
            journal_value = _journal(journal)
            from .journal_sampling import (
                sampling_lease,
                shared_decision,
                successful_gate,
            )

            shared = leases.enter_context(sampling_lease(journal_value))
            if shared is False:
                return None
            sampled_at = stamp(at) if at is not None else utc()
            with connector() as db, db.transaction():
                db.execute("SET TRANSACTION READ ONLY")
                revision = db.execute(
                    "SELECT revision FROM current_pregame_revision WHERE singleton"
                ).fetchone()["revision"]
                info = db.info
                identity = (info.host, info.port, info.dbname, revision)
            if shared:
                state = journal_value.status()
                due, include_arbs = shared_decision(
                    state, identity[:-1], revision, sampled_at
                )
                if not due:
                    return None
            else:
                include_arbs = now - self.last_arb >= 15
                if identity == self.revision and not include_arbs:
                    return None
            result = sample(
                journal=journal_value,
                connector=connector,
                at=at,
                include_arbs=include_arbs,
            )
            self.revision = (*identity[:-1], result["revision"])
            if include_arbs:
                self.last_arb = now
            if shared:
                journal_value.status(
                    sampling_gate=successful_gate(
                        state,
                        identity[:-1],
                        result["revision"],
                        sampled_at,
                        include_arbs,
                    )
                )
            return result
        except Exception as exc:
            from app.diagnostics import failure

            failure(__name__, "personal_journal_monitor", exc)
            if journal_value is not None:
                try:
                    journal_value.status(
                        monitor_state="error",
                        monitor_checked_at=(
                            stamp(at) if at is not None else utc()
                        ).isoformat(),
                        monitor_error="Stored prices could not be observed; saved journal records are preserved.",
                        provider_requests=0,
                    )
                except Exception as status_exc:
                    failure(__name__, "personal_journal_monitor_status", status_exc)
            return None
        finally:
            try:
                leases.close()
            finally:
                self.lock.release()


_MONITOR = Monitor()


def poll(*, journal=None, connector=connect, at=None):
    return _MONITOR.poll(journal=journal, connector=connector, at=at)
