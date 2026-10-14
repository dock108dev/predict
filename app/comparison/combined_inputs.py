"""Reusable occurrence inputs from immutable retained SQL envelopes.

OccurrenceResolver owns joins; shared benchmark and financial owners calculate
results. This owner neither acquires data nor publishes a board/latest pointer."""
import base64
import json
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from collections import OrderedDict
from threading import RLock
from app.storage.store import hashed, encoded, stamp
from app.comparison.occurrence_matching import OccurrenceResolver
from app.comparison.combined_native import normalize
from app.comparison.benchmark import SPORTSBOOKS
from app.comparison.source_inputs import produce_two_way_benchmark
from app.comparison.domain import CanonicalSelection, Scope
from app.comparison.current_dependencies import profile, references
from app.comparison.shared_templates import ProfilePool
from app.dashboard.current_state import unavailable
from app.dashboard.current_normalized import catalog_from_normalized
from app.dashboard.current_contract import quotes_of

VERSION = 'predict-combined-occurrence-inputs-1'
MAX_ENVELOPES = 256
_ADMITTED_CACHE = OrderedDict()
_ADMITTED_CACHE_LOCK = RLock()
_ADMITTED_CACHE_BYTES = 4*1024*1024


def _admitted_rows(item, body, projected):
    """Verify current SQL rows against their exact immutable provider frame.

    Cache only successful normalization, keyed by receipt identity/hash and
    original event subset. Bytes in the cache are immutable; callers receive
    fresh objects. Current source membership is never cached here.
    """
    from app.collection.current_aggregate_admission import admit
    by_venue={}
    for row in projected:
        r=row['value'];q=r['quote'];s=q['source']
        native=hashed([q['venue'],s['native_event_id'],s['native_market_id'],s['native_outcome_id']])
        if row['native_id']!=native or row['envelope_id']!=item['id'] or s['provider']!='the_odds_api':
            raise ValueError('combined_admitted_projection_association_conflict')
        by_venue.setdefault(q['venue'],{})[native]=r
    result=[];value=item['record']['value']
    for venue in SPORTSBOOKS:
        wanted=by_venue.pop(venue,{})
        if not wanted:continue
        ids=tuple(sorted({r['quote']['source']['native_event_id'] for r in wanted.values()}))
        key=(item['id'],item['payload_sha256'],venue,ids)
        with _ADMITTED_CACHE_LOCK:
            cached=_ADMITTED_CACHE.get(key)
            if cached is not None:_ADMITTED_CACHE.move_to_end(key)
        if cached is None:
            rows=admit(body,'NFL',value['received_at'],venue=venue,event_ids=ids)
            cached=encoded(rows)
            if len(cached)<=512*1024:
                with _ADMITTED_CACHE_LOCK:
                    _ADMITTED_CACHE[key]=cached;_ADMITTED_CACHE.move_to_end(key)
                    while len(_ADMITTED_CACHE)>32 or sum(map(len,_ADMITTED_CACHE.values()))>_ADMITTED_CACHE_BYTES:
                        _ADMITTED_CACHE.popitem(last=False)
        seen=set()
        for r in json.loads(cached):
            q=r['quote'];s=q['source']
            native=hashed([q['venue'],s['native_event_id'],s['native_market_id'],s['native_outcome_id']])
            if native not in wanted:continue
            if r!=wanted[native]:raise ValueError('combined_admitted_projection_original_conflict')
            seen.add(native);result.append(r)
        if seen!=set(wanted):raise ValueError('combined_admitted_projection_original_absent')
    if by_venue:raise ValueError('combined_admitted_projection_venue_conflict')
    return result


def _key(row):
    q=row['quote'];s=q['source']
    return (q['venue'],s['native_event_id'],s['native_market_id'],s['native_outcome_id'])


