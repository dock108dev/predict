"""Bounded committed price dependencies, without rebuilding a board on reads.

Match neighborhoods include possible peers, including newly admitted source events.
Quote clocks belong to their own observation; routine source status clocks do not.
"""
from fractions import Fraction
from .store import encoded, hashed, stamp

VERSION = 'predict-observation-publication-4'


def health(value):
    return {key:value.get(key) for key in ('state','reason_code','reason')}


def identity_index(db):
    """Small membership/identity index; no contracts, prices or ladders decoded."""
    events=db.execute('SELECT id,provider,native_event_id,revision,facts FROM current_event ORDER BY id').fetchall()
    if len(events)>4096:raise ValueError('publication_dependency_capacity')
    epoch=db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch']
    # This is a cached identity lookup, not occurrence resolution, board building,
    # price evaluation or optional financial work.
    from app.normalization.registry import Registry
    registry=Registry.current()
    for event in events:
        facts=event['facts'];roles=[]
        for role in ('home','away'):
            participant=facts.get(role)
            for name,cid in facts.get('participants',{}).items():
                if cid==participant:
                    resolved=registry.resolve('team',name,league=facts.get('competition'),venue=event['provider'])
                    if resolved.status=='resolved':participant=resolved.canonical_id
            roles.append(participant)
        event['pair']=[facts.get('competition'),sorted(roles,key=str)]
        raw=facts.get('_native') or facts.get('native_metadata') or {}
        event['start']=facts.get('original_start') or raw.get('originalStartTime') or facts.get('scheduled_start')
        event['participants']={facts.get(role):value for role,value in zip(('home','away'),roles)}
        shared=dict(facts.get('shared_provider_ids',{}))
        if raw.get('sportradarGameId'):shared['sportradar']=str(raw['sportradarGameId'])
        for fact in facts.get('observed_identity_facts',[]):
            if fact.get('source_provider')=='sportradar' and fact.get('source_id'):
                shared['sportradar']=str(fact['source_id'])
        event['shared']=[[name,str(value)] for name,value in sorted(shared.items())]
    # Matching needs every small event identity and active-membership bit, but
    # only contracts/books in the complete selected neighborhood need decoding.
    # Reviewed aliases can join rescheduled occurrences beyond the metadata
    # time window. Include all such edges conservatively, even expired ones.
    from app.comparison.event_links import reviewed_links
    aliases={}
    for edge in reviewed_links().edges:
        aliases.setdefault((edge.provider,edge.provider_event_id),[]).append(edge.occurrence_id)
    for event in events:
        event['reviewed']=aliases.get((event['provider'],event['native_event_id']),[])
    event_index={r['id']:r for r in events}
    active={r['event_id'] for r in db.execute('SELECT DISTINCT c.event_id FROM current_contract c JOIN current_offer o ON o.contract_id=c.id').fetchall()}
    return dict(epoch=str(epoch),events=event_index,offers={},active_events=active,neighborhoods={})


