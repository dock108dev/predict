"""Ordinary dashboard payload from the shared durable projection."""
from app.dashboard.multi_game import game_calculation, rank_filter


def references_for(snapshot,game,key=None):
    side=game['sides'].get(key) if key else None
    return [r for r in snapshot['references'] if r.get('market_identity')==game['product_identity'] and
            (side is None or (r.get('participant')==side['participant'] and side['predicate'] in ('win','score')))]


def usable(r):
    if r.get('market_identity',{}).get('family') in ('spread','total') and (r.get('parser')!='score_distribution' or r.get('schema_version')!='b4-reference-1'):return False
    if r.get('market_identity',{}).get('competition') in ('NHL','MLB','NBA','NCAAF','NCAAB') and r.get('schema_version')!='b4-reference-1':return False
    return r.get('availability',r.get('state','available'))=='available' and r.get('value_kind') in ('probability','partition_distribution') and r.get('conversion_method') and r.get('value') is not None


def reference_for(snapshot,game,key):
    # Compatibility only: never silently choose between multiple usable estimates.
    refs=[r for r in references_for(snapshot,game,key) if usable(r)]
    return refs[0] if len(refs)==1 else None


def calculate(snapshot,game,q):
    point=snapshot['points'][game['id']]
    reference=None
    if q.get('reference'):
        reference=next((r for r in references_for(snapshot,game,q['contract']) if r['id']==q['reference']),None)
        if not reference:raise ValueError('Reference unavailable at this cutoff')
    probability=(reference['value'] if usable(reference) else None) if reference else q.get('probability') or None
    result=game_calculation(point,snapshot['rows_by_game'][game['id']],dict(game,assessment_at=point['at']),q.get('quantity','100'),q.get('scenario','cent'),probability,q.get('contract'))
    if reference:
        result['ev']['probability_source']=reference['role']+' · '+reference['provider_id']+' / '+reference.get('origin_id','unknown')+' · received '+reference['received_at']
        result['ev'].update(reference=reference,unconditional_ev=None,exceptional_probabilities=reference.get('exceptional_probabilities'),reference_limitation=reference.get('reason') or 'Published probability used in a normal-winner two-state what-if; no exceptional-outcome renormalization. Unconditional EV unavailable.')
    if game.get('score_reviews') and reference:
        result['ev']['reference_limitation']='Explicit completed-game partition distribution; exceptional probabilities unknown. Unconditional EV unavailable.'
    result['reference_id']=reference['id'] if reference else None
    if not game.get('score_reviews'):result['assumptions']='Normal winner comparison; fees apply only where retained source terms and the pinned source handler support them. Unknown fee, settlement or depth inputs leave net dollars unavailable. '+('Synthetic integration inputs.' if snapshot['data_mode']=='synthetic' else 'Retained observation inputs.')
    result.update(references=references_for(snapshot,game),data_mode=snapshot['data_mode'],view_mode=snapshot['view_mode'],state=snapshot['state'],frozen_cutoff=True)
    return result


def dashboard(snapshot,q,assumptions):
    items=[];sid=snapshot['session_id'];view=q.get('view','arb')
    if view=='research':return [] # Retrospective research remains on its original saved packages.
    for game in snapshot['games']:
        r=calculate(snapshot,game,{k:v for k,v in q.items() if k!='reference'});point=snapshot['points'][game['id']]
        common=dict(game_id=game['id'],game_title=game['title'],start=game['scheduled_start'],session=sid+'~'+game['id'],hash=sid,cutoff=point['id'],at=point['at'],historical=snapshot['view_mode']!='current',references=references_for(snapshot,game),market_identity=game['product_identity'])
        if view=='arb':
            for c in r['candidates']:
                venues=sorted({l['venue'] for l in c['legs']})
                items.append(dict({**common,**c},id=game['id']+'~'+c['id'],candidate=c['id'],venues=venues,venue_pair='+'.join(venues),assumption=r['assumptions']))
        else:
            for key in game['sides']:
                manual=assumptions.get(game['id']+'~'+key,{})
                refs=references_for(snapshot,game,key)
                choices=[(ref,None) for ref in refs]
                if manual:choices.append((None,manual))
                if not choices:choices=[(None,{})]
                for ref,assumption in choices:
                    probability=assumption.get('probability') if assumption else None
                    basis=assumption.get('basis') if assumption else (ref['role']+' · '+ref['provider_id']+' / '+ref.get('origin_id','unknown')+' · as of '+str(ref.get('source_at') or ref.get('model_as_of') or 'unknown')+' · '+ref.get('freshness','dated')) if ref else 'Assumption needed'
                    if probability is not None and not basis:raise ValueError('Probability needs an explicit source or basis')
                    ev=calculate(snapshot,game,dict(q,contract=key,probability=probability,reference=ref['id'] if ref else ''))['ev'];leg=ev['leg'];v=leg['venue']
                    if ref and not usable(ref):basis+=' · '+(ref.get('reason') or 'Unsupported reference value')
                    items.append(dict(**common,id=game['id']+'~'+key+('~'+ref['id'] if ref else ''),candidate='',contract=key,reference_id=ref['id'] if ref else None,legs=[leg],status=ev['status'],profit=ev['expected_profit'],return_pct=ev['return_pct'],break_even_pct=ev['break_even_pct'],probability=ev['probability'],assumption=basis,venues=[v],venue_pair=v,usable=ev['usable'],modeled_quantity=ev['modeled_quantity'],depth_limited=ev['depth_limited'],raw_gap=None))
    return rank_filter(items,q.get('sort','roi'),q.get('positive')=='true',q.get('venue',''),q.get('freshness',''),q.get('search',''))
