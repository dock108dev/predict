"""Reproduce the offline suite and all eight examples without overwriting old evidence."""
import json
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parents[2];out=root/'evidence/slice-8'
commands=[('tests',[sys.executable,'-m','unittest','discover','-s','tests','-v'])]
commands += [(module,[sys.executable,'-m','app.'+module]) for module in
    ('example','polymarket_us_example','prophetx_example','kalshi_example','novig_example','normalization_example','matching_example')]
commands += [('moneyline-example',[sys.executable,'-m','app.moneyline_example','--store',str(out/'captured-store.json')])]
runs=[]
for label,command in commands:
    log=out/(label+('.json' if label in ('normalization_example','matching_example','moneyline-example') else '.txt'))
    with log.open('w') as stream:
        result=subprocess.run(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT)
    runs.append({'command':command,'exit_code':result.returncode,'log':str(log.relative_to(root))})
    print(label,result.returncode,flush=True)
(out/'verification.json').write_text(json.dumps(runs,indent=2)+'\n')
if any(r['exit_code'] for r in runs):sys.exit(1)
