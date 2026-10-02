"""Build inert package or explicitly classified offline rehearsal. No transport/access."""
import json,sys,uuid
from pathlib import Path
from datetime import datetime,timezone
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from app.collection.native_approval import digest,implementation
OLD=ROOT/'evidence/native-nyi-tor-20260930-v2';TEMPLATES=Path(__file__).parent

def build(folder,attempt_id=None,*,offline=False):
    folder=Path(folder).resolve();folder.mkdir(exist_ok=False)
    old=json.loads((OLD/'identity.json').read_text());attempt_id=attempt_id or str(uuid.uuid4())
    output=ROOT/'evidence'/('OFFLINE-native-binding-session-' if offline else 'native-nyi-tor-binding-attempt-')
    output=output.with_name(output.name+attempt_id)
    assert not output.exists()
    impl=implementation();spec=json.loads((OLD/'run-spec.json').read_text())
    # Scope and semantic records unchanged; binding schema is an engineering boundary.
    implhash=digest(impl);spechash=digest(spec)
    for n in ('limits.json','request-plan.json','review-templates.json','field-policy.json'):(folder/n).write_bytes((OLD/n).read_bytes())
    for n in ('launch.py','control.py','supervise.py','binding-schema.json'):(folder/n).write_bytes((TEMPLATES/n).read_bytes())
    values={'run-spec.json':spec,'attempt.json':dict(attempt_id=attempt_id,output=str(output),status='OFFLINE_REHEARSAL' if offline else 'UNUSED_UNAPPROVED'),'implementation.json':impl}
    now=datetime.now(timezone.utc);window=json.loads((OLD/'window.json').read_text());window.update(prepared_at=now.isoformat(),sealed_at=now.isoformat(),expired_at_sealing=now.isoformat()>spec['start_before'])
    values['window.json']=window
    for n,v in values.items():(folder/n).write_text(json.dumps(v,indent=2)+'\n')
    specification=(OLD/'SPECIFICATION.md').read_text().replace(old['implementation_sha256'],implhash).replace(old['attempt_id'],attempt_id).replace(old['output'],str(output))
    specification+='\n## Integrated control binding\n\n`native-control-binding-v1` validates bounded public identity JSON before preserving exact values for binding. Every hash is compared, including AUTHORIZATION.txt. Redaction remains on ordinary responses and saved records. Pre-Start refusal invokes ordinary Stop/status/diagnostics and closes the owned server. Activation, dispatch and Start consumption are separate durable states; an activated refused attempt is retired without fabricated dispatch.\n'
    (folder/'SPECIFICATION.md').write_text(specification)
    auth=(OLD/'AUTHORIZATION.txt').read_text().replace(old['implementation_sha256'],implhash).replace(old['attempt_id'],attempt_id).replace(old['output'],str(output))
    auth+='Verify native-control-binding-v1 schema, exact package hashes, unused status and window before one dispatch. Dispatch consumes the attempt, including failure/interruption. Preserve both prior retired and consumed attempts.\n'
    (folder/'AUTHORIZATION.txt').write_text(auth)
    names=[*old['file_hashes'],'supervise.py','binding-schema.json']
    ident=dict(implementation_sha256=implhash,spec_sha256=spechash,attempt_id=attempt_id,output=str(output),file_hashes={n:sha256((folder/n).read_bytes()).hexdigest() for n in names})
    (folder/'identity.json').write_text(json.dumps(ident,indent=2)+'\n')
    (folder/'approval-template.json').write_text(json.dumps(dict(approved=False,**ident),indent=2)+'\n')
    if offline:(folder/'approval.json').write_text(json.dumps(dict(approved=True,**ident,classification='OFFLINE ISOLATED REHEARSAL ONLY; transport and credentials intercepted; no provider authority'),indent=2)+'\n')
    return ident
if __name__=='__main__':print(json.dumps(build(sys.argv[1],offline='--offline' in sys.argv),indent=2))
