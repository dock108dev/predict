"""Run only offline tests/examples; preserve logs in this slice's evidence directory."""
import subprocess,json,pathlib,sys,hashlib
root=pathlib.Path.cwd(); out=root/'evidence/slice-11'; results=[]
commands=[('tests',[sys.executable,'-m','unittest','discover','-s','tests','-v'])]
commands += [(name,[sys.executable,'-m','app.'+name]) for name in ['example','polymarket_us_example','prophetx_example','kalshi_example','novig_example','normalization_example','matching_example','moneyline_example','fee_example','arbitrage_example','depth_example']]
for name,cmd in commands:
    r=subprocess.run(cmd,capture_output=True,text=True)
    path=out/(name+'.txt'); path.write_text(r.stdout+r.stderr)
    if name=='depth_example' and r.returncode==0: (out/'depth-example.json').write_text(r.stdout)
    results.append(dict(command=cmd,exit_code=r.returncode,log=str(path.relative_to(root))))
    print(name,r.returncode,flush=True)
(out/'verification.json').write_text(json.dumps(results,indent=2)+'\n')
before=json.loads((out/'preserved-before.json').read_text())
changed=[p for p,h in before.items() if not (root/p).is_file() or hashlib.sha256((root/p).read_bytes()).hexdigest()!=h]
allowed=['app/arbitrage_example.py','app/fees/engine.py']
preservation=dict(checked=len(before),changed=changed,authorized_implementation_changes=allowed,unexpected_changes=[p for p in changed if p not in allowed],plan_unchanged='PLAN.md' not in changed,historical_evidence_unchanged=not any(p.startswith('evidence/') for p in changed),credentials='Not read or changed; excluded from hashing.')
(out/'preservation.json').write_text(json.dumps(preservation,indent=2)+'\n')
raise SystemExit(any(r['exit_code'] for r in results) or bool(preservation['unexpected_changes']))
