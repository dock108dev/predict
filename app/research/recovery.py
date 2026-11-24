"""Explicit retrospective recovery of retained T−10 responses. Never acquires data.

Original task states and checkpoint pointers are never changed. New checkpoint
records carry their original receipt clocks and their actual database write time.
"""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

from psycopg.types.json import Jsonb

from app.collection import original_receipts
from app.collection.sportsgameodds_adapter import parse_page
from app.comparison import fee_mode
from app.storage.store import encoded, hashed, stamp
from . import experiment as owner, paper, workspace
from .ev_movement import build_snapshot

VERSION = "raw-t10-opportunity-recovery-1"


def eligible_attempt(game, checkpoint, attempt, metadata):
    """Admission depends on provenance and time, never on calculated EV."""
    details = attempt.get("details") or {}
    try:
        start, end = stamp(checkpoint["target_at"]), stamp(checkpoint["deadline_at"])
        dispatch, received = stamp(details["dispatch_at"]), stamp(details["received_at"])
        return (attempt.get("dispatched") is True
                and attempt["schedule_id"] == game["schedule_id"]
                and start <= dispatch <= received <= end
                and stamp(metadata["received_at"]) == received
                and metadata["state"] == "retained"
                and metadata["provider"] == "sportsgameodds"
                and metadata["receipt_sha256"] == details["receipt_sha256"]
                and metadata["request_scope"] == details["request_scope"]
                and details["request_scope"]["eventIDs"] == game["event"]["source_event_id"]
                and details["request_scope"].get("includeAltLines") is True
                and not details["request_scope"].get("cursor"))
    except (KeyError, TypeError, ValueError):
        return False


def receipt_for_attempt(game, attempt, attempt_id):
    """Older failure records kept clocks but omitted the raw receipt ID.

    Require one exact receipt-time/event match in the original manifest. Never
    search a nearby time range. Derived single-response cohort IDs are labeled
    as such; they do not assert a lost original acquisition identifier.
    """
    details = attempt.get("details") or {}
    receipt_id = (details.get("original_response") or {}).get("id")
    if receipt_id:
        metadata, body = original_receipts.read(receipt_id)
        return attempt, metadata, body
    if not details.get("received_at") or not details.get("requested_at"):
        return None
    manifest = original_receipts.readonly(original_receipts.directory())
    if manifest is None:
        return None
    try:
        moment = stamp(details["received_at"]).isoformat()
        matches = [json.loads(row["metadata"]) for row in manifest.execute(
            "SELECT metadata FROM receipt WHERE received_at IN (?,?)",
            (moment, moment.replace("+00:00", "Z")))]
        matches = [m for m in matches if m["request_scope"].get("eventIDs") == game["event"]["source_event_id"]]
    finally:
        manifest.close()
    if len(matches) != 1:
        return None
    metadata, body = original_receipts.read(matches[0]["id"])
    enriched = dict(deepcopy(attempt))
    enriched["details"] = dict(details, dispatch_at=details["requested_at"],
        receipt_sha256=metadata["receipt_sha256"], request_scope=metadata["request_scope"],
        pull_id="retrospective-single-response:" + metadata["receipt_sha256"],
        attempt_id="retrospective-attempt-record:" + attempt_id,
        recovery_binding="unique exact original receipt timestamp and event scope; derived single-response cohort IDs")
    return enriched, metadata, body


def reconstruct(game, checkpoint, attempt_id, attempt, metadata, body):
    if not eligible_attempt(game, checkpoint, attempt, metadata):
        raise ValueError("recovery_source_ineligible")
    details = attempt["details"]
    page = parse_page(body, details["received_at"])
    if page.receipt_sha256 != metadata["receipt_sha256"] or len(page.events) != 1:
        raise ValueError("recovery_receipt_mismatch")
    source = page.events[0]
    if (source["event_id"] != game["event"]["source_event_id"]
            or source["league"] != "NCAAB" or source["phase"] != "pregame"
            or stamp(source["starts_at"]) != stamp(game["event"]["starts_at"])):
        raise ValueError("recovery_schedule_mismatch")
    page = replace(page, pull_id=details["pull_id"], attempt_id=details["attempt_id"],
                   request_scope=details["request_scope"])
    # This is an explicit replay assumption, not a read of today's fee settings.
    mode = fee_mode.state(False)
    context = SimpleNamespace(fee_mode=mode,
        price_routes={venue: "sportsgameodds" for venue in ("kalshi", "polymarket_us", "novig", "prophetx")},
        fee=lambda record, at: fee_mode.zero_fee(record, mode))
    snapshot = build_snapshot(None, page, request_scope=details["request_scope"],
        dispatch_at=details["dispatch_at"], known_at=details["received_at"], calculation_context=context)
    return dict(status="reconstructed", source_kind="retrospective_raw_t10", checkpoint="late",
        schedule_id=game["schedule_id"], target_at=checkpoint["target_at"], deadline_at=checkpoint["deadline_at"],
        requested_at=details["dispatch_at"], received_at=details["received_at"],
        snapshot=snapshot, fee_mode=mode,
        recovery=dict(version=VERSION, attempt_id=attempt_id, receipt_id=metadata["id"],
            receipt_sha256=metadata["receipt_sha256"], original_failure=attempt.get("reason"),
            original_known_at=details.get("known_at"),
            binding=details.get("recovery_binding", "original attempt names receipt, hash and acquisition identifiers"),
            admission="last original response received inside the recorded T−10 window; no EV-dependent admission",
            calculation="computed retrospectively under this code version; not EV known or persisted at T−10",
            fees="explicit $0-fee replay assumption", results="deferred"))


