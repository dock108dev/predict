"""Read-only interpretation of the original paper witness."""

from fractions import Fraction

from app.storage.store import stamp

VERSION = "paper-trade-evidence-1"


def _age(source_at, received_at):
    if not source_at or not received_at:
        return None
    try:
        age = (stamp(received_at) - stamp(source_at)).total_seconds()
    except (TypeError, ValueError):
        return None
    return age if age >= 0 else None


def clock_counts(tickets):
    return {
        "tickets": len(tickets),
        "quote_ages_known": sum(_age(times.get("source_at"), times.get("received_at")) is not None
                                for ticket in tickets if (times := ticket.get("times"))),
        # This experiment captures price offers, without executable quote sizes
        # or verified account-level fees attached to the captured offers.
        "verified_executable_size": 0,
        "verified_actual_fees": 0,
    }


def inspect(ticket, checkpoint, offer, sized, policy):
    snapshot = checkpoint.get("snapshot") or {}
    quote = (offer.get("record") or {}).get("quote") or {}
    source = quote.get("source") or {}
    times = ticket.get("times") or {}
    fee = sized.get("fee") or {}
    mode = ticket.get("fee_mode") or {}
    decimal = (sized.get("raw") or {}).get("posted_decimal")
    probability = ticket.get("probability")
    gross_ev = (str(Fraction(probability) * Fraction(decimal) - 1)
                if probability is not None and decimal is not None else None)
    game = ticket.get("identity") or {}
    fee_state = {False: "zero_assumed", True: "captured_fee_model"}.get(mode.get("enabled"), "unknown")
    cashflows = fee.get("cashflows") or {}
    commitment = Fraction(fee["committed_usd"]) if fee.get("committed_usd") else None
    returns = {state: str(Fraction(value["net_receipt_usd"]) / commitment - 1)
               for state, value in cashflows.items() if commitment and value.get("net_receipt_usd") is not None}
    # The SGO normalizer synthesizes its native_market_id from event and line.
    # Keep the provider's odd ID and that binding distinct from a venue contract.
    return dict(version=VERSION,
        quote=dict(venue=ticket.get("venue"), provider=source.get("provider") or game.get("provider"),
                   provider_event_id=source.get("native_event_id"), provider_odd_id=source.get("native_outcome_id"),
                   source_market_key=source.get("native_market_id"),
                   venue_contract_id=source.get("venue_contract_id"),
                   exact_bet=game, posted_odds=ticket.get("posted_odds"), posted_decimal=decimal,
                   original_price=quote.get("original")),
        clocks=dict(source_at=times.get("source_at"), source_time_kind=times.get("source_time_kind"),
                    quote_received_at=times.get("received_at"),
                    quote_age_at_receipt_seconds=_age(times.get("source_at"), times.get("received_at")),
                    requested_at=checkpoint.get("requested_at"),
                    dispatched_at=(snapshot.get("times") or {}).get("dispatch_at"),
                    received_at=checkpoint.get("received_at"), known_at=checkpoint.get("known_at"),
                    captured_at=(snapshot.get("times") or {}).get("captured_at"),
                    decision_at=ticket.get("decision_at"), reconstructed_at=ticket.get("reconstructed_at")),
        probability=probability, gross_ev=gross_ev, screening_ev=ticket.get("screen_ev"), modeled_ev=ticket.get("ev"),
        kelly=dict(reference_bankroll_usd=policy.get("reference_bankroll_usd"),
                   multiplier=policy.get("kelly_multiplier"), sizing_scale_usd=policy.get("sizing_scale_usd"),
                   outcome_returns=returns, budget_usd=ticket.get("kelly_budget_usd"),
                   commitment_usd=ticket.get("cash_commitment_usd"),
                   aggregate_budget_cap_usd=policy.get("budget_cap"), compounding=policy.get("intraday_compounding")),
        fees=dict(paper_assumption=fee_state, actual_fee_evidence="unknown", modeled_entry_usd=fee.get("entry_usd")),
        size=dict(paper_assumption="quoted_price_at_modeled_stake", executable_size_evidence="unavailable",
                  executable_size_usd=None))
