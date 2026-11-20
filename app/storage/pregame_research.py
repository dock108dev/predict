"""Read-only amount research using retained price inputs and the calculation owners.

Refuse changed inputs instead of silently pricing a different observation. Expired
eligibility is permitted here: all outputs describe research, never executable size.
"""

from fractions import Fraction as F

from app.comparison.current_pregame import calculate
from app.comparison.pregame_arbs import evaluate
from app.comparison.pregame_valuation import parse_amount
from app.storage.pregame_arbs import book_entry


class ChangedInputs(ValueError):
    pass


def same_quote(a, b):
    return all(
        a.get(k) == b.get(k)
        for k in ("id", "game_key", "venue", "selection", "posted", "source", "times")
    )


def research(db, body, *, at):
    if not isinstance(body, dict) or set(body) != {"kind", "snapshot", "amount"}:
        raise ValueError("Supply a research snapshot and cash budget")
    amount = parse_amount(body["amount"])
    snapshot, kind = body["snapshot"], body["kind"]
    if kind not in ("ev", "arb") or not isinstance(snapshot, dict):
        raise ValueError("Unknown research kind")
    rows = snapshot.get("legs") if kind == "arb" else [snapshot]
    if not isinstance(rows, list) or len(rows) != (2 if kind == "arb" else 1):
        raise ValueError("Exact research legs required")
    if not all(isinstance(r, dict) and isinstance(r.get("id"), str) for r in rows):
        raise ValueError("Exact research identities required")
    entries = []
    for row in rows:
        if row["id"].startswith("book:"):
            entries.append(None)
            continue
        entry = db.execute(
            """SELECT p.payload,p.record,p.fee_input,c.payload AS calculation
            FROM current_pregame_price p LEFT JOIN current_pregame_calculation c
            ON c.contract_id=p.contract_id WHERE p.contract_id=%s""",
            (row["id"],),
        ).fetchone()
        if not entry or not same_quote(row, entry["payload"]):
            raise ChangedInputs(
                "The retained price inputs changed. Original research is preserved; open current alternatives to evaluate a new amount."
            )
        if row.get("fee", {}).get("evidence") != entry["payload"]["fee"].get(
            "evidence"
        ):
            raise ChangedInputs(
                "Fee inputs changed. Reopen the current quote before evaluating another amount."
            )
        entries.append(entry)
    for i, entry in enumerate(entries):
        if entry is not None:
            continue
        template = next((e for e in entries if e and e.get("record")), None)
        if template is None:
            raise ValueError("A market leg is required")
        quotes = db.execute(
            "SELECT facts FROM current_sgo_reference WHERE event_id=ANY(%s) AND facts->>'venue'=%s",
            (template["payload"].get("sportsbook_event_ids", []), rows[i].get("venue")),
        )
        candidates = [book_entry(q["facts"], template, at=at) for q in quotes]
        entries[i] = next(
            (e for e in candidates if e and same_quote(rows[i], e["payload"])), None
        )
        if entries[i] is None:
            raise ChangedInputs(
                "The opposite sportsbook observation changed. Original research is preserved; check current alternatives."
            )
    if kind == "ev":
        entry = entries[0]
        reference = (entry.get("calculation") or {}).get("reference")
        if rows[0].get("reference") != reference:
            raise ChangedInputs(
                "The reference changed. Reopen the comparison before evaluating another amount."
            )
        result = calculate(
            entry["record"],
            reference,
            entry["fee_input"],
            at=at,
            game_key=rows[0]["game_key"],
            amount=F(amount),
        )
        result["ev_unavailable_reason"] = rows[0].get("ev_unavailable_reason")
    else:
        result = evaluate(*entries, at=at, budget=F(amount), positive_only=False)
        if result is None:
            raise ValueError("This amount cannot fund both legal modeled quantities")
    from .pregame_quote_evidence import enrich

    if kind == "arb":
        result["legs"] = enrich(db, result["legs"])
    else:
        result = enrich(db, [result])[0]
    return dict(
        result=result, research_only=True, provider_requests=0, journal_writes=0
    )
