"""Exact offline corpus ledger, retaining per-session provenance without pooling prices."""
import json
from pathlib import Path
from collections import Counter
from hashlib import sha256
OUT=Path('evidence/native-retained-coverage-20260930-v1')
def read(p):return json.loads(p.read_text())
def key(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def dump(name,x):(OUT/name).write_text(json.dumps(x,sort_keys=True,indent=2)+'\n')
idx=read(Path('app/reviews/native/index-v4.json'));records=[read(Path('app/reviews/native')/n) for n in idx['records']]
pair=lambda r:tuple(r['sources'][v][k] for v in ('kalshi','polymarket_us') for k in ('event_id','market_id'))
reviewed_events={key(r['event']) for r in records};pairs={pair(r) for r in records};priced=set();cards=set();receipts={};receipt_totals=Counter();objects={};sessions=[];obs_totals=Counter();all_native_books=0
reopen={r['session_id']:r for r in read(OUT/'reopening-final.json')['records']}
for f in sorted((OUT/'sessions').glob('*.json')):
 a=read(f);sid=a['session_id'];native=sid!='pinnacle-nfl-retained-20260921';o=OUT/'oracles'/(sid+'.json');o=read(o) if o.exists() else None
 observations=Counter()
 if o:
  for value in o['observations'].values():observations.update(value)
  obs_totals.update(observations)
 all_native_books+=a['counts'].get('prediction_book',0)
 for r in a['receipts']:
  receipt_totals['complete_200_usable' if r['exclusion'] is None else r['exclusion']]+=1
  ident=key({k:r.get(k) for k in ('source','path','params','received_at','body_sha256','complete','status')})
  receipts.setdefault(ident,dict(receipt={k:v for k,v in r.items() if k!='cursor'},provenance=[]))['provenance'].append(dict(session_id=sid,cursor=r['cursor']))
 for venue,catalog in a['derived_inventory'].items():
  for kind in ('events','markets'):
   for obj in catalog[kind]:
    ident=key([venue,kind,obj['id'],sha256(key(obj['native_metadata']).encode()).hexdigest()])
    objects.setdefault(ident,dict(venue=venue,kind=kind,native_id=obj['id'],native_metadata_sha256=sha256(key(obj['native_metadata']).encode()).hexdigest(),native_structure={k:obj['native_metadata'].get(k) for k in ('marketType','sportsMarketType','sportsMarketTypeV2','type','series_ticker','product_metadata')},provenance=[],assessments=[]))
    objects[ident]['provenance'].append(dict(session_id=sid,receipts=obj.get('provenance',[])))
    objects[ident]['assessments'].append(dict(session_id=sid,identity=obj.get('identity'),exclusion=obj.get('exclusion'),family=obj.get('family'),period=obj.get('period'),matching_status=obj.get('matching_status')))
 d=read(OUT/'derived'/(sid+'.json'))
 for g in d['snapshot']['games']:
  if g.get('native_raw'):priced.add(pair(g['native_review']['record']))
 for r in d['comparisons']:
  if r.get('native_raw'):cards.add(key([r['event_key'],r['outcome']]))
 sessions.append(dict(session_id=sid,folder=a['folder'],evidence_class='real native acquisition' if native else 'retained reference only',start=a['start'],end=a['end'],state=a['state'],journal_chain=a['journal_chain'],http_receipts=len(a['receipts']),receipt_assessments=dict(Counter(r['exclusion'] or 'complete_200_usable' for r in a['receipts'])),complete_catalog_events={v:len(c['events']) for v,c in a['derived_inventory'].items()},complete_catalog_markets={v:len(c['markets']) for v,c in a['derived_inventory'].items()},selected_metadata=len(a['selected_metadata']),metadata_revisions={k:len(v) for k,v in a['metadata_timeline'].items()},native_frames=len(a['frames']),native_book_rows=a['counts'].get('prediction_book',0),observations=dict(observations),**{k:reopen[sid][k] for k in ('native_cards','native_games','metadata_only','cutoff','original_v3_sha256','original_failure','derived_v4_sha256','independent_leg_checks')}))
standalone=read(OUT/'standalone-discovery.json')
for attempt in standalone:
 for r in attempt['receipts']:
  receipt_totals['complete_200_usable' if r.get('exclusion') is None else r['exclusion']]+=1
  ident=key({k:r.get(k) for k in ('source','path','params','received_at','body_sha256','complete','status')})
  receipts.setdefault(ident,dict(receipt=r,provenance=[]))['provenance'].append(dict(discovery_journal=attempt['path']))
associations=read(OUT/'associations.json');eventonly={}
for a in associations:
 if key(a['event']) not in reviewed_events:
  eventonly.setdefault(key(a['event']),dict(event=a['event'],competition=a['competition'],events=a['events'],provenance=[],missing=[]))
  eventonly[key(a['event'])]['provenance'].append(a['session_id']);eventonly[key(a['event'])]['missing']+=a['exclusions']
for a in eventonly.values():a['missing']=sorted(set(a['missing']))
metadata_only=[]
for p in sorted(pairs-priced):
 rs=[r for r in records if pair(r)==p];metadata_only.append(dict(native_pair=list(p),event=rs[0]['event'],competition=rs[0]['identity']['competition'],records=[dict(review_id=r['review_id'],sha256=r['sha256'],origin=r.get('historical_session_id')) for r in rs],per_capture_books=[dict(session_id=a['session_id'],books=r['books']) for a in associations for r in a['reviews'] if tuple(a['events'][v] if k=='event_id' else r['markets'][v] for v in ('kalshi','polymarket_us') for k in ('event_id','market_id'))==p],missing='No paired usable native books at an original observation cutoff; missing venue books listed per capture'))
summary=dict(unique_session_packages=len(sessions),native_acquisitions=sum(s['evidence_class']=='real native acquisition' for s in sessions),reference_packages=1,native_sessions_with_books=sum(s['native_book_rows']>0 for s in sessions),standalone_discovery_attempts=len(standalone),native_http_receipt_occurrences=sum(len(read(f)['receipts']) for f in (OUT/'sessions').glob('*.json')),standalone_http_receipt_occurrences=sum(len(a['receipts']) for a in standalone),distinct_receipt_identities=len(receipts),receipt_assessments=dict(receipt_totals),indexed_review_records=len(records),new_review_records=len(records)-1,unique_reviewed_events=len(reviewed_events),reviewed_events_by_competition=dict(Counter({c:len({key(r['event']) for r in records if r['identity']['competition']==c}) for c in {r['identity']['competition'] for r in records}})),unique_reviewed_market_pairs=len(pairs),new_market_pairs=len(pairs)-1,unique_priced_market_pairs=len(priced),unique_outcome_cards=len(cards),additional_outcome_cards=len(cards)-2,full_review_metadata_only_pairs=len(metadata_only),event_only_associations=len(eventonly),unique_event_associations=len({key(a['event']) for a in associations}),native_book_rows=all_native_books,observations=dict(obs_totals),native_card_occurrences=sum(s['native_cards'] for s in sessions),native_pair_occurrences=sum(s['native_games'] for s in sessions),independent_leg_checks=sum(s['independent_leg_checks'] for s in sessions),source_checks=len(read(OUT/'source-checks.json')['checks']),fresh_process_reopenings=len(reopen),required_scope_cells=63)
dump('corpus-accounting.json',dict(summary=summary,sessions=sessions,event_only_associations=list(eventonly.values()),full_review_metadata_only_pairs=metadata_only,record_inventory=[dict(file=n,sha256=idx['records'][n]) for n in idx['records']],boundaries=['Real historical correspondence only; no economics, freshness, execution or owner qualification','Books remain scoped to their exact original session and cutoff','Repeated captures retain original receipt and journal provenance; no blended prices','Synthetic controls, preparations, truncated payloads and reference books excluded from real coverage']))
dump('reviewed-event-ledger.json',[dict(event=json.loads(e),competition=next(r['identity']['competition'] for r in records if key(r['event'])==e),native_pairs=[list(p) for p in sorted({pair(r) for r in records if key(r['event'])==e})],records=[dict(review_id=r['review_id'],sha256=r['sha256'],origin=r.get('historical_session_id'),applicability=r['applicability']) for r in records if key(r['event'])==e]) for e in sorted(reviewed_events)])
dump('receipt-ledger.json',list(receipts.values()));dump('native-object-ledger.json',list(objects.values()));dump('session-inputs-final.json',dict(audited_packages=[s['folder'] for s in sessions],original_discovery=read(OUT/'session-inputs.json'),standalone_discovery=[a['path'] for a in standalone],reference_aliases=['evidence/b4-pinnacle-sample-20260921/sessions/pinnacle-nfl-retained-20260921','evidence/product-sessions/pinnacle-nfl-retained-20260921'],classification='Final journal-backed packages supersede preliminary directory classification; original discovery retained',no_journal_attempt='feb2bf9e-8afb-47c9-9cb9-8ddc085836a4: retained run-spec/limits/product-run only; no durable source receipt'))
print(json.dumps(summary,indent=2))
