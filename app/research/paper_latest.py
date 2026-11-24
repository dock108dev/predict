"""One newest covering pull, selected before success or EV filtering."""

from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction as F

from app.storage.acquisition_snapshot import read_snapshot
from app.storage.market_board import offer as display_offer
from app.storage.store import stamp
from .ev_movement import offer_measurements
from .paper import MINIMUM, POLICY, candidates, portfolios


def dated_pulls(db, day, *, selected=None, covering=False, limit=50):
    return db.execute("""SELECT p.pull_id,p.state,p.requested_at,p.request_scope,p.details,p.started_order
        FROM public.market_pull p WHERE (%s::text IS NULL OR p.pull_id=%s) AND EXISTS (
          SELECT 1 FROM public.market_pull_scope s WHERE s.pull_id=p.pull_id
            AND (NOT %s OR s.coverage->>'covers_board'='true')
            AND COALESCE(p.details#>>'{event,league}',s.snapshot#>>'{event,competition}')=%s
            AND ((COALESCE(p.details#>>'{event,starts_at}',s.snapshot#>>'{event,scheduled_start}'))::timestamptz
                 AT TIME ZONE 'America/New_York')::date=%s::date)
        ORDER BY p.started_order DESC LIMIT %s""", (selected, selected, covering, POLICY["league"], day, limit))


def _observation(snapshot, raw, pull_id, complete, qualified):
    from app.storage.store import hashed

    record = raw.get("record") or {}
    quote = record.get("quote") or {}
    market = record.get("market_identity") or {}
    original = quote.get("original") or {}
    event = snapshot.get("event") or {}
    times = quote.get("times") or {}
    try:
        display = display_offer(snapshot, raw, pull_id)
        screen = offer_measurements(raw)["screen"]
    except (ValueError, KeyError, TypeError, ArithmeticError):
        display = dict(revision=hashed([pull_id, raw]), outcome="Selection unavailable", line=market.get("line"))
        screen = dict(ev=None, probability=None, reason="observation_evidence_unreadable")
    reason = screen.get("reason")
    if not reason and not complete:
        reason = "pull_incomplete"
    if not reason and not qualified:
        reason = "not_qualified_by_this_pull"
    ev = screen["ev"] if not reason else None
    return dict(id=display["revision"], venue=quote.get("venue"), label=display["outcome"],
                family=market.get("family"), line=display["line"], posted_odds=original.get("value"),
                price_units=original.get("units"), available=quote.get("state") == "available",
                probability=screen["probability"] if not reason else None,
                screen_ev=ev, meets_pilot_screen=ev is not None and F(ev) >= MINIMUM, reason=reason,
                starts_at=event.get("scheduled_start"), received_at=times.get("received_at"),
                source_at=times.get("source_at"))


def latest(db, day=POLICY["default_date"], *, selected=None, evidence=False):
    at = datetime.now(timezone.utc).isoformat()
    # Select before filtering on success or prices; never fill gaps from an
    # older pull. Explicitly pinned scopes may also include restricted pulls.
    pull = dated_pulls(db, day, selected=selected, covering=selected is None, limit=1).fetchone()
    result = dict(date=day, as_of=at, pull=None, rows=[], preview_portfolios=None,
                  observations=[], recent_pulls=[], positive_only=True, provider_requests=0, orders_submitted=0,
                  capture_type="odds_pull", experiment_eligible=False,
                  designation="Single odds pull for inspection. T−10 eligibility is established by a frozen checkpoint.")
    if not evidence:
        result["recent_pulls"] = [dict(pull_id=row["pull_id"], state=row["state"],
            requested_at=row["requested_at"].isoformat(), title=(row["details"].get("event") or {}).get("title"))
            for row in dated_pulls(db, day)]
    if not pull:
        return result
    result["pull"] = {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in pull.items()}
    scopes = list(db.execute("SELECT family,period,state,coverage FROM public.market_pull_scope WHERE pull_id=%s ORDER BY family", (pull["pull_id"],)))
    result["scopes"] = scopes
    complete = pull["state"] == "complete" and all(scope["state"] == "complete" for scope in scopes)
    if not complete:
        result["incomplete_reason"] = "This pull is incomplete. Its statuses and any retained evidence belong to this attempt."
    identity = db.execute("SELECT sha256,raw_bytes FROM public.market_pull_evidence WHERE pull_id=%s",
                          (pull["pull_id"],)).fetchone()
    receipts = list(db.execute("""SELECT attempt_id,receipt_sha256,received_at,
        CASE WHEN %s THEN membership END membership FROM public.market_pull_receipt
        WHERE pull_id=%s ORDER BY received_at,attempt_id""", (evidence, pull["pull_id"])))
    if identity is not None:
        result["evidence_identity"] = identity
        snapshot = read_snapshot(db, pull["pull_id"])
    else:
        snapshot = None
        if complete:
            result["incomplete_reason"] = "The original snapshot is unavailable for this pull."
    if evidence:
        result.update(snapshot=snapshot, receipts=[dict(row, received_at=row["received_at"].isoformat()) for row in receipts])
        return result
    if snapshot is None:
        return result
    accepted = {(r["attempt_id"], r["receipt_sha256"], stamp(r["received_at"])) for r in receipts}
    eligible, refused = [], Counter()
    for offer in snapshot.get("offers", []):
        acquisition = (offer.get("calculation_payload") or {}).get("acquisition") or {}
        required = acquisition.get("required_inputs") or []
        qualified = acquisition.get("eligible") is True and acquisition.get("pull_id") == pull["pull_id"] and bool(required) and all(
            item.get("pull_id") == pull["pull_id"] and
            (item.get("attempt_id"), item.get("receipt_sha256"), stamp(item["received_at"])) in accepted for item in required)
        result["observations"].append(_observation(snapshot, offer, pull["pull_id"], complete, qualified))
        if qualified:
            eligible.append(offer)
        else:
            refused["not_qualified_by_this_pull"] += 1
    if not complete:
        return result
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
    return result
