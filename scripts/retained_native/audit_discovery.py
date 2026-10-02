"""Account for pre-session discovery attempts without promoting them to sessions."""
import json,base64
from pathlib import Path
from hashlib import sha256
from app.collection.transport_session import reopen
from app.collection.coverage import catalog,match_catalogs,stamp
from app.dashboard.session_projection import stable
out=Path('evidence/native-retained-coverage-20260930-v1');ledger=[]
for path in sorted(Path('evidence/e6/prediction-only').glob('real-*/discovery.jsonl')):
 saved=reopen(path);pages=[];receipts=[]
 for cursor,r in enumerate(saved['rows'],1):
  if r['type']!='prediction_discovery_http':continue
  raw=base64.b64decode(r['body_b64']);assert sha256(raw).hexdigest()==r['body_sha256'];reason=None
  if not r.get('complete') or r.get('status')!=200:reason='Incomplete/unsuccessful native response'
  else:
   try:json.loads(raw)
   except ValueError:reason='Invalid JSON'
  receipts.append(dict(cursor=cursor,source=r['source'],path=r['path'],params=r['params'],received_at=r['received_at'],body_sha256=r['body_sha256'],bytes=len(raw),exclusion=reason))
  if not reason:pages.append(r)
 end=saved['rows'][-1]['finished_at'] if saved['rows'][-1].get('finished_at') else max((r['received_at'] for r in pages),default='2026-09-15T00:00:00+00:00')
 cats={v:catalog(pages,v,stamp(end)) for v in ('kalshi','polymarket_us')};match_catalogs(cats)
 for c in cats.values():
  for x in c['events']+c['markets']:x['native_metadata']=x.pop('_native')
 ledger.append(dict(path=str(path),journal_sha256=saved['sha256'],receipts=receipts,catalogs=cats,classification='original pre-session discovery attempt; no priced session',associations=[dict(event=e['canonical_key'],events=dict(kalshi=e['id'],polymarket_us=e['counterpart_event_ids']),market_ids=e['market_ids']) for e in cats['kalshi']['events'] if e.get('counterpart_event_ids')]))
(out/'standalone-discovery.json').write_text(json.dumps(ledger,sort_keys=True,indent=2)+'\n')
print([(x['path'],len(x['receipts']),len(x['associations']),sum(bool(a['market_ids']) for a in x['associations'])) for x in ledger])
