"""Offline, independent native catalogs. No transport, credentials or scan owner.

Input: retained saved-observations.json or a coverage-pages-1 synthetic envelope.
Pagination describes the first captured traversal of each exact query, not live
completeness. Missing pages/markets are never filled by network requests.
"""
import argparse
import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import parse_qsl

from app.adapters import kalshi, polymarket_us
from app.collection.prediction_discovery import participant_mapping

VENUES = ('kalshi', 'polymarket_us')


def stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('timezone required')
    return result


def load_pages(path):
    raw = path.read_bytes()
    value = json.loads(raw)
    historical_collection = {}
    if value.get('format') == 'coverage-pages-1':
        if value.get('classification') != 'synthetic':
            raise ValueError('fixture envelope must be explicitly synthetic')
        pages = value['pages']
        classification = 'synthetic'
    elif value.get('format') == 'e6-transport-observations-1':
        pages = [r for r in value['rows'] if r['type'] == 'prediction_discovery_http'
                 and r['source'] in VENUES and r['path'].endswith(('/events', '/markets'))]
        modes = {r.get('spec', {}).get('mode') for r in value['rows'] if r['type']=='session_started'}
        classification = 'historical retained capture' if modes == {'real'} else 'synthetic or unverified retained capture'
        for venue in VENUES:
            commands = [dict(observed_at=r['observed_at'], body=r['body']) for r in value['rows']
                        if r['type']=='prediction_command' and r['source']==venue]
            books = {r['book']['raw']['ref']['market_id'] for r in value['rows']
                     if r['type']=='prediction_book' and r['source']==venue}
            finished = [r for r in value['rows'] if r['type']=='native_stream_finished' and r['source']==venue]
            historical_collection[venue] = dict(subscription_requests=commands,
                markets_with_retained_books=sorted(books), markets_with_retained_books_count=len(books),
                stream_closed=finished[-1].get('closed') if finished else None,
                finished_at=finished[-1]['observed_at'] if finished else None)
    else:
        raise ValueError('unsupported input format')
    return pages, dict(path=str(path), sha256=sha256(raw).hexdigest(), classification=classification, historical_collection=historical_collection)


def decode_page(page):
    raw = base64.b64decode(page['body_b64'], validate=True)
    if sha256(raw).hexdigest() != page['body_sha256']:
        raise ValueError('retained body hash mismatch')
    return raw.decode(), json.loads(raw)


def params(page):
    q = page['params']
    return dict(parse_qsl(q)) if isinstance(q, str) else q


def traversal(pages, venue, field):
    """Validate a contiguous first traversal; retain usable prefix on failure."""
    accepted = []
    expected = '' if venue == 'kalshi' else 0
    seen = set()
    state, reason = 'unknown', 'no retained pages'
    for page_index, page in enumerate(pages):
        q = params(page)
        try:
            limit = int(q['limit'])
            position = q.get('cursor', '') if venue == 'kalshi' else int(q.get('offset', 0))
            if limit <= 0 or position != expected:
                raise ValueError('pagination gap or repeated request')
            if page.get('status') != 200 or page.get('complete') is not True:
                # A bounded retry of exactly this position can supply the page;
                # the failed attempt remains in retained/unused page evidence.
                if page_index+1 < len(pages) and params(pages[page_index+1]) == q:
                    continue
                raise ValueError('failed or incomplete HTTP response')
            body, data = decode_page(page)
            rows = data.get(field)
            if not isinstance(rows, list):
                raise ValueError('missing result array')
            accepted.append((page, body, data))
            if venue == 'kalshi':
                cursor = data.get('cursor')
                if not isinstance(cursor, str):
                    state, reason = 'unknown', 'missing cursor'
                    break
                if not cursor:
                    state, reason = 'exhausted', 'terminal empty cursor'
                    break
                if cursor in seen:
                    raise ValueError('repeated response cursor')
                seen.add(cursor)
                expected = cursor
            else:
                if len(rows) < limit:
                    state, reason = 'exhausted', 'short offset page (adapter stopping rule)'
                    break
                expected = position + limit
            state, reason = 'bounded/truncated', 'continuation not retained'
        except (KeyError, TypeError, ValueError) as exc:
            state, reason = 'failed', str(exc)
            break
    return accepted, dict(state=state, reason=reason, retained_pages=len(pages),
                          used_pages=len(accepted), unused_pages=len(pages)-len(accepted),
                          next_position=expected if state != 'exhausted' else None,
                          query=params(pages[0]) if pages else None)


