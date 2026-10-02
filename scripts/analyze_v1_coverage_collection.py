#!/usr/bin/env python3
"""Versioned local accounting of the single completed capture. No acquisition."""
import json,sys,hashlib
from pathlib import Path
from collections import Counter,defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.dashboard.session_history import verified,load
from app.reference.aggregate import augment
from app.dashboard.session_projection import stable
from app.collection.source_bindings import SOURCES
OUT=ROOT/'evidence/v1-coverage-integration-713fd0fa-v1'
LIVE=ROOT/'evidence/LIVE-v1-coverage-713fd0fa-73ae-4beb-b446-3c7925eca6e5'
SESSION=LIVE/'9eae4ce9-6fd1-4e9c-8068-3c6debfaaf1c'
def cell(i):return '/'.join([i['competition'],i['period'],i.get('category') or i['family']])
def main():
 baseline=json.loads((ROOT/'evidence/v1-coverage-comparison-20261001-v1/coverage-63.json').read_text());rows=list(verified(SESSION)['rows']);snapshot=load(SESSION)
 from app.collection.coverage import catalog,stamp
 from app.collection.v1_comparison import annotate
 pages=[r for r in rows if r['type']=='prediction_discovery_http' and (r['path'].endswith('/events') or r['path'].endswith('/markets') or '/events/' in r['path'] or '/market/' in r['path'] or r['path'].endswith('/milestones'))]
 interpreted=[{k:v for k,v in r.items() if k!='acquisition_discovery_policy'} for r in pages]
 for venue in SOURCES[:2]:
  compact=catalog(pages,venue,stamp(rows[-1]['observed_at']))
  (OUT/(venue+'-compact-catalog-v1.json')).write_text(json.dumps(compact,indent=2)+'\n')
  full=catalog(interpreted,venue,stamp(rows[-1]['observed_at']));annotate(full,venue,rows[0]['spec'].get('native_review_records',[]))
  (OUT/(venue+'-derived-catalog.json')).write_text(json.dumps(full,indent=2)+'\n')

 prices=defaultdict(list);refs=defaultdict(list);metadata=defaultdict(list);pairs=defaultdict(list);allrecords=[];dispositions=defaultdict(dict);disposition_history=defaultdict(list);receiptsets=defaultdict(set);valuesets=defaultdict(set)
 for row in rows:
  if row['type'] in ('v1_link_discovery','native_scope_discovery'):
   for cid,d in row.get('cells',{}).items():
    disposition_history[(cid,row['source'])].append(dict(observed_at=row['observed_at'],type=row['type'],disposition=d))
    previous=dispositions[cid].get(row['source'])
    if d.get('state')!='prior_generation_query_retained' or not previous:dispositions[cid][row['source']]=d
  if row['type'] in ('aggregate_snapshot','aggregate_award_snapshot'):
   response_projection=dict(session_id=snapshot['session_id'],durable_cursor=row['ingress_id'],market_catalog=[],references=[],games=[],points={},rows_by_game={},sources=[])
   augment(response_projection,row['records'])
   for p in response_projection['aggregate_comparisons']:
    if p['raw_difference'] is not None:pairs[cell(p['identity'])].append(dict(row_id=p['id'],sources=sorted(l['venue'] for l in p['legs']),cutoff=row['ingress_id'],received_at=row['observed_at'],evidence_class='one_complete_retained_response',identity=p['identity'],timing=p['timing']))
   for a in row['records']:
    cid=cell(a['identity']);r=a['original'];venue=r['bookmaker'];entry=dict(record_id=a['id'],source=venue,price=r['decimal_odds'],source_at=r.get('source_at'),received_at=r['received_at'],reasons=a['reasons'],identity=a['identity'],body_sha256=r['receipt_sha256'])
    (prices if venue in SOURCES else refs)[(cid,venue)].append(entry);allrecords.append(a)
    key=(cid,venue,r['source_event_id'],r['market'],r['outcome'],r['point']);receiptsets[key].add((r['received_at'],r['receipt_sha256']));valuesets[key].add(r['decimal_odds'])
 for venue in SOURCES[:2]:
  cat=json.loads((OUT/(venue+'-derived-catalog.json')).read_text())
  for m in cat['markets']:
   b=m.get('v1_raw_binding') or {};i=b.get('identity');scope=m.get('native_scope_binding') or {}
   cid=cell(i) if i and i.get('competition') else '/'.join([scope.get('sport','?'),scope.get('period','?'),scope.get('category') or scope.get('family','?')])
   metadata[(cid,venue)].append(dict(market_id=m['id'],event_id=m['event_id'],binding=b,exclusion=m.get('exclusion'),provenance=m.get('provenance')))
 native_quotes=[]
 for row in rows:
  if row['type']!='prediction_book':continue
  ref=row['book']['raw']['ref'];venue=row['source'];cat=json.loads((OUT/(venue+'-derived-catalog.json')).read_text())
  m=next((m for m in cat['markets'] if m['id']==ref['market_id']),None)
  if not m:continue
  b=m.get('v1_raw_binding') or {};i=b.get('identity')
  if not i or not i.get('competition'):continue
  cid=cell(i);entry=dict(record_id=row['ingress_id'],source=venue,price=None,received_at=row['observed_at'],source_at=None,reasons=b['blockers'],identity=i,book=row['book'],classification='Actual retained native depth image; identity blocked is not pair admission')
  prices[(cid,venue)].append(entry);native_quotes.append(entry)
 (OUT/'native-price-records.json').write_text(json.dumps(native_quotes,indent=2)+'\n')
 cells=[];source_records=[]
 for old in baseline['cells']:
  cid=old['cell_id'];newpairs=pairs[cid];paired={s for p in newpairs for s in p['sources']};sources={};why=[]
  for v,prev in old['sources'].items():
   actual=prices[(cid,v)];meta=metadata[(cid,v)];dis=dispositions[cid].get(v,{})
   reasons=[]
   if v in paired:reasons=['Retained raw pair; freshness and unknown economics independently gated']
   else:
    reasons+=sorted({r for a in actual for r in a['reasons']})
    reasons+=sorted({r for m in meta for r in m['binding'].get('blockers',[])})
    if actual:reasons.append('No exact eligible same-outcome, same-line counterpart pair in the complete response')
    elif meta:reasons.append('Metadata retained without two independently received eligible native quote legs')
    elif dis:reasons.append('Native discovery disposition: '+str(dis.get('state')))
    else:reasons.append('No actual comparison-source observation in this capture')
    reasons+=prev['exact_remaining_locator_or_identity_blocker'] if not prev['valid_comparable_pair'] else ['Historical pair remains dated; this capture supplies no new valid pair']
   sources[v]=dict(prior_observed=prev['actual_retained_observations'],prior_paired=prev['valid_comparable_pair'],new_metadata_records=len(meta),new_price_records=len(actual),new_identity_bound_price_records=sum(not a['reasons'] for a in actual),new_valid_pair=v in paired,
    retained_observed=prev['actual_retained_observations'] or bool(actual or meta),retained_paired=prev['valid_comparable_pair'] or v in paired,discovery_disposition=dis,discovery_history=disposition_history[(cid,v)],blockers=list(dict.fromkeys(reasons)),metadata=meta,price_records=actual)
   source_records.append(dict(cell_id=cid,source=v,**sources[v]))
   if v not in paired:why.append(v+': '+'; '.join(sources[v]['blockers']))
  union_pair=bool(old['comparable_sources'] or paired);newprice=sum(len(prices[(cid,v)]) for v in SOURCES);newmeta=sum(len(metadata[(cid,v)]) for v in SOURCES)
  cells.append(dict(cell_id=cid,sources=sources,prior_observed=bool(old['observed_sources']),prior_paired=bool(old['comparable_sources']),retained_observed=any(s['retained_observed'] for s in sources.values()),retained_paired=union_pair,new_valid_pair=bool(paired),pair_evidence=newpairs,new_metadata_records=newmeta,new_actual_comparison_price_records=newprice,new_reference_only_price_records=sum(len(a) for (c,v),a in refs.items() if c==cid),
   repeated_receipts=sum(max(0,len(v)-1) for (c,*_),v in receiptsets.items() if c==cid),changed_prices=sum(max(0,len(v)-1) for (c,*_),v in valuesets.items() if c==cid),remaining_requirement_reason=None if union_pair else why))
 summary=dict(before={'observed_requirements':25,'paired_requirements':15,'observed_source_support':53,'paired_source_support':34},after=dict(observed_requirements=sum(c['retained_observed'] for c in cells),paired_requirements=sum(c['retained_paired'] for c in cells),observed_source_support=sum(c['retained_observed'] for c in source_records),paired_source_support=sum(c['retained_paired'] for c in source_records)),
  this_capture=dict(native_price_images=len(native_quotes),requirements_with_metadata=sum(bool(c['new_metadata_records']) for c in cells),requirements_with_comparison_prices=sum(bool(c['new_actual_comparison_price_records']) for c in cells),requirements_with_reference_only_prices=sum(bool(c['new_reference_only_price_records']) for c in cells),requirements_with_valid_pairs=sum(c['new_valid_pair'] for c in cells),newly_closed_pairs=sum(c['new_valid_pair'] and not c['prior_paired'] for c in cells),repeat_receipts=sum(c['repeated_receipts'] for c in cells),changed_prices=sum(c['changed_prices'] for c in cells)),update_stages_by_source={v:dict(repeated_receipts=sum(max(0,len(a)-1) for (c,b,*_),a in receiptsets.items() if b==v),changed_prices=sum(max(0,len(a)-1) for (c,b,*_),a in valuesets.items() if b==v),role='comparison' if v in SOURCES else 'reference_only') for v in list(SOURCES)+['pinnacle','draftkings','betmgm']},by_source={v:dict(observed=sum(c['sources'][v]['retained_observed'] for c in cells),paired=sum(c['sources'][v]['retained_paired'] for c in cells)) for v in SOURCES})
 result=dict(version='v1-post-collection-integration-2',original_modified=False,session=snapshot['session_id'],snapshot_sha256=stable(snapshot),summary=summary,cells=cells,limitations=['Retained historical union is not current live availability','Reference-only books do not count as comparison-source support','Metadata and unbound prices do not create pairs','No exact season inferred from outright kickoff','No live authority from this local derivation'])
 for name,data in [('coverage-63.json',result),('source-support-252.json',source_records),('bound-aggregate-records.json',allrecords)]: (OUT/name).write_text(json.dumps(data,indent=2)+'\n')
 print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
