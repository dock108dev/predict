"""Reviewed aggregate normalization into source-local current records.

Provider event identity binds Novig/ProphetX within this response only. It never
asserts a native occurrence join, depth, payout, season, fees or freshness SLA.
"""
from dataclasses import dataclass
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
from app.dashboard.session_projection import stable
from app.dashboard.current_contract import stamp, bounded_decimal
from app.reference.odds_sample import normalize
from app.reference.aggregate import bind, VENUES
from app.reference.product import SPORT_KEYS


@dataclass(frozen=True)
class ParsedAggregateFrame:
    payload: object
    receipt_sha256: str


def parse_frame(body):
    """One strict decode retaining original decimal spellings for every adapter."""
    from app.reference.odds_acquire import strict_json
    return ParsedAggregateFrame(strict_json(body,parse_float=str),sha256(body).hexdigest())


def _frame(body,frame):
    frame=parse_frame(body) if frame is None else frame
    # A retained SQL parse already carries its original receipt identity. Never
    # reserialize it and pretend that the resulting bytes were provider bytes.
    valid=isinstance(frame,ParsedAggregateFrame) and len(frame.receipt_sha256)==64 and all(c in '0123456789abcdef' for c in frame.receipt_sha256)
    if not valid or (body is not None and frame.receipt_sha256!=sha256(body).hexdigest()):
        raise ValueError('aggregate_parsed_frame_identity')
    return frame


