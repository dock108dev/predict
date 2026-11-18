"""Revalue only generated snapshot rows, preserving source, fee and control state."""

from collections import defaultdict
from datetime import datetime, timezone
from psycopg.types.json import Jsonb
from app.comparison import current_pregame as math
from .current_pregame import affected, numeric
from .current_rows import CurrentRowStore, contract_id, LOCK
from .store import hashed


def revalue(db, *, at=None):
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
