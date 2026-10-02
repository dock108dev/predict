#!/usr/bin/env python3
"""Offline verified negative indexes; no transport, prices, or resolution invented."""
import json,sys
from pathlib import Path
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.dashboard.native_reviews import historical_paths
from app.dashboard.session_history import verified
from app.dashboard.session_projection import stable
entries={}
for sid,folder in historical_paths().items():
 data=verified(folder,stream_flat=True);count=0;first=last=None;valid=True;finished=False
 for row in data['rows']:
  if first is None:first=row
  if finished or row['session_id']!=first['session_id']:valid=False
  finished=row['type']=='session_finished'
  last=row['type'];count+=row['type']=='product_resolution'
 if not valid or data['state']!='complete' or last!='session_finished' or count or (first['session_id']!=folder.name and not (folder/'session'/(first['session_id']+'.jsonl')).is_file()):continue
 files={str(p.relative_to(folder)):sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()}
 entries[str(folder.relative_to(ROOT))]=dict(session_id=first['session_id'],resolution_records=0,state='complete',files=files,qualification='Complete journal verified before indexing; negative resolution fact only')
d=dict(version='retained-empty-resolutions-1',collection_authorized=False,entries=entries);d['sha256']=stable(d);p=ROOT/'app/fixtures/retained-empty-resolution-index-v1.json';p.write_text(json.dumps(d,indent=2,sort_keys=True)+'\n');print(len(entries),'verified complete empty histories',p.stat().st_size,'bytes')