def admit(body, sport, received_at, *, venue=None, event_ids=None, frame=None):
    frame=_frame(body,frame)
    from datetime import datetime,timezone,timedelta
    receipt=datetime.fromisoformat(received_at.replace('Z','+00:00'))
    if receipt.utcoffset() is None:raise ValueError('aggregate_receipt_timezone_required')
    if receipt.utcoffset()!=timedelta(0):received_at=receipt.astimezone(timezone.utc).isoformat()
    # Venue filtering/validation is isolated; it never mutates the shared frame.
    payload=deepcopy(frame.payload)
    if event_ids is not None:
        # A read may normalize only already-admitted provider events. Keep the
        # full original receipt hash below; filtering is never new acquisition
        # or an assertion that omitted games/books were present.
        if not isinstance(event_ids,(set,frozenset,tuple,list)) or any(not isinstance(v,str) or not v for v in event_ids):
            raise ValueError('aggregate_selected_event_identity')
        if not isinstance(payload,list):
            raise ValueError('aggregate_event_bound')
        payload=[e for e in payload if isinstance(e,dict) and e.get('id') in event_ids]
    if venue is not None and isinstance(payload,list):
        payload=deepcopy(payload)
        for event in payload:
            if not isinstance(event,dict) or not isinstance(event.get('bookmakers'),list):raise ValueError('aggregate_books_shape')
            event['bookmakers']=[b for b in event['bookmakers'] if isinstance(b,dict) and b.get('key')==venue]
    if not isinstance(payload,list): raise ValueError('aggregate_event_bound')
    seen=set()
    for event in payload:
        if not isinstance(event,dict) or event.get('id') in seen: raise ValueError('aggregate_event_identity')
        seen.add(event.get('id'))
        books=set()
        if not isinstance(event.get('bookmakers'),list): raise ValueError('aggregate_books_shape')
        for book in event['bookmakers']:
            if book.get('key') not in (*VENUES,'pinnacle') or book['key'] in books: raise ValueError('aggregate_book_identity')
            books.add(book['key']);markets=set();valid_markets=[]
            for market in book['markets']:
                if market['key'] in markets or market['key'] not in ('h2h','spreads','totals'): raise ValueError('aggregate_market_identity')
                markets.add(market['key']);supported_prices=True
                if len(market['outcomes'])!=2: raise ValueError('aggregate_complete_two_way_required')
                names=[o['name'] for o in market['outcomes']]
                expected=['Over','Under'] if market['key']=='totals' else [event['home_team'],event['away_team']]
                if sorted(names)!=sorted(expected): raise ValueError('aggregate_outcome_identity')
                for outcome in market['outcomes']:
                    value=bounded_decimal(str(outcome['price']))
                    if value<=1:supported_prices=False
                    if market['key']!='h2h': bounded_decimal(str(outcome['point']))
                if market['key']=='totals' and Decimal(str(market['outcomes'][0]['point']))!=Decimal(str(market['outcomes'][1]['point'])):raise ValueError('aggregate_total_line_conflict')
                if market['key']=='spreads' and Decimal(str(market['outcomes'][0]['point']))!=-Decimal(str(market['outcomes'][1]['point'])):raise ValueError('aggregate_spread_line_conflict')
                if supported_prices:valid_markets.append(market)
            book['markets']=valid_markets
    # The existing normalizer consumes the already-decoded exact fields.
    rows=normalize(body,sport,received_at,_parsed_events=payload,_receipt_sha256=frame.receipt_sha256)
    bound=bind(rows)
    for r in bound:
        if r['price_issue']:raise ValueError('aggregate_decimal_price')
        if r['reasons']:raise ValueError('aggregate_binding_rejected')
    records=[]
    by_group={}
    for r in bound:
        original=r['original'];event_id=original['source_event_id'];book=original['bookmaker']
        by_group.setdefault((event_id,book,original['market']),[]).append(r)
    for (event_id,book,market),values in by_group.items():
        if len(values)!=2:raise ValueError('aggregate_group_incomplete')
        values=sorted(values,key=lambda x:x['original']['outcome'])
        r=values[0];raw=r['original'];parts=r['identity']['participants'] if 'participants' in r['identity'] else None
        # Reuse reviewed participant mapping, including explicit provider-slot IDs.
        home=next(x['participant'] for x in values if x['original']['outcome']==raw['home_team']) if market!='totals' else None
        away=next(x['participant'] for x in values if x['original']['outcome']==raw['away_team']) if market!='totals' else None
        if market=='totals':
            from app.normalization.college_registry import aggregate_registry
            registry=aggregate_registry()
            def participant(role):
                found=registry.resolve('team',raw[role+'_team'],league=sport,venue='the_odds_api')
                return found.canonical_id if found.status=='resolved' else 'the_odds_api:'+sport+':'+event_id+':'+role+'_team'
            home,away=participant('home'),participant('away')
        event=dict(id=event_id,sport={'NFL':'american_football','NCAAF':'american_football','NBA':'basketball','NCAAB':'basketball','MLB':'baseball','NHL':'ice_hockey'}[sport],
            competition=sport,season='unverified',stage='unverified',scheduled_start=raw['scheduled_start'],home=home,away=away,
            participants={raw['home_team']:home,raw['away_team']:away},title=raw['away_team']+' at '+raw['home_team'])
        from app.storage.store import hashed
        from app.storage.schedule_metadata import VERSION as SCHEDULE_VERSION
        witness=dict(version=SCHEDULE_VERSION,native_event_id=event_id,authority=['the_odds_api','event',event_id],
            start=raw['scheduled_start'],received_at=received_at,
            proofs=[dict(path='the_odds_api/receipt/'+frame.receipt_sha256,body_sha256=frame.receipt_sha256,received_at=received_at)])
        event['schedule_metadata']=dict(witness,revision=hashed(witness))
        from app.comparison.event_links import provider_key
        key=provider_key('the_odds_api',event)
        family={'h2h':'moneyline','spreads':'spread','totals':'total'}[market]
        canonical=None if market=='h2h' else next(x['original']['point'] for x in values if market=='totals' or x['participant']==home)
        selections=[dict(participant=None if market=='totals' else x['participant'],predicate=x['predicate'] if market!='spreads' else 'cover',
            signed_line=x['original']['point'],label=x['original']['outcome']) for x in values]
        for r,selection in zip(values,selections):
            raw=r['original'];source_time=raw['source_at']
            if source_time is not None:stamp(source_time)
            clocks={kind:raw['source_fields'][kind].get('last_update') for kind in ('book','market')}
            for clock in clocks.values():
                if clock is not None:stamp(clock)
            clock_basis='market' if clocks['market'] else 'book' if clocks['book'] else 'unknown'
            source=dict(provider='the_odds_api',native_event_id=event_id,
                native_market_id=stable([event_id,market,raw['point'],raw['outcome']]),native_outcome_id=raw['outcome'],
                native_side='bookmaker_outcome',binding_id=r['id'],binding_version=r['version'],native_line=raw['point'],quote_side='buy')
            q=dict(id='',revision=1,venue=book,source=source,
                original=dict(value=raw['decimal_odds'],units='decimal_odds',payout='1',payout_units='USD',quantity_units='unknown',role='comparison'),
                times=dict(source_at=source_time,received_at=received_at,projected_at=received_at,
                    source_time_kind='provider_book' if source_time else 'unknown'),state='budget_delayed',
                rule_note='Aggregate full-game outcome; settlement and native occurrence association unverified.',
                cost_note='Cents are 1 / decimal odds per mathematical unit payout. Actual fees, execution, depth and probability unknown.',
                observation_time_evidence='The Odds API original update clocks: '+json.dumps(clocks,sort_keys=True)+
                    '; selected basis: '+clock_basis+'; upstream delay unknown.',
                provider_clocks=dict(book=clocks['book'],market=clocks['market'],selected_basis=clock_basis),
                provenance=dict(mode='current',real_source=True,sha256=frame.receipt_sha256))
            record=dict(event=deepcopy(event),market_identity=dict(event=key,sport=event['sport'],competition=sport,season='unverified',stage='unverified',
                scheduled_start=raw['scheduled_start'],family=family,period='full_game',line=canonical,outcome_set=stable(selections),rules='aggregate-common-1'),
                period_boundary='Provider full-game market; exceptional settlement unverified',anchor_participant=home if market=='spreads' else None,
                selection=selection,quote=q,orientation_evidence=[r['version']+':'+r['registry_sha256'],raw['receipt_sha256']],verified=True,
                outcome_cardinality=2,outcome_selections=deepcopy(selections),result_policy='aggregate-common-1:'+market,
                event_scope=dict(policy='aggregate-provider-event-2',source='the_odds_api',native_event_id=event_id))
            instrument=stable([book,event_id,market,raw['outcome'],raw['point']])
            # Binder IDs include receipt hashes; revision identity must not.
            source['binding_id']=instrument
            record['_instrument']=instrument
            record['_fingerprint']=stable([source,q['original'],q['state'],record['market_identity']])
            records.append(record)
    return records


