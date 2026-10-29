"""Exhaustive ordinary listing and metadata traversal with durable checkpoints."""
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json

from . import coverage
from .current_policy import native_scope, native_markets
from .native_scope_bindings import selectors_for
from .native_selectors import query
from .current_sink import utc
from .bulk_checkpoint import owned_thread


def _catalog_process(receipts, venue, at, selection):
    """Pure CPU work on already received public metadata; no acquisition owner."""
    import os
    import resource
    import sys
    result=coverage.catalog(receipts,venue,at,compact_output=False,current_selection=selection)
    from .current_native_catalog import detach_event_packaging
    detach_event_packaging(result)
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return result,dict(pid=os.getpid(),peak_rss_bytes=rss if sys.platform=='darwin' else rss*1024)


async def build_catalog(worker, receipts, at, selection):
    if not getattr(worker,'checkpoint',None):
        return await owned_thread(coverage.catalog,receipts,worker.venue,at,
            compact_output=False,current_selection=selection)
    if getattr(worker,'catalog_pool',None) is None:
        from concurrent.futures import ProcessPoolExecutor
        from multiprocessing import get_context
        worker.catalog_pool=ProcessPoolExecutor(max_workers=1,mp_context=get_context('spawn'))
    future=asyncio.wrap_future(worker.catalog_pool.submit(_catalog_process,receipts,worker.venue,at,selection))
    try:
        result,metrics=await asyncio.shield(future)
    except asyncio.CancelledError:
        await asyncio.gather(future,return_exceptions=True)
        raise
    worker.metrics['catalog_worker']=metrics
    from .current_native_catalog import share_catalog_metadata
    return await owned_thread(share_catalog_metadata,getattr(worker,'catalog',{}),result)


async def close_catalog_worker(worker):
    pool=getattr(worker,'catalog_pool',None)
    if pool is not None:
        worker.catalog_pool=None
        await owned_thread(pool.shutdown,wait=True,cancel_futures=True)
        worker.metrics['catalog_worker_stopped']=True


async def pages(worker, path, base, field, scope=None, size=50):
    """Resume exact queries. A repeated cursor/page is a failure, never absence."""
    checkpoint = getattr(worker, 'checkpoint', None)
    key, saved = await owned_thread(checkpoint.query, path, base) if checkpoint else (None, [])
    position = '' if worker.venue == 'kalshi' else 0
    seen = set()
    result = []
    index = 0
    while True:
        worker.guard()
        params = dict(base)
        detail=path.startswith('/v1/events/') or path.startswith('/v1/market/id/')
        if field and not detail:
            params['limit'] = size
            params.update({'cursor': position} if worker.venue == 'kalshi' and position else
                          {} if worker.venue == 'kalshi' else {'offset': position})
        if index < len(saved):
            page = saved[index]
            worker.pages.append(page)
        else:
            await worker.get(path, params, None if detail else field, scope)
            page = worker.pages[-1]
        _, data = coverage.decode_page(page)
        rows = data.get(field) if field else data.get('markets', [data.get('market', data)])
        if not isinstance(rows, list):
            raise ValueError('bulk_listing_array_missing')
        if not field or detail:
            complete = True
        elif worker.venue == 'kalshi':
            cursor = data.get('cursor')
            if not isinstance(cursor, str) or len(cursor) > 4096:
                raise ValueError('bulk_cursor_missing')
            complete = not cursor
            if cursor and (cursor == position or cursor in seen):
                raise ValueError('bulk_cursor_repeated')
            seen.add(cursor)
            position = cursor
        else:
            if len(rows) > size:
                raise ValueError('bulk_offset_boundary_unknown')
            complete = len(rows) < size
            fingerprint = sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
            if rows and fingerprint in seen:
                raise ValueError('bulk_page_repeated')
            seen.add(fingerprint)
            position += size
        if checkpoint and index >= len(saved):
            await owned_thread(checkpoint.page, key, index, page, complete)
        if checkpoint:
            page['current_checkpoint']=dict(source=worker.venue,query_key=key,position=index)
        result.extend(rows)
        index += 1
        worker.metrics['bulk_progress'] = dict(path=path, pages=index, rows=len(result),
                                              exhausted=complete, continuation=None if complete else position)
        if complete:
            return result, index
        await asyncio.sleep(0)