def capture(db, states, *, selector=None, compact=False, resource_guard=None):
    index=identity_index(db)
    events=list(index['events'].values());epoch=index['epoch'];active=index['active_events']
    selected_ids=None
    if selector is not None:
        selected_ids=[row[0] for row in neighborhood(index,selector)]
    query='''SELECT c.id,c.event_id,c.venue,c.native_market_id,c.native_outcome_id,c.native_side,c.revision AS contract_revision,
        encode(sha256(convert_to((c.facts #- '{comparison_source_metadata,observed_at}')::text,'UTF8')),'hex') AS contract_dependency,
        c.facts AS contract,o.revision AS offer_revision,o.source_at,o.received_at
        FROM current_contract c JOIN current_offer o ON o.contract_id=c.id WHERE (%s::text[] IS NULL OR c.event_id=ANY(%s)) ORDER BY c.id'''
    event_index={r['id']:r for r in events}
    selections={};scope_keys=[];scope_contexts=[]
    def retain(row):
        if row['venue'] in ('kalshi','polymarket_us'):
            event=event_index[row['event_id']];contract=row['contract']
            scope_keys.append((event['provider'],event['native_event_id'],row['native_market_id'],row['native_outcome_id'],row['native_side']))
            scope_contexts.append(dict(league=event['facts'].get('competition'),
                family=contract.get('market_identity',{}).get('family'),
                period=contract.get('market_identity',{}).get('period'),
                native_market_type=contract.get('comparison_source_metadata',{}).get('native_market_type'),
                series_id=contract.get('comparison_source_metadata',{}).get('series_id')))
        if compact:
            if resource_guard:resource_guard(len(encoded(row))*8)
            # Compute the exact same candidate identity before releasing bulky
            # original contract wording. The full contract dependency hash stays.
            selections[row['id']]=_selection(dict(events=event_index),row)
            row['contract']={}
        return row
    if compact:
        offers=[]
        with db.cursor(name='predict_publication_proof') as cursor:
            cursor.itersize=8;cursor.execute(query,(selected_ids,selected_ids))
            for row in cursor:
                if len(offers)>=32768:raise ValueError('publication_dependency_capacity')
                offers.append(retain(row))
    else:
        offers=[retain(row) for row in db.execute(query,(selected_ids,selected_ids)).fetchall()]
    books=db.execute('SELECT venue,event_id,native_market_id,revision,received_at FROM current_native_book WHERE (%s::text[] IS NULL OR event_id=ANY(%s)) ORDER BY venue,event_id,native_market_id',(selected_ids,selected_ids)).fetchall()
    if len(events)>4096 or len(offers)>32768 or len(books)>32768:raise ValueError('publication_dependency_capacity')
    from app.comparison.native_scoring_scope import publication_dependencies
    native_offers=[row for row in offers if row['venue'] in ('kalshi','polymarket_us')]
    by_event={}
    for row in offers:
        row['scoring_dependency']=None
        by_event.setdefault(row['event_id'],[]).append(row)
    for row,dependency in zip(native_offers,publication_dependencies(scope_keys,contexts=scope_contexts)):
        row['scoring_dependency']=dependency
    return dict(epoch=str(epoch),events={r['id']:r for r in events},offers={r['id']:r for r in offers},by_event=by_event,
        books={(r['venue'],r['event_id'],r['native_market_id']):r for r in books},states=states,neighborhoods={},candidate_sets={},selection_identities=selections,active_events=active)


def neighborhood(frame, selector):
    """Necessary conditions used by occurrence resolution; conservative on forks."""
    cache=hashed(selector)
    if cache in frame['neighborhoods']:return frame['neighborhoods'][cache]
    selected=set(selector['events']);occurrences=list(selector['occurrences']);shared=list(selector['shared'])
    for key in selected:
        if key not in frame['events']:continue
        event=frame['events'][key]
        occurrence=[event['pair'],event['start']]
        if occurrence not in occurrences:occurrences.append(occurrence)
        for value in event['shared']:
            if value not in shared:shared.append(value)
    def possible_metadata(event,pair,start):
        if event['pair']!=pair or not event['start'] or not start or abs((stamp(event['start'])-stamp(start)).total_seconds())>3600:
            return False
        # An explicit different game in the same namespace is not a possible
        # metadata peer, including closely scheduled doubleheaders/rematches.
        known={name:{value for namespace,value in shared if namespace==name} for name,_ in shared}
        return all(name not in known or value in known[name] for name,value in event['shared'])
    if 'event_candidate_index' not in frame:
        pairs={};aliases={};reviews={}
        for key,event in frame['events'].items():
            pairs.setdefault(hashed(event['pair']),set()).add(key)
            for value in event['shared']:aliases.setdefault(tuple(value),set()).add(key)
            for value in event.get('reviewed',[]):reviews.setdefault(value,set()).add(key)
        frame['event_candidate_index']=(pairs,aliases,reviews)
    pairs,aliases,reviews=frame['event_candidate_index']
    while True:
        reviewed={alias for key in selected if key in frame['events'] for alias in frame['events'][key].get('reviewed',[])}
        possible=set(selected)
        for pair,_ in occurrences:possible.update(pairs.get(hashed(pair),()))
        for value in shared:possible.update(aliases.get(tuple(value),()))
        for value in reviewed:possible.update(reviews.get(value,()))
        found={key for key in possible if key in frame['events']
               for event in (frame['events'][key],) if key in selected
               or any(possible_metadata(event,pair,start) for pair,start in occurrences)
               or any(value in shared for value in event['shared'])
               or reviewed.intersection(event.get('reviewed',[]))}
        if found<=selected:break
        selected.update(found)
        for key in found:
            event=frame['events'][key]
            occurrence=[event['pair'],event['start']]
            if occurrence not in occurrences:occurrences.append(occurrence)
            for value in event['shared']:
                if value not in shared:shared.append(value)
    active=frame.get('active_events',{value['event_id'] for value in frame['offers'].values()})
    result=sorted((key,frame['events'][key]['revision'],key in active) for key in selected if key in frame['events'])
    frame['neighborhoods'][cache]=result
    return result