def admit_alternate(body,sport,received_at,*,frame=None):
    """Split original alternate ladders into exact two-outcome full-game lines.

    The base-market projection is only adapter input. Every resulting quote
    retains the actual event-odds receipt hash, original price and source clocks.
    Route-prefixed instruments keep independent authoritative refresh scopes.
    """
    from collections import defaultdict
    frame=_frame(body,frame);event=frame.payload
    if not isinstance(event,dict):raise ValueError('aggregate_event_identity')
    records=[];errors={};complete=[]
    for venue in (*VENUES,'pinnacle'):
        books=[b for b in event.get('bookmakers',[]) if b.get('key')==venue]
        if len(books)>1:errors[venue]='aggregate_book_identity';continue
        failed=False
        for book in books:
            seen=set()
            for market in book.get('markets',[]):
                try:
                    native=market['key'];base={'alternate_spreads':'spreads','alternate_totals':'totals'}[native]
                    if native in seen:raise ValueError('aggregate_market_identity')
                    seen.add(native);pairs=defaultdict(list)
                    for outcome in market['outcomes']:
                        try:
                            line=bounded_decimal(str(outcome['point']))
                            if base=='spreads' and outcome['name']==event['away_team']:line=-line
                            pairs[line].append(outcome)
                        except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                            failed=True;errors[venue]=_admission_error(exc)
                    for outcomes in pairs.values():
                        if len(outcomes)!=2:
                            failed=True;errors[venue]='aggregate_complete_two_way_required'
                            continue
                        try:
                            selected=deepcopy(event)
                            selected['bookmakers']=[dict(book,markets=[dict(market,key=base,outcomes=outcomes)])]
                            subset=ParsedAggregateFrame([selected],frame.receipt_sha256)
                            pair=admit(body,sport,received_at,venue=venue,frame=subset)
                            for row in pair:
                                source=row['quote']['source']
                                source['native_market_id']='alternate:'+source['native_market_id']
                                source['binding_id']='alternate:'+source['binding_id']
                                row['_instrument']='alternate:'+row['_instrument']
                                row['quote']['rule_note']='Aggregate '+native+' exact full-game line; settlement and native occurrence association unverified.'
                            records.extend(pair)
                        except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                            failed=True;errors[venue]=_admission_error(exc)
                except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                    failed=True;errors[venue]=_admission_error(exc)
        if not failed:complete.append(venue)
    return records,complete,errors


