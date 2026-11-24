"""One newest covering pull, selected before success or EV filtering."""

from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction as F

from app.storage.acquisition_snapshot import read_snapshot
from app.storage.store import stamp
from .paper import POLICY, candidates, portfolios


def latest(db, day=POLICY["default_date"]):
    at = datetime.now(timezone.utc).isoformat()
    # Select the newest attempt, including failures. Never fill its gaps from
    # the previous successful event, market or venue snapshot.
    pull = db.execute("""SELECT p.pull_id,p.state,p.requested_at,p.request_scope,p.details,
        p.started_order FROM public.market_pull p WHERE EXISTS (
          SELECT 1 FROM public.market_pull_scope s WHERE s.pull_id=p.pull_id
            AND s.coverage->>'covers_board'='true'
            AND COALESCE(p.details#>>'{event,league}',s.snapshot#>>'{event,competition}')=%s
            AND ((COALESCE(p.details#>>'{event,starts_at}',s.snapshot#>>'{event,scheduled_start}'))::timestamptz
                 AT TIME ZONE 'America/New_York')::date=%s::date)
        ORDER BY p.started_order DESC LIMIT 1""", (POLICY["league"], day)).fetchone()
    result = dict(date=day, as_of=at, pull=None, rows=[], preview_portfolios=None,
                  positive_only=True, provider_requests=0, orders_submitted=0,
                  designation="Latest single odds pull; preview only, not the frozen T−10 portfolio")
    if not pull:
        return result
    result["pull"] = {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in pull.items()}
    scopes = list(db.execute("SELECT family,period,state,coverage FROM public.market_pull_scope WHERE pull_id=%s ORDER BY family", (pull["pull_id"],)))
    result["scopes"] = scopes
    if pull["state"] != "complete" or any(s["state"] != "complete" for s in scopes):
        result["incomplete_reason"] = "Latest pull is incomplete; older successful pulls are not substituted."
        return result
    snapshot = read_snapshot(db, pull["pull_id"])
    accepted = {(r["attempt_id"], r["receipt_sha256"], stamp(r["received_at"])) for r in db.execute(
        "SELECT attempt_id,receipt_sha256,received_at FROM public.market_pull_receipt WHERE pull_id=%s", (pull["pull_id"],))}
    eligible, refused = [], Counter()
    for offer in snapshot.get("offers", []):
        acquisition = (offer.get("calculation_payload") or {}).get("acquisition") or {}
        required = acquisition.get("required_inputs") or []
        if acquisition.get("eligible") is not True or acquisition.get("pull_id") != pull["pull_id"] or not required or any(
                r.get("pull_id") != pull["pull_id"] or
                (r.get("attempt_id"), r.get("receipt_sha256"), stamp(r["received_at"])) not in accepted for r in required):
            refused["not_qualified_by_this_pull"] += 1
        else:
            eligible.append(offer)
    snapshot = dict(snapshot, offers=eligible)
    known = (snapshot.get("times") or {}).get("known_at") or (snapshot.get("times") or {}).get("received_at")
    known = stamp(known).isoformat()
    found, gaps = candidates(snapshot, game_id=(snapshot.get("event") or {}).get("id") or pull["pull_id"],
        checkpoint_id=pull["pull_id"], at=known, minimum=F(0))
    # Preview both actual experiment strategies using the identical received
    # evidence and the same sizing/threshold rules as the frozen backtest.
    sized, sizing_gaps = candidates(snapshot, game_id=(snapshot.get("event") or {}).get("id") or pull["pull_id"],
        checkpoint_id=pull["pull_id"], at=known)
    result["preview_portfolios"] = {k: {a: b for a, b in v.items() if a != "tickets"}
                                    for k, v in portfolios(sized, as_of=at).items()}
    result["rows"] = [{k: v for k, v in t.items() if k not in ("witness", "grading")} for t in found]
    result["exclusions"] = dict(Counter(gaps) + refused)
    result["sizing_exclusions"] = sizing_gaps
    result["positive_only"] = True
    return result
