"""Restricted SQL actors in a disposable migrated project database."""
from hashlib import sha256
from pathlib import Path
import shutil

import psycopg
from psycopg.errors import InsufficientPrivilege
import pytest

from app.collection.runtime_status import RuntimeState
from app.comparison import fee_mode
from app.dashboard.admin_database import catalog, inspection
from app.research import paper_campaigns
from app.storage import database_roles as roles, odds_archive, odds_archive_export, storage_maintenance, store
from app.storage.payload_codec import payload_row
from tests.test_odds_archive_sql import FEED, db, quote, staged, status, usage
from tests.pregame_fixture import PregameFixture, page
from tests.test_paper_campaigns import fixed_config


def connection(admin, user):
    return psycopg.connect(host=admin.info.host, port=admin.info.port, dbname=admin.info.dbname,
                           user=user, autocommit=True, row_factory=payload_row, connect_timeout=5)


def test_runtime_role_writes_and_denials(db, monkeypatch):
    db.execute('CREATE EXTENSION pgstattuple')
    roles.enable(db)
    db.execute('GRANT predict_migrator TO predict_web')
    try:
        with pytest.raises(ValueError, match='database_role_attributes_unexpected'):
            roles.enable(db)
    finally:
        db.execute('REVOKE predict_migrator FROM predict_web')
    roles.enable(db)  # Repair/reconciliation can repeat with prior operations retained.
    with (connection(db, roles.WEB) as web, connection(db, roles.COLLECTOR) as collector,
          connection(db, roles.ARCHIVE) as archive, connection(db, roles.MIGRATOR) as migrator):
        for runtime in (web, collector):
            store.Store(runtime).require_current_schema()
        with monkeypatch.context() as unsafe_socket:
            unsafe_socket.setenv('PREDICT_DB_ROLE', roles.WEB)
            unsafe_socket.setenv('PREDICT_DB_PASSWORD', 'synthetic')
            with pytest.raises(ValueError, match='database_socket_accepted_another_role'):
                roles.verify_socket_login(web)
        with inspection(lambda: connection(db, roles.WEB)) as reader:
            assert any(r['schema'] == 'retained' for r in catalog(reader)['relations'])
        campaign = paper_campaigns.create(web, fixed_config())
        assert paper_campaigns.view(web, campaign['id'])['config']['target_profit_usd'] == '10'
        assert fee_mode.set_enabled(web, True)['enabled']
        assert fee_mode.read(collector)['enabled']
        assert fee_mode.set_enabled(web, False)['enabled'] is False
        fixture = PregameFixture()
        assert fixture.ingest(collector, page())
        fixture.process(collector)
        assert web.execute(
            'SELECT count(*) n FROM pregame_monitor.current_pregame_price'
        ).fetchone()['n'] > 0
        assert migrator.execute(
            "SELECT table_len FROM public.pgstattuple('public.odds_archive_stage'::regclass)"
        ).fetchone()['table_len'] >= 0
        monkeypatch.setattr(storage_maintenance, 'PRESSURE_BYTES', 0)
        maintenance = storage_maintenance.maintain(collector)
        assert {'table': 'storage', 'reason': 'vacuum_requires_migration_role'} in maintenance['deferred']
        assert maintenance['rewrites'] == []
        source_event = quote()
        odds_archive.record(collector, FEED, [source_event])
        assert len(staged(collector)) == 1
        batch = odds_archive_export.claim(archive, feed=FEED, force=True)
        raw = odds_archive_export.load_batch(archive, batch)
        receipt = dict(path=f"v1/{FEED}/{batch['receipt_day']}/{batch['id']}.jsonl.gz",
                       bytes=len(raw), sha256=sha256(raw).hexdigest())
        assert odds_archive_export.acknowledge(archive, batch, receipt)
        assert usage(collector) == 0
        assert status(archive)['verified'] == 1

        for runtime, queries in (
            (web, ("DELETE FROM data_runtime", "UPDATE odds_archive_stage SET batch_id=NULL",
                   "UPDATE current_pregame_price SET game_key='invalid'", "DELETE FROM paper_campaign")),
            (collector, ("UPDATE paper_campaign SET payload='{}'", "DELETE FROM odds_archive_batch",
                         "DELETE FROM odds_archive_stage", "DELETE FROM ev_experiment_accounting",
                         "INSERT INTO odds_archive_stage(batch_id) VALUES (NULL)",
                         "INSERT INTO public.schema_migration VALUES('fake','fake')")),
            (archive, ("SELECT * FROM paper_campaign", "UPDATE odds_archive_stage SET body='{}'",
                       "UPDATE odds_archive_feed_status SET skipped=0", "INSERT INTO odds_archive_stage DEFAULT VALUES")),
        ):
            for query in (*queries, "CREATE TABLE public.denied(id int)", "SET ROLE predict_migrator",
                          "ALTER TABLE public.odds_archive_stage ADD COLUMN denied int",
                          "SELECT * FROM public.pgstattuple('public.odds_archive_stage'::regclass)"):
                with pytest.raises(InsufficientPrivilege):
                    runtime.execute(query)
        web_runtime = RuntimeState(connector=lambda: connection(db, roles.WEB))
        collector_runtime = RuntimeState(connector=lambda: connection(db, roles.COLLECTOR))
        collector_runtime._write_authority(collector, dict(runtime_id='synthetic-owner',
            state='running', config={}, states={}, dispatch=True, status={}, fingerprint='fixture',
            paused_sources=[], global_stopped=False))
        assert web_runtime.read()['healthy']
        command = web_runtime.submit('synthetic-owner', 'stop', {})
        assert [row['id'] for row in collector_runtime.pending(collector)] == [command]
        collector_runtime.acknowledge(command, {'stopped': True})
        assert web_runtime.result(command)['acknowledgment'] == {'stopped': True}

    manifest = db.execute("SELECT * FROM public.schema_migration ORDER BY version").fetchall()
    roles.rollback(db)
    assert db.execute('SELECT id FROM public.paper_campaign').fetchone()['id'] == campaign['id']
    assert db.execute('SELECT * FROM public.schema_migration ORDER BY version').fetchall() == manifest
    assert db.execute("SELECT pg_get_userbyid(relowner) owner FROM pg_class WHERE oid='paper_campaign'::regclass"
                      ).fetchone()['owner'] == roles.BOOTSTRAP
    with connection(db, roles.WEB) as retired:
        with pytest.raises(InsufficientPrivilege):
            retired.execute('SELECT * FROM paper_campaign')