def provenance(page, index, body):
    return dict(inventory_row=index, path=page['path'], params=params(page),
                received_at=page['received_at'], body_sha256=sha256(body.encode()).hexdigest())


def response(venue, page, body):
    adapter = kalshi if venue == 'kalshi' else polymarket_us
    return adapter.Response(body, page['path'], stamp(page['received_at']))


def insert(records, record, native, proof):
    key = record['id']
    if key in records:
        old = records[key]
        old['occurrences'] += 1
        old['provenance'].append(proof)
        if (old['_native'] != native or old.get('event_id') != record.get('event_id')
                or old.get('scheduled_start') != record.get('scheduled_start')):
            old['conflicting_duplicate'] = True
            old['exclusion'] = 'conflicting_duplicate'
        return
    records[key] = dict(record, occurrences=1, provenance=[proof], _native=native,
                        conflicting_duplicate=False)


def event_record(venue, page, body, native, index, as_of):
    eid = str(native.get('event_ticker' if venue == 'kalshi' else 'id') or f'unknown-event-row-{index}')
    record = dict(id=eid, title=native.get('title'), scheduled_start=None,
                  native_aliases={k:native[k] for k in ('ticker','slug','series_ticker','seriesSlug') if k in native},
                  terms_references={k:native[k] for k in ('settlement_sources','resolutionSource') if k in native},
                  participants={}, identity='unresolved', canonical_key=None,
                  exclusion=None, status={k:native.get(k) for k in ('status','active','closed','live','ended','period')})
    try:
        r = response(venue, page, body)
        if venue == 'kalshi':
            event = kalshi.parse_event(r, native, 'KXNFLGAME')
        else:
            event = polymarket_us.parse_event(r, native)
        if venue == 'polymarket_us' and params(page).get('tagSlug') != 'nfl' and '/leagues/nfl/' not in page['path']:
            raise ValueError('NFL query scope unestablished')
        # Normalize this occurrence alone: identical duplicate native rows must
        # not look like ambiguous event identity to the shared extractor. Original
        # bytes remain in the hashed source; this view is used only for identity.
        identity_payload = json.loads(body)
        identity_payload['events'] = [native]
        identity_event = replace(event, raw=replace(event.raw, json_text=json.dumps(identity_payload)))
        normalized, mapping = participant_mapping(identity_event)
        record['participants'] = mapping
        start = event.scheduled_start
        record['scheduled_start'] = start.isoformat() if start else None
        resolved = normalized.league.canonical_id == 'NFL' and len(mapping) == 2 and None not in mapping.values() and len(set(mapping.values())) == 2
        record['identity'] = 'resolved' if resolved else 'unresolved'
        if resolved and start:
            record['canonical_key'] = [start.astimezone(timezone.utc).isoformat(), sorted(mapping.values())]
        if not start:
            record['exclusion'] = 'unknown_schedule'
        elif start <= as_of:
            record['exclusion'] = 'kickoff_reached'
        elif venue == 'polymarket_us' and (any(native.get(k) is True for k in ('live','ended','closed')) or native.get('period') not in (None,'NS') or native.get('rescheduledFromGameId') not in (None,0,'0')):
            record['exclusion'] = 'phase_or_reschedule'
        # Unresolved participant identity does not remove an otherwise in-scope event.
    except (ValueError, KeyError, TypeError) as exc:
        record.update(exclusion='event_parse_error', error=str(exc))
    return record