def prepare(db, day):
    workspace.game_day(day)
    games = list(db.execute("""SELECT * FROM public.ev_experiment_game
        WHERE event->>'league'='NCAAB' AND
        ((event->>'starts_at')::timestamptz AT TIME ZONE 'America/New_York')::date=%s::date
        ORDER BY id""", (day,)))
    recovered, dispositions = {}, []
    for game in games:
        checkpoint = owner._checkpoint_view(db, game, "late")
        if checkpoint["status"] == "captured":
            dispositions.append(dict(game_id=game["id"], title=game["event"]["title"], status="captured"))
            continue
        valid = []
        for row in db.execute("""SELECT id FROM public.ev_experiment_record
            WHERE game_id=%s AND checkpoint='late' AND kind='attempt' ORDER BY recorded_at,id""", (game["id"],)):
            index = owner._closure(db, [row["id"]])
            attempt = owner._value(index[row["id"]], index)
            try:
                bound = receipt_for_attempt(game, attempt, row["id"])
            except (KeyError, ValueError, OSError):
                continue
            if bound is None:
                continue
            attempt, metadata, body = bound
            if eligible_attempt(game, checkpoint, attempt, metadata):
                valid.append((stamp(metadata["received_at"]), row["id"], attempt, metadata, body))
        if valid:
            _, identity, attempt, metadata, body = max(valid, key=lambda item: item[:2])
            recovered[game["id"]] = reconstruct(game, checkpoint, identity, attempt, metadata, body)
        dispositions.append(dict(game_id=game["id"], title=game["event"]["title"],
            status="reconstructed" if valid else "no_eligible_retained_response", original_status=checkpoint["status"]))
    return recovered, dispositions


def record(db, day, *, commit=False):
    """CLI-only bounded recovery; default previews without changing any records."""
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        recovered, dispositions = prepare(db, day)
        parent = workspace._definition(db, workspace.PILOT_VERSION)
    if not commit:
        preview = []
        for game_id, value in recovered.items():
            tickets, gaps = paper.candidates(value["snapshot"], game_id=game_id,
                checkpoint_id="preview", at=value["received_at"], policy=parent["policy"])
            preview.append(dict(game_id=game_id, offers=len(value["snapshot"]["offers"]),
                                qualifying=len(tickets), exclusions=gaps))
        return dict(commit=False, dispositions=dispositions, recovered=preview, provider_requests=0, orders_submitted=0)
    with db.transaction():
        owner._lock(db)
        mapping = {}
        for game_id, value in recovered.items():
            mapping[game_id], _ = owner._write(db, "checkpoint", value, game_id=game_id, checkpoint="late",
                summary=dict(source_kind="retrospective_raw_t10", version=VERSION))
        policy = dict(deepcopy(parent["policy"]), recovered_checkpoints=mapping, defer_results=True,
            recovery_version=VERSION, fees="Original captures preserve their fee mode; reconstructed responses explicitly assume $0 fees.")
        identity = hashed([VERSION, day, parent["version"]])
        version = hashed([identity, policy])
        payload = {k: deepcopy(v) for k, v in parent.items()
                   if k not in ("id", "version", "recorded_at", "supersedes")}
        payload.update(title=f"{day} · T−10 opportunity record and raw-response recovery",
            question="Which >=4% paper opportunities can be recorded from the original T−10 evidence, separating frozen calculations from retrospective raw-response calculations?",
            policy=policy, template_version=parent["version"], designation="retrospective_raw_recovery",
            registration="Retrospectively registered opportunity record. Results integration deferred. Original pilot unchanged.")
        size = len(encoded(payload))
        if not db.execute("SELECT 1 FROM public.research_workspace_definition WHERE version=%s", (version,)).fetchone():
            workspace._admit(db, size)
            db.execute("""INSERT INTO public.research_workspace_definition
                (version,id,supersedes,payload_bytes,payload) VALUES (%s,%s,NULL,%s,%s)""",
                (version, identity, size, Jsonb(payload)))
    result = workspace.replay(db, day, version, {})
    return dict(run=result["run"], dispositions=dispositions, provider_requests=0, orders_submitted=0)


if __name__ == "__main__":
    import argparse
    from app.storage.store import connect

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    with connect() as connection:
        print(json.dumps(record(connection, args.date, commit=args.commit), default=str))
