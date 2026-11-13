"""Coverage partitions preserve complete possible-peer components and one MVCC snapshot."""
from copy import deepcopy
from .board_capture import capture_batches
from app.comparison.broad_coverage import COUNT_KEYS,MAX_EXAMPLES,totals,ratios


def partitions(db,maximum_offers=2048,*,groups=None):
    sizes={r['event_id']:r['n'] for r in db.execute('SELECT c.event_id,count(*) n FROM current_contract c JOIN current_offer o ON o.contract_id=c.id GROUP BY c.event_id').fetchall()}
    groups=capture_batches(db) if groups is None else groups
    seen=set();packed=[];count=0
    for group in groups:
        if seen.intersection(group):
            # A non-disjoint planner cannot silently double-count coverage.
            raise ValueError('coverage_component_overlap')
        seen.update(group);size=sum(sizes.get(eid,0) for eid in group)
        if packed and count+size>maximum_offers:
            yield packed;packed=[];count=0
        packed.extend(group);count+=size
    if packed:yield packed
    if not groups:yield []


def merge(parts):
    out=None;cells={};aggregation={k:[] for k in ('outcomes','occurrences','inputs','publications')}
    for part in parts:
        if out is None:out={k:v for k,v in part.items() if k not in ('cells','aggregation')}
        for k in aggregation:aggregation[k].extend(part['aggregation'][k])
        for cell in part['cells']:
            key=cell['id']
            if key not in cells:cells[key]=deepcopy(cell);continue
            target=cells[key]
            for k in COUNT_KEYS:
                a,b=target['counts'][k],cell['counts'][k]
                target['counts'][k]=None if a is None or b is None else a+b
            target['examples']=(target['examples']+cell['examples'])[:MAX_EXAMPLES]
            reasons={r['code']:r for r in target['reasons']}
            for r in cell['reasons']:
                if r['code'] not in reasons:reasons[r['code']]=deepcopy(r)
                else:
                    saved=reasons[r['code']]
                    for k in ('count','primary_count'):saved[k]+=r[k]
                    saved['examples']=(saved['examples']+r['examples'])[:MAX_EXAMPLES]
            from app.comparison.broad_coverage import PRIMARY_ORDER
            target['reasons']=sorted(reasons.values(),key=lambda r:PRIMARY_ORDER.index(r['code']))
    values=sorted(cells.values(),key=lambda c:c['id'])
    for cell in values:cell['ratios']=ratios(cell['counts'],'captured cell retained observations')
    counts=totals(values,aggregation['outcomes'],aggregation['occurrences'],aggregation['inputs'],aggregation['publications'])
    out.update(cells=values,aggregation=aggregation,total_cells=len(values),filtered_cells=len(values),
        global_totals=counts,filtered_totals=deepcopy(counts),ratios=ratios(counts,'all captured retained observations'),
        filtered_ratios=ratios(counts,'all captured retained observations'))
    out['dimensions']['families']=sorted({c['family'] for c in values})
    out['dimensions']['periods']=sorted({c['period'] for c in values})
    return out
