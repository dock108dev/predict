"""Reproducible verification; writes only Slice 13 evidence and project test DBs."""
import hashlib,json,pathlib,subprocess,sys
root=pathlib.Path(__file__).resolve().parents[2]; out=root/'evidence/slice-13'
commands=[('javascript-syntax',['node','--check','app/dashboard/static/app.js']),('offline-tests',[sys.executable,'-m','unittest','discover','-s','tests','-v']),
          ('integration-tests',[sys.executable,'-m','unittest','discover','-s','integration_tests','-v'])]
commands += [(name,[sys.executable,'-m','app.'+name]) for name in ['example','polymarket_us_example','prophetx_example','kalshi_example','novig_example','normalization_example','matching_example','moneyline_example','fee_example','arbitrage_example','depth_example','storage_example']]
results=[]
for name,cmd in commands:
 r=subprocess.run(cmd,cwd=root,capture_output=True,text=True)
 (out/(name+'.txt')).write_text(r.stdout+r.stderr)
 results.append(dict(name=name,command=cmd,exit_code=r.returncode,log=name+'.txt',class_='PostgreSQL integration' if name in ('storage_example','integration-tests') else 'offline'))
 print(name,r.returncode,flush=True)
(out/'verification.json').write_text(json.dumps(results,indent=2)+'\n')
before=json.loads((out/'preserved-before.json').read_text())
changed=[p for p,h in before.items() if not (root/p).is_file() or hashlib.sha256((root/p).read_bytes()).hexdigest()!=h]
(out/'preservation.json').write_text(json.dumps(dict(checked=len(before),changed=changed,plan_unchanged='PLAN.md' not in changed,historical_evidence_unchanged=not any(p.startswith('evidence/') for p in changed),credentials='Existing named Keychain entries used server-side for authorized live collection; values not printed, hashed or changed.'),indent=2)+'\n')
raise SystemExit(any(x['exit_code'] for x in results) or bool(changed))