def _admission_error(exc):
    code=str(exc)
    if not code.startswith('aggregate_') or len(code)>80 or not all(c.islower() or c=='_' for c in code):
        code='aggregate_missing_'+exc.args[0] if isinstance(exc,KeyError) and exc.args[0] in ('markets','outcomes','price','point','home_team','away_team','commence_time','sport_key') else 'aggregate_schema_'+type(exc).__name__.lower()
    return code


def admit_venues(body,sport,received_at,*,frame=None,include_reference=False):
    records={};errors={};venues=(*VENUES,'pinnacle') if include_reference else VENUES
    try:frame=_frame(body,frame)
    except (ValueError,KeyError,TypeError,ArithmeticError,StopIteration) as exc:
        return {},{venue:_admission_error(exc) for venue in venues}
    for venue in venues:
        try:records[venue]=admit(body,sport,received_at,venue=venue,frame=frame)
        except (ValueError,KeyError,TypeError,ArithmeticError,StopIteration) as exc:
            errors[venue]=_admission_error(exc)
            # Recover independent valid markets without claiming a complete
            # venue replacement. Original receipt identity and clocks survive.
            recovered=[]
            if isinstance(frame.payload,list):
                for event in frame.payload:
                    if not isinstance(event,dict):continue
                    for book in event.get('bookmakers',[]) if isinstance(event.get('bookmakers'),list) else []:
                        if not isinstance(book,dict) or book.get('key')!=venue:continue
                        for market in book.get('markets',[]) if isinstance(book.get('markets'),list) else []:
                            partial=deepcopy(event)
                            partial['bookmakers']=[dict(book,markets=[market])]
                            subset=ParsedAggregateFrame([partial],frame.receipt_sha256)
                            try:recovered.extend(admit(body,sport,received_at,venue=venue,frame=subset))
                            except (ValueError,KeyError,TypeError,ArithmeticError,StopIteration):pass
            if recovered:records[venue]=recovered
    return records,errors


def market_exclusions(body,*,frame=None):
    """Invalid decimal prices exclude their complete market, never one leg."""
    payload=_frame(body,frame).payload;counts={}
    for event in payload if isinstance(payload,list) else []:
        if not isinstance(event,dict):continue
        for book in event.get('bookmakers',[]) if isinstance(event.get('bookmakers'),list) else []:
            if not isinstance(book,dict) or book.get('key') not in VENUES:continue
            for market in book.get('markets',[]) if isinstance(book.get('markets'),list) else []:
                if not isinstance(market,dict):continue
                try:bad=any(bounded_decimal(str(o['price']))<=1 for o in market['outcomes'])
                except (ValueError,KeyError,TypeError):continue
                if bad:counts[book['key']]=counts.get(book['key'],0)+1
    return counts


def diagnostic(body,sport,received_at,rejected):
    """Latest bounded allowlisted parser replay; no URLs, headers or extra fields."""
    try:payload=json.loads(body,parse_float=str)
    except (ValueError,UnicodeError):payload=None
    def pick(value,keys):
        if not isinstance(value,dict):return None
        return {k:v for k,v in value.items() if k in keys and (isinstance(v,(str,int,bool)) or v is None) and len(str(v))<=2048}
    events=[]
    if isinstance(payload,list) and len(payload)<=200:
        for event in payload:
            e=pick(event,('id','sport_key','commence_time','home_team','away_team'))
            if e is None:continue
            e['bookmakers']=[]
            for book in event.get('bookmakers',[]) if isinstance(event.get('bookmakers'),list) else []:
                b=pick(book,('key','last_update'))
                if b is None:continue
                b['markets']=[]
                for market in book.get('markets',[]) if isinstance(book.get('markets'),list) else []:
                    m=pick(market,('key','last_update'))
                    if m is None:continue
                    m['outcomes']=[pick(o,('name','price','point')) for o in market.get('outcomes',[])] if isinstance(market.get('outcomes'),list) else None
                    b['markets'].append(m)
                e['bookmakers'].append(b)
            events.append(e)
    return dict(schema='predict-redacted-aggregate-diagnostic-1',sport=sport,received_at=received_at,
                body_sha256=sha256(body).hexdigest(),body_bytes=len(body),rejections=rejected,
                replay=events if isinstance(payload,list) else None,retention='Latest response per sport, max 2 MiB; allowlisted fields only')
