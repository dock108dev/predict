"""Fee registry descriptions and examples from the dashboard's committed engine output."""

from datetime import datetime, timezone

from app.comparison.snapshot_fee_outcome import reviews
from app.comparison.current_dependencies import instant
from app.comparison.snapshot_polymarket_fee import CURRENT_CUTOVER
from app.fees import product_schedules, schedule_lifecycle, pricing
from app.fees.evidence import applies
from app.storage.store import connect


def guide():
    with connect() as db, db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        at = datetime.now(timezone.utc)
        products = product_schedules.read_all(db)
        prophetx = schedule_lifecycle.read(db)
        schedules = reviews(at)
        configured = pricing.read(db)
        examples = {
            r["venue"]: r["payload"]
            for r in db.execute(
                """
            SELECT DISTINCT ON (venue) venue,payload FROM current_pregame_calculation
            WHERE reason IS NULL AND valid_until>%s AND start_at>%s
            ORDER BY venue,start_at,contract_id""",
                (at, at),
            )
        }
    result = {}
    for venue, fallback in schedules.items():
        row = dict(venue=venue, game_state="scheduled")
        terms = (
            schedule_lifecycle.for_offer(prophetx, row, at, fallback=fallback)
            if venue == "prophetx"
            else product_schedules.for_offer(products, row, at, fallback=fallback)
        )
        available = bool(
            terms and not terms.get("unavailable_reason") and applies(terms, at)
        )
        if venue == "polymarket_us" and at >= instant(CURRENT_CUTOVER):
            available = (
                available and terms.get("published_effective_from") == CURRENT_CUTOVER
            )
        rule = pricing.select(configured, venue, None, at)
        if venue in configured and not rule:
            available = False
        if rule:
            terms = dict(terms or {}, fee_rate=rule['rate'], source_url=rule['source_url'],
                         effective_from=rule['effective_from'])
            available = True
            if nhl := pricing.select(configured, venue, 'NHL', at):
                if nhl['formula'] == 'prophetx_nhl_taker':
                    terms['nhl_taker_coefficient'] = nhl['rate']
        item = result[venue] = dict(available=available)
        if venue in configured:
            item['configured_rules'] = configured[venue]
        if not terms:
            continue
        item.update(
            {
                k: terms[k]
                for k in (
                    "source_url",
                    "document_url",
                    "published_effective_from",
                    "published_version",
                    "effective_from",
                    "reviewed_at",
                    "fee_rate",
                    "nhl_taker_coefficient",
                )
                if k in terms
            }
        )
        example = examples.get(venue)
        if example and venue in configured:
            active = pricing.select(configured, venue, example['league'], at)
            if (example['fee'].get('evidence') or {}).get('database_fee_rule') != active:
                example = None
        if available and example:
            cash = example["fee"]["cashflows"]
            item["current_example"] = dict(
                game=example["game"],
                league=example["league"],
                posted_odds=example["display"]["posted_odds"],
                after_fees=example["display"]["after_fees"],
                comparison_basis_usd="100",
                upfront_usd=example["fee"]["committed_usd"],
                entry_usd=example["fee"]["entry_usd"],
                winning_fee_usd=cash["win"]["total_fee_usd"],
                winning_receipt_usd=cash["win"]["net_receipt_usd"],
                input_revision=example.get("input_revision"),
                calculated_at=example["calculated_at"],
            )
    return result
