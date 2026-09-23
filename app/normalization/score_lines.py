"""Explicit retained score-predicate reviews; no discovery or inferred native terms."""
from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from hashlib import sha256
import json
from app.normalization import nba,ncaab,nfl_lines,ncaaf_lines,mlb_lines,nhl_lines,nfl_first_half,ncaaf_first_half,nba_first_half,ncaab_first_half,first_half
from app.reference.product import time
from app.fees.engine import number

from app.normalization import score_periods,futures

def partial(i):return first_half.scope(i) or score_periods.scope(i)

VERSION='score-lines-1'
CONFIG={'NBA':nba,'NCAAB':ncaab,'NFL':nfl_lines,'NCAAF':ncaaf_lines,'MLB':mlb_lines,'NHL':nhl_lines}
OPS={'gt','ge','lt','le','eq','ne'}

def decimal(x):
    if not isinstance(x,str):raise ValueError('Exact decimal string required')
    n=number(x)
    if not n.is_finite() or abs(n)>10000 or n*2!=(n*2).to_integral_value():raise ValueError('Only bounded integer or half-point lines supported')
    return n

def path_value(native,path):
    if not isinstance(path,list) or not path:raise ValueError('Native evidence path missing')
    for part in path:native=native[part]
    return native

def descriptor(event,d):
    if d.get("family")=="futures":return futures.descriptor(event,d)
    segment=score_periods.scope(dict(d,competition=event['competition']));h1=partial(dict(d,competition=event['competition']))
    if d.get('version')!=VERSION or d.get('period')!=(d['period'] if segment else 'first_half' if h1 else 'full_game') or d.get('unit')!=('goals' if event['competition']=='NHL' else 'runs' if event['competition']=='MLB' else 'points') or d.get('overtime')!=('excluded' if h1 else 'included'):
        raise ValueError('Reviewed full-game scoring unit and extra periods required')
    expected='three_20_minute_periods' if event['competition']=='NHL' else 'nine_scheduled_innings' if event['competition']=='MLB' else 'four_12_minute_quarters' if event['competition']=='NBA' else 'four_15_minute_quarters' if event['competition'] in ('NFL','NCAAF') else 'two_20_minute_halves'
    if h1:expected='first_20_minute_half' if event['competition']=='NCAAB' else 'first_two_12_minute_quarters' if event['competition']=='NBA' else 'first_two_15_minute_quarters'
    if segment:
        expected=d['period'];score_periods.validate_descriptor(event,d)
    if d.get('regulation')!=expected:raise ValueError('Scoring period structure conflicts with competition')
    if event['competition']=='NCAAB' and h1:ncaab_first_half.validate_descriptor(event,d)
    if event['competition']=='NBA' and h1:nba_first_half.validate_descriptor(event,d)
    if event['competition']=='NFL':(nfl_first_half if h1 else nfl_lines).validate_descriptor(event,d)
    if event['competition']=='NCAAF':(ncaaf_first_half if h1 else ncaaf_lines).validate_descriptor(event,d)
    if event['competition']=='MLB' and not segment:mlb_lines.validate_descriptor(event,d)
    if event['competition']=='NHL' and not segment:nhl_lines.validate_descriptor(event,d)
    family=d.get('family');line=Decimal(0) if h1 and family=='moneyline' else decimal(d.get('line'))
    if family=='spread' or (h1 and family=='moneyline'):
        if d.get('participant') not in (event['home'],event['away']):raise ValueError('Spread participant missing or outside game')
        threshold=-line if d['participant']==event['home'] else line
    elif family=='total':
        if d.get('participant')!='combined' or line<0:raise ValueError('Only combined nonnegative game total supported')
        threshold=line
    else:raise ValueError('Only spread and total predicates supported')
    sides=d.get('outcomes',[])
    if len(sides) not in (2,3) or len({s.get('native_id') for s in sides})!=len(sides):raise ValueError('Two distinct native outcomes required')
    for s in sides:
        if not s.get('native_id') or not s.get('native_label') or s.get('operator') not in OPS:raise ValueError('Native outcome orientation / inequality missing')
        if s.get('equality') not in ('predicate','stake_refund','fraction','unknown'):raise ValueError('Explicit equality convention required')
        if s.get('refund_fees') not in ('retained','returned','unknown'):raise ValueError('Explicit refund fee treatment required')
    for side in sides:
        if side['equality']=='fraction':
            value=side.get('equality_payout')
            if not isinstance(value,str) or not 0<=number(value)<=1:raise ValueError('Exact fractional equality payout required')
    ops={s['operator'] for s in sides}
    if ops not in ({'gt','le'},{'ge','lt'},{'gt','lt'},{'eq','ne'},{'gt','eq','lt'}):raise ValueError('Unsupported native predicate pair')
    if ops=={'gt','lt'} and any(s['equality']=='predicate' for s in sides):raise ValueError('Strict pair requires explicit push or unknown equality')
    return dict(domain='home_margin' if family in ('spread','moneyline') else 'combined_score',threshold=format(threshold,'f'))

