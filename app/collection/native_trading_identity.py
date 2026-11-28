"""Exact native selections and conservative links to Predict's existing games."""

from copy import deepcopy
from fractions import Fraction as F
from functools import lru_cache
import json
from pathlib import Path

from app.storage.store import hashed, stamp


SPORT = dict(
    NFL="american_football",
    NCAAF="american_football",
    NBA="basketball",
    NCAAB="basketball",
    NHL="ice_hockey",
    MLB="baseball",
)


def record(
    venue,
    event,
    market_id,
    outcome_id,
    native_side,
    family,
    side,
    line,
    *,
    settlement,
    main=None,
):
    """Do not copy the provider's price or contract IDs into a native offer."""
    selected = dict(
        participant=event.get(side),
        predicate=side
        if family == "total"
        else "cover"
        if family == "spread"
        else "win",
        signed_line=None if line is None else str(F(line)),
    )
    source = dict(
        provider=venue,
        native_event_id=event["id"],
        native_market_id=market_id,
        native_outcome_id=outcome_id,
        native_side=native_side,
        native_line=selected["signed_line"],
    )
    return dict(
        event=deepcopy(event),
        selection=selected,
        market_identity=dict(
            family=family, period="full_game", rules=hashed(settlement)
        ),
        quote=dict(venue=venue, source=source),
        comparison_source_metadata=dict(alternate=None if main is None else not main),
    )


def expected(row):
    from app.comparison.execution_contract import expected as exact

    return exact(row)


def native_event(
    venue,
    eid,
    league,
    start,
    roles,
    labels,
    *,
    proof,
    shared=None,
    game_number=None,
    occurrence_id=None,
    occurrence_links=(),
):
    if (
        set(roles) != {"home", "away"}
        or not all(roles.values())
        or len(set(roles.values())) != 2
    ):
        raise ValueError("native_event_roles_unverified")
    return dict(
        id=str(eid),
        competition=league,
        sport=SPORT[league],
        scheduled_start=stamp(start).isoformat(),
        **roles,
        participants={labels[side]: roles[side] for side in roles},
        title=labels["away"] + " at " + labels["home"],
        native_role_evidence=proof,
        shared_provider_ids=shared or {},
        provider=venue,
        game_number=game_number,
        occurrence_id=occurrence_id or str(eid),
        occurrence_links=list(occurrence_links),
    )


@lru_cache(maxsize=1)
def college_reviews():
    return json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "fixtures/native-trading-college-20261127.json"
        ).read_text()
    )


@lru_cache(maxsize=1)
def _college_aliases():
    document = college_reviews()
    aliases = {}
    for sgo_id, review in document["events"].items():
        for role, evidence in review["teams"].items():
            proof = dict(
                evidence,
                reviewed_role=role,
                sgo_event=sgo_id,
                novig_event=review["novig_event"],
                novig_market=review["novig_market"],
                school_schedule=review["school_schedule"],
                version=document["version"],
            )
            for venue, alias in (
                ("sportsgameodds", evidence["sgo_name"]),
                ("novig", evidence["novig_subject"]),
            ):
                key = review["league"], venue, alias
                if key in aliases and aliases[key]["canonical"] != proof["canonical"]:
                    raise ValueError("conflicting native trading college alias review")
                aliases[key] = proof
    return aliases


def _sgo_d1_alias(label, day):
    from app.normalization.mens_d1_membership import load_membership
    from .admission_enrichment import college_entrant

    membership = load_membership(day)
    reviewed = membership.lookup(name=label)
    institution = college_entrant(label, "NCAAB")
    canonical = reviewed["canonical_id"] or institution
    if not canonical or (
        institution and reviewed["canonical_id"] not in (None, institution)
    ):
        return None
    proof = membership.lookup(name=label, canonical_id=canonical)
    if proof["division"] != "d1":
        return None
    return dict(
        canonical=canonical,
        sgo_name=label,
        method="reviewed_season_alias"
        if reviewed["canonical_id"]
        else "exact_institutional_alias",
        membership_version=proof["membership_version"],
        sources=proof["sources"],
    )


def _roles(event, venue):
    """Resolve only reviewed source-local team IDs without rewriting evidence."""
    roles = {role: event.get(role) for role in ("home", "away")}
    league = event["competition"]
    if league not in ("NCAAF", "NCAAB"):
        return roles, {}
    evidence = {}
    for role, current in roles.items():
        alias = None
        if (
            venue == "sportsgameodds"
            and current == f"sportsgameodds:{league}:{event['id']}:{role}"
        ):
            observed = [
                name
                for name, value in event.get("participants", {}).items()
                if value == current
            ]
            if len(observed) == 1:
                alias = observed[0]
        if venue == "novig":
            subject = (
                (event.get("native_role_evidence") or {}).get("subjects", {}).get(role)
            )
            if subject and current == "novig:team:" + subject:
                alias = subject
        proof = _college_aliases().get((league, venue, alias))
        if not proof and alias and league == "NCAAB" and venue == "sportsgameodds":
            proof = _sgo_d1_alias(alias, stamp(event["scheduled_start"]).date())
        if proof:
            roles[role] = proof["canonical"]
            evidence[role] = proof
    return roles, evidence


def _novig_role_proof(event, anchor, source_roles, native_roles):
    proof = anchor.get("novig_subject_roles")
    source = anchor["event"]
    subjects = (event.get("native_role_evidence") or {}).get("subjects")
    if (
        event["provider"] != "novig"
        or not proof
        or proof["event_id"] != event["id"]
        or (source.get("shared_provider_ids") or {}).get("novig_event") != event["id"]
        or proof["sgo_event_id"] != source["id"]
        or proof["subjects"] != subjects
        or stamp(source["scheduled_start"]) != stamp(event["scheduled_start"])
    ):
        return None
    # Exact subject IDs may establish unresolved aliases. A known canonical
    # team disagreement remains a contradiction even with typed event links.
    if any(
        native_roles[role] not in (source_roles[role], "novig:team:" + subjects[role])
        for role in subjects
    ):
        return None
    return proof


