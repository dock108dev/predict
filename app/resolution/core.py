"""Shared bounded resolution evidence. No collection, trading or settlement execution.

All records are immutable annotations of retained JSON literals. Corrections are
explicit edges, not last-write-wins. Prediction snapshots are never modified.
"""
from copy import deepcopy
from decimal import Decimal
import json
from hashlib import sha256
from app.reference.product import digest, time, number
from app.normalization.nfl_lines import event_key as nfl_event_key
from app.normalization.nba import event_key as nba_event_key
from app.normalization.ncaaf import event_key as ncaaf_event_key
from app.normalization.ncaab import event_key as ncaab_event_key
from app.normalization.registry import Registry
from app.normalization import score_periods,futures
from app.normalization.mlb import event_key as mlb_event_key
from app.normalization.nhl_lines import event_key as nhl_event_key

VERSIONS={'sporting':'nfl-sport-result-1','venue':'nfl-venue-settlement-1'}
NBA_VERSIONS={'sporting':'nba-sport-result-1','venue':'nba-venue-settlement-1'}
NCAAF_VERSIONS={'sporting':'ncaaf-sport-result-1','venue':'ncaaf-venue-settlement-1'}
NCAAB_VERSIONS={'sporting':'ncaab-sport-result-1','venue':'ncaab-venue-settlement-1'}
MLB_VERSIONS={'sporting':'mlb-sport-result-1','venue':'mlb-venue-settlement-1'}
NHL_VERSIONS={'sporting':'nhl-sport-result-1','venue':'nhl-venue-settlement-1'}

def event_key(event):
    if event.get('stage')=='championship':return futures.event_key(event)
    return {'NBA':nba_event_key,'NCAAF':ncaaf_event_key,'NCAAB':ncaab_event_key,'MLB':mlb_event_key,'NHL':nhl_event_key}.get(event.get('competition'),nfl_event_key)(event)

VENUES={'kalshi','polymarket_us','novig','prophetx'}
MAX_RECORDS=128


def record(kind,body,*,url,path,received_at,evidence_mode):
    if kind not in VERSIONS or evidence_mode not in ('synthetic','retained'):raise ValueError('Unknown resolution schema/mode')
    if not isinstance(body,str) or len(body.encode())>1024*1024 or not url:raise ValueError('Bounded original body and provenance required')
    if not isinstance(path,list) or not path or len(path)>16:raise ValueError('Explicit retained JSON path required')
    value=json.loads(body)
    for key in path:value=value[key]
    if not isinstance(value,dict):raise ValueError('Resolution payload must be an object')
    if value.get('target',{}).get('market_identity',{}).get('family')!='futures' and len(body.encode())>65536:raise ValueError('Bounded original body and provenance required')
    versions={'NBA':NBA_VERSIONS,'NCAAF':NCAAF_VERSIONS,'NCAAB':NCAAB_VERSIONS,'MLB':MLB_VERSIONS,'NHL':NHL_VERSIONS}.get(value.get('target',{}).get('market_identity',{}).get('competition'),VERSIONS)
    if value.get('target',{}).get('market_identity',{}).get('family')=='futures':versions={'sporting':'championship-sport-result-1','venue':'championship-venue-settlement-1'}
    x=dict(schema_version=versions[kind],kind=kind,payload=value,received_at=received_at,evidence_mode=evidence_mode,
           raw=dict(body=body,sha256=sha256(body.encode()).hexdigest(),url=url,path=path))
    for at in (received_at,value.get('published_at'),value.get('source_at')):
        if at is not None:time(at)
    if not isinstance(value.get('supersedes'),list) or any(not isinstance(v,str) for v in value['supersedes']):raise ValueError('Explicit correction list required')
    if len(set(value['supersedes']))!=len(value['supersedes']):raise ValueError('Duplicate correction edge')
    return dict(x,id=digest(x))


def validate(r):
    raw=r['raw']
    if record(r['kind'],raw['body'],url=raw['url'],path=raw['path'],received_at=r['received_at'],evidence_mode=r['evidence_mode'])!=r:raise ValueError('Resolution record hash/schema/literal conflict')


