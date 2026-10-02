"""Offline per-requirement accounting from an exact saved session; never dispatch."""
import argparse,json,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from app.dashboard.session_history import verified,load
from app.dashboard.price_comparison import comparisons
from app.collection.native_approval import digest
from app.collection.source_session import verify_rows
from app.collection.v1_coverage import PAIRED
from app.collection.source_bindings import required_cells

def cell(identity):return '/'.join(str(identity.get(k)) for k in ('competition','period'))+'/'+str(identity.get('category') or identity.get('family'))
def report(folder):
    folder=Path(folder);rows=list(verified(folder)['rows']);snapshot=load(folder)
    evidence=verify_rows(rows);prices=defaultdict(list);metadata=defaultdict(list);locators=defaultdict(list);dispositions={}
    seen_prices=defaultdict(set);receipts=defaultdict(set);pairs=defaultdict(list)
    for row in rows:
        if row['type'] in ('native_scope_discovery','v1_link_discovery'):
            for cid,value in row.get('cells',{}).items():dispositions.setdefault(cid,{})[row['source']]=value
        if row['type'] in ('aggregate_snapshot','aggregate_award_snapshot'):
            for r in row['records']:
                cid=cell(r['identity']);raw=r['original'];key=(raw['bookmaker'],raw['source_event_id'],raw['market'],raw['outcome'],raw['point'])
                prices[cid].append(dict(source=raw['bookmaker'],price=raw['decimal_odds'],received_at=raw['received_at'],source_at=raw.get('source_at'),identity_bound=not r['reasons']))
                if not r['reasons']:metadata[cid].append(r['id'])
                seen_prices[(cid,key)].add(raw['decimal_odds']);receipts[(cid,key)].add(raw['receipt_sha256'])
    for row in comparisons(snapshot,{}):
        if row.get('raw_difference') is not None and len({l['venue'] for l in row['legs']})>=2:pairs[cell(row['identity'])].append(row['id'])
    targets=[]
    for c in required_cells():
        cid=c['cell_id'];targets.append(dict(cell_id=cid,baseline_pair=cid in PAIRED,
            locator_discovery=dispositions.get(cid,{}),complete_identity_metadata_records=len(set(metadata[cid])),
            aggregate_actual_price_observations=len(prices[cid]),valid_comparable_pairs_at_cutoff=len(pairs[cid]),
            repeated_receipts=sum(max(0,len(v)-1) for (k,_),v in receipts.items() if k==cid),
            changed_price_observations=sum(max(0,len(v)-1) for (k,_),v in seen_prices.items() if k==cid),
            disposition='valid_pair' if pairs[cid] else 'prices_identity_or_counterpart_missing' if prices[cid] else 'locator_or_metadata_only' if dispositions.get(cid) else 'unreached',
            not_closed_reason=None if pairs[cid] else 'No valid pair at exact selected saved cutoff; no claim of provider non-support'))
    return dict(classification='Exact saved cutoff, offline analysis; no new source observation',session=snapshot['session_id'],cutoff=snapshot['durable_cursor'],
        snapshot_sha256=digest(snapshot),raw_replay=evidence,targets=targets,requirements=63,
        missing_baseline_requirements_with_pairs_at_cutoff=sum(not t['baseline_pair'] and bool(t['valid_comparable_pairs_at_cutoff']) for t in targets),
        limitations=['Native quote admission is represented in comparisons; aggregate price counts are separate','Repeated receipts do not establish newly published prices or source clocks','Empty, capped, unsupported predicates and unreached dependencies remain in locator_discovery dispositions','A valid pair somewhere suffices; all-four venue coverage is not required; no claim of all 48 closures'])
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder');a=p.parse_args();print(json.dumps(report(a.folder),indent=2))
