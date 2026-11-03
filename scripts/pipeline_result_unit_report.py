"""Sampled unit delivery report; generations are not financial qualification."""
import gzip,json,sys
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timedelta

def stamp(s):return datetime.fromisoformat(s)
def seconds(a,b):return (stamp(a)-stamp(b)).total_seconds()
def distribution(values):
    values=sorted(values)
    if not values:return dict(n=0)
    def percentile(p):return values[min(len(values)-1,int((len(values)-1)*p))]
    return dict(n=len(values),min=values[0],p50=percentile(.5),p95=percentile(.95),max=values[-1])

def report(folder,cohort,path):
    paths=sorted(Path(folder).glob('sample-*.json.gz'));original=json.loads(Path(cohort).read_text())['rows']
    samples=[];generations={};baseline_generations={};inputs={};changes=Counter();cohort_changes=Counter();last={};runs=[];seen=defaultdict(set);semantic_seen=defaultdict(set);seen_events=defaultdict(set)
    original_ids={r['source_event_id'] for r in original}
    schedules={};inventories={};inventory_union=set();unit_events=defaultdict(set);unit_observed=Counter();event_offer_samples=Counter();arrivals=set();removed=set()
    reasons=Counter();start=None;first_visible={};last_current={};sample_gaps=[];universe=set();prior_units={}
    for p in paths:
        s=json.loads(gzip.decompress(p.read_bytes()));at=s['at']
        if start is None:start=at;initial_window=set(s['window'])
        if samples:sample_gaps.append(seconds(at,samples[-1]['at']))
        arrivals.update(set(s['window'])-initial_window);universe.update(s['window'])
        for e in s['events']:
            if e.get('scheduled_start'):schedules[e['id']]=e['scheduled_start']
            if e['id'] in s['window'] and e['offers']:event_offer_samples[e['id']]+=1
        for cid,values in s['inputs'].items():
            previous=inputs.get(cid)
            if previous is None:
                if not s['inputs_complete']:changes['added_offer']+=1
            elif previous!=values:
                meaningful=any(previous[i]!=values[i] for i in (0,1,3,4))
                kind='semantic_or_source_clock_or_book' if meaningful else 'receipt_only'
                changes[kind]+=1
                if len(values)>6 and values[6] in original_ids:cohort_changes[kind]+=1
            inputs[cid]=values
        for cid in s.get('removed_inputs',[]):inputs.pop(cid,None);changes['removed_offer']+=1
        for g in s['generations']:
            generations[g['id']]=g
            if not samples:baseline_generations[g['id']]=dict(g)
        for key,inv in s['inventory'].items():
            inventories[key]=inv
            inventory_union.update((key,u['id']) for u in inv['units'])
            for u in inv['units']:
                unit_events[(key,u['id'])].update(inv.get('events',[]))
        active=set()
        for u in s['units']:
            key=(u['game_key'],u['unit_id']);unit_events[key].update(u['events']);unit_observed[key]+=1
            generation=(key,u['generation_id']);first_visible.setdefault(generation,at)
            if u['current']:
                active.add(generation);seen[key].add(u['generation_id'])
                if u.get('semantic_dependencies'):semantic_seen[key].add(u['semantic_dependencies'])
                for e in u['events']:seen_events[e].add(generation)
                if generation not in last:last[generation]=dict(first=at,last=at,samples=0)
                last[generation]['last']=at;last[generation]['samples']+=1;last_current[key]=at
            else:reasons.update(u['reasons'])
        for generation in set(last)-active:
            runs.append(dict(game=generation[0][0],unit=generation[0][1],generation=generation[1],**last.pop(generation),invalidated_sample=at))
        samples.append(dict(at=at,engine=s['engine'],runtime=s['runtime'],storage_bytes=s['storage_bytes'],units=s['units'],inventory=s['inventory'],window=s['window']))
    for generation,run in last.items():runs.append(dict(game=generation[0][0],unit=generation[0][1],generation=generation[1],**run,right_censored=True))
    end=samples[-1]['at'];duration=seconds(end,start)
    active_generations={gid:g for gid,g in generations.items() if g['last_attempt'] and stamp(start)<=stamp(g['last_attempt'])<=stamp(end)}
    scoped={gid:g for gid,g in active_generations.items() if set(g['events'])&{r['source_event_id'] for r in original}}
    latest={(u['game_key'],u['unit_id']):u for u in samples[-1]['units']}
    all_known={(game,u['id']) for game,inv in inventories.items() for u in inv['units']}
    desired={(game,u['id']) for game,inv in inventories.items() if not inv.get('superseded_at') for u in inv['units']}
    superseded=all_known-desired
    outside={eid for eid,scheduled in schedules.items() if not stamp(end)<=stamp(scheduled)<stamp(end)+timedelta(hours=72)}
    desired_end={key for key in desired if not unit_events[key] or bool(unit_events[key]-outside)}
    event_units=defaultdict(set)
    for key,events in unit_events.items():
        if key in desired:
            for e in events:event_units[e].add(key)
    dispositions=[]
    for old in original:
        eid=old['source_event_id'];units=event_units[eid];attempted=[g for g in scoped.values() if eid in g['events']]
        observed={key for key in units if seen[key]};repeated={key for key in units if len(seen[key])>=2};current={key for key in units if latest.get(key,{}).get('current')}
        dispositions.append(dict(source_event_id=eid,source=old['source'],native_event_id=old['native_event_id'],
            offered_samples=event_offer_samples[eid],samples=len(samples),known_game_units=len(units),
            superseded_game_units=sum(eid in unit_events[k] for k in superseded),
            units_ever_current=len(observed),units_repeat_current=len(repeated),units_repeat_changed_current=sum(len(semantic_seen[k])>=2 for k in units),units_current_end=len(current),
            units_never_observed_current=len(units-observed),units_not_current_end=len(units-current),
            first_observed_admission=min((g['admitted_at'] for g in attempted),default=None),last_observed_attempt=max((g['last_attempt'] for g in attempted),default=None),attempts=len(attempted),committed_generations=sum(bool(g['commits']) for g in attempted),
            last_observed_schedule=schedules.get(eid),outside_window_on_last_observed_schedule=eid in outside,full_inventory_evidence=bool(units),all_known_units_repeat=bool(units) and repeated==units,
            disposition='no_result_inventory_evidence' if not units else 'no_observed_current_unit' if not observed else 'partial_repeat_delivery' if repeated else 'single_generation_only',
            units=[dict(game=k[0],unit=k[1],current_generations=len(seen[k]),current_end=bool(latest.get(k,{}).get('current')),
                end_reasons=latest.get(k,{}).get('reasons',['not_committed']),last_current_at=last_current.get(k)) for k in sorted(units)]))
    latency=defaultdict(list);timing=defaultdict(list);cohort_latency=defaultdict(list);cohort_timing=defaultdict(list)
    for gid,g in active_generations.items():
        if g.get('completed_at'):latency['admission_to_completion_s'].append(seconds(g['completed_at'],g['admitted_at']))
        facts=g.get('facts') or {};capture=facts.get('captured_at')
        if capture and g.get('completed_at'):latency['capture_to_completion_s'].append(seconds(g['completed_at'],capture))
        if facts.get('commit_observed_at') and g.get('published_at'):latency['transaction_marker_to_commit_observed_s'].append(seconds(facts['commit_observed_at'],g['published_at']))
        key=(g['game_key'].split('#result:')[0],g['game_key'].split('#result:')[-1]);visible=first_visible.get((key,gid))
        if visible and g.get('published_at'):latency['transaction_marker_to_first_sample_visibility_s'].append(seconds(visible,g['published_at']))
        for k,v in facts.get('timing',{}).items():timing[k].append(v)
        if gid in scoped:
            if g.get('completed_at'):cohort_latency['admission_to_completion_s'].append(seconds(g['completed_at'],g['admitted_at']))
            if capture and g.get('completed_at'):cohort_latency['capture_to_completion_s'].append(seconds(g['completed_at'],capture))
            for k,v in facts.get('timing',{}).items():cohort_timing[k].append(v)
    lifetime=[seconds(r['last'],r['first']) for r in runs]
    current_end=sum(u['current'] for u in latest.values());unsealed=desired_end-set(latest)
    storage=[s['storage_bytes'] for s in samples]
    out=dict(start=start,end=end,duration_seconds=duration,samples=len(samples),sample_gap_seconds=distribution(sample_gaps),
        fixed_engines=sorted({s['engine'] for s in samples}),fixed_runtimes=sorted({s['runtime']['runtime_id'] for s in samples}),
        board_unavailable_samples=sum(s['runtime'].get('calculations',{}).get('board')!='running' for s in samples),unhealthy_samples=sum(not s['runtime']['healthy'] for s in samples),inactive_samples=sum(not s['runtime']['active'] for s in samples),
        population=dict(original_events=len(original),initial_window_events=len(initial_window),observed_window_events=len(universe),arrival_event_ids=sorted(arrivals),window_exit_event_ids=sorted(outside&universe),
            original_offered_every_sample=sum(d['offered_samples']==len(samples) for d in dispositions),events_any_current=sum(d['units_ever_current']>0 for d in dispositions),
            events_any_repeat=sum(d['units_repeat_current']>0 for d in dispositions),events_all_known_units_repeat=sum(d['all_known_units_repeat'] for d in dispositions),
            events_any_changed_repeat=sum(d['units_repeat_changed_current']>0 for d in dispositions),
            events_all_known_units_changed_repeat=sum(d['known_game_units']>0 and d['units_repeat_changed_current']==d['known_game_units'] for d in dispositions),
            events_without_inventory=sum(not d['full_inventory_evidence'] for d in dispositions)),
        units=dict(interval_inventory_union=len(inventory_union),endpoint_inventory_units=sum(len(v["units"]) for v in samples[-1]["inventory"].values()),known_inventory=len(desired),known_units_outside_window_end=len(desired-desired_end),retained_end=len(latest),unsealed_known_end=len(unsealed),current_end=current_end,
            historical_end=len(latest)-current_end,ever_sampled_current=sum(bool(seen[k]) for k in desired),repeat_current=sum(len(seen[k])>=2 for k in desired),repeat_changed_current=sum(len(semantic_seen[k])>=2 for k in desired),
            financial_states_end=dict(Counter(u['financial_state'] for u in latest.values())),
            never_current=len([k for k in desired if not seen[k]])),
        generation_ledger=dict(interval_counter_increases={field:sum(max(0,g.get(field,0)-baseline_generations.get(gid,{}).get(field,0)) for gid,g in generations.items()) for field in ('attempts','calculations','reuses','commits')},unique_admitted_or_attempted=len(active_generations),unique_cohort_generations=len(scoped),
            dispositions=dict(Counter(g['disposition'] for g in active_generations.values())),
            calculations=sum(g['calculations'] for g in active_generations.values()),reuses=sum(g['reuses'] for g in active_generations.values()),
            commits=sum(g['commits'] for g in active_generations.values()),failures=dict(Counter(g.get('reason') for g in active_generations.values() if g.get('reason')))),
        input_changes=dict(changes),original_cohort_input_changes=dict(cohort_changes),latency={k:distribution(v) for k,v in latency.items()},seal_timing_ms={k:distribution(v) for k,v in timing.items()},
        cohort_latency={k:distribution(v) for k,v in cohort_latency.items()},cohort_seal_timing_ms={k:distribution(v) for k,v in cohort_timing.items()},observed_current_lifetime_lower_bound_seconds=distribution(lifetime),current_runs=runs,invalidation_reason_sample_counts=dict(reasons),
        storage=dict(start=storage[0],end=storage[-1],peak=max(storage),growth=storage[-1]-storage[0],cap=2147483648,minimum_headroom=2147483648-max(storage)),
        original_dispositions=dispositions,
        superseded_inventories=[dict(game=game,at=inv['superseded_at'],successors=inv.get('superseded_by'),events=inv.get('events'),units=[u['id'] for u in inv['units']]) for game,inv in inventories.items() if inv.get('superseded_at')],
        measurement_notes=['Requested cadence is recorded by the run command; actual gaps are reported. Missed subinterval publications cannot be counted as current.',
            'Current lifetimes are sampled lower bounds, including zero-duration single samples; no claim of uninterrupted between-sample validity.',
            'Event denominators use the entire known game unit inventory/closure for each native identity, not one easy market. Inventory absence is explicit and never counted as success.',
            'known_inventory uses the latest observed inventory per game across the interval; interval_inventory_union separately includes membership revisions. Endpoint current inventory requires the separate coherent census.',
            'Known inventories include the independent inventory owner before any seal, plus retained historical parent/child evidence. Current proof is reported separately; undiscovered or obsolete current membership remains unknown.',
            'Positively superseded occurrence inventories are enumerated separately and excluded from active unit denominators. Missing/invalid catalogs never justify this classification; original source identities remain in the 68-event denominator.',
            'Generation totals are ledger states observed during the interval, filtered by last_attempt. Reuse counters are cumulative on those observed identities, not newly admitted counts.',
            'Post-transaction commit_observed_at is an upper visibility bound; published_at is an in-transaction marker.',
            'Current unsupported output is dependency-valid diagnostic delivery, not numeric EV or executable-pair qualification.'])
    Path(path).write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k not in ('original_dispositions','current_runs')},indent=2))
if __name__=='__main__':report(*sys.argv[1:])