def market_record(venue, page, body, native, eid, index):
    mid = str(native.get('ticker' if venue == 'kalshi' else 'id') or f'unknown-market-row-{index}')
    record = dict(id=mid, event_id=eid, native_slug=native.get('slug'), title=native.get('title',native.get('question')),
                  market_type='unknown', period='unknown', status='unknown', exclusion=None,
                  terms={k:native[k] for k in ('rules_primary','rules_secondary','description','resolutionSource') if k in native}, sides=[])
    try:
        r = response(venue, page, body)
        market = kalshi.parse_market(r, native, eid, 'KXNFLGAME') if venue == 'kalshi' else polymarket_us.parse_market(r, native, eid)
        record.update(market_type=market.market_type.value, status=market.state.value)
        full = venue == 'kalshi' or native.get('sportsMarketType') == 'football_team_full_game_winner'
        record['period'] = 'full_game' if full else 'unknown_or_other'
        if market.market_type.value != 'moneyline' or not full:
            record['exclusion'] = 'unsupported_market_type_or_period'
        elif market.state.value != 'active' or native.get('closed') is True or native.get('active') is False:
            record['exclusion'] = 'inactive_or_unknown_market_state'
        roles = {str(s['id']): s['long'] for s in native.get('marketSides', [])}
        for side in market.outcomes:
            supported = venue == 'kalshi' or roles.get(side.native_id) is True
            record['sides'].append(dict(id=side.native_id, label=side.label,
                role=side.native_id if venue == 'kalshi' else ('Long' if roles[side.native_id] else 'Short'),
                purchase_support='supported' if supported else 'unsupported',
                basis='opposite native bid complement in existing adapter' if venue == 'kalshi' else
                ('native Long offers in existing adapter' if supported else 'Short purchase ladder not reconstructed by existing adapter')))
    except (ValueError, KeyError, TypeError) as exc:
        record.update(exclusion='market_parse_error', error=str(exc))
        # Preserve even malformed native sides; support cannot be established.
        record['sides'] = [dict(id=str(s.get('id')), label=s.get('description'), role=s.get('long'),
                                purchase_support='unknown', basis='market parse failed')
                           for s in native.get('marketSides', []) if isinstance(s,dict)]
    return record


