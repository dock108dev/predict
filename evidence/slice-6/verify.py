"""Run offline verification and retain exact outputs and exit status."""
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
out=ROOT/'evidence/slice-6'
checks=[('tests.txt',['-m','unittest','discover','-s','tests','-v']),
        ('normalization-tests.txt',['-m','unittest','tests.test_normalization','-v'])]
checks += [(module+'-example.txt',['-m','app.'+module]) for module in ('example','polymarket_us_example','prophetx_example','kalshi_example','novig_example')]
checks += [('normalization-example.json',['-m','app.normalization_example'])]
results=[]
for filename,args in checks:
 start=datetime.now(timezone.utc).isoformat()
 with (out/filename).open('w') as f:
  p=subprocess.run([sys.executable,*args],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
 results.append({'command':[sys.executable,*args],'output':filename,'started_at_utc':start,'exit_code':p.returncode})
 print(filename,p.returncode,flush=True)
(out/'verification.json').write_text(json.dumps(results,indent=2)+'\n')
if any(r['exit_code'] for r in results):raise SystemExit(1)