def emit_records(collector,records):
    """The existing collector owns ingress, acknowledgement, bounds and Stop."""
    if collector.stop_event.is_set():raise ValueError('Collector stopped')
    if not isinstance(records,list) or not 1<=len(records)<=16:raise ValueError('Import 1 to 16 retained resolution records')
    for r in records:
        validate(r)
        if collector.spec.get('mode')!='mock' and r['evidence_mode']=='synthetic':raise ValueError('Synthetic resolution in real session')
    if len(set(collector.projection.resolutions)|{r['id'] for r in records})>MAX_RECORDS:raise ValueError('Resolution record bound')
    if sum(len(json.dumps(v).encode()) for v in collector.projection.resolutions.values())+sum(len(json.dumps(r).encode()) for r in records)>8*1024*1024:raise ValueError('Resolution byte bound')
    for r in records:collector.emit('resolution',dict(type='product_resolution',resolution=r))


def target(snapshot,game,event):
    """Explicit target factory; does not infer missing reviewed event fields."""
    event_key(event)
    return dict(session_id=snapshot['session_id'],prediction_cutoff=snapshot['durable_cursor'],game_id=game['id'],market_identity=game['product_identity'],event=deepcopy(event))


def binding_error(p,snapshot,game,kind):
    t=p.get('target')
    if not isinstance(t,dict):return 'Unbound: explicit prediction target missing'
    if any(t.get(k)!=v for k,v in [('session_id',snapshot['session_id']),('prediction_cutoff',snapshot['durable_cursor']),('game_id',game['id']),('market_identity',game['product_identity'])]):return 'Unbound: exact prediction identity/cutoff conflict'
    i=game['product_identity'];e=t.get('event',{})
    if (i.get('competition'),i.get('season')) not in (('NFL','2026'),('NBA','2026-2027'),('NCAAF','2026'),('NCAAB','2026-2027'),('MLB','2026'),('NHL','2026-2027')) or i.get('family') not in ('moneyline','spread','total','futures') or (i.get('period') not in ('full_game','first_half') and not score_periods.scope(i) and not (futures.scope(i) and i.get('period')=='season')):return 'Unsupported competition, season or market scope'
    try:
        key=event_key(e)
        if time(e['scheduled_start'])!=time(game['scheduled_start']):return 'Unbound: game start conflict'
        # For legacy winner projection, require the reviewed event in every
        # original source catalog. Missing game/stage/reschedule stays unbound.
        for source,native in game['sources'].items():
            cat=next(s['catalog'] for s in snapshot['sources'] if s['source_id']==source)
            original=next(v for v in cat['events'] if v['id']==native['event_id'])
            if event_key(original)!=key:return 'Unbound: original reviewed event conflict'
        if (game.get('score_reviews') or i.get('competition') in ('NBA','NCAAF','NCAAB')) and key!=i['event']:return 'Unbound: canonical event conflict'
        if not game.get('score_reviews'):
            from app.normalization.college_registry import for_event
            registry=for_event(e);names={registry.entities[e[k]]['name'] for k in ('home','away')}
            if any(side.get('participant') not in names or side.get('predicate') not in ('win','not_win') for side in game['sides'].values()):return 'Unbound: legacy native participant/predicate conflict'
    except (ValueError,KeyError,TypeError,StopIteration,AttributeError):return 'Unbound: reviewed event evidence missing or invalid'
    if i.get('competition')=='NCAAF' and not futures.scope(i):
        from app.resolution.ncaaf import scope_error
        reason=scope_error(e)
        if reason:return reason
    if i.get('competition')=='NCAAB' and not futures.scope(i):
        from app.resolution.ncaab import scope_error
        reason=scope_error(e)
        if reason:return reason
    if p.get('period')!=i['period']:return 'Unbound: result period conflict'
    if not isinstance(p.get('source_event_id'),str) or not p['source_event_id'].strip():return 'Unbound: source event identity missing'
    if kind=='venue':
        source=p.get('source');native=p.get('native',{});side=game['sides'].get(p.get('contract'))
        if source not in VENUES or source not in game['sources'] or not side:return 'Unbound: venue/outcome missing'
        if not p['contract'].startswith(source+':') or native!={**game['sources'][source],'outcome_id':side['native_id']} or p['source_event_id']!=native['event_id']:return 'Unbound: native source/event/market/outcome conflict'
    elif not isinstance(p.get('source'),str) or not p['source'].strip():return 'Unbound: sporting source missing'
    return None