def catalog(pages, venue, as_of):
    groups = defaultdict(list)
    for page in pages:
        if page['source'] != venue:
            continue
        q = {k:str(v) for k,v in params(page).items() if k not in ('cursor','offset','limit')}
        groups[(page['path'], json.dumps(q,sort_keys=True))].append(page)
    events, markets, discoveries = {}, {}, []
    event_pages = []
    market_pages = []
    for (path, query), values in sorted(groups.items()):
        field = 'events' if path.endswith('/events') else 'markets'
        accepted, status = traversal(values, venue, field)
        status.update(path=path, filters=json.loads(query),
                      page_evidence=[{k:p.get(k) for k in ('received_at','status','complete','body_sha256')} for p in values])
        discoveries.append(status)
        (event_pages if field == 'events' else market_pages).extend(accepted)
    row_index = 0
    # D2 may independently enumerate US markets by the documented native gameId.
    # Retain both sources. Query exhaustion cannot erase an observed listing.
    independent_games = {str(params(p).get('gameId')) for p, _, _ in market_pages
                         if venue == 'polymarket_us' and params(p).get('gameId')}
    for page, body, data in event_pages:
        for native in data['events']:
            row_index += 1
            proof = provenance(page,row_index,body)
            record = event_record(venue,page,body,native,row_index,as_of)
            insert(events,record,native,proof)
            if venue == 'polymarket_us':
                embedded = native.get('markets')
                events[record['id']]['market_discovery'] = 'embedded_only' if isinstance(embedded,list) else 'unknown'
                for m in (embedded or []):
                    row_index += 1
                    insert(markets,market_record(venue,page,body,m,record['id'],row_index),m,provenance(page,row_index,body))
    for page, body, data in market_pages:
        for native in data['markets']:
            row_index += 1
            if venue == 'polymarket_us':
                candidates = [e['id'] for e in events.values()
                              if str(e['_native'].get('gameId')) == str(params(page).get('gameId'))
                              and params(page).get('gameId')]
                eid = candidates[0] if len(candidates) == 1 else 'unknown'
            else:
                eid = str(native.get('event_ticker') or params(page).get('event_ticker') or 'unknown')
            insert(markets,market_record(venue,page,body,native,eid,row_index),native,provenance(page,row_index,body))
    for event in events.values():
        if venue == 'kalshi':
            states = [d['state'] for d in discoveries if d['path'].endswith('/markets') and d['filters'].get('event_ticker')==event['id']]
            event['market_discovery'] = states[0] if len(states)==1 else 'unknown'
        elif str(event['_native'].get('gameId')) in independent_games:
            states = [d['state'] for d in discoveries if d['path'].endswith('/markets')
                      and d['filters'].get('gameId') == str(event['_native'].get('gameId'))]
            event['market_discovery'] = states[0] if len(states)==1 else 'unknown'
            returned = {str(m.get('id')) for p, _, d in market_pages
                        if str(params(p).get('gameId')) == str(event['_native'].get('gameId'))
                        for m in d['markets']}
            missing = sorted({str(m.get('id')) for m in event['_native'].get('markets', [])} - returned)
            if missing:
                event['market_discovery'] = 'contradictory_listings'
                event['embedded_missing_from_market_query'] = missing
        event['market_ids'] = sorted(m['id'] for m in markets.values() if m['event_id']==event['id'])
    for market in markets.values():
        event = events.get(market['event_id'])
        if event is None:
            market['exclusion'] = market['exclusion'] or 'missing_event'
        elif event['exclusion']:
            market['exclusion'] = market['exclusion'] or 'event_excluded:' + event['exclusion']
        native = market['_native']
        if venue == 'polymarket_us':
            sides = native.get('marketSides', [])
            reason = None
            if not native.get('id') or not native.get('slug') or not event or event['identity'] != 'resolved':
                reason = 'unresolved_native_identity'
            elif sum(m.get('native_slug') == market['native_slug'] for m in markets.values()) != 1:
                reason = 'ambiguous_subscription_slug'
            elif not any(isinstance(market['terms'].get(k), str) and market['terms'][k].strip()
                         for k in ('description','rules_primary','rules_secondary')):
                reason = 'missing_native_terms'
            elif (len(sides) != 2 or len({s.get('id') for s in sides}) != 2
                  or {s.get('long') for s in sides} != {True, False}
                  or any(type(s.get('long')) is not bool or not s.get('id') for s in sides)
                  or {s.get('team', {}).get('name') for s in sides} != set(event['participants'])
                  or any(str(s.get('marketId')) != market['id'] for s in sides)):
                reason = 'unresolved_native_sides'
            market['subscription_evidence_exclusion'] = reason
            market['subscription_evidence_basis'] = 'native ID, unique slug, resolved event and side teams, explicit roles, native terms; completeness independent'
        if venue == 'polymarket_us' and native.get('gameStartTime') and event:
            try:
                conflict = stamp(native['gameStartTime']).isoformat() != event['scheduled_start']
            except (ValueError, TypeError):
                conflict = True
            if conflict:
                market['exclusion'] = market['exclusion'] or 'schedule_conflict'
    event_states = [d['state'] for d in discoveries if d['path'].endswith('/events')]
    event_discovery = ('exhausted' if event_states and all(s=='exhausted' for s in event_states)
                       else 'failed' if 'failed' in event_states
                       else 'bounded/truncated' if 'bounded/truncated' in event_states else 'unknown')
    return dict(event_discovery=event_discovery, market_completeness='unestablished' if any(e['market_discovery']!='exhausted' for e in events.values()) or event_discovery!='exhausted' else 'exhausted_for_retained_events',
                events=sorted(events.values(),key=lambda r:r['id']), markets=sorted(markets.values(),key=lambda r:r['id']),
                discovery=discoveries, active_subscriptions=None,
                subscription_basis='offline inventory; no live subscription state queried')


