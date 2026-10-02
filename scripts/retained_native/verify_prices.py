"""Independent decimal wire oracle, separate from adapters and comparison reducers."""
from collections import defaultdict,Counter
from decimal import Decimal as D
from pathlib import Path
import base64,json,sys
from app.dashboard.session_history import verified
from app.dashboard.session_projection import stable
folder=Path(sys.argv[1]);destination=Path(sys.argv[2]);state={};images={};counts=Counter();updates={};last={};seen={};canonical_previous={};purchase_previous={};failures=[];latest_purchases={};native_market_ids={};sides={};us_images=set()
def levels(items):return {D(p):D(q) for p,q in items if D(q)>0}
def read(ladder):return {} if ladder is None else {D(l['price']['value']):D(l['quantity']['value']) for l in ladder['levels']}
for cursor,row in enumerate(verified(folder)['rows'],1):
 v=row.get('source');typ=row['type']
 if typ=='market_selected' and v=='polymarket_us':
  raw=row['market']['raw'];body=json.loads(raw['json_text']);ref=raw['ref'];m=next(m for m in body.get('markets',[])+[m for e in body.get('events',[]) if str(e['id'])==ref['event_id'] for m in e.get('markets',[])] if str(m['id'])==ref['market_id']);sides[ref['market_id']]={str(s['id']):s['long'] for s in m['marketSides']};native_market_ids[m['slug']]=ref['market_id']
 if typ=='prediction_frame' and v=='polymarket_us':
  payload=json.loads(base64.b64decode(row['body_b64']))
  if 'marketData' in payload:us_images.add(stable(payload['marketData']))
 if typ=='prediction_frame' and v=='kalshi':
  msg=json.loads(base64.b64decode(row['body_b64']));data=msg.get('msg') or {};mid=data.get('market_ticker')
  if msg.get('type')=='orderbook_snapshot':state[mid]={s:levels(data[s+'_dollars_fp']) for s in ('yes','no')}
  elif msg.get('type')=='orderbook_delta' and mid in state:
   side=data['side'];p=D(data['price_dollars']);q=state[mid][side].get(p,D(0))+D(data['delta_fp'])
   if q<0:failures.append(dict(cursor=cursor,reason='Negative native delta balance'))
   if q>0:state[mid][side][p]=q
   else:state[mid][side].pop(p,None)
  else:continue
  # Finite sequence images; health emissions refer to a retained wire image.
  by=images.setdefault(mid,{})
  by[msg.get('seq')]=(stable(msg),{s:dict(ls) for s,ls in state[mid].items()})
  while len(by)>8:by.pop(next(iter(by)))
 if typ!='prediction_book':continue
 b=row['book'];raw=json.loads(b['raw']['json_text']);ref=b['raw']['ref'];key='|'.join((v,ref['event_id'],ref['market_id']));oid=stable([b['raw']['json_text'],b['raw']['received_at']]);summary=updates.setdefault(key,Counter());summary['book_rows']+=1
 if oid in seen.setdefault(key,set()):summary['health_reemissions']+=1
 else:
  seen[key].add(oid)
  canonical={(o['outcome_id'],side,price):qty for o in b['outcomes'] for side in ('bids','asks') for price,qty in read(o[side]).items()}
  ladders=stable(sorted((oid,side,str(price.normalize()),str(qty.normalize())) for (oid,side,price),qty in canonical.items()));prev=last.get(key)
  if prev is not None and prev!=ladders:
   summary['price_level_changes' if set(canonical)!=set(canonical_previous[key]) else 'quantity_only_changes']+=1
  canonical_previous[key]=canonical
  summary['initial_images' if prev is None else 'unchanged_ladder_observations' if prev==ladders else 'actual_ladder_updates']+=1;last[key]=ladders
 try:
  if v=='kalshi':
   msg=raw['message'];mid=msg['msg']['market_ticker'];oracle=images[mid][msg['seq']];assert oracle[0]==stable(msg),'Wire message differs'
   purchases={}
   for o in b['outcomes']:
    assert read(o['bids'])==oracle[1][o['outcome_id']],'Native Kalshi bids differ'
    opposite='no' if o['outcome_id']=='yes' else 'yes';expected={1-p:q for p,q in oracle[1][opposite].items()}
    # Kalshi native outcome may omit asks; purchase quotes explicitly complement opposite bids.
    if o['asks'] is not None:assert read(o['asks'])==expected,'Kalshi asks differ'
    purchases[o['outcome_id']]=[dict(price=str(p),quantity=str(q)) for p,q in sorted(expected.items())]
  else:
   md=raw['marketData'];assert stable(md) in us_images,'US native image missing original wire receipt'
   assert native_market_ids[md['marketSlug']]==ref['market_id'],'US native slug differs'
   bids={D(l['px']['value']):D(l['qty']) for l in md.get('bids',[]) if D(l['qty'])>0};offers={D(l['px']['value']):D(l['qty']) for l in md.get('offers',[]) if D(l['qty'])>0}
   purchases={}
   for o in b['outcomes']:
    long=sides[ref['market_id']][o['outcome_id']]
    expected=offers if long else {1-p:q for p,q in bids.items()}
    if o['asks'] is not None:assert read(o['asks'])==expected,'US purchasable asks differ'
    elif not long:counts['original_us_short_asks_omitted']+=1
    else:raise AssertionError('US Long native asks missing')
    purchases[o['outcome_id']]=[dict(price=str(p),quantity=str(q)) for p,q in sorted(expected.items())]
    if long:assert read(o['bids'])==bids,'US Long bids differ'
  tops={side:ls[0]['price'] if ls else None for side,ls in purchases.items()}
  if oid not in purchase_previous.setdefault(key,{'seen':set()})['seen']:
   prior=purchase_previous[key].get('tops')
   if prior is not None and {s:None if p is None else D(p) for s,p in tops.items()}!={s:None if p is None else D(p) for s,p in prior.items()}:summary['top_buy_price_changes']+=1
   purchase_previous[key]['seen'].add(oid);purchase_previous[key]['tops']=tops
  latest_purchases[key]=purchases
  counts[v]+=1
 except (AssertionError,KeyError) as exc:failures.append(dict(cursor=cursor,key=key,reason=str(exc)))
result=dict(folder=str(folder),exact_books=dict(counts),observations={k:dict(c) for k,c in updates.items()},latest_purchases=latest_purchases,failures=failures)
destination.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print(json.dumps(dict(books=dict(counts),failures=len(failures))))
if failures:sys.exit(1)
