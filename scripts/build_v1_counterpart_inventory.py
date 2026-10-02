"""Read-only retained derivation; no transports, credentials or approval writes."""
import json,sys
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.collection.counterparts import inventory
from app.dashboard.session_projection import stable
OLD=ROOT/'evidence/v1-admission-delivery-repair-20261001-v1'
OUT=ROOT/'evidence/v1-counterpart-completion-20261001-v1'
def build():
 cats={v:json.loads((OLD/(v+'-repaired-catalog.json')).read_text()) for v in ('kalshi','polymarket_us')}
 accounting=json.loads((OLD/'record-accounting.json').read_text());assert sum(r['metadata_admitted'] for r in accounting)==521
 pairs=inventory(cats);at=datetime.now(timezone.utc)
 for p in pairs:
  p.update(historical_start=p['identity']['scheduled_start'],expired_at_preparation=datetime.fromisoformat(p['identity']['scheduled_start'].replace('Z','+00:00'))<=at,
   remaining_checks=['Fresh discovery must bind exact identity and literal predicate','Active/open/unhidden/unarchived and five-minute schedule margin','Both independent initial synchronized books in this session','Independent updates, connection state, 15-second quote receipt/source age','Material identity changes invalidate prior books'],
   missing_identity_facts=[],only_fresh_books_missing_in_retained_identity=True,current_selection=False)
 awards=[]
 for v,c in cats.items():
  for m in c['markets']:
   b=m.get('v1_raw_binding',{});i=b.get('identity') or {}
   if b.get('status')=='BOUND_RAW_PREDICATE' and i.get('family')=='futures':awards.append(dict(source=v,event_id=m['event_id'],market_id=m['id'],identity=i,predicate=b['predicate'],provenance=m['provenance'],counterpart='not evidenced',remaining=['Exact other-venue season/category/conference/entrant/predicate association','Fresh eligibility/deadline and independently synchronized books']))
 coverage=json.loads((OLD/'coverage-63.json').read_text());targets=[]
 for c in coverage['cells']:
  cid=c['cell_id'];matches=[p for p in pairs if p['cell_id']==cid];records=[r for r in accounting if r.get('identity') and '/'.join([r['identity']['competition'],r['identity']['period'],r['identity'].get('category') or r['identity']['family']])==cid]
  paired=cid in __import__('app.collection.v1_coverage',fromlist=['PAIRED']).PAIRED
  sources=c['sources'];unknown=any('locator' in str(v).lower() and ('unestablished' in str(v).lower() or 'unresolved' in str(v).lower()) for v in sources.values())
  metadata=sum(v.get('new_metadata_records',0) for v in sources.values())
  disposition='ready_for_fresh_paired_books_after_current_refresh' if matches else 'missing_counterpart_identity' if records or metadata else 'unknown_locator' if unknown else 'offering_unavailable_in_retained_observations'
  hypothesis=None
  if cid in ('NFL/first_half/spread','NFL/first_half/total','NCAAF/first_half/spread','NCAAF/first_half/total'):
   hypothesis='Refresh documented native first-half series and US exact event detail; compare literal common lines; aggregate H1 spread/total only can supply absent same-event comparison leg or establish bounded offering/line mismatch'
  targets.append(dict(cell_id=cid,retained_paired=paired,disposition=disposition,exact_native_predicate_candidates=[p['id'] for p in matches],actionable_missing_requirement=bool(matches) and not paired,current_selection=False,retained_admitted_records=len(records),source_dependencies={v:{k:r[k] for k in ('discovery_disposition','blockers','retained_observed','retained_paired','new_metadata_records','new_price_records') if k in r} for v,r in sources.items()},discovery_hypothesis=hypothesis,requests_without_hypothesis=0))
 result=dict(version='exact-counterpart-inventory-1',prepared_at=at.isoformat(),admitted_records=521,retained_inputs={n:stable(json.loads((OLD/n).read_text())) for n in ('record-accounting.json','kalshi-repaired-catalog.json','polymarket_us-repaired-catalog.json','coverage-63.json')},pairs=pairs,awards=awards,targets=targets,
  summary=dict(predicate_groups=len(pairs),candidate_cells=dict(Counter(p['cell_id'] for p in pairs)),exact_award_cross_venue_pairs=0,actionable_missing_requirements=[t['cell_id'] for t in targets if t['actionable_missing_requirement']],untargetable_missing_requirements=[t['cell_id'] for t in targets if not t['retained_paired'] and not t['actionable_missing_requirement']],paired_coverage_before=15,paired_coverage_after=15),collection_authorized=False)
 OUT.mkdir(exist_ok=True);(OUT/'counterpart-inventory.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['summary'],indent=2))
 return result
if __name__=='__main__':build()
