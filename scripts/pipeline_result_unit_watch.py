"""Bounded fixed-runtime result-unit observation; no acquisition or controls."""
import argparse
from collections import Counter, OrderedDict
from datetime import timedelta
import gzip
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,stamp,hashed
from app.storage.current_games import engine_binding,observation_binding
from app.storage.latest_board import runtime,source_states,_control_barrier
from app.storage import observation_publication as publication
from app.storage.result_publication import validate,invalid
from app.collection.current_storage_policy import sql_usage


# Observer-only bounded memoization; never grants publication authority.
_metric_fingerprints = OrderedDict()


def required_metric_identity(generation, facts):
    if generation in _metric_fingerprints:
        _metric_fingerprints.move_to_end(generation)
        return _metric_fingerprints[generation]
    from app.storage.payload_codec import decode
    from app.storage.shared_json import loads
    from app.dashboard.comparison_board import entries,quote_key
    evidence=loads(decode(facts['selected_frame']))['financial']
    value=hashed({quote_key(q):dict(price=q['original']['value'],units=q['original']['units'],depth=q.get('depth'))
        for _,_,q in entries(evidence['state_inputs'])})
    _metric_fingerprints[generation]=value
    while len(_metric_fingerprints)>4096:_metric_fingerprints.popitem(last=False)
    return value


