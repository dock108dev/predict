"""Passive paired prices from the same frozen acquisition used by Data.

The current working-table omission grace is intentionally outside this reader.
A newer covering failed/partial capture suppresses pairing just as it does EV.
"""
from collections import defaultdict
from fractions import Fraction
from itertools import product

from app.comparison.acquisition import validate
from app.comparison.reference_scope import REFERENCE_BOOKS, public_scope
from .store import hashed, stamp


def read(db, query, *, at, can_continue=None):
    from .pregame_arbs import book_entry, cached_pair, ordered_pairs

    def checkpoint():
        if can_continue is not None and not can_continue():
            raise TimeoutError('arbitrage_read_cancelled')

    checkpoint()
    limit = max(1, min(100, int(query.get('limit', 30))))
    offset = max(0, int(query.get('offset', 0)))
    sort = query.get('sort', 'return')
    if sort not in ('return', 'newest', 'oldest', 'start'):
        raise ValueError('Unknown arbitrage order')
    scopes = db.execute('''WITH ranked AS (
        SELECT s.*,p.started_order,row_number() OVER (
          PARTITION BY s.event_id,s.family,s.period ORDER BY p.started_order DESC) newest
        FROM public.market_pull_scope s JOIN public.market_pull p USING(pull_id)
        WHERE s.coverage->>'covers_board'='true' AND s.period='full_game')
        SELECT * FROM ranked WHERE newest=1 AND state='complete'
          AND (snapshot#>>'{event,scheduled_start}')::timestamptz>%s
        ORDER BY started_order,event_id,family''', (at,)).fetchall()
    results, revisions, modes = [], [], []
    evaluated = 0
    decoded_pull, decoded, membership = None, None, set()
    for scope in scopes:
        checkpoint()
        from .acquisition_snapshot import read_snapshot

        if decoded_pull != scope['pull_id']:
            decoded_pull = scope['pull_id']
            decoded = read_snapshot(db, decoded_pull)
            receipts = db.execute('''SELECT attempt_id,receipt_sha256,received_at
                FROM public.market_pull_receipt WHERE pull_id=%s''',(decoded_pull,)).fetchall()
            membership = {(value['attempt_id'],value['receipt_sha256'],value['received_at']) for value in receipts}
        snapshot = decoded
        event = snapshot.get('event') or {}
        revisions.append([scope['pull_id'], scope['family']])
        if query.get('league') and query['league'] != event.get('competition'):
            continue
        if query.get('family') and query['family'] != scope['family']:
            continue
        if query.get('search', '').casefold() not in event.get('title', '').casefold():
            continue
        groups = defaultdict(list)
        for offer in snapshot.get('offers', []):
            # A missing probability reference does not prevent a price-only pair.
            payload = offer.get('price_payload') or offer.get('calculation_payload')
            record = offer.get('record') or {}
            if not payload or payload.get('family') != scope['family'] or payload.get('period') != scope['period']:
                continue
            if record.get('quote', {}).get('state') != 'available' or not offer.get('fee_input'):
                continue
            try:
                witness = validate((payload.get('acquisition') or {}).get('required_inputs', []))
            except (ValueError, KeyError, TypeError):
                continue
            if witness['pull_id'] != scope['pull_id']:
                continue
            if any((value['attempt_id'],value['receipt_sha256'],stamp(value['received_at'])) not in membership
                   for value in witness['required_inputs']):
                continue
            if query.get('max_age_minutes'):
                age = int(query['max_age_minutes'])
                if not 1 <= age <= 525600:
                    raise ValueError('Invalid maximum age')
                clock = payload.get('times', {}).get('source_at')
                if not clock or (at-stamp(clock)).total_seconds() > age*60:
                    continue
            payload = dict(payload, sportsbook_event_ids=[scope['event_id']])
            item = dict(payload=payload, record=record, fee_input=offer['fee_input'], sportsbook=False)
            item['cache_identity'] = hashed([scope['pull_id'], payload, offer['fee_input']])
            groups[payload['arb_key']].append(item)
        for markets in groups.values():
            checkpoint()
            template = markets[0]
            books = []
            for reference in snapshot.get('references', []):
                quote = reference.get('facts') or reference
                if query.get('reference_scope', 'selected') == 'selected' and quote.get('venue') not in REFERENCE_BOOKS:
                    continue
                book = book_entry(quote, template, at=at)
                if book:
                    proof = (book['payload'].get('acquisition') or {}).get('required_inputs', [])
                    if not proof or any((value['attempt_id'],value['receipt_sha256'],stamp(value['received_at'])) not in membership
                                        for value in proof):
                        continue
                    book['cache_identity'] = hashed([scope['pull_id'], book['payload']])
                    books.append(book)
            candidates = [*markets, *books]
            first = [item for item in candidates if item['payload']['side'] in ('home', 'over')]
            second = [item for item in candidates if item['payload']['side'] in ('away', 'under')]
            for left, right in product(first, second):
                checkpoint()
                if left['sportsbook'] and right['sportsbook']:
                    continue
                category = 'market_book' if left['sportsbook'] or right['sportsbook'] else 'market_market'
                if query.get('category') and query['category'] != category:
                    continue
                if query.get('venue') and not any(item['payload']['venue'] == query['venue'] for item in (left,right)):
                    continue
                if query.get('book') and not any(item['sportsbook'] and item['payload']['venue'] == query['book'] for item in (left,right)):
                    continue
                if left['payload']['venue'] == right['payload']['venue']:
                    continue
                if sum(1/Fraction(item['payload']['raw']['posted_decimal']) for item in (left,right)) >= 1:
                    continue
                evaluated += 1
                pair = cached_pair(left, right, at=at)
                if pair:
                    game_id = snapshot.get('canonical_game_id') or 'source:sportsgameodds:' + scope['event_id']
                    results.append(dict(pair, pull_id=scope['pull_id'],
                        market_id=game_id+'|'+scope['family']+'|'+scope['period']))
            for item in candidates:
                item.pop('_reprice_cache', None)
        if snapshot.get('fee_mode'):
            modes.append(snapshot['fee_mode'])
    results = ordered_pairs(list({pair['id']:pair for pair in results}.values()), sort)
    return dict(schema='predict-pregame-arbs-1', rows=results[offset:offset+limit],
        total=len(results),offset=offset,limit=limit,cursor=hashed(revisions),
        provider_requests=0,scheduled_calculations=0,evaluated_pairs=evaluated,
        reference_scope=public_scope(),fee_mode=modes[0] if modes and all(mode==modes[0] for mode in modes) else None,
        refresh_at=None,conditioning='decisive_completed_game',instant_fill_max_usd=None,
        population='Latest complete covering acquisition per game and market; stored prices, no fill promises.')
