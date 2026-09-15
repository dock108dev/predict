"""Reproduce offline Slice 7 verification; run from the project root."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[2]
out=root/'evidence/slice-7'
runs=[]
commands=[('tests',[sys.executable,'-m','unittest','discover','-s','tests','-v'])]
commands += [(module,[sys.executable,'-m','app.'+module]) for module in
             ('example','polymarket_us_example','prophetx_example','kalshi_example','novig_example','normalization_example')]
commands += [('matching-example',[sys.executable,'-m','app.matching_example','--store',str(out/'captured-store.json')])]
for label,command in commands:
    suffix='.json' if label in ('normalization_example','matching-example') else '.txt'
    log=out/(label+suffix)
    with log.open('w') as stream:
        result=subprocess.run(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT)
    runs.append({'command':command,'exit_code':result.returncode,'log':str(log.relative_to(root))})
    print(label,result.returncode,flush=True)
(out/'verification.json').write_text(json.dumps(runs,indent=2)+'\n')
if any(r['exit_code'] for r in runs): sys.exit(1)
