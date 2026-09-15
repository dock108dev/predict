"""Record exact artifacts and verify pre-Slice-7 files remain preserved."""
from pathlib import Path
from hashlib import sha256
import json
import re

root=Path(__file__).resolve().parents[2]
out=root/'evidence/slice-7'
def fingerprint(p):return sha256(p.read_bytes()).hexdigest()
before=json.loads((out/'preserved-before.json').read_text())
allowed={'README.md'}
changed=[name for name,h in before.items() if not (root/name).exists() or fingerprint(root/name)!=h]
assert set(changed)<=allowed,changed
preservation={'baseline_files':len(before),'changed_existing_files':changed,
    'all_other_baseline_files_unchanged':True,
    'preserved_plan_sha256':fingerprint(root/'PLAN.md'),
    'new_paths':['app/matching.py','app/matching_example.py','tests/test_matching.py','docs/slice-7.md','evidence/slice-7/'],
    'external_tracker_updated':str(root.parent/'prediction_arb_next_steps.md')}
(out/'preservation.json').write_text(json.dumps(preservation,indent=2)+'\n')
verification=json.loads((out/'verification.json').read_text())
assert len(verification)==8 and all(r['exit_code']==0 for r in verification)
log=(out/'tests.txt').read_text()
assert re.search(r'Ran 176 tests .*\n\nOK',log)
report=json.loads((out/'matching-example.json').read_text())
summary={'matcher_version':'event-matcher-1','schema_version':1,'tests_passed':176,
         'focused_matcher_tests':25,'examples_passed':7,'coverage':report['coverage'],
         'next_action':'Slice 8 — moneyline market matching','slice_8_started':False,
         'external_dependencies':'ProphetX limitations and Novig live qualification remain separate.'}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
files=[root/name for name in ('app/matching.py','app/matching_example.py','tests/test_matching.py','docs/slice-7.md','README.md')]
files += sorted(p for p in out.iterdir() if p.is_file() and p.name!='manifest.json')
files += [root.parent/'prediction_arb_next_steps.md']
manifest=[{'file':str(p.relative_to(root)) if p.is_relative_to(root) else str(p),
           'sha256':fingerprint(p),'bytes':p.stat().st_size} for p in files]
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(summary,indent=2))
print('Preservation passed:',len(before),'baseline files;',len(manifest),'artifacts identified.')
