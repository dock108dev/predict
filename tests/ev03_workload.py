"""Explicitly synthetic EV03 slate through ordinary normalized admission.

Retained metadata supplies only the software shape. All game/instrument identities,
prices, reference observations and qualification here are authored test inputs.
This module performs no acquisition and needs no credentials or running service.
"""
from copy import deepcopy
from hashlib import sha256
import json
from time import perf_counter
import resource

from tests.test_comparison_source_inputs import native_records, authored_opposition, AT
from app.collection.current_benchmark import attach as attach_benchmark
from tests.current_fixture import fixture, InjectedTestProvider
from app.comparison.event_links import provider_key
from app.dashboard.current_normalized import catalog_from_normalized
from app.dashboard.current_contract import quotes_of, packed
from app.dashboard.current_state import CurrentStore


def records(games=150, quote_count=2000):
    seeds=native_records();rows=[];refs=[];expected={}
    for game in range(games):
        count=quote_count//games+(game<quote_count%games)
        expected[game]=[]
        game_rows=[]
        for index in range(count):
            r=deepcopy(seeds[index%2]);r={k:v for k,v in r.items() if not k.startswith('_')}
            native_event=f'synthetic:ev03:game:{game:03d}'
            r['event']['id']=native_event
            r['event']['game_id']=native_event
            r['event']['title']=f'Synthetic game {game:03d}'
            r['event_scope']=dict(policy='native-provider-event-1',source='polymarket_us',native_event_id=native_event)
            r['market_identity']['event']=provider_key('polymarket_us',r['event'])
            q=r['quote'];q.pop('native_predicate',None);q.pop('occurrence_link',None)
            q.pop('occurrence_match',None);q.pop('sharp_reference',None)
            q['source'].update(native_event_id=native_event,native_market_id=f'synthetic:ev03:market:{game}',
                native_outcome_id=f'synthetic:ev03:instrument:{game}:{index}',
                binding_id=sha256(f'{game}:{index}'.encode()).hexdigest(),binding_version='authored-ev03-1')
            q['rule_note']='Synthetic conditional completed-result inputs; actual exceptional facts unknown'
            q['provenance']=dict(mode='synthetic',real_source=False,sha256=sha256(f'authored:{game}:{index}'.encode()).hexdigest())
            r['comparison_source_metadata']=dict(phase='pregame',overtime='included',
                native_key=[q['venue'],*[q['source'][k] for k in ('native_event_id','native_market_id','native_outcome_id','native_side')]])
            r['comparison_source_metadata'].update(native_terms={'description':'Authored full-game winner including overtime'}, original_wording={'description':'Authored full-game winner including overtime'})
            r['orientation_evidence']=['authored:ev03:exact-selected-contract']
            # An intentional missing reference is independent from healthy fees,
            # payout, identity, grid and policy. All later games have support.
            supported=index%10!=0

            expected[game].append(supported)
            game_rows.append(r)
        opposition=authored_opposition(deepcopy(game_rows[0]));refs.extend(opposition)
        attach_benchmark(game_rows,opposition)
        for index,r in enumerate(game_rows):
            if not expected[game][index]:r['quote'].pop('sharp_reference',None)
        rows.extend(game_rows)
    return rows,refs,expected


def workload():
    rows,refs,expected=records();envelope=fixture();envelope['events']=[]
    envelope.update(runtime_id='synthetic:ev03:150-games-2000-quotes',clock_at=AT.isoformat(),projected_at=AT.isoformat())
    started=perf_counter();raw=catalog_from_normalized(envelope,rows,reference_records=refs)
    admission=perf_counter()-started
    return raw,expected,admission


def measure():
    raw,expected,admission=workload();started=perf_counter()
    store=CurrentStore(InjectedTestProvider(raw),monotonic=lambda:0)
    projection=perf_counter()-started;state=store._state
    profiles=raw['comparison_profiles'];by_event=[];attachments=[]
    for event in state['events']:
        qs=[q for g in event['groups'] for o in g['outcomes'] for q in quotes_of(o)]
        position=int(qs[0]['source']['native_event_id'].rsplit(':',1)[1])
        capacities=sum(any('capacity' in s.get('reason','') for s in q.get('comparison_input_status',{}).values()) for q in qs)
        by_event.append(dict(position=position,quotes=len(qs),supported=sum(expected[position]),
            eligible=sum(q['calculations']['net_ev']['eligible'] for q in qs),capacity_deferrals=capacities,
            missing_refusals=sum(not q['calculations']['net_ev']['eligible'] and not any('capacity' in s.get('reason','') for s in q.get('comparison_input_status',{}).values()) for q in qs)))
        attachments.extend(len(packed({k:v for k,v in q.items() if k in ('comparison_input_refs','comparison_input_status')})) for q in qs)
    from app.comparison.metrics import snapshot_metrics
    report=dict(evidence_class='explicitly synthetic offline software workload',games=len(state['events']),quotes=sum(e['quotes'] for e in by_event),
        profile_count=len(profiles),profile_bytes=len(packed(profiles)),
        attachment_bytes=dict(max=max(attachments),mean=sum(attachments)/len(attachments)),
        snapshot_bytes=len(store.encoded_snapshot()),comparison_response_bytes=len(packed(snapshot_metrics(state))),
        admission_seconds=admission,projection_seconds=projection,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        by_event=sorted(by_event,key=lambda e:e['position']))
    if isinstance(profiles,dict) and profiles.get('version')=='comparison-current-dependencies-2':
        report.update(template_count=len(profiles['templates']),binding_count=len(profiles['bindings']))
    return report


if __name__=='__main__':
    print(json.dumps(measure(),indent=2))
