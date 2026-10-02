"""Retained-only review admission. No requests, clocks, credentials or learned aliases."""
from copy import deepcopy
from pathlib import Path
import json,re
from datetime import timedelta
from decimal import Decimal
from collections import Counter
from app.dashboard.session_projection import stable,stamp
from app.dashboard.native_reviews import validate,DIRECTORY
from app.normalization.native_registry import native_registry
from app.opportunities.board import assess
from app.settlement import compare_profiles
from app.dashboard.native_review_assessment import retained_terms
OUT=Path('evidence/native-retained-coverage-20260930-v1');reg=native_registry()
index=json.loads((DIRECTORY/'index.json').read_text());ledger=[];admitted=[];sealed_sessions=set(index['historical_sessions'])
inputs=[json.loads(file.read_text()) for file in sorted((OUT/'sessions').glob('*.json'))]
for acquisition in json.loads((OUT/'standalone-discovery.json').read_text()):
 if not any(a['market_ids'] for a in acquisition['associations']):continue
 receipts=[p for p in acquisition['receipts'] if not p['exclusion']]
 inputs.append(dict(session_id='discovery-'+acquisition['journal_sha256'][:24],folder=acquisition['path'],acquisition_only=True,derived_inventory=acquisition['catalogs'],selected_metadata=[],observations={},receipts=receipts,start=min(p['received_at'] for p in receipts),end=max(p['received_at'] for p in receipts)))
