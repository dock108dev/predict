"""Seal the offline source and verification identity; does not authorize acquisition."""
import json,tarfile
from pathlib import Path
from hashlib import sha256
from app.collection.native_approval import implementation,digest
OUT=Path('evidence/native-retained-coverage-20260930-v1')
def read(name):return json.loads((OUT/name).read_text())
app=implementation();entry=read('entry-implementation.json');identity=digest(app)
(OUT/'implementation.json').write_text(json.dumps(dict(sha256=identity,files=app,changed_since_entry=[n for n,h in app.items() if entry.get(n)!=h]),sort_keys=True,indent=2)+'\n')
files=[Path(n) for n in app]
files += [p for root in ('scripts/retained_native','tests') for p in Path(root).rglob('*') if p.is_file() and p.suffix in ('.py','.js','.cjs') and '__pycache__' not in p.parts]
files += [Path('docs/native-review-records.md'),Path('docs/native-retained-coverage.md')]
files += [p for p in (Path('pyproject.toml'),Path('requirements.txt')) if p.exists()]
files=sorted(set(files));manifest={str(p):sha256(p.read_bytes()).hexdigest() for p in files}
(OUT/'source-manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
with tarfile.open(OUT/'source-candidate.tar.gz','w:gz') as tar:
 for p in files:tar.add(p,arcname=str(p),recursive=False)
reopen=read('reopening-final.json');oracle=read('oracle-execution-final.json');preserve=read('preservation-result.json');assert all(x['returncode']==0 for x in reopen['execution']+oracle);assert len(reopen['records'])==23;assert preserve['passed'];assert len(read('source-checks.json')['checks'])==313
logs={'test-focused-sealed.log':39,'test-corpus-history-final.log':11,'test-history-selection-final.log':1,'test-routes-final.log':1,'test-63-review-v4.log':1,'test-scope.log':21}
for name,count in logs.items():
 text=(OUT/name).read_text();assert ('Ran '+str(count)+' test') in text and '\nOK\n' in text,name
value=dict(implementation_sha256=identity,source_archive_sha256=sha256((OUT/'source-candidate.tar.gz').read_bytes()).hexdigest(),source_manifest_sha256=sha256((OUT/'source-manifest.json').read_bytes()).hexdigest(),interpretation='native-book-comparison-4',python_tests=74,python_batches=logs,javascript_suites=6,javascript_log='test-js-final.log',real_source_reviews=313,fresh_process_original_and_derived_packages=23,independent_leg_checks=748,protected_original_files=preserve['protected_files'],changed_original_files=0,scope_cells=63,corpus=read('corpus-accounting.json')['summary'],qualification='Historical raw correspondence only; net/EV, execution, owner and commercial validation not qualified',authority='Local engineering/offline verification only; no new acquisition or credential authority',preserved_wku_projection_sha256={'original':'ec133aca72d787fd9d9d0d124370e964385e6ac3083f5cd5215b9b26e4075db4','native-book-comparison-2':'fce68c3545983d2a87381eadef9ceca39f2ced83017f7dffd23750901d88343c','native-book-comparison-3':'a6b63fe28c401db2607770c5ea32afd908971fa5ad555bba3fe8011d90c76e78'})
(OUT/'final-verification.json').write_text(json.dumps(value,sort_keys=True,indent=2)+'\n');print(identity)