def review(event,market,meta,source,mode):
    config=futures if market.get('market_type')=='futures' else CONFIG.get(event.get('competition'))
    if not config:raise ValueError('Score-line mapping unavailable for this competition')
    key=config.event_key(event);r=market.get('score_review',{})
    if (r.get('source'),r.get('event_id'),r.get('market_id'))!=(source,event['id'],market['id']):raise ValueError('Source-specific score-line review missing')
    raw=meta['market']['raw'];body=raw['json_text'];native=json.loads(body)
    if r.get('evidence_mode') not in ('synthetic','observation') or raw.get('kind')!=r['evidence_mode'] or (r['evidence_mode']=='synthetic' and mode!='mock'):raise ValueError('Score-line evidence mode conflict')
    if r.get('raw_sha256')!=sha256(body.encode()).hexdigest():raise ValueError('Score-line original input changed')
    if r.get('event_binding')!=key or set(r.get('event_paths',{}))!=set(config.EVENT_FIELDS):raise ValueError('Score-line event binding missing')
    for field,path in r['event_paths'].items():
        a=path_value(native,path);b=event[field]
        if field in ('scheduled_start','original_start'):a,b=time(a),time(b)
        if a!=b:raise ValueError('Score-line native event conflict: '+field)
    d=r.get('descriptor',{});canonical=descriptor(event,d)
    if (d.get('source'),d.get('event_id'),d.get('market_id'))!=(source,event['id'],market['id']) or raw.get('ref',{}).get('event_id')!=event['id'] or raw.get('ref',{}).get('market_id')!=market['id']:
        raise ValueError('Native score listing / receipt association conflict')
    # A scoped, retained annotation may describe native text/fields, but its exact
    # mapping and literals must be in the original receipt, never title heuristics.
    if path_value(native,r.get('descriptor_path'))!=d:raise ValueError('Native score predicate evidence conflict')
    if market.get('market_type')!=d['family'] or market.get('period')!=d['period'] or market.get('line')!=d['line'] or market.get('subject')!=d['participant'] or market.get('rules_revision')!=VERSION or market.get('outcome_set')!='score_partition' or (d['family']!='futures' and any(market.get(k) is not None for k in ('category','horizon'))) or (d['family']=='futures' and any(market.get(k)!=d.get(k) for k in ('category','horizon'))):raise ValueError('Projected score-line scope conflicts with native review')
    terms=r.get('terms',{})
    if nba_first_half.scope(dict(d,competition=event['competition'])):config=nba_first_half
    if ncaab_first_half.scope(dict(d,competition=event['competition'])):config=ncaab_first_half
    if score_periods.scope(dict(d,competition=event['competition'])):config=score_periods
    if set(terms)!=getattr(config,'TERM_FIELDS',{'completion','cancellation','suspension','postponement','void','corrections','settlement_fee'}) or path_value(native,r.get('terms_path'))!=terms:raise ValueError('Source-specific score settlement evidence missing')
    if first_half.scope(dict(d,competition=event['competition'])) and terms['completion']!=first_half.completion(dict(d,competition=event['competition'])):raise ValueError('First-half completion terms must explicitly bind the reviewed completed segment')
    if score_periods.scope(dict(d,competition=event['competition'])) and terms['completion']!=score_periods.completion(dict(d,competition=event['competition'])):raise ValueError('Segment completion terms conflict')
    if not terms['completion'] or terms['completion'] in ('unknown','unverified'):raise ValueError('Completed-game score definition unknown')
    sides=[]
    for s in d['outcomes']:
        if d['family']=='futures':
            label=d['participant']+' '+s['native_label'];sides.append(dict(s,participant=label,predicate='score',operator='state',threshold=None,domain='championship_states',label=label));continue
        operator=s['operator']
        if d['family'] in ('spread','moneyline') and d['participant']==event['away']:operator={'gt':'lt','ge':'le','lt':'gt','le':'ge','eq':'eq','ne':'ne'}[operator]
        label=(d['participant']+' '+d['line'] if d['family']=='spread' else d['participant']+(' '+d['period']+' winner' if score_periods.scope(dict(d,competition=event['competition'])) else ' First half winner') if d['family']=='moneyline' else 'Total '+d['line'])+' '+s['native_label']
        sides.append(dict(s,participant=label,predicate='score',operator=operator,threshold=canonical['threshold'],domain=canonical['domain'],label=label))
    if market.get('product_outcomes')!=sides:raise ValueError('Projected native score outcomes conflict')
    basis=r.get('fee_basis')
    if basis and path_value(native,r.get('fee_path'))!=basis:raise ValueError('Score-line fee evidence conflicts')
    if source not in ('kalshi','polymarket_us'):raise ValueError('Source score economics not reviewed')
    if source=='kalshi':
        series=('KXNHL' if event['competition']=='NHL' else 'KXMLB' if event['competition']=='MLB' else 'KXNBA' if event['competition']=='NBA' else 'KXNFL' if event['competition']=='NFL' else 'KXNCAAF' if event['competition']=='NCAAF' else 'KXNCAAMB')+('SPREAD' if d['family']=='spread' else 'TOTAL')
        if first_half.scope(dict(d,competition=event['competition'])):series=first_half.series(dict(d,competition=event['competition']))
        if score_periods.scope(dict(d,competition=event['competition'])) or d['family']=='futures':
            series=r.get('series_id')
            if not isinstance(series,str) or not series:raise ValueError('Explicit source-native segment series missing')
        if r.get('series_id')!=series or d.get('series_id')!=series:raise ValueError('Native line series binding conflict')
    return dict(r,canonical=canonical)

