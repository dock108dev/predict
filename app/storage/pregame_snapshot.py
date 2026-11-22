"""Revalue only generated snapshot rows, preserving source, fee and control state."""

from collections import defaultdict
from datetime import datetime, timezone
from psycopg.types.json import Jsonb
from app.comparison import current_pregame as math
from .current_pregame import affected, numeric
from .current_rows import CurrentRowStore, contract_id, LOCK
from .store import hashed


def _reference_only_revalue(db, *, at=None):
    if math.VERSION != "predict-current-pregame-6":
        raise ValueError(
            "Reference-only snapshot upgrade supports calculation version 5 to 6 only"
        )
    at = at or datetime.now(timezone.utc)
    updates = []
    excluded = defaultdict(int)
    changed = 0
    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        versions = {
            r["version"]
            for r in db.execute(
                """SELECT DISTINCT version FROM current_pregame_calculation
            WHERE reason IS NULL AND payload IS NOT NULL AND start_at>%s AND valid_until>%s""",
                (at, at),
            )
        }
        if versions - {"predict-current-pregame-5", math.VERSION}:
            raise ValueError(
                "Snapshot requires a full calculation upgrade, not reference-only revaluation"
            )
        rows = list(
            db.execute(
                """SELECT contract_id,payload FROM current_pregame_calculation
            WHERE reason IS NULL AND payload IS NOT NULL AND start_at>%s AND valid_until>%s
            AND (version<>%s OR payload#>'{reference,main_line_evidence}' IS NULL
                 OR payload#>>'{reference,selection_policy}' IS DISTINCT FROM %s) ORDER BY game_key,contract_id""",
                (at, at, math.VERSION, math.REFERENCE_POLICY),
            )
        )
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["payload"]["game_key"]].append(row)
        for game_key, entries in grouped.items():
            source = entries[0]["payload"]["source"]
            events, observations, occurrence = affected(
                db,
                dict(
                    provider=source["provider"],
                    native_event_id=source["native_event_id"],
                ),
                at,
            )
            records = (
                CurrentRowStore(db).capture(
                    include_depth=False, event_ids=[e["id"] for e in events]
                )["records"]
                if events
                else []
            )
            by_id = {contract_id(r): r for r in records}
            inputs = math.ReferenceInputs(observations)
            references = {}
            for entry in entries:
                prior = entry["payload"]
                result = None
                reason = None
                try:
                    record = by_id[entry["contract_id"]]
                    if (
                        occurrence is None
                        or "pregame:"
                        + hashed(
                            [occurrence[0], occurrence[1].isoformat(), *occurrence[2:]]
                        )
                        != game_key
                    ):
                        raise ValueError("occurrence_identity_conflict")
                    if record["quote"]["source"]["provider"] == "sportsgameodds":
                        record["event"] = dict(
                            record["event"], home=occurrence[2], away=occurrence[3]
                        )
                    key = math.reference_key(record)
                    if key not in references:
                        references[key] = math.reference(record, inputs, at=at)
                    selected = references[key]
                    result = math.revalue_reference(prior, selected, at=at)
                    result["main"] = math.main_line(record, selected)
                    changed += (
                        prior["reference"]["book"],
                        prior["reference"]["probability"],
                    ) != (selected["book"], selected["probability"])
                except (KeyError, ValueError) as exc:
                    reason = str(exc) or "snapshot_reference_unavailable"
                    excluded[reason] += 1
                revision = (
                    result["input_revision"]
                    if result
                    else hashed(
                        [prior["input_revision"], math.REFERENCE_POLICY, reason]
                    )
                )
                updates.append(
                    (
                        Jsonb(result) if result else None,
                        math.VERSION,
                        revision,
                        numeric(result["raw"]["net_ev"]) if result else None,
                        numeric(result["raw"]["opportunity_score"]) if result else None,
                        result["main"] if result else False,
                        reason,
                        entry["contract_id"],
                    )
                )
        if updates:
            with db.cursor() as cursor:
                cursor.executemany(
                    """UPDATE current_pregame_calculation SET payload=%s,version=%s,
                    input_revision=%s,net_ev=%s,opportunity_score=%s,main=%s,reason=%s,
                    calculated_at=clock_timestamp() WHERE contract_id=%s""",
                    updates,
                )
            db.execute(
                "UPDATE current_pregame_revision SET revision=revision+1,committed_at=clock_timestamp() WHERE singleton"
            )
    return dict(
        policy=math.REFERENCE_POLICY,
        version=math.VERSION,
        revalued=len(updates) - sum(excluded.values()),
        examined=len(updates),
        reference_updated=changed,
        excluded=dict(excluded),
    )


