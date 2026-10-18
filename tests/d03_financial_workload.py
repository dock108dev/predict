"""Explicit synthetic current-row financial workload; never production evidence.

The 500-event structural test clones retain exact native units and complete depth
shape. This helper separately authors source bindings and generic modeled rules
for those fictional instruments. The ordinary current API still rejects synthetic
provenance. No real selected qualification, confirmation seal or source authority
is copied to a fictional instrument.
"""
from copy import deepcopy
from dataclasses import replace

from app.comparison.current_dependencies import references, profile
from app.comparison.shared_templates import ProfilePool
from app.comparison.payouts import PayoutProfile, selection_digest, bind_profile, CompletionContext
from app.comparison.domain import CanonicalSelection, EvidenceReference
from app.comparison.event_links import digest
from app.dashboard.current_contract import quotes_of, serialize as ordinary_serialize
from app.storage.store import hashed, stamp

VERSION='d03-authored-current-financial-1'


def authored_records(records):
    """Author fictional source material before upsert; preserve prices and clocks."""
    result=deepcopy(records)
    for record in result:
        q=record['quote'];source=q['source']
        if q['provenance'].get('mode')!='synthetic' or q['provenance'].get('real_source') is not False:
            raise ValueError('D03 authoring is confined to explicitly synthetic facts')
        for key in ('_instrument','_fingerprint'):record.pop(key,None)
        for key in ('native_predicate','book_confirmation','observation_time_evidence','occurrence_link',
                    'occurrence_match','native_contract','sharp_reference','binding',
                    'comparison_input_refs','comparison_input_status','calculations'):
            q.pop(key,None)
        source['binding_version']=VERSION
        source['binding_id']=hashed([VERSION,source['provider'],source['native_event_id'],source['native_market_id'],source['native_outcome_id'],source['native_side'],record['selection']])
        # Both benchmark selections must originate in one authored provider frame.
        q['provenance']=dict(mode='synthetic',real_source=False,
            sha256=hashed([VERSION,'provider-frame',source['provider'],source['native_event_id']]),
            fixture='D03 fictional current-row financial workload; no real venue observations')
        q['rule_note']='Explicit authored normal contract; existing modeled fees and settlement, no venue authority'
        meta=dict(phase='pregame',overtime='included',native_key=[q['venue'],*[source[k] for k in ('native_event_id','native_market_id','native_outcome_id','native_side')]])
        if q['venue']=='kalshi':meta['series_id']='KXNFLGAME' # Authored choice of the existing named fee model.
        meta.update(native_terms={'description':'Authored full-game winner including overtime'}, original_wording={'description':'Authored full-game winner including overtime'})
        record['comparison_source_metadata']=meta
        record['comparison_scope']=dict(overtime='included')
        record['orientation_evidence']=[VERSION+':fictional-exact-selection']
    return result


def authored_payout_inputs(raw):
    """Author exact current-occurrence scopes, then require the real binder.

    Current combination rebinds canonical occurrence identity. Generic source
    hypotheses retain their pre-combination payout digest; the fictional workload
    authors a new payout profile for that canonical selection. Cashflow cells,
    units, native keys, effective interval and modeled rule stay unchanged. This
    does not weaken bind_profile or alter any financial owner.
    """
    raw=deepcopy(raw);raw['mode']='synthetic';pool=ProfilePool(raw['comparison_profiles'])
    for event in raw['events']:
        for group in event['groups']:
            for outcome in group['outcomes']:
                for q in quotes_of(outcome):
                    if q['provenance'].get('mode')!='synthetic' or q['provenance'].get('real_source') is not False:
                        raise ValueError('D03 synthetic serializer cannot accept current source evidence')
                    values=references(q,raw['comparison_profiles'])
                    original=values.get('payout');identity=values.get('identity',{}).get('payload',{})
                    if original is None or identity.get('completion_context') is None:continue
                    selected=CanonicalSelection.from_dict(identity['selection'])
                    prior=PayoutProfile.from_dict(original['payload'])
                    if any(cell.status=='evidenced' for cell in (prior.below,prior.equal,prior.above,prior.noncompleted)):
                        raise ValueError('D03 cannot clone evidenced settlement cells to fictional instruments')
                    evidence=EvidenceReference('authored:'+VERSION+':'+q['id'],hashed([VERSION,q['id']]),'authored')
                    current=replace(prior,selection_sha256=selection_digest(selected),source_evidence=(evidence,))
                    bound=bind_profile(selected,current,at=stamp(raw['clock_at']),rule_revision=identity['rule_revision'],context=CompletionContext.from_dict(identity['completion_context']))
                    assert bound.profile.native_key==selected.native.key
                    for part in ('below','equal','above','noncompleted'):
                        assert getattr(current,part)==getattr(prior,part)
                    key,item=profile('payout',current.to_dict(),expires_at=original.get('expires_at'))
                    if not pool.add(key,item):raise ValueError('D03 authored profile capacity')
                    q['comparison_input_refs']['refs']['payout']=key
                    recipe=q['comparison_input_status']['payout'].get('estimate_content')
                    if recipe:
                        recipe['original_profile_ref']=key
                        recipe['id']=digest({k:v for k,v in recipe.items() if k!='id'})
    raw['comparison_profiles']=pool.finish()
    return raw


def serialize_synthetic(raw,**kwargs):
    """Explicit test patch for current_contract.serialize; ordinary path unchanged."""
    return ordinary_serialize(authored_payout_inputs(raw),allow_synthetic=True,**kwargs)