def link(event, anchors, *, prior=None):
    """Both roles and one occurrence must agree; nearby kickoffs alone never join.

    Typed venue links can explain provider schedule skew, with both original
    clocks retained. The canonical/Paper clock always remains the SGO clock.
    """
    exact_candidates, strong_candidates, conflicts = [], [], {}
    native = event.get("shared_provider_ids") or {}
    native_start = stamp(event["scheduled_start"])
    native_roles, native_aliases = _roles(event, event["provider"])
    occurrence = event.get("occurrence_id", event["id"])
    venue_ids = {event["id"], occurrence, *event.get("occurrence_links", ())}
    previous_sgo = (
        prior.get("sgo_event_id")
        if prior and prior.get("roles") == native_roles
        else None
    )
    previous_present = False
    for anchor in anchors:
        source = anchor["event"]
        previous_present |= source["id"] == previous_sgo
        if source["competition"] != event["competition"] or source.get(
            "schedule_conflict"
        ):
            continue
        shared = source.get("shared_provider_ids") or {}
        venue_id = shared.get(event["provider"] + "_event")
        common = {
            key for key in shared.keys() & native.keys() if shared[key] and native[key]
        }
        same_time = stamp(source["scheduled_start"]) == native_start
        retained = source["id"] == previous_sgo
        same_typed_id = bool(venue_id and str(venue_id) in venue_ids) or any(
            str(shared[key]) == str(native[key]) for key in common
        )
        if (
            venue_id
            and str(venue_id) not in venue_ids
            or any(str(shared[key]) != str(native[key]) for key in common)
        ):
            if retained or same_typed_id or same_time and _roles(source, "sportsgameodds")[0] == native_roles:
                conflicts[source["id"]] = "typed_event_id_conflict"
            continue
        typed = bool(venue_id or common)
        if not (typed or same_time or retained):
            continue
        # Baseball needs an occurrence number or a shared event ID. A time
        # match cannot distinguish a separately listed doubleheader game.
        if event["competition"] == "MLB":
            numbers = {
                str(value)
                for value in (event.get("game_number"), source.get("game_number"))
                if value
            }
            if (
                len(numbers) > 1
                or not (typed or retained)
                and not all((event.get("game_number"), source.get("game_number")))
            ):
                if typed or retained:
                    conflicts[source["id"]] = "doubleheader_occurrence_conflict"
                continue
        source_roles, source_aliases = _roles(source, "sportsgameodds")
        if len(set(source_roles.values())) != 2 or not all(source_roles.values()):
            continue
        novig_roles = None
        if source_roles != native_roles:
            novig_roles = _novig_role_proof(event, anchor, source_roles, native_roles)
            if not novig_roles:
                if typed or retained or set(source_roles.values()) == set(native_roles.values()):
                    conflicts[source["id"]] = "team_role_conflict"
                continue
        method = (
            "typed_source_event_and_retained_subject_roles"
            if novig_roles
            else "typed_source_event_and_both_roles"
            if typed
            else "retained_source_event_and_both_roles"
            if retained and not same_time
            else "unique_exact_schedule_and_both_roles"
        )
        (strong_candidates if typed or retained else exact_candidates).append(
            (anchor, source_aliases, method, novig_roles)
        )
    if previous_sgo and not previous_present and not strong_candidates and not conflicts:
        # A current source row can close or age out before a later venue clock.
        # Keep the accepted occurrence for passive closure guards. It cannot
        # supply a reference while it is absent from the current anchor slate.
        return dict(
            prior,
            status="unresolved",
            reason="sgo_occurrence_unavailable",
            native_start=event["scheduled_start"],
            schedule_skew_seconds=str(
                (native_start - stamp(prior["sgo_start"])).total_seconds()
            ),
        )
    candidates = strong_candidates or exact_candidates
    if len(candidates) != 1:
        unresolved = dict(
            canonical_game_id="source:" + event["provider"] + ":" + occurrence,
            sgo_event_id=None,
            status="unresolved",
            reason=("ambiguous_occurrence" if candidates else
                    "occurrence_identity_conflict" if conflicts else "occurrence_unmatched"),
            native_start=event["scheduled_start"],
        )
        if conflicts:
            unresolved["evidence"] = {"candidate_rejections": conflicts}
        return unresolved
    anchor, source_aliases, method, novig_roles = candidates[0]
    source = anchor["event"]
    schedule = source.get("schedule_metadata") or {}
    original = (schedule.get("reviewed_correction") or {}).get("original", {})
    return dict(
        canonical_game_id=anchor["canonical_game_id"],
        sgo_event_id=source["id"],
        status="matched",
        method=method,
        native_start=event["scheduled_start"],
        sgo_start=source["scheduled_start"],
        sgo_original_start=original.get("start", source["scheduled_start"]),
        sgo_prior_start=source.get("original_start"),
        schedule_skew_seconds=str(
            (native_start - stamp(source["scheduled_start"])).total_seconds()
        ),
        roles=native_roles,
        evidence=dict(
            native=event.get("native_role_evidence"),
            sgo=source.get("schedule_metadata"),
            shared_provider_ids=source.get("shared_provider_ids"),
            **({"novig_subject_roles": novig_roles} if novig_roles else {}),
            **(
                {
                    "college_review": dict(
                        novig=native_aliases, sportsgameodds=source_aliases
                    )
                }
                if native_aliases or source_aliases
                else {}
            ),
        ),
    )
