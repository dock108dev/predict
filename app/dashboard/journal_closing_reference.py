"""Conservative exact-line references, or an explicitly labeled harder-line bound."""

from copy import deepcopy
from fractions import Fraction as F

from app.comparison.current_pregame import ReferenceInputs, select_reference
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