def partitions(domain,threshold):
    t=decimal(threshold);floor=t.to_integral_value(rounding=ROUND_FLOOR);ceil=t.to_integral_value(rounding=ROUND_CEILING)
    low=int(ceil-1);high=int(floor+1);out=[]
    if domain not in ('home_margin','combined_score'):raise ValueError('Unknown integer scoring domain')
    if domain=='home_margin' or low>=0:out.append(dict(id='below',lower=None if domain=='home_margin' else 0,upper=low,representative=str(low)))
    if t==floor:out.append(dict(id='equal',lower=int(t),upper=int(t),representative=str(t)))
    out.append(dict(id='above',lower=high,upper=None,representative=str(high)))
    return out

def payout(side,part):
    if side.get("domain")=="championship_states":return side["payouts"].get(part["id"])
    x=Decimal(part['representative']);t=Decimal(side['threshold'])
    if x==t:
        if side['equality']=='fraction':return side['equality_payout']
        if side['equality']=='unknown':return None
        if side['equality']=='stake_refund':return 'refund' if side['refund_fees']=='retained' else None
    return '1' if {'gt':x>t,'ge':x>=t,'lt':x<t,'le':x<=t,'eq':x==t,'ne':x!=t}[side['operator']] else '0'

def distribution(value,parts,side=None):
    ids={p['id'] for p in parts}
    if isinstance(value,str):
        if any('winners' in part for part in parts):raise ValueError('Every championship state requires explicit probability mass')
        # Scalar cover/over/under assumptions cannot hide equality probability.
        if 'equal' in ids:raise ValueError('Explicit partition distribution including equality mass required')
        p=number(value)
        if not 0<=p<=1:raise ValueError('Probability outside [0,1]')
        return {part['id']:str(p if payout(side,part)=='1' else 1-p) for part in parts}
    if not isinstance(value,dict) or set(value)!=ids:raise ValueError('Complete exact partition probability distribution required')
    nums={k:number(v) for k,v in value.items()}
    if any(not 0<=n<=1 for n in nums.values()) or sum(nums.values())!=1:raise ValueError('Partition probabilities must be in [0,1] and sum exactly to 1')
    return {k:format(v,'f') for k,v in nums.items()}


def market_partitions(identity):
    if futures.scope(identity):return futures.parts(identity)
    parts=partitions(identity['rules']['domain'],'0' if partial(identity) and identity['family']=='moneyline' else identity['line'])
    # A normally completed postseason game cannot end tied. Only the zero
    # boundary needs removal: elsewhere zero shares an interval's same payout.
    if (identity['competition']=='NFL' and identity['stage']=='postseason'
        and identity['family']=='spread' and decimal(identity['line'])==0
        and identity['rules'].get('overtime_format')==nfl_lines.OVERTIME['postseason']):
        parts=[p for p in parts if p['id']!='equal']
    if (identity['competition']=='NCAAF' and identity['family']=='spread'
        and decimal(identity['line'])==0
        and identity['rules'].get('overtime_format')==ncaaf_lines.OVERTIME
        and identity['rules'].get('tied_score')=='exceptional_not_normal_completed_game'):
        parts=[p for p in parts if p['id']!='equal']
    return parts
