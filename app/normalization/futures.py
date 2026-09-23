"""Exact current-season championship fields and exhaustive settlement states."""
import json
from decimal import Decimal,ROUND_DOWN
from app.reference.product import time
from app.normalization.college_registry import expanded
from app.fees.engine import number
SEASONS={'NFL':'2026','NCAAF':'2026','MLB':'2026','NBA':'2026-2027','NCAAB':'2026-2027','NHL':'2026-2027'}
EVENT_FIELDS=('competition','sport','season','stage','scheduled_start','championship_id','category','horizon','field','states','field_structure','gender','division','conference_id','horizon_start')
TERM_FIELDS={'completion','cancellation','suspension','postponement','void','corrections','settlement_fee','tie','refund','elimination','award_basis'}

def scope(i):return i.get('family')=='futures'

def event_key(e):
    if e.get('season')!=SEASONS.get(e.get('competition')):raise ValueError('Unreviewed futures competition/season')
    if e.get('category') not in ('conference_champion','league_champion') or e.get('stage')!='championship':raise ValueError('Only conference/league champion futures selected')
    if e.get('competition')=='NCAAB' and (e.get('gender'),e.get('division'))!=('men','I'):raise ValueError('Futures college basketball gender/division conflict')
    for k in ('championship_id','horizon'):
        if not isinstance(e.get(k),str) or not e[k].strip():raise ValueError('Explicit championship/horizon identity required')
    if e['category']=='conference_champion' and not e.get('conference_id','horizon_start'):raise ValueError('Exact conference identity required')
    if e['category']=='league_champion' and e.get('conference_id','horizon_start') is not None:raise ValueError('League and conference horizons conflict')
    if time(e['horizon_start'])>=time(e['scheduled_start']):raise ValueError('Championship start/deadline conflict')
    field=e.get('field');reg=expanded()
    if not isinstance(field,list) or not 2<=len(field)<=512 or len(set(field))!=len(field) or any(cid not in reg.entities or reg.entities[cid].get('league')!=e['competition'] for cid in field):raise ValueError('Explicit distinct championship field required')
    if e.get('field_structure') not in ('mutually_exclusive','overlapping'):raise ValueError('Unknown championship field structure')
    states=e.get('states')
    if not isinstance(states,list) or not 2<=len(states)<=1024 or len({v.get('id') for v in states})!=len(states):raise ValueError('Bounded distinct exhaustive state table required')
    seen=[]
    for state in states:
        winners=state.get('winners')
        if not isinstance(state.get('id'),str) or not state['id'] or not isinstance(winners,list) or len(set(winners))!=len(winners) or any(cid not in field for cid in winners):raise ValueError('Unknown championship state participant')
        if e['field_structure']=='mutually_exclusive' and len(winners)>1:raise ValueError('Shared champion conflicts with exclusive field')
        seen+=winners
    if set(seen)!=set(field):raise ValueError('Incomplete championship state field')
    return ['futures',e['competition'],e['season'],e['scheduled_start'],json.dumps({k:e[k] for k in EVENT_FIELDS},sort_keys=True,separators=(',',':'))]

def descriptor(e,d):
    event_key(e)
    if d.get('family')!='futures' or d.get('period')!='season' or d.get('line') is not None or d.get('participant') not in e['field'] or d.get('category')!=e['category'] or d.get('horizon')!=e['horizon']:raise ValueError('Futures horizon/participant conflict')
    if d.get('state_space')!='explicit_exhaustive' or not d.get('contract_document'):raise ValueError('Explicit source-backed exhaustive future state space required')
    sides=d.get('outcomes',[]);ids={v['id'] for v in e['states']}
    if len(sides)!=2 or len({s.get('native_id') for s in sides})!=2:raise ValueError('Exact native binary instrument required; field stays multi-outcome')
    for side in sides:
        if d.get('source')=='kalshi' and side.get('native_id') in ('yes','no') and side.get('role')!=('achievement' if side['native_id']=='yes' else 'not_achievement'):raise ValueError('Native YES/NO achievement orientation conflict')
        if side.get('role') not in ('achievement','not_achievement'):raise ValueError('Explicit native achievement orientation required')
        if not side.get('native_label') or set(side.get('payouts',{}))!=ids:raise ValueError('Every future state needs an explicit native payout')
        for v in side['payouts'].values():
            if v is not None and (not isinstance(v,str) or not 0<=number(v)<=1):raise ValueError('Unknown or bounded exact future fractions required')
    if {side['role'] for side in sides}!={'achievement','not_achievement'}:raise ValueError('Complementary native achievement instrument required')
    if d.get('settlement_model')=='shared_cent_floor':
        for state in e['states']:
            winners=state['winners']
            expected=None if not winners else (Decimal(1)/len(winners)).quantize(Decimal('.01'),rounding=ROUND_DOWN) if d['participant'] in winners else Decimal(0)
            for side in sides:
                want=None if expected is None else expected if side['role']=='achievement' else 1-expected
                got=side['payouts'][state['id']]
                if (got is None)!=(want is None) or got is not None and number(got)!=want:raise ValueError('Shared championship payout differs from reviewed cent-floor allocation')
    elif d.get('settlement_model')!='explicit_source_state_table':raise ValueError('Unknown championship payout model')
    return dict(domain='championship_states',threshold=None)

def parts(identity):return [dict(id=s['id'],winners=s['winners']) for s in identity['rules']['states']]