def _benchmark(rows, state, venue):
    """Declare aggregate h2h grouping; retain original outcome-local IDs too."""
    from app.collection.current_comparison_inputs import selection
    candidates=[r for r in rows if r['quote']['venue']==venue and r['selection']['predicate']=='win']
    if len(candidates)!=2:raise ValueError('selected_benchmark_two_originals_absent')
    first=candidates[0]['quote']
    if any(r['quote']['provenance']['sha256']!=first['provenance']['sha256'] or
           r['quote']['source']['native_event_id']!=first['source']['native_event_id'] or
           r['market_identity']!=candidates[0]['market_identity'] for r in candidates):
        raise ValueError('selected_benchmark_shared_frame_conflict')
    # Aggregate admission assigned outcome-local synthetic market locators.
    # The real provider h2h frame is the grouping authority, never an invented
    # provider-native market ID. All original keys remain in source_originals.
    grouped='declared-aggregate-h2h:'+hashed([venue,first['source']['native_event_id'],'h2h'])
    event=state['events'][0]; typed=[]
    for r in candidates:
        q=r['quote'];g=dict(market='winner',period='full_game',line=None)
        s=CanonicalSelection.from_dict(selection(event,g,r['selection'],q))
        s=replace(s,scope=Scope('full_game','included','conditional_decisive_win_loss'),
                  native=replace(s.native,market_id=grouped))
        clocks=q['provider_clocks']
        typed.append(dict(selection=s.to_dict(),decimal_odds=q['original']['value'],
            book_at=clocks['book'],market_at=clocks['market'],received_at=q['times']['received_at'],
            revision=hashed(r)))
    reference=produce_two_way_benchmark(typed,venue=venue,receipt_sha256=first['provenance']['sha256'],
        source_revision=hashed([first['times']['received_at'],first['provenance']['sha256'],grouped]))
    return reference,dict(grouping_authority='exact admitted provider event/book/h2h in shared original response',
        grouped_market_id=grouped,source_originals=deepcopy(candidates))


def prepare(envelopes, *, at, resolver=None, associations=None, admitted_records=None):
    """Resolve current membership once, before financial/profile hydration."""
    if len(envelopes)>MAX_ENVELOPES or len(encoded(envelopes))>24*1024*1024:
        raise ValueError('combined_input_capacity')
    instant=stamp(at); originals={};catalogs={};books={};aggregate={};excluded=[]
    projected={}
    if admitted_records is not None:
        if associations is None:raise ValueError('combined_admitted_associations_required')
        known_ids={item['id'] for item in envelopes}
        for row in admitted_records:
            if row['envelope_id'] not in known_ids or associations.get(('the_odds_api','quote',row['native_id']))!=row['envelope_id']:
                raise ValueError('combined_admitted_projection_association_conflict')
            projected.setdefault(row['envelope_id'],[]).append(row)
    from app.collection.current_aggregate_admission import admit
    for item in sorted(envelopes,key=lambda x:stamp(x['record']['retained_at'])):
        item=deepcopy(item);record=item['record'];eid=item['id']
        if hashed(record)!=item['payload_sha256']:raise ValueError('combined_envelope_hash_conflict:'+eid)
        if eid in originals and originals[eid]!=item:raise ValueError('combined_envelope_identity_conflict')
        if stamp(record['retained_at'])>instant:continue
        originals[eid]=item;source=record['source'];kind=record['kind'];value=record['value']
        if kind=='catalog' and source in ('kalshi','polymarket_us'):catalogs[source]=item
        elif kind=='admitted_books' and source in ('kalshi','polymarket_us'):books.setdefault(source,[]).append(item)
        elif kind=='aggregate_batch' and value['sport']=='NFL':
            body=base64.b64decode(value['body_b64'],validate=True)
            if sha256(body).hexdigest()!=value['body_sha256']:raise ValueError('combined_aggregate_body_hash_conflict')
            venue_records=[]
            if admitted_records is not None:
                venue_records=_admitted_rows(item,body,projected.pop(eid,[]))
            else:
                for venue in SPORTSBOOKS:
                    try:venue_records.extend(admit(body,'NFL',value['received_at'],venue=venue))
                    except (ValueError,KeyError,TypeError) as error:
                        excluded.append(dict(venue=venue,envelope_id=eid,reason=str(error)))
            for r in venue_records:
                q=r['quote'];native=hashed([q['venue'],q['source']['native_event_id'],q['source']['native_market_id'],q['source']['native_outcome_id']])
                if associations is not None and associations.get(('the_odds_api','quote',native))!=eid:continue
                if r['market_identity']['family']!='moneyline':continue
                for name in ('_instrument','_fingerprint'):r.pop(name,None)
                r['comparison_scope']=dict(overtime='included')
                r['comparison_source_metadata']=dict(phase='pregame' if instant<stamp(r['event']['scheduled_start']) else 'unknown',
                    overtime='included',combined_envelope_id=eid,
                    scope_basis='declared aggregate NFL full-game decisive benchmark; exceptional execution rules retained')
                old=aggregate.get(_key(r));time=r['quote']['times']
                order=stamp(time['source_at'] or time['received_at'])
                if old is None or order>=old[0]:aggregate[_key(r)]=(order,r)
    if any(stamp(originals[eid]['record']['retained_at'])<=instant for eid in projected if eid in originals):
        raise ValueError('combined_admitted_projection_envelope_conflict')
    records=[r for _,r in aggregate.values()]
    for source,catalog in catalogs.items():
        native,errors=normalize(catalog,books.get(source,[]),at=at,associations=associations);records.extend(native);excluded.extend(errors)
    resolved=(resolver or OccurrenceResolver()).resolve(records,clock=at)
    groups={}
    for r in resolved:groups.setdefault(encoded(r['market_identity']['event']),[]).append(r)
    return dict(at=at,originals=originals,groups=list(groups.values()),excluded=excluded)


