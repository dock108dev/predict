"""Connect verified SGO receipt-cutoff replay to the general research population."""

from datetime import date
from fractions import Fraction as F

from app.comparison import current_pregame as math
from app.comparison.cashflows import exact_wire as wire
from app.storage.odds_archive import digest
from app.storage.odds_archive_replay import replay_event
from app.storage.store import stamp


def from_changes(changes, *, event_id, case, as_of, policy=math.COHERENT_POLICY):
    """Rebuild a whole eligible pair without later receipts or inferred depth.

    Compact archives establish receipt causality. They do not establish every
    original internal knowledge transition or continuous source freshness.
    """
    if len(changes) > 100000:
        raise ValueError("research_replay_event_capacity")
    deadline = stamp(as_of)
    accepted = []
    for row in changes:
        if len(row) != 9 or row[0] != digest(row[1:]):
            raise ValueError("research_replay_record_integrity")
        if row[4] in (None, event_id) and stamp(row[6]) <= deadline:
            accepted.append(row)
    accepted.sort(key=lambda row: (stamp(row[6]), row[0]))
    contexts = [r for r in accepted if r[4] == event_id and r[2] == "event"
                and isinstance(r[8], dict) and "teams" in r[8]]
    if not contexts:
        raise ValueError("research_replay_event_context_unavailable")
    event = contexts[-1][8]
    if stamp(event["starts_at"]) != stamp(case["starts_at"]):
        raise ValueError("research_replay_occurrence_conflict")
    from app.collection.sportsgameodds_current_rows import event_record
    from app.normalization.college_registry import sgo_registry

    canonical = event_record(dict(event_id=event_id, league=event["league"],
        teams=event["teams"], starts_at=event["starts_at"], status=event["event_status"]),
        "0" * 64, contexts[-1][6], sgo_registry())
    if any(canonical[k] != case[k] for k in ("home", "away")):
        raise ValueError("research_replay_participant_roles_conflict")
    definitions, tops = {}, {}
    for row in accepted:
        if row[4] != event_id:
            continue
        if row[2] == "definition" and isinstance(row[8], dict) and "venue" in row[8]:
            definitions.setdefault(row[3], []).append(row)
        if row[2] == "top":
            tops[row[3]] = row
    references, input_changes = [], []
    for scope, top in sorted(tops.items()):
        eligible = [r for r in definitions.get(scope, ()) if stamp(r[6]) <= stamp(top[6])]
        definition = eligible[-1] if eligible else None
        if not definition:
            continue
        facts = dict(definition[8], provider="sportsgameodds", event_id=event_id,
            phase=event["phase"], source_at=top[5], received_at=top[6],
            price_american=top[8][0], available=top[8][4])
        if facts.get("side") in ("home", "away") and canonical.get("source_participant_roles"):
            roles = canonical["source_participant_roles"]
            source_role = facts["side"]
            # A nontrivial historical role correction needs its exact owner;
            # do not guess an orientation from display names in a replay.
            if isinstance(roles, dict) and roles.get(source_role) not in (None, source_role, canonical[source_role]):
                raise ValueError("research_replay_source_roles_unverified")
        from app.storage.sportsgameodds_reference import quote_identity
        identity = quote_identity(event_id, facts["venue"], facts["odd_id"], facts["line"])
        if digest(["sportsgameodds", event_id, identity]) != scope:
            raise ValueError("research_replay_quote_identity_conflict")
        references.append(dict(id=identity, revision=top[7][0], facts=facts))
        input_changes.extend([top[0], definition[0]])
    family, line = case["family"], case["line"]
    anchor = "over" if family == "total" else "home"
    selection = (dict(predicate=anchor, signed_line=line) if family == "total" else
                 dict(predicate="win" if family == "moneyline" else "cover",
                      participant=case["home"], signed_line=line))
    record = dict(event=canonical, market_identity=dict(family=family), selection=selection)
    try:
        baseline = math.coherent_reference(record, {event_id: references}, at=deadline, policy=policy)
    except ValueError as exc:
        baseline = dict(policy_version=policy, probabilities=None, probability=None, reason=str(exc))
    gaps = [r[0] for r in accepted if r[2] in ("source_status", "runtime_status", "discovery_gap")]
    payload = dict(id="archive:" + case["case_key"], game_key=case["event_id"],
        kickoff=case["starts_at"], family=family, period=case["period"], selection=selection,
        calculated_at=deadline.isoformat(), fee=None, reference=None,
        coherent_probability=baseline, raw=dict(net_ev=None),
        times=dict(source_at=None, received_at=contexts[-1][6]),
        replay=dict(feed="sportsgameodds", source_event_id=event_id,
            receipt_cutoff=deadline.isoformat(), original_knowledge_cutoff=None,
            reconstructed_at=None, verified_input_change_ids=sorted(set(input_changes)),
            event_change_id=contexts[-1][0], status_change_ids=gaps,
            freshness="not_established", depth="not_retained_for_sgo",
            calculation_scope="probability_only; execution fees and quantity absent"),
    )
    return dict(payload=payload, source_records=len(accepted), provider_requests=0)


def replay(root, *, event_id, case, first_day, last_day, as_of, policy=math.COHERENT_POLICY):
    changes = replay_event(root, "sportsgameodds", event_id,
        date.fromisoformat(first_day) if isinstance(first_day, str) else first_day,
        date.fromisoformat(last_day) if isinstance(last_day, str) else last_day, as_of)
    return from_changes(changes, event_id=event_id, case=case, as_of=as_of, policy=policy)
