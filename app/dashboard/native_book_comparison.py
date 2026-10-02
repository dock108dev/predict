"""Reusable raw comparison from exact versioned native judgments."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from app.dashboard.session_projection import stable, stamp, format_book
from app.dashboard.native_reviews import records, validate
VERSION='native-book-comparison-4'


def review():
    # Compatibility accessor for the sealed regression's retained source inputs.
    from app.dashboard.native_book_comparison_sealed_v2 import review as original
    return original()


def settlement(binding):
    return binding['settlement_assessment']


def connect(projection,result,at):
    interpretation=getattr(projection,'native_interpretation',VERSION)
    if interpretation=='original':return
    if interpretation=='native-book-comparison-2':
        from app.dashboard.native_book_comparison_sealed_v2 import connect as sealed
        return sealed(projection,result,at)
    if interpretation=='native-book-comparison-3':
        from app.dashboard.native_book_comparison_sealed_v3 import connect as sealed
        return sealed(projection,result,at)
    try:reviews,errors=records(projection)
    except (ValueError,KeyError,OSError) as exc:
        reviews=[];errors={'registry':str(exc)}
    result['native_comparison_review']=dict(version=VERSION,reviews={},rejections={},errors=errors,assessments={},records={})
    result['projection_revision']+='+'+VERSION
    # Legacy title-based NFL correspondence remains available through sealed versions.
    # This interpretation requires explicit records for real native raw comparisons.
    if projection.spec.get('mode')=='real':
        for game in list(result['games']):
            if set(game['sources'])=={'kalshi','polymarket_us'} and game['product_identity'].get('rules')=='normal-winner-legacy':
                result['games'].remove(game);result['points'].pop(game['id'],None);result['rows_by_game'].pop(game['id'],None)
    for binding in reviews:
        try:
            reasons=connect_one(projection,result,at,binding)
            if reasons:result['native_comparison_review']['errors'][binding['sha256']]=reasons
        except (KeyError,ValueError,TypeError,ArithmeticError) as exc:
            result['native_comparison_review']['errors'][binding['sha256']]=str(exc)


def connect_one(projection, result, at, binding):
    """Add reviewed raw games; qualified sport gates remain independent."""
    accepted={};rejections={}
    token=binding['sha256']
    from app.collection.native_review_binding import CURRENT_POLICIES,revalidated_sources,enabled as current_binding_enabled
    current_policy=binding.get('current_session_revalidation',{}).get('policy') in CURRENT_POLICIES
    if current_binding_enabled(projection.spec) and not current_policy:
        result['native_comparison_review']['assessments'][token]=dict(status='TEMPLATE_ONLY',reason='Selected historical review needs current originating-session receipt revalidation')
        return
    applicable=binding['applicability']
    if applicable['status']!='SUPPORTED' or not stamp(applicable['start'])<=stamp(at)<=stamp(applicable['end']):
        result['native_comparison_review']['assessments'][token]=dict(status='OUTSIDE_REVIEW_INTERVAL',reason='Review is outside its supported effective interval',applicability=deepcopy(applicable))
        return
    result['native_comparison_review']['records'][token]=binding
    for venue,b in binding['sources'].items():
        if current_policy and venue not in revalidated_sources(binding):
            rejections[venue]='Source has no current originating-session receipt binding';continue
        cat=projection.inventory.get(venue,{})
        e=next((e for e in cat.get('events',[]) if e['id']==b['event_id']),None)
        m=next((m for m in cat.get('markets',[]) if m['id']==b['market_id']),None)
        catalog_evidence=b.get('catalog_evidence')
        anchors=getattr(projection,'native_receipts',{})
        anchored=catalog_evidence and all((venue,x['body_sha256']) in anchors and stamp(anchors[(venue,x['body_sha256'])])<=stamp(at) for x in b['provenance'])
        if anchored and (not e or not m or 'native_metadata' not in e or 'native_metadata' not in m or (stable(m['native_metadata'])==b.get('base_native_metadata_sha256') and stable(m['native_metadata'])!=b['native_metadata_sha256'])):
            e=deepcopy(catalog_evidence['event']);m=deepcopy(catalog_evidence['market'])
        if anchored and e and m:
            source_view=next((x for x in result['sources'] if x['source_id']==venue),None)
            if source_view:
                view=source_view.get('catalog')
                if view is None:source_view['catalog']=view=dict(events=[],markets=[])
                for field,value in (('events',e),('markets',m)):
                    if not any(x['id']==value['id'] for x in view.get(field,[])):view.setdefault(field,[]).append(deepcopy(value))
            if not any(x['source_id']==venue and x['market_id']==m['id'] for x in result['market_catalog']):
                result['market_catalog'].append(dict(source_id=venue,event_id=e['id'],market_id=m['id'],title=m['title'],native=deepcopy(m),reason='Reviewed metadata only; exact selected books unavailable at cutoff',usable=False,native_review_sha256=token,identity=deepcopy(binding['identity'])))
        if not e or not m:
            rejections[venue]='Complete reviewed native listing unavailable at cutoff';continue
        if len([x for x in cat.get('events',[]) if x['id']==b['event_id']])>1 or len([x for x in cat.get('markets',[]) if x['id']==b['market_id']])>1:
            rejections[venue]='Conflicting duplicate native IDs';continue
        reason=None
        if cat.get('role','prediction')!='prediction':reason='Reference catalog cannot supply prediction comparison books'
        if not reason and e.get('canonical_key')!=binding['event'] or e.get('identity')!='resolved':reason='Retained canonical event differs from reviewed event'
        elif e.get('conflicting_duplicate') or m.get('conflicting_duplicate') or m.get('exclusion'):reason='Conflicting or excluded retained identity'
        elif 'semantic_review_contract' in b:
            from app.collection.native_review_contract import matches
            if not matches(venue,b['semantic_review_contract'],e['native_metadata'],m['native_metadata']):reason='Native semantic identity or current eligibility differs from versioned review'
            if current_policy and (stable(e['native_metadata'])!=b['event_metadata_sha256'] or stable(m['native_metadata'])!=b['native_metadata_sha256']):
                reason='Current native metadata revision differs from session receipt binding'
        elif stable(e['native_metadata'])!=b['event_metadata_sha256'] or stable(m['native_metadata'])!=b['native_metadata_sha256']:reason='Native metadata differs from exact reviewed listing; outcome mapping unavailable'
        
        ident=binding['identity']
        if not reason and (e.get('competition')!=ident['competition'] or {'hockey':'ice_hockey'}.get(e.get('sport'),e.get('sport'))!=ident['sport'] or m.get('event_id')!=e['id'] or m.get('market_type')!=ident['family'] or m.get('period')!=ident['period'] or m.get('line')!=b.get('descriptor',ident).get('line')):
            reason='Normalized native event / market scope differs from selected review'
        if not reason and set(e.get('participants',{}).values() or e.get('field',[]))!=set(binding['participants']):reason='Reviewed canonical participants differ from retained event'
        if not reason and any(s.get('native_direction') and s['native_direction']!=next((x.get('role','').lower() for x in m.get('sides',[]) if x['id']==n),None) for n,s in b['outcomes'].items()):reason='Native execution direction differs from selected orientation review'
        if not reason and set(b['outcomes'])!=({x['id'] for x in m.get('sides',[])} or {x['native_id'] for x in m.get('product_outcomes',[])}):reason='Reviewed native outcomes differ from retained sides'
        if not reason and not e.get('scheduled_start'):reason='Validated native schedule missing'
        if not reason and current_policy:
            from datetime import timedelta
            if stamp(at)+timedelta(minutes=5)>=stamp(e['scheduled_start']):reason='Current native review is outside the prestart applicability margin'
        if not reason and any(e.get(k) is not None and e.get(k)!=ident.get(k) for k in ('season','stage')):reason='Normalized season/stage differs from selected review'
        normalized=binding.get('normalized_event',{})
        if not reason and any(k in normalized and e.get(k)!=normalized[k] for k in ('competition','season','stage','home','away','game_id','schedule_status','original_start','field','states','category','horizon')):reason='Native event differs from reviewed scoring/state domain'
        key=(venue,b['event_id'],b['market_id'])
        meta=projection.metadata.get(key)
        if not reason and not meta:
            result['native_comparison_review']['assessments'].setdefault(token,{})[venue]=dict(status='METADATA_ONLY',event_id=b['event_id'],market_id=b['market_id'],reason='Exact selected metadata and usable book unavailable at cutoff',provenance=deepcopy(b['provenance']))
            accepted[venue]=(e,m,None,key)
            for market in result['market_catalog']:
                if market['source_id']==venue and market['market_id']==b['market_id']:
                    market.setdefault('native_review_assessments',[]).append(dict(review_sha256=token,review_id=binding['review_id'],revision=binding['revision'],status='METADATA_ONLY',outcomes=deepcopy(b['outcomes']),orientation=deepcopy(b['orientation_evidence']),settlement=settlement(binding),fee=deepcopy(b.get('fee_review',{'status':'UNKNOWN'})),applicability=deepcopy(binding['applicability'])))
            continue
        if not reason:
            raw=meta['market']['raw']
            if stamp(meta['observed_at'])>stamp(at) or stamp(raw['received_at'])>stamp(at):reason='Selected metadata is later than exact cutoff'
            if raw.get('kind')!=binding['evidence_mode']:reason='Native receipt evidence class differs from review'
            if raw['ref']!=dict(venue=venue,event_id=b['event_id'],market_id=b['market_id']) or sha256(raw['json_text'].encode()).hexdigest() not in {p['body_sha256'] for p in b['provenance']}:
                reason='Selected metadata provenance differs from reviewed listing'
            book=projection.books.get(key)
            if book and (stamp(book['observed_at'])>stamp(at) or stamp(book['book']['raw']['received_at'])>stamp(at)):reason='Native book is later than exact cutoff'
            if book and book['book']['raw']['ref']!=raw['ref']:reason='Book native reference differs from selected market'
            if current_policy and book and book['book']['raw']['kind']!=binding['evidence_mode']:reason='Native book evidence class differs from current review'
            if book and {o['outcome_id'] for o in book['book']['outcomes']}!=set(b['outcomes']):reason='Native book outcomes differ from selected review'
        if reason:rejections[venue]=reason;continue
        for market in result['market_catalog']:
            if market['source_id']==venue and market['market_id']==b['market_id']:
                market.setdefault('native_review_assessments',[]).append(dict(review_sha256=token,review_id=binding['review_id'],revision=binding['revision'],outcomes=deepcopy(b['outcomes']),orientation=deepcopy(b['orientation_evidence']),settlement=settlement(binding),fee=deepcopy(b.get('fee_review',{'status':'UNKNOWN'})),applicability=deepcopy(binding['applicability'])))
                if current_policy and book:market['native_book']=deepcopy(book['book'])
        accepted[venue]=(e,m,meta,key)
    result['native_comparison_review']['reviews'][token]=dict(version=VERSION,binding_sha256=token,rejections=rejections,settlement=settlement(binding))
    result['native_comparison_review']['rejections'].update(rejections)
    if set(accepted)!=set(binding['sources']):
        for m in result['market_catalog']:
            venue=m['source_id'];b=binding['sources'].get(venue)
            if b and m['market_id']==b['market_id'] and venue in rejections:m['native_review_exclusion']=rejections[venue]
        return rejections
    # A reviewed contract replaces its legacy interpretation only in this explicit version.
    target={v:(b['event_id'],b['market_id']) for v,b in binding['sources'].items()}
    replaced=[g for g in result['games'] if {v:(s['event_id'],s['market_id']) for v,s in g['sources'].items()}==target]
    for g in replaced:
        result['games'].remove(g);result['points'].pop(g['id'],None);result['rows_by_game'].pop(g['id'],None)
    missing=[v for v,(e,m,meta,key) in accepted.items() if not meta or key not in projection.books]
    if missing:
        result['native_comparison_review']['assessments'][token]=dict(status='METADATA_ONLY',sources=deepcopy(target),missing_books=missing,reason='Identity/orientation assessment only; two native books required for a priced comparison',settlement=settlement(binding))
        return
    if len({projection.inventory.get(v,{}).get('origin_id',v) for v in accepted})!=len(accepted):return {'origin':'Reviewed prediction sources share an origin; independent venue books required'}
    if len(result['games'])>=64:return {'capacity':'Native comparison game capacity reached'}
    sides={};cards=[]
    for venue,(e,m,meta,key) in accepted.items():
        b=binding['sources'][venue]
        for native,s in b['outcomes'].items():
            side=dict(s,native_id=native,native_label=s.get('native_label',native))
            if s.get('comparison_outcome'):
                from app.normalization.score_lines import descriptor
                domain=descriptor(binding['normalized_event'],b['descriptor'])
                if domain['domain']=='championship_states':label=b['descriptor']['participant']+' · '+s['role'].replace('_',' ')
                else:label=domain['domain'].replace('_',' ').capitalize()+' '+{'gt':'>','ge':'≥','lt':'<','le':'≤','eq':'=','ne':'≠'}[s['operator']]+' '+domain['threshold']
                side['comparison_label']=label
            sides[venue+':'+native]=side
        row=projection.books.get(key)
        derived_row=row
        if row and venue=='polymarket_us' and any(o['asks'] is None for o in row['book']['outcomes']) and any(o.get('native_direction')=='long' for o in b['outcomes'].values()) and not any(o.get('comparison_outcome') for o in b['outcomes'].values()):
            from app.collection.native_semantics import purchase_saved_book
            cache=getattr(projection,'purchase_review_cache',{})
            key_hash=stable([row['book']['raw'],b['outcomes']])
            if cache.get(key,{}).get('hash')!=key_hash:cache[key]=dict(hash=key_hash,row=purchase_saved_book(row,b['outcomes']))
            projection.purchase_review_cache=cache;derived_row=cache[key]['row']
        formatted=format_book(derived_row,{venue:{n:(s['participant'],n) for n,s in b['outcomes'].items()}}) if row else None
        age=None if not row else str(Decimal(str((stamp(at)-stamp(row['book']['raw']['received_at'])).total_seconds())))
        state='disconnected' if projection.finished else projection.health.get(key,{}).get('state','awaiting_snapshot')
        if key in projection.invalid and state=='connected':state='resynchronization_required'
        if formatted:
            # Health re-emissions retain the same underlying native observation.
            formatted['id']=stable([venue,row['book']['raw']['json_text'],row['book']['raw']['received_at']])
            formatted['native_observation']=deepcopy(projection.book_evidence.get(key))
            formatted['native_raw']=row['book']['raw']
            formatted['native_ladders']=row['book']['outcomes']
            if derived_row is not row:formatted['purchase_interpretation']=dict(version='native-purchase-saved-1',method='Shared purchase_book: Short complements native Long bids',ladders=derived_row['book']['outcomes'])
            formatted['application_received_at']=row.get('application_received_at')
            formatted['local_timing']=deepcopy(row.get('local_timing'))
        cards.append(dict(venue=venue,label={'kalshi':'Kalshi','polymarket_us':'Polymarket US'}[venue],book=formatted,connection=state,age_seconds=age,receipt_stale=age is None or Decimal(age)>15))
    gid=stable([VERSION,token,binding['event'],[(s,b['event_id'],b['market_id']) for s,b in binding['sources'].items()]])
    scheduled=next(iter(accepted.values()))[0]['scheduled_start']
    if any(stamp(e['scheduled_start'])!=stamp(scheduled) for e,m,meta,key in accepted.values()):return {'association':'Reviewed native schedules differ'}
    ident=dict(binding['identity'],version=4,event=binding['event'],scheduled_start=scheduled,rules=token)
    game=dict(id=gid,native_raw=True,title=' vs '.join(binding['participants'].values())+' · '+ident['period'].replace('_',' ')+' '+ident['family']+(' · line '+str(ident['line']) if ident.get('line') is not None else ''),scheduled_start=scheduled,teams=sorted(binding['participants'].values()),sides=sides,sources={s:dict(event_id=b['event_id'],market_id=b['market_id'],native_review_version=VERSION,native_review=binding) for s,b in binding['sources'].items()},candidates=[],product_identity=ident,native_review=dict(version=VERSION,binding_sha256=token,record=binding,settlement=settlement(binding),orientation={s:b['orientation_evidence'] for s,b in binding['sources'].items()}))
    result['games'].append(game)
    for venue,source in game['sources'].items():
        fact=getattr(projection,'native_fee_contexts',{}).get(source['event_id']) if venue=='kalshi' else None
        if fact and stamp(fact['observed_at'])<=stamp(at):source['current_fee_metadata']=deepcopy(fact)
    result['points'][gid]=dict(id=result['durable_cursor'],at=at,cards=cards,label='Exact retained cutoff')
    result['rows_by_game'][gid]=[a[2] for a in accepted.values()]
    for m in result['market_catalog']:
        if m['source_id'] in accepted and m['market_id']==binding['sources'][m['source_id']]['market_id']:
            m['qualified_exclusion']=m['reason'];m['reason']='Raw comparison connected; settlement '+settlement(binding)['status'].lower()+'; net evidence assessed separately'
            m['outcome_review']=deepcopy(binding['sources'][m['source_id']]['orientation_evidence'])


def entry(contract,quantity,at,identity,source):
    if identity.get('rules')=='native-book-comparison-2':
        from app.dashboard.native_book_comparison_sealed_v2 import entry as sealed
        return sealed(contract,quantity,at,identity,source)
    if source.get('native_review') and not source.get('native_review_version'):
        from app.dashboard.native_book_comparison_sealed_v3 import entry as sealed
        return sealed(contract,quantity,at,identity,source)
    from app.depth import consume
    value=dict(lower=None,upper=None,net=None,notional=None,quantity=str(quantity),reason='Selected native fee review missing',fee_status='UNKNOWN',basis='Provisional entry only; settlement/private costs assessed separately')
    if quantity<=0:return value
    try:
        fills=consume(contract['levels'],str(quantity))
        value['notional']=str(sum(Decimal(f['price'])*Decimal(f['quantity']) for f in fills))
        b=validate(source['native_review'])
        s=b['sources'][contract['venue']]
        fact=source.get('current_fee_metadata')
        if fact and contract['venue']=='kalshi' and stamp(fact['observed_at'])<=stamp(at):
            from app.fees.engine import kalshi_terms
            c=fact['context']
            if c['event_id']!=source['event_id']:raise ValueError('Current fee event identity differs')
            value['current_fee_terms']=kalshi_terms(dict(series_id=c['series_id'],event_id=c['event_id'],kalshi_metadata=c),at)
            value['current_fee_evidence']=deepcopy(fact)
        if source['event_id']!=s['event_id'] or source['market_id']!=s['market_id'] or identity['rules']!=b['sha256']:raise ValueError('Selected fee review identity differs')
        from app.collection.native_review_binding import CURRENT_POLICIES,revalidated_sources
        if b.get('current_session_revalidation',{}).get('policy') in CURRENT_POLICIES:
            if contract['venue'] not in revalidated_sources(b):raise ValueError('Source has no current originating-session receipt binding')
            current=b['applicability']
            if current['status']!='SUPPORTED' or not stamp(current['start'])<=stamp(at)<stamp(current['end']):raise ValueError('Current native review outside originating-session applicability')
        f=s.get('fee_review',dict(status='UNKNOWN',evidence=[],reason='Selected native fee review missing'));a=f.get('applicability',b.get('source_template_applicability',{}).get(contract['venue'],b['applicability']))
        value['evidence']=dict(version=VERSION,review_sha256=b['sha256'],listing=s['provenance'],fee=deepcopy(f))
        value['fee_status']=f['status']
        if a['status']!='SUPPORTED' or not stamp(a['start'])<=stamp(at)<=stamp(a['end']):raise ValueError('Fee evidence outside effective interval')
        if f['status'] in ('UNKNOWN','INCOMPATIBLE'):raise ValueError(f.get('reason','Fee review '+f['status'].lower()))
        if quantity!=quantity.to_integral_value() and not f.get('fractional'):raise ValueError('Fractional execution applicability unverified')
        if quantity<Decimal(f.get('minimum_quantity','0')):raise ValueError('Requested quantity below reviewed minimum')
        if f['model']=='us_taker_bound' and contract['venue']=='polymarket_us':
            from app.fees.entry_bounds import us_taker_bound
            audit=us_taker_bound(fills,f['coefficient'])
            if f['status']=='SUPPORTED':value.update(lower=value['notional'],upper=str(Decimal(value['notional'])+Decimal(audit['upper'])),audit=audit,reason=None)
            else:value.update(conditional_fee_scenario=audit,reason=f.get('reason','Conditional fee formula only'))
        elif f['model']=='kalshi' and contract['venue']=='kalshi':
            from app.fees import calculate
            c=deepcopy(f['context']);c.update(venue='kalshi',environment='production',market_id=s['market_id'],event_id=s['event_id'],product='event_contract',trade_time=at,calculation_time=at,complete_order_history=True,settlement_status='UNKNOWN',outcomes={},fills=[dict(fill_id=str(i),order_id='hypothetical-new-taker-order',role='taker',price=x['price'],quantity=x['quantity'],unit='contracts') for i,x in enumerate(fills)])
            c['kalshi_metadata']['event_id']=s['event_id']
            for x in c['kalshi_metadata']['series_changes']:x.setdefault('scheduled_ts',a['start'])
            audit=calculate(c)
            if f['status']=='SUPPORTED':value.update(lower=audit['entry_cash_requirement'],upper=audit['entry_cash_requirement'],audit=audit,reason=None if audit['entry_cash_requirement'] else 'Fee engine rejected review context')
            else:value.update(conditional_fee_scenario=audit,reason=f.get('reason','Conditional fee formula only'))
        else:raise ValueError('Unsupported reviewed fee model')
    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:value['reason']=str(exc)
    return value
