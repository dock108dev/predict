"""Reconcile preserved historical source-event observations with a frozen run."""
import json,sys
from collections import Counter
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.storage.store import stamp


def runtime_available(sample):
 runtime=sample['runtime']
 return (runtime['healthy'] and runtime['active']
  and runtime.get('calculation_state')=='running' and runtime.get('observation_state')=='running')


def publication_current(publication,sample):
 return (publication['selected'] and publication['engine']==sample['engine']
  and publication['dependency_current'] and publication['retained_only']!='true'
  and not any(publication.get('dependency_failures',{}).values())
  and (not publication.get('valid_until') or stamp(publication['valid_until'])>stamp(sample['at']))
  and runtime_available(sample))


def report(directory, run_name="frozen-selected-cohort.json"):
 folder=Path(directory);historical=json.loads((folder/'historical-83.json').read_text())
 run=json.loads((folder/run_name).read_text());first,last=run['records'][0],run['records'][-1]
 current={r['id']:r for r in last['events']};attempts={(r['event_id'],r['branch']):r for r in last['attempts']}
 events=[]
 dispositions={'queued':('eligible pending','queue admission','Wait for the metrics scheduler to select this complete component'),
  'background_capture_changed':('deferred','capture reservation','Replan and admit the actual expanded component under the memory guard'),
  'membership_changed':('deferred','publication validation','Capture and calculate/reuse the new complete peer membership'),
  'attempt_LockNotAvailable':('deferred','SQL lock acquisition','Retry the component after the ingress transaction releases its lock'),
  'scheduled':('unknown','after scheduling; no completed attempt recorded','Identify interrupted/cancelled worker or finish its pending attempt'),
  'published':('unknown','publication replaced under a different game key','Reconcile changed occurrence membership; the historical full dependencies were not captured')}
 for r in historical['rows']:
  eid=r['event']['id'];h=r['historical_attempt'];d,stage,action=('published','publication commit','Revalidate current dependencies on the ordinary read') if r['published_current_engine'] else dispositions.get(h['reason'],('unknown','unrecorded','Recover owner evidence'))
  pubs=[p for p in last['publications'] if eid in (p['publication_events'] or []) and p['selected']]
  a=attempts.get((eid,'metrics'))
  current_engine=any(p['engine']==last['engine'] for p in pubs)
  current_valid=any(publication_current(p,last) for p in pubs)
  revisions=[next((e['semantic_revision'] for e in sample['events'] if e['id']==eid),None) for sample in run['records']]
  changes=sum(x!=y for x,y in zip(revisions,revisions[1:]))
  if current_valid:current_disposition='published';current_reason='selected_current_engine_and_dependency_valid'
  elif not runtime_available(last):current_disposition='deferred';current_reason='runtime_authority_unavailable'
  elif eid not in current:current_disposition='unknown';current_reason='not_in_current_offered_72_hour_population; inspect withdrawal/start separately'
  elif a and a['reason']=='queued':current_disposition='eligible pending';current_reason='never_selected_this_engine'
  elif a and a['reason']=='scheduled':current_disposition='eligible pending';current_reason='scheduled_without_completed_attempt; active_or_interrupted_worker'
  elif a and a['reason'].startswith('attempt_'):current_disposition='deferred';current_reason=a['reason']
  elif changes>1:current_disposition='repeatedly invalidated';current_reason='observed_component_dependency_changes'
  else:current_disposition='eligible pending';current_reason='publication_requires_dependency_revalidation_or_new_engine'
  lineage=[g for g in last['generations'] if eid in (g['events'] or [])]

  events.append(dict(source_event_id=eid,source=r['event']['provider'],native_event_id=(r.get('identity') or {}).get('native_event_id'),league=r['event']['competition'],
    historical_input_revision=r['event']['revision'],historical_offer_book_revision=r['event']['inputs'],
    historical_disposition=d,historical_stage=stage,historical_queue_first_entry=h['first_attempt'],historical_last_attempt=h['last_attempt'],
    historical_pending_age_seconds=None if d=='published' else (stamp(historical['interval'][1])-stamp(h['first_attempt'])).total_seconds(),
    historical_reason=h['reason'],historical_attempts=h['attempts'],historical_details=h['facts'],historical_publications=r['historical_publications'],
    historical_full_dependencies='unrecorded; stable event/offer/book hashes do not establish stable peer/model/expiry dependencies',
    current_event=current.get(eid),current_attempt=a,current_publications=pubs,current_engine=current_engine,
    current_disposition=current_disposition,current_reason=current_reason,observed_dependency_changes=changes,generation_lineage=lineage,
    current_queue_age_seconds=(end_age if (end_age:=(stamp(last['at'])-stamp(a['first_attempt'])).total_seconds())>=0 else None) if a and not current_valid else None,
    current_dependency_valid=current_valid,
    historical_next_action=action,owner='app.storage.latest_board.reconcile; app.storage.board_capture',
    missing_historical_evidence=['exact generation identity','full candidate/reference dependency manifest','individual worker cancellation time','invalidation history','ordinary row render selection']))
 begin=stamp(first['at']);end=stamp(last['at']);duration=(end-begin).total_seconds()
 observed_components=[];seen_components=set();component_arrivals=[]
 for sample in run['records']:
  values={(tuple(e['component']),e['semantic_revision']) for e in sample['events']}
  new=values-seen_components
  component_arrivals.append(dict(at=sample['at'],newly_observed=len(new),current=len(values)))
  seen_components.update(values);observed_components.append(values)
 observed_arrivals=len(seen_components-observed_components[0])
 old={r['id']:r for r in first['generations']};gens=[r for r in last['generations'] if r['engine']==first['engine']]
 admitted=[g for g in gens if begin<=stamp(g['admitted_at'])<=end]
 completed=[g for g in gens if g['completed_at'] and begin<=stamp(g['completed_at'])<=end]
 committed=[g for g in gens if g['published_at'] and begin<=stamp(g['published_at'])<=end]
 event_metadata={e['id']:e for sample in run['records'] for e in sample['events']}
 completed_cells={}
 for generation in completed:
  for eid in generation['events'] or []:
   event=event_metadata.get(eid)
   if event is None:continue
   for family in event['families']:
    cell=(event['provider'],event['competition'],str(family))
    completed_cells.setdefault(cell,set()).add(generation['id'])
 delta=lambda field:sum(g[field]-old.get(g['id'],{}).get(field,0) for g in gens)
 waits=[(stamp(g['published_at'])-stamp(g['admitted_at'])).total_seconds() for g in committed]
 ledger=dict(unit='semantic game-comparison bundle generation; not source events, individual outcomes, pairs or result rows',
    admitted_unique=len(admitted),completed_unique=len(completed),first_committed_unique=len(committed),
    completed_calculation_attempts=delta('calculations'),reuse_validations=delta('reuses'),publication_commits=delta('commits'),
    repeated_generation_commits=delta('commits')-len(committed),
    repeated_calculations_same_generation=sum(max(0,g['calculations']-max(1,old.get(g['id'],{}).get('calculations',0))) for g in gens),
    committed_result_rows={kind:sum((g.get('facts') or {}).get('result_rows',{}).get(kind,0) for g in committed) for kind in ('ev','arbs')},
    committed_generation_source_events=len({eid for g in committed for eid in g['events'] or []}),
    completed_by_source_league_family=[dict(source=k[0],league=k[1],family=k[2],unique_generations=len(v)) for k,v in sorted(completed_cells.items())],
    duplicate_admission_attempts=delta('attempts')-len(admitted),
    dispositions=dict(Counter(g['disposition'] for g in gens)),
    arrivals_per_minute=len(admitted)*60/duration,completions_per_minute=len(completed)*60/duration,
    first_commit_latency_seconds=dict(min=min(waits,default=None),max=max(waits,default=None)),
    limits=['Admission clock starts at calculation bundle capture, not first ingress or queue time.',
      'Fast validated reuse is counted separately; first publication can be retained superseded evidence, not current authority.',
      'A captured game bundle covers all its result rows. This ledger does not claim per-pair generation throughput.',
      'Completed calculation workflows include explicit unavailable outcomes; result-row totals do not establish numeric or currently eligible financial results.',
      'Repeated-generation commits are separate from first commits. An output-content hash is not recorded, so byte-identical output republication is not independently proven.',
      'Terminal ledger history is bounded to two hours/50,000 entries; frozen exports retain observed history.'])
 # Preserve every initially offered event and every later entrant, including
 # events whose dependency changes remove them from the fixed stable subset.
 population={}; histories={}; timeline=[]
 for sample in run['records']:
  offered={e['id']:e for e in sample['events']}
  valid={eid for p in sample['publications'] if publication_current(p,sample) for eid in p['publication_events'] or []}
  for eid,e in offered.items():
   population.setdefault(eid,e)
   histories.setdefault(eid,[]).append(dict(at=sample['at'],revision=e['semantic_revision'],valid=eid in valid))
  stable=set(sample['summary']['stable_ids']); pending=stable-valid
  timeline.append(dict(at=sample['at'],stable=len(stable),stable_pending=len(pending),
    stable_current=len(stable&valid),oldest_stable_pending_seconds=(stamp(sample['at'])-begin).total_seconds() if pending else 0,
    offered=len(offered),selected_current_valid=len(set(offered)&valid)))
 cohort=[];initial_ids={e['id'] for e in first['events']};stable_ids=set(last['summary']['stable_ids'])
 for eid,e in population.items():
  history=histories[eid];a=attempts.get((eid,'metrics'));lineage=[g for g in gens if eid in (g['events'] or [])]
  pubs=[p for p in last['publications'] if eid in (p['publication_events'] or []) and p['selected']]
  valid=any(publication_current(p,last) for p in pubs)
  changes=sum(x['revision']!=y['revision'] for x,y in zip(history,history[1:]))
  reason=(a or {}).get('reason','no_attempt_record')
  disposition=('published' if valid else 'deferred' if not runtime_available(last) else 'unknown' if eid not in current else
    'deferred' if reason.startswith('attempt_') or reason=='background_capture_changed' else
    'eligible pending' if reason in ('queued','scheduled') else
    'repeatedly invalidated' if changes>1 else 'eligible pending')
  first_valid=next((h['at'] for h in history if h['valid']),None)
  cohort.append(dict(source_event_id=eid,source=e['provider'],native_event_id=e['native_event_id'],league=e['competition'],
    families=e['families'],initial=eid in initial_ids,stable=eid in stable_ids,still_offered=eid in current,
    initial_component=e['component'],initial_revision=e['semantic_revision'],current_revision=current.get(eid,{}).get('semantic_revision'),
    disposition=disposition,reason='selected_current_engine_dependency_valid' if valid else 'runtime_authority_unavailable' if not runtime_available(last) else reason,
    first_observed_generation_disposition='published' if any(h['valid'] and h['revision']==history[0]['revision'] for h in history) else 'superseded' if changes else disposition,
    first_observed=history[0]['at'],first_valid_publication_observed=first_valid,
    observed_time_to_publication_seconds=(stamp(first_valid)-stamp(history[0]['at'])).total_seconds() if first_valid else None,
    dependency_changes=changes,attempt=a,generation_ids=[g['id'] for g in lineage],publications=pubs,
    pending_observation_age_seconds=(end-stamp(history[0]['at'])).total_seconds() if not valid else 0))
 coverage=Counter()
 for e in cohort:
  for family in e['families']:
   coverage[(e['source'],e['league'],str(family),e['disposition'])]+=1
 (folder/(Path(run_name).stem+'-population.json')).write_text(json.dumps(dict(
   unit='source events; family counts overlap',rows=cohort,timeline=timeline,
   source_league_family=[dict(source=k[0],league=k[1],family=k[2],disposition=k[3],events=v) for k,v in sorted(coverage.items())],
   limits=['Observed at sample cadence, not continuous dependency history.',
     'Age starts at observation; scheduler first-entry age remains separately available in attempts.',
     'Absent events require separate withdrawal/start diagnosis; they are not silently excluded.']),indent=2))
 result=dict(historical_interval=historical['interval'],historical_engine=historical['engine'],historical_count=len(events),
   historical_dispositions=dict(Counter(r['historical_disposition'] for r in events)),rows=events,
   fixed_initial_population=dict(events=len(initial_ids),dispositions=dict(Counter(e['disposition'] for e in cohort if e['initial']))),
   subsequent_population_entrants=dict(events=len(population)-len(initial_ids),dispositions=dict(Counter(e['disposition'] for e in cohort if not e['initial']))),
   continuously_unchanged_subset=dict(events=len(stable_ids),dispositions=dict(Counter(e['disposition'] for e in cohort if e['stable'])),
    note='Subset of the fixed initial population; every changed or absent initial event remains in the population export.'),
   frozen_summary=last['summary'],engine_constant=len({r['engine'] for r in run['records']})==1,
   runtime_constant=len({r['runtime']['runtime_id'] for r in run['records']})==1,seconds=duration,ledger=ledger,
   observed_semantic_arrivals=dict(unit='observed complete candidate-component revision; distinct from ledger game-bundle generation',
    initial=len(observed_components[0]),new_after_initial=observed_arrivals,per_minute=observed_arrivals*60/duration,
    timeline=component_arrivals,limits=['Sample-cadence lower bound; intermediate changes can be missed.',
     'Component signatures include full observed peer identities and authority/freshness state; they are not price-tick counts.',
     'Changed generations can be superseded before worker admission. Admission/completion rates alone do not measure ingress arrival rate.']))
 (folder/'reconciliation.json').write_text(json.dumps(result,indent=2))
 print(json.dumps({k:v for k,v in result.items() if k not in ('rows',)},indent=2))
if __name__=='__main__':report(sys.argv[1] if len(sys.argv)>1 else ROOT/'test-results/d02-convergence',sys.argv[2] if len(sys.argv)>2 else 'frozen-selected-cohort.json')
