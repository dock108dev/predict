"""Independent supervisor: issue the explicit entry-point Stop at Start+240s once."""
import json,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parent
start=json.loads((root/'start-response.json').read_text())['started_monotonic']
while time.monotonic()<start+240:
    if (root/'attempt'/'validation.json').exists():
        (root/'stop-not-issued-early-termination.json').write_text(json.dumps(dict(elapsed=time.monotonic()-start,reason='session finalized before scheduled direct Stop'))+'\n')
        raise SystemExit(0)
    time.sleep(min(.1,max(0,start+240-time.monotonic())))
issued=time.monotonic()
r=subprocess.run([str(Path.cwd()/'.venv/bin/python'),'-m','app.collection.supervised_live','stop','--output',str(root/'attempt')],capture_output=True,text=True,timeout=5)
(root/'direct-stop-response.json').write_text(json.dumps(dict(invoked_elapsed=issued-start,completed_elapsed=time.monotonic()-start,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr),indent=2)+'\n')
print((root/'direct-stop-response.json').read_text(),flush=True)
