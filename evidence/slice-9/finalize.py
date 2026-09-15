"""Record preservation and final artifact hashes after verification."""
from pathlib import Path
import json,hashlib,datetime
root=Path.cwd(); out=root/'evidence/slice-9'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
baseline=json.loads((out/'baseline.json').read_text())
changed=[name for name,h in baseline.items() if not (root/name).exists() or sha(root/name)!=h]
allowed=['README.md']
unexpected=[name for name in changed if name not in allowed]
(out/'preservation.json').write_text(json.dumps(dict(checked_at=datetime.datetime.now(datetime.UTC).isoformat(),baseline_files=len(baseline),changed=changed,allowed_changes=allowed,unexpected_changes=unexpected,credentials='not read or modified; excluded from hash collection'),indent=2)+'\n')
if unexpected: raise SystemExit(str(unexpected))
paths=[root/'app/fees/__init__.py',root/'app/fees/engine.py',root/'app/fixtures/fee-schedules-v1.json',root/'app/fee_example.py',root/'tests/test_fees.py',root/'docs/slice-9.md',root/'README.md',root.parent/'prediction_arb_next_steps.md']
paths += [p for p in out.rglob('*') if p.is_file() and p.name!='manifest.json']
(out/'manifest.json').write_text(json.dumps(dict(created_at=datetime.datetime.now(datetime.UTC).isoformat(),artifacts=[dict(path=str(p.relative_to(root)) if p.is_relative_to(root) else str(p),sha256=sha(p),bytes=p.stat().st_size) for p in sorted(paths)]),indent=2)+'\n')
print('Preserved',len(baseline),'baseline files; changed',changed)