def build(envelopes, *, at, selected=None, benchmark_venue='pinnacle', resolver=None, associations=None, admitted_records=None, prepared=None):
    """Hydrate only selected resolved occurrences; preserve original clocks.

    A read context may supply one verified prepared frame across several boards.
    Legacy retained replay without admitted rows uses its unchanged admission.
    """
    if benchmark_venue not in SPORTSBOOKS:raise ValueError('unsupported_selected_benchmark')
    prepared=prepared or prepare(envelopes,at=at,resolver=resolver,associations=associations,admitted_records=admitted_records)
    if prepared['at']!=at:raise ValueError('combined_prepared_clock_conflict')
    originals=prepared['originals'];excluded=prepared['excluded']
    result=[]
    for rows in prepared['groups']:
        members={(r['quote']['source']['provider'],r['quote']['source']['native_event_id']) for r in rows}
        if selected is not None and tuple(selected) not in members:continue
        references_rows=[r for r in rows if r['quote']['venue']=='pinnacle']
        executions=[r for r in rows if r['quote']['venue']!='pinnacle']
        if not executions:continue
        raw=unavailable();raw.update(clock_at=at,projected_at=at,state='available',runtime_id='retained-combined-input')
        for status in raw['source_status'].values():status.update(state='available',reason_code='retained_input',reason='Retained observations; original clocks apply.')
        state=catalog_from_normalized(raw,deepcopy(executions),reference_records=deepcopy(references_rows))
        # Legacy producer/fallback identities used different occurrence aliases.
        # Bind a combined-input identity consistently and retain the complete parent.
        pool=ProfilePool(state['comparison_profiles'])
        for event in state['events']:
            for group in event['groups']:
                for outcome in group['outcomes']:
                    for q in quotes_of(outcome):
                        old=references(q,state['comparison_profiles']).get('identity')
                        if old is None:continue
                        payload=deepcopy(old['payload'])
                        typed=CanonicalSelection.from_dict(payload['selection'])
                        typed=replace(typed,event=replace(typed.event,occurrence_id=event['id']))
                        payload['selection']=typed.to_dict()
                        payload['combined_occurrence_binding']=dict(version=VERSION,occurrence_id=event['id'],
                            original_identity=deepcopy(old),match_revision=q['occurrence_match']['revision'])
                        payload['current_scope_binding']['occurrence_id']=event['id']
                        key,item=profile('identity',payload,expires_at=old['expires_at'])
                        if not pool.add(key,item):raise ValueError('combined_identity_profile_capacity')
                        q['comparison_input_refs']['refs']['identity']=key
                        if q['venue'] in ('kalshi','polymarket_us') and q['original']['units']=='usd_per_contract':
                            old_quantity=pool.get(q['comparison_input_refs']['refs']['quantity']) if q['comparison_input_refs']['refs']['quantity'] else None
                            original_status=q['comparison_input_status']['quantity']
                            # Exact known conflicting/bound grids retain precedence.
                            if old_quantity is None or original_status['status'] in ('absent','available_but_unbound','applicability_unresolved'):
                                quantity=dict(version='predict-combined-quantity-model-1',
                                    unit=dict(unit='dollar_face_contracts',face_usd_per_native='1',quantity_scale=None,price_scale=None),
                                    grid=dict(minimum_native='0.01',increment_native='0.01',legal_price_tick=None),
                                    grid_qualification='N01 declared cent-contract grid; actual minimum/increment unqualified',
                                    original_profile=deepcopy(old_quantity),original_status=deepcopy(original_status),
                                    native_key=[q['venue'],*[q['source'][k] for k in ('native_event_id','native_market_id','native_outcome_id','native_side')]],
                                    reason='named decimal $1 purchase-contract scenario; six-decimal Kalshi notional supported on observed cent-price path',
                                    actual_grid_qualified=False)
                                qkey,qitem=profile('quantity',quantity)
                                if not pool.add(qkey,qitem):raise ValueError('combined_quantity_model_capacity')
                                q['comparison_input_refs']['refs']['quantity']=qkey
                                q['comparison_input_status']['quantity']=dict(status='available_and_bound',reason='named_quantity_model_bound',
                                    actual_grid_qualified=False,original_status=deepcopy(original_status))

        state['comparison_profiles']=pool.finish()
        benchmark=None;benchmark_reason=None;benchmark_originals=None
        try:benchmark,benchmark_originals=_benchmark(rows,state,benchmark_venue)
        except (ValueError,KeyError,TypeError) as error:benchmark_reason=str(error)
        if benchmark is not None:
            pool=ProfilePool(state['comparison_profiles']);key,item=profile('reference',benchmark)
            if not pool.add(key,item):raise ValueError('combined_benchmark_profile_capacity')
            for event in state['events']:
                for group in event['groups']:
                    for outcome in group['outcomes']:
                        for q in quotes_of(outcome):
                            q['comparison_input_refs']['refs']['reference']=key
                            q['comparison_input_status']['reference']=dict(status='available_and_bound',reason='selected_two_way_benchmark_originals_bound')
            state['comparison_profiles']=pool.finish()
        used=set()
        for r in rows:
            meta=r.get('comparison_source_metadata',{});native=meta.get('combined_native_binding',{})
            used.update(x for x in (meta.get('combined_envelope_id'),native.get('catalog_envelope_id'),native.get('book_envelope_id')) if x)
        value=dict(version=VERSION,adapter_version='predict-combined-native-1',as_of=at,
            members=[list(x) for x in sorted(members)],records=deepcopy(rows),state_inputs=state,
            envelope_ids=sorted(used),envelopes=[originals[eid] for eid in sorted(used)],
            benchmark_venue=benchmark_venue,benchmark=benchmark,benchmark_reason=benchmark_reason,
            benchmark_originals=benchmark_originals,excluded=deepcopy(excluded),
            representation='authentic retained parsed/redacted observations and reconstructed books; not original wire bytes')
        value['input_version']=hashed(value);value['game_key']='combined:'+state['events'][0]['id']
        result.append(value)
    return result


