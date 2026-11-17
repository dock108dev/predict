"""Migration and logical restore on the disposable PostgreSQL runner."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import subprocess
from threading import Barrier
from uuid import uuid4

from psycopg import sql
import pytest

from app.storage import store


BEFORE_QUOTE_REPAIR = '094_desk_recent_inputs.sql'


@pytest.fixture
def disposable_socket():
    socket = store.ROOT / '.local/pgsocket'
    if not (os.environ.get('PREDICT_CI_ISOLATED_ROOT')
            and os.environ.get('PREDICT_DB_SOCKET') == str(socket)
            and os.environ.get('DA_TEST_PGSOCKET') == str(socket)
            and store.ROOT.name.startswith('predict-pg-')):
        pytest.skip('Run through scripts/ci/postgres.py with a disposable cluster')
    return socket


@contextmanager
def empty_database():
    name = 'prediction_arb_test_migration_' + uuid4().hex[:12]
    identifier = sql.Identifier(name)
    with store.connect() as db:
        db.execute(sql.SQL('CREATE DATABASE {}').format(identifier))
    try:
        yield name
    finally:
        with store.connect() as db:
            db.execute(sql.SQL('DROP DATABASE {}').format(identifier))


def ledger(db):
    return db.execute('SELECT * FROM public.schema_migration ORDER BY version').fetchall()


def packaged_ledger():
    migrations = Path(store.__file__).with_name('migrations')
    return [dict(version=path.name, sha256=sha256(path.read_bytes()).hexdigest())
            for path in sorted(migrations.glob('*.sql'))]


def test_concurrent_fresh_migrations_share_the_committed_history(disposable_socket):
    with empty_database() as name:
        start = Barrier(2, timeout=5)

        def migrate():
            with store.connect(name) as db:
                start.wait()
                store.Store(db).migrate()
                return ledger(db)

        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [pool.submit(migrate), pool.submit(migrate)]
            first, second = (call.result() for call in calls)
        assert first == second == packaged_ledger()


def test_refuses_a_gapped_or_newer_ledger_before_pending_migrations(disposable_socket):
    with empty_database() as name, store.connect(name) as db:
        schema = store.Store(db)
        schema.migrate(through=BEFORE_QUOTE_REPAIR)
        original = ledger(db)
        with db.transaction(force_rollback=True):
            future = '999_fixture_future.sql'
            db.execute('INSERT INTO public.schema_migration VALUES (%s,%s)', (future, 'x'))
            with pytest.raises(ValueError, match=f'outside the packaged history: {future}'):
                schema.migrate()
            assert [row['version'] for row in ledger(db)] == [
                *(row['version'] for row in original), future,
            ]
        with db.transaction(force_rollback=True):
            db.execute("DELETE FROM public.schema_migration WHERE version='001_capture.sql'")
            with pytest.raises(ValueError, match='outside the packaged history: 002_unknown_structural.sql'):
                schema.migrate()
            assert ledger(db) == original[1:]
        with db.transaction(force_rollback=True):
            db.execute('UPDATE public.schema_migration SET sha256=%s WHERE version=%s',
                       ('x', BEFORE_QUOTE_REPAIR))
            with pytest.raises(ValueError, match='applied migration changed: 094_desk_recent_inputs.sql'):
                schema.migrate()
            assert ledger(db)[-1]['version'] == BEFORE_QUOTE_REPAIR
        schema.migrate()
        upgraded = ledger(db)
        assert upgraded[:len(original)] == original
        assert len(upgraded) > len(original)
        assert upgraded == packaged_ledger()


def test_restore_before_upgrade_preserves_retained_evidence_and_pauses(disposable_socket, tmp_path):
    with empty_database() as original, empty_database() as recovered:
        def authoritative_rows(db):
            return (
                db.execute('SELECT global_stopped,paused_sources FROM data_runtime').fetchone(),
                db.execute('SELECT * FROM retained.capture_session').fetchone(),
            )

        with store.connect(original) as db:
            schema = store.Store(db)
            schema.migrate(through=BEFORE_QUOTE_REPAIR)
            prior_ledger = ledger(db)
            db.execute('''INSERT INTO data_runtime
                (runtime_id,owner_pid,started_at,heartbeat_at,state,config,source_status,
                 dispatch,status,fingerprint,paused_sources,global_stopped)
                 VALUES ('fixture',1,now(),now(),'stopped','{}','{}',false,'{}',
                         'fixture','["kalshi"]',true)''')
            db.execute('''INSERT INTO retained.capture_session
                (id,environment,evidence_class,started_at,ended_at,state,config,provenance)
                VALUES ('fixture','synthetic','synthetic',now(),now(),'complete','{}','fixture')''')
            prior_rows = authoritative_rows(db)
            dump = tmp_path / 'before-upgrade.dump'
            target = ['-h', str(disposable_socket), '-p', '55432', '-U', 'prediction_arb']
            subprocess.run(['pg_dump', *target, '-Fc', '-f', str(dump), original],
                           check=True, timeout=30)
            schema.migrate()
            assert authoritative_rows(db) == prior_rows
            upgraded_ledger = ledger(db)

        subprocess.run(['pg_restore', *target, '--exit-on-error', '--single-transaction',
                        '-d', recovered, str(dump)], check=True, timeout=30)
        with store.connect(recovered) as db:
            assert authoritative_rows(db) == prior_rows
            assert ledger(db) == prior_ledger
            store.Store(db).migrate()
            assert ledger(db) == upgraded_ledger
            assert authoritative_rows(db) == prior_rows
