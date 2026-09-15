"""Record preservation and exact artifacts after successful verification."""
from pathlib import Path
import hashlib
import json
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'evidence/slice-6'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
baseline=json.loads((OUT/'preserved-before.json').read_text())
allowed={'README.md','pyproject.toml'}
changed=[p for p,h in baseline.items() if not (ROOT/p).exists() or digest(ROOT/p)!=h]
unexpected=sorted(set(changed)-allowed)
assert not unexpected,unexpected
historical=[p for p in baseline if p.startswith('evidence/')]
(OUT/'preservation.json').write_text(json.dumps({'checked_at_utc':datetime.now(timezone.utc).isoformat(),
    'baseline_files':len(baseline),'historical_evidence_files_checked':len(historical),
    'allowed_changed_existing_files':sorted(changed),'unexpected_changes':unexpected,
    'PLAN_unchanged':digest(ROOT/'PLAN.md')==baseline['PLAN.md'],
    'credentials_file_unchanged':digest(ROOT/'.env')==baseline['.env'],
    'all_historical_evidence_unchanged':all(digest(ROOT/p)==baseline[p] for p in historical)},indent=2)+'\n')
verification=json.loads((OUT/'verification.json').read_text())
assert len(verification)==8 and all(x['exit_code']==0 for x in verification)
files=list((ROOT/'app/normalization').glob('*.py'))+list((ROOT/'app/normalization').glob('*.json'))
files += [ROOT/p for p in ('app/normalization_example.py','tests/test_normalization.py','README.md','pyproject.toml','docs/slice-6.md')]
files += [p for p in OUT.iterdir() if p.is_file() and p.name!='manifest.json']
files += [ROOT.parent/'prediction_arb_next_steps.md']
records={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):digest(p) for p in sorted(files)}
(OUT/'manifest.json').write_text(json.dumps({'created_at_utc':datetime.now(timezone.utc).isoformat(),
    'identity_type':'sha256; no Git operations','artifacts':records},indent=2)+'\n')
print('Preserved',len(historical),'historical evidence files;',len(records),'artifact hashes recorded')
