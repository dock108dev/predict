"""Fresh-process exact B6 prefix, original native packet and calculation audit."""
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import json
import statistics
import sys
import time
from tests.b6_integrated import calculations_at,digest,save
from app.dashboard import session_history
from app.collection.transport_session import reopen
from app.dashboard.coverage_owner import replay_groups

def verify(root):
    root=Path(root);result=[];cadences=defaultdict(list);health=[]
    for oracle_path in sorted((root/'sessions').glob('*/b6-oracle.json')):
        folder=oracle_path.parent;oracle=json.loads(oracle_path.read_text());start=time.monotonic()
        snap=session_history.load(folder,oracle['cutoff']);load_seconds=time.monotonic()-start
        actual=json.loads(json.dumps({k:snap[k] for k in oracle['snapshot_fields']}))
        assert actual==oracle['snapshot_fields'],folder
        assert json.loads(json.dumps(calculations_at(snap)))==oracle['calculations'],folder
        saved=reopen(folder/(folder.name+'.jsonl'));native=replay_groups(saved)
        assert native==json.loads((folder/'replay.json').read_text()),folder
        previous={};counts=defaultdict(int)
        for row in saved['rows']:
            if row['type']=='prediction_book':
                kind='reviewed-projection' if row.get('b6_input') else 'native'
                key=(row['source'],kind,row['book']['raw']['ref']['market_id'])
                at=datetime.fromisoformat(row['observed_at'])
                if key in previous:cadences[row['source']+'/'+kind].append((at-previous[key]).total_seconds())
                previous[key]=at;counts[row['source']+'/'+kind]+=1
            if row['type']=='source_health' and row['state'] not in ('connected','awaiting_snapshot'):
                health.append(dict(session=folder.name,source=row['source'],state=row['state'],reason=row.get('gap_reason'),at=row['observed_at']))
        final=session_history.load(folder)
        assert final['state']=='saved' and final['stop_reason']=='manual_stop'
        result.append(dict(session=folder.name,exact_snapshot=True,exact_calculations=True,exact_native_replay=True,
            reopen_seconds=load_seconds,books=dict(counts),rows=len(saved['rows']),snapshot_sha256=digest(actual),calculation_sha256=digest(oracle['calculations'])))
    assert result,'No completed oracles'
    summary=dict(sessions=result,cadence={k:dict(count=len(v),minimum=min(v),median=statistics.median(v),maximum=max(v)) for k,v in cadences.items()},health_events=health,
        measurement_boundary='Wall receipt intervals within each segment and each market only; no across-session concatenation. Reopen is local parse/validation/projection time, excluding browser rendering. No provider delivery qualification.')
    save(root/'fresh-process-verification.json',summary)
    print(json.dumps(dict(verified_sessions=len(result),exact=True,reopen_seconds=[r['reopen_seconds'] for r in result],cadence=summary['cadence']),indent=2))

if __name__=='__main__':verify(sys.argv[1])
