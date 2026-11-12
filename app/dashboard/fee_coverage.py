"""Reconcile an unfiltered ordinary publication to its working source inventory."""
from collections import Counter, defaultdict
from itertools import product
from app.comparison.snapshot_fee_outcome import CLASSES, FAMILIES, VENUES
from app.storage.comparison_snapshot import SPORTS
from .snapshot_display import ranking_value


def source_inventory(db, dependencies):
    # Use the same working keys, horizon and transaction as price authority.
    # A working price can be stale or unpublished, even if the catalog lists it.
    return db.execute("""SELECT c.id, c.venue, e.competition AS league,
        c.facts#>>'{market_identity,family}' AS family,
        c.facts#>>'{market_identity,period}' AS period
        FROM current_contract c JOIN current_event e ON e.id=c.event_id
        WHERE c.id=ANY(%s) AND c.venue=ANY(%s)""",
        (list(dependencies), list(VENUES))).fetchall()


def source_key(row):
    return row['current_authority']['price'].get('dependency') or row['id']


def offer_key(row):
    source = row.get('source', {})
    if source.get('provider') == 'the_odds_api':
        # These routes refresh independently, but can publish the exact same
        # venue/event/line/side. The underlying source key encodes that line.
        return (row['venue'], source['provider'], source['native_event_id'],
                source['native_market_id'].removeprefix('alternate:'),
                source['native_outcome_id'], source['native_side'])
    return source_key(row)


def census(result, inventory, *, pairs=(), policy=None):
    by_offer = {}
    published_source_keys = set()
    pair_keys = {}
    outside = Counter()
    current_presentations = 0
    duplicate_rows = 0
    for row in result['rows']:
        family = row['market']['market']
        if row['venue'] not in VENUES or row['league'] not in SPORTS or family not in FAMILIES:
            outside[(row['venue'], row['league'], family, row['market']['period'])] += 1
            continue
        offer_id = offer_key(row)
        published_source_keys.add(source_key(row))
        if row['price_current']:
            current_presentations += 1
            if row.get('publication_policy') == policy:
                pair_keys[row['id']] = offer_id
        previous = by_offer.get(offer_id)
        if previous is not None:
            duplicate_rows += 1
            if (bool(previous['price_current']), previous.get('captured_at') or '') >= (
                    bool(row['price_current']), row.get('captured_at') or ''):
                continue
        by_offer[offer_id] = row

    def bucket():
        return Counter(dict.fromkeys(('published', 'retained_unavailable', 'current', 'covered', 'uncovered',
            'exact_pinnacle_reference', 'before_fee_ev', 'reviewed_after_fee_ev', 'conservative_after_fee_ev',
            'any_after_fee_ev', *CLASSES), 0))

    totals = bucket()
    dimensions = defaultdict(bucket)
    providers = defaultdict(bucket)
    reasons = defaultdict(Counter)
    provider_reasons = defaultdict(Counter)
    price_gaps = Counter()
    for row in by_offer.values():
        phase = {'scheduled': 'pregame', 'live': 'in_game'}.get(row.get('game_state'), row.get('game_state', 'unknown'))
        key = (row['venue'], row['league'], row['market']['market'], row['market']['period'], phase)
        provider_key = (row.get('source', {}).get('provider') or 'unknown', *key)
        count = Counter(published=1)
        if row['price_current']:
            fee = row.get('trade_fee') or {}
            covered = bool(fee.get('available'))
            classification = fee.get('classification', 'unknown')
            count.update(current=1, covered=int(covered), uncovered=int(not covered))
            count[classification] += 1
            exact_reference = bool(row.get('exact_pinnacle_reference_current'))
            count['exact_pinnacle_reference'] = int(exact_reference)
            for label, metric in (
                    ('before_fee_ev', 'gross_return_percent'),
                    ('reviewed_after_fee_ev', 'conditional_return_percent'),
                    ('conservative_after_fee_ev', 'conservative_return_percent')):
                count[label] = int(ranking_value(row, metric, current=True) is not None)
            count['any_after_fee_ev'] = int(count['reviewed_after_fee_ev'] or count['conservative_after_fee_ev'])
            if not covered:
                reason = fee.get('reason') or 'fee_outcome_not_published'
                reasons[key][reason] += 1
                provider_reasons[provider_key][reason] += 1
        else:
            count['retained_unavailable'] = 1
            price_gaps.update(row.get('price_reasons') or ['source_price_not_current'])
        totals.update(count)
        dimensions[key].update(count)
        providers[provider_key].update(count)

    def with_rate(count):
        return dict(count, fee_coverage_percent=round(100 * count['covered'] / count['current'], 4)
                    if count['current'] else None)

    source = defaultdict(Counter)
    unpublished = 0
    published_working = set()
    for item in inventory:
        family = {'moneyline': 'winner'}.get(item['family'], item['family'])
        key = (item['venue'], item['league'], family, item['period'])
        if item['league'] not in SPORTS or family not in FAMILIES:
            source[key]['outside_scope_working_prices'] += 1
            continue
        source[key]['working_prices'] += 1
        if item['id'] not in published_source_keys:
            source[key]['unpublished_working_prices'] += 1
            unpublished += 1
        else:
            published_working.add(item['id'])
            source[key]['published_working_prices'] += 1

    current_pairs = {frozenset(pair_keys[leg] for leg in pair['legs'])
                     for pair in pairs if pair.get('before_fees') and all(leg in pair_keys for leg in pair['legs'])}
    current_pairs = {legs for legs in current_pairs if len(legs) == 2}
    both_fees = sum(all((by_offer[key].get('trade_fee') or {}).get('available') for key in legs)
                    for legs in current_pairs)

    def labels(key):
        return dict(zip(('venue', 'league', 'family', 'period', 'phase'), key))

    gaps = Counter()
    for counts in reasons.values():
        gaps.update(counts)
    present = {key[:3] for key, counts in dimensions.items() if counts['current']}
    working = {key[:3] for key, counts in source.items() if counts['working_prices']}
    return dict(scope=dict(venues=VENUES, leagues=SPORTS, families=FAMILIES,
                           publication=result.get('scope'), profile='manual_retail'),
                total=with_rate(totals), missing_reasons=dict(gaps.most_common()),
                by_scope=[dict(labels(key), **with_rate(counts), missing_reasons=dict(reasons[key]))
                          for key, counts in sorted(dimensions.items(), key=lambda item: str(item[0]))],
                by_provider=[dict(provider=key[0], **labels(key[1:]), **with_rate(counts),
                                  missing_reasons=dict(provider_reasons[key]))
                             for key, counts in sorted(providers.items(), key=lambda item: str(item[0]))],
                duplicate_published_rows=duplicate_rows, current_presentation_rows=current_presentations,
                published_source_price_keys=len(published_source_keys),
                retained_price_gap_reasons=dict(price_gaps.most_common()),
                published_working_prices=len(published_working),
                unpublished_working_prices=unpublished,
                published_without_working_price=len(published_source_keys - published_working),
                pair_coverage=dict(current_before_fee_pairs=len(current_pairs),
                    both_legs_have_normalized_fee=both_fees),
                source_price_inventory=[dict(labels(key), **counts) for key, counts in sorted(source.items(), key=lambda item: str(item[0]))],
                cohorts_without_current_prices=[dict(labels(key), working_prices_present=key in working)
                    for key in product(VENUES, SPORTS, FAMILIES) if key not in present],
                outside_scope_published=[dict(labels(key), rows=n) for key, n in outside.items() if n],
                source_states=result['publication'].get('sources', {}),
                read_at=result['publication'].get('read_at'))
