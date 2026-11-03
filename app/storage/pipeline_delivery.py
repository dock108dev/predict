"""Prospective allowlisted witnesses from the exact calculation snapshot."""
from .store import hashed


def witness(frame, dependencies, captured_at, capture_finished_at):
    ids = sorted(set(dependencies.get('observations',{})) | set(dependencies.get('metric_identities',{})))
    rows = [frame['offers'][cid] for cid in ids if cid in frame['offers']]
    receipts = [r['received_at'] for r in rows if r.get('received_at')]
    return dict(captured_at=captured_at,capture_finished_at=capture_finished_at,
        receipt_oldest_at=min(receipts) if receipts else None,receipt_newest_at=max(receipts) if receipts else None,
        dependency_count=len(ids),dependency_digest=hashed(dependencies),
        witnesses=[dict(id=r['id'],event=r['event_id'],price=r.get('price_value'),units=r.get('price_units'),
            source_at=r.get('source_at'),received_at=r.get('received_at'),
            contract=r.get('contract_dependency'),offer=r['offer_revision'],scoring=r.get('scoring_dependency')) for r in rows[:8]],
        witness_limit=8,witness_scope='first_sorted_dependencies_not_complete_materiality')


def difference(previous, current):
    before={r['id']:r for r in previous.get('witnesses',[])}
    changes=[]
    for row in current.get('witnesses',[]):
        old=before.get(row['id'])
        if old is None:continue
        fields={k:dict(before=old.get(k),after=v) for k,v in row.items() if old.get(k)!=v}
        if fields:changes.append(dict(id=row['id'],fields=fields,
            classification='receipt_only' if set(fields)=={'received_at'} else 'dependency_change'))
    return changes


def validation_witness(before, after, dependencies, checks):
    """Bounded exact mismatches selected from failing dependencies, not quiet IDs."""
    from . import observation_publication as p
    failed=sorted({cid for section in ('observations','comparisons','benchmark_identity','benchmarks')
        for cid,reasons in checks.get(section,{}).items() if reasons})
    def fields(frame,cid):
        row=frame['offers'].get(cid)
        if row is None:return None
        book=frame.get('books',{}).get((row['venue'],row['event_id'],row['native_market_id']))
        return dict(event=row['event_id'],price=row.get('price_value'),units=row.get('price_units'),
            source_at=row.get('source_at'),received_at=row.get('received_at'),
            offer=row['offer_revision'],contract=row.get('contract_dependency'),metric=row.get('metric_dependency'),
            scoring=row.get('scoring_dependency'),book=None if book is None else book['revision'],
            depth=None if book is None else book.get('depth_revision'),
            book_state=None if book is None else book.get('state'),
            book_sync=None if book is None else book.get('sync'),
            book_source_at=None if book is None else book.get('source_at'),
            health=p.health(frame['states'].get(row['venue'],{})))
    def peers(frame,cid):
        selected=dependencies['selections'].get(cid)
        if selected is None:return {}
        ids={r[0] for r in p.neighborhood(frame,dependencies['selector'])}
        return {r['id']:dict(contract=r.get('contract_dependency',r['contract_revision']),scoring=r.get('scoring_dependency'),
            own=p.own(frame,r['id']) if r['id'] in dependencies.get('eligible',{}).get(cid,[]) else None)
            for eid in ids for r in frame['by_event'].get(eid,[])
            if r['venue'] not in ('pinnacle',selected['venue']) and p._same_candidate(p.selection(frame,r),selected)}
    def peer_changes(cid):
        a,b=peers(before,cid),peers(after,cid)
        return [dict(id=rid,before=a.get(rid),after=b.get(rid)) for rid in sorted(a.keys()|b.keys()) if a.get(rid)!=b.get(rid)][:4]
    return dict(common=checks['all'],counts={section:sum(bool(r) for r in checks.get(section,{}).values())
        for section in ('observations','comparisons','benchmark_identity','benchmarks')},
        matching_before=dependencies['matching'],matching_after=p.hashed(p.neighborhood(after,dependencies['selector'])),
        mismatches=[dict(id=cid,before=fields(before,cid),after=fields(after,cid),peer_changes=peer_changes(cid),
            candidate_saved=dependencies.get('candidates',{}).get(cid),
            candidate_before=p.candidates(before,dependencies['selector'],dependencies['selections'][cid],dependencies.get('eligible',{}).get(cid,[])) if cid in dependencies['selections'] else None,
            candidate_after=p.candidates(after,dependencies['selector'],dependencies['selections'][cid],dependencies.get('eligible',{}).get(cid,[])) if cid in dependencies['selections'] else None) for cid in failed[:4]],
        omitted=max(0,len(failed)-4))
