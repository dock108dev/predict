"""Adapt the existing reviewed event/market identities into current-1 input.

Source workers supply normalized records after admission. This adapter never reads a
journal, invents a native outcome correspondence, or obtains provider data.
Native labels are retained in quotes; display selection semantics are explicit.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from .current_contract import identity, stamp, line, binding_context, fields, event_identity


@dataclass(frozen=True)
class NormalizationRegistries:
    """One read context's validated registry snapshot, stored as immutable bytes.

    Each occurrence receives detached dictionaries. The selected retail/event
    registry still passes its existing validator once when this context loads;
    quote-specific applicability remains with the ordinary producer on every use.
    """
    source_rules: bytes
    selected_applicability: bytes
    binding: str

    @classmethod
    def load(cls):
        from app.comparison.current_dependencies import digest, encoded
        from app.comparison.public_retail import registry
        root = Path(__file__).resolve().parents[1] / 'fixtures'
        rules = json.loads((root / 'comparison-source-rules-v1.json').read_text())
        selected = registry(json.loads((root / 'comparison-selected-applicability-v1.json').read_text()))
        raw_rules = encoded(rules)
        if len(raw_rules) > 512 * 1024:
            raise ValueError('Source rule registry capacity')
        raw_selected = encoded(selected)
        return cls(raw_rules, raw_selected, digest(dict(source_rules=rules, selected_applicability=selected)))

    def detached(self):
        return json.loads(self.source_rules), json.loads(self.selected_applicability)


def catalog_from_normalized(envelope, records, *, reference_records=(), selected_applicability=None, occurrence_resolver=None, include_profiles=True, source_rules=None, registries=None):
    from app.resolution.core import event_key
    from app.comparison.event_links import provider_key, current_event_key, ordinary_event_key
    if occurrence_resolver is not None:
        records=occurrence_resolver.resolve(records,clock=envelope['clock_at'])
    result=deepcopy(envelope);result['events']=[];events={};groups={};outcomes={}
    from app.comparison.current_dependencies import encoded
    from app.comparison.shared_templates import ProfilePool, ProfileFactory
    from app.comparison.source_inputs import produce
    if registries is not None:
        if not isinstance(registries, NormalizationRegistries) or source_rules is not None or selected_applicability is not None:
            raise ValueError('Exact normalization registry snapshot required')
        source_rules, selected_applicability = registries.detached()
    if source_rules is None:
        source_rules=json.loads((Path(__file__).resolve().parents[1]/'fixtures/comparison-source-rules-v1.json').read_text())
    if selected_applicability is None:
        selected_applicability=json.loads((Path(__file__).resolve().parents[1]/'fixtures/comparison-selected-applicability-v1.json').read_text())
        from app.comparison.public_retail import registry
        selected_applicability=registry(selected_applicability)
    if len(encoded(source_rules))>512*1024:raise ValueError('Source rule registry capacity')
    reference_groups={}
    for item in reference_records:
        reference_groups.setdefault(encoded(item['market_identity']),[]).append(item)
    pool=ProfilePool();profile_factory=ProfileFactory()
    if not isinstance(records,list) or len(records)>16000:raise ValueError('Bounded normalized quote records required')
    from app.comparison.projection_batches import batches
    ordered=(record for batch in batches(records,lambda r:encoded(r['market_identity']['event'])) for record in batch)
    for record in ordered:
        # Reattach supported retained metadata to existing SQL rows as well as
        # new collection. This does not need another provider observation.
        from app.comparison.native_scoring_scope import attach
        record=attach(record,at=envelope['clock_at'])
        fields(record,{'event','market_identity','period_boundary','anchor_participant','selection','quote','orientation_evidence','verified','outcome_cardinality'},{'result_policy','event_scope','outcome_selections','comparison_source_metadata','comparison_scope'})
        event=record['event'];market=record['market_identity'];selection=record['selection'];q=deepcopy(record['quote'])
        if record.get('event_scope') is not None:
            scope=record['event_scope']
            fields(scope,{'policy','source','native_event_id'})
            if scope['policy'] in ('aggregate-provider-event-1','aggregate-provider-event-2'):
                if record['verified'] is not True or scope['source']!='the_odds_api' or q['source']['provider']!='the_odds_api' or scope['native_event_id']!=event['id']:
                    raise ValueError('Exact aggregate source-local event required')
                key=provider_key(scope['source'],event) if scope['policy'].endswith('-2') else ['aggregate-provider-event-1',event['competition'],event['id'],event['scheduled_start'],event['home'],event['away']]
            elif scope['policy']=='native-provider-event-1':
                if record['verified'] is not True or scope['source']!=q['venue'] or q['source']['provider']!=scope['source'] or scope['native_event_id']!=event['id']:
                    raise ValueError('Exact native source-local verified event required')
                key=provider_key(scope['source'],event)
            elif scope['policy'] not in ('native-event-unverified-1','native-event-unverified-2') or record['verified'] is not False or scope['source']!=q['venue'] or scope['native_event_id']!=event['id']:
                raise ValueError('Exact source-scoped unverified event required')
            else:
                key=provider_key(scope['source'],event) if scope['policy'].endswith('-2') else ['native-event-unverified-1',scope['source'],scope['native_event_id'],event['scheduled_start'],sorted(event['participants'].values())]
        else:
            key=(ordinary_event_key(event) if market['event'][0]=='predict-occurrence-1' else
                 current_event_key(event) if market['event'][0]=='comparison-reviewed-occurrence-1' else event_key(event))
        admission=record.get('comparison_source_metadata',{}).get('comparison_admission',{})
        display_context=(key[0]=='comparison-provider-occurrence-1' and record['verified'] is False
            and admission.get('supported') is False and admission.get('reason')=='comparison_context_missing')
        # SQL shares current event metadata across retained instruments. A later
        # source witness may fill missing context before every old book rebinds.
        # Display that event without promoting the old contract or its refusal;
        # populated contradictions still fail and originals remain in the audit.
        context_conflict=any(market.get(k)!=event.get(k) and not (
            display_context and market.get(k) in (None,'','unknown','unverified')
            and k in admission.get('missing_fields',[])) for k in ('season','stage'))
        if market['event']!=key or any(market[k]!=event[ek] for k,ek in [('sport','sport'),('competition','competition')]) or context_conflict:
            raise ValueError('Normalized market/event binding conflict')
        if any(event.get(k) is None for k in ('season','stage')) and not (
                key[0]=='comparison-provider-occurrence-1' and record['verified'] is False):
            raise ValueError('Missing comparison context requires an unverified source-local observation')
        if event.get('schedule_conflict') or stamp(market['scheduled_start'])!=stamp(event['scheduled_start']):raise ValueError('Normalized schedule conflict')
        family={'moneyline':'winner','team_binary':'winner','spread':'spread','total':'total'}.get(market['family'])
        if family is None:raise ValueError('Current common market adapter unsupported for this family')
        participants=[dict(id=event[role],name=next(n for n,cid in event['participants'].items() if cid==event[role]),role=role) for role in ('away','home')]
        discriminator=identity('reviewed-event',key)
        if key[0] in ('comparison-provider-occurrence-1','comparison-reviewed-occurrence-1','predict-occurrence-1'):
            discriminator='comparison-occurrence-1:'+discriminator
        if key[0]=='comparison-provider-occurrence-1':
            # Provider identity is durable while optional comparison context is
            # learned. A later supported cross-source join has its own identity.
            discriminator='comparison-provider-occurrence-1:'+identity('provider-event',key)
        if key[0]=='predict-occurrence-1':discriminator='predict-occurrence-1:'+identity('occurrence',key)
        e=dict(id='',sport=event['sport'],league=event['competition'],season=event.get('season'),stage=event.get('stage'),event_discriminator=discriminator,
               participants=participants,title=event['title'],start_at=stamp(event['scheduled_start']).isoformat(),groups=[])
        e['id']=event_identity(e)
        if e['id'] not in events:events[e['id']]=e;result['events'].append(e)
        e=events[e['id']]
        # Metadata joins can contain source-specific advertised starts. The
        # earliest supported start closes current pregame eligibility; every
        # original schedule remains in its occurrence audit and Details frame.
        e['start_at']=min(stamp(e['start_at']),stamp(event['scheduled_start'])).isoformat()
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
        matched=q.get('occurrence_match',{}).get('status')=='matched'
        overtime=(record.get('comparison_scope') or dict(overtime='unknown'))['overtime']
        if matched:g['period_boundary']+=' | Scoring overtime: '+overtime
        g['id']=identity('group',[e['id'],*[g[k] for k in ('market','period','period_boundary','line','anchor_participant','outcome_cardinality')],g.get('result_policy','unspecified')])
        if matched:
            from app.comparison.domain import display_group_key
            display_key=display_group_key(e['id'],market['family'],market['period'],overtime,market['line'])
            g['display_group']=dict(version='predict-display-group-1',id=identity('display-group',display_key),
                occurrence_id=e['id'],market=family,period=market['period'],overtime=overtime,line=line(market['line']))
        if 'occurrence_match' in q:
            from app.comparison.event_links import digest
            metadata=record.get('comparison_source_metadata',{})
            contract=dict(version='predict-native-contract-1',source=deepcopy(q['source']),
                predicate=deepcopy(q['occurrence_match']['original_selection']),
                wording=deepcopy(metadata.get('original_wording',{'selection':selection['label'],'rule_note':q['rule_note']})),
                result_policy=q.get('native_predicate',{}).get('original_result_policy',policy),
                scope=dict(period=market['period'],overtime=overtime),
                material_sha256=metadata.get('material_sha256',q['provenance'].get('sha256')))
            if 'same_outcome' in metadata:
                contract['same_outcome']=deepcopy(metadata['same_outcome'])
            if 'scoring_scope' in metadata:
                contract['scope_evidence']=deepcopy(metadata['scoring_scope'])
            contract['id']='native-contract:'+digest(contract)
            q['native_contract']=contract
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
        if include_profiles:
            proposal=produce(record,dict(event=e,group=g,outcome=o,quote=q,source_rules=source_rules,profile_factory=profile_factory,
                selected_applicability=selected_applicability,
                reference_records=reference_groups.get(encoded(record['market_identity']),[])),at=stamp(result['clock_at']))
            q['comparison_input_refs']=proposal['comparison_input_refs']
            # Admission is facet-local: one exhausted/absent facet cannot erase
            # independently bound policy, fee, payout or original price observations.
            for kind,key in q['comparison_input_refs']['refs'].items():
                if key is not None and not pool.add(key,proposal['profiles'][key]):
                    q['comparison_input_refs']['refs'][kind]=None
                    proposal['gaps'][kind].update(status='available_but_unbound',
                        reason='comparison_representation_capacity_deferred')
            q['comparison_input_status']=proposal['gaps']
        v=q['venue']
        if v in o['quotes']:o['alternatives'].setdefault(v,[]).append(q)
        else:o['quotes'][v]=q
    result['comparison_profiles']=pool.finish()
    if include_profiles:
        from app.collection.current_comparison_inputs import attach
        result['comparison_profiles']=attach(result,reference_records=reference_records,selected_applicability=selected_applicability)
    return result