def match_catalogs(catalogs):
    buckets = defaultdict(lambda: defaultdict(list))
    for venue, cat in catalogs.items():
        for event in cat['events']:
            event['matching_status'] = 'excluded' if event['exclusion'] else 'unresolved'
            event['counterpart_event_ids'] = []
            if not event['exclusion'] and event['canonical_key']:
                buckets[json.dumps(event['canonical_key'])][venue].append(event)
    for values in buckets.values():
        ambiguous = any(len(rows)>1 for rows in values.values())
        for venue, events in values.items():
            other = values.get(next(v for v in VENUES if v!=venue), [])
            for event in events:
                event['matching_status'] = 'ambiguous' if ambiguous else ('matched' if other else 'unmatched')
                event['counterpart_event_ids'] = [e['id'] for e in other]
    for venue, cat in catalogs.items():
        events = {e['id']:e for e in cat['events']}
        for market in cat['markets']:
            event = events.get(market['event_id'])
            market['matching_status'] = 'excluded' if market['exclusion'] else (event['matching_status'] if event else 'unresolved')
            other_cat = catalogs[next(v for v in VENUES if v != venue)]
            market['counterpart_market_ids'] = sorted(m['id'] for m in other_cat['markets']
                if event and m['event_id'] in event['counterpart_event_ids'] and not m['exclusion'])
            if market['matching_status'] == 'matched' and not market['counterpart_market_ids']:
                market['matching_status'] = 'unmatched_missing_market'
            market['matching_basis'] = 'event identity and retained in-scope market presence only; outcome/terms equivalence not established'


def totals(cat):
    result = {}
    for kind in ('events','markets'):
        rows = cat[kind]
        count = dict(discovered=len(rows), in_scope=sum(r['exclusion'] is None for r in rows),
                     excluded=sum(r['exclusion'] is not None for r in rows),
                     raw_occurrences=sum(r['occurrences'] for r in rows),
                     duplicates=sum(r['occurrences']-1 for r in rows),
                     matching=dict(sorted(Counter(r['matching_status'] for r in rows).items())),
                     exclusions=dict(sorted(Counter(r['exclusion'] for r in rows if r['exclusion']).items())))
        assert count['discovered']==count['in_scope']+count['excluded']==sum(count['matching'].values())
        assert count['raw_occurrences']==count['discovered']+count['duplicates']
        assert count['excluded']==sum(count['exclusions'].values())
        result[kind]=count
    sides = [s for m in cat['markets'] for s in m['sides']]
    result['sides'] = {k:sum(s['purchase_support']==k for s in sides) for k in ('supported','unsupported','unknown')}
    result['sides']['total']=len(sides)
    result['in_scope_sides'] = dict(Counter(s['purchase_support'] for m in cat['markets'] if not m['exclusion'] for s in m['sides']))
    assert sum(result['sides'][k] for k in ('supported','unsupported','unknown'))==len(sides)
    result['events_without_retained_markets']=sum(not e['market_ids'] for e in cat['events'])
    result['market_discovery']=dict(Counter(e['market_discovery'] for e in cat['events']))
    return result


