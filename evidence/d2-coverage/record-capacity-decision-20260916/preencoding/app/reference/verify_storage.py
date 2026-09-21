"""Create, verify and remove a NEW socket-only disposable PostgreSQL cluster.

Never imports the default connect helper. All connection identities originate
from mkdtemp below, are checked before migrations, and appear in the evidence.
"""
import asyncio
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import psycopg
from psycopg.rows import dict_row

from app.storage.store import Store, hashed, encoded
from app.reference.storage import ReferenceStore
from app.reference.adapter import OddsAPIReferenceAdapter, Response, Bounds, PersistenceFailure
from app.reference.records import Receipt, QuoteRevision, ReferenceGap, import_records, export_records, as_of, EVENT
from app.reference.enrichment import enrich
from app.reference.fixtures import FixtureClock, FixtureTransport, payload, source, assessment, before

OUTPUT = Path(__file__).resolve().parents[2] / 'evidence/e2/implementation'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='e2pg-', dir='/tmp')).resolve()
    data, socket = root/'data', root/'socket'
    socket.mkdir(mode=0o700)
    user, port = 'e2_disposable', 55479
    result = {'scope': 'synthetic offline E2; newly created cluster only', 'root': str(root), 'identities': [], 'checks': []}
    started = False
    def run(args):
        with (OUTPUT/'postgres-commands.txt').open('a') as log:
            subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=True)
    def connection(database):
        db = psycopg.connect(host=str(socket), port=port, user=user, dbname=database,
                            autocommit=True, row_factory=dict_row, connect_timeout=5,
                            options='-c statement_timeout=15000 -c lock_timeout=3000')
        identity = db.execute("SELECT current_database() AS database,current_user AS username,current_setting('data_directory') AS data_directory,current_setting('unix_socket_directories') AS sockets,current_setting('listen_addresses') AS listen_addresses,current_setting('port') AS port").fetchone()
        assert Path(identity['data_directory']).resolve() == data
        assert identity['sockets'] == str(socket) and identity['listen_addresses'] == ''
        assert identity['username'] == user and identity['database'] == database and int(identity['port']) == port
        result['identities'].append(identity)
        return db
    try:
        run(['initdb','-D',str(data),'-U',user,'--auth-local=trust','--auth-host=reject','--encoding=UTF8','--no-locale'])
        run(['pg_ctl','-D',str(data),'-l',str(root/'server.log'),'-o',f"-k {socket} -p {port} -c listen_addresses='' -c unix_socket_permissions=0700",'start'])
        started = True
        with connection('postgres') as admin:
            for name in ('e2_source','e2_restore','e2_legacy_source','e2_legacy_restore'):
                admin.execute(psycopg_sql(name))
        with connection('e2_source') as db:
            foundation=Store(db);foundation.migrate();foundation.migrate()
            assert db.execute('SELECT count(*) AS n FROM schema_migration').fetchone()['n']==len(list((Path(__file__).resolve().parents[1]/'storage/migrations').glob('*.sql')))
            sid=foundation.start('synthetic','synthetic','invented NFL E2 adapter pipeline')
            repo=ReferenceStore(db); src=source(assessed=False);repo.save(src)
            clock=FixtureClock()
            transport=FixtureTransport([Response(200,payload()),Response(200,payload()),
                Response(429,b'{"message":"synthetic rate limit"}',(('x-requests-remaining','100'),('Retry-After','1'))),
                Response(200,payload().replace(b'2.1000',b'2.2000')),Response(200,b'bad json'),Response(200,payload())])
            adapter=OddsAPIReferenceAdapter(transport=transport,clock=clock,sink=repo.save,source=src,
                assessment=assessment(pairing=False,rules=False),session_id=sid,
                failure_journal=OUTPUT/'unexpected-storage-failure.jsonl',bounds=Bounds(max_requests=6))
            async def collect():return [q async for q in adapter.observe(EVENT)]
            asyncio.run(collect())
            records=repo.records();receipts=sorted([r for r in records if isinstance(r,Receipt)],key=lambda r:r.received_at)
            assert len(receipts)==6 and len({r.id for r in receipts})==6
            assert receipts[0].body==receipts[1].body
            assert sum(r.recovery=='fresh_snapshot' for r in records if isinstance(r,ReferenceGap))==2
            early_cutoff=before(59)
            early=repo.replay(early_cutoff)
            later=source(known_at=before(40),identity='later-synthetic-source');repo.save(later)
            revised=enrich(receipts[0],later,assessment(known_at=before(40)),revision_id='later-enrichment')
            repo.save(revised)
            # Prior raw body with a genuinely later local arrival, never backdated.
            late=replace(receipts[0],id='late-download',received_at=before(30),request_started_at=before(30))
            repo.save(late);repo.save(enrich(late,later,assessment(known_at=before(30))))
            historical=json.dumps({'timestamp':before(3600),'previous_timestamp':before(3900),'next_timestamp':before(3300),
                                    'data':json.loads(payload(),parse_float=str)}).encode()
            import base64
            history=replace(late,id='synthetic-historical-download',body_b64=base64.b64encode(historical).decode(),body_sha256=sha256(historical).hexdigest())
            repo.save(history);repo.save(enrich(history,later,assessment(known_at=before(30))))
            from app.normalization.registry import Registry
            alias_body=payload().replace(b'Atlanta Falcons',b'Synthetic ATL Alias')
            alias_receipt=replace(late,id='later-alias-receipt',received_at=before(45),request_started_at=before(45),
                body_b64=base64.b64encode(alias_body).decode(),body_sha256=sha256(alias_body).hexdigest())
            repo.save(alias_receipt)
            repo.save(enrich(alias_receipt,src,assessment(known_at=before(45))))
            alias_registry=json.loads(Registry.load().to_json())
            alias_registry['version']='synthetic-later-alias-v2'
            alias_registry['aliases'].append({'kind':'team','league':'NFL','text':'Synthetic ATL Alias',
                'targets':['NFL:ATL'],'source':'synthetic:invented later mapping assumption'})
            mapped=enrich(alias_receipt,later,assessment(known_at=before(40)),registry=Registry(alias_registry))
            assert mapped.quote is not None
            repo.save(mapped)
            assert repo.replay(early_cutoff)==early
            repo.save(receipts[0]) # exact idempotent retry
            try:
                repo.save(replace(receipts[0],status=201))
                raise AssertionError('identity collision accepted')
            except (ValueError,psycopg.errors.RaiseException):pass
            try:
                db.execute('DELETE FROM reference_receipt WHERE id=%s',(receipts[0].id,))
                raise AssertionError('mutable history')
            except psycopg.errors.RaiseException:pass
            try:
                repo.save(replace(revised,id='bad-revision',known_at=before(200)))
                raise AssertionError('future knowledge accepted')
            except ValueError:pass
            # Real lost PostgreSQL connection: only a local fallback can retain
            # the unsaved response. It must not claim primary DB durability.
            failed_connection=connection('e2_source')
            failed_repo=ReferenceStore(failed_connection)
            failed_connection.close()
            failed_adapter=OddsAPIReferenceAdapter(transport=FixtureTransport([Response(200,payload())]),
                clock=FixtureClock(),sink=failed_repo.save,source=src,assessment=assessment(),session_id=sid,
                failure_journal=OUTPUT/'disconnected-db-journal.jsonl',bounds=Bounds(max_requests=1))
            async def fail_collect():return [q async for q in failed_adapter.observe(EVENT)]
            try:
                asyncio.run(fail_collect());raise AssertionError('disconnected storage accepted ingress')
            except PersistenceFailure:pass
            journal=json.loads((OUTPUT/'disconnected-db-journal.jsonl').read_text().splitlines()[-1])
            assert journal['reason']=='storage_failure' and journal['record']['type']=='Receipt'
            assert base64.b64decode(journal['record']['data']['body_b64'])==payload()
            # Cancellation persists a PostgreSQL interruption gap with no invented receipt.
            async def cancel_collection():
                entered=asyncio.Event()
                transport=FixtureTransport([])
                async def pending(request):entered.set();await asyncio.Event().wait()
                transport.request=pending
                cancelled=OddsAPIReferenceAdapter(transport=transport,clock=FixtureClock(before(25)),sink=repo.save,
                    source=src,assessment=assessment(),session_id=sid,failure_journal=OUTPUT/'unexpected-storage-failure.jsonl')
                async def consume():return [q async for q in cancelled.observe(EVENT)]
                task=asyncio.create_task(consume());await entered.wait();task.cancel()
                try:await task
                except asyncio.CancelledError:pass
                assert transport.closed
            asyncio.run(cancel_collection())
            assert any(isinstance(r,ReferenceGap) and r.reason=='cancelled' for r in repo.records())
            result['checks']+=['real closed PostgreSQL connection preserves raw receipt in failure journal',
                               'cancelled request persists interruption gap in PostgreSQL']
            blob_path=OUTPUT/'reference-bundle.json';result['bundle_sha256']=repo.export(blob_path)
            cutoffs=[before(3500),before(61),early_cutoff,before(45),before(35),before(20)]
            replays={c:repo.replay(c) for c in cutoffs}
            result['counts']={cls.__name__:sum(isinstance(r,cls) for r in repo.records()) for cls in (Receipt,QuoteRevision,ReferenceGap)}
            result['checks']+=['migration apply + idempotent reapply','adapter ingress -> PostgreSQL -> enrichment -> observed gaps/recovery',
                'identical/non-opportunity/error arrivals remain distinct','immutable SQL records and identity collisions rejected',
                'later source/mapping knowledge and late downloads cannot rewrite earlier replay','historical snapshot kept separate from download receipt']
        with connection('e2_restore') as db:
            Store(db).migrate();repo=ReferenceStore(db);repo.restore(blob_path)
            restored=OUTPUT/'reference-bundle-restored.json';repo.export(restored)
            assert restored.read_bytes()==blob_path.read_bytes()
            checks=[]
            for cutoff, expected in replays.items():
                actual=repo.replay(cutoff);assert actual==expected
                checks.append({'cutoff':cutoff,'sha256':sha256(actual.encode()).hexdigest(),'byte_identical':True})
            result['replays']=checks
            result['checks']+=['fresh-store restore has byte-identical full export','six as-of reconstructions byte-identical after restore']
        # Build a real pre-E2 capture-bundle-1 on the old schema and restore on all four migrations.
        with connection('e2_legacy_source') as db:
            db.execute('CREATE TABLE schema_migration(version text PRIMARY KEY,sha256 text NOT NULL)')
            for p in sorted((Path(__file__).resolve().parents[1]/'storage/migrations').glob('00[123]_*.sql')):
                db.execute(p.read_text());db.execute('INSERT INTO schema_migration VALUES (%s,%s)',(p.name,sha256(p.read_bytes()).hexdigest()))
            store=Store(db);sid=store.start('synthetic','synthetic','legacy capture compatibility')
            from app.arbitrage_example import synthetic_inputs, NOW
            from app.storage.replay import detector_audit
            parents,matcher,obs,contexts,_=synthetic_inputs()
            audit=detector_audit(parents,matcher,obs,contexts,evaluation_time=NOW)
            store.calculation(sid,'legacy-calculation',audit)
            store.finish(sid)
            store.export(OUTPUT/'legacy-capture-bundle.json')
        with connection('e2_legacy_restore') as db:
            store=Store(db);store.migrate();store.import_bundle(OUTPUT/'legacy-capture-bundle.json')
            result['legacy_replay']=store.replay_all()
            result['checks'].append('pre-E2 capture-bundle-1 restored on additive schema with detector audit replay')
        # Reuse the existing storage suite, rebinding its sole connection entry
        # point to this identity-checked cluster before any setup executes.
        import unittest
        from unittest.mock import patch
        from integration_tests import test_storage
        def isolated_connect(database=None):
            if database is not None and not database.startswith('prediction_arb_test_'):
                raise ValueError('unexpected test database')
            return connection(database or 'postgres')
        with patch.object(test_storage, 'connect', isolated_connect):
            with (OUTPUT/'foundation-storage-tests.txt').open('w') as log:
                suite=unittest.defaultTestLoader.loadTestsFromModule(test_storage)
                tested=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
                assert tested.wasSuccessful()
                result['foundation_storage_tests']=tested.testsRun
        result['success']=True
    except BaseException as exc:
        result['success']=False;result['failure']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        if started:
            run(['pg_ctl','-D',str(data),'-m','fast','stop'])
            result['cluster_stopped']=True
        shutil.rmtree(root)
        result['cluster_removed']=not root.exists()
        (OUTPUT/'storage-verification.json').write_text(json.dumps(result,indent=2,default=str)+'\n')
    print(json.dumps(result,indent=2,default=str))


def psycopg_sql(name):
    from psycopg import sql
    return sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name))


if __name__=='__main__': main()
