"""Scoped content selection, separate from actual-net eligibility.

Recipes travel in fact-level status records. Original profile references remain
intact; disclosed models never promote unknown actual values to known facts."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from .current_dependencies import digest, encoded, instant, public_tree, references
from .estimated_templates import _contract
from .source_inputs import observation, selected_binding, _facet

VERSION = 'predict-estimate-content-1'
STATES = ('home_win', 'away_win', 'tie', 'terminal_noncompletion')


@lru_cache(maxsize=1)
def _catalog():
    value = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/estimated-content-v1.json').read_text())
    if value['sha256'] != digest({k:v for k,v in value.items() if k != 'sha256'}):
        raise ValueError('estimate_catalog_digest_conflict')
    for row in value['templates']:
        if row['id'] != digest({k:v for k,v in row.items() if k != 'id'}):
            raise ValueError('estimate_template_digest_conflict')
    public_tree(value)
    return value


def catalog():
    return deepcopy(_catalog())


def native_contract(q, group):
    """Exact admitted source-local economics; occurrence matching adds no authority."""
    if q.get('native_contract') is not None:
        value = q['native_contract']
    else:
        value = dict(version='predict-native-contract-1', source=deepcopy(q['source']),
            predicate=deepcopy(q['binding']['selection']),
            wording=dict(rule_note=q['rule_note']), result_policy=group.get('result_policy','unspecified'),
            scope=dict(period=group['period'], overtime='unknown'),
            material_sha256=q['provenance']['sha256'])
        value['id'] = 'native-contract:' + digest(value)
    source=q['source']
    return _contract(value, [q['venue'],*[source[k] for k in
        ('native_event_id','native_market_id','native_outcome_id','native_side')]])


def _active(value, at):
    for name in ('effective_from','model_effective_from'):
        if value.get(name) is not None and at < instant(value[name]):return False
    for name in ('expires_at','effective_to','effective_until'):
        if value.get(name) is not None and at >= instant(value[name]):return False
    return True


def attach(result, record, context, *, at):
    """Attach an explicit modeled recipe without replacing any original profile.

    Selected facets override each component independently. A selected conflict or
    expiry blocks that facet; another healthy facet still gets its own recipe.
    """
    q=context['quote'];g=context['group'];e=context['event'];o=context['outcome']
    if q['venue'] not in ('kalshi','polymarket_us','novig','prophetx'):return
    if e['league'] != 'NFL' or g['market'] != 'winner' or g['period'] != 'full_game':return
    metadata=record.get('comparison_source_metadata',{})
    templates=[t for t in _catalog()['templates'] if t['venue']==q['venue']]
    template=templates[0]
    # The source producer and its legacy readers may qualify older retained
    # instants. Successor content applies only at its declared model boundary.
    if not _active(template,at):return
    try:contract=native_contract(q,g)
    except (ValueError,KeyError,TypeError):
        for kind in ('fee','payout'):
            result['gaps'].setdefault(kind,dict(status='absent',reason=kind+'_inputs_absent'))['estimate_unresolved_reason']='estimate_native_material_unresolved'
        return
    from .source_inputs import _phase
    phase=_phase(record,metadata,at)
    scoped_overtime=metadata.get('overtime',contract['scope']['overtime'])
    reasons=[]
    if not _active(metadata,at):reasons.append('estimate_source_metadata_expired_or_not_effective')
    from .source_inputs import _selection
    from .domain import Scope
    try:_selection(record,context,Scope('full_game','included','conditional_completed_result'))
    except (ValueError,KeyError,TypeError):reasons.append('estimate_exact_source_attachment_unresolved')
    if not q['binding']['verified']:reasons.append('estimate_native_orientation_unresolved')
    if phase!='pregame':reasons.append('estimate_pregame_scope_unresolved')
    if scoped_overtime=='excluded':reasons.append('estimate_overtime_scope_conflict')
    if metadata.get('native_key') is not None and metadata['native_key'] != observation(q)['native_key']:
        reasons.append('estimate_native_attachment_conflict')
    if o['participant'] not in [p['id'] for p in e['participants']] and o['predicate']!='draw':
        reasons.append('estimate_native_participant_unresolved')
    if o['predicate'] not in ('win','not_win','draw'):reasons.append('estimate_winner_predicate_unresolved')
    row,problem=selected_binding(q,context.get('selected_applicability'),at)
    for kind in ('fee','payout'):
        original=result['comparison_input_refs']['refs'][kind]
        recipe=dict(version=VERSION,kind=kind,template_ref=template['id'],template_version=template['version'],
            native_contract_id=contract['id'],native_key=observation(q)['native_key'],
            selection=deepcopy(q['binding']['selection']),home_id=next(p['id'] for p in e['participants'] if p['role']=='home'),phase=phase,
            overtime=scoped_overtime,original_profile_ref=original,
            selected_binding_version=None,selected=None,metadata={},reasons=list(reasons),
            actual_qualified=False,actual_value=None,
            applicability='named_direct_site_standalone_taker_model',expires_at=template['expires_at'])
        if problem is not None:
            recipe['reasons'].append(problem['reason'])
        elif row is not None and kind in row.get('facets',{}):
            try:
                facet=_facet(row,kind,q)
                if q['provenance']['real_source'] and row.get('material_sha256') != metadata.get('material_sha256'):
                    raise ValueError('estimate_selected_material_conflict')
                recipe.update(selected=deepcopy(facet),selected_binding_version=row['binding_version'],
                    applicability='selected_applicable_terms',expires_at=min(row['effective_until'],template['expires_at'],key=instant))
            except (ValueError,KeyError,TypeError):
                recipe['reasons'].append('estimate_selected_facet_conflict')
        if kind=='fee':
            # Caller-supplied selected source metadata remains exact; no title
            # or aggregate label may establish native API quantity scales.
            recipe['metadata']={k:deepcopy(metadata[k]) for k in
                ('series_id','kalshi_metadata','balance_precision','selected_reference_data',
                 'selected_public_retail_data','market_fee','api_regime','phase_at_match') if k in metadata}
        else:
            recipe['metadata']={k:deepcopy(metadata[k]) for k in ('tie_strike_listed','tie_outcome_listed','fair_price') if k in metadata}
        recipe['id']=digest(recipe)
        result['gaps'].setdefault(kind,dict(status='absent',reason=kind+'_inputs_absent'))['estimate_content']=recipe


def resolve_content(q, profiles, *, at, kind, _values=None):
    """Versioned consumer reads exact original shared references and selected recipe."""
    if kind not in ('fee','payout'):raise ValueError('estimate_component_kind_required')
    recipe=q.get('comparison_input_status',{}).get(kind,{}).get('estimate_content')
    if recipe is None:
        status=q.get('comparison_input_status',{}).get(kind,{})
        reasons=[status.get('estimate_unresolved_reason', status.get('reason',kind+'_inputs_missing'))]
        templates=[t for t in _catalog()['templates'] if t['venue']==q['venue']]
        values=references(q,profiles) if _values is None else _values
        selection=values.get('identity',{}).get('payload',{}).get('selection',{})
        scope=selection.get('scope',{})
        applicable=[t for t in templates if t['scope']['league']==selection.get('event',{}).get('league') and t['scope']['period']==scope.get('period') and selection.get('family') in ('moneyline','team_binary')]
        if not applicable:
            reasons.append(kind+'_estimate_scope_unsupported')
        elif any(not _active(t,at) for t in applicable):
            reasons.append(kind+'_estimate_model_expired_or_not_effective')
        return dict(available=False,reasons=sorted(set(reasons)))
    if recipe.get('version')!=VERSION or recipe.get('id')!=digest({k:v for k,v in recipe.items() if k!='id'}):
        raise ValueError('estimate_content_digest_conflict')
    values=references(q,profiles) if _values is None else _values
    original=q['comparison_input_refs']['refs'][kind]
    if recipe['original_profile_ref'] != original or recipe['native_key'] != observation(q)['native_key'] or recipe['selection'] != q['binding']['selection']:
        raise ValueError('estimate_content_native_or_profile_conflict')
    rows=[t for t in _catalog()['templates'] if t['id']==recipe['template_ref']]
    if len(rows)!=1:raise ValueError('estimate_content_version_unavailable')
    template=rows[0]
    if template['version']!=recipe['template_version'] or template['venue']!=q['venue'] or recipe['kind']!=kind:
        raise ValueError('estimate_content_scope_conflict')
    if q.get('native_contract') is not None and q['native_contract']['id']!=recipe['native_contract_id']:
        raise ValueError('estimate_content_contract_conflict')
    reasons=list(recipe['reasons'])
    if not _active(template,at) or not _active(recipe,at):reasons.append('estimate_content_expired_or_not_effective')
    profile=values.get(kind)
    if profile is not None and q['comparison_input_status'][kind]['status']=='available_and_bound':
        if not _active(profile,at) or not _active(profile['payload'],at):
            reasons.append('estimate_'+kind+'_inputs_expired_or_not_effective')
    # Transport state gates current ranking, not the economics of retained prices.
    # Exact identity, recipe and applicability guards above still govern inspection.
    if not q['binding']['verified']:reasons.append('estimate_native_orientation_unresolved')
    return dict(version=VERSION,available=not reasons,reasons=sorted(set(reasons)),recipe=deepcopy(recipe),
        template=deepcopy(template),original_profile=deepcopy(values.get(kind)),
        original_status={k:deepcopy(v) for k,v in q['comparison_input_status'][kind].items() if k!='estimate_content'},
        observation=observation(q),actual_qualified=False)


def describe(q, profiles, *, at):
    values=references(q,profiles)
    return {kind:resolve_content(q,profiles,at=at,kind=kind,_values=values) for kind in ('fee','payout')}


def temporal(q, at):
    """No packets needed when selected model content crosses its interval."""
    result={}
    for kind in ('fee','payout'):
        recipe=q.get('comparison_input_status',{}).get(kind,{}).get('estimate_content')
        if recipe is None:continue
        changes=[]
        metadata=recipe['metadata'].get('kalshi_metadata',{})
        for field in ('series_changes','event_changes'):
            changes.extend(c['scheduled_ts'] for c in metadata.get(field,[]) if instant(c['scheduled_ts'])<=at)
        result[kind]=dict(active=_active(recipe,at),selected_changes=changes)
    return result


def validate_attached(q):
    for kind in ('fee','payout'):
        recipe=q.get('comparison_input_status',{}).get(kind,{}).get('estimate_content')
        if recipe is not None:
            public_tree(recipe)
            if len(encoded(recipe))>32768 or recipe.get('version')!=VERSION or recipe.get('id')!=digest({k:v for k,v in recipe.items() if k!='id'}):
                raise ValueError('estimate_content_digest_or_capacity_conflict')
            if recipe['kind']!=kind or recipe['actual_value'] is not None or recipe['actual_qualified'] is not False:
                raise ValueError('estimate_content_authority_conflict')
            if recipe['native_key']!=observation(q)['native_key'] or recipe['selection']!=q['binding']['selection'] or recipe['original_profile_ref']!=q['comparison_input_refs']['refs'][kind]:
                raise ValueError('estimate_content_native_or_profile_conflict')
