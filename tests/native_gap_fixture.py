"""Mixed fixture: unchanged complete Kalshi bytes, explicitly synthetic US controls.

The original truncated CFB prefix is used ONLY for an oversized transport control.
No synthesized US game or new matching metadata is provider evidence.
"""
import base64,io,json
from pathlib import Path
from datetime import datetime,timezone,timedelta
from urllib.parse import urlsplit
import aiohttp
ROOT=Path(__file__).resolve().parents[1]
PAGES=json.loads((ROOT/'evidence/native-probe-r2-derived-20260930-v1/captured-pages.json').read_text())
class Response:
 def __init__(self,raw,status=200,headers=None):self.buffer=io.BytesIO(raw);self.content=self;self.status=status;self.headers=headers or {}
 async def read(self,size):return self.buffer.read(size)
 def at_eof(self):return self.buffer.tell()==len(self.buffer.getbuffer())
 async def __aenter__(self):return self
 async def __aexit__(self,*a):pass
class HTTP:
 calls=[];clients=[];mode='oversized';retry=False
 def __init__(self,*a,**kw):self.connector=kw.get('connector');self.closed=False;self.clients.append(self)
 @classmethod
 def reset(cls,mode='oversized',retry=False):cls.calls=[];cls.clients=[];cls.mode=mode;cls.retry=retry
 def get(self,url,*,params,**kw):
  host=urlsplit(url).hostname;assert host in ('external-api.kalshi.com','gateway.polymarket.us')
  assert kw['allow_redirects'] is False and kw['headers']=={'Accept-Encoding':'identity'}
  path=urlsplit(url).path;q={k:str(v) for k,v in params.items()};source='kalshi' if host=='external-api.kalshi.com' else 'polymarket_us'
  label='UNCHANGED RETAINED KALSHI' if source=='kalshi' else 'SYNTHETIC US TRANSPORT CONTROL'
  self.calls.append(dict(source=source,path=path,params=q,classification=label))
  if source=='kalshi':
   match=[p for p in PAGES if p['source']==source and p['path']==path and {k:str(v) for k,v in p['params'].items()}==q]
   if match:return Response(base64.b64decode(match[0]['body_b64']))
   # Newly selected WKU/NMSU and NYI/TOR market records are genuinely missing.
   self.calls[-1]['classification']='SYNTHETIC 404: KALSHI SELECTED METADATA NOT RETAINED'
   return Response(b'{"error":"OFFLINE: selected-market evidence not retained"}',404)
  assert path in ('/v1/events','/v1/markets')
  if path.endswith('/events'):
   assert q['marketTypes']=='moneyline' and q['limit']=='1' and q['tagSlug']!='nfl'
   if q['tagSlug']=='cfb' and self.mode.startswith('oversized'):
    self.calls[-1]['classification']='ORIGINAL TRUNCATED CFB PREFIX, OVERSIZE CONTROL ONLY'
    return Response(base64.b64decode(next(p for p in PAGES if not p['complete'])['body_b64']))
   if q['tagSlug']=='nba' and self.mode=='retry_first' and sum(c['params'].get('tagSlug')=='nba' for c in self.calls)==1:
    return Response(b'{"error":"synthetic rate limit"}',429,{'Retry-After':'1'})
   e=self.event(q['tagSlug'])
   if self.mode=='null_schedule' and q['tagSlug']=='cfb':e['startTime']=None
   if self.mode in ('duplicate','oversized_source_stop') and q['tagSlug']=='nba':e['startTime']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
   return Response(json.dumps(dict(events=[e])).encode())
  game=q['gameId'];assert q['sportsMarketTypes']=='SPORTS_MARKET_TYPE_MONEYLINE' and q['limit']=='5'
  if game=='1002':return Response(b'{"error":"synthetic missing metadata"}',404)
  if self.retry and game=='1004' and sum(c['params'].get('gameId')==game for c in self.calls)==1:return Response(b'{}',503)
  return Response(json.dumps(dict(markets=[self.market(game)])).encode())
 @staticmethod
 def event(slug):
  game={'cfb':1001,'nba':1002,'mlb':1003,'nhl':1004,'cbb':1005}[slug]
  return dict(id=str(game+10000),gameId=game,title='SYNTHETIC Alpha vs Beta',startTime=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),active=True,closed=False,ended=False,teams=[dict(id=game*2,name='SYNTHETIC Alpha',league=slug),dict(id=game*2+1,name='SYNTHETIC Beta',league=slug)],tags=[dict(slug='games'),dict(league=dict(slug=slug))],markets=[HTTP.market(str(game))],description='SYNTHETIC CFB-shaped bounded response '+('x'*180000 if slug=='cfb' else ''))
 @staticmethod
 def market(game):return dict(id=str(int(game)+20000),gameId=int(game),slug='synthetic-'+game,question='SYNTHETIC winner',marketType='moneyline',sportsMarketType='moneyline',sportsMarketTypeV2='SPORTS_MARKET_TYPE_MONEYLINE',status='MARKET_STATUS_OPEN',active=True,closed=False,description='SYNTHETIC transport control; no terms authority',marketSides=[dict(id='a'+game,long=True,marketId=int(game)+20000,team=dict(name='SYNTHETIC Alpha')),dict(id='b'+game,long=False,marketId=int(game)+20000,team=dict(name='SYNTHETIC Beta'))])
 async def close(self):
  self.closed=True
  if self.connector:await self.connector.close()
