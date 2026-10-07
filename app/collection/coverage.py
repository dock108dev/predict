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

def event_path(path):
    from .native_payload import event_detail_id
    return path.endswith('/events') or event_detail_id(path) is not None


def market_path(path):
    from .native_payload import market_detail_id
    return path.endswith('/markets') or market_detail_id(path) is not None

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
                 and r['source'] in VENUES and (event_path(r['path']) or market_path(r['path']) or r.get('v1_coverage_policy') and r['path']=='/trade-api/v2/milestones')]
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
    limits = page.get('transport_policy')
    if limits is not None:
        from .native_payload import exact_transport
        if not exact_transport(limits):
            raise ValueError('native_transport_contract_mismatch')
        if page.get('complete') is not True or page.get('usable_metadata') is not True:
            raise ValueError(page.get('delivery_reason') or 'native_unusable_metadata')
    raw = base64.b64decode(page['body_b64'], validate=True)
    if sha256(raw).hexdigest() != page['body_sha256']:
        raise ValueError('retained body hash mismatch')
    if limits is not None or page.get('acquisition_discovery_policy')in ('bounded-open-catalog-v3','bounded-open-catalog-v4','sport-directed-games-v1'):
        from .native_payload import parse, validate_envelope
        data=parse(raw, limits=limits, revised=page.get("v1_comparison_policy")=="manual-comparison-2")
        if limits is not None:validate_envelope(data, page['path'])
    else:data=json.loads(raw)
    from .native_payload import event_detail_id, market_detail_id
    if event_detail_id(page['path']) is not None:
        if not isinstance(data.get('event'),dict):raise ValueError('native_malformed_data')
        data={**data,'events':[data['event']]}
    elif market_detail_id(page['path']) is not None:
        if not isinstance(data.get('market'),dict):raise ValueError('native_malformed_data')
        data={'markets':[data['market']]}
    return raw.decode(),data


def params(page):
    from .native_payload import event_detail_id, market_detail_id
    q = page['params']
    selected=event_detail_id(page['path']) or market_detail_id(page['path'])
    if selected is not None:return {'limit':1,'offset':0,'id':[selected]}
    return dict(parse_qsl(q)) if isinstance(q, str) else q


def traversal(pages, venue, field):
    """Validate a contiguous first traversal; retain usable prefix on failure."""
    accepted = []
    expected = '' if venue == 'kalshi' else 0
    seen = set()
    row_ids=set()
    state, reason = 'unknown', 'no retained pages'
    for page_index, page in enumerate(pages):
        q = params(page)
        try:
            limit = int(q.get('limit',1)) if event_path(page['path']) and '/events/' in page['path'] else int(q['limit'])
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
            if page.get('acquisition_discovery_policy')in ('bounded-open-catalog-v2','bounded-open-catalog-v3','bounded-open-catalog-v4','sport-directed-games-v1'):
                if any(not isinstance(r,dict) for r in rows):raise ValueError('invalid catalog row')
                ids=[str(r.get('id' if venue=='polymarket_us' else 'event_ticker' if field=='events' else 'ticker') or '') for r in rows]
                from .native_payload import exact_transport
                explicit_v2=exact_transport(page.get('transport_policy'))
                if (len(rows)>limit and not explicit_v2) or any(not x for x in ids) or len(set(ids))!=len(ids) or row_ids.intersection(ids):
                    raise ValueError('duplicate or invalid catalog rows')
                if venue=='kalshi' and data.get('cursor') and data['cursor'] in seen:
                    raise ValueError('repeated response cursor')
                row_ids.update(ids)
            accepted.append((page, body, data))
            if len(rows)>limit:
                state,reason='bounded/truncated','provider returned more rows than requested; complete response retained without exhaustion or offset inference'
                break
            from .native_payload import event_detail_id, market_detail_id
            if page.get('transport_policy') is not None and (
                    event_detail_id(page['path']) is not None or market_detail_id(page['path']) is not None):
                state, reason = 'exhausted', 'complete single entity response'
                break
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
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            state, reason = 'failed', str(exc)
            break
    return accepted, dict(state=state, reason=reason, retained_pages=len(pages),
                          used_pages=len(accepted), unused_pages=len(pages)-len(accepted),
                          next_position=expected if state != 'exhausted' else None,
                          query=params(pages[0]) if pages else None)


