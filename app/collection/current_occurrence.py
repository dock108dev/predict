"""One evidence-backed occurrence and direct-win correspondence; no acquisition."""
from copy import deepcopy
from pathlib import Path
import json
from functools import lru_cache
from datetime import datetime, timezone
from app.dashboard.session_projection import stable
from app.dashboard.current_contract import stamp
VERSION='predict-direct-win-1'
PATH=Path(__file__).resolve().parents[1]/'fixtures/current-colts-commanders-1.json'
HISTORICAL_PATH=PATH
CURRENT_PATH=PATH.with_name('current-buccaneers-cowboys-20261006.json')

def material(venue,native):
    if venue=='kalshi':
        return {k:deepcopy(native.get(k)) for k in ('ticker','event_ticker','rules_primary','rules_secondary','custom_strike','strike_type')}
    return dict(id=str(native.get('id')),sportsMarketType=native.get('sportsMarketType'),description=native.get('description'),
        gameStartTime=native.get('gameStartTime'),marketSides=sorted([dict(id=str(s.get('id')),marketId=str(s.get('marketId')),long=s.get('long'),team_id=str((s.get('team') or {}).get('id')),team_name=(s.get('team') or {}).get('name')) for s in native.get('marketSides',[])],key=lambda s:s['id']))

@lru_cache(maxsize=2)
def _load(path,signature):
    b=json.loads(Path(path).read_text())
    if b['version']!=VERSION or b['sha256']!=stable({k:v for k,v in b.items() if k!='sha256'}):raise ValueError('Occurrence evidence seal changed')
    from app.resolution.core import event_key
    event_key(b['event'])
    if not b['evidence'] or not b['original_start_evidence'] or not b['schedule_status_evidence']:raise ValueError('Occurrence provenance missing')
    return b

def load():
    path=PATH
    if path==HISTORICAL_PATH:
        s=CURRENT_PATH.stat();current=_load(str(CURRENT_PATH),(s.st_mtime_ns,s.st_size))
        if stamp(current['applicability']['start'])<=datetime.now(timezone.utc)<=stamp(current['applicability']['end']):
            return deepcopy(current)
    s=path.stat();return deepcopy(_load(str(path),(s.st_mtime_ns,s.st_size)))

def annotate(cat,venue):
    """Revalidate each catalog generation; invalid target retains local exclusion."""
    b=load();target=b['sources'][venue];expected=b['event']
    applicable=stamp(b['applicability']['start'])<=datetime.now(timezone.utc)<=stamp(b['applicability']['end'])
    for market in cat['markets']:
        market.pop('direct_win_binding',None)
    for event in cat['events']:
        if event.get('current_occurrence_binding') and event['id']!=target['event_id']:
            for key in ('game_id','original_start','schedule_status','current_occurrence_binding'):
                event.pop(key,None)
    for event in cat['events']:
        if event['id']!=target['event_id']:continue
        # Never retain prior enrichment on a changed observation.
        for key in ('game_id','original_start','schedule_status','current_occurrence_binding'):
            old=event.pop(key,None)
            if old is not None and key in expected and old!=expected[key]:event['occurrence_conflict']=True
        native=event.get('_native') or event.get('native_metadata') or {}
        valid=applicable and not event.get('occurrence_conflict') and not event.get('conflicting_duplicate')
        valid=valid and set(event.get('participants',{}).values())=={expected['home'],expected['away']}
        valid=valid and stamp(event['scheduled_start'])==stamp(expected['scheduled_start'])
        valid=valid and all(event.get(k) in (None,expected[k]) for k in ('season','stage','home','away'))
        roles=event.get('source_participant_roles',{})
        valid=valid and all(roles.get(k) in (None,expected[k]) for k in ('home','away'))
        if venue=='polymarket_us':
            valid=valid and str(native.get('id'))==target['event_id'] and str(native.get('gameId'))==target['game_id']
            if target.get('shared_game_id'):
                valid=valid and native.get('sportradarGameId')==target['shared_game_id']
                valid=valid and native.get('active') is True and native.get('closed') is False and native.get('period')=='NS'
            valid=valid and native.get('rescheduledFromGameId') in (None,0,'0') and native.get('originalStartTime') in (None,expected['original_start'])
            valid=valid and all(native.get(k) is None or stamp(native[k])==stamp(expected['scheduled_start']) for k in ('startDate','startTime'))
        else:
            facts=event.get('observed_identity_facts',[])
            valid=valid and any(all(f.get(k)==v for k,v in target['milestone'].items()) for f in facts)
        markets=[m for m in cat['markets'] if m['event_id']==event['id'] and m['id'] in target['markets']]
        for market in markets:
            market.pop('direct_win_binding',None)
            raw=market.get('_native') or market.get('native_metadata') or {}
            m=target['markets'][market['id']]
            binding=market.get('v1_raw_binding',{})
            good=valid and stable(material(venue,raw))==m['material_sha256']
            if target.get('shared_game_id'):
                good=good and raw.get('active') is True and raw.get('closed') is False
            good=good and binding.get('sha256')==stable({k:v for k,v in binding.items() if k!='sha256'}) and binding.get('status')=='BOUND_RAW_PREDICATE'
            good=good and binding.get('identity',{}).get('family')=='moneyline' and binding['identity']['period']=='full_game'
            if good:market['direct_win_binding']=dict(version=VERSION,sha256=b['sha256'],outcomes=m['outcomes'])
        if valid:
            event.update({k:expected[k] for k in ('game_id','original_start','schedule_status','season','stage','home','away')})
            event['current_occurrence_binding']=b['sha256']
    return cat

def direct(record,market,native,selection):
    """Selection correspondence never maps a Kalshi NO to the opposing YES."""
    proof=market.get('direct_win_binding')
    if not proof or proof['sha256']!=load()['sha256']:return False
    expected=proof['outcomes'].get(native)
    return expected is not None and expected['predicate']=='win' and selection['predicate']=='win' and expected['participant']==selection['participant']
