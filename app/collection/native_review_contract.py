"""Explicit semantic contract v1. Raw hashes remain independent provenance.

Only enumerated observations may vary. Unknown paths default to review-sensitive
terms; additions/removals (even observational fields) require review. Packaging
markets are independently selected and reviewed rather than discarded as terms.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
from app.dashboard.session_projection import stable
POLICY = 'native-semantic-review-v1'
CURRENT_POLICY = 'native-semantic-review-v2'
POLICIES=(POLICY,CURRENT_POLICY)
OBSERVATIONS = {
 'kalshi': frozenset(('last_price_dollars','previous_price_dollars','previous_yes_ask_dollars',
 'previous_yes_bid_dollars','yes_bid_dollars','yes_ask_dollars','no_bid_dollars','no_ask_dollars',
 'yes_bid_size_fp','yes_ask_size_fp','volume_fp','volume_24h_fp','open_interest_fp','liquidity_dollars')),
 'polymarket_us': frozenset(('volume','volume24hr','volume1wk','volume1mo','volume1yr',
 'openInterest','liquidity','outcomePrices','bestBidQuote','bestAskQuote')),
}
ELIGIBILITY = {'kalshi':frozenset(('status',)),
 'polymarket_us':frozenset(('active','closed','archived','live','ended','period','status','ep3Status','hidden'))}

def classify(venue, key):
 if key in OBSERVATIONS[venue]:return 'mutable_observation'
 if key in ELIGIBILITY[venue]:return 'current_eligibility'
 return 'contract_terms_or_unknown'

def project(venue, value, *, event=False, policy=POLICY):
 if policy not in POLICIES:raise ValueError('unsupported_semantic_review_policy')
 if not isinstance(value,dict):raise ValueError('unsupported_identity_object')
 result=deepcopy(value)
 if policy==CURRENT_POLICY and venue=='polymarket_us':
  def modified(value):
   if 'updatedAt' in value:
    from app.dashboard.session_projection import stamp
    if not isinstance(value['updatedAt'],str):raise ValueError('invalid_source_modified_timestamp')
    if stamp(value['updatedAt']).utcoffset() is None:raise ValueError('invalid_source_modified_timestamp')
    value['updatedAt']={'observation_present':True,'type':'RFC3339'}
  def tag(value):
   if not isinstance(value,dict):raise ValueError('invalid_source_tag')
   modified(value)
   for child in value.get('subtags',[]):tag(child)
  modified(result)
  if event:
   if 'sortType' in result:
    if result['sortType'] not in ('manual','price'):raise ValueError('unreviewed_source_display_sort')
    result['sortType']={'presentation_present':True,'type':'reviewed_display_sort'}
   for value in result.get('tags',[]):tag(value)
   if isinstance(result.get('primaryTag'),dict):tag(result['primaryTag'])
 if event:result.pop('markets',None)
 # Presence is part of the contract, so unknown/missing observations do not pass.
 for k in OBSERVATIONS[venue]:
  if k in result:result[k]=mask_observation(result[k],quote=k in ('bestBidQuote','bestAskQuote'))
 for k in ELIGIBILITY[venue]:
  if k in result:result[k]={'eligibility_present':True,'type':type(result[k]).__name__}
 if venue=='polymarket_us' and not event:
  for side in result.get('marketSides',[]):
   for k in ('price','quote'):
    if k in side:side[k]=mask_observation(side[k],quote=k=='quote')
 return result

def contract(venue, event, market, *, policy=POLICY):
 return dict(policy=policy,event=project(venue,event,event=True,policy=policy),market=project(venue,market,policy=policy),
             unknown_fields='review-sensitive; exact presence/type/value',missing_fields='reject differences')

def compare(venue, expected, current, *, event=False):
 reason=eligibility(venue,current,event=event)
 if reason:return False,reason
 if not valid_observations(venue,current,event=event):return False,'malformed_mutable_observation'
 if project(venue,expected,event=event)!=project(venue,current,event=event):
  return False,'changed_missing_unknown_or_conflicting_terms_require_review'
 return True,'semantic_contract_admitted'

def validate(venue, value, event, market):
 if value!=contract(venue,event,market,policy=value.get('policy')):raise ValueError('Semantic review contract differs from reviewed source evidence')


def eligibility(venue, value, *, event=False):
 if venue=='kalshi':
  if not event and value.get('status')!='active':return 'unsupported_current_eligibility'
 else:
  if value.get('active') is not True or value.get('closed') is not False or value.get('archived') is not False:return 'missing_or_closed_current_eligibility'
  if value.get('hidden') is not False:return 'unknown_or_hidden_current_eligibility'
  if event:
   if value.get('period')!='NS' or value.get('live',False) is not False or value.get('ended',False) is not False:return 'unsupported_current_phase'
  elif value.get('status')!='MARKET_STATUS_OPEN' or value.get('ep3Status')!='OPEN':return 'unsupported_current_eligibility'
 return None

def matches(venue, policy, event, market):
 if policy.get('policy') not in POLICIES:return False
 if eligibility(venue,event,event=True) or eligibility(venue,market):return False
 if not valid_observations(venue,event,event=True) or not valid_observations(venue,market):return False
 try:return policy==contract(venue,event,market,policy=policy['policy'])
 except (ValueError,TypeError):return False


def mask_observation(value, *, quote=False):
 if quote and isinstance(value,dict):
  return {k:mask_observation(v) if k=='value' else deepcopy(v) for k,v in value.items()}
 return {'observation_present':True,'type':type(value).__name__}

def valid_observations(venue, value, *, event=False):
 def number(v):
  try:return not isinstance(v,bool) and Decimal(str(v)).is_finite() and Decimal(str(v))>=0
  except (InvalidOperation,ValueError):return False
 def quote(v):return isinstance(v,dict) and v.get('currency')=='USD' and number(v.get('value'))
 for k in OBSERVATIONS[venue]:
  if k not in value:continue
  v=value[k]
  if k in ('bestBidQuote','bestAskQuote'):
   if not quote(v):return False
  elif k=='outcomePrices':
   try:prices=json.loads(v)
   except (TypeError,ValueError):return False
   if not isinstance(prices,list) or not prices or not all(number(p) for p in prices):return False
  elif not number(v):return False
 if venue=='polymarket_us' and not event:
  if not isinstance(value.get('marketSides'),list):return False
  for side in value['marketSides']:
   if not isinstance(side,dict):return False
   if 'price' in side and not number(side['price']):return False
   if 'quote' in side and not quote(side['quote']):return False
 return True
