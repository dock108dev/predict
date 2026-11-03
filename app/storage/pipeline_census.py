"""Read-only native receipt census using the actual normalization owner.

Run inside the caller's repeatable-read transaction. Each current received book
has exactly one primary disposition. Missing history remains unknown; observation
age must never be described as queue waiting age without a recorded transition.
"""
from collections import Counter, defaultdict
from types import SimpleNamespace
from .store import stamp, hashed
from app.collection.current_sink import normalized_records


def native_receipts(db, at, end, normalized):
    headers={r['source']:r['header'] for r in db.execute('SELECT source,header FROM current_native_catalog_recovery')}
    # Recovery metadata precedes normal catalog enrichment. Replay that actual
    # owning stage too; otherwise repaired roles masquerade as current failures.
    catalogs={source:dict(header,markets=[]) for source,header in headers.items()}
    for row in db.execute('SELECT source,metadata FROM current_native_market_recovery'):
        if row['source'] in catalogs:catalogs[row['source']]['markets'].append(row['metadata'])
    if catalogs:
        from app.collection.current_service import prepare_catalog
        source='kalshi' if 'kalshi' in catalogs else next(iter(catalogs))
        catalogs=prepare_catalog(catalogs,source,catalogs[source],share_metadata=True)
    prepared={(source,m['event_id'],m['id']):m for source,h in catalogs.items() for m in h['markets']}
    events={(source,e['id']):e for source,h in catalogs.items() for e in h.get('events',[])}
    markets=defaultdict(list)
    for key in normalized:markets[key[:3]].append(key)
    rows=[];counts=Counter()
    with db.cursor(name='pipeline_native_receipts') as cur:
        cur.itersize=64
        cur.execute('''SELECT i.source,i.event_id,i.market_id,i.received_at,i.disposition,
            i.image,r.metadata,r.parsed IS NOT NULL parsed
            FROM current_acquisition_image i LEFT JOIN current_native_market_recovery r
            ON r.source=i.source AND r.market_id=i.market_id
            ORDER BY i.source,i.event_id,i.market_id''')
        for r in cur:
            key=(r['source'],r['event_id'],r['market_id']);event=events.get(key[:2]);m=prepared.get(key,r['metadata']);book=r['image']
            start=(event or {}).get('scheduled_start');within=None if not start else at<=stamp(start)<end
            base=dict(unit='native_book',source=r['source'],event_id=r['event_id'],market_id=r['market_id'],
                revision=hashed([book.get('sequence'),book.get('raw',{}).get('received_at'),book.get('outcomes')]),
                league=(event or {}).get('competition','unknown'),family=(m or {}).get('market_type','unknown'),
                window='unknown_schedule' if within is None else 'next_72_hours' if within else 'outside_window',
                received_at=r['received_at'].isoformat(),receipt_age_seconds=max(0,(at-r['received_at']).total_seconds()),
                first_observed_at=None,attempts=None,retries=None,waiting_age_seconds=None,
                evidence_ref=dict(table='current_acquisition_image',key=list(key)),
                normalization_evidence_ref=dict(table='current_native_market_recovery',key=[key[0],key[2]]),
                receipt_disposition=r['disposition'],children=[list(k) for k in markets.get(key,[])],
                owner='app.collection.current_sink.normalized_records',secondary_reasons=[])
            if within is False:stage,state,reason='received','intentionally_excluded','outside_72_hour_window'
            elif markets.get(key):stage,state,reason='normalized','passed','normalized_children_present'
            elif not event or not m:stage,state,reason='parsed','waiting','retained_event_missing' if not event else 'retained_market_missing'
            elif not r['parsed']:stage,state,reason='parsed','rejected','native_market_parse_not_retained'
            elif not m.get('v1_raw_binding'):stage,state,reason='normalized','waiting','native_binding_absent'
            else:
                projection=SimpleNamespace(inventory={key[0]:dict(events=[event],markets=[m])},
                    books={key:dict(book=book)},invalid=set())
                records,errors=normalized_records(projection,{key[0]:dict(state='available')},{},
                    dated_annotations=False,clock=at.isoformat(),include_missing=True)
                priced=[v for v in records if not v.get('offer_missing')]
                if errors:
                    detail=errors[0];stage,state,reason='normalized','rejected',detail['reason_code']
                    base['normalization']=detail;base['secondary_reasons']=detail['binding_blockers']
                elif priced:
                    stage,state,reason='normalized','waiting','replay_has_prices_current_sql_missing'
                    base['replay_children']=[v['quote']['source'] for v in priced]
                elif book.get('sync')!='synchronized' or book.get('state')!='active':
                    stage,state,reason='parsed','waiting','book_not_synchronized_active'
                elif records:stage,state,reason='normalized','intentionally_excluded','typed_outcomes_have_no_purchase_price'
                else:stage,state,reason='normalized','unknown','normalizer_returned_no_rows_or_refusal'
            base.update(stage=stage,disposition=state,primary_reason=reason,
                next_action={'passed':'Trace normalized children through branch publication',
                    'rejected':'Repair demonstrated source facts or normalization rule; replay this same identity',
                    'waiting':'Inspect admission generation and retained source evidence',
                    'intentionally_excluded':'Retain evidence; no fabricated price or date',
                    'unknown':'Instrument unclassified owning branch'}[state])
            rows.append(base);counts['|'.join((base['source'],base['league'],base['family'],base['window'],stage,state,reason))]+=1
    return dict(unit='native_book',total=len(rows),primary_counts=dict(sorted(counts.items())),records=rows,
        reconciled=sum(counts.values())==len(rows),
        history='Current retained revisions only; first observation/attempts/waiting ages unavailable until recorded by owner')