def revision_error(p,competition):
    """Explicit score/administrative revision meaning, independent of sport rules."""
    revision=p.get('revision_type')
    if revision not in ('original','score_correction','administrative_change'):
        return 'Missing or unsupported '+competition+' revision type'
    if bool(p['supersedes'])!=(revision!='original'):
        return 'Conflicting '+competition+' revision type and correction edges'
    if revision=='administrative_change' or p['status']=='administrative_change':
        if revision!='administrative_change' or p['status']!='administrative_change':
            return 'Administrative change cannot be promoted to an on-field final score'
    return None


def value_error(p,kind):
    if kind=='sporting' and futures.scope(p.get('target',{}).get('market_identity',{})):
        from app.resolution.championship import sporting_error
        return sporting_error(p)
    if kind=='sporting' and p.get('target',{}).get('market_identity',{}).get('competition') in ('MLB','NHL'):
        from app.resolution.diamond_ice import sporting_error
        return sporting_error(p)
    if kind=='sporting' and p.get('target',{}).get('market_identity',{}).get('competition')=='NCAAB':
        from app.resolution.ncaab import sporting_error
        return sporting_error(p)
    if kind=='sporting' and p.get('target',{}).get('market_identity',{}).get('competition')=='NCAAF':
        from app.resolution.ncaaf import sporting_error
        return sporting_error(p)
    if kind=='sporting' and p.get('target',{}).get('market_identity',{}).get('competition')=='NBA':
        from app.resolution.nba import sporting_error
        return sporting_error(p)
    if kind=='sporting':
        if p.get('status') not in ('pending','final','cancelled','suspended','abandoned','postponed','unknown'):return 'Unsupported sporting status'
        if p['status']=='final':
            if p.get('completion')!=('first_two_quarters_definitively_completed' if p['period']=='first_half' else 'all_regulation_and_applicable_overtime'):return 'Unsupported completion evidence'
            if any(type(p.get(k)) is not int or not 0<=p[k]<=1000 for k in ('home_score','away_score')):return 'Unsupported or missing period scores'
            if p['period']=='full_game' and p['target']['event']['stage']=='postseason' and p['home_score']==p['away_score']:return 'Unsupported tied postseason full-game final'
    else:
        if p.get('status') not in ('pending','settled','void','refund','cancelled','unknown'):return 'Unsupported venue status'
        pay=p.get('payout')
        if pay is not None:
            if not isinstance(pay,dict) or set(pay)!={'kind','value','fee_treatment'}:return 'Unsupported venue payout structure'
            if pay['kind']=='fraction':
                try:
                    if not isinstance(pay['value'],str) or not 0<=number(pay['value'])<=1:return 'Unsupported payout fraction'
                except (ValueError,ArithmeticError):return 'Unsupported payout fraction'
            elif pay['kind']=='stake_refund':
                if pay['value'] is not None:return 'Refund cannot invent a face-value payout'
            else:return 'Unsupported venue payout kind'
            if pay['fee_treatment'] not in ('retained','returned','unknown'):return 'Unsupported fee treatment'
            if p['status'] in ('pending','unknown','cancelled'):return 'Conflicting pending/cancelled status and payout'
    return None


def lineage(r):
    p=r['payload']
    return [r['kind'],p.get('source'),p.get('source_event_id'),p.get('target'),p.get('period'),p.get('native'),p.get('contract')]