async def enumerate_native(worker):
    sports, families = native_scope(worker.config), native_markets(worker.config)
    checkpoint = getattr(worker, 'checkpoint', None)
    if checkpoint:
        await owned_thread(checkpoint.begin)
    selected, native_events, markets = {}, {}, {}
    catalogs=[]
    cache=getattr(worker,'catalog_cache',{})
    worker.catalog_cache=cache
    scopes = [(s, f) for s in sports for f in families] if worker.venue == 'kalshi' else [(s, None) for s in sports]
    for sport, family in scopes:
        worker._coverage_sport, worker._coverage_family = sport, family
        started = utc()
        if worker.venue == 'kalshi':
            selectors = selectors_for(sport + '/full_game/' + family)
            if not selectors:
                raise ValueError('bulk_selector_unestablished')
        else:
            path, params = query(worker.venue, sport, families=families)
            selectors = [dict(path=path, params=params, binding=None)]
        for selector in selectors:
            if worker.venue=='kalshi':
                selector=dict(selector,params=dict(selector['params'],with_nested_markets='true'))
            scope = selector['binding']
            rows, count = await pages(worker, selector['path'], selector['params'], 'events', scope,
                                      size=50 if worker.venue == 'kalshi' else 5)
            ids = []
            for native in rows:
                eid = str(native['event_ticker' if worker.venue == 'kalshi' else 'id'])
                native_events[eid] = native
                selected[eid] = dict(id=eid, competition=sport, scope=scope,
                                     game_id=native.get('gameId'))
                ids.append(eid)
            worker.findings.append(dict(sport=sport, family=family, queried=True, configured=True,
                rows=len(set(ids)), discovered=len(set(ids)), selected=list(dict.fromkeys(ids)),
                state='discovered' if rows else 'empty', traversal_exhausted=True,
                traversal_pages=count, unique_listing_events=len(set(ids)), next_position=None,
                query_started_at=started, query_completed_at=utc(),
                query_sha256=sha256(json.dumps(selector, sort_keys=True).encode()).hexdigest(),
                scope='complete listing traversal; metadata pending'))
    listing_pages=[coverage.DecodedPage(p) for p in worker.pages]
    # All configured listing scopes precede metadata. Distinct native IDs remain
    # independent even when derived occurrence/financial bindings are unavailable.
    from app.adapters.polymarket_us import full_game_family
    for eid, event in selected.items():
        worker._coverage_sport = event['competition']
        worker._coverage_family = (event['scope'] or {}).get('family')
        metadata_start=len(worker.pages)
        listing_native=native_events[eid]
        missing_listing_ids=set()
        if worker.venue == 'kalshi':
            rows=native_events[eid].get('markets')
            if not isinstance(rows,list):
                rows, _ = await pages(worker, '/trade-api/v2/markets', dict(event_ticker=eid), 'markets', event['scope'])
        else:
            details, _ = await pages(worker, '/v1/events/' + eid, {}, 'events')
            if len(details)!=1 or str(details[0].get('id'))!=eid:
                raise ValueError('bulk_event_detail_identity')
            native_events[eid]=details[0]
            rows=details[0].get('markets')
            if not isinstance(rows,list):
                raise ValueError('bulk_event_markets_missing')
            rows=[m for m in rows if full_game_family(m.get('sportsMarketType')) in families]
        # A metadata route returning no rows cannot erase embedded listings.
        # Keep every evidenced locator; exact catalog conflict checks still apply.
        if worker.venue == 'polymarket_us':
            combined={str(m['id']):m for m in listing_native.get('markets') or [] if m.get('id') is not None and full_game_family(m.get('sportsMarketType')) in families}
            missing_listing_ids=set(combined)-{str(m['id']) for m in rows}
            combined.update({str(m['id']):m for m in rows})
            worker.metrics['listing_only_markets']=worker.metrics.get('listing_only_markets',0)+len(missing_listing_ids)
            rows=list(combined.values())
        for native in rows:
            mid = str(native['ticker' if worker.venue == 'kalshi' else 'id'])
            family = (event['scope'] or {}).get('family') if worker.venue == 'kalshi' else full_game_family(native.get('sportsMarketType'))
            markets[(eid,mid)] = dict(id=mid, event_id=eid, market_type=family or 'unknown', _native=native)
        own_ids=[m['id'] for m in markets.values() if m['event_id']==eid]
        # Derive one event at a time. Complete raw receipts live in indexed SQL;
        # unselected props and duplicated depth never accumulate in the graph.
        relevant=[p for p in listing_pages if
            (p.get('native_scope_binding') or {}).get('sport')==event['competition']] if worker.venue=='kalshi' else []
        if not relevant and worker.venue=='kalshi':relevant=listing_pages
        if missing_listing_ids:
            # Preserve actual listing receipts, including conflict checks. Never
            # synthesize an expanded response or relabel its provider hash.
            relevant=[p for p in listing_pages if any(str(e.get('id'))==eid
                for e in coverage.decode_page(p)[1].get('events',[]))]
        receipts=relevant+worker.pages[metadata_start:]
        if worker.venue!='kalshi':
            signature=tuple(p['body_sha256'] for p in receipts)
            if eid in cache and cache[eid][0]==signature:
                cat=cache[eid][1]
                worker.metrics['metadata_catalog_reused']=worker.metrics.get('metadata_catalog_reused',0)+1
            else:
                cat=await build_catalog(worker,receipts,datetime.now(timezone.utc),
                    dict(events=[eid],markets=own_ids))
                cache[eid]=(signature,cat)
            catalogs.append(cat)
            if checkpoint:
                for page in worker.pages[metadata_start:]:
                    page.pop('body_b64',None)
        # Keep selected metadata only, with raw evidence available independently.
        if worker.venue=='polymarket_us':
            native_events[eid]=dict(native_events[eid],markets=rows)

    if worker.venue=='kalshi':
        # One complete pass through the shared listing pages. Sending those same
        # multi-event pages to a child for every event caused quadratic decoding
        # and IPC even after HTTP acquisition had finished.
        catalogs=[await build_catalog(worker,worker.pages,datetime.now(timezone.utc),
            dict(events=list(selected),markets=[mid for _,mid in markets]))]
        cache.clear()
        if checkpoint:
            for page in worker.pages:page.pop('body_b64',None)
    for eid in set(cache)-set(selected):cache.pop(eid)
    for finding in worker.findings:
        finding.update(metadata_complete=True, scope='complete listing and metadata traversal')
    if catalogs:
        worker.bulk_catalog=dict(catalogs[0],events=[e for c in catalogs for e in c['events']],markets=[m for c in catalogs for m in c['markets']])
    else:
        worker.bulk_catalog=coverage.catalog(listing_pages,worker.venue,datetime.now(timezone.utc),compact_output=False,current_selection=dict(events=[],markets=[]))
    # Identity collisions across individually decoded events must not disappear
    # at the merge boundary or bind one socket channel to two instruments.
    from collections import Counter,defaultdict
    counts=Counter(m['id'] for m in worker.bulk_catalog['markets'])
    slugs=defaultdict(set)
    for m in worker.bulk_catalog['markets']:
        if m.get('native_slug'):slugs[m['native_slug']].add(m['id'])
    for m in worker.bulk_catalog['markets']:
        if counts[m['id']]>1 or len(slugs[m.get('native_slug')])>1:
            m['subscription_evidence_exclusion']='ambiguous_native_subscription_identity'
    worker.metrics['bulk_enumeration'] = dict(events=len(selected), markets=len(markets), pages=len(worker.pages),
        completed_at=utc(), started_at=min((f['query_started_at'] for f in worker.findings), default=utc()),
        resident_receipt_bytes=sum(len(p.get('body_b64','')) * 3 // 4 for p in worker.pages))
    from .current_native_catalog import detach_event_packaging
    detach_event_packaging(worker.bulk_catalog)
    return list(selected.values()), native_events, list(markets.values())
