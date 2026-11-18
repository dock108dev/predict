"""Observed sportsbook prices for one exact pregame bet; no derived prices."""

from fractions import Fraction
from app.storage.store import stamp
from app.comparison.sportsbooks import SPORTSBOOKS


def matching_prices(row, observations, *, at):
    reference = row["reference"]
    side = reference.get("selected_outcome")
    event_ids = {p.get("event_id") for p in reference.get("prices", [])} - {None}
    if not side or not event_ids:
        return []
    odd_ids = {
        p.get("odd_id") for p in reference.get("prices", []) if p.get("side") == side
    } - {None}
    line = row["selection"].get("signed_line")
    expected = None if line is None else Fraction(line)
    matches = {}
    for quote in observations:
        try:
            if quote.get("venue") not in SPORTSBOOKS:
                continue
            if (
                quote.get("event_id") not in event_ids
                or (odd_ids and quote.get("odd_id") not in odd_ids)
                or quote.get("league") != row["league"]
                or quote.get("market") != row["family"]
                or (not odd_ids and quote.get("side") != side)
                or quote.get("partition") == "three_way"
                or quote.get("period") != "game"
                or quote.get("phase") != "pregame"
                or quote.get("available") is not True
                or quote.get("provider_available", True) is not True
                or stamp(quote["starts_at"]) != stamp(row["kickoff"])
                or (None if quote.get("line") is None else Fraction(quote["line"]))
                != expected
            ):
                continue
            status = quote.get("event_status") or {}
            if any(
                status.get(key)
                for key in (
                    "live",
                    "started",
                    "ended",
                    "finalized",
                    "cancelled",
                    "suspended",
                    "delayed",
                )
            ):
                continue
            price = Fraction(quote["price_american"])
            if -100 < price < 100:
                continue
            clock = stamp(quote["source_at"] or quote["received_at"])
            if clock > stamp(quote["received_at"]) or stamp(quote["received_at"]) > at:
                continue
            item = dict(
                book=quote["venue"],
                posted_odds=quote["price_american"],
                line=line,
                side=side,
                source_at=quote.get("source_at"),
                received_at=quote["received_at"],
                provider=quote.get("provider"),
                is_reference=quote["venue"] == reference["book"],
            )
            matches.setdefault(quote["venue"], []).append((clock, item))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
    result = []
    for candidates in matches.values():
        newest = max(clock for clock, _ in candidates)
        latest = [item for clock, item in candidates if clock == newest]
        if len({item["posted_odds"] for item in latest}) == 1:
            result.append(latest[0])
    preferred = ("fanduel", "draftkings", "betmgm", "caesars", "betrivers")
    return sorted(
        result,
        key=lambda item: (
            not item["is_reference"],
            preferred.index(item["book"])
            if item["book"] in preferred
            else len(preferred),
            item["book"],
        ),
    )


def read_prices(db, rows, *, at):
    if not rows:
        return []
    event_ids = sorted(
        {
            p["event_id"]
            for r in rows
            for p in r["reference"]["prices"]
            if p.get("event_id")
        }
    )
    if not event_ids:
        return []
    observations = [
        item["facts"]
        for item in db.execute(
            "SELECT facts FROM current_sgo_reference WHERE event_id=ANY(%s)",
            (event_ids,),
        )
    ]
    return matching_prices(rows[0], observations, at=at)