def history(records,snapshot,game,as_of):
    cutoff=time(as_of);visible=[];excluded=0
    for wrapper in records:
        r=wrapper['record'];validate(r);p=r['payload'];ats=[wrapper['observed_at'],r['received_at'],p.get('published_at'),p.get('source_at')]
        if any(at is not None and time(at)>cutoff for at in ats):excluded+=1;continue
        reason=('Unbound: synthetic resolution cannot qualify a real prediction snapshot' if snapshot['data_mode']!='synthetic' and r['evidence_mode']=='synthetic' else binding_error(p,snapshot,game,r['kind']))
        if not reason and any(at is None for at in ats):reason='Unknown evidence timestamp; no inferred ordering'
        if not reason and (time(p['published_at'])>time(r['received_at']) or time(p['source_at'])>time(p['published_at']) or time(r['received_at'])>time(wrapper['observed_at'])):reason='Conflicting evidence timestamps'
        if not reason and p.get('status')=='final' and time(p['source_at'])<time(p['target']['event']['horizon_start'] if futures.scope(game['product_identity']) else p['target']['event']['scheduled_start']):reason='Final result predates scheduled start'
        reason=reason or value_error(p,r['kind'])
        visible.append(dict(id=r['id'],record=r,reason=reason,correction_state='original'))
    byid={v['id']:v for v in visible};superseded=set()
    # Edges can arrive out of order in the journal, but must prove temporal order.
    for v in visible:
        if v['reason']:continue
        r=v['record'];parents=r['payload']['supersedes'];bad=None
        for pid in parents:
            prior=byid.get(pid)
            if not prior or prior['reason'] or lineage(prior['record'])!=lineage(r):bad='Correction predecessor missing, unsupported or differently bound';break
            a=prior['record'];ap=a['payload'];p=r['payload']
            if pid==r['id'] or time(a['received_at'])>time(r['received_at']) or time(ap['published_at'])>=time(p['published_at']) or time(ap['source_at'])>time(p['source_at']):bad='Correction ordering conflict';break
        if bad:v['reason']=bad
        elif parents:v['correction_state']='corrected';superseded.update(parents)
    # Propagate invalid predecessor chains independent of journal arrival order.
    for _ in range(len(visible)):
        changed=False
        for v in visible:
            if not v['reason'] and any(pid not in byid or byid[pid]['reason'] for pid in v['record']['payload']['supersedes']):
                v['reason']='Correction predecessor unsupported';changed=True
        if not changed:break
    # Invalid descendants cannot erase predecessors; never drop evidence.
    superseded={pid for v in visible if not v['reason'] for pid in v['record']['payload']['supersedes']}
    for v in visible:
        if v['id'] in superseded:v['correction_state']='superseded'
    return visible,excluded


def group(items):
    active=[v for v in items if v['correction_state']!='superseded']
    if not active:return dict(state='missing',records=items,selected=None)
    if len(active)>1:return dict(state='conflicting',records=items,selected=None)
    v=active[0];p=v['record']['payload']
    state='unbound' if v['reason'] and v['reason'].startswith('Unbound:') else 'unsupported' if v['reason'] else 'corrected' if v['correction_state']=='corrected' else p['status']
    return dict(state=state,records=items,selected=None if v['reason'] else v['record'])


