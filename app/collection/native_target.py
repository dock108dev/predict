"""Sealed exact selections, current metadata gates and session-only review revisions."""
from copy import deepcopy
from datetime import timedelta
from app.dashboard.session_projection import stable
from app.dashboard.native_reviews import validate
from . import coverage
from .native_selectors import POLICY, SPORTS
SLICE='native-reviewed-target-v1'
REPAIRED_SLICE='native-reviewed-target-v2'
EVENTS={'kalshi':'KXNHLGAME-26SEP30NYITOR','polymarket_us':'127804'}
MARKETS={'kalshi':['KXNHLGAME-26SEP30NYITOR-NYI','KXNHLGAME-26SEP30NYITOR-TOR'],'polymarket_us':['1061481']}
CONTRACT=dict(policy=POLICY,sports=list(SPORTS),discovery_only=False,generations=1,slice=SLICE,
 acquisition_sports=['NHL'],events_per_venue=1,markets_per_venue=2)

def enabled(spec):return spec.get('native_discovery',{}).get('slice')in (SLICE,REPAIRED_SLICE)

def validate_spec(spec):
 from .venue_access import REFERENCES
 if spec['native_discovery']!={**CONTRACT,'slice':spec['native_discovery']['slice']}:raise ValueError('Exact reviewed target contract required')
 if not 0<spec['duration']<=90 or spec['prediction']!=dict(messages=600,connections=2,frame_bytes=262144,session_bytes=8388608,discovery_requests=1,dollar_cap_per_source='0',dollars_per_discovery_request='0',dollars_per_connection='0',plan_evidence='docs/native-nyi-tor-acquisition.md#access'):raise ValueError('Target bounds changed')
 templates=spec.get('native_review_records',[])
 if len(templates)!=2:raise ValueError('Two conditional review templates required')
 if {r['sources']['kalshi']['market_id'] for r in templates}!=set(MARKETS['kalshi']):raise ValueError('Selected Kalshi markets changed')
 for r in templates:
  validate(r)
  if spec['native_discovery']['slice']==REPAIRED_SLICE:
   from .native_review_contract import validate as validate_contract
   for v,source in r['sources'].items():validate_contract(v,source.get('semantic_review_contract'),source['catalog_evidence']['event']['native_metadata'],source['metadata'])
  if r['applicability']['status']!='CONDITIONAL' or r['identity']['competition']!='NHL' or set(r['participants'])!={'NHL:NYI','NHL:TOR'}:raise ValueError('Target review changed')
  if any(r['sources'][v]['event_id']!=EVENTS[v] or r['sources'][v]['market_id'] not in MARKETS[v] for v in EVENTS):raise ValueError('Target IDs changed')
 if any(spec['sources'][v]['credential_reference']!=REFERENCES[v] for v in EVENTS):raise ValueError('Dedicated credentials required')
 if any(x is not None for x in spec['assessment_revisions'].values()):raise ValueError('Economics unavailable')

async def discover(d,venue):
 if venue=='kalshi':
  await d.pages_for(venue,'/trade-api/v2/events',dict(tickers=EVENTS[venue],with_milestones='true',with_nested_markets='true'),'events',1,page_cap=1)
 elif d.session.spec['native_discovery']['slice']==REPAIRED_SLICE:
  response=await d.clients[venue].get(d.clients[venue].endpoint+'/v1/events/127804',{})
  if response.status_code!=200:raise ValueError('catalog_http_'+str(response.status_code))
  data=response.json()
  if not isinstance(data.get('event'),dict):raise ValueError('native_malformed_data')
  if str(data['event'].get('id'))!='127804':raise ValueError('absent_selected_event_in_complete_response')
 else:
  await d.pages_for(venue,'/v1/events',dict(id=['127804'],tagSlug='nhl',includeHidden='false',includePopularPlayerProps='false',**({'marketTypes':['moneyline']} if d.session.spec['native_discovery']['slice']==REPAIRED_SLICE else {})),'events',1,page_cap=1)

