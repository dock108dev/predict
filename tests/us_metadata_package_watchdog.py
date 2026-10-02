"""Offline absolute supervisor-deadline control; final live identity is untouched."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/us-metadata-diagnostic-preparation-20260930-v1'


def run():
    folder=OUT/('watchdog-control-'+str(time.time_ns()))
    folder.mkdir(parents=True)
    package=ROOT/'evidence'/('OFFLINE-us-metadata-watchdog-package-'+str(uuid.uuid4()))
    source=importlib.util.spec_from_file_location('watchdog_builder',ROOT/'scripts/us_metadata_package/build.py')
    builder=importlib.util.module_from_spec(source)
    source.loader.exec_module(builder)
    identity=builder.build(package,offline=True)
    fixture=folder/'fixture'
    fixture.mkdir()
    audit=folder/'offline-boundary-audit.jsonl'
    (fixture/'sitecustomize.py').write_text(f'''import json,socket,sys,time
from pathlib import Path
AUDIT=Path({str(audit)!r})
def record(value):
 with AUDIT.open('a') as f:f.write(json.dumps(value)+'\\n')
original_connect=socket.socket.connect
def local_connect(sock,address):
 if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1'):
  record(dict(forbidden_network=str(address)));raise RuntimeError('OFFLINE external network denied')
 record(dict(loopback_connect=list(address)));return original_connect(sock,address)
socket.socket.connect=local_connect
original_connect_ex=socket.socket.connect_ex
def local_connect_ex(sock,address):
 if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','::1'):
  record(dict(forbidden_network=str(address)));raise RuntimeError('OFFLINE external network denied')
 return original_connect_ex(sock,address)
socket.socket.connect_ex=local_connect_ex
from app.collection import venue_access,native_product,prediction_producer
def forbidden(*a,**kw):
 record(dict(forbidden_credentials_or_socket=True));raise RuntimeError('OFFLINE credentials/books prohibited')
venue_access.load_credentials=forbidden
native_product.load_native_secret=forbidden
prediction_producer.connect=forbidden
if Path(sys.argv[0]).name=='supervise.py':
 sys.path.insert(0,str(Path(sys.argv[0]).parent))
 import control
 def stalled_owned_control(*a,**kw):
  record(dict(constructed_stalled_parent_control=True));time.sleep(60)
 control.request=stalled_owned_control
''')
    env=dict(os.environ,PYTHONPATH=str(fixture)+os.pathsep+str(ROOT))
    began=time.monotonic()
    result=subprocess.run([sys.executable,str(package/'supervise.py')],cwd=ROOT,env=env,
                          capture_output=True,text=True,timeout=35)
    elapsed=time.monotonic()-began
    (folder/'supervisor-stdout.txt').write_text(result.stdout)
    (folder/'supervisor-stderr.txt').write_text(result.stderr)
    assert result.returncode==124,(result.returncode,result.stderr)
    assert elapsed<32.5,elapsed
    deadline=json.loads((package/'supervisor-deadline.json').read_text())
    assert deadline['reason']=='metadata_diagnostic_supervisor_wall_cap'
    assert deadline['elapsed_seconds']<32
    assert deadline['cleanup_verified'] is False
    assert (package/'activation.json').exists()
    assert not (package/'start-dispatch.json').exists()
    output=Path(identity['output'])
    assert output.exists()
    assert not (output/'b3-attempt.json').exists()
    assert not list(output.glob('*/manifest.json'))
    try:
        with socket.create_connection(('127.0.0.1',8831),timeout=.3):
            raise AssertionError('Owned server survived watchdog')
    except ConnectionRefusedError:
        pass
    rows=[json.loads(line) for line in audit.read_text().splitlines()]
    assert len([r for r in rows if 'constructed_stalled_parent_control' in r])==1
    assert not any('forbidden_network' in r or 'forbidden_credentials_or_socket' in r for r in rows)
    check=subprocess.run([sys.executable,str(package/'launch.py')],cwd=ROOT,
                         capture_output=True,text=True,timeout=3)
    assert check.returncode!=0
    assert 'activated' in check.stderr.lower() or 'exists' in check.stderr.lower()
    (package/'retirement.json').write_text(json.dumps(dict(
        classification='OFFLINE ENGINEERING CONTROL ONLY',
        reason='activated watchdog failure before dispatch; never reuse',
        attempt_id=identity['attempt_id'],activated=True,dispatched=False,consumed=False,retired=True),indent=2)+'\n')
    verification=dict(status='PASS_OFFLINE_ENGINEERING_ONLY',
        classification='Constructed stalled owned control; no provider evidence or live authority',
        implementation_sha256=identity['implementation_sha256'],spec_sha256=identity['spec_sha256'],
        package_sha256=builder.digest(identity),attempt_id=identity['attempt_id'],package=str(package),
        output=str(output),elapsed_seconds=elapsed,supervisor_exit=124,reason=deadline['reason'],
        provider_requests=0,credential_access=0,book_connections=0,kalshi_requests=0,
        owned_server_port_closed=True,activation=True,dispatch=False,consumed=False,retired=True,
        retirement_reuse_rejected=True,
        template_hashes={name:sha256((package/name).read_bytes()).hexdigest()
                         for name in ('build.py','launch.py','control.py','supervise.py')},
        exact_deadline_record=deadline)
    (folder/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    print(json.dumps(dict(status=verification['status'],elapsed_seconds=elapsed,
                         package=str(package),verification=str(folder/'verification.json'))),flush=True)
    return verification


if __name__=='__main__':
    run()
