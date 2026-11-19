"""Capture independent collection cohorts without renewing source timestamps.

Only the admission owner writes these bounded working sets. Dashboard reads
select a schema inside their read-only transaction and never collect/recalculate.
"""

from datetime import datetime, timezone

from psycopg import sql
from psycopg.types.json import Jsonb
from .store import stamp, hashed

SCHEMAS = {
    "monitor": "pregame_monitor",
    "live": "pregame_live",
    "all": "pregame_combined",
}
TABLES = (
    "current_event",
    "current_contract",
    "current_offer_storage",
    "current_sgo_reference",
    "sgo_line_presence",
    "current_pregame_calculation",
    "current_pregame_price",
)


def select(db, kind):
    if kind not in SCHEMAS:
        raise ValueError("Unknown collection data type")
    db.execute(
        sql.SQL("SET LOCAL search_path TO {},public").format(
            sql.Identifier(SCHEMAS[kind])
        )
    )


def capture(db, run, event_ids, at, *, observed=None):
    """Snapshot every admitted page, including unchanged quotes, after calculation.

    The transaction contains inputs and calculations from one committed page.
    References not observed by this cohort remain absent, so the read validator
    cannot borrow another cohort's inputs to claim a qualified calculation.
    """
    at = stamp(at)
    kind = run.get("kind")
    if kind not in ("monitor", "live"):
        raise ValueError("Collection cohort required")
    schema = SCHEMAS[kind]
    event_ids = sorted(set(event_ids))
    if not event_ids:
        return
    with db.transaction():
        # Serialize whole snapshot replacement with the source/calculation owner.
        from .current_rows import LOCK

        db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        events = [
            r["id"]
            for r in db.execute(
                """SELECT id FROM public.current_event e WHERE provider='sportsgameodds' AND native_event_id=ANY(%s)
            AND scheduled_start::timestamptz>%s
            AND (%s::timestamptz IS NULL OR scheduled_start::timestamptz>=%s)
            AND (%s::timestamptz IS NULL OR scheduled_start::timestamptz<=%s)
            AND NOT EXISTS(SELECT 1 FROM public.current_pregame_work w WHERE w.provider=e.provider AND w.native_event_id=e.native_event_id)""",
                (
                    event_ids,
                    at,
                    run.get("scope_start_at"),
                    run.get("scope_start_at"),
                    run.get("scope_end_at"),
                    run.get("scope_end_at"),
                ),
            )
        ]
        event_ids = [
            r["native_event_id"]
            for r in db.execute(
                "SELECT native_event_id FROM public.current_event WHERE id=ANY(%s)",
                (events,),
            )
        ]
        if not events:
            return
        cids = [
            r["id"]
            for r in db.execute(
                "SELECT id FROM public.current_contract WHERE event_id=ANY(%s)",
                (events,),
            )
        ]
        if observed is not None:
            from .current_rows import contract_id

            observed_records = {contract_id(r): r for r in observed["records"]}
            cids = [cid for cid in cids if cid in observed_records]
            # Out-of-order source rejection must not relabel a newer public
            # quote, observed only by another mode, as this capture's input.
            admitted = []
            for row in db.execute(
                "SELECT contract_id,record FROM public.current_pregame_price WHERE contract_id=ANY(%s)",
                (cids,),
            ):
                actual = row["record"]["quote"]
                witnessed = observed_records[row["contract_id"]]["quote"]
                if actual["original"] == witnessed["original"] and actual["times"].get(
                    "source_at"
                ) == witnessed["times"].get("source_at"):
                    admitted.append(row["contract_id"])
            cids = admitted
        refs = [
            r["id"]
            for r in db.execute(
                "SELECT id FROM public.current_sgo_reference WHERE event_id=ANY(%s)",
                (event_ids,),
            )
        ]
        if observed is not None:
            witnessed = {r["id"]: r["revision"] for r in observed["references"]}
            refs = [
                r["id"]
                for r in db.execute(
                    "SELECT id,revision FROM public.current_sgo_reference WHERE id=ANY(%s)",
                    (refs,),
                )
                if witnessed.get(r["id"]) == r["revision"]
            ]
        conditions = {
            "current_event": ("id=ANY(%s)", events),
            "current_contract": ("id=ANY(%s)", cids),
            "current_offer_storage": ("contract_id=ANY(%s)", cids),
            "current_sgo_reference": ("id=ANY(%s)", refs),
            "sgo_line_presence": ("event_id=ANY(%s)", event_ids),
            "current_pregame_price": ("contract_id=ANY(%s)", cids),
        }
        for table, (condition, current) in conditions.items():
            target = sql.Identifier(schema, table)
            columns = [
                r["attname"]
                for r in db.execute(
                    "SELECT attname FROM pg_attribute WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped ORDER BY attnum",
                    ("public." + table,),
                )
            ]
            columns.append("cohort_observed_at")
            key = key_for(table)
            assignments = sql.SQL(",").join(
                sql.SQL("{}=excluded.{}").format(sql.Identifier(c), sql.Identifier(c))
                for c in columns
                if c != key
            )
            db.execute(
                sql.SQL(
                    "INSERT INTO {} SELECT p.*,%s FROM {} p WHERE "
                    + condition
                    + " ON CONFLICT({}) DO UPDATE SET {}"
                ).format(
                    target,
                    sql.Identifier("public", table),
                    sql.Identifier(key),
                    assignments,
                ),
                (at, current),
            )
        metadata = dict(
            kind=kind,
            observed_at=at.isoformat(),
            run_id=run.get("id"),
            origin=run.get("origin", "collected"),
        )
        own_cids = [
            r["id"]
            for r in db.execute(
                sql.SQL(
                    "SELECT id FROM {}.current_contract WHERE event_id=ANY(%s)"
                ).format(sql.Identifier(schema)),
                (events,),
            )
        ]
        derive(db, schema, own_cids, at, metadata)
        combine(db, events, event_ids)
        for name in (schema, "pregame_combined"):
            db.execute(
                sql.SQL(
                    "UPDATE {}.current_pregame_revision SET revision=revision+1,committed_at=%s WHERE singleton"
                ).format(sql.Identifier(name)),
                (at,),
            )
        prune(db, schema, at)
        prune(db, "pregame_combined", at)