def expectation(snapshot,game,contract,sport,q):
    """Reuse existing payout functions and original hypothetical fee/depth audit."""
    absent=dict(state='unavailable',reason='No unambiguous supported final sporting result',payout=None,cashflow=None)
    r=sport.get('selected')
    if not r:return absent
    special=r['payload']['target']['event']['competition']=='MLB' and r['payload']['status']=='shortened'
    if r['payload']['status']!='final' and not special:return absent
    if special:
        venue=contract.split(':')[0]
        if game.get('score_reviews') or game.get('mlb_reviews',{}).get(venue,{}).get('terms',{}).get('shortened_game')!='official_winner':return dict(absent,reason='Shortened official score retained; this source/market completion payout is unverified')
    p=r['payload'];side=game['sides'][contract]
    if p['target']['event']['competition']=='MLB' and p.get('resume_status')=='resumed_completed':
        venue=contract.split(':')[0];terms=game.get('score_reviews',game.get('mlb_reviews',{})).get(venue,{}).get('terms',{})
        rule=terms.get('resumed_game',terms.get('suspension'))
        within=rule in ('resume_within_48_hours_original_start','resume_within_48_hours_else_venue_fair_value') and (time(p['resumed_at'])-time(p['target']['event']['original_start'])).total_seconds()<=48*3600
        if not within:return dict(absent,reason='Resumed MLB score retained; original source-specific resumption window/payout rule unverified or exceeded')
    if p['target']['event']['competition']=='NHL' and p['period']=='full_game':
        from app.resolution.diamond_ice import hockey_score
        mapped=hockey_score(p);p=dict(p,home_score=mapped['home'],away_score=mapped['away'])
    from app.dashboard.product_view import calculate
    calc=calculate(snapshot,game,dict(q,contract=contract,probability='',reference=''));leg=calc['ev']['leg']
    if game.get('score_reviews'):
        from app.normalization.score_lines import payout,market_partitions
        value=0 if futures.scope(game['product_identity']) else p['home_score']-p['away_score'] if side['domain']=='home_margin' else p['home_score']+p['away_score']
        parts=[part for part in market_partitions(game['product_identity']) if part['id']==p.get('winning_state')] if futures.scope(game['product_identity']) else [part for part in market_partitions(game['product_identity']) if (part['lower'] is None or value>=part['lower']) and (part['upper'] is None or value<=part['upper'])]
        if len(parts)!=1:return dict(absent,reason='Score outside reviewed payout partitions')
        outcome=parts[0]['id'];v=payout(side,parts[0]);pay=None if v is None else dict(kind='stake_refund' if v=='refund' else 'fraction',value=None if v=='refund' else v)
    else:
        from app.settlement import payout
        event=p['target']['event']
        from app.normalization.college_registry import for_event
        reg=for_event(event)
        outcome='tie' if p['home_score']==p['away_score'] else 'winner:'+reg.entities[event['home'] if p['home_score']>p['away_score'] else event['away']]['name']
        venue=contract.split(':')[0]
        profile=calc['assessment']['profiles'].get(venue)
        if not profile:return dict(absent,reason='Source payout profile unavailable')
        pay=payout(side,outcome,profile)
        if pay['kind'] not in ('fraction','refund'):pay=None
    cf=leg['cashflows'].get(outcome)
    return dict(state='conditional' if pay else 'unavailable',reason='Rule-derived expectation only; original hypothetical size/fees/depth, not an observed settlement or trade',payout=pay,cashflow=cf if not leg['reasons'] else None,economics_reasons=leg['reasons'],sporting_record=r['id'])


def resolve(records,snapshot,game,as_of,q=None):
    visible,excluded=history(records,snapshot,game,as_of)
    # Unbound records stay visible, but cannot contaminate a correctly bound group.
    unbound=[v for v in visible if v['reason'] and v['reason'].startswith('Unbound:')]
    linked=[v for v in visible if v not in unbound]
    sport=group([v for v in linked if v['record']['kind']=='sporting'])
    venues=[]
    for contract,side in game['sides'].items():
        source=contract.split(':')[0];decision=group([v for v in linked if v['record']['kind']=='venue' and v['record']['payload'].get('contract')==contract])
        expected=expectation(snapshot,game,contract,sport,q or {})
        observed=decision['selected'];payout_value=observed['payload'].get('payout') if observed else None
        disagreement=False
        if expected['payout'] and payout_value:
            a=expected['payout'];b=payout_value
            ak='stake_refund' if a['kind']=='refund' else a['kind']
            disagreement=ak!=b['kind'] or (ak=='fraction' and number(a['value'])!=number(b['value']))
        venues.append(dict(source=source,contract=contract,label=side.get('label',side['participant']),native_id=side['native_id'],expected=expected,observed=decision,disagrees_with_rule=disagreement))
    return dict(version='championship-resolution-view-1' if futures.scope(game['product_identity']) else {'NBA':'nba-resolution-view-1','NCAAF':'ncaaf-resolution-view-1','NCAAB':'ncaab-resolution-view-1','MLB':'mlb-resolution-view-1','NHL':'nhl-resolution-view-1'}.get(game['product_identity'].get('competition'),'nfl-resolution-view-1'),as_of=as_of,prediction_cutoff=snapshot['durable_cursor'],sporting=sport,venues=venues,unbound=unbound,excluded_future_count=excluded,
        limitation='Sporting results, rule-derived expectations and venue reports are separate. No fills, account balances or realized profit are established.')
