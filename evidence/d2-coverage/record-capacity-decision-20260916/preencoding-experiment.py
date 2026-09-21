from pathlib import Path
import shutil,json,hashlib,subprocess,sys
out=Path('evidence/d2-coverage/record-capacity-decision-20260916');root=out/'preencoding';root.mkdir()
for n in ('app','tests','scripts'):shutil.copytree(n,root/n,ignore=shutil.ignore_patterns('__pycache__'))
(root/'evidence').symlink_to(Path('evidence').resolve(),target_is_directory=True)
p=root/'app/collection/continuous.py';s=p.read_text().replace("    journal_encoding = 'd2-zlib-row-1'\n",'').replace('n = len(packed(self.journal.encoded(record)).encode())+2048','n = len(packed(record).encode())+2048');p.write_text(s)
p=root/'app/dashboard/coverage_owner.py';p.write_text(p.read_text().replace('max(session.journal.bytes, session.journal.expanded_bytes)*6','session.journal.bytes*6'))
p=root/'app/collection/recovery.py';s=p.read_text().replace('    from .journal_encoding import decode, MAX_EXPANDED\n','').replace("rows=[];expanded=0",'rows=[]').replace("chain=expected;row=decode(item['row']);expanded+=len(packed(row).encode())\n        if expanded>MAX_EXPANDED:raise ValueError('saved expanded byte cap')\n        rows.append(row);offset+=len(line)","chain=expected;rows.append(item['row']);offset+=len(line)");p.write_text(s)
p=root/'app/collection/transport_session.py';s=p.read_text().replace('def __init__(self, path, *, encoding=None):','def __init__(self, path):').replace("        from .journal_encoding import VERSION\n        if encoding not in (None, VERSION):raise ValueError('unsupported journal encoding')\n        self.encoding=encoding; self.expanded_bytes=0\n",'')
a=s.index('    def encoded(self, row):');b=s.index('    def save(self, row):',a);s=s[:a]+s[b:]
s=s.replace('        original=row\n        row=self.encoded(row)\n','').replace('        self.expanded_bytes+=len(packed(original).encode())\n','').replace("self.terminal_acknowledged=original.get('type')", "self.terminal_acknowledged=row.get('type')").replace('    from .journal_encoding import decode, MAX_EXPANDED\n','').replace("rows=[]; expanded=0",'rows=[]')
s=s.replace("            previous=digest\n            row=decode(row)\n            expanded+=len(packed(row).encode())\n            if expanded>MAX_EXPANDED:raise ValueError('saved expanded byte cap')\n            rows.append(row)","            previous=digest; rows.append(row)")
s=s.replace("n=len(packed(self.journal.encoded(row)).encode()) if getattr(self.journal,'encoding',None) else len(packed(row).encode())",'n=len(packed(row).encode())').replace("            options={'encoding':self.journal_encoding} if getattr(self,'journal_encoding',None) else {}\n            self.journal=ObservationJournal(self.output/(self.sid+'.jsonl'),**options)","            self.journal=ObservationJournal(self.output/(self.sid+'.jsonl'))")
p.write_text(s)
base=json.load(open('evidence/d2-coverage/offline-repair-20260916/verification.json'))['source_sha256'];diff=[n for n,h in base.items() if hashlib.sha256((root/n).read_bytes()).hexdigest()!=h];assert not diff,diff
(out/'preencoding-identity.json').write_text(json.dumps(dict(source_hashes_matched=len(base),differences=diff,candidate='d42c27b914996c4f05376aaf3a1982998677e34211545550d95c345ec7bf0481'),indent=2))
command=[sys.executable,'-m','unittest','tests.test_e6_recovery.ReadOnlySurface','-v']
for label,cwd in [('preencoding',root),('current',Path.cwd())]:
 r=subprocess.run(command,cwd=cwd,capture_output=True,text=True,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'});(out/(label+'-legacy-tests.log')).write_text(r.stdout+r.stderr);print(label,r.returncode)