def key_for(table):
    return (
        "contract_id"
        if table
        in (
            "current_offer_storage",
            "current_pregame_price",
            "current_pregame_calculation",
        )
        else "quote_id"
        if table == "sgo_line_presence"
        else "id"
    )


def combine(db, events, event_ids):
    """Materialize latest per-key observations; omission cannot erase other mode."""
    cids = [
        r["id"]
        for r in db.execute(
            """SELECT id FROM pregame_monitor.current_contract WHERE event_id=ANY(%s)
        UNION SELECT id FROM pregame_live.current_contract WHERE event_id=ANY(%s)
        UNION SELECT id FROM pregame_combined.current_contract WHERE event_id=ANY(%s)""",
            (events, events, events),
        )
    ]
    for table in TABLES:
        key = key_for(table)
        condition, ids = (
            ("id=ANY(%s)", events)
            if table == "current_event"
            else ("event_id=ANY(%s)", events)
            if table == "current_contract"
            else ("event_id=ANY(%s)", event_ids)
            if table in ("current_sgo_reference", "sgo_line_presence")
            else ("contract_id=ANY(%s)", cids)
        )
        db.execute(
            sql.SQL("DELETE FROM {} WHERE " + condition).format(
                sql.Identifier("pregame_combined", table)
            ),
            (ids,),
        )
        statement = (
            "INSERT INTO {} SELECT DISTINCT ON ({}) * FROM (SELECT * FROM {} WHERE "
            + condition
            + " UNION ALL SELECT * FROM {} WHERE "
            + condition
            + ") p ORDER BY {},cohort_observed_at DESC"
        )
        db.execute(
            sql.SQL(statement).format(
                sql.Identifier("pregame_combined", table),
                sql.Identifier(key),
                sql.Identifier("pregame_live", table),
                sql.Identifier("pregame_monitor", table),
                sql.Identifier(key),
            ),
            (ids, ids),
        )