def own(frame, cid):
    value=frame['offers'].get(cid)
    if value is None:return None
    book=frame['books'].get((value['venue'],value['event_id'],value['native_market_id']))
    return hashed([value.get('contract_dependency',value['contract_revision']),value['offer_revision'],value['source_at'],
        None if book is None else book['revision'],health(frame['states'].get(value['venue'],{})),
        value.get('scoring_dependency')])


def manifest(frame, bundle):
    from .current_rows import contract_id
    event_ids={hashed([r['quote']['source']['provider'],r['quote']['source']['native_event_id']]) for r in bundle['records']}
    events=[frame['events'][key] for key in sorted(event_ids) if key in frame['events']]
    selector=dict(events=sorted(event_ids),occurrences=[[e['pair'],e['start']] for e in events],shared=[v for e in events for v in e['shared']])
    selections={contract_id(r):selection(frame,frame['offers'][contract_id(r)]) for r in bundle['records']
                if r['quote']['venue']!='pinnacle' and contract_id(r) in frame['offers']}
    # Normalization already ran in the background. Retain its structural peer
    # roster, rather than repeating scope/price admission on an HTTP read.
    from app.dashboard.comparison_board import entries,common_odds
    from app.comparison.same_outcome import quote_identity
    values=entries(bundle['state_inputs']);eligible={}
    for event,group,q in values:
        cid=contract_id(dict(quote=q));identity=quote_identity(q,group,event)
        compatible=[]
        if identity['supported']:
            for other_event,other_group,other in values:
                peer=quote_identity(other,other_group,other_event)
                if (peer['supported'] and peer['key']==identity['key']
                    and other['venue']!=q['venue'] and other['binding']['verified']
                    and other.get('occurrence_match',{}).get('status')=='matched'
                    and other['original']['payout_units']=='USD' and common_odds(other)['supported']):
                    compatible.append(contract_id(dict(quote=other)))
        eligible[cid]=sorted(compatible)
    return dict(version=VERSION,epoch=frame['epoch'],selector=selector,matching=hashed(neighborhood(frame,selector)),
        observations={contract_id(r):own(frame,contract_id(r)) for r in bundle['records'] if r['quote']['venue']!='pinnacle'},
        selections=selections,eligible=eligible,candidates={cid:candidates(frame,selector,value,eligible.get(cid,[])) for cid,value in selections.items()})


def selection(frame, row):
    # Captured SQL frames are immutable. Many selections inspect the same peer;
    # decode its sporting identity once per frame, never across observations.
    cache=frame.get('selection_identities')
    if cache is None:return _selection(frame,row)
    key=row['id']
    if key not in cache:cache[key]=_selection(frame,row)
    return cache[key]