def check(catalog,venue,templates,at):
 from .native_review_contract import compare
 semantic=all('semantic_review_contract' in r['sources'][venue] for r in templates)
 e=next((e for e in catalog['events'] if e['id']==EVENTS[venue]),None)
 if not e:return [],'absent_selected_event_in_complete_response'
 if e.get('exclusion') or e.get('identity')!='resolved':return [],'target_closed_unsupported_or_unresolved'
 if not e.get('scheduled_start') or not at+timedelta(minutes=5)<coverage.stamp(e['scheduled_start']):return [],'target_outside_prestart_applicability'
 en=deepcopy(e['_native'])
 # Nested markets are transport packaging; every selected market is checked below.
 if venue=='kalshi':en.pop('markets',None)
 expected=templates[0]['sources'][venue]['catalog_evidence']['event']['native_metadata']
 if semantic:
  ok,reason=compare(venue,expected,en,event=True)
  if not ok:return [],reason
 elif en!=expected:return [],'changed_event_metadata_requires_new_explicit_review'
 ids=[]
 for mid in MARKETS[venue]:
  m=next((m for m in catalog['markets'] if m['id']==mid),None)
  if not m:return [],'absent_selected_market_in_complete_response'
  if m.get('exclusion'):return [],'unsupported_selected_market_identity'
  if m.get('status')!='active':return [],'unsupported_current_market_eligibility'
  t=next(r for r in templates if r['sources'][venue]['market_id']==mid)
  if semantic:
   ok,reason=compare(venue,t['sources'][venue]['metadata'],m['_native'])
   if not ok:return [],reason
  elif stable(m['_native'])!=t['sources'][venue]['native_metadata_sha256']:continue
  if e['canonical_key']!=t['event'] or m['event_id']!=e['id'] or m['market_type']!='moneyline' or m['period']!='full_game':continue
  ids.append(mid)
 return ids,'exact_metadata_admitted' if len(ids)==len(MARKETS[venue]) else 'missing_closed_or_changed_market_requires_review'

async def finish(d):
 templates=d.session.spec['native_review_records'];cats={v:coverage.catalog(d.pages,v,d.selection_time) for v in EVENTS}
 d.acquisition_selected={v:{EVENTS[v]} for v in EVENTS};d.book_market_ids={}
 for v in EVENTS:
  if d.session.spec.get('native_transport'):d.bound_source_catalog(v,cats[v])
  ids,reason=check(cats[v],v,templates,d.selection_time)
  if d.session.spec['native_discovery']['slice']==REPAIRED_SLICE and v not in d.source_stops:
   from .native_review_contract import compare
   for page in d.pages:
    if page['source']!=v or not page.get('usable_metadata'):continue
    _,data=coverage.decode_page(page)
    raw_event=next((x for x in data.get('events',[]) if str(x.get('event_ticker' if v=='kalshi' else 'id'))==EVENTS[v]),None)
    if raw_event is None:continue
    if v=='polymarket_us' and (not isinstance(raw_event.get('teams'),list) or len(raw_event['teams'])<2):ids=[];reason='unsupported_selected_identity';break
    expected=templates[0]['sources'][v]['catalog_evidence']['event']['native_metadata']
    ok,raw_reason=compare(v,expected,raw_event,event=True)
    if not ok:ids=[];reason=raw_reason;break
    embedded=raw_event.get('markets')
    if not isinstance(embedded,list):ids=[];reason='native_malformed_data';break
    if any(not any(str(x.get('ticker' if v=='kalshi' else 'id'))==mid for x in embedded if isinstance(x,dict)) for mid in MARKETS[v]):ids=[];reason='absent_selected_market_in_complete_response';break
  if v in d.source_stops:ids=[];reason=d.source_stops[v]
  if not ids:d.stop_source(v,reason)
  d.book_market_ids[v]=ids
  d.session.emit(v,dict(type='native_book_selection',event_id=EVENTS[v],market_ids=ids,reason=reason,substitution=False,qualification='raw prices only'))
 for template in templates:
  if not all(template['sources'][v]['market_id'] in d.book_market_ids[v] for v in EVENTS):continue
  r=deepcopy(template);r.pop('sha256');r['revision']+=1;r['historical_session_id']=d.session.sid
  r['applicability']=dict(status='SUPPORTED',start=d.selection_time.isoformat(),end=(d.selection_time+timedelta(seconds=d.session.spec['duration'])).isoformat(),basis='Explicit sealed exact-metadata revalidation policy; this new session only, raw correspondence only')
  r['current_session_revalidation']=dict(policy=d.session.spec['native_discovery']['slice'],template_sha256=template['sha256'])
  for v,s in r['sources'].items():
   e=next(e for e in cats[v]['events'] if e['id']==s['event_id']);m=next(m for m in cats[v]['markets'] if m['id']==s['market_id'])
   s.pop('catalog_evidence',None);s.pop('base_native_metadata_sha256',None)
   s['reviewed_template_raw_hashes']=dict(event=s['event_metadata_sha256'],market=s['native_metadata_sha256'])
   s['metadata']=deepcopy(m['_native']);s['native_metadata_sha256']=stable(m['_native'])
   if 'semantic_review_contract' in s:
    from .native_review_contract import contract
    s['semantic_review_contract']=contract(v,e['_native'],m['_native'])
   s['event_metadata_sha256']=stable(e['_native']);s['provenance']=deepcopy(e['provenance']+m['provenance'])
  r['sha256']=stable(r);validate(r)
  d.session.emit('session',dict(type='native_review',review=r))
