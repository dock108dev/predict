"""Versioned compact excluded-catalog metadata; original wire evidence is authority."""
from .coverage import decode_page

POLICY='bounded-open-catalog-v4'


def compact(catalog, venue):
    # Excluded evidence must not occupy the bounded operating market table.
    # Column rows share page references; full source JSON remains in the journal.
    evidence=dict(version='excluded-catalog-1',source=venue,
        columns=['id','event_id','title','exclusion','page','occurrences'],pages=[],events=[],markets=[],side_counts={})
    repaired=any((m.get('v1_raw_binding') or {}).get('version')=='manual-comparison-2' for m in catalog['markets'])
    admitted=[]
    if repaired:
        from collections import defaultdict
        from .v1_coverage import PAIRED
        from app.dashboard.bounds import retained_bytes
        groups=defaultdict(list)
        # Embedded markets are packaging, explicitly excluded by the shared
        # native event semantic contract. Keep one copy in the hashed journal,
        # not a second expanded copy inside every operating event.
        for event in catalog['events']:
            native=event.get('_native',{})
            if 'markets' in native:
                event['embedded_market_packaging_reference']=dict(body_sha256=event['provenance'][-1]['body_sha256'],event_id=event['id'],path=event['provenance'][-1]['path'])
                event['_native']={k:v for k,v in native.items() if k!='markets'}
        for m in catalog['markets']:
            b=m.get('v1_raw_binding') or {};i=b.get('identity') or {}
            if b.get('status')=='BOUND_RAW_PREDICATE' and not m.get('exclusion'):
                cid='/'.join([i.get('competition','?'),i.get('period','?'),i.get('category') or i.get('family','?')])
                groups[cid].append(m)
                admitted.append(dict(id=m['id'],event_id=m['event_id'],cell_id=cid,binding_sha256=b['sha256'],native_metadata_sha256=b['native_metadata_sha256']))
        # One entrant/line per cell precedes second representatives. Whole
        # selected records stay intact; other complete records stay inspectable
        # through hashed raw-page references. This is selection, not rejection.
        order=[]
        keys=sorted(groups,key=lambda cid:(cid in PAIRED,cid))
        for index in range(max((len(v) for v in groups.values()),default=0)):
            for key in keys:
                if index<len(groups[key]):order.append(groups[key][index])
        for m in catalog['markets']:
            if (m.get('v1_raw_binding') or {}).get('status')!='BOUND_RAW_PREDICATE':m['exclusion']=m.get('exclusion') or 'identity_admission_blocked'
        order.sort(key=lambda m:not m.get('counterpart_priority',False))
        chosen=order[:64]
        chosen_ids={m['id'] for m in chosen}
        for m in catalog['markets']:
            if (m.get('v1_raw_binding') or {}).get('status')=='BOUND_RAW_PREDICATE' and m['id'] not in chosen_ids:
                m['exclusion']=m.get('exclusion') or 'admitted_metadata_not_selected'
        # Keep the unchanged source-resident ceiling binding. Remove complete
        # secondary candidates before any cell's first representative; no terms
        # are sliced to make a selected instrument appear to fit.
        import json
        # Journal/reopening may detach shared immutable strings. Account for
        # that ordinary representation, rather than relying on Python aliasing.
        def operating_bytes():
            return retained_bytes(json.loads(json.dumps(dict(events=catalog['events'],markets=chosen))))
        while chosen and operating_bytes()>2*1024*1024-256*1024:
            removed=chosen.pop();removed['exclusion']='admitted_metadata_not_selected'
        evidence.update(metadata_admissions=admitted,operating_market_limit=64,selection_policy='manual-comparison-2: missing-cell round robin within unchanged source resident bound')
    # An excluded/unresolved parent cannot leave an operating orphan market.
    operating_events={r['id'] for r in catalog['events'] if not r.get('exclusion') and r.get('identity')!='unresolved'}
    for row in catalog['markets']:
        if row.get('event_id') not in operating_events:
            row['exclusion']=row.get('exclusion') or 'unresolved_parent_event'
    refs={}
    for kind in ('events','markets'):
        kept=[]
        for row in catalog[kind]:
            if not row.get('exclusion') and row.get('identity')!='unresolved':
                kept.append(row);continue
            proof=row['provenance'][0];key=proof['body_sha256']
            if key not in refs:
                refs[key]=len(evidence['pages'])
                evidence['pages'].append(dict(response_sha256=key,path=proof['path'],received_at=proof['received_at']))
            evidence[kind].append([row['id'],row.get('event_id',row['id']),str(row.get('title') or '')[:160],
                row.get('exclusion') or 'unresolved_native_identity',refs[key],row.get('occurrences',1)])
            for side in row.get('sides',[]):
                k=side['purchase_support'];evidence['side_counts'][k]=evidence['side_counts'].get(k,0)+1
        catalog[kind]=kept
    catalog['excluded_catalog']=evidence
    return catalog


def references(catalog):
    evidence=catalog.get('excluded_catalog',{})
    for kind in ('events','markets'):
        for row in evidence.get(kind,[]):
            yield dict(version='catalog-metadata-reference-1',source=evidence['source'],
                response_sha256=evidence['pages'][row[4]]['response_sha256'],entity='event' if kind=='events' else 'market',
                id=row[0],event_id=row[1])


def resolve(pages, ref):
    """Inspectable original metadata, resolved only on demand from complete bytes."""
    matches=[]
    for p in pages:
        if p.get('source')!=ref['source'] or p.get('body_sha256')!=ref['response_sha256'] or p.get('complete') is not True or p.get('status')!=200:continue
        _,data=decode_page(p)
        key='id' if ref['source']=='polymarket_us' else 'event_ticker' if ref['entity']=='event' else 'ticker'
        if ref['entity']=='event':candidates=data.get('events',[])
        elif 'markets' in data:candidates=data['markets']
        else:candidates=[m for e in data.get('events',[]) if str(e.get('id'))==ref['event_id'] for m in (e.get('markets') or [])]
        matches.extend(x for x in candidates if isinstance(x,dict) and str(x.get(key))==ref['id'])
    if len(matches)!=1:raise ValueError('Source metadata missing or ambiguous; no inferred reconstruction')
    return matches[0]
