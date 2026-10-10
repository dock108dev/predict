"""Adapt the existing reviewed event/market identities into current-1 input.

Source workers supply normalized records after admission. This adapter never reads a
journal, invents a native outcome correspondence, or obtains provider data.
Native labels are retained in quotes; display selection semantics are explicit.
"""
from copy import deepcopy
from .current_contract import identity, stamp, line, binding_context, fields, event_identity


def catalog_from_normalized(envelope, records, *, reference_records=(), selected_applicability=None):
    from app.resolution.core import event_key
    from app.comparison.event_links import provider_key, current_event_key
    result=deepcopy(envelope);result['events']=[];events={};groups={};outcomes={}
    from app.comparison.current_dependencies import encoded,MAX_PROFILES,MAX_PROFILES_BYTES
    from app.comparison.source_inputs import produce
    import json
    from pathlib import Path
    source_rules=json.loads((Path(__file__).resolve().parents[1]/'fixtures/comparison-source-rules-v1.json').read_text())
    if selected_applicability is None:
        selected_applicability=json.loads((Path(__file__).resolve().parents[1]/'fixtures/comparison-selected-applicability-v1.json').read_text())
        from app.comparison.public_retail import registry
        selected_applicability=registry(selected_applicability)
    if len(encoded(source_rules))>512*1024:raise ValueError('Source rule registry capacity')
    reference_groups={}
    for item in reference_records:
        reference_groups.setdefault(encoded(item['market_identity']),[]).append(item)
    result['comparison_profiles']={}
    if not isinstance(records,list) or len(records)>16000:raise ValueError('Bounded normalized quote records required')
    for record in records:
        fields(record,{'event','market_identity','period_boundary','anchor_participant','selection','quote','orientation_evidence','verified','outcome_cardinality'},{'result_policy','event_scope','outcome_selections','comparison_source_metadata'})
        event=record['event'];market=record['market_identity'];selection=record['selection'];q=deepcopy(record['quote'])
        if record.get('event_scope') is not None:
            scope=record['event_scope']
            fields(scope,{'policy','source','native_event_id'})
            if scope['policy'] in ('aggregate-provider-event-1','aggregate-provider-event-2'):
                if record['verified'] is not True or scope['source']!='the_odds_api' or q['source']['provider']!='the_odds_api' or scope['native_event_id']!=event['id']:
                    raise ValueError('Exact aggregate source-local event required')
                key=provider_key(scope['source'],event) if scope['policy'].endswith('-2') else ['aggregate-provider-event-1',event['competition'],event['id'],event['scheduled_start'],event['home'],event['away']]
            elif scope['policy'] not in ('native-event-unverified-1','native-event-unverified-2') or record['verified'] is not False or scope['source']!=q['venue'] or scope['native_event_id']!=event['id']:
                raise ValueError('Exact source-scoped unverified event required')
            else:
                key=provider_key(scope['source'],event) if scope['policy'].endswith('-2') else ['native-event-unverified-1',scope['source'],scope['native_event_id'],event['scheduled_start'],sorted(event['participants'].values())]
        else:
            key=current_event_key(event) if market['event'][0]=='comparison-reviewed-occurrence-1' else event_key(event)
        if market['event']!=key or any(market[k]!=event[ek] for k,ek in [('sport','sport'),('competition','competition'),('season','season'),('stage','stage')]):
            raise ValueError('Normalized market/event binding conflict')
        if stamp(market['scheduled_start'])!=stamp(event['scheduled_start']):raise ValueError('Normalized schedule conflict')
        family={'moneyline':'winner','spread':'spread','total':'total'}.get(market['family'])
        if family is None:raise ValueError('Current common market adapter unsupported for this family')
        participants=[dict(id=event[role],name=next(n for n,cid in event['participants'].items() if cid==event[role]),role=role) for role in ('away','home')]
        discriminator=identity('reviewed-event',key)
        if key[0] in ('comparison-provider-occurrence-1','comparison-reviewed-occurrence-1'):
            discriminator='comparison-occurrence-1:'+discriminator
        e=dict(id='',sport=event['sport'],league=event['competition'],season=event['season'],stage=event['stage'],event_discriminator=discriminator,
               participants=participants,title=event['title'],start_at=stamp(event['scheduled_start']).isoformat(),groups=[])
        e['id']=event_identity(e)
        if e['id'] not in events:events[e['id']]=e;result['events'].append(e)
        e=events[e['id']]
        fields(selection,{'participant','predicate','signed_line','label'},{'result_interpretation'})
        # The descriptor/normalizer owns operator/equality/push and native-side
        # correspondence. Its exact meaning remains part of group identity.
        policy=record.get('result_policy',identity('normalized-outcomes',[market['outcome_set'],market['rules']]))
        cardinality=record['outcome_cardinality']
        if type(cardinality) is not int or cardinality not in (2,3):raise ValueError('Explicit supported outcome cardinality required')
        g=dict(id='',market=family,period=market['period'],period_boundary=record['period_boundary'],outcome_cardinality=cardinality,line=line(market['line']),anchor_participant=record['anchor_participant'],outcomes=[],result_policy=policy)
        # Keep exact normalized predicate policy in the period boundary as well;
        # this prevents same-line draw/push policies sharing a comparison group.
        g['period_boundary']+=' | '+policy
        g['id']=identity('group',[e['id'],*[g[k] for k in ('market','period','period_boundary','line','anchor_participant','outcome_cardinality')],g.get('result_policy','unspecified')])
        if g['id'] not in groups:groups[g['id']]=g;e['groups'].append(g)
        g=groups[g['id']]
        if 'outcome_selections' in record:
            values=record['outcome_selections']
            if not isinstance(values,list) or len(values)!=cardinality:raise ValueError('Complete bounded native outcome descriptors required')
            for value in values:
                fields(value,{'participant','predicate','signed_line','label'},{'result_interpretation'})
                missing=dict(id='',**deepcopy(value),quotes={},alternatives={});missing['signed_line']=line(missing['signed_line'])
                missing['id']=identity('outcome',[g['id'],missing['participant'],missing['predicate'],missing['signed_line'],missing.get('result_interpretation','normal_win')])
                if missing['id'] not in outcomes:outcomes[missing['id']]=missing;g['outcomes'].append(missing)
        o=dict(id='',**deepcopy(selection),quotes={},alternatives={});o['signed_line']=line(o['signed_line'])
        o['id']=identity('outcome',[g['id'],o['participant'],o['predicate'],o['signed_line'],o.get('result_interpretation','normal_win')])
        if o['id'] not in outcomes:outcomes[o['id']]=o;g['outcomes'].append(o)
        o=outcomes[o['id']]
        q['binding']=dict(verified=record['verified'],evidence=deepcopy(record['orientation_evidence']),selection=binding_context(e,g,o))
        if q.get('sharp_reference') is not None:q['sharp_reference']['selection_digest']=identity('binding',q['binding']['selection'])
        proposal=produce(record,dict(event=e,group=g,outcome=o,quote=q,source_rules=source_rules,
            selected_applicability=selected_applicability,
            reference_records=reference_groups.get(encoded(record['market_identity']),[])),at=stamp(result['clock_at']))
        combined=dict(result['comparison_profiles'],**proposal['profiles'])
        if len(combined)<=MAX_PROFILES and len(encoded(combined))<=MAX_PROFILES_BYTES:
            result['comparison_profiles']=combined
            q['comparison_input_refs']=proposal['comparison_input_refs']
        else:
            q['comparison_input_refs']=dict(proposal['comparison_input_refs'],refs={k:None for k in proposal['comparison_input_refs']['refs']})
            for status in proposal['gaps'].values():
                if status['status']=='available_and_bound':status.update(status='available_but_unbound',reason='comparison_profile_capacity')
        q['comparison_input_status']=proposal['gaps']
        v=q['venue']
        if v in o['quotes']:o['alternatives'].setdefault(v,[]).append(q)
        else:o['quotes'][v]=q
    from app.collection.current_comparison_inputs import attach
    result['comparison_profiles']=attach(result,reference_records=reference_records,selected_applicability=selected_applicability)
    return result