def provenance(page, index, body):
    from .native_payload import event_detail_id, market_detail_id
    singular=event_detail_id(page['path']) is not None or market_detail_id(page['path']) is not None
    return dict(inventory_row=index, path=page['path'], params=page['params'] if singular else params(page),
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
        if record.get('native_binding_revision')=='live-native-binding-2' and ('/v1/events/' in proof['path'] or '/v1/market/id/' in proof['path']):
            from .admission_enrichment import duplicate_identity_conflicts
            conflicts=duplicate_identity_conflicts(old['_native'],native,event='event_id' not in record)
            if not conflicts and old.get('event_id')==record.get('event_id') and old.get('scheduled_start')==record.get('scheduled_start') and not old.get('conflicting_duplicate'):
                occurrences=old['occurrences'];proofs=old['provenance']
                old.update(record,_native=native,occurrences=occurrences,provenance=proofs,representation_review='manual-comparison-2: identity-equivalent expanded metadata; settlement terms independently qualified')
                return
        if record.get('native_binding_revision')=='live-native-binding-2' and proof['path'].startswith('/v1/market/id/'):

            # Captured list enrichment adds titles and display colors absent or
            # different in the exact detail. Terms, side/team IDs, directions,
            # question and every unreviewed field must still agree.
            def shape(value):
                from .native_review_contract import project
                value=project('polymarket_us',value)
                for field in ('title','titleShort'):value.pop(field,None)
                for side in value.get('marketSides',[]):
                    if isinstance(side.get('team'),dict):side['team'].pop('color',None)
                return value
            if (old.get('event_id')==record.get('event_id') and shape(old['_native'])==shape(native)
                    and not old.get('conflicting_duplicate')):
                occurrence=old['occurrences'];proofs=old['provenance']
                old.update(record,_native=native,occurrences=occurrence,provenance=proofs,
                    representation_review='live-native-binding-2: exact endpoint after verified list enrichment equivalence')
                return
        if (old['_native'] != native or old.get('event_id') != record.get('event_id')
                or old.get('scheduled_start') != record.get('scheduled_start')):
            old['conflicting_duplicate'] = True
            old['exclusion'] = 'conflicting_duplicate'
        return
    records[key] = dict(record, occurrences=1, provenance=[proof], _native=native,
                        conflicting_duplicate=False)


def event_record(venue, page, body, native, index, as_of, linked_milestones=()):
    eid = str(native.get('event_ticker' if venue == 'kalshi' else 'id') or f'unknown-event-row-{index}')
    record = dict(id=eid, title=native.get('title'), scheduled_start=None,
                  native_aliases={k:native[k] for k in ('ticker','slug','series_ticker','seriesSlug') if k in native},
                  terms_references={k:native[k] for k in ('settlement_sources','resolutionSource') if k in native},
                  participants={}, identity='unresolved', canonical_key=None,
                  exclusion=None, status={k:native.get(k) for k in ('status','active','closed','live','ended','period')})
    if page.get('v1_comparison_policy')=='manual-comparison-2':record['native_binding_revision']='live-native-binding-2'
    try:
        r = response(venue, page, body)
        if venue == 'kalshi':
            if page.get('acquisition_discovery_policy')in ('bounded-open-catalog-v3','bounded-open-catalog-v4','sport-directed-games-v1') and not native.get('series_ticker'):
                raise ValueError('missing_native_series')
            from .native_scope_bindings import POLICY as SCOPE_POLICY, series_binding
            typed_scope = page.get('native_scope_policy') == SCOPE_POLICY or page.get('v1_coverage_policy') and series_binding(native.get('series_ticker')) is not None
            event = kalshi.parse_event(r, native, native.get('series_ticker','KXNFLGAME'), typed_scope=typed_scope, linked_milestones=linked_milestones)
            if typed_scope:
                record['native_scope_binding'] = series_binding(native['series_ticker'])
        else:
            league=params(page).get('tagSlug')
            if page.get('acquisition_discovery_policy')=='sport-directed-games-v1' and page['path'].startswith('/v2/leagues/'):
                league=page['path'].split('/')[3]
            if not league:
                if page.get('v1_comparison_policy')!='manual-comparison-2' and page.get('acquisition_discovery_policy') not in ('bounded-open-catalog-v1','bounded-open-catalog-v2','bounded-open-catalog-v3','bounded-open-catalog-v4','sport-directed-games-v1','polymarket-us-metadata-delivery-v1'):
                    if '/leagues/nfl/' not in page['path']:raise ValueError('league query scope unestablished')
                    league='nfl'
            if not league:
                # Public events schema supplies team league fields. The query
                # need not know a tag ID; require unanimous supported evidence.
                from app.normalization.registry import Registry
                from app.reference.product import SPORT_KEYS
                teams=native.get('teams',[])
                from app.normalization.native_registry import native_registry
                registry=native_registry(live=True) if page.get('v1_comparison_policy')=='manual-comparison-2' else Registry.load()
                leagues=[registry.resolve('league',t.get('league')).canonical_id for t in teams]
                from .native_payload import event_detail_id
                if (len(leagues)<2 if event_detail_id(page['path']) is not None else len(leagues)!=2) or None in leagues or len(set(leagues))!=1 or leagues[0] not in SPORT_KEYS:
                    raise ValueError('native league metadata missing or conflicting')
                league=leagues[0]
            event = polymarket_us.parse_event(r, native, league=league)
        if venue=='polymarket_us' and params(page).get('tagSlug') and any(t.get('league') and str(t['league']).lower()!=str(params(page)['tagSlug']).lower() for t in native.get('teams',[])):
            raise ValueError('native league conflicts with discovery scope')
        # Normalize this occurrence alone: identical duplicate native rows must
        # not look like ambiguous event identity to the shared extractor. Original
        # bytes remain in the hashed source; this view is used only for identity.
        identity_payload = json.loads(body)
        if linked_milestones:identity_payload['milestones']=list(linked_milestones)
        identity_payload['events'] = [native]
        identity_event = replace(event, raw=replace(event.raw, json_text=json.dumps(identity_payload)))
        live_binding=page.get('native_binding_revision') in ('live-native-binding-1','live-native-binding-2') or page.get('v1_comparison_policy')=='manual-comparison-2'
        normalized, mapping = participant_mapping(identity_event,live=live_binding,scope_binding=record.get('native_scope_binding') if page.get('v1_comparison_policy')in ('manual-comparison-1','manual-comparison-2') else None)
        record['participants'] = mapping
        if page.get('v1_comparison_policy')=='manual-comparison-2':
            # Keep only identity fields of exact linked milestones, never the
            # injury/lineup payload, and never inherit unrelated game records.
            record['observed_identity_facts']=[dict(id=m.get('id'),source_id=m.get('source_id'),start_date=m.get('start_date'),**{k:v for k,v in m.get('details',{}).items() if k in ('season','main_game_event_ticker','home_team_id','away_team_id','game_number','original_start','schedule_status','status')}) for m in identity_payload.get('milestones',[]) if eid in m.get('related_event_tickers',[])]

        if page.get('v1_comparison_policy')in ('manual-comparison-1','manual-comparison-2') and venue=='kalshi':
            links={m.get('details',{}).get('main_game_event_ticker') for m in identity_payload.get('milestones',[]) if eid in m.get('related_event_tickers',[]) and m.get('details',{}).get('main_game_event_ticker') in m.get('related_event_tickers',[])}
            if len(links)==1 and None not in links:record['related_game_event_id']=next(iter(links))
        if live_binding:
            roles={p.role:p.resolution.canonical_id for p in normalized.participants if p.role in ('home','away')}
            if set(roles)=={'home','away'} and None not in roles.values() and len(set(roles.values()))==2:
                record['source_participant_roles']=roles
        start = event.scheduled_start
        record['scheduled_start'] = start.isoformat() if start else None
        record.update(sport={'NFL':'american_football','NBA':'basketball','MLB':'baseball','NHL':'hockey','NCAAF':'american_football','NCAAB':'basketball'}.get(normalized.league.canonical_id,event.sport or 'unknown'),competition=normalized.league.canonical_id or event.league)
        resolved = normalized.league.status == 'resolved' and len(mapping) == 2 and None not in mapping.values() and len(set(mapping.values())) == 2
        record['identity'] = 'resolved' if resolved else 'unresolved'
        if normalized.league.status=='conflicting' or any(p.resolution.status=='conflicting' for p in normalized.participants):
            record['exclusion']='native_competition_conflict'
        if resolved and start:
            record['canonical_key'] = [start.astimezone(timezone.utc).isoformat(), sorted(mapping.values())]
        if not start:
            record['exclusion'] = 'unknown_schedule'
        elif start <= as_of:
            record['exclusion'] = 'kickoff_reached'
        elif venue == 'polymarket_us' and (any(native.get(k) is True for k in ('live','ended','closed')) or native.get('period') not in (None,'NS') or native.get('rescheduledFromGameId') not in (None,0,'0')):
            record['exclusion'] = 'phase_or_reschedule'
        # Unresolved participant identity does not remove an otherwise in-scope event.
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        record.update(exclusion='event_parse_error', error=str(exc))
    return record


def market_record(venue, page, body, native, eid, index, series_id='KXNFLGAME'):
    if not isinstance(native,dict):native={'malformed_source':native}
    mid = str(native.get('ticker' if venue == 'kalshi' else 'id') or f'unknown-market-row-{index}')
    record = dict(id=mid, event_id=eid, native_slug=native.get('slug'), title=native.get('title',native.get('question')),
                  market_type='unknown', period='unknown', status='unknown', exclusion=None,
                  terms={k:native[k] for k in ('rules_primary','rules_secondary','description','resolutionSource') if k in native}, sides=[])
    if page.get('native_binding_revision'):record['native_binding_revision']=page['native_binding_revision']
    if venue=='polymarket_us' and (not isinstance(native.get('marketSides'),list) or any(not isinstance(x,dict) for x in native['marketSides'])):
        record['exclusion']='unsupported_market_sides'
        return record
    try:
        r = response(venue, page, body)
        from .native_scope_bindings import POLICY as SCOPE_POLICY, series_binding
        typed_scope = venue == 'kalshi' and page.get('native_scope_policy') == SCOPE_POLICY
        market = kalshi.parse_market(r, native, eid, series_id, typed_scope=typed_scope) if venue == 'kalshi' else polymarket_us.parse_market(r, native, eid)
        record.update(market_type=market.market_type.value, status=market.state.value)
        us_types=polymarket_us.LIVE_FULL_GAME_TYPES if page.get('native_binding_revision') in ('live-native-binding-1','live-native-binding-2') else polymarket_us.FULL_GAME_TYPES
        full = (venue == 'kalshi' and series_id in kalshi.SPORT_SERIES) or native.get('sportsMarketType') in set(us_types.values())
        record['period'] = market.period if typed_scope else 'full_game' if full else 'unknown_or_other'
        if typed_scope:
            binding = series_binding(series_id)
            record['native_scope_binding'] = binding
            record['category'] = binding['category']
            if binding['period'] != 'full_game' or binding['family'] != 'moneyline':
                record['exclusion'] = 'native_scope_predicate_review_required'
                if page.get('native_binding_revision') in ('live-native-binding-1','live-native-binding-2'):
                    from .native_score_binding import bind
                    fact=bind(native,binding)
                    if fact:
                        record['source_predicate']=fact
                        record['line']=fact.get('line')
                        record['exclusion']='native_scope_effective_descriptor_facts_missing'
            if market.state.value != 'active' or native.get('closed') is True or native.get('active') is False:
                record['exclusion'] = 'inactive_or_unknown_market_state'
        elif market.market_type.value != 'moneyline' or not full:
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
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        record.update(exclusion='market_parse_error', error=str(exc))
        # Preserve even malformed native sides; support cannot be established.
        record['sides'] = [dict(id=str(s.get('id')), label=s.get('description'), role=s.get('long'),
                                purchase_support='unknown', basis='market parse failed')
                           for s in native.get('marketSides', []) if isinstance(s,dict)]
    return record


def catalog(pages, venue, as_of, *, v1_templates=(), share_identity=True, compact_output=True, current_selection=None):
    # Current mode may parse only exact listing-selected native IDs while keeping
    # original complete response bytes, hashes and row positions unchanged.
    # Historical callers retain their full catalog behavior.
    selected_events=selected_markets=None
    if current_selection is not None:
        if set(current_selection)!={'events','markets'}:raise ValueError('Exact current catalog selection required')
        selected_events=set(current_selection['events']);selected_markets=set(current_selection['markets'])
        if len(selected_events)>24 or len(selected_markets)>72:raise ValueError('Current catalog selection capacity')
    groups = defaultdict(list)
    linked_milestones=[]
    for page in pages:
        if page['source']==venue and page.get('v1_coverage_policy') and page['path']=='/trade-api/v2/milestones' and page.get('usable_metadata'):
            _,data=decode_page(page);linked_milestones.extend(data['milestones'])
    for page in pages:
        if page['path']=='/trade-api/v2/milestones':continue
        if page['source'] != venue:
            continue
        q = {k:str(v) for k,v in params(page).items() if k not in ('cursor','offset','limit')}
        groups[(page['path'], json.dumps(q,sort_keys=True))].append(page)
    events, markets, discoveries = {}, {}, []
    event_pages = []
    market_pages = []
    for (path, query), values in sorted(groups.items()):
        field = 'events' if event_path(path) else 'markets'
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
            if selected_events is not None and str(native.get('event_ticker' if venue=='kalshi' else 'id')) not in selected_events:continue
            proof = provenance(page,row_index,body)
            record = event_record(venue,page,body,native,row_index,as_of,linked_milestones if page.get('v1_coverage_policy') else ())
            from .native_payload import event_detail_id
            requested = event_detail_id(page['path'])
            if requested is not None and record['id'] != requested:
                record['exclusion'] = 'conflicting_query_identity'
            insert(events,record,native,proof)
            if venue == 'polymarket_us' or params(page).get('with_nested_markets') in (True,'true'):
                embedded = native.get('markets')
                events[record['id']]['market_discovery'] = 'embedded_only' if isinstance(embedded,list) else 'unknown'
                for m in (embedded if isinstance(embedded,list) else []):
                    row_index += 1
                    if selected_markets is not None and str(m.get('id')) not in selected_markets:continue
                    insert(markets,market_record(venue,page,body,m,record['id'],row_index,native.get('series_ticker','KXNFLGAME')),m,provenance(page,row_index,body))
    for page, body, data in market_pages:
        for native in data['markets']:
            row_index += 1
            if selected_markets is not None and str(native.get('ticker' if venue=='kalshi' else 'id')) not in selected_markets:continue
            if venue == 'polymarket_us':
                candidates = [e['id'] for e in events.values()
                              if str(e['_native'].get('gameId')) == str(params(page).get('gameId'))
                              and params(page).get('gameId')]
                if not candidates and params(page).get('slug'):
                    requested=params(page)['slug'];requested=requested if isinstance(requested,list) else [requested]
                    candidates=[e['id'] for e in events.values() if native.get('slug') in requested and any(str(m.get('id'))==str(native.get('id')) and m.get('slug')==native.get('slug') for m in (e['_native'].get('markets') or []) if isinstance(m,dict))]
                from .native_payload import market_detail_id
                if not candidates and market_detail_id(page['path']) is not None:
                    # A detail route identifies a market, not its game. Only
                    # an exact independently retained parent listing can bind it.
                    candidates=[e['id'] for e in events.values() if any(
                        str(m.get('id')) == str(native.get('id')) and m.get('slug') == native.get('slug')
                        for m in (e['_native'].get('markets') or []) if isinstance(m,dict))]
                eid = candidates[0] if len(candidates) == 1 else 'unknown'
            else:
                eid = str(native.get('event_ticker') or params(page).get('event_ticker') or 'unknown')
            record=market_record(venue,page,body,native,eid,row_index,events.get(eid,{}).get('native_aliases',{}).get('series_ticker','unknown'))
            from .native_payload import market_detail_id
            requested = market_detail_id(page['path'])
            if requested is not None and record['id'] != requested:record['exclusion']='conflicting_query_identity'
            if (venue=='kalshi' and params(page).get('event_ticker') and native.get('event_ticker')!=params(page)['event_ticker']) or (venue=='polymarket_us' and params(page).get('gameId') is not None and native.get('gameId') is not None and str(native['gameId'])!=str(params(page).get('gameId'))):
                record['exclusion']='conflicting_query_identity'
            insert(markets,record,native,provenance(page,row_index,body))
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
            missing = sorted({str(m.get('id')) for m in (event['_native'].get('markets') or []) if isinstance(m,dict)} - returned)
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
        if venue=='polymarket_us' and event:
            types=polymarket_us.LIVE_FULL_GAME_TYPES if any(p.get('native_binding_revision') in ('live-native-binding-1','live-native-binding-2') for p,_,_ in event_pages+market_pages) else polymarket_us.FULL_GAME_TYPES
            expected=types.get({'NFL':'nfl','NCAAF':'cfb','MLB':'mlb','NHL':'nhl','NBA':'nba'}.get(event.get('competition')))
            if market['period']=='full_game' and expected!=native.get('sportsMarketType'):market['exclusion']='market_event_sport_conflict'
        if venue == 'polymarket_us':
            sides = native.get('marketSides')
            sides = sides if isinstance(sides,list) and all(isinstance(s,dict) for s in sides) else []
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
                  or {(s['team'].get('name') if isinstance(s.get('team'),dict) else None) for s in sides} != set(event['participants'])
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
    event_states = [d['state'] for d in discoveries if event_path(d['path'])]
    event_discovery = ('exhausted' if event_states and all(s=='exhausted' for s in event_states)
                       else 'failed' if 'failed' in event_states
                       else 'bounded/truncated' if 'bounded/truncated' in event_states else 'unknown')
    result=dict(event_discovery=event_discovery, market_completeness='unestablished' if any(e['market_discovery']!='exhausted' for e in events.values()) or event_discovery!='exhausted' else 'exhausted_for_retained_events',
                events=sorted(events.values(),key=lambda r:r['id']), markets=sorted(markets.values(),key=lambda r:r['id']),
                discovery=discoveries, active_subscriptions=None,
                subscription_basis='offline inventory; no live subscription state queried')

    if any(p.get('v1_comparison_policy')in ('manual-comparison-1','manual-comparison-2') for p in pages if p['source']==venue):
        from .v1_comparison import annotate
        if venue=='polymarket_us' and share_identity and any(p.get('v1_comparison_policy')=='manual-comparison-2' for p in pages):
            other=catalog(pages,'kalshi',as_of,v1_templates=v1_templates,share_identity=False,compact_output=False)
            from .admission_enrichment import share_games
            share_games(result,other)
        annotate(result,venue,v1_templates,policy='manual-comparison-2' if any(p.get('v1_comparison_policy')=='manual-comparison-2' for p in pages if p['source']==venue) else 'manual-comparison-1')
    if compact_output and any(p.get('acquisition_discovery_policy') in ('bounded-open-catalog-v4','sport-directed-games-v1') for p in pages if p['source']==venue):
        from .catalog_metadata import compact
        compact(result,venue)
    return result


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
            other = [e for v,rows in values.items() if v!=venue for e in rows]
            for event in events:
                event['matching_status'] = 'ambiguous' if ambiguous else ('matched' if other else 'unmatched')
                event['counterpart_event_ids'] = [e['id'] for e in other]
    for venue, cat in catalogs.items():
        events = {e['id']:e for e in cat['events']}
        for market in cat['markets']:
            event = events.get(market['event_id'])
            market['matching_status'] = 'excluded' if market['exclusion'] else (event['matching_status'] if event else 'unresolved')
            other_markets = [m for v,c in catalogs.items() if v!=venue for m in c['markets']]
            market['counterpart_market_ids'] = sorted(m['id'] for m in other_markets
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
    evidence=cat.get('excluded_catalog',{})
    for kind in ('events','markets'):
        rows=evidence.get(kind,[]);c=result[kind]
        c['discovered']+=len(rows);c['excluded']+=len(rows)
        c['raw_occurrences']+=sum(r[5] for r in rows);c['duplicates']+=sum(r[5]-1 for r in rows)
        if rows:c['matching']['unsupported']=c['matching'].get('unsupported',0)+len(rows)
        for r in rows:c['exclusions'][r[3]]=c['exclusions'].get(r[3],0)+1
    for k,n in evidence.get('side_counts',{}).items():
        result['sides'][k]+=n;result['sides']['total']+=n
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
