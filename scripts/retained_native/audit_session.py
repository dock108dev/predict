"""Offline source audit; one process per retained session preserves reader RSS bounds."""
import base64,json,sys
from collections import Counter
from pathlib import Path
from hashlib import sha256
from app.dashboard.session_history import verified
from app.dashboard.session_projection import SessionProjection,stable,stamp
from app.collection.coverage import catalog,match_catalogs
folder=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
p=SessionProjection();projection_error=None;p.native_interpretation='native-book-comparison-3'
counts=Counter();pages=[];receipts=[];observations={};frames=[];inventories=[];metadata_timeline={};product_chain='0'*64
verified_data=verified(folder)
for cursor,row in enumerate(verified_data['rows'],1):
 product_chain=stable([product_chain,row]);counts[row['type']]+=1
 if not projection_error:
  try:p.apply(row)
  except (ValueError,KeyError) as exc:projection_error=str(exc)
 # Audit source bytes even when the original product projection cannot publish.
 p.last=row['observed_at']
 if row['type'] in ('prediction_http','prediction_discovery_http'):
  page=dict(row);raw=base64.b64decode(page['body_b64']);reason=None;body=None
  if sha256(raw).hexdigest()!=page['body_sha256']:raise ValueError('body hash mismatch')
  if not page.get('complete') or page.get('status')!=200:reason='incomplete response' if not page.get('complete') else 'HTTP '+str(page.get('status'))
  else:
   try:body=json.loads(raw)
   except ValueError:reason='invalid JSON'
  receipts.append(dict(cursor=cursor,source=row['source'],path=row['path'],params=row.get('params'),received_at=row['received_at'],body_sha256=row['body_sha256'],bytes=len(raw),complete=row.get('complete'),status=row.get('status'),exclusion=reason))
  if not reason:pages.append(page)
 if row['type']=='coverage_inventory':inventories.append(dict(cursor=cursor,observed_at=row['observed_at'],generation=row['generation']))
 if row['type']=='market_selected':
  meta=row['market'];r=meta['raw'];payload=json.loads(r['json_text']);ref=r['ref'];key='|'.join((row['source'],ref['event_id'],ref['market_id']))
  native=next(m for m in payload.get('markets',[])+[m for e in payload.get('events',[]) if str(e.get('id'))==ref['event_id'] for m in e.get('markets',[])] if str(m.get('ticker' if row['source']=='kalshi' else 'id'))==ref['market_id'])
  entry=dict(cursor=cursor,observed_at=row['observed_at'],received_at=r['received_at'],body_sha256=sha256(r['json_text'].encode()).hexdigest(),native_metadata=native,source=r['source'])
  sequence=metadata_timeline.setdefault(key,[])
  if not sequence or sequence[-1]['body_sha256']!=entry['body_sha256']:sequence.append(entry)
 if row['type']=='prediction_frame':
  raw=base64.b64decode(row['body_b64']);frames.append(dict(cursor=cursor,source=row['source'],received_at=row.get('received_at',row['observed_at']),body_sha256=sha256(raw).hexdigest()))
 if row['type']=='prediction_book':
  b=row['book'];r=b['raw'];key='|'.join((row['source'],r['ref']['event_id'],r['ref']['market_id']))
  item=dict(cursor=cursor,observed_at=row['observed_at'],received_at=r['received_at'],source_at=r.get('exchange_at'),raw_sha256=sha256(r['json_text'].encode()).hexdigest(),raw=json.loads(r['json_text']),outcomes=b['outcomes'],sync=b['sync'],state=b['state'])
  group=observations.setdefault(key,dict(rows=0,unique={},first=item,last=item))
  group['rows']+=1;group['last']=item
  oid=stable([item['raw_sha256'],item['received_at']])
  group['unique'].setdefault(oid,dict(cursor=cursor,received_at=item['received_at'],raw_sha256=item['raw_sha256'],ladders_sha256=stable(item['outcomes'])))
# Full catalogs derived solely from complete native bytes. Never draw across sessions.
cat={v:catalog(pages,v,stamp(p.last)) for v in ('kalshi','polymarket_us')}
match_catalogs(cat)
for c in cat.values():
 for x in c['events']+c['markets']:x['native_metadata']=x.pop('_native')
# Preserve original selected catalogs for exact books (including historical parser identity).
snapshot=p.snapshot(mode='saved') if not projection_error else None
if snapshot is not None:snapshot['state']='saved' if verified_data['state']=='complete' and 'failure' not in (p.stop_reason or '') else 'incomplete'
data=dict(session_id=p.sid,folder=str(folder),state=verified_data['state'],start=p.started,end=p.last,counts=dict(counts),spec_sha256=stable(p.spec),journal_chain=product_chain,receipts=receipts,inventories=inventories,original_inventory=p.inventory,derived_inventory=cat,metadata_timeline=metadata_timeline,selected_metadata=[dict(key=list(k),row=r) for k,r in p.metadata.items()],observations=observations,frames=frames,projection_error=projection_error,original_projection_sha256=stable(snapshot),original_games=len(snapshot['games']) if snapshot else None)
(out/(p.sid+'.json')).write_text(json.dumps(data,sort_keys=True,indent=2))
print(json.dumps(dict(session=p.sid,counts=dict(counts),original_games=data['original_games'],events={v:len(c['events']) for v,c in cat.items()},markets={v:len(c['markets']) for v,c in cat.items()})))