def sample():
    engine=engine_binding();binding=observation_binding()
    with connect() as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        at=db.execute('SELECT transaction_timestamp() at').fetchone()['at'].isoformat();end=stamp(at)+timedelta(hours=72)
        owner=runtime(db,at=at)
        states=source_states({r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status')},owner)
        events=db.execute('''SELECT e.id,e.provider,e.native_event_id,e.scheduled_start,
            count(o.contract_id) offers FROM current_event e LEFT JOIN current_contract c ON c.event_id=e.id
            LEFT JOIN current_offer o ON o.contract_id=c.id GROUP BY e.id''').fetchall()
        window={e['id'] for e in events if e['scheduled_start'] and stamp(at)<=stamp(e['scheduled_start'])<end}
        frame=publication.capture(db,states,compact='lazy',selector=dict(events=sorted(window),occurrences=[],shared=[]))
        frame['control_barrier']=_control_barrier(db)
        from app.comparison.estimated_policy import load
        policy=load().revision;rows=[];inventory={}
        with patch('app.storage.result_publication.observation_binding',return_value=binding):
            with db.cursor(name='unit_observer') as cursor:
                cursor.itersize=8
                cursor.execute('SELECT game_key,unit_id,generation_id,captured_at,calculated_at,published_at,facts FROM current_result_unit')
                for row in cursor:
                    facts=row.pop('facts');dep=facts['publication_dependencies'];members=set(dep['selector']['events'])
                    if not members&window:continue
                    check=validate(frame,facts,at=at,owner=owner,engine=engine,policy=policy)
                    reasons=sorted(set(check['all']+[r for section in ('observations','comparisons') for values in check[section].values() for r in values]))
                    # Exclude capture/expiry movement and receipt-only bookkeeping from
                    # changed-input delivery. Retain required quote, peer, metric
                    # and reference identities, including executable book depth.
                    semantic=dict(observations=dep.get('observations'),references=dep.get('references'),
                        metrics=dep.get('metric_identities'),peers=dep['result_unit'].get('peer_inputs'))
                    row.update(dependency_identity=hashed(semantic),semantic_dependencies=required_metric_identity(row['generation_id'],facts) if not invalid(check) else None,semantic_dependency_basis='native-quote-price-and-depth-v5',events=sorted(members),current=not invalid(check),reasons=reasons,
                        financial_state=facts.get('estimate_availability',{}).get('state'),
                        results={v:len(facts['boards'][v]['rows']) for v in ('ev','arbs')})
                    rows.append(row)
                    prior=inventory.get(row['game_key'])
                    if prior is None or row['captured_at']>prior['at']:
                        inventory[row['game_key']]=dict(at=row['captured_at'],units=facts.get('unit_inventory',[]))
        for row in db.execute("""SELECT game_key,facts->'result_unit_inventory' units,
            facts#>'{publication_dependencies,selector,events}' events,
            calculated_at AS at FROM latest_board WHERE facts ? 'result_unit_inventory'"""):
            if set(row['events'] or [])&window:
                current=inventory.get(row['game_key'])
                if current is None:inventory[row['game_key']]=dict(at=row['at'],units=row['units'],events=row['events'])
                else:current['events']=row['events']
        # Independent discovery takes precedence even when every unit deferred
        # and no latest-board or child publication can carry the inventory.
        from app.storage.result_inventory import current as inventory_current
        from app.storage.latest_board import runtime_identity
        visits={r['game_key']:r for r in db.execute('''SELECT game_key,
            count(*) FILTER(WHERE active) active_units,
            count(*) FILTER(WHERE active AND visits=0) never_visited,
            sum(visits) visits,min(last_visit) oldest_visit,max(last_visit) newest_visit,
            min(visit_order) oldest_order,max(visit_order) newest_order
            FROM current_result_work GROUP BY game_key''')}
        for row in db.execute('SELECT game_key,discovered_at,revision,events,dependencies,units,superseded_at,superseded_by FROM current_result_inventory'):
            if set(row['events'])&window:
                saved=row['dependencies']
                current=not row['superseded_at'] and inventory_current(frame,saved,engine=engine,policy=policy,owner=runtime_identity(owner),at=at)
                inventory[row['game_key']]=dict(at=row['discovered_at'],units=row['units'],events=row['events'],
                    revision=row['revision'],proof_current=current,unknown_current_inventory=not current and not row['superseded_at'],
                    superseded_at=row['superseded_at'],superseded_by=row['superseded_by'],
                    durable_visits=visits.get(row['game_key']))
        generations=db.execute("""SELECT id,game_key,events,admitted_at,last_attempt,completed_at,published_at,
            attempts,calculations,reuses,commits,disposition,reason,facts FROM pipeline_generation
            WHERE position('#result:' in game_key)>0 AND last_attempt>clock_timestamp()-interval '40 minutes'""").fetchall()
        bytes_used=sql_usage(db)
        signatures={cid:[r['offer_revision'],r['source_at'],r['received_at'],r['contract_dependency'],
            frame['books'].get((r['venue'],r['event_id'],r['native_market_id']),{}).get('revision'),r['venue'],r['event_id']]
            for cid,r in frame['offers'].items()}
    return dict(at=at,engine=engine,runtime={k:owner.get(k) for k in ('runtime_id','healthy','active','global_stopped','paused_sources','calculations','heartbeat_at')},
        events=events,window=sorted(window),units=rows,inventory=inventory,generations=generations,storage_bytes=bytes_used,inputs=signatures)


def run(folder,seconds,interval):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    start=time.monotonic();identity=None;summaries=[];total_bytes=0;prior_inputs={};prior_generations={}
    while True:
        tick=time.monotonic();value=sample();elapsed=time.monotonic()-start
        current=(value['engine'],value['runtime']['runtime_id'])
        if identity is not None and current!=identity:raise RuntimeError('fixed_runtime_or_engine_changed')
        identity=current
        inputs=value['inputs'];value['inputs']={k:v for k,v in inputs.items() if prior_inputs.get(k)!=v}
        value['removed_inputs']=sorted(set(prior_inputs)-set(inputs));value['inputs_complete']=not summaries
        prior_inputs=inputs
        changes=[]
        for generation in value['generations']:
            fingerprint=json.dumps(generation,default=str,sort_keys=True)
            if prior_generations.get(generation['id'])!=fingerprint:
                changes.append(generation);prior_generations[generation['id']]=fingerprint
        value['generations']=changes
        data=gzip.compress(json.dumps(value,default=str,separators=(',',':')).encode())
        total_bytes+=len(data)
        if total_bytes>256*1024*1024:raise RuntimeError('observer_storage_cap')
        (folder/f'sample-{len(summaries):04}.json.gz').write_bytes(data)
        summary=dict(at=value['at'],elapsed=elapsed,sample_seconds=time.monotonic()-tick,storage_bytes=value['storage_bytes'],
            healthy=value['runtime']['healthy'],units=len(value['units']),current=sum(u['current'] for u in value['units']),
            financial=dict(Counter(u['financial_state'] for u in value['units'])),bytes=total_bytes)
        summaries.append(summary);(folder/'summary.json').write_text(json.dumps(summaries,indent=2))
        print(json.dumps(summary),flush=True)
        if elapsed>=seconds:break
        time.sleep(max(.1,interval-(time.monotonic()-tick)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');p.add_argument('--seconds',type=int,default=1505);p.add_argument('--interval',type=float,default=5)
    a=p.parse_args();run(a.folder,a.seconds,a.interval)
