"""Native full-game Novig discovery, independent of aggregate venue quotes."""

from collections import defaultdict
from datetime import datetime, timezone
from fractions import Fraction as F
import re

from app.comparison.sgo_native_binding import settlement_profile
from app.storage.store import stamp

from .admission_enrichment import resolve_team
from .native_trading_identity import native_event, record, expected
from .novig_experiment_depth import (
    catalog_depth,
    EVENT_FRESH_SECONDS,
    _fresh,
    PublicEventDepth,
)


def roles(markets, league):
    """The documented spread strike is the home handicap; subject IDs bind names.

    Every available nonzero full-game spread must corroborate the same two
    subjects. Exact team resolution is independent for each role. Unknown
    college aliases remain source-local rather than borrowing an opponent's ID.
    """
    pairs, names = set(), {}
    for market in markets.values():
        if market.get("marketType") == "MONEY":
            for outcome in market["outcomes"]:
                if outcome.get("subjectId"):
                    names[outcome["subjectId"]] = outcome["name"]
        if market.get("marketType") != "SPREAD" or market.get("status") != "OPEN":
            continue
        strike = F(market["strike"])
        if not strike:
            continue
        selected = {}
        for outcome in market["outcomes"]:
            name, line = outcome["name"].rsplit(" ", 1)
            signed = F(line)
            if signed not in (strike, -strike) or not outcome.get("subjectId"):
                raise ValueError("novig_subject_role_conflict")
            role = "home" if signed == strike else "away"
            if role in selected:
                raise ValueError("novig_subject_role_conflict")
            selected[role] = outcome["subjectId"]
            names.setdefault(outcome["subjectId"], name)
        if set(selected) != {"home", "away"} or len(set(selected.values())) != 2:
            raise ValueError("novig_subject_role_conflict")
        pairs.add((selected["home"], selected["away"]))
    if len(pairs) != 1:
        raise ValueError("novig_subject_roles_unverified")
    home, away = next(iter(pairs))
    subjects = dict(home=home, away=away)
    labels = {side: names[subject] for side, subject in subjects.items()}
    canonical = {
        side: resolve_team(dict(id=subject, name=labels[side]), league, "novig")
        or "novig:team:" + subject
        for side, subject in subjects.items()
    }
    return canonical, labels, subjects


def bindings(event, markets, event_proof, *, at):
    league, eid = event["league"], event["eventId"]
    if event.get("status") != "OPEN_PREGAME" or _fresh(
        event_proof, at, EVENT_FRESH_SECONDS
    ):
        return {}
    members = {mid: m for mid, m in markets.items() if m["eventId"] == eid}
    canonical, labels, subjects = roles(members, league)
    start = datetime.fromtimestamp(event["startsTs"] / 1000, timezone.utc)
    external = event.get("ids") or {}
    shared = {}
    for native_key, typed_key, pattern in (
        ("oo", "opticodds", r"[A-Za-z0-9_-]{1,80}"),
        ("sr", "sportradar_match_urn", r"sr:match:[0-9]+"),
    ):
        value = external.get(native_key)
        if isinstance(value, str) and re.fullmatch(pattern, value):
            shared[typed_key] = value
    native = native_event(
        "novig",
        eid,
        league,
        start,
        canonical,
        labels,
        shared=shared,
        proof=dict(
            method="documented_home_handicap_and_both_native_subject_ids",
            subjects=subjects,
            vendor_ids=shared,
            source_url="https://docs.novig.com/api/catalog",
            receipt=event_proof,
        ),
    )
    output = {}
    for mid, market in members.items():
        family = {"MONEY": "moneyline", "SPREAD": "spread", "TOTAL": "total"}.get(
            market["marketType"]
        )
        if (
            not family
            or market.get("status") != "OPEN"
            or market["startsTs"] != event["startsTs"]
        ):
            continue
        outcomes = market["outcomes"]
        if len(outcomes) != 2 or len({o["outcomeId"] for o in outcomes}) != 2:
            continue
        for outcome in outcomes:
            if family == "total":
                side = outcome["name"].split()[0].lower()
                if side not in ("over", "under"):
                    continue
                line = str(F(market["strike"]))
            else:
                side = next(
                    (
                        role
                        for role, subject in subjects.items()
                        if subject == outcome.get("subjectId")
                    ),
                    None,
                )
                if side is None:
                    continue
                line = (
                    None
                    if family == "moneyline"
                    else str(F(market["strike"]) * (1 if side == "home" else -1))
                )
            (other,) = [
                o["outcomeId"]
                for o in outcomes
                if o["outcomeId"] != outcome["outcomeId"]
            ]
            settlement = settlement_profile(
                league, family, None if line is None else F(line), market.get("voids")
            )
            row = record(
                "novig",
                native,
                mid,
                outcome["outcomeId"],
                "buy",
                family,
                side,
                line,
                settlement=settlement,
                main=True if family == "moneyline" else None,
            )
            contract = expected(row)
            binding = dict(
                available=True,
                phase="scheduled",
                phase_verified=True,
                starts_at=start.isoformat(),
                league=league,
                family=family,
                selected_side=side,
                signed_line=line,
                event_id=eid,
                market_id=mid,
                outcome_id=outcome["outcomeId"],
                opposite_outcome_id=other,
                subject_role_anchors=[
                    dict(home_subject=subjects["home"], away_subject=subjects["away"])
                ],
            )
            depth = catalog_depth(binding, PublicEventDepth(members, ()), stamp(at))
            if depth.get("contract"):
                depth["contract"]["contract_id"] = contract["contract_id"]
                depth.update(
                    contract_id=contract["contract_id"],
                    identity_receipts=[event_proof],
                    _record=row,
                    _binding=binding,
                    binding_method="native_catalog_subjects_and_home_handicap",
                )
                output[contract["contract_id"]] = depth
    return output


async def discover(client, league, start, end, *, cutoff):
    inventory = await client.read_slate(league, after=start, before=end, cutoff=cutoff, include_start=True)
    by_event = defaultdict(dict)
    for mid, market in inventory.markets.items():
        by_event[market["eventId"]][mid] = market
    if not by_event:
        return {}, [inventory.reason]
    events, metadata_reason = await client.read_slate_metadata(
        league, after=start, before=end, cutoff=cutoff
    )
    output, reasons = {}, []
    for eid, markets in by_event.items():
        if client.clock() >= cutoff:
            reasons.append("discovery_deferred")
            break
        if eid in events:
            event, receipt = events[eid]
            reason = None
        else:
            event, receipt, reason = await client.read_event_metadata(eid, cutoff)
        if reason:
            reasons.append(reason)
            continue
        try:
            output.update(bindings(event, markets, receipt, at=client.clock()))
        except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
            reasons.append(str(exc))
    return output, [inventory.reason, metadata_reason, *reasons]
