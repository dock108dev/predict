"""Read-only candidate lookup evidence using production occurrence predicates."""
from app.comparison.occurrence_matching import OccurrenceResolver,UNKNOWN
from . import observation_publication as publication
from .store import stamp


def census(db):
    resolver=OccurrenceResolver();index=publication.identity_index(db);facts={};out=[]
    for key,row in index['events'].items():
        if key not in index['active_events']:continue
        facts[key]=resolver._facts(dict(event=row['facts'],quote=dict(source=dict(
            provider=row['provider'],native_event_id=row['native_event_id'],binding_version='census'),provenance={})))
    for key,a in facts.items():
        lookup={v[0] for v in publication.neighborhood(index,dict(events=[key],occurrences=[],shared=[]))}
        peers=[(k,b) for k,b in facts.items() if b['key'][0]!=a['key'][0] and b['league']==a['league']
            and (set(a['roles'].values()) & set(b['roles'].values())-{None} or
                 any(b['shared'].get(n)==v for n,v in a['shared'].items()))]
        valid=[];rejected=[]
        for k,b in peers:
            differences=[]
            for field in ('roles','season','stage','game_number','replacement'):
                if a[field]!=b[field]:differences.append(dict(field=field,expected=a[field],observed=b[field]))
            for namespace in set(a['shared']) & set(b['shared']):
                if a['shared'][namespace]!=b['shared'][namespace]:differences.append(dict(field='shared.'+namespace,expected=a['shared'][namespace],observed=b['shared'][namespace]))
            clocks=(a['original_start'] or a['start'],b['original_start'] or b['start'])
            gap=abs((stamp(clocks[0])-stamp(clocks[1])).total_seconds())
            if gap>3600:differences.append(dict(field='start',expected=clocks[0],observed=clocks[1],gap_seconds=gap,maximum_seconds=3600))
            missing=[field for field in ('season','stage') if a[field] in UNKNOWN and b[field] in UNKNOWN]
            source_local=any(a[field] in UNKNOWN for field in ('season','stage')) if a['key'][0] in ('kalshi','polymarket_us') else False
            peer_local=any(b[field] in UNKNOWN for field in ('season','stage')) if b['key'][0] in ('kalshi','polymarket_us') else False
            exact_context_peer=(source_local != peer_local and a['roles']==b['roles']
                and stamp(a['start'])==stamp(b['start']) and resolver._metadata(a,b))
            compatible=resolver._metadata(a,b) and not (a['conflict'] or b['conflict']) and (
                not(source_local or peer_local) or exact_context_peer)
            row=dict(identity=list(b['key']),event_id=k,in_publication_lookup=k in lookup,
                differences=differences,missing_shared_context=missing,source_local_exclusion=source_local and not exact_context_peer,
                peer_source_local_exclusion=peer_local and not exact_context_peer,metadata_candidate_only=True,identity_conflict=a['conflict'] or b['conflict'])
            if compatible:valid.append(row)
            else:rejected.append(row)
        omitted=[r for r in valid if not r['in_publication_lookup']]
        reason=('normalized_compatible_peer_omitted_from_lookup' if omitted else
            'compatible_normalized_candidates_present' if valid else
            'normalized_peers_rejected_by_facts' if rejected else
            'no_normalized_peer_with_shared_participant_or_id_received')
        out.append(dict(identity=list(a['key']),event_id=key,revision=index['events'][key]['revision'],
            lookup_keys=dict(league=a['league'],roles=a['roles'],shared=a['shared'],start=a['start']),
            lookup_count=len(lookup),tested_normalized_peer_count=len(peers),compatible_count=len(valid),
            primary_reason=reason,compatible=valid,rejected_examples=rejected[:3],
            rejected_count=len(rejected),owner='app.comparison.occurrence_matching.OccurrenceResolver',
            limitation='Pair metadata compatibility does not establish mutual uniqueness or contract admission. No normalized peer does not prove no raw peer; join native receipt diagnostics before assigning source absence'))
    return out


def link_raw_peers(db, rows, receipt_trace):
    """Join the existing normalized audit to retained native receipts.

    Absence is bounded to retained catalogs/receipts. A provider's unreceived or
    discarded history cannot be reconstructed or asserted as never offered.
    """
    from collections import defaultdict,Counter
    resolver=OccurrenceResolver();raw=[];receipts=defaultdict(list)
    for r in receipt_trace['records']:receipts[(r['source'],r['event_id'])].append(r)
    normalized={tuple(r['identity']):r for r in rows}
    for catalog in db.execute('SELECT source,header FROM current_native_catalog_recovery'):
        source=catalog['source']
        for event in catalog['header'].get('events',[]):
            participants=set()
            for name,cid in event.get('participants',{}).items():
                value=resolver._participant(cid,event,source) if cid else None
                if value:participants.add(value)
            raw.append(dict(identity=[source,event['id']],league=event.get('competition'),
                participants=participants,start=event.get('scheduled_start')))
    for row in rows:
        selected=row['lookup_keys'];roles=set(selected['roles'].values())-{None}
        candidates=[]
        for peer in raw:
            if peer['identity'][0]==row['identity'][0] or peer['league']!=selected['league']:continue
            if not roles.intersection(peer['participants']):continue
            key=tuple(peer['identity']);received=receipts[key];n=normalized.get(key)
            differences=[]
            if roles!=peer['participants']:differences.append('participants')
            if not peer['start'] or not selected['start']:differences.append('start_unknown')
            elif abs((stamp(peer['start'])-stamp(selected['start'])).total_seconds())>3600:differences.append('start')
            linked=next((p for p in row['compatible'] if p['identity']==peer['identity']),None)
            if differences:category='received_different_occurrence' if received else 'catalog_different_occurrence'
            elif not received:category='catalog_peer_without_retained_book'
            elif n and linked:category='normalized_compatible_peer' if linked['in_publication_lookup'] else 'normalized_peer_omitted_from_lookup'
            elif n:category='normalized_candidate_rejected'
            elif any(r['stage']=='parsed' and r['disposition']=='rejected' for r in received):category='received_parse_failed'
            elif any(r['stage']=='normalized' and r['disposition']=='rejected' for r in received):category='parsed_normalization_failed'
            elif any(r['primary_reason']=='replay_has_prices_current_sql_missing' for r in received):category='normalizable_peer_not_committed'
            else:category='received_peer_admission_pending_or_unclassified'
            candidates.append(dict(identity=peer['identity'],category=category,differing_fields=differences,
                received_books=len(received),receipt_causes=dict(Counter(r['primary_reason'] for r in received)),
                evidence_refs=[r['evidence_ref'] for r in received[:3]]))
        row['raw_peer_linkage']=dict(scope='current_retained_native_catalogs_and_receipts',
            candidates=candidates,counts=dict(Counter(p['category'] for p in candidates)),
            absence='no_identifiable_peer_in_retained_native_evidence' if not candidates else None,
            never_received='not_established_without_complete_receipt_history')
    return rows