def test_pending_upgrade_and_failed_grants_are_atomic(db, tmp_path, monkeypatch):
    migrations = Path(store.__file__).with_name('migrations')
    release = '124_pregame_projection_recovery.sql'
    pending = 0
    prior = tmp_path / 'migrations'
    prior.mkdir()
    for path in migrations.glob('*.sql'):
        if path.name < release:
            (prior / path.name).symlink_to(path)
        else:
            pending += 1
    db.execute('DROP SCHEMA pregame_monitor, pregame_live, pregame_combined, retained, public CASCADE')
    db.execute('CREATE SCHEMA public AUTHORIZATION pg_database_owner')
    old_boundary = sorted(prior.glob('*.sql'))[-1].name
    with monkeypatch.context() as revision:
        revision.setattr(store, '__file__', str(tmp_path / 'store.py'))
        store.Store(db).migrate(through=old_boundary)
        roles.enable(db)
    with (connection(db, roles.WEB) as web, connection(db, roles.COLLECTOR) as collector,
          connection(db, roles.MIGRATOR) as migrator):
        assert store.Store(web).pending_migrations() == pending
        with pytest.raises(ValueError, match='database_schema_maintenance_required'):
            store.Store(collector).ensure_runtime_schema()
        with pytest.raises(ValueError, match='database_migration_requires_migrator'):
            store.Store(collector).migrate()
        def fail(_db):
            raise RuntimeError('synthetic grant failure')

        with monkeypatch.context() as failure:
            failure.setattr(roles, '_grant_policy', fail)
            with pytest.raises(RuntimeError, match='synthetic grant failure'):
                roles.migrate(migrator)
        assert store.Store(web).pending_migrations() == pending
        assert not web.execute("SELECT to_regclass('public.pregame_cohort_work') IS NOT NULL present").fetchone()['present']
        roles.migrate(migrator)
        assert store.Store(web).pending_migrations() == 0
        assert collector.execute('SELECT count(*) count FROM public.pregame_cohort_work').fetchone()['count'] == 0
        with pytest.raises(InsufficientPrivilege):
            web.execute('SELECT count(*) FROM public.pregame_cohort_work')
        assert store.Store(migrator).pending_migrations() == 0
