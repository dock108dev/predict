#!/usr/bin/env python3
"""Versioned coverage accounting; no acquisition or invented quotes."""
import json,sys
from pathlib import Path
from collections import Counter,defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.repair_v1_retained_admission import OUT,OLD,SESSION
from app.dashboard.session_history import verified
from app.dashboard.session_projection import stable
from app.collection.source_bindings import SOURCES

def main():
 result=json.loads((OLD/'coverage-63.json').read_text());result['version']='v1-admission-delivery-repair-2';result['original_modified']=False
 accounts=json.loads((OUT/'record-accounting.json').read_text());bycell=defaultdict(list);indications=[]
 for venue in ('kalshi','polymarket_us'):
  cat=json.loads((OUT/(venue+'-repaired-catalog.json')).read_text());events={e['id']:e for e in cat['events']}
  for m in cat['markets']:
   b=m.get('v1_raw_binding',{});i=b.get('identity') or {};scope=m.get('native_scope_binding',{});locator=b.get('locator',{})
   if scope or locator.get('status')=='DOCUMENTED_LOCATOR':
    cid='/'.join([scope.get('sport',i.get('competition','?')),scope.get('period',i.get('period','?')),scope.get('category') or scope.get('family') or i.get('family','?')]);bycell[(cid,venue)].append(dict(market_id=m['id'],metadata_admitted=b.get('status')=='BOUND_RAW_PREDICATE',blockers=b.get('blockers',[]),exclusion=m.get('exclusion'),identity=i,provenance=m['provenance']))
   native=m['_native'];fields={k:native[k] for k in ('yes_bid_dollars','yes_ask_dollars','no_bid_dollars','no_ask_dollars','bestBidQuote','bestAskQuote','outcomePrices') if k in native}
   if fields:indications.append(dict(source=venue,market_id=m['id'],metadata_admitted=b.get('status')=='BOUND_RAW_PREDICATE',indications=fields,received_at=m['provenance'][-1]['received_at'],body_sha256=m['provenance'][-1]['body_sha256'],classification='Actual embedded price indications, not synchronized selected-book images',comparison_eligible=False,reason='Ordinary native adapter requires independent selected-book state; metadata modification time is not a price timestamp'))
 source_records=[]
 for c in result['cells']:
  for venue,s in c['sources'].items():
   meta=bycell[(c['cell_id'],venue)];s['repaired_metadata']=meta;s['repaired_metadata_admissions']=sum(m['metadata_admitted'] for m in meta);s['repaired_metadata_records']=len(meta)
   if meta:s['retained_observed']=True
   # Remove erroneous inherited game-only award diagnostics and disconnected
   # facts; retained pairs and actual price records are never regenerated.
   if meta and not s['new_valid_pair']:
    s['blockers']=sorted({b for m in meta for b in m['blockers']})
    s['blockers'].append('No independently received eligible same-event/same-award counterpart book pair in this capture')
   source_records.append(dict(cell_id=c['cell_id'],source=venue,**s))
  c['retained_observed']=any(s['retained_observed'] for s in c['sources'].values())
  c['repaired_metadata_admissions']=sum(s['repaired_metadata_admissions'] for s in c['sources'].values())
  c['remaining_requirement_reason']=None if c['retained_paired'] else [v+': '+'; '.join(s['blockers']) for v,s in c['sources'].items()]
 after=dict(observed_requirements=sum(c['retained_observed'] for c in result['cells']),paired_requirements=sum(c['retained_paired'] for c in result['cells']),observed_source_support=sum(s['retained_observed'] for s in source_records),paired_source_support=sum(s['retained_paired'] for s in source_records))
 result['summary']['after']=after;result['summary']['by_source']={v:dict(observed=sum(s['source']==v and s['retained_observed'] for s in source_records),paired=sum(s['source']==v and s['retained_paired'] for s in source_records)) for v in SOURCES}
 result['summary']['repair']=dict(metadata_admitted=sum(r['metadata_admitted'] for r in accounts),original_570_admitted=sum(r['metadata_admitted'] for r in accounts if r['cohort']=='original_570'),recovered_detail_new_records=sum(r['cohort']=='recovered_complete_US_detail' for r in accounts),embedded_price_indications=len(indications),new_price_pairs=0,requirements_still_open=48)
 for name,d in [('coverage-63.json',result),('source-support-252.json',source_records),('embedded-price-indications.json',indications),('coverage-summary.json',result['summary'])]:(OUT/name).write_text(json.dumps(d,indent=2)+'\n')
 print(json.dumps(result['summary'],indent=2))
if __name__=='__main__':main()