def _selection(frame, row):
    value=row['contract'].get('selection',{});event=frame['events'][row['event_id']]
    market=row['contract'].get('market_identity',{})
    result=dict(venue=row['venue'],participant=event['participants'].get(value.get('participant'),value.get('participant')),
        predicate=value.get('predicate'),signed_line=value.get('signed_line'),family=market.get('family'),period=market.get('period'))
    from app.comparison.same_outcome import candidate_identity
    facts=dict(event.get('facts',{}))
    if facts:
        facts.update({role:event['participants'].get(facts.get(role),facts.get(role)) for role in ('home','away')})
        facts['participants']={name:event['participants'].get(cid,cid) for name,cid in facts.get('participants',{}).items()}
        record=dict(row['contract'],event=facts,selection=dict(value,participant=result['participant']),quote=dict(venue=row['venue'],
            source=dict(provider=event.get('provider',row['venue']),native_event_id=event.get('native_event_id'),
                native_market_id=row.get('native_market_id'),native_outcome_id=row.get('native_outcome_id'),native_side=row.get('native_side'))))
        condition=candidate_identity(record)
        result['condition']=condition['key'] if condition['supported'] else None
        if facts.get('neutral_venue') is True and condition['supported']:
            result['neutral_condition']=_neutral_condition(record)
    return result


def _neutral_condition(record):
    """One detached orientation for two explicitly neutral source witnesses.

    OccurrenceResolver allows their original home/away roles to differ. Keep
    the ordinary source condition too: a single neutral declaration must not
    override the other source's opposite explicit roles.
    """
    from app.comparison.same_outcome import candidate_identity
    event=record['event'];roles=sorted((event['home'],event['away']))
    value=record
    if event['home']!=roles[0]:
        metadata=record.get('comparison_source_metadata',{})
        facts=metadata.get('same_outcome',{})
        predicate=facts.get('predicate')
        if predicate and predicate.get('domain')=='home_margin':
            predicate=dict(predicate,operator={'gt':'lt','ge':'le','lt':'gt','le':'ge','eq':'eq','ne':'ne'}[predicate['operator']],
                threshold=str(-Fraction(predicate['threshold'])))
            metadata=dict(metadata,same_outcome=dict(facts,predicate=predicate))
        value=dict(record,event=dict(event,home=roles[0],away=roles[1]),comparison_source_metadata=metadata)
    condition=candidate_identity(value)
    return condition['key'] if condition['supported'] else None


def _same_candidate(a,b):
    if a.get('condition') is not None and b.get('condition') is not None:
        return a['condition']==b['condition'] or (a.get('neutral_condition') is not None
            and b.get('neutral_condition') is not None and a['neutral_condition']==b['neutral_condition'])
    return all(a.get(field)==b.get(field) for field in ('participant','predicate','signed_line','family','period'))


def candidates(frame, selector, selected, eligible):
    cache=hashed([selector,selected,eligible])
    if cache in frame['candidate_sets']:return frame['candidate_sets'][cache]
    ids={row[0] for row in neighborhood(frame,selector)}
    # Include supported and unresolved scope candidates for this exact native
    # predicate. A later scope correction can admit a formerly ineligible peer;
    # opposing outcomes and same-venue prices cannot change this selection.
    metadata=sorted((row['id'],row.get('contract_dependency',row['contract_revision']),row.get('scoring_dependency')) for key in ids for row in frame['by_event'].get(key,[])
        if row['venue'] not in ('pinnacle',selected['venue'])
        and _same_candidate(selection(frame,row),selected))
    result=hashed([metadata,[(cid,own(frame,cid)) for cid in eligible]])
    frame['candidate_sets'][cache]=result
    return result


def reasons(frame, saved):
    if saved.get('version')!=VERSION:return dict(all=['current_dependencies_changed'],observations={},comparisons={})
    common=[]
    if saved['epoch']!=frame['epoch'] or saved['matching']!=hashed(neighborhood(frame,saved['selector'])):
        common.append('current_dependencies_changed')
    observations={cid:(['current_dependencies_changed'] if own(frame,cid)!=value else [])
                  for cid,value in saved['observations'].items()}
    comparisons={cid:(['current_dependencies_changed'] if candidates(frame,saved['selector'],saved['selections'][cid],saved.get('eligible',{}).get(cid,[]))!=value else [])
                 for cid,value in saved['candidates'].items()}
    return dict(all=common,observations=observations,comparisons=comparisons)