def validate(bundle):
    expected=hashed({k:v for k,v in bundle.items() if k not in ('input_version','game_key')})
    if bundle.get('version')!=VERSION or expected!=bundle['input_version']:
        raise ValueError('combined_input_identity_conflict')
    if bundle['game_key']!='combined:'+bundle['state_inputs']['events'][0]['id'] or bundle['as_of']!=bundle['state_inputs']['clock_at']:
        raise ValueError('combined_occurrence_clock_binding_conflict')
    if bundle['envelope_ids']!=sorted({e['id'] for e in bundle['envelopes']}):
        raise ValueError('combined_envelope_membership_conflict')
    for e in bundle['envelopes']:
        if hashed(e['record'])!=e['payload_sha256']:raise ValueError('combined_envelope_hash_conflict')
    return deepcopy(bundle)


def calculate(bundle, policy, *, details=True):
    from app.comparison.estimated_ev import evaluate
    from app.comparison.estimated_pair import assemble
    bundle=validate(bundle);state=deepcopy(bundle['state_inputs']);at=stamp(bundle['as_of'])
    if getattr(policy,'benchmark_venue','pinnacle')!=bundle['benchmark_venue']:
        raise ValueError('combined_selected_benchmark_policy_conflict')
    from app.dashboard.current_contract import serialize
    state=serialize(state,estimate_policy=policy,details=details,supported=False,paired=False)
    for event in state['events']:
        event['funded_pairs'],event['funded_pair_search']=assemble(event,state['comparison_profiles'],at,policy=policy,details=details)
    return json.loads(encoded(state))
