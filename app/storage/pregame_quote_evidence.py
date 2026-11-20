"""Selected-quote venue evidence; no invented URL or aggregate liquidity."""

from fractions import Fraction as F
from urllib.parse import urlsplit, urlunsplit

HOSTS = {
    "novig": {"novig.com", "www.novig.com"},
    "kalshi": {"kalshi.com", "www.kalshi.com"},
    "polymarket_us": {"polymarket.us", "www.polymarket.us"},
    "prophetx": {"prophetx.co", "www.prophetx.co"},
    "fanduel": {"sportsbook.fanduel.com"},
    "draftkings": {"sportsbook.draftkings.com"},
    "betmgm": {"sports.betmgm.com"},
    "caesars": {"sportsbook.caesars.com"},
    "betrivers": {"www.betrivers.com"},
}


def market_link(venue, value):
    if not isinstance(value, dict):
        return None
    host, path = value.get("host"), value.get("path")
    if host not in HOSTS.get(venue, set()) or not isinstance(path, str):
        return None
    if (
        len(path) > 2048
        or "\\" in path
        or ".." in path
        or any(ord(c) <= 32 for c in path)
    ):
        return None
    parsed = urlsplit(path)
    if (
        not path.startswith("/")
        or path.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.path == "/"
    ):
        return None
    return urlunsplit(("https", host, parsed.path, parsed.query, ""))


def enrich(db, rows):
    if not rows:
        return rows
    entries = db.execute(
        "SELECT contract_id,record FROM current_pregame_price WHERE contract_id=ANY(%s)",
        ([r["id"] for r in rows],),
    ).fetchall()
    records = {e["contract_id"]: e["record"] for e in entries}
    native_ids = [
        cid
        for cid, record in records.items()
        if record["quote"]["source"]["provider"] == record["quote"]["venue"]
        and record["quote"]["venue"] in ("kalshi", "polymarket_us")
    ]
    books = {}
    if native_ids:
        from .current_rows import CurrentRowStore

        books = CurrentRowStore(db).native_valuation_asks(native_ids, cap=1)
    result = []
    for row in rows:
        value = dict(
            row,
            available_size=dict(
                status="unknown",
                quantity=None,
                reason="No price-specific quantity is supplied by this observation.",
            ),
        )
        record = records.get(row["id"])
        if (
            record
            and record["quote"]["original"] == row["posted"]
            and record["quote"]["times"] == row["times"]
        ):
            meta = record.get("comparison_source_metadata") or {}
            link = market_link(row["venue"], meta.get("bookmaker_market_link"))
            if link:
                value["verification_link"] = dict(
                    url=link,
                    scope="market",
                    basis="Retained provider market link; verify venue identity and terms",
                )
            book = books.get(row["id"])
            if book:
                from app.dashboard.current_contract import price

                cost = price(dict(original=row["posted"]))
                level = book["levels"][0]
                if F(level[0]) == cost and F(level[2]) > 0:
                    value["available_size"] = dict(
                        status="observed",
                        quantity=str(level[2]),
                        unit="contracts",
                        source_at=book["source_at"].isoformat()
                        if hasattr(book["source_at"], "isoformat")
                        else book["source_at"],
                        received_at=book["received_at"].isoformat()
                        if hasattr(book["received_at"], "isoformat")
                        else book["received_at"],
                        reason="Observed top ask at this exact price; current execution and fills unverified.",
                    )
        result.append(value)
    return result