def derive(db, schema, cids, at, metadata):
    """Compute EV from this capture's reference witnesses, never public leftovers."""
    from app.comparison import current_pregame as math
    from .current_pregame import numeric
    from . import odds_archive

    rows = list(
        db.execute(
            sql.SQL(
                "SELECT * FROM {}.current_pregame_price WHERE contract_id=ANY(%s)"
            ).format(sql.Identifier(schema)),
            (cids,),
        )
    )
    # A page can contain hundreds of prices attached to the same reference
    # events. Decode each cohort's witnesses once, then index each distinct
    # event/role attachment once. Never consult the public reference table.
    event_ids = sorted(
        {eid for row in rows for eid in row["payload"].get("sportsbook_event_ids", [])}
    )
    by_event = {}
    for reference in db.execute(
        sql.SQL(
            "SELECT id,revision,event_id,facts FROM {}.current_sgo_reference WHERE event_id=ANY(%s)"
        ).format(sql.Identifier(schema)),
        (event_ids,),
    ):
        by_event.setdefault(reference["event_id"], []).append(reference)
    attachments = {}
    reference_inputs = {}
    snapshots = []
    for row in rows:
        original = row["payload"]
        row_metadata = dict(metadata, observed_at=row["cohort_observed_at"].isoformat())
        if row["cohort_observed_at"] != at:
            row_metadata["run_id"] = (original.get("collection") or {}).get("run_id")
            row_metadata["origin"] = (original.get("collection") or {}).get(
                "origin", metadata["origin"]
            )
        ids = original.get("sportsbook_event_ids", [])
        reversed_sides = original.get("sportsbook_sides_reversed", {})
        attachment = tuple(
            sorted((eid, bool(reversed_sides.get(eid))) for eid in set(ids))
        )
        if attachment not in attachments:
            observations = {}
            for event_id, references in by_event.items():
                if event_id not in ids:
                    continue
                for reference in references:
                    # Only this orientation changes. ReferenceInputs and the
                    # selector read nested source evidence without mutating it.
                    facts = dict(reference["facts"])
                    if reversed_sides.get(event_id) and facts.get("side") in (
                        "home",
                        "away",
                    ):
                        facts["canonical_side"] = (
                            "away" if facts["side"] == "home" else "home"
                        )
                    observations.setdefault(event_id, []).append(
                        dict(reference, facts=facts)
                    )
            attachments[attachment] = observations
        observations = attachments[attachment]
        reason = None
        payload = None
        reference = None
        try:
            if attachment not in reference_inputs:
                reference_inputs[attachment] = math.ReferenceInputs(observations)
            reference = math.reference(
                row["record"], reference_inputs[attachment], at=at
            )
            # The admitted price already contains the qualified fee cashflows.
            # Only probability-dependent values and line status can change.
            payload = math.revalue_reference(original, reference, at=at)
            payload["main"] = math.main_line(row["record"], reference)
            payload.update(
                sportsbook_event_ids=list(observations),
                sportsbook_sides_reversed=original.get("sportsbook_sides_reversed", {}),
            )
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            reason = str(exc)[:160] or type(exc).__name__
        revision = hashed([row["record"]["quote"], reference, reason, row["fee_input"]])
        price = dict(
            original,
            collection=row_metadata,
            input_revision=revision,
            sportsbook_event_ids=list(observations),
        )
        if payload:
            payload.update(collection=row_metadata, input_revision=revision)
        db.execute(
            sql.SQL(
                "UPDATE {}.current_pregame_price SET payload=%s WHERE contract_id=%s"
            ).format(sql.Identifier(schema)),
            (Jsonb(price), row["contract_id"]),
        )
        db.execute(
            sql.SQL("""INSERT INTO {}.current_pregame_calculation
            (contract_id,game_key,bet_id,league,family,venue,start_at,main,input_revision,version,
             calculated_at,valid_until,net_ev,opportunity_score,reason,payload,cohort_observed_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(contract_id) DO UPDATE SET game_key=excluded.game_key,bet_id=excluded.bet_id,
              league=excluded.league,family=excluded.family,venue=excluded.venue,start_at=excluded.start_at,
              main=excluded.main,input_revision=excluded.input_revision,version=excluded.version,
              calculated_at=excluded.calculated_at,valid_until=excluded.valid_until,net_ev=excluded.net_ev,
              opportunity_score=excluded.opportunity_score,reason=excluded.reason,payload=excluded.payload,
              cohort_observed_at=excluded.cohort_observed_at""").format(
                sql.Identifier(schema)
            ),
            (
                row["contract_id"],
                row["game_key"],
                price["bet_id"],
                price["league"],
                price["family"],
                price["venue"],
                row["start_at"],
                (payload or price)["main"],
                revision,
                math.VERSION,
                at,
                row["valid_until"],
                numeric(payload["raw"]["net_ev"]) if payload else None,
                numeric(payload["raw"]["opportunity_score"]) if payload else None,
                reason,
                Jsonb(payload) if payload else None,
                row["cohort_observed_at"],
            ),
        )
        if odds_archive.enabled() and metadata["origin"] == "collected":
            snapshots.append(
                odds_archive.observation(
                    "sportsgameodds",
                    "collection_calculation",
                    [metadata["run_id"], row["contract_id"]],
                    row["record"]["event"]["id"],
                    price["times"].get("source_at"),
                    at.isoformat(),
                    revision,
                    dict(
                        collection=metadata,
                        price=price,
                        calculation=payload,
                        reason=reason,
                        record=row["record"],
                        fee_input=row["fee_input"],
                    ),
                )
            )
    if snapshots:
        odds_archive.record(db, "sportsgameodds", snapshots)


