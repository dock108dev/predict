"""Ordinary dashboard payload from the shared durable projection."""
from app.dashboard.multi_game import game_calculation, rank_filter


def reference_for(snapshot,game,key):
    side=game['sides'][key]
    for r in reversed(snapshot['references']):
        if r.get('market_identity')==game['product_identity'] and r.get('participant')==side['participant'] and side['predicate']=='win' and r.get('value_kind')=='probability' and r.get('conversion_method') and r.get('value') is not None:
            return r
    return None


def calculate(snapshot,game,q):
    point=snapshot['points'][game['id']]
    reference=None
    if q.get('reference'):
        reference=reference_for(snapshot,game,q['contract'])
        if not reference or reference['id']!=q['reference']:raise ValueError('Reference unavailable at this cutoff')
    probability=reference['value'] if reference else q.get('probability') or None
    result=game_calculation(point,snapshot['rows_by_game'][game['id']],game,q.get('quantity','100'),q.get('scenario','cent'),probability,q.get('contract'))
    if reference:result['ev']['probability_source']=reference['role']+' · '+reference['provider_id']+' · received '+reference['received_at']
    result['reference_id']=reference['id'] if reference else None
    result['assumptions']='Normal winner comparison; fees apply only where retained source terms and the pinned source handler support them. Unknown fee, settlement or depth inputs leave net dollars unavailable. '+('Synthetic integration inputs.' if snapshot['data_mode']=='synthetic' else 'Retained observation inputs.')
    result.update(references=snapshot['references'],data_mode=snapshot['data_mode'],view_mode=snapshot['view_mode'],state=snapshot['state'],frozen_cutoff=True)
    return result


def dashboard(snapshot,q,assumptions):
    items=[];sid=snapshot['session_id'];view=q.get('view','arb')
    if view=='research':return [] # Retrospective research remains on its original saved packages.
    for game in snapshot['games']:
        r=calculate(snapshot,game,q);point=snapshot['points'][game['id']]
        common=dict(game_id=game['id'],game_title=game['title'],start=game['scheduled_start'],session=sid+'~'+game['id'],hash=sid,cutoff=point['id'],at=point['at'],historical=snapshot['view_mode']!='current',references=snapshot['references'],market_identity=game['product_identity'])
        if view=='arb':
            for c in r['candidates']:
                venues=sorted({l['venue'] for l in c['legs']})
                items.append(dict({**common,**c},id=game['id']+'~'+c['id'],candidate=c['id'],venues=venues,venue_pair='+'.join(venues),assumption=r['assumptions']))
        else:
            for key in game['sides']:
                manual=assumptions.get(game['id']+'~'+key,{})
                ref=reference_for(snapshot,game,key)
                probability=manual.get('probability') if manual else ref.get('value') if ref else None
                basis=manual.get('basis') if manual else (ref['role']+' · '+ref['provider_id']+' · '+ref.get('model_as_of',ref.get('source_at',ref['received_at']))) if ref else 'Assumption needed'
                if manual.get('probability') is not None and not basis:raise ValueError('Probability needs an explicit source or basis')
                ev=calculate(snapshot,game,dict(q,contract=key,probability=probability,reference=ref['id'] if ref and not manual else ''))['ev'];leg=ev['leg'];v=leg['venue']
                items.append(dict(**common,id=game['id']+'~'+key,candidate='',contract=key,reference_id=ref['id'] if ref and not manual else None,legs=[leg],status=ev['status'],profit=ev['expected_profit'],return_pct=ev['return_pct'],break_even_pct=ev['break_even_pct'],probability=ev['probability'],assumption=basis,venues=[v],venue_pair=v,usable=ev['usable'],modeled_quantity=ev['modeled_quantity'],depth_limited=ev['depth_limited'],raw_gap=None))
    return rank_filter(items,q.get('sort','roi'),q.get('positive')=='true',q.get('venue',''),q.get('freshness',''),q.get('search',''))
