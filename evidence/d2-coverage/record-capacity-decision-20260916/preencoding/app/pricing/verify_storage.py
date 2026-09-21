"""E3 durable proof in a newly created, identity-checked socket-only cluster.

No default DB connection helper is called. Existing E2 evidence is read-only.
"""
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
OUTPUT = ROOT / 'evidence/e3/durable'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='e3pg-', dir='/tmp')).resolve()
    data, socket = root/'data', root/'socket'
    socket.mkdir(mode=0o700)
    user, port = 'e3_disposable', 55481
    result = {'scope': 'E3 synthetic offline; fresh socket-only disposable cluster',
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
            for name in ('e3_source', 'e3_restore', 'e3_legacy', 'e3_e2_capture'):
                db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        estimates = []
        with connection('e3_source') as db:
            foundation = Store(db); foundation.migrate(); foundation.migrate()
            assert db.execute('SELECT count(*) AS n FROM schema_migration').fetchone()['n'] == len(list((ROOT/'app/storage/migrations').glob('*.sql')))
            refs, fair = ReferenceStore(db), FairPriceStore(db)
            # Start with the exact E2 archive, not fabricated detached quotes.
            original_path = ROOT/'evidence/e2/implementation/reference-bundle.json'
            refs.restore(original_path)
            refs.export(OUTPUT/'e2-reference-restored.json')
            assert (OUTPUT/'e2-reference-restored.json').read_bytes() == original_path.read_bytes()
            for seconds in (61, 59, 45, 35, 20):
                cutoff = before(seconds)
                estimate = calculate(refs.replay(cutoff), target=target(), cutoff=cutoff, estimated_at=cutoff)
                fair.save(estimate); estimates.append(estimate)
            assert [e.data['status'] for e in estimates] == ['unavailable']*3 + ['degraded']*2
            positive = estimates[-1]
            # New invalid arrival plus later source/rule knowledge cannot rewrite it.
            original = next(r for r in refs.records() if isinstance(r, Receipt) and r.id == 'synthetic-historical-download')
            new = receipt(b'{"synthetic":"latest invalid snapshot"}', identity='e3-new-invalid',
                          at=before(15), session=original.session_id)
            src = source(known_at=before(12), identity='e3-later-copy-knowledge')
            src = replace(src, copied_from=('kalshi',))
            refs.save(src); refs.save(new)
            refs.save(enrich(new, src, assessment(known_at=before(12)), revision_id='e3-new-invalid-revision'))
            refs.save(enrich(original, src, assessment(known_at=before(12)), revision_id='e3-later-correction'))
            assert fair.get(positive.id) == positive
            assert calculate(refs.replay(before(20)), target=target(), cutoff=before(20), estimated_at=before(20)) == positive
            unavailable = calculate(refs.replay(before(10)), target=target(), cutoff=before(10), estimated_at=before(10))
            assert unavailable.data['status'] == 'unavailable'
            fair.save(unavailable); estimates.append(unavailable)
            fair.save(positive)  # idempotent immutable retry
            for table, key, identity in [('fair_price', 'id', positive.id), ('fair_price_input', 'estimate_id', positive.id)]:
                for operation in ('UPDATE', 'DELETE'):
                    try:
                        if operation == 'DELETE':
                            db.execute(sql.SQL('DELETE FROM {} WHERE {}=%s').format(sql.Identifier(table), sql.Identifier(key)), (identity,))
                        else:
                            db.execute(sql.SQL("UPDATE {} SET payload='changed' WHERE {}=%s").format(sql.Identifier(table), sql.Identifier(key)), (identity,))
                        raise AssertionError('SQL mutation accepted')
                    except psycopg.errors.RaiseException:
                        pass
            tampered = positive.data; tampered['conditional_target_probability'] = '0.99'
            try:
                fair.save(Estimate(packed(tampered))); raise AssertionError('tampered result accepted')
            except ValueError:
                pass
            # A valid calculation over an incomplete subset cannot be persisted.
            subset = [r for r in refs.records() if not (isinstance(r, Receipt) and r.id == new.id)
                      and not (isinstance(r, QuoteRevision) and r.receipt_id == new.id)]
            partial = calculate(as_of(subset, before(10)), target=target(), cutoff=before(10), estimated_at=before(10))
            try:
                fair.save(partial); raise AssertionError('omitted newest receipt accepted')
            except ValueError as exc:
                assert 'as-of dependencies' in str(exc)
            # Future dependency/target data is rejected before any durable write.
            bad = positive.data; bad['as_of'] = before(61)
            try:
                fair.save(Estimate(packed(bad))); raise AssertionError('late dependencies persisted')
            except ValueError:
                pass
            result['reference_sha256'] = refs.export(OUTPUT/'reference-bundle.json')
            cutoffs = [e.data['as_of'] for e in estimates]
            replays = {c: refs.replay(c) for c in cutoffs}
            for index, estimate in enumerate(estimates):
                fair.export(estimate.id, OUTPUT/f'estimate-{index}.json')
            result['counts'] = {table: db.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier(table))).fetchone()['n']
                                for table in ('reference_receipt', 'reference_quote_revision', 'reference_source_revision', 'fair_price', 'fair_price_input')}
            # A capture exported with E2 migrations remains readable as well.
            foundation.export(OUTPUT/'capture-current.json')
            e2_capture = json.loads((OUTPUT/'capture-current.json').read_text())
            e2_capture['payload']['migrations'] = e2_capture['payload']['migrations'][:4]
            from app.storage.store import hashed
            e2_capture['sha256'] = hashed(e2_capture['payload'])
            (OUTPUT/'capture-e2-prefix.json').write_text(json.dumps(e2_capture))
            result['checks'] += ['five migrations plus idempotent reapply', 'exact original E2 reference-bundle-1 restore',
                'E2 replay -> eligibility -> de-vig -> immutable fair_price and all candidate links',
                'later receipt/source/rule correction leaves prior persisted estimate unchanged',
                'SQL update/delete blocked for estimates and links', 'idempotent retry',
                'tampered output, late dependencies and omitted newest receipt rejected before persistence']
        # Flush to disk, shut down and restart the actual server before rereading.
        run(['pg_ctl', '-D', str(data), '-m', 'fast', 'stop']); started = False
        start(); started = True
        with connection('e3_source') as db:
            for estimate in estimates:
                assert FairPriceStore(db).get(estimate.id).export() == estimate.export()
            result['checks'].append('all six estimates and input links survive PostgreSQL server restart with fsync on')
        with connection('e3_restore') as db:
            Store(db).migrate()
            refs, fair = ReferenceStore(db), FairPriceStore(db)
            refs.restore(OUTPUT/'reference-bundle.json')
            refs.export(OUTPUT/'reference-bundle-restored.json')
            assert (OUTPUT/'reference-bundle-restored.json').read_bytes() == (OUTPUT/'reference-bundle.json').read_bytes()
            result['replays'] = []
            for index, expected in enumerate(estimates):
                restored = fair.restore(OUTPUT/f'estimate-{index}.json')
                assert recompute(restored) == expected
                fair.export(expected.id, OUTPUT/f'estimate-{index}-restored.json')
                assert (OUTPUT/f'estimate-{index}-restored.json').read_bytes() == (OUTPUT/f'estimate-{index}.json').read_bytes()
                cutoff = expected.data['as_of']
                replay = refs.replay(cutoff)
                assert replay == replays[cutoff]
                assert calculate(replay, target=target(), cutoff=cutoff, estimated_at=cutoff) == expected
                result['replays'].append({'estimate_id': expected.id, 'as_of': cutoff, 'status': expected.data['status'],
                    'probability': expected.data['conditional_target_probability'],
                    'estimate_file_sha256': sha256(expected.export().encode()).hexdigest(),
                    'reference_replay_sha256': sha256(replay.encode()).hexdigest(), 'byte_exact': True})
            result['checks'].append('fresh-store reference export, six estimate exports, exclusions and exact recomputation are byte-identical')
        with connection('e3_legacy') as db:
            store = Store(db); store.migrate()
            store.import_bundle(ROOT/'evidence/e2/implementation/legacy-capture-bundle.json')
            result['legacy_replay'] = store.replay_all()
            result['checks'].append('original pre-E2 capture-bundle-1 restores on five migrations and detector replay passes')
        with connection('e3_e2_capture') as db:
            store = Store(db); store.migrate(); store.import_bundle(OUTPUT/'capture-e2-prefix.json')
            result['checks'].append('E2 migration-prefix capture-bundle-1 is readable on E3')
        from integration_tests import test_storage
        def isolated_connect(database=None):
            if database is not None and not database.startswith('prediction_arb_test_'):
                raise ValueError('unexpected regression database')
            return connection(database or 'postgres')
        with patch.object(test_storage, 'connect', isolated_connect):
            with (OUTPUT/'foundation-storage-tests.txt').open('w') as log:
                tested = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_storage))
                assert tested.wasSuccessful()
                result['foundation_storage_tests'] = tested.testsRun
        result['success'] = True
    except BaseException as exc:
        result['success'] = False; result['failure'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        if started:
            run(['pg_ctl', '-D', str(data), '-m', 'fast', 'stop'])
            result['cluster_stopped'] = True
        shutil.rmtree(root)
        result['cluster_removed'] = not root.exists()
        (OUTPUT/'storage-verification.json').write_text(json.dumps(result, indent=2, default=str) + '\n')
    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__': main()