for original in inputs:
 sid=original['session_id'];record_names=[]
 timelines=original.get('metadata_timeline',{})
 boundaries=sorted({z['observed_at'] for seq in timelines.values() for z in seq[1:]})
 ends=[(stamp(t)-timedelta(microseconds=1)).isoformat() for t in boundaries]+[original['end']]
 starts=[original['start']]+boundaries
 for revision,(window_start,window_end) in enumerate(zip(starts,ends),1):
  x=deepcopy(original);x['end']=window_end;cats=x['derived_inventory'];selected={tuple(a['key']):a['row'] for a in x['selected_metadata']}
  for v,c in cats.items():
   for m in c['markets']:
    sequence=timelines.get('|'.join((v,m['event_id'],m['id'])),[])
    observations=[z for z in sequence if stamp(z['observed_at'])<=stamp(window_end)]
    if observations:
     z=observations[-1];m['base_native_metadata_sha256']=stable(m['native_metadata']);m['native_metadata']=z['native_metadata'];m['terms']={k:z['native_metadata'][k] for k in ('description','rules_primary','rules_secondary') if z['native_metadata'].get(k)}
     receipt=next((r for r in original['receipts'] if r['source']==v and r['body_sha256']==z['body_sha256'] and not r['exclusion']),None)
     if receipt:m['provenance']=[{k:receipt[k] for k in ('path','params','received_at','body_sha256')}]
     else:m['exclusion']='selected_metadata_missing_complete_response_receipt'
  for ke in cats['kalshi']['events']:
   us=[e for e in cats['polymarket_us']['events'] if ke.get('canonical_key') and e.get('canonical_key')==ke['canonical_key'] and e['identity']=='resolved']
   if ke['identity']!='resolved' or len(us)!=1:continue
   ue=us[0];competition=ke['competition'];km=[m for m in cats['kalshi']['markets'] if m['event_id']==ke['id']];um=[m for m in cats['polymarket_us']['markets'] if m['event_id']==ue['id']]
   association=dict(session_id=sid,event=ke['canonical_key'],competition=competition,events=dict(kalshi=ke['id'],polymarket_us=ue['id']),reviews=[],exclusions=[])
   if not km:association['exclusions'].append('Kalshi event summary only; selected-event market structure, primary orientation and outcomes missing')
   if not um:association['exclusions'].append('US event only; native market and outcome evidence missing')
   for k in km:
    for u in um:
     target=dict(kalshi=k['id'],polymarket_us=u['id']);reason=None
     try:
      if any(e['exclusion'] for e in (ke,ue)) or any(m['exclusion'] for m in (k,u)):raise ValueError('Excluded normalized native event or market: '+str([e['exclusion'] for e in (ke,ue)]+[m['exclusion'] for m in (k,u)]))
      if any(m['market_type']!='moneyline' or m['period']!='full_game' or m.get('line') is not None for m in (k,u)):raise ValueError('No retained review of this market scoring/state domain')
      names={i:reg.entities[i]['name'] for i in ke['canonical_key'][1]}
      kn=k['native_metadata'];un=u['native_metadata']
      if Decimal(kn.get('notional_value_dollars','0'))!=1:raise ValueError('Native fixed dollar contract payout denomination missing or unsupported')
      if kn.get('market_type')!='binary' or {s['id'] for s in k['sides']}!={'yes','no'}:raise ValueError('Kalshi binary YES/NO structure missing')
      match=re.fullmatch(r'If (.+?) wins .+?, then the market resolves to Yes\.',kn.get('rules_primary',''))
      if not match:raise ValueError('Explicit Kalshi primary-rule winner predicate missing')
      strike=kn.get('custom_strike') or {};native_team=next(iter(strike.values())) if len(strike)==1 else None
      resolved=reg.resolve('team',match[1],league=competition,venue='kalshi',environment='production',native_id=native_team)
      if resolved.status!='resolved' or resolved.canonical_id not in names:raise ValueError('Kalshi rule winner has no unique league-scoped canonical participant')
      winner=names[resolved.canonical_id];other=next(n for n in names.values() if n!=winner)
      ko={'yes':dict(participant=winner,predicate='win',normal_winner=winner,native_label='YES'),'no':dict(participant=winner,predicate='not_win',normal_winner=other,native_label='NO')}
      sides=un.get('marketSides',[])
      if len(sides)!=2 or {s.get('long') for s in sides}!={True,False} or len({str(s.get('id')) for s in sides})!=2:raise ValueError('US two-sided Long/Short structure missing')
      uo={};uevidence=[]
      for side in sides:
       team=side.get('team') or {};tid=side.get('teamId')
       if tid is None or str(tid)!=str(team.get('id')) or str(side.get('marketId'))!=u['id']:raise ValueError('US side/market/team nested IDs disagree')
       rr=reg.resolve('team',team.get('name'),league=competition,venue='polymarket_us',environment='production',native_id=tid)
       if rr.status!='resolved' or rr.canonical_id not in names:raise ValueError('US native side team unresolved/conflicting with event participants')
       name=names[rr.canonical_id];direction='long' if side['long'] else 'short'
       uo[str(side['id'])]=dict(participant=name,predicate='win',normal_winner=name,native_direction=direction,native_label=direction.title())
       uevidence.append(dict(outcome_id=str(side['id']),team_id=str(tid),team_name=team['name'],canonical_id=rr.canonical_id,role=direction,resolution_provenance=list(rr.provenance)))
      if {o['participant'] for o in uo.values()}!=set(names.values()):raise ValueError('US sides do not cover the canonical event')
      from app.adapters.polymarket_us import FULL_GAME_TYPES
      if un.get('marketType')!='moneyline':raise ValueError('Native US market structure is not a moneyline')
      if un.get('sportsMarketType')!=FULL_GAME_TYPES.get({'NFL':'nfl','NCAAF':'cfb','MLB':'mlb','NHL':'nhl'}.get(competition)):raise ValueError('Native US market type differs from full-game winner structure')
      if not un.get('description'):raise ValueError('US exact native terms missing')
      sources={}
      for v,e,m,outcomes,orientation in [('kalshi',ke,k,ko,dict(basis='Explicit native primary rule winner with league-scoped alias; YES win, NO complement',rules_primary=kn['rules_primary'],rule_sha256=stable(kn['rules_primary']),canonical_winner=resolved.canonical_id,resolution_provenance=list(resolved.provenance),custom_strike=kn.get('custom_strike'))),('polymarket_us',ue,u,uo,dict(basis='Exact marketSides ID/marketId/teamId/nested team agreement and explicit Long/Short roles',sides=uevidence))]:
       provenance=[]
       for proof in m['provenance']+e['provenance']:
        proof=dict(proof,session_id=sid,session_folder=x['folder'],evidence_class='retained_native_complete_response')
        if proof not in provenance:provenance.append(proof)
       sources[v]=dict(event_id=e['id'],market_id=m['id'],native_metadata_sha256=stable(m['native_metadata']),event_metadata_sha256=stable(e['native_metadata']),metadata=m['native_metadata'],base_native_metadata_sha256=m.get('base_native_metadata_sha256',stable(m['native_metadata'])),provenance=provenance,orientation_evidence=orientation,outcomes=outcomes,catalog_evidence=dict(event=e,market=m),fee_review=dict(status='UNKNOWN',reason='Listing coefficient is evidence only; effective selected-contract fee schedule, execution/rounding/private charges not established by this capture',evidence=[dict(body_sha256=p['body_sha256'],received_at=p['received_at']) for p in m['provenance']],observed_metadata={f:m['native_metadata'][f] for f in ('feeCoefficient','minimumOrderSize','minTick','notional_value_dollars') if f in m['native_metadata']}))
      start=max(p['received_at'] for s in sources.values() for p in s['provenance']);identity=dict(sport={'hockey':'ice_hockey'}.get(ke['sport'],ke['sport']),competition=competition,family='moneyline',period='full_game',line=None,season=ke['scheduled_start'][:4],stage=None)
      assessment=dict(status='UNKNOWN',qualified=False,evidence=[dict(source=v,body_sha256=m['provenance'][0]['body_sha256'],terms=m['terms']) for v,m in [('kalshi',k),('polymarket_us',u)]],unknown=[dict(condition='Material native exceptional payouts and effective modification coverage require exact evidence')],conflicts=[])
      assessment=retained_terms(sources) or assessment
      # Reuse the existing sport-specific settlement assessor on the exact retained rows.
      rows=[selected[(v,s['event_id'],s['market_id'])] for v,s in sources.items() if (v,s['event_id'],s['market_id']) in selected and stamp(selected[(v,s['event_id'],s['market_id'])]['observed_at'])<=stamp(window_end)]
      try:
       a=assess(rows,x['end'],dict(sources=sources,product_identity=identity,assessment_at='2026-09-30T00:00:00+00:00',teams=sorted(names.values())))
       if set(a['profiles'])==set(sources):
        comparison=compare_profiles(a['profiles']['kalshi'],a['profiles']['polymarket_us']);assessment.update(comparison,profiles_detail=a['profiles']);assessment['evidence']=[a['sources']];assessment['qualified']=False
        if assessment['status'] in ('EXACT','COMPATIBLE'):assessment['status']='SUPPORTED'
      except (ValueError,KeyError,StopIteration):pass
      record=dict(schema='native-review-1',review_id='retained-'+stable([sid,target])[:24],revision=revision,evidence_mode='observation',scope='Exact retained session listings; normal winner correspondence only',event=ke['canonical_key'],participants=names,identity=identity,sources=sources,applicability=dict(status='SUPPORTED',start=max(start,window_start),end=x['end'],basis='Complete receipts in this exact immutable historical session only; no later/current availability claim'),settlement_assessment=assessment,reviewed_at='2026-09-30T00:00:00+00:00',registry_sha256=stable(json.loads(reg.to_json())),timing_assessment=dict(status='UNKNOWN',reason='Captured clocks, health and cutoff staleness assessed separately; no contemporaneous execution qualification'),execution_assessment=dict(status='UNKNOWN',reason='No trading/account/executable economics qualification'),**({'historical_acquisition_id':sid} if original.get('acquisition_only') else {'historical_session_id':sid}))
      record['sha256']=stable(record);validate(record)
      # Original WKU review remains the sealed selected interpretation of its original capture.
      if sid in sealed_sessions:continue
      name=record['review_id']+'-v'+str(revision)+'.json';(DIRECTORY/name).write_text(json.dumps(record,sort_keys=True,indent=2)+'\n');index['records'][name]=record['sha256'];record_names.append(name)
      association['reviews'].append(dict(name=name,sha256=record['sha256'],markets=target,books={v:'|'.join((v,s['event_id'],s['market_id'])) in x['observations'] for v,s in sources.items()}));admitted.append(record)
     except (ValueError,KeyError,StopIteration) as exc:association['exclusions'].append(dict(markets=target,reason=str(exc)))
   ledger.append(association)
 if record_names:index.setdefault('historical_acquisitions' if original.get('acquisition_only') else 'historical_sessions',{})[sid]=record_names
index['historical_paths']={sid:dict(folder=json.loads((OUT/'sessions'/(sid+'.json')).read_text())['folder'],product_chain=json.loads((OUT/'sessions'/(sid+'.json')).read_text())['journal_chain'],started_at=json.loads((OUT/'sessions'/(sid+'.json')).read_text())['start']) for sid in [json.loads(f.read_text())['session_id'] for f in (OUT/'sessions').glob('*.json')]}
(DIRECTORY/'index-v4.json').write_text(json.dumps(index,sort_keys=True,indent=2)+'\n')
(OUT/'associations.json').write_text(json.dumps(ledger,sort_keys=True,indent=2)+'\n')
print(json.dumps(dict(records=len(admitted),unique_events=len({stable(r['event']) for r in admitted}),by_competition=dict(Counter(r['identity']['competition'] for r in admitted)),sessions=len(index['historical_sessions'])),indent=2))
