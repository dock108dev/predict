"""Offline verification; run from repository root."""
import subprocess,json,pathlib,sys
root=pathlib.Path.cwd(); out=root/'evidence/slice-10'; results=[]
commands=[('tests',[sys.executable,'-m','unittest','discover','-s','tests','-v'])]
commands += [(name,[sys.executable,'-m','app.'+name]) for name in ['example','polymarket_us_example','prophetx_example','kalshi_example','novig_example','normalization_example','matching_example','moneyline_example','fee_example','arbitrage_example']]
for name,cmd in commands:
 r=subprocess.run(cmd,capture_output=True,text=True)
 path=out/(name+'.txt'); path.write_text(r.stdout+r.stderr)
 results.append(dict(command=cmd,exit_code=r.returncode,log=str(path.relative_to(root))))
 print(name,r.returncode,flush=True)
(out/'verification.json').write_text(json.dumps(results,indent=2)+'\n')
raise SystemExit(any(r['exit_code'] for r in results))
