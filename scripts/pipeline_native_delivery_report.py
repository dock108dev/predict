"""Reconcile fixed native identities, sampled intervals and committed seal evidence."""
from collections import Counter
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import stamp
from scripts.pipeline_delivery_report import build,load_samples
from scripts.pipeline_convergence_report import publication_current
from scripts.pipeline_changing_report import distribution


def report(folder,cohort,dispositions,target,api=None):
    folder=Path(folder);samples=load_samples(folder)
    original=json.loads(Path(cohort).read_text());final=json.loads(Path(dispositions).read_text())
    baseline=json.loads(Path('test-results/d02-storage-recovery/qualified-cohort-details.json').read_text())
    original_ids={r['source_event_id'] for r in original['rows']};baseline_ids={r['source_event_id'] for r in baseline['rows']}
    summary=build(folder);first,last=samples[0],samples[-1];ledger={};valid_commits={};ever=set();valid_by_sample=[]
    for s in samples:
        pubs=[p for p in s['publications'] if publication_current(p,s)];valid_by_sample.append(pubs)
        ever.update(eid for p in pubs for eid in p['publication_events'] or [])
        for g in s['generations']:
            ledger[g['id']]=g
            witness=g['facts'].get('validation_witness') or {}
            if (g['published_at'] and g['facts'].get('commit_observed_at') and not g['facts'].get('retained_financial_only')
                    and g['facts'].get('validation_witness') is not None and not witness.get('common') and not any(witness.get('counts',{}).values())):
                valid_commits[g['id']]=g
    dispositions={r['source_event_id']:r for r in final['rows']};rows=[]
    api_records=json.loads(Path(api).read_text()).get('records',[]) if api else []
    for original_row in original['rows']:
        eid=original_row['source_event_id'];generations=[g for g in ledger.values() if eid in g['events']]
        times=[];gids=set();intervals=[];active=None;changes=Counter();membership=[];last_member=None
        for i,s in enumerate(samples):
            offered=any(e['id']==eid for e in s['events'])
            if offered!=last_member:membership.append(dict(at=s['at'],offered=offered));last_member=offered
            if s['summary'].get('field_comparison_available',bool(i)):changes.update(s['summary'].get('event_changes',{}).get(eid,{}))
            valid=[p for p in valid_by_sample[i] if eid in (p['publication_events'] or [])]
            current_gids=sorted({p['generation'] for p in valid if p['generation']})
            if valid:
                times.append(s['at']);gids.update(current_gids)
            signature=current_gids if valid else None
            if signature is not None and (active is None or active['generations']!=signature):
                if active is not None:active['first_not_same_at']=s['at'];intervals.append(active)
                active=dict(generations=signature,first_current_at=s['at'],last_current_at=s['at'],
                    previous_sample_at=samples[i-1]['at'] if i else None,samples=1)
            elif active is not None and signature is not None:active['last_current_at']=s['at'];active['samples']+=1
            elif active is not None:active['first_not_same_at']=s['at'];intervals.append(active);active=None
        if active is not None:active['first_not_same_at']=None;intervals.append(active)
        attempts=[a for a in last['attempts'] if a['event_id']==eid and a['branch']=='metrics']
        commits=[g for g in valid_commits.values() if eid in g['events']]
        last_g=max(generations,key=lambda g:stamp(g['last_attempt'])) if generations else None
        observed_events=[e for s in samples for e in s['events'] if e['id']==eid]
        changing_samples=sum(bool(s['summary'].get('field_comparison_available',bool(i))) and any(k!='receipt_only' and n for k,n in s['summary'].get('event_changes',{}).get(eid,{}).items()) for i,s in enumerate(samples))
        row=dict(source_event_id=eid,source=original_row['source'],native_event_id=original_row['native_event_id'],
            baseline_class=original_row['delivery_class'],disposition=dispositions[eid],membership_transitions=membership,
            meaningful_field_change_counts=dict(changes),meaningful_change_samples=changing_samples,
            repeat_required_for_continuing_changes=changing_samples>=2,
            ordinary_read_observations=[r for r in api_records if eid in r['source_event_ids']],observed_component_memberships=sorted({tuple(e['component']) for e in observed_events}),
            unique_generations=len(generations),calculations=sum(g['calculations'] for g in generations),reuses=sum(g['reuses'] for g in generations),
            generation_dispositions=dict(Counter(g['disposition'] for g in generations)),
            generation_ids=[g['id'] for g in generations],admissions=sum(g['attempts'] for g in generations),
            deferred_or_superseded=sum(g['disposition'] in ('deferred','superseded') for g in generations),
            failed_generations=sum(g['disposition']=='failed' for g in generations),publication_game_keys=sorted({g['game_key'] for g in generations}),
            exact_validated_commit_candidates=len(commits),sampled_current_generations=sorted(gids),current_samples=len(times),
            first_sampled_current=times[0] if times else None,last_sampled_current=times[-1] if times else None,
            current_visibility_intervals=intervals,latest_attempt=attempts[0] if attempts else None,
            latest_generation=last_g,
            final_publication_states=[{k:p.get(k) for k in ('game_key','generation','engine','dependency_failures','dependency_current','retained_only','valid_until')}
                for p in last['publications'] if eid in (p['publication_events'] or [])],
            remaining_blocker=(None if len(gids)>=2 or times and changing_samples<2 else 'repeat_delivery_not_yet_observed' if times else
                'validated_commit_not_sampled_current' if commits else
                (last_g['reason'] or ('committed_without_current_read_evidence' if last_g['published_at'] else last_g['disposition'])) if last_g else (attempts[0]['reason'] if attempts else dispositions[eid]['disposition'])))
        rows.append(row)
    initial={e['id'] for e in first['events']};all_ids={e['id'] for s in samples for e in s['events']}
    def group(ids):
        return dict(identities=len(ids),observed=len(ids&all_ids),sampled_current=len(ids&ever),
            no_sampled_current=sorted(ids-ever),final_offered=len(ids&{e['id'] for e in last['events']}))
    cap_times=[];commit_lags=[];lock_holds=[];mismatch=Counter()
    for g in ledger.values():
        f=g['facts'];t=g['trace']
        if t.get('captured_at') and g['completed_at']:cap_times.append((stamp(g['completed_at'])-stamp(t['captured_at'])).total_seconds())
        if f.get('commit_observed_at') and g['published_at']:commit_lags.append((stamp(f['commit_observed_at'])-stamp(g['published_at'])).total_seconds())
        if f.get('ingress_lock_held_ms') is not None:lock_holds.append(f['ingress_lock_held_ms'])
        for d in (f.get('validation_witness') or {}).get('mismatches',[]):
            a,b=d['before'],d['after']
            if a is None or b is None:mismatch['membership']+=1;continue
            for k in a:
                if a[k]!=b[k]:mismatch[k]+=1
    result=dict(**{k:v for k,v in summary.items() if k!='rows'},original_native=group(original_ids),broader_baseline=group(baseline_ids),
        observation_arrivals=group(all_ids-initial),new_to_historical_baseline=group(all_ids-baseline_ids),original_repeat_sampled=sum(len(r['sampled_current_generations'])>=2 for r in rows),
        original_multiple_current_samples=sum(r['current_samples']>=2 for r in rows),dispositions_at=final['at'],
        capture_to_calculation_completion_seconds=distribution(cap_times),publication_marker_to_commit_observed_seconds=distribution(commit_lags),
        ingress_lock_held_ms=distribution(lock_holds),validation_changed_fields=dict(mismatch),rows=rows)
    native_generations=[g for g in ledger.values() if original_ids.intersection(g['events'])]
    result['native_stage_timings']=dict(unique_generations=len(native_generations),
        capture_to_completion_seconds=distribution([(stamp(g['completed_at'])-stamp(g['trace']['captured_at'])).total_seconds()
            for g in native_generations if g['completed_at'] and g['trace'].get('captured_at')]),
        generation_admission_to_completion_seconds=distribution([(stamp(g['completed_at'])-stamp(g['admitted_at'])).total_seconds()
            for g in native_generations if g['completed_at']]),
        ingress_lock_wait_ms=distribution([g['facts']['ingress_lock_wait_ms'] for g in native_generations if g['facts'].get('ingress_lock_wait_ms') is not None]),
        ingress_lock_held_lower_bound_ms=distribution([g['facts']['ingress_lock_held_ms'] for g in native_generations if g['facts'].get('ingress_lock_held_ms') is not None]))
    result['sample_interval_seconds']=distribution([(stamp(b['at'])-stamp(a['at'])).total_seconds() for a,b in zip(samples,samples[1:])])
    result['field_comparison_baseline_resets']=[s['at'] for i,s in enumerate(samples) if i and s['summary'].get('field_comparison_available') is False]
    result['ordinary_native_reads']=dict(attempts=len(api_records),same_frame_without_refusal=len({eid for r in api_records if r.get('same_economic_revision') and r.get('no_frame_refusal') for eid in r['source_event_ids']}),
        successful_http_seconds=distribution([r['http']['seconds'] for r in api_records if r['http'].get('status')==200]))
    result['generation_ledger']=list(ledger.values())
    unfinished=[r for r in rows if not r['current_samples'] and r['disposition']['disposition']=='still_offered_and_eligible']
    result['oldest_original_without_sampled_current']=min((dict(source_event_id=r['source_event_id'],native_event_id=r['native_event_id'],
        first_scheduler_observation=r['latest_attempt']['first_attempt'],latest_attempt=r['latest_attempt']['last_attempt'],
        reason=r['remaining_blocker']) for r in unfinished if r['latest_attempt']),
        key=lambda r:stamp(r['first_scheduler_observation']),default=None)
    records={}
    for sample in samples:
        for r in (sample.get('ingress') or {}).get('records',[]):
            records[json.dumps(r,sort_keys=True)]=r
    result['ingress_bounded_operation_seconds']={key:distribution([r[key] for r in records.values() if r.get(key) is not None])
        for key in ('queue_seconds','prepare_seconds','precompute_seconds','commit_seconds','seconds')}
    result['maintenance_observations']=[dict(at=s['at'],maintenance=s.get('maintenance')) for i,s in enumerate(samples)
        if s.get('maintenance') and (i==0 or s.get('maintenance')!=samples[i-1].get('maintenance'))]
    result['limitations']=[v for v in result['limitations'] if not v.startswith('Raw field snapshots')]
    result['limitations'].extend(['Field rows and publication checks share one MVCC snapshot. Snapshot completion is a later wall-clock bound.',
        'Ingress timings are deduplicated bounded operation records, not an exhaustive per-event latency distribution.',
        'First scheduler observation is not uninterrupted wait time; retained but overtaken attempts can be marked passed.',
        'Generation records are incremental per sample; report reconstructs the full observed ledger.',
        'validation_ms includes projection and initial validation; ingress_lock_held_ms excludes final generation bookkeeping and commit.',
        'commit_observed_at is recorded after transaction exit. It bounds visibility above; validated_at is inside the transaction.',
        'After an observer resume, the first field comparison is a new baseline; changes across that gap are unknown. Runtime/engine must still match.',
        'Visibility intervals are sampled lower bounds; their adjacent samples bound transitions, not exact lifetimes.',
        'A validated commit candidate is not by itself proof of freshness, ordinary-read currentness, or sustained use.',
        'Per-event field counts cover every sampled offer; only 32 detailed sample witnesses and four per-publication mismatches are retained.',
        'Receipt to admission is not recoverable per event from aggregate ingress timing records; those timings remain separate.',
        'A publication current at successive samples may have been invalid between them; continuity is not assumed.'])
    Path(target).write_text(json.dumps(result,indent=2,default=str))
    lines=['# Original 68 native dispositions','',
        f"Interval: {first['at']} → {last['at']} ({result['seconds']:.1f} seconds).",'',
        'All original identities remain in the JSON report, including complete source-event hashes, membership transitions, exact generation lineage, timing witnesses and final dependency failures. Temporary absence is not retirement.','',
        '| Source | Native event | Final disposition | Generations | Calculations / reuses | Current samples / generations | Remaining blocker |',
        '| --- | --- | --- | ---: | ---: | ---: | --- |']
    for r in rows:
        lines.append(f"| {r['source']} | {r['native_event_id']} | {r['disposition']['disposition']} | {r['unique_generations']} | {r['calculations']} / {r['reuses']} | {r['current_samples']} / {len(r['sampled_current_generations'])} | {r['remaining_blocker'] or 'repeat current observed'} |")
    lines.extend(['',f"Complete machine-readable evidence: [{Path(target).name}]({Path(target).name}).",''])
    Path(target).with_suffix('.md').write_text('\n'.join(lines))
    print(json.dumps({k:result[k] for k in ('interval','seconds','samples','healthy_samples','original_native','original_repeat_sampled','storage','validation_changed_fields')},indent=2))


if __name__=='__main__':report(*sys.argv[1:])
