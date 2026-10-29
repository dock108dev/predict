"""Source-native exact-query inventories, independent of retained price rows."""
from hashlib import sha256
import json

FAMILIES={'h2h':'moneyline','spreads':'spread','totals':'total'}


def identity(*parts):
    return sha256(json.dumps(parts,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def aggregate_inventory(payload, venue, family, records, *, rejected=False):
    games=set();markets=set();units={};listing_only=set()
    for event in payload:
        for book in event.get('bookmakers',[]):
            if book.get('key')!=venue:continue
            for market in book.get('markets',[]):
                if FAMILIES.get(market.get('key'))!=family:continue
                eid=event['id'];games.add(eid)
                outcomes=market.get('outcomes') or []
                mid=identity(venue,eid,market['key'],sorted((o.get('name'),str(o.get('point'))) for o in outcomes),'full_game');markets.add(mid)
                if not any(o.get('price') is not None for o in outcomes):listing_only.add(mid)
                for outcome in outcomes:
                    if outcome.get('price') is None:continue
                    uid=identity(venue,eid,market['key'],outcome['name'],str(outcome.get('point')),'full_game','bookmaker_outcome')
                    units[uid]=True
    admitted=set()
    for record in records:
        q=record['quote'];source=q['source']
        if q['venue']==venue and record['market_identity']['family']==family:
            key=next(k for k,v in FAMILIES.items() if v==family)
            admitted.add(identity(venue,source['native_event_id'],key,source['native_outcome_id'],str(source.get('native_line')),'full_game','bookmaker_outcome'))
    received=set(units);admitted &= received
    return dict(unique_offered=dict(games=len(games),markets=len(markets),quotes=len(received)),
        listing_only_markets=len(listing_only),received=len(received),admitted=len(admitted),
        rejected=len(received-admitted),omitted=0,pending=0,
        omission_reasons={'normalization_or_value_rejected':len(received-admitted)} if received-admitted else {},
        identity_sha256=identity(sorted(received)),_unit_ids=sorted(received),
        denominator_status='complete',scope_limitations=['Exact configured sport odds route; alternate-line inventory not established'],
        provider_universe_complete=False)


def native_inventory(findings, markets, selected_ids, *, started_at, completed_at, venue, sport, family):
    """Lower bounds from fetched metadata; never infer price offerings from listings."""
    related=[f for f in findings if f.get('sport')==sport and f.get('family') in (None,family)]
    queried=[f for f in related if f.get('queried')]
    ids={(m['event_id'],m['id']) for m in markets}
    reasons={}
    for finding in related:
        reason=finding.get('reason') or finding.get('continuation_limitation')
        if reason:reasons[reason]=reasons.get(reason,0)+finding.get('budget_omitted_events',1)
    unselected=sum(mid not in selected_ids for _,mid in ids)
    if unselected:reasons['metadata_projection_or_subscription_limit']=unselected
    if any(not f.get('traversal_exhausted') for f in queried):reasons['listing_traversal_incomplete']=1
    reasons['price_inventory_unmeasured']=1
    return dict(route='kalshi_events_and_markets' if venue=='kalshi' else 'polymarket_us_events_and_markets',
        requested_scope=dict(sport=sport,family=family,period='full_game',native_sides=True,available_lines=True),
        started_at=min((f.get('query_started_at',started_at) for f in queried),default=started_at),
        completed_at=completed_at,pages=sum(f.get('traversal_pages',1) for f in queried),
        page_scope='listing traversal; metadata completion not established',
        listing_queries=[{k:f.get(k) for k in ('query_sha256','query_started_at','query_completed_at','traversal_pages','unique_listing_events','traversal_exhausted','continuation_limitation')} for f in queried],
        exhausted=bool(queried) and all(f.get('traversal_exhausted') for f in queried),
        continuation=any(f.get('next_position') is not None for f in queried),
        failures=sum(f.get('state') in ('failed','unsupported') for f in related),
        denominator_status='partial' if queried else 'unknown',
        unique_listing_games=len({e for e,_ in ids}),unique_listing_markets=len(ids),
        offered_price_units=None,listing_only_markets=None,received=None,admitted=None,rejected=None,
        omitted=None,pending=None,known_unselected_markets=unselected,omission_reasons=reasons,
        provider_universe_complete=False,
        reconciliation='Partial pages cannot establish withdrawals or zero price offerings')


class NativePriceInventory:
    """Latest received book identities; reconnects replace, not add, units.

    This is a measured subset, never the complete provider denominator. An empty
    image withdraws its prior units; absence from a partial catalog does not.
    """
    def __init__(self):
        self.books={}

    def observe(self,venue,sport,family,book,disposition):
        ref=book['raw']['ref'];units=set()
        for outcome in book['outcomes']:
            for side in ('asks','bids'):
                ladder=outcome.get(side)
                if ladder and ladder.get('levels'):
                    units.add(identity(venue,ref['event_id'],ref['market_id'],outcome['outcome_id'],side))
        key=(venue,ref['event_id'],ref['market_id'])
        previous=self.books.get(key,{})
        same_image=previous.get('received_at')==book['raw']['received_at'] and previous.get('units')==units
        self.books[key]=dict(sport=sport,family=family,units=units,disposition=disposition,
            received_at=book['raw']['received_at'],source_at=book['raw'].get('exchange_at'),
            added=previous['added'] if same_image else len(units-previous.get('units',set())),
            withdrawn=previous['withdrawn'] if same_image else len(previous.get('units',set())-units))

    def counts(self,venue,sport,family):
        rows=[v for k,v in self.books.items() if k[0]==venue and v['sport']==sport and v['family']==family]
        return dict(count_scope='latest_received_native_books_this_runtime',
            received=sum(len(r['units']) for r in rows),
            **{state:sum(len(r['units']) for r in rows if r['disposition']==state) for state in ('admitted','rejected','pending')},
            listing_only_markets=sum(not r['units'] for r in rows),
            last_receipt_at=max((r['received_at'] for r in rows),default=None),
            last_source_at=max((r['source_at'] for r in rows if r['source_at']),default=None),
            native_unit_definition='native event/market/outcome and ask or bid with at least one price level',
            observed_market_images=len(rows),
            last_image_additions=sum(r['added'] for r in rows),last_image_withdrawals=sum(r['withdrawn'] for r in rows))
