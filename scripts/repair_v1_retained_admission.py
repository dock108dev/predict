#!/usr/bin/env python3
"""Offline derivation only. Complete retained bytes, ordinary catalog and replay."""
import base64,json,sys,tracemalloc
from copy import deepcopy
from pathlib import Path
from collections import Counter
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.dashboard.session_history import verified,load,project_rows
from app.dashboard.session_projection import stable
from app.collection.coverage import catalog,stamp
from app.collection.native_payload import parse,validate_envelope
from app.collection.transport_session import ObservationJournal
OUT=ROOT/'evidence/v1-admission-delivery-repair-20261001-v1'
OLD=ROOT/'evidence/v1-coverage-integration-713fd0fa-v1'
SESSION=ROOT/'evidence/LIVE-v1-coverage-713fd0fa-73ae-4beb-b446-3c7925eca6e5/9eae4ce9-6fd1-4e9c-8068-3c6debfaaf1c'
SID='offline-v1-repair-713fd0fa-20261001'
def derive_page(row):
 p=deepcopy(row);p.update(v1_comparison_policy='manual-comparison-2',native_binding_revision='live-native-binding-2')
 if p.get('complete') is True and p.get('delivery_reason')=='native_parse_expansion_cap':
  raw=base64.b64decode(p['body_b64']);assert sha256(raw).hexdigest()==p['body_sha256'];metrics={}
  tracemalloc.start();data=parse(raw,limits=p['transport_policy'],metrics=metrics,revised=True);current,peak=tracemalloc.get_traced_memory();tracemalloc.stop();validate_envelope(data,p['path'])
  metrics.update(actual_live_allocation_bytes=current,actual_peak_allocation_bytes=peak,body_sha256=p['body_sha256'],complete=True,path=p['path'],original_disposition=p['delivery_reason'],offline_recovery=True)
  (OUT/'parser-after.json').write_text(json.dumps(metrics,indent=2)+'\n')
  p.update(usable_metadata=True,delivery_reason=None,offline_original_delivery_reason='native_parse_expansion_cap',offline_parse_metrics=metrics)
 return p

