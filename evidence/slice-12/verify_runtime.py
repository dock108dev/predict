"""Exercise only the dedicated cluster; leave it STOPPED with data preserved."""
import hashlib,json,subprocess
from pathlib import Path
from importlib.metadata import version
from app.storage import Store,connect
from app.storage.store import ROOT

out=ROOT/'evidence/slice-12'; log=[]
def control(action,expected=0):
 r=subprocess.run([str(ROOT/'scripts/project-postgres'),action],capture_output=True,text=True)
 log.append(dict(action=action,exit_code=r.returncode,output=r.stdout+r.stderr))
 if expected is not None: assert r.returncode==expected
 return r
with connect() as db:
 before=Store(db).summary()
 assert not any(r['state']=='running' for r in before['sessions'])
 dbs=[r['datname'] for r in db.execute("SELECT datname FROM pg_database WHERE datname LIKE 'prediction_arb%' ORDER BY datname").fetchall()]
 assert dbs==['prediction_arb'],dbs
control('start') # Existing instance reused, not duplicated.
control('stop'); control('start')
with connect() as db:
 assert Store(db).summary()==before
 check=db.execute("SELECT current_setting('listen_addresses') AS tcp,current_setting('unix_socket_permissions') AS socket_permissions,version() AS version").fetchone()
 assert check['tcp']==''
control('stop')
r=control('status',expected=None); assert r.returncode!=0
result=dict(final_state='stopped',data_preserved=True,restart_summary_equal=True,databases=dbs,server=check,
 dependencies={n:version(n) for n in ('psycopg','psycopg-binary','httpx')},control_log=log)
(out/'runtime-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
