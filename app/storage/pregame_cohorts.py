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


def collection_witnesses(records, references):
    from .current_rows import contract_id

    return dict(
        offers={
            contract_id(r): [
                r["quote"]["original"],
                r["quote"]["times"].get("source_at"),
            ]
            for r in records
        },
        references={r["id"]: r["revision"] for r in references},
    )


def enqueue(
    db, run, event_ids, at, *, received_at, receipt_sha256, records, references, frames
):
    """Retain the page's original scope and exact normalized witnesses at admission."""
    if run.get("kind") not in ("monitor", "live"):
        raise ValueError("Collection cohort required")
    key = hashed([run.get("id"), received_at, receipt_sha256, sorted(event_ids)])
    db.execute(
        """INSERT INTO public.pregame_cohort_work
           (id,observed_at,expires_at,received_at,receipt_sha256,collection_run,event_ids,witnesses)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
        (
            key,
            at,
            max(stamp(frame["expires_at"]) for frame in frames),
            received_at,
            receipt_sha256,
            Jsonb(run),
            sorted(event_ids),
            Jsonb(collection_witnesses(records, references)),
        ),
    )
    return key


def staged_table(table):
    return sql.SQL(
        "jsonb_populate_recordset(NULL::{}, (SELECT snapshot->%s FROM public.pregame_cohort_work WHERE id=%s))"
    ).format(sql.Identifier("public", table))


def staged_inputs(db, key, event_ids):
    events = [
        row["id"]
        for row in db.execute(
            sql.SQL("SELECT id FROM {} WHERE native_event_id=ANY(%s)").format(
                staged_table("current_event")
            ),
            ("current_event", key, event_ids),
        )
    ]
    cids = [
        row["id"]
        for row in db.execute(
            sql.SQL("SELECT id FROM {} WHERE event_id=ANY(%s)").format(
                staged_table("current_contract")
            ),
            ("current_contract", key, events),
        )
    ]
    return (
        events,
        event_ids,
        {
            "current_event": ("id=ANY(%s)", events),
            "current_contract": ("id=ANY(%s)", cids),
            "current_offer_storage": ("contract_id=ANY(%s)", cids),
            "current_sgo_reference": ("event_id=ANY(%s)", event_ids),
            "sgo_line_presence": ("event_id=ANY(%s)", event_ids),
            "current_pregame_price": ("contract_id=ANY(%s)", cids),
        },
    )


def seal(db, key):
    """Stage typed inputs before another collection mode can change public rows."""
    work = db.execute(
        """SELECT collection_run,event_ids,observed_at,witnesses
        FROM public.pregame_cohort_work WHERE id=%s AND snapshot IS NULL""",
        (key,),
    ).fetchone()
    if work is None:
        return True
    pending = db.execute(
        """SELECT 1 FROM public.current_pregame_work
        WHERE provider='sportsgameodds' AND native_event_id=ANY(%s) LIMIT 1""",
        (work["event_ids"],),
    ).fetchone()
    if pending:
        return False
    _, _, conditions = inputs(
        db,
        work["collection_run"],
        work["event_ids"],
        work["observed_at"],
        work["witnesses"],
    )
    fields, parameters = [], []
    for table, (condition, keys) in conditions.items():
        fields.extend(
            (
                sql.Literal(table),
                sql.SQL(
                    "(SELECT COALESCE(jsonb_agg(to_jsonb(p)), '[]'::jsonb) FROM {} p WHERE {})"
                ).format(sql.Identifier("public", table), sql.SQL(condition)),
            )
        )
        parameters.append(keys)
    db.execute(
        sql.SQL(
            "UPDATE public.pregame_cohort_work SET snapshot=jsonb_build_object({}) WHERE id=%s"
        ).format(sql.SQL(",").join(fields)),
        (*parameters, key),
    )
    return True


def project(db, key, *, at, retry=False):
    """Publish only staged observations, atomically completing the work."""
    from .current_pregame import process
    from .current_rows import LOCK

    at = stamp(at)
    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        work = db.execute(
            """SELECT collection_run,event_ids,observed_at,expires_at,received_at,receipt_sha256,snapshot IS NOT NULL staged
            FROM public.pregame_cohort_work WHERE id=%s FOR UPDATE""",
            (key,),
        ).fetchone()
        if work is None:
            return "complete"
        if work["expires_at"] <= at:
            db.execute("DELETE FROM public.pregame_cohort_work WHERE id=%s", (key,))
            return "expired"
        if not work["staged"]:
            if not retry:
                return "current_calculation_pending"
            current_receipt = db.execute(
                """SELECT count(*) count FROM public.current_sgo_event_frame
                WHERE event_id=ANY(%s) AND facts->>'receipt_sha256'=%s AND facts->>'received_at'=%s""",
                (work["event_ids"], work["receipt_sha256"], work["received_at"]),
            ).fetchone()["count"]
            if current_receipt != len(work["event_ids"]):
                return "cohort_receipt_superseded_before_staging"
            keys = ["sportsgameodds:" + event for event in work["event_ids"]]
            process(db, keys=keys, limit=len(keys), at=work["observed_at"])
            if not seal(db, key):
                return "current_calculation_pending"
        schema = SCHEMAS[work["collection_run"]["kind"]]
        # An old projection must never replace a newer observation of the
        # same event in this mode. Other modes use independent staged facts.
        active = db.execute(
            sql.SQL("""SELECT e.native_event_id FROM {} e
            LEFT JOIN {} c ON c.id=e.id
            WHERE e.scheduled_start::timestamptz>%s
                AND (c.cohort_observed_at IS NULL OR c.cohort_observed_at<=%s)""").format(
                staged_table("current_event"), sql.Identifier(schema, "current_event")
            ),
            ("current_event", key, at, work["observed_at"]),
        ).fetchall()
        capture(
            db,
            work["collection_run"],
            [event["native_event_id"] for event in active],
            work["observed_at"],
            snapshot_key=key,
            recovered_at=at,
        )
        db.execute("DELETE FROM public.pregame_cohort_work WHERE id=%s", (key,))
    return "complete"


def attempt_projection(db, key, *, at, retry=False):
    from app.diagnostics import failure, failure_details

    try:
        reason = project(db, key, at=at, retry=retry)
        if reason in ("complete", "expired"):
            return dict(state=reason)
        details = None
    except Exception as exc:
        failure(__name__, "pregame_cohort_projection", exc)
        reason = "cohort_projection_failed"
        details = failure_details(exc)
    db.execute(
        """UPDATE public.pregame_cohort_work SET
          retry_after=clock_timestamp()+interval '15 seconds', last_error=%s WHERE id=%s""",
        (reason, key),
    )
    return dict(state="pending", reason=reason, diagnostics=details)


def recover(db, *, at, include_deferred=False, limit=8):
    """Retry independent receipts using only local SQL and original source clocks."""
    ids = db.execute(
        """SELECT id FROM public.pregame_cohort_work
        WHERE %s OR retry_after IS NULL OR retry_after<=clock_timestamp()
        ORDER BY retry_after NULLS FIRST,observed_at,id LIMIT %s""",
        (include_deferred, limit),
    ).fetchall()
    return [attempt_projection(db, job["id"], at=at, retry=True) for job in ids]


def inputs(db, run, event_ids, at, witnesses):
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
    cids = [
        r["id"]
        for r in db.execute(
            "SELECT id FROM public.current_contract WHERE event_id=ANY(%s)",
            (events,),
        )
    ]
    if witnesses is not None:
        offers = witnesses["offers"]
        cids = [cid for cid in cids if cid in offers]
        # Out-of-order source rejection must not relabel a newer public
        # quote, observed only by another mode, as this capture's input.
        admitted = []
        for row in db.execute(
            "SELECT contract_id,record FROM public.current_pregame_price WHERE contract_id=ANY(%s)",
            (cids,),
        ):
            actual = row["record"]["quote"]
            if [actual["original"], actual["times"].get("source_at")] == offers[
                row["contract_id"]
            ]:
                admitted.append(row["contract_id"])
        cids = admitted
    refs = [
        r["id"]
        for r in db.execute(
            "SELECT id FROM public.current_sgo_reference WHERE event_id=ANY(%s)",
            (event_ids,),
        )
    ]
    if witnesses is not None:
        witnessed = witnesses["references"]
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
    return events, event_ids, conditions


def capture(
    db, run, event_ids, at, *, observed=None, snapshot_key=None, recovered_at=None
):
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
    witnesses = (
        collection_witnesses(observed["records"], observed["references"])
        if observed is not None
        else None
    )
    with db.transaction():
        # Serialize whole snapshot replacement with the source/calculation owner.
        from .current_rows import LOCK

        db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        if snapshot_key is None:
            events, event_ids, conditions = inputs(db, run, event_ids, at, witnesses)
        else:
            events, event_ids, conditions = staged_inputs(db, snapshot_key, event_ids)
        if not events:
            return
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
                    staged_table(table)
                    if snapshot_key is not None
                    else sql.Identifier("public", table),
                    sql.Identifier(key),
                    assignments,
                ),
                (at, table, snapshot_key, current)
                if snapshot_key is not None
                else (at, current),
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
                    "UPDATE {}.current_pregame_revision SET revision=revision+1,committed_at=GREATEST(committed_at,%s) WHERE singleton"
                ).format(sql.Identifier(name)),
                (at,),
            )
        prune(db, schema, recovered_at or at)
        prune(db, "pregame_combined", recovered_at or at)


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
    from app.comparison.acquisition import calculation as acquisition_calculation, offer_input
    from app.collection.sportsgameodds_current_rows import source_bookmaker
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
        if attachment not in reference_inputs:
            reference_inputs[attachment] = math.ReferenceInputs(
                observations, books=math.COHERENT_POLICIES[math.EXPANSION_POLICY]
            )
        inputs = reference_inputs[attachment]
        probabilities = {}
        for policy in math.COHERENT_POLICIES:
            try:
                probabilities[policy] = math.qualified_coherent_reference(
                    row["record"], inputs, at=at, policy=policy,
                    evaluated_book=source_bookmaker(row["record"]) if policy == math.EXPANSION_POLICY else None,
                )
            except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                probabilities[policy] = dict(
                    policy_version=policy, probability=None, probabilities=None,
                    reason=str(exc)[:160] or type(exc).__name__,
                )
        probability_evidence = dict(
            coherent_probability=probabilities[math.COHERENT_POLICY],
            alternative_probabilities={p: r for p, r in probabilities.items() if p != math.COHERENT_POLICY},
        )
        try:
            if settlement_reason := math.posted_settlement_reason(row["record"]):
                raise ValueError(settlement_reason)
            reference = math.reference(
                row["record"], inputs, at=at
            )
            # The admitted price already contains the qualified fee cashflows.
            # Only probability-dependent values and line status can change.
            acquisition = (acquisition_calculation(row["record"], reference)
                           if offer_input(row["record"]).get("pull_id") else None)
            payload = math.revalue_reference(original, reference, at=at)
            if acquisition is not None:
                payload["acquisition"] = acquisition
            payload["main"] = math.main_line(row["record"], reference)
            payload.update(
                sportsbook_event_ids=list(observations),
                sportsbook_sides_reversed=original.get("sportsbook_sides_reversed", {}),
                **probability_evidence,
            )
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            reason = str(exc)[:160] or type(exc).__name__
        revision = hashed([row["record"]["quote"], reference, reason, row["fee_input"],
                           {p: math.probability_inputs(r) for p, r in probabilities.items()}])
        price = dict(
            original,
            collection=row_metadata,
            input_revision=revision,
            sportsbook_event_ids=list(observations),
            **probability_evidence,
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
