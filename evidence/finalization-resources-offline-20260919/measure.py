from pathlib import Path
from unittest.mock import patch
import json,tempfile,time
from hashlib import sha256
from app.collection.finalization import write_supplement
from app.collection.segmented import SegmentedJournal
from app.collection.supervised import NAME
from app.collection.supervised_live import identity
from tests.test_finalization_resources import Writes
source=Path('evidence/supervised-5m-live-20260916/attempt/validation.json')
# Read-only historical payload used solely as a representative serialization input.
value=json.loads(source.read_text())
with tempfile.TemporaryDirectory() as t:
    out=Path(t);writes=Writes();start=time.monotonic()
    with patch.object(Path,'open',lambda p,*a,**kw:writes(p,*a,**kw)):
        h=SegmentedJournal(out/'history',label='new offline synthetic resource measurement',output_root=out,profile_name=NAME)
        for i in range(4):
            h.save(dict(type='synthetic',index=i));h.rotate()
        h.finalizing=True;h.finish(cleanup_complete=True);closed=time.monotonic()
        receipt=write_supplement(out,h,value,started=start,closed=closed)
    files={str(p.relative_to(out)):p.stat().st_size for p in out.rglob('*') if p.is_file()}
    assert sum(files.values())==receipt['final_retained_output_bytes']
    assert writes.bytes==receipt['cumulative_application_file_write_bytes']
    assert receipt['status']=='complete'
    result=dict(scope='New offline verification only; no historical lifetime memory inference',input_sha256=sha256(source.read_bytes()).hexdigest(),receipt=receipt,actual_files=files,independent_successful_write_bytes=writes.bytes,independent_writes_by_path={str(Path(p).relative_to(out)):n for p,n in writes.by_path.items()},candidate=identity())
Path('/tmp/predict-finalization-audit/measurement.json').write_text(json.dumps(result,indent=2))
print(json.dumps(receipt,indent=2))
