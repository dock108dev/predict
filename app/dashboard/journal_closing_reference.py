"""Exact closes, bracketed same-book estimates, and labeled one-sided bounds."""

from copy import deepcopy
from fractions import Fraction as F

from app.comparison.current_pregame import (
    ReferenceInputs,
    select_reference,
    reference_candidates,
    MIN_TRUSTED_BOOKS,
)
from app.comparison.cashflows import exact_wire as wire
from app.comparison.pregame_valuation import american
from app.comparison.sgo_reference import BEST_BOOKS, american_probability
from app.comparison.pregame_reference import target
from app.storage.store import stamp


def choose(original, observations, *, at):
    family, side = original["family"], original.get("side")
    if not side:
        return None
    line = target(family, side, original["selection"].get("signed_line"))
    observations = {
        event: [
            r
            for r in rows
            if r["facts"].get("starts_at")
            and stamp(r["facts"]["starts_at"]) == stamp(original["kickoff"])
        ]
        for event, rows in observations.items()
    }
    inputs = ReferenceInputs(observations)

    def select(value):
        return select_reference(
            inputs,
            family=family,
            side=side,
            line=value,
            start=original["kickoff"],
            at=at,
        )

    try:
        ref = select(line)
        return dict(ref, closing_basis="exact_line_conservative")
    except ValueError:
        pass
    if family == "moneyline":
        return None
    # Interpolate only within one book's nearest two surrounding lines. Mixing
    # one book's lower alternate with another book's upper creates a fake curve.
    by_book = {}
    for candidate in sorted(
        {
            value
            for _, market, value in inputs.groups
            if market == family and value is not None and value != line
        }
    ):
        for ref in reference_candidates(
            inputs,
            family=family,
            side=side,
            line=candidate,
            start=original["kickoff"],
            at=at,
        ):
            by_book.setdefault(ref["book"], {})[candidate] = ref
    estimates = []
    inconsistent = set()
    for book, values in by_book.items():
        lower, upper = [v for v in values if v < line], [v for v in values if v > line]
        if not lower or not upper:
            continue
        low, high = max(lower), min(upper)
        a, b = values[low], values[high]
        pa, pb = F(a["probability"]), F(b["probability"])
        increasing = (family == "spread" and side == "home") or (
            family == "total" and side == "under"
        )
        if (increasing and pa > pb) or (not increasing and pa < pb):
            inconsistent.add(book)
            continue
        probability = ((high - line) * pa + (line - low) * pb) / (high - low)
        brackets = []
        for value, ref in ((low, a), (high, b)):
            selected = next(q for q in ref["prices"] if q["side"] == side)
            brackets.append(
                dict(
                    line=wire(value),
                    probability=ref["probability"],
                    fair_odds=ref["fair_odds"],
                    posted_odds=selected["price_american"],
                    source_at=selected["source_at"],
                )
            )
        quoted_probability = (
            (high - line) * american_probability(brackets[0]["posted_odds"])
            + (line - low) * american_probability(brackets[1]["posted_odds"])
        ) / (high - low)
        estimates.append(
            dict(
                a,
                probability=wire(probability),
                fair_decimal_odds=wire(1 / probability),
                fair_odds=american(1 / probability),
                estimated_posted_odds=american(1 / quoted_probability),
                market=dict(a["market"], line=wire(line)),
                prices=[*a["prices"], *b["prices"]],
                closing_basis="alternate_line_interpolation",
                target_line=wire(line),
                alternate_lines=brackets,
                probability_range=[wire(min(pa, pb)), wire(max(pa, pb))],
                estimate_note="Estimated within same-book alternate lines using linear interpolation of no-vig probabilities; not an observed exact-line close.",
            )
        )
    if len(estimates) >= MIN_TRUSTED_BOOKS:
        chosen = min(
            estimates,
            key=lambda ref: (F(ref["probability"]), BEST_BOOKS.index(ref["book"])),
        )
        return dict(
            chosen,
            selection_policy="lowest-no-vig-two-trusted-books-alt-interpolation-1",
            required_trusted_books=MIN_TRUSTED_BOOKS,
            trusted_book_count=len(estimates),
            candidate_probabilities={
                ref["book"]: ref["probability"] for ref in estimates
            },
        )
    if inconsistent:
        inputs = ReferenceInputs(
            {
                event: [r for r in rows if r["facts"]["venue"] not in inconsistent]
                for event, rows in observations.items()
            }
        )
    # A harder nested outcome gives a lower probability bound without assuming
    # a score distribution or pretending to have observed the original line.
    harder = []
    for _, market, candidate in inputs.groups:
        if market != family or candidate is None or candidate == line:
            continue
        direction = (
            1
            if (family == "total" and side == "over")
            or (family == "spread" and side == "away")
            else -1
        )
        if direction * (candidate - line) > 0:
            try:
                harder.append((abs(candidate - line), select(candidate)))
            except ValueError:
                pass
    if not harder:
        return None
    distance = min(d for d, _ in harder)
    ref = min(
        (r for d, r in harder if d == distance), key=lambda r: F(r["probability"])
    )
    return dict(
        ref,
        closing_basis="harder_line_probability_lower_bound",
        target_line=str(line),
        bound_line=ref["market"]["line"],
        estimate_note="Conservative probability bound from a harder line; not an observed exact-line close.",
    )


def capture(db, originals, *, at):
    events = {}
    for row in originals:
        ids = {
            p.get("event_id") for p in (row.get("reference") or {}).get("prices", [])
        }
        if row.get("source", {}).get("provider") == "sportsgameodds":
            ids.add(row["source"].get("native_event_id"))
        events[row["id"]] = ids - {None}
    ids = sorted(set().union(*events.values())) if events else []
    if not ids:
        return []
    groups = {}
    for value in db.execute(
        """SELECT s.id,s.revision,s.event_id,s.facts FROM current_sgo_reference s
      WHERE s.event_id=ANY(%s) AND NOT EXISTS(SELECT 1 FROM current_pregame_work w
      WHERE w.provider='sportsgameodds' AND w.native_event_id=s.event_id)""",
        (ids,),
    ):
        groups.setdefault(value["event_id"], []).append(value)
    result = []
    for original in originals:
        if stamp(original["kickoff"]) <= at:
            continue
        ref = choose(
            original,
            {e: groups[e] for e in events[original["id"]] if e in groups},
            at=at,
        )
        if ref:
            row = deepcopy(original)
            row.update(reference=ref, journal_reference_only=True)
            result.append(row)
    return result
