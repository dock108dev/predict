"""Frozen exact inputs and reproducible mathematics; no account or network reads."""

from copy import deepcopy
from fractions import Fraction as F

from app.comparison import current_pregame as math
from app.comparison.cashflows import exact_wire as wire
from app.storage.store import hashed, stamp

VERSION = "research-exact-cashflow-1"


def probability(reference):
    """Reconstruct the coherent baseline using its original fixed-priority policy."""
    if reference.get("policy_version") not in math.COHERENT_POLICIES:
        raise ValueError("research_probability_policy_unsupported")
    if not reference.get("probabilities"):
        return None
    observations = {}
    for candidate in reference["candidates"]:
        for q in candidate["prices"]:
            observations.setdefault(candidate["event_id"], []).append(dict(
                id=q["input_id"], revision=q["input_revision"], facts=q,
            ))
    market = reference["market"]
    side = reference["selected_outcome"]
    family = market["family"]
    line = market["line"]
    selection = (
        dict(predicate=side, signed_line=line)
        if family == "total" else
        dict(participant=side, predicate="win")
        if family == "moneyline" else
        dict(participant=side, predicate="cover",
             signed_line=wire(F(line) if side == "home" else -F(line)))
    )
    # Reference eligibility also needs the event start, retained in every snapshot.
    record = dict(
        event=dict(home="home", away="away", scheduled_start=reference["starts_at"]),
        market_identity=dict(family=family), selection=selection,
    )
    result = math.coherent_reference(
        record, observations, at=stamp(reference["cutoff"]),
        policy=reference["policy_version"], evaluated_book=reference.get("evaluated_book"),
    )
    # starts_at is a snapshot envelope, not part of the baseline selector's basis.
    expected = {key: value for key, value in reference.items() if key != "starts_at"}
    if result != expected:
        raise ValueError("research_probability_reproduction_mismatch")
    return F(result["probability"])


def freeze(payload, *, record=None, fee_input=None):
    """Keep exact source, applicability, rounding, cashflows and both policies.

    This is an arithmetic witness. It does not establish predictive quality,
    settlement equivalence, availability of a fill, or realized trading profit.
    """
    source = deepcopy(payload)
    reference = source.get("coherent_probability")
    if reference and reference.get("probabilities"):
        reference["starts_at"] = source["kickoff"]
    for alternative in source.get("alternative_probabilities", {}).values():
        if alternative.get("probabilities"):
            alternative["starts_at"] = source["kickoff"]
    inputs = dict(
        calculation=source, source_record=deepcopy(record),
        fee_input=deepcopy(fee_input),
        settlement_assumptions=dict(
            conditioning="decisive_completed_game",
            supported_states=["win", "loss"],
            exceptional_outcomes="tie_push_void_not_modelled",
        ),
    )
    result = recompute(inputs)
    alternatives = {}
    for policy, alternative in source.get("alternative_probabilities", {}).items():
        other = deepcopy(inputs)
        other["calculation"]["coherent_probability"] = alternative
        alternatives[policy] = recompute(other)
    body = dict(version=VERSION, inputs=inputs, results=result, alternative_results=alternatives)
    return dict(body, id=hashed(body))


def recompute(inputs):
    saved = inputs["calculation"]
    fee = saved.get("fee")
    if not fee or fee.get("committed_usd") is None:
        ref = saved.get("coherent_probability")
        p = probability(ref) if ref and ref.get("probabilities") else None
        return dict(status="probability_only" if p is not None else "unavailable",
                    reason="fee_cashflows_unavailable" if p is not None else
                    (ref or {}).get("reason") or "coherent_reference_unavailable",
                    probability=wire(p) if p is not None else None,
                    net_ev=None, expected_profit_usd=None)
    committed = F(fee["committed_usd"])
    if committed <= 0:
        raise ValueError("research_committed_cash_invalid")
    states = fee["cashflows"]
    if set(states) != {"win", "loss"}:
        raise ValueError("research_settlement_states_unsupported")
    ref = saved.get("coherent_probability")
    if not ref or ref.get("probabilities") is None:
        return dict(status="unavailable", reason=(ref or {}).get("reason") or
                    "coherent_reference_unavailable", probability=None,
                    net_ev=None, expected_profit_usd=None)
    p = probability(ref)
    ev, _, _ = math.cashflow_values(dict(probability=wire(p)), states, committed)
    return dict(status="calculated", reason=None, probability=wire(p),
                net_ev=wire(ev), expected_profit_usd=wire(committed * ev),
                committed_usd=wire(committed),
                probability_policy=ref["policy_version"],
                baseline_id=ref["baseline_id"],
                screen_policy=(saved.get("reference") or {}).get("selection_policy"),
                screen_net_ev=saved.get("raw", {}).get("net_ev"))


def reproduce(snapshot):
    body = {key: snapshot[key] for key in ("version", "inputs", "results")}
    if "alternative_results" in snapshot:
        body["alternative_results"] = snapshot["alternative_results"]
    if snapshot["id"] != hashed(body) or snapshot["version"] != VERSION:
        raise ValueError("research_calculation_integrity")
    result = recompute(snapshot["inputs"])
    if result != snapshot["results"]:
        raise ValueError("research_calculation_reproduction_mismatch")
    for policy, value in snapshot.get("alternative_results", {}).items():
        other = deepcopy(snapshot["inputs"])
        other["calculation"]["coherent_probability"] = other["calculation"]["alternative_probabilities"][policy]
        if recompute(other) != value:
            raise ValueError("research_alternative_reproduction_mismatch")
    # When the full normalized source and fee rule were supplied, also run the
    # existing quantity/rounding owner. No fee schedule is looked up here.
    inputs, original = snapshot["inputs"], snapshot["inputs"]["calculation"]
    if inputs["source_record"] is not None and inputs["fee_input"] is not None:
        value = math.calculate(
            inputs["source_record"], original.get("reference"), inputs["fee_input"],
            at=stamp(original["calculated_at"]), game_key=original["game_key"],
            amount=F(original["fee"]["comparison_basis_usd"]),
        )
        same_fee = value["fee"] == original["fee"]
        if original.get("version") == "predict-current-pregame-6":
            # V6 did not assert purchase/quantity/increment fields. Verify every
            # field it did retain; an explicit null is still an asserted value.
            # Never enrich or rewrite the original payload to make it pass.
            same_fee = all(key in value["fee"] and value["fee"][key] == asserted
                           for key, asserted in original["fee"].items())
        if not same_fee or any(value[key] != original[key] for key in ("raw", "posted")):
            raise ValueError("research_fee_cashflow_reproduction_mismatch")
    return result
