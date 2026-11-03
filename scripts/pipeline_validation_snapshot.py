"""Read-only exact failed dependency identities, never an acquisition trigger."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,stamp
from app.storage.current_games import utc,engine_binding
from app.storage.latest_board import runtime,source_states
from app.storage import observation_publication as p

def run(path):
 with connect() as db,db.transaction():
  db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
  at=utc();owner=runtime(db);states=source_states({r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status')},owner)
  status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts'];games={g['game_key'] for g in status['games']}
  pubs=db.execute("SELECT game_key,publication_events,facts#>>'{context,engine_binding}' engine,coalesce(facts->'financial_dependencies',facts->'publication_dependencies') dependencies,facts->>'valid_until' valid_until,facts->>'retained_financial_only' retained_only,facts->>'calculation_error' calculation_error,facts->'estimate_availability' estimate_availability FROM latest_board WHERE game_key=ANY(%s)",(list(games),)).fetchall()
  ids=sorted({eid for r in pubs for eid in r['publication_events'] or []});frame=p.capture(db,states,compact='lazy',selector=dict(events=ids,occurrences=[],shared=[]));rows=[]
  for pub in pubs:
   saved=pub.pop('dependencies');checks=p.reasons(frame,saved) if saved else dict(all=['missing_manifest'],observations={},comparisons={});failures=[]
   for section in ('observations','comparisons','benchmarks','benchmark_identity'):
    for cid,reasons in checks.get(section,{}).items():
     if not reasons:continue
     offer=frame['offers'].get(cid);event=frame['events'].get(offer['event_id']) if offer else None
     failures.append(dict(section=section,contract_id=cid,reasons=reasons,
       source=None if event is None else event['provider'],native_event_id=None if event is None else event['native_event_id'],
       current_offer=offer,recorded_observation_hash=(saved or {}).get('observations',{}).get(cid),
       current_observation_hash=p.own(frame,cid),recorded_metric_identity=(saved or {}).get('metric_identities',{}).get(cid),current_metric_identity=p.metric_identity(frame,cid)))
   rows.append(dict(pub,common_reasons=checks['all'],expired=bool(pub['valid_until'] and stamp(pub['valid_until'])<=stamp(at)),failed_dependencies=failures,
     next_action='Capture and calculate/reuse the newest complete component; old dependency hashes cannot authorize current results' if failures or checks['all'] else 'Respect temporal and financial eligibility; dependency validation passes'))
  Path(path).write_text(json.dumps(dict(at=at,engine=engine_binding(),rows=rows),indent=2,default=str));print('selected publications',len(rows),'with dependency failures',sum(bool(r['failed_dependencies'] or r['common_reasons']) for r in rows))
if __name__=='__main__':run(sys.argv[1])
