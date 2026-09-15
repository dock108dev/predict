"""Two bounded beyond-envelope scenarios on a private disposable cluster."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
import asyncio,json,shutil,subprocess,tempfile
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
from app.capture_benchmark import DiagnosticPipeline,trial
from app.storage import Store

out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
base=Path(tempfile.mkdtemp(prefix='13b-drain-',dir=ROOT/'.local'));sock=base/'socket';sock.mkdir(mode=0o700)
data=base/'data';started=False
try:
    subprocess.run(['initdb','-D',str(data),'-U','prediction_arb','--auth-local=trust','--auth-host=reject','--encoding=UTF8','--no-locale'],check=True,stdout=subprocess.DEVNULL,timeout=30)
    subprocess.run(['pg_ctl','-D',str(data),'-l',str(base/'postgres.log'),'-o',f"-k {sock} -p 55439 -c listen_addresses='' -c unix_socket_permissions=0700 -c shared_buffers=32MB",'start'],check=True,timeout=30);started=True
    with psycopg.connect(host=str(sock),port=55439,user='prediction_arb',dbname='postgres',autocommit=True) as db:db.execute('CREATE DATABASE prediction_arb_13a')
    def connector(database='prediction_arb_13a'):
        return psycopg.connect(host=str(sock),port=55439,user='prediction_arb',dbname='prediction_arb_13a',autocommit=True,row_factory=dict_row,connect_timeout=2)
    with connector() as db:Store(db).migrate()
    original=DiagnosticPipeline.synthetic_bootstrap
    def bootstrap(p):
        v=original(p);p.delay=.1;return v
    runs=[]
    with patch.object(DiagnosticPipeline,'synthetic_bootstrap',bootstrap):
        for n in (2,4):
            r=asyncio.run(trial(connector,n,'overload'));runs.append(r)
            (out/'measurements.json').write_text(json.dumps(runs,indent=2)+'\n')
            c=r['accounting']['counts']
            assert all(r['accounting']['gates'].values())
            assert c['accepted']==48 and c['rejected']==8 and c['unprocessed']>0
            assert r['shutdown_seconds']<=10 and r['producer_close_seconds']<=2
            assert r['saved_state']['state'] in ('interrupted','failed')
            print(json.dumps(dict(markets=n,counts=c,shutdown_seconds=r['shutdown_seconds'],state=r['saved_state']['state'])),flush=True)
finally:
    if started:subprocess.run(['pg_ctl','-D',str(data),'-m','immediate','stop'],check=True,timeout=30)
    shutil.rmtree(base)
    (out/'cleanup.json').write_text(json.dumps(dict(isolated_cluster_removed=not base.exists(),owner_cluster_touched=False)))
