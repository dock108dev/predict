"""Recover explicit source roles lost before canonical team enrichment.

Only exact side team IDs/names/league under the same retained native event are
used. Never infer roles from list order, a title, a date, or a price.
"""
from collections import defaultdict
from app.storage.store import hashed
from app.adapters.polymarket_us import event_game_binding
from .admission_enrichment import resolve_team


def attach(catalog):
    markets=defaultdict(list)
    for market in catalog['markets']:
        markets[market['event_id']].append(market.get('_native') or market.get('native_metadata') or {})
    changed=set()
    for event in catalog['events']:
        raw=event.get('_native') or {};previous=event.get('native_role_evidence')
        if previous:
            # Replaced or missing witnesses must not leave this owner's old role.
            for field in ('home','away','source_participant_roles','native_role_evidence'):
                event.pop(field,None)
        league=next((t.get('league') for t in raw.get('teams',[]) if t.get('league')),None)
        try:
            bound=event_game_binding(dict(raw,markets=markets[event['id']]),league,live_bindings=True)
            teams=bound['teams']
            if bound['basis']!='embedded_full_game_side_team_ids' or {t.get('ordering') for t in teams}!={'home','away'}:continue
            roles={t['ordering']:resolve_team(t,event.get('competition'),'polymarket_us') for t in teams}
            if None in roles.values() or len(set(roles.values()))!=2:continue
            participants=event.get('participants',{})
            if set(roles.values())!=set(participants.values()):
                # A restored catalog can predate a reviewed team mapping.
                # Revalidate both original event names against the side team IDs.
                resolved={t['name']:resolve_team(t,event.get('competition'),'polymarket_us')
                          for t in raw['teams']}
                if (set(resolved)!=set(participants) or set(resolved.values())!=set(roles.values())
                        or any(v is not None and v!=resolved[k] for k,v in participants.items())):continue
                event.update(participants=resolved,identity='resolved')
            prior=event.get('source_participant_roles') or {k:event.get(k) for k in ('home','away')}
            if any(prior.get(k) not in (None,v) for k,v in roles.items()):
                event['conflicting_duplicate']=True;continue
            evidence=dict(version='native-explicit-role-1',event_id=event['id'],
                markets=bound['markets'],roles=roles,
                source_sha256=hashed([[{k:t.get(k) for k in ('id','name','league')} for t in raw.get('teams',[])],
                    [{k:m.get(k) for k in ('id','slug','sportsMarketType')} | {'sides':[{k:s.get(k) for k in ('id','marketId','teamId')} |
                      {'team':{k:(s.get('team') or {}).get(k) for k in ('id','name','league','ordering')}} for s in m.get('marketSides',[])]}
                     for m in markets[event['id']]]]))
            event.update(home=roles['home'],away=roles['away'],source_participant_roles=roles,native_role_evidence=evidence)
        except (ValueError,KeyError,TypeError):
            event['conflicting_duplicate']=True
        finally:
            if previous!=event.get('native_role_evidence'):changed.add(event['id'])
    return changed


def attach_kalshi(catalog):
    """Link source-declared role IDs through same-game structured winner labels.

    Labels resolve through the existing collision-checked institutional registry.
    This creates no global UUID alias, date inference or cross-event name match.
    """
    from .admission_enrichment import TEAM_KEYS
    witnesses=defaultdict(list)
    for market in catalog['markets']:
        if market.get('market_type')!='moneyline' or market.get('period')!='full_game':continue
        n=market.get('_native') or {};label=n.get('yes_sub_title');text=n.get('rules_primary','')
        if (n.get('strike_type')!='structured' or not isinstance(label,str)
                or not text.startswith('If '+label+' wins ') or not text.endswith(', then the market resolves to Yes.')):continue
        witnesses[market['event_id']].append((market,n,label))
    changed=set()
    for event in catalog['events']:
        previous=event.get('native_role_evidence')
        if previous and previous.get('version')=='kalshi-structured-role-1':
            for key in ('home','away','source_participant_roles','native_role_evidence'):event.pop(key,None)
        league=event.get('competition');key=TEAM_KEYS.get(league)
        choices=[]
        for fact in event.get('observed_identity_facts',[]):
            main=fact.get('main_game_event_ticker')
            if main not in (event['id'],event.get('related_game_event_id')):continue
            bindings=defaultdict(set);proof=[]
            for market,n,label in witnesses.get(main,[]):
                native_id=(n.get('custom_strike') or {}).get(key)
                if not isinstance(native_id,str):continue
                canonical=resolve_team(dict(id=native_id,name=label),league,'kalshi')
                if canonical is None:continue
                bindings[native_id].add(canonical)
                proof.append(dict(market_id=market['id'],native_id=native_id,label=label,
                    canonical=canonical,source_sha256=hashed(n)))
            ids={role:fact.get(role+'_team_id') for role in ('home','away')}
            if any(len(bindings[i])!=1 for i in ids.values()):continue
            roles={role:next(iter(bindings[i])) for role,i in ids.items()}
            if len(set(roles.values()))!=2:continue
            prior=set(event.get('participants',{}).values())-{None}
            if not prior.issubset(set(roles.values())):continue
            choices.append((roles,ids,proof))
        if choices and len({hashed(c[0]) for c in choices})==1:
            roles,ids,proof=choices[0]
            existing=event.get('source_participant_roles') or {}
            if any(existing.get(k) not in (None,v) for k,v in roles.items()):continue
            names={p['label']:p['canonical'] for p in proof if p['native_id'] in ids.values()}
            event.update(home=roles['home'],away=roles['away'],source_participant_roles=roles,
                participants=names,identity='resolved',native_role_evidence=dict(
                    version='kalshi-structured-role-1',event_id=event['id'],roles=roles,native_ids=ids,witnesses=proof))
        if previous!=event.get('native_role_evidence'):changed.add(event['id'])
    return changed


def kalshi_participant(event,native_id,label):
    """Require the exact retained structured-role witness, including its label."""
    proof=event.get('native_role_evidence') or {}
    if proof.get('version')!='kalshi-structured-role-1' or proof.get('event_id')!=event.get('id'):return None
    values={p['canonical'] for p in proof.get('witnesses',[]) if p['native_id']==native_id and p['label']==label}
    return next(iter(values)) if len(values)==1 else None