def main():
 rows=list(verified(SESSION)['rows']);pages=[derive_page(r) for r in rows if r['type']=='prediction_discovery_http' and (r['path'].endswith('/events') or r['path'].endswith('/markets') or '/events/' in r['path'] or '/market/' in r['path'] or r['path'].endswith('/milestones'))]
 fullpages=[{k:v for k,v in p.items() if k!='acquisition_discovery_policy'} for p in pages]
 cats={v:catalog(fullpages,v,stamp(rows[0]['observed_at']),v1_templates=rows[0]['spec'].get('native_review_records',[])) for v in ('kalshi','polymarket_us')}
 accounting=[]
 for v,c in cats.items():
  (OUT/(v+'-repaired-catalog.json')).write_text(json.dumps(c,indent=2)+'\n')
  before={m['id']:m for m in json.loads((OLD/(v+'-derived-catalog.json')).read_text())['markets']}
  events={e['id']:e for e in c['events']}
  for m in c['markets']:
   b=m.get('v1_raw_binding',{});reasons=b.get('blockers',[]);e=events[m['event_id']];prior=before.get(m['id'],{}).get('v1_raw_binding',{});admitted=b.get('status')=='BOUND_RAW_PREDICATE'
   if admitted:category='already_admitted' if prior.get('status')=='BOUND_RAW_PREDICATE' else 'newly_admitted'
   elif any('Conflicting'in r or 'conflicts'in r for r in reasons) or m.get('exclusion')=='market_parse_error':category='malformed_or_contradictory'
   elif any('Unsupported'in r or 'No documented'in r or 'predicate'in r or 'inequality'in r for r in reasons):category='unsupported_predicate'
   elif m.get('status')!='active' or e.get('exclusion') in ('kickoff_reached','phase_or_reschedule'):category='stale_or_ineligible'
   else:category='actual_missing_fact'
   accounting.append(dict(source=v,market_id=m['id'],event_id=m['event_id'],cohort='original_570' if m['id'] in before else 'recovered_complete_US_detail',classification=category,metadata_admitted=admitted,prior_admitted=prior.get('status')=='BOUND_RAW_PREDICATE',blockers=reasons,market_exclusion=m.get('exclusion'),event_exclusion=e.get('exclusion'),identity=b.get('identity'),source_prices_are_not_depth=True,provenance=m['provenance']))
 (OUT/'record-accounting.json').write_text(json.dumps(accounting,indent=2)+'\n')
 print({v:Counter(m['v1_raw_binding']['status'] for m in c['markets']) for v,c in cats.items()},flush=True)
 print(Counter((r['cohort'],r['classification']) for r in accounting),flush=True)
 # A separate saved local derivation through the ordinary bounded journal/reducer.
 # No live activation or original approval is copied as new authority.
 folder=OUT/'saved'/SID;folder.mkdir(parents=True,exist_ok=True)
 derived=[];seen=[];cache={}
 for original in rows:
  r=deepcopy(original);r['session_id']=SID
  if r['type']=='session_started':
   r['spec']['session_id']=SID;r['spec']['v1_comparison_policy']='manual-comparison-2';r['spec']['offline_derivation']=dict(original_session=rows[0]['session_id'],collection_authorized=False)
  if r['type']=='prediction_discovery_http':
   match=next((p for p in pages if p['ingress_id']==r['ingress_id']),None)
   if match:r.update(deepcopy(match),session_id=SID);seen.append(r)
  if r['type']=='coverage_inventory':
   key=stable([p['ingress_id'] for p in seen])
   if key not in cache:cache[key]={v:catalog(seen,v,stamp(r['observed_at']),v1_templates=rows[0]['spec'].get('native_review_records',[])) for v in r['inventory']}
   r['inventory']=deepcopy(cache[key])
  derived.append(r)
 journalpath=folder/(SID+'.jsonl')
 if journalpath.exists():journalpath.unlink() # this local derivation only; originals protected
 from app.collection.journal_encoding import VERSION
 j=ObservationJournal(journalpath,encoding=VERSION)
 for r in derived:j.save(r)
 chain=j.previous;j.close()
 for name in ('aggregate-limits.json','report.json','replay.json'):
  d=json.loads((SESSION/name).read_text());d['offline_derivation']=dict(original_session=rows[0]['session_id'],derived_session=SID,collection_authorized=False,classification='Local interpretation of retained live inputs; original run outcome preserved as provenance');(folder/name).write_text(json.dumps(d,indent=2)+'\n')
 (folder/'run-spec.json').write_text(json.dumps(derived[0]['spec'],indent=2)+'\n')
 files={name:sha256((folder/name).read_bytes()).hexdigest() for name in ['run-spec.json','aggregate-limits.json','report.json','replay.json',SID+'.jsonl']}
 (folder/'manifest.json').write_text(json.dumps(dict(files=files,journal_chain=chain,classification='OFFLINE retained-input derivation; no acquisition authority'),indent=2)+'\n')
 index_path=ROOT/'app/reviews/native/index-v4.json';index=json.loads(index_path.read_text())
 if SID in index.get('historical_paths',{}):
  binding=index['historical_paths'][SID];assert binding['classification'].startswith('OFFLINE') and binding['folder']==str(folder.relative_to(ROOT))
  product_chain='0'*64
  for r in derived:product_chain=stable([product_chain,r])
  binding['product_chain']=product_chain;index_path.write_text(json.dumps(index,indent=2,sort_keys=True)+'\n')
 snapshot=load(folder);assert snapshot==load(folder);original=load(SESSION)
 assert stable(original)=='57facbc23c27b80f8862b1f150246b3596fe9800e1886f5e06c0e3d24ae6c15c',stable(original)
 summary=dict(classification='OFFLINE retained-input derivation',original_snapshot_sha256=stable(original),derived_snapshot_sha256=stable(snapshot),metadata_admissions={cohort:dict(Counter(r['classification'] for r in accounting if r['cohort']==cohort)) for cohort in ('original_570','recovered_complete_US_detail')},total_metadata_admitted=sum(r['metadata_admitted'] for r in accounting),native_price_images=sum(r['type']=='prediction_book' for r in rows),new_provider_requests=0,original_session=rows[0]['session_id'],derived_session=SID,exact_reopening=True)
 (OUT/'replay-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
if __name__=='__main__':main()