def revalue(db, *, at=None):
    """Upgrade generated local rows using their retained source and fee owners.

    Version seven adds coherent and optional probability baselines. A reference-
    only patch cannot create these from the old scalar probability, so rebuild
    only affected stored games. Original snapshots and source/control/fee rows
    are read, never rewritten by this upgrade.
    """
    if math.VERSION == "predict-current-pregame-6":
        return _reference_only_revalue(db, at=at)
    if math.VERSION != "predict-current-pregame-7":
        raise ValueError("Snapshot calculation upgrade version unsupported")
    from .current_pregame import process

    at = at or datetime.now(timezone.utc)
    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        versions = {r["version"] for r in db.execute(
            "SELECT DISTINCT version FROM current_pregame_calculation WHERE start_at>%s AND valid_until>%s", (at, at))}
        if versions - {"predict-current-pregame-5", "predict-current-pregame-6", math.VERSION}:
            raise ValueError("Snapshot requires a full calculation upgrade from a supported stored version")
        rows = list(db.execute("""SELECT c.contract_id,c.payload,e.provider,e.native_event_id
            FROM current_pregame_calculation c JOIN current_contract t ON t.id=c.contract_id
            JOIN current_event e ON e.id=t.event_id
            LEFT JOIN current_pregame_price p ON p.contract_id=c.contract_id
            WHERE c.start_at>%s AND c.valid_until>%s AND
              (c.version<>%s OR c.reason IS NULL AND
                (c.payload#>>'{reference,selection_policy}' IS DISTINCT FROM %s
                 OR c.payload#>'{reference,main_line_evidence}' IS NULL
                 OR c.payload#>>'{coherent_probability,policy_version}' IS DISTINCT FROM %s)
               OR p.contract_id IS NOT NULL AND p.payload->'coherent_probability' IS NULL
               OR e.provider='sportsgameodds' AND t.venue='polymarket_us'
                 AND c.reason IS DISTINCT FROM 'provider_venue_fee_applicability_unestablished')
            ORDER BY c.game_key,c.contract_id""", (at, at, math.VERSION, math.REFERENCE_POLICY, math.COHERENT_POLICY)))
        keys = sorted({r["provider"] + ":" + r["native_event_id"] for r in rows})
        for source in {(r["provider"], r["native_event_id"]) for r in rows}:
            db.execute("""INSERT INTO current_pregame_work(provider,native_event_id) VALUES(%s,%s)
                ON CONFLICT(provider,native_event_id) DO UPDATE SET error=NULL,attempted_at=NULL""", source)
        # Each selected source is bounded by already retained current games;
        # no provider request is made and unchanged output stays idempotent.
        results = process(db, keys=keys, limit=max(1, len(keys)), at=at) if keys else []
        if any("error" in result for result in results):
            raise ValueError("snapshot_stored_game_upgrade_failed")
        after = {r["contract_id"]: r for r in db.execute(
            "SELECT contract_id,payload,reason FROM current_pregame_calculation WHERE contract_id=ANY(%s)",
            ([r["contract_id"] for r in rows],))}
        excluded = defaultdict(int)
        changed = revalued = 0
        for row in rows:
            result = after.get(row["contract_id"])
            if not result or result["reason"]:
                excluded[(result or {}).get("reason") or "source_identity_no_longer_current"] += 1
                continue
            revalued += 1
            old = (row["payload"] or {}).get("reference") or {}
            new = result["payload"]["reference"]
            changed += (old.get("book"), old.get("probability")) != (new["book"], new["probability"])
    return dict(policy=math.REFERENCE_POLICY, version=math.VERSION, examined=len(rows),
                revalued=revalued, reference_updated=changed, excluded=dict(excluded),
                upgrade="stored_affected_game_rebuild", provider_requests=0)