def build(pages, source, as_of):
    catalogs = {v:catalog(pages,v,as_of) for v in VENUES}
    match_catalogs(catalogs)
    receipts = sorted(stamp(p['received_at']) for p in pages)
    if receipts and as_of < receipts[-1]:
        raise ValueError('as-of must not precede the latest retained retrieval')
    for venue, cat in catalogs.items():
        cat['historical_collection'] = source.get('historical_collection', {}).get(venue)
        cat['counts'] = totals(cat)
        for r in cat['events']+cat['markets']:
            del r['_native']
    return dict(format='coverage-inventory-1', source=source, as_of=as_of.isoformat(),
                scope='NFL pregame full-game winner; retained endpoint filters are part of the denominator',
                current_full_coverage=False, current_counts=None,
                caveats=['Historical/synthetic inventory only; no new data collected.',
                         'Exhausted applies only to a captured query traversal, not the whole live venue.',
                         'Polymarket embedded markets are not independently proven exhaustive.',
                         'Matching is event identity plus retained market presence, not outcome/contract/settlement equivalence.',
                         'Purchase support is adapter capability, not available liquidity or live qualification.'],
                first_retrieval=receipts[0].isoformat() if receipts else None,
                last_retrieval=receipts[-1].isoformat() if receipts else None,
                snapshot_age_seconds=(as_of-receipts[-1]).total_seconds() if receipts else None,
                venues=catalogs)


def markdown(report):
    lines=['# Offline coverage inventory', '', f"Input: `{report['source']['path']}` ({report['source']['classification']}).",
           f"SHA-256: `{report['source']['sha256']}`.", f"As of: {report['as_of']}; last retrieval: {report['last_retrieval']}; age: {report['snapshot_age_seconds']} seconds.",
           '', '**Current full coverage: unavailable.**', '', *['- '+c for c in report['caveats']], '']
    for venue,cat in report['venues'].items():
        lines += [f'## {venue}', '', '```json', json.dumps(cat['counts'],indent=2), '```', '',
                  'Active subscriptions: unknown (offline).',
                  f"Event discovery: {cat['event_discovery']}; market completeness: {cat['market_completeness']}.", '', 'Discovery:', '']
        for d in cat['discovery']:
            lines.append(f"- `{d['path']}` {d['filters']}: **{d['state']}**, {d['reason']}; {d['used_pages']}/{d['retained_pages']} retained pages used.")
        if cat['historical_collection']:
            h = cat['historical_collection']
            lines += ['', f"Historical collection: {len(h['subscription_requests'])} subscription request(s); {h['markets_with_retained_books_count']} markets with retained books; stream closed={h['stream_closed']} at {h['finished_at']}."]
        lines += ['', '| Event ID | Title | Schedule | Identity | Match | Exclusion | Market discovery |', '|---|---|---|---|---|---|---|']
        def cell(value):
            return str(value if value is not None else '—').replace('|','\\|').replace('\n',' ')
        for e in cat['events']:
            lines.append('| '+' | '.join(cell(e[k]) for k in ('id','title','scheduled_start','identity','matching_status','exclusion','market_discovery'))+' |')
        lines += ['', '| Market ID | Event ID | Type / period / state | Purchase sides | Event match | Exclusion |','|---|---|---|---|---|---|']
        for m in cat['markets']:
            sides='; '.join(f"{s['id']} {s['label']} ({s['purchase_support']})" for s in m['sides'])
            lines.append('| '+' | '.join(map(cell,[m['id'],m['event_id'],f"{m['market_type']} / {m['period']} / {m['status']}",sides,m['matching_status'],m['exclusion']]))+' |')
        lines += ['']
    lines += ['Full native provenance, participants, terms and counterpart IDs are in the companion JSON report.','']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--as-of',required=True,help='Explicit timezone-aware historical scope cutoff / age reference')
    parser.add_argument('--output',type=Path,required=True,help='New output directory; existing paths are refused')
    args=parser.parse_args()
    pages,source=load_pages(args.input)
    report=build(pages,source,stamp(args.as_of))
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'coverage.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    (args.output/'coverage.md').write_text(markdown(report))
    print(json.dumps({v:c['counts'] for v,c in report['venues'].items()},indent=2))


if __name__=='__main__':
    main()
