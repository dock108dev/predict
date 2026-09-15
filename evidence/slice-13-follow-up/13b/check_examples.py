"""Existing offline examples, plus storage only on an isolated disposable socket."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
import contextlib,json,runpy,shutil,socket,subprocess,tempfile,time
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
results=[]
def blocked(*args,**kwargs):raise AssertionError('network disabled in offline examples')
for module in ('example','polymarket_us_example','prophetx_example','kalshi_example','novig_example','normalization_example','matching_example','moneyline_example','fee_example','arbitrage_example','depth_example'):
    sys.argv=[module];start=time.monotonic()
    with (out/(module+'.json')).open('w') as stream,contextlib.redirect_stdout(stream),patch.object(socket.socket,'connect',blocked):runpy.run_module('app.'+module,run_name='__main__')
    results.append(dict(module=module,passed=True,seconds=time.monotonic()-start))
base=Path(tempfile.mkdtemp(prefix='13b-examples-',dir=ROOT/'.local'));sock=base/'socket';sock.mkdir(mode=0o700)
data=base/'data';started=False
try:
    subprocess.run(['initdb','-D',str(data),'-U','prediction_arb','--auth-local=trust','--auth-host=reject','--encoding=UTF8','--no-locale'],check=True,stdout=subprocess.DEVNULL,timeout=30)
    subprocess.run(['pg_ctl','-D',str(data),'-l',str(base/'postgres.log'),'-o',f"-k {sock} -p 55439 -c listen_addresses='' -c unix_socket_permissions=0700 -c shared_buffers=32MB",'start'],check=True,timeout=30);started=True
    with psycopg.connect(host=str(sock),port=55439,user='prediction_arb',dbname='postgres',autocommit=True) as db:db.execute('CREATE DATABASE prediction_arb')
    def connector(database='prediction_arb'):
        assert database=='prediction_arb'
        return psycopg.connect(host=str(sock),port=55439,user='prediction_arb',dbname=database,autocommit=True,row_factory=dict_row,connect_timeout=2)
    from app import storage
    with patch.object(storage,'connect',connector),(out/'storage_example.json').open('w') as stream,contextlib.redirect_stdout(stream):runpy.run_module('app.storage_example',run_name='__main__')
    with connector() as db:
        replayed=storage.Store(db).replay_all()
        size=db.execute('SELECT pg_database_size(current_database()) n').fetchone()['n']
        assert size<=256*1024*1024
    results.append(dict(module='storage_example',passed=True,replayed=replayed,database_bytes=size))
    (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
finally:
    if started:subprocess.run(['pg_ctl','-D',str(data),'-m','immediate','stop'],check=True,timeout=30)
    shutil.rmtree(base)
    (out/'cleanup.json').write_text(json.dumps(dict(isolated_cluster_removed=not base.exists(),owner_cluster_touched=False)))
