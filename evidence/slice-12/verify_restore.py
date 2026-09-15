"""Real project bundle, pg_dump/pg_restore, corruption rollback and outage exercise."""
import hashlib,json,subprocess,sys,uuid
from pathlib import Path
from psycopg import sql
from app.storage import Store,connect
from app.storage.store import ROOT,encoded,hashed
from app.storage.workflow import packet
from app.depth_example import fixture

out=ROOT/'evidence/slice-12'; result={}; names=[]
with connect() as admin:
 s=Store(admin)
 # Real terminated persistence connection: previously committed receipt is retained,
 # session cannot falsely finish, and the local journal is imported on recovery.
 sid=s.start('synthetic','synthetic','actual PostgreSQL connection termination verification')
 conn=connect(); broken=Store(conn)
 p=packet(fixture()[0][2][0]); broken.receipt(sid,'before-outage',p)
 admin.execute('SELECT pg_terminate_backend(%s)',(conn.info.backend_pid,))
 try: broken.ingest(sid,[('after-outage',p)])
 except Exception as exc: result['outage_error_type']=type(exc).__name__
 finally: conn.close()
 result['interrupted_before_recovery']=admin.execute('SELECT state FROM capture_session WHERE id=%s',(sid,)).fetchone()['state']
 assert result['interrupted_before_recovery']=='running'
 s.interrupt(sid)
 result['interrupted_after_recovery']=admin.execute('SELECT state FROM capture_session WHERE id=%s',(sid,)).fetchone()['state']
 result['failure_journals_imported']=admin.execute("SELECT count(*) n FROM coverage_event WHERE session_id=%s AND kind='failure'",(sid,)).fetchone()['n']
 assert result['failure_journals_imported']>=1
 bundle=out/'replay-bundle.json'; s.export(bundle)
 result['source_summary']=s.summary(); result['source_replayed']=s.replay_all()
 result['bundle']={'file':str(bundle.relative_to(ROOT)),'bytes':bundle.stat().st_size,'sha256':hashlib.sha256(bundle.read_bytes()).hexdigest()}
 def create(suffix):
  name='prediction_arb_'+suffix+'_'+uuid.uuid4().hex[:8]; names.append(name)
  admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
  return name
 try:
  restored=create('bundle_restore')
  with connect(restored) as db:
   restored_store=Store(db); restored_store.migrate(); restored_store.import_bundle(bundle)
   assert restored_store.summary()==s.summary()
   result['bundle_restore']={'database':restored,'replayed':restored_store.replay_all(),'counts_equal':True}
  corrupt=create('corrupt_test')
  with connect(corrupt) as db:
   cs=Store(db); cs.migrate()
   tampered=json.loads(bundle.read_bytes()); tampered['payload']['tables']['artifact'][-1]['hash']={'json':'0'*64}
   tampered['sha256']=hashed(tampered['payload'])
   temp=ROOT/'.local/corrupt-bundle.json'; temp.write_bytes(encoded(tampered))
   try: cs.import_bundle(temp)
   except ValueError: pass
   else: raise AssertionError('corrupt bundle accepted')
   assert all(v==0 for v in cs.summary()['counts'].values())
   result['corrupt_restore_rolled_back']=True
   temp.unlink() # Explicit disposable corrupt test artifact only.
  backup=out/'project-postgres.dump'
  common=['-h',str(ROOT/'.local/pgsocket'),'-p','55432','-U','prediction_arb']
  subprocess.run(['pg_dump',*common,'-d','prediction_arb','-Fc','-f',str(backup)],check=True)
  restored=create('backup_restore')
  subprocess.run(['pg_restore',*common,'-d',restored,'--exit-on-error','--no-owner',str(backup)],check=True)
  with connect(restored) as db:
   bs=Store(db); assert bs.summary()==s.summary()
   result['pg_restore']={'database':restored,'replayed':bs.replay_all(),'counts_equal':True}
  result['backup']={'file':str(backup.relative_to(ROOT)),'bytes':backup.stat().st_size,'sha256':hashlib.sha256(backup.read_bytes()).hexdigest()}
  result['server_configuration']=admin.execute("SELECT current_setting('listen_addresses') AS listen_addresses,current_setting('unix_socket_permissions') AS socket_permissions,version() AS version").fetchone()
  result['indexes']=[]
  receipt=admin.execute('SELECT session_id,venue,market_id FROM receipt LIMIT 1').fetchone()
  candidate=admin.execute('SELECT session_id,candidate_id,engine FROM candidate_observation LIMIT 1').fetchone()
  queries=[('SELECT * FROM receipt WHERE session_id=%s AND venue=%s AND market_id=%s ORDER BY received_at',tuple(receipt.values())),
   ('SELECT * FROM candidate_observation WHERE session_id=%s AND candidate_id=%s AND engine=%s ORDER BY observed_at',tuple(candidate.values())),
   ('SELECT * FROM coverage_event WHERE session_id=%s ORDER BY observed_at',(sid,))]
  for query,params in queries:
   natural=admin.execute('EXPLAIN (ANALYZE,BUFFERS) '+query,params).fetchall()
   admin.execute('SET enable_seqscan=off')
   indexed=admin.execute('EXPLAIN (ANALYZE,BUFFERS) '+query,params).fetchall()
   admin.execute('RESET enable_seqscan')
   result['indexes'].append({'query':query,'natural_plan':natural,'index_access_path':indexed,'note':'small retained dataset; forced index path is not a performance benchmark'})
  admin.execute('RESET enable_seqscan')
 finally:
  for name in names: admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
  result['disposable_databases_removed']=names
(out/'restore-verification.json').write_text(json.dumps(result,indent=2,default=str)+'\n')
print(json.dumps(result,indent=2,default=str))
