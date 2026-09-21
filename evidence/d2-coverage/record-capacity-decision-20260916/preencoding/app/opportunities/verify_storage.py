"""E4 durable proof in a newly created, identity-checked socket-only cluster.

No default DB connection helper is called. Existing E2/E3 evidence is read-only.
"""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.storage.store import Store
from app.reference.storage import ReferenceStore
from app.reference.records import Receipt, SourceRevision, QuoteRevision, as_of, export_records, packed
from app.reference.enrichment import enrich
from app.reference.fixtures import source, assessment, before
from app.pricing.fixtures import target, receipt
from app.pricing.baseline import calculate, recompute, Estimate
from app.pricing.storage import FairPriceStore

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'evidence/e4/durable'


from app.opportunities.service import evaluate, replay, rank, Audit
from app.opportunities.storage import OpportunityStore
from app.opportunities.fixtures import inputs


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='e4pg-', dir='/tmp')).resolve()
    data, socket = root/'data', root/'socket'
    socket.mkdir(mode=0o700)
    user, port = 'e4_disposable', 55482
    result = {'scope': 'E4 synthetic offline; fresh socket-only disposable cluster',
              'root': str(root), 'identities': [], 'checks': []}
    started = False

    def run(args):
        with (OUTPUT/'postgres-commands.txt').open('a') as log:
            subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=True)

    def start():
        run(['pg_ctl', '-D', str(data), '-l', str(root/'server.log'), '-o',
             f"-k {socket} -p {port} -c listen_addresses='' -c unix_socket_permissions=0700", 'start'])

    def connection(database):
        db = psycopg.connect(host=str(socket), port=port, user=user, dbname=database,
                            autocommit=True, row_factory=dict_row, connect_timeout=5,
                            options='-c statement_timeout=15000 -c lock_timeout=3000')
        identity = db.execute("SELECT current_database() AS database,current_user AS username,current_setting('data_directory') AS data_directory,current_setting('unix_socket_directories') AS sockets,current_setting('listen_addresses') AS listen_addresses,current_setting('port') AS port,current_setting('fsync') AS fsync").fetchone()
        assert Path(identity['data_directory']).resolve() == data
        assert identity['sockets'] == str(socket) and identity['listen_addresses'] == ''
        assert identity['username'] == user and identity['database'] == database and int(identity['port']) == port
        assert identity['fsync'] == 'on'
        result['identities'].append(identity)
        return db

    try:
        run(['initdb', '-D', str(data), '-U', user, '--auth-local=trust', '--auth-host=reject', '--encoding=UTF8', '--no-locale'])
        start(); started = True
        with connection('postgres') as db:
            for name in ('e4_source', 'e4_restore', 'e4_legacy', 'e4_prefix', 'e4_e3_prefix', 'e4_e4_prefix', 'e4_missing'):
                db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        estimates=[]; audits=[]
        with connection('e4_source') as db:
            foundation=Store(db);foundation.migrate();foundation.migrate()
            assert db.execute('SELECT count(*) AS n FROM schema_migration').fetchone()['n']==6
            refs=ReferenceStore(db); fair=FairPriceStore(db); service=OpportunityStore(db)
            refs.restore(ROOT/'evidence/e3/durable/reference-bundle.json')
            refs.export(OUTPUT/'reference-bundle.json')
            assert (OUTPUT/'reference-bundle.json').read_bytes()==(ROOT/'evidence/e3/durable/reference-bundle.json').read_bytes()
            for i in range(6):
                e=fair.restore(ROOT/f'evidence/e3/durable/estimate-{i}.json');estimates.append(e)
                fair.export(e.id,OUTPUT/f'estimate-{i}.json')
                assert (OUTPUT/f'estimate-{i}.json').read_bytes()==(ROOT/f'evidence/e3/durable/estimate-{i}.json').read_bytes()
            # Public service entry reads persisted E3, not a detached caller estimate.
            cases=[('e3-unavailable-ev',inputs()),('invented-positive',inputs(model='complete')),
                ('invented-negative',inputs(price='0.8',model='complete')),
                ('invented-missing-mass',inputs(model='missing')),
                ('unknown-quantity',inputs(quantity=None,model='complete'))]
            unknown=inputs(model='complete');unknown['market']['contexts'][0][1].pop('balance_precision')
            cases.append(('unknown-fees',unknown))
            stale=inputs(model='complete')
            book=stale['market']['books'][0]
            for k in ('received_at','exchange_at'): book['observation']['quote']['raw'][k]='2026-09-13T16:59:09+00:00'
            from app.fees.engine import digest
            book['id']=digest({k:v for k,v in book.items() if k!='id'})
            cases.append(('stale-book',stale))
            for name,x in cases:
                a=service.evaluate(estimates[4].id,x);audits.append((name,a))
                service.save(a)
                service.export(a.id,OUTPUT/f'{name}.json')
            assert audits[0][1].data['signals'][1]['net_total_usd'] is None
            from decimal import Decimal
            assert Decimal(audits[1][1].data['signals'][1]['net_total_usd'])==Decimal('1.265')
            assert Decimal(audits[2][1].data['signals'][1]['net_total_usd'])==Decimal('-.535')
            ranking=rank([a for _,a in audits]);(OUTPUT/'ranking.json').write_text(packed(ranking))
            assert ranking['aggregate_attainable_profit_usd'] is None
            for table,key,identity in [('opportunity_audit','id',audits[0][1].id),
                ('opportunity_input','audit_id',audits[0][1].id),
                ('opportunity_dependency','id',digest(cases[0][1]['market']))]:
                for operation in ('UPDATE','DELETE'):
                    try:
                        if operation=='DELETE':
                            db.execute(sql.SQL('DELETE FROM {} WHERE {}=%s').format(sql.Identifier(table),sql.Identifier(key)),(identity,))
                        else:
                            column='kind' if table=='opportunity_input' else 'payload'
                            db.execute(sql.SQL("UPDATE {} SET {}='changed' WHERE {}=%s").format(sql.Identifier(table),sql.Identifier(column),sql.Identifier(key)),(identity,))
                        raise AssertionError('SQL mutation accepted')
                    except psycopg.errors.RaiseException: pass
            # A dangling link cannot be inserted even using direct SQL.
            try:
                db.execute('INSERT INTO opportunity_input VALUES (%s,%s,%s)',(audits[0][1].id,'missing','missing'))
                raise AssertionError('missing dependency accepted')
            except psycopg.errors.ForeignKeyViolation: pass
            bad=audits[0][1].data;bad['signals'][0]['net_total_usd']='100'
            try:service.save(Audit(packed(bad)));raise AssertionError('mutated output accepted')
            except ValueError:pass
            late=deepcopy(cases[0][1]);late['market']['known_at']='2026-09-13T16:59:41+00:00'
            try:service.evaluate(estimates[4].id,late);raise AssertionError('late dependency accepted')
            except ValueError:pass
            result['counts']={t:db.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier(t))).fetchone()['n'] for t in
                ('fair_price','fair_price_input','opportunity_audit','opportunity_dependency','opportunity_input')}
            foundation.export(OUTPUT/'capture-current.json')
            result['checks'] += ['six migrations and idempotent reapply',
                'all original six E3 estimates restored byte-exact with durable reference dependencies',
                'persisted E3 replay plus identified prediction books produce separate Arb and Mispricing',
                'seven complete immutable service audits and every input link saved; idempotent retries',
                'positive 1.265 USD and negative -0.535 USD independent expected-value checks',
                'SQL update/delete rejection on all three E4 tables; dangling dependency FK rejected',
                'mutated result and late knowledge rejected before persistence']
        run(['pg_ctl','-D',str(data),'-m','fast','stop']);started=False
        start();started=True
        with connection('e4_source') as db:
            for _,a in audits:assert OpportunityStore(db).get(a.id)==a
            result['checks'].append('all seven service audits and dependency links survive server restart with fsync on')
            # Deliberate corruption probes are isolated to rolled-back transactions
            # in this identity-checked disposable DB. Triggers are restored by rollback.
            for kind in ('missing_link','changed_dependency'):
                with db.transaction():
                    if kind=='missing_link':
                        db.execute('ALTER TABLE opportunity_input DISABLE TRIGGER immutable_opportunity_input')
                        db.execute("DELETE FROM opportunity_input WHERE audit_id=%s AND kind='market'",(audits[0][1].id,))
                    else:
                        db.execute('ALTER TABLE opportunity_dependency DISABLE TRIGGER immutable_opportunity_dependency')
                        db.execute("UPDATE opportunity_dependency SET payload='changed' WHERE id=%s",(digest(cases[0][1]['market']),))
                    try:OpportunityStore(db).get(audits[0][1].id);raise AssertionError('corruption accepted')
                    except ValueError:pass
                    raise psycopg.Rollback
                assert OpportunityStore(db).get(audits[0][1].id)==audits[0][1]
            result['checks'].append('read rejects missing links and changed dependencies in rolled-back corruption probes; intact audit reverified')
        with connection('e4_restore') as db:
            Store(db).migrate();refs=ReferenceStore(db);fair=FairPriceStore(db);service=OpportunityStore(db)
            refs.restore(OUTPUT/'reference-bundle.json');refs.export(OUTPUT/'reference-bundle-restored.json')
            assert (OUTPUT/'reference-bundle-restored.json').read_bytes()==(OUTPUT/'reference-bundle.json').read_bytes()
            for i,e in enumerate(estimates):assert fair.restore(OUTPUT/f'estimate-{i}.json')==e
            result['replays']=[]
            for name,a in audits:
                restored=service.restore(OUTPUT/f'{name}.json');assert replay(restored)==a
                h=service.export(a.id,OUTPUT/f'{name}-restored.json')
                assert (OUTPUT/f'{name}-restored.json').read_bytes()==(OUTPUT/f'{name}.json').read_bytes()
                result['replays'].append(dict(name=name,audit_id=a.id,export_sha256=h,estimate_id=a.data['estimate_id'],book_ids=a.data['book_ids'],byte_exact=True,
                    signals=[{k:s[k] for k in ('signal_class','status','net_total_usd','reasons')} for s in a.data['signals']]))
            assert rank([service.get(a.id) for _,a in audits])==ranking
            result['checks'].append('fresh-store reference, six E3 estimates, seven E4 exports, recomputation and rankings byte-exact')
        with connection('e4_missing') as db:
            Store(db).migrate()
            try:OpportunityStore(db).restore(OUTPUT/'e3-unavailable-ev.json');raise AssertionError('missing E3 accepted')
            except ValueError:pass
            result['checks'].append('fresh store rejects opportunity restore before durable E3/reference dependencies')
        with connection('e4_legacy') as db:
            st=Store(db);st.migrate();st.import_bundle(ROOT/'evidence/e2/implementation/legacy-capture-bundle.json')
            assert st.replay_all()==1
            result['checks'].append('pre-E2 capture-bundle-1 restored with exact detector replay')
        with connection('e4_prefix') as db:
            st=Store(db);st.migrate()
            # Both actual retained E2-prefix and actual E3 capture exports remain readable.
            st.import_bundle(ROOT/'evidence/e3/durable/capture-e2-prefix.json')
        with connection('e4_e3_prefix') as db:
            st=Store(db);st.migrate();st.import_bundle(ROOT/'evidence/e3/durable/capture-current.json')
        with connection('e4_e4_prefix') as db:
            st=Store(db);st.migrate();st.import_bundle(OUTPUT/'capture-current.json')
            result['checks'].append('E2, E3 and E4 exact migration-prefix capture exports remain readable')
        from integration_tests import test_storage
        def isolated_connect(database=None):
            if database is not None and not database.startswith('prediction_arb_test_'):raise ValueError('unexpected test DB')
            return connection(database or 'postgres')
        with patch.object(test_storage,'connect',isolated_connect):
            with (OUTPUT/'foundation-storage-tests.txt').open('w') as log:
                tested=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_storage))
                assert tested.wasSuccessful();result['foundation_storage_tests']=tested.testsRun
        result['success']=True
    except BaseException as exc:
        result['success']=False;result['failure']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        if started:
            run(['pg_ctl','-D',str(data),'-m','fast','stop']);result['cluster_stopped']=True
        shutil.rmtree(root);result['cluster_removed']=not root.exists()
        (OUTPUT/'storage-verification.json').write_text(json.dumps(result,indent=2,default=str)+'\n')
    print(json.dumps(result,indent=2,default=str))


if __name__=='__main__':main()
