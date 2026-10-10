"""Reviewed aggregate normalization into source-local current records.

Provider event identity binds Novig/ProphetX within this response only. It never
asserts a native occurrence join, depth, payout, season, fees or freshness SLA.
"""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
from app.dashboard.session_projection import stable
from app.dashboard.current_contract import stamp, bounded_decimal
from app.reference.odds_sample import normalize
from app.reference.aggregate import bind, VENUES
from app.reference.product import SPORT_KEYS


def admit(body, sport, received_at, *, venue=None):
    from app.reference.odds_acquire import strict_json
    strict_json(body)
    payload=json.loads(body,parse_float=str)
    if venue is not None and isinstance(payload,list):
        payload=deepcopy(payload)
        for event in payload:
            if not isinstance(event,dict) or not isinstance(event.get('bookmakers'),list):raise ValueError('aggregate_books_shape')
            event['bookmakers']=[b for b in event['bookmakers'] if isinstance(b,dict) and b.get('key')==venue]
    if not isinstance(payload,list) or len(payload)>200: raise ValueError('aggregate_event_bound')
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
    # Existing normalizer preserves original JSON decimal spellings with parse_float=str.
    rows=normalize(json.dumps(payload).encode(),sport,received_at)
    for row in rows:row['receipt_sha256']=sha256(body).hexdigest()
    if len(rows)>1200:raise ValueError('aggregate_quote_bound')
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
                provenance=dict(mode='current',real_source=True,sha256=sha256(body).hexdigest()))
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


def admit_venues(body,sport,received_at):
    records={};errors={}
    for venue in VENUES:
        try:records[venue]=admit(body,sport,received_at,venue=venue)
        except (ValueError,KeyError,TypeError,ArithmeticError,StopIteration) as exc:
            code=str(exc)
            if not code.startswith('aggregate_') or len(code)>80 or not all(c.islower() or c=='_' for c in code):
                code='aggregate_missing_'+exc.args[0] if isinstance(exc,KeyError) and exc.args[0] in ('markets','outcomes','price','point','home_team','away_team','commence_time','sport_key') else 'aggregate_schema_'+type(exc).__name__.lower()
            errors[venue]=code
    return records,errors


def market_exclusions(body):
    """Invalid decimal prices exclude their complete market, never one leg."""
    payload=json.loads(body,parse_float=str);counts={}
    for event in payload if isinstance(payload,list) else []:
        for book in event.get('bookmakers',[]):
            if book.get('key') not in VENUES:continue
            for market in book.get('markets',[]):
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