def prune(db, schema, at):
    """Only hot cohorts expire; the immutable archive has no TTL deletion."""
    events = [
        r["id"]
        for r in db.execute(
            sql.SQL(
                "SELECT id FROM {}.current_event WHERE scheduled_start::timestamptz<=%s"
            ).format(sql.Identifier(schema)),
            (at,),
        )
    ]
    cids = [
        r["id"]
        for r in db.execute(
            sql.SQL("SELECT id FROM {}.current_contract WHERE event_id=ANY(%s)").format(
                sql.Identifier(schema)
            ),
            (events,),
        )
    ]
    for table in (
        "current_pregame_calculation",
        "current_pregame_price",
        "current_offer_storage",
    ):
        db.execute(
            sql.SQL("DELETE FROM {} WHERE contract_id=ANY(%s)").format(
                sql.Identifier(schema, table)
            ),
            (cids,),
        )
    db.execute(
        sql.SQL("DELETE FROM {}.current_contract WHERE event_id=ANY(%s)").format(
            sql.Identifier(schema)
        ),
        (events,),
    )
    db.execute(
        sql.SQL("DELETE FROM {}.current_event WHERE id=ANY(%s)").format(
            sql.Identifier(schema)
        ),
        (events,),
    )
    db.execute(
        sql.SQL(
            "DELETE FROM {}.sgo_line_presence WHERE quote_id IN (SELECT id FROM {}.current_sgo_reference WHERE (facts->>'starts_at')::timestamptz<=%s)"
        ).format(sql.Identifier(schema), sql.Identifier(schema)),
        (at,),
    )
    db.execute(
        sql.SQL(
            "DELETE FROM {}.current_sgo_reference WHERE (facts->>'starts_at')::timestamptz<=%s"
        ).format(sql.Identifier(schema)),
        (at,),
    )


def bootstrap(db, *, at=None):
    """Adopt retained authentic prices as a labeled legacy Monitor baseline once.

    This is not a new provider observation and does not renew any source clock.
    """
    at = at or datetime.now(timezone.utc)
    from .current_rows import LOCK

    with db.transaction():
        # Preserve the admission/fee writer's lock order before the row lock.
        db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        row = db.execute(
            "SELECT baseline_initialized FROM pregame_monitor.current_pregame_revision WHERE singleton FOR UPDATE"
        ).fetchone()
        if row["baseline_initialized"]:
            return
        ids = [
            r["native_event_id"]
            for r in db.execute(
                "SELECT native_event_id FROM public.current_event WHERE provider='sportsgameodds' AND scheduled_start::timestamptz>%s",
                (at,),
            )
        ]
        capture(db, dict(kind="monitor", origin="legacy_retained"), ids, at)
        db.execute(
            "UPDATE pregame_monitor.current_pregame_revision SET baseline_initialized=true WHERE singleton"
        )
