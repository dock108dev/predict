"""Explicit bootstrap, schema ownership and operational PostgreSQL access."""
import psycopg
from psycopg import sql

BOOTSTRAP = 'prediction_arb'
MIGRATOR = 'predict_migrator'
WEB = 'predict_web'
COLLECTOR = 'predict_collector'
ARCHIVE = 'predict_archive'
RUNTIME = (WEB, COLLECTOR, ARCHIVE)
ROLES = (MIGRATOR, *RUNTIME)
COHORTS = ('pregame_monitor', 'pregame_live', 'pregame_combined')
SCHEMAS = ('public', 'retained', *COHORTS)
ARCHIVE_TABLES = ('odds_archive_batch', 'odds_archive_feed_status', 'odds_archive_stage', 'odds_archive_usage')

# Web includes the paper-results subprocess. Several writes are by normal
# triggers: saved runs register result jobs, and fee settings invalidate prices.
WEB_WRITES = {
    'INSERT': tuple("""
        comparison_snapshot comparison_snapshot_result comparison_publication
        comparison_policy_revision comparison_result_reference current_pregame_work
        data_runtime_command paper_campaign paper_campaign_day paper_result_dependency
        paper_result_input paper_result_job paper_result_report research_issue_disposition
        research_market_census research_market_census_retry research_workspace_definition
        research_workspace_finding research_workspace_run public_fee_schedule
    """.split()),
    'UPDATE': tuple("""
        comparison_policy_revision comparison_publication comparison_result_reference
        paper_campaign_day paper_result_input paper_result_job public_fee_schedule
        research_market_census_retry
    """.split()),
    'DELETE': ('comparison_result_reference', 'research_market_census_retry'),
}
WEB_COLUMNS = {
    'comparison_snapshot': ('lease_until',),
    'comparison_snapshot_result': ('lease_until',),
    'current_pregame_work': ('revision', 'admitted_at', 'error'),
    'current_pregame_calculation': ('valid_until',),
    'current_pregame_price': ('valid_until',),
    'current_pregame_revision': ('revision', 'committed_at'),
}
COLLECTOR_WRITES = {
    'INSERT, UPDATE, DELETE': tuple("""
        acquisition_receipt arb_appearance comparison_publication comparison_result_reference
        comparison_snapshot comparison_snapshot_result current_acquisition_image_parts
        current_acquisition_market current_contract current_contract_storage current_event
        current_native_book current_offer current_offer_storage current_native_catalog_recovery
        current_native_market_body current_native_market_recovery current_row_state current_sgo_history
        current_pregame_calculation current_pregame_price current_pregame_work data_runtime_command
        delivery_clock native_book_revision native_ladder_revision sgo_event_evidence
        sgo_line_presence sgo_quote_revision
    """.split()),
    'INSERT, UPDATE': tuple("""
        activity_collection_run activity_mode current_pregame_revision data_runtime
        ev_experiment_accounting ev_experiment_game ev_experiment_record ev_experiment_task
        market_pull market_pull_evidence market_pull_receipt market_pull_scope mens_d1_attempt
        mens_d1_binding mens_d1_job mens_d1_receipt mens_d1_revision mens_d1_source_state
        public_fee_schedule research_record research_retention_accounting research_retention_disposition
        odds_archive_feed_status odds_archive_head
    """.split()),
    'INSERT': ('paper_result_input',),
    'DELETE': ('odds_archive_head',),
}
COHORT_WRITES = tuple("""
    current_contract current_event current_offer_storage current_pregame_calculation
    current_pregame_price current_pregame_revision current_sgo_reference sgo_line_presence
""".split())


def identifiers(values):
    return sql.SQL(', ').join(sql.Identifier(value) for value in values)


def grant(db, privileges, schema, names, role, *, kind='TABLE'):
    if names:
        db.execute(sql.SQL('GRANT {} ON {} {} TO {}').format(
            sql.SQL(privileges), sql.SQL(kind),
            sql.SQL(', ').join(sql.Identifier(schema, name) for name in names), sql.Identifier(role)))


def grant_updates(db, schema, table, columns, role):
    db.execute(sql.SQL('GRANT UPDATE ({}) ON TABLE {} TO {}').format(
        identifiers(columns), sql.Identifier(schema, table), sql.Identifier(role)))


def _grant_policy(db):
    # Explicit grants follow the migrations. A new writer must be inventoried.
    for schema in SCHEMAS:
        for kind in ('TABLES', 'SEQUENCES'):
            db.execute(sql.SQL('REVOKE ALL ON ALL {} IN SCHEMA {} FROM {}').format(
                sql.SQL(kind), sql.Identifier(schema), identifiers(RUNTIME)))
        roles = RUNTIME if schema == 'public' else (WEB,) if schema == 'retained' else (WEB, COLLECTOR)
        db.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema), identifiers(roles)))
        db.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}').format(
            sql.Identifier(schema), identifiers((WEB, COLLECTOR) if schema == 'public' else roles)))
    # Admin has a read-only structure and stored-value viewer for every app schema.
    db.execute(sql.SQL('GRANT SELECT ON ALL SEQUENCES IN SCHEMA public, retained TO {}').format(sql.Identifier(WEB)))
    for privileges, names in WEB_WRITES.items():
        grant(db, privileges, 'public', names, WEB)
    grant(db, 'USAGE', 'public', ('research_issue_disposition_sequence_seq',), WEB, kind='SEQUENCE')
    for table, columns in WEB_COLUMNS.items():
        schemas = ('public', *COHORTS) if table.startswith('current_pregame_') and table != 'current_pregame_work' else ('public',)
        for schema in schemas:
            grant_updates(db, schema, table, columns, WEB)
    grant(db, 'INSERT, UPDATE, DELETE', 'retained', ('current_grid_read_lease',), WEB)
    for privileges, names in COLLECTOR_WRITES.items():
        grant(db, privileges, 'public', names, COLLECTOR)
    if db.execute("SELECT to_regclass('public.ev_experiment_depth') IS NOT NULL AS present").fetchone()['present']:
        grant(db, 'INSERT', 'public', ('ev_experiment_depth',), COLLECTOR)
    if db.execute("SELECT to_regclass('public.current_pregame_depth') IS NOT NULL AS present").fetchone()['present']:
        grant(db, 'INSERT, UPDATE, DELETE', 'public', ('current_pregame_depth',), COLLECTOR)
    if db.execute("SELECT to_regclass('public.native_trading_offer') IS NOT NULL AS present").fetchone()['present']:
        grant(db, 'INSERT, UPDATE, DELETE', 'public', ('native_trading_offer',), COLLECTOR)
        grant(db, 'INSERT, DELETE', 'public', ('native_trading_snapshot',), COLLECTOR)
        grant(db, 'INSERT', 'public', ('native_trading_sgo_game',), COLLECTOR)
    if db.execute("SELECT to_regclass('public.paper_campaign_retirement') IS NOT NULL AS present").fetchone()['present']:
        grant(db, 'INSERT', 'public', ('paper_campaign_retirement',), WEB)
    if db.execute("SELECT to_regclass('public.pregame_cohort_work') IS NOT NULL AS present").fetchone()['present']:
        grant(db, 'SELECT, INSERT, UPDATE, DELETE', 'public', ('pregame_cohort_work',), COLLECTOR)
        db.execute(sql.SQL('REVOKE SELECT ON public.pregame_cohort_work FROM {}').format(sql.Identifier(WEB)))
    # Web inserts commands. The collector consumes them and acknowledges Stop.
    db.execute(sql.SQL('''GRANT INSERT (id,feed,receipt_day,received_at,bytes,body)
        ON public.odds_archive_stage TO {}''').format(sql.Identifier(COLLECTOR)))
    grant_updates(db, 'public', 'odds_archive_usage', ('staged_bytes',), COLLECTOR)
    grant(db, 'USAGE', 'public', ('acquisition_failure_id', 'arb_appearance_id_seq',
          'market_pull_started_order_seq', 'mens_d1_revision_immutable_sequence_seq'), COLLECTOR, kind='SEQUENCE')
    for schema in COHORTS:
        grant(db, 'INSERT, UPDATE, DELETE', schema, COHORT_WRITES, COLLECTOR)
    grant(db, 'SELECT', 'public', ARCHIVE_TABLES, ARCHIVE)
    grant(db, 'INSERT, DELETE', 'public', ('odds_archive_batch',), ARCHIVE)
    grant(db, 'DELETE', 'public', ('odds_archive_stage',), ARCHIVE)
    grant_updates(db, 'public', 'odds_archive_stage', ('batch_id',), ARCHIVE)
    grant_updates(db, 'public', 'odds_archive_usage', ('staged_bytes',), ARCHIVE)
    grant_updates(db, 'public', 'odds_archive_feed_status',
                  ('verified', 'verified_file_bytes', 'last_verified_at', 'last_verified_file'), ARCHIVE)


def _transfer(db, source, destination):
    """Move only known Predict schemas and their objects in the current database."""
    target = sql.Identifier(destination)
    db.execute(sql.SQL('ALTER DATABASE {} OWNER TO {}').format(sql.Identifier(db.info.dbname), target))
    for schema in SCHEMAS:
        # PostgreSQL 16's public schema follows pg_database_owner.
        if schema != 'public':
            db.execute(sql.SQL('ALTER SCHEMA {} OWNER TO {}').format(sql.Identifier(schema), target))
    relations = db.execute('''SELECT n.nspname, c.relname, c.relkind FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=ANY(%s) AND pg_get_userbyid(c.relowner)=%s AND c.relkind=ANY(%s)
        ORDER BY (c.relkind='S'), c.oid''', (list(SCHEMAS), source, ['r', 'p', 'v', 'm', 'S'])).fetchall()
    kinds = {'r': 'TABLE', 'p': 'TABLE', 'v': 'VIEW', 'm': 'MATERIALIZED VIEW', 'S': 'SEQUENCE'}
    for row in relations:
        db.execute(sql.SQL('ALTER {} {} OWNER TO {}').format(
            sql.SQL(kinds[row['relkind']]), sql.Identifier(row['nspname'], row['relname']), target))
    routines = db.execute('''SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid) arguments
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname=ANY(%s) AND pg_get_userbyid(p.proowner)=%s
        AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass
            AND d.objid=p.oid AND d.deptype='e')''', (list(SCHEMAS), source)).fetchall()
    for row in routines:
        db.execute(sql.SQL('ALTER ROUTINE {}({}) OWNER TO {}').format(
            sql.Identifier(row['nspname'], row['proname']), sql.SQL(row['arguments']), target))


def _assert_bootstrap(db):
    if db.info.user != BOOTSTRAP or not db.execute(
        'SELECT rolsuper FROM pg_roles WHERE rolname=current_user'
    ).fetchone()['rolsuper']:
        raise ValueError('database_role_change_requires_bootstrap')


def _validate_roles(db):
    roles = db.execute('''SELECT rolname, rolcanlogin, rolsuper, rolinherit, rolcreatedb, rolcreaterole,
        rolreplication, rolbypassrls, EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid) member
        FROM pg_roles r WHERE rolname=ANY(%s)''', (list(ROLES),)).fetchall()
    if set(ROLES) != {row['rolname'] for row in roles} or any(
        not row['rolcanlogin'] or any(row[flag] for flag in (
            'rolsuper', 'rolinherit', 'rolcreatedb', 'rolcreaterole', 'rolreplication', 'rolbypassrls', 'member'
        )) for row in roles
    ):
        raise ValueError('database_role_attributes_unexpected')


def _compaction_grant(db, command, direction):
    extension = db.execute('''SELECT n.nspname schema FROM pg_extension e
        JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pgstattuple' ''').fetchone()
    if extension:
        db.execute(sql.SQL('{} EXECUTE ON FUNCTION {}(regclass) {} {}').format(
            sql.SQL(command), sql.Identifier(extension['schema'], 'pgstattuple'),
            sql.SQL(direction), sql.Identifier(MIGRATOR)))


def verify_socket_login(db):
    """Check the active socket rules from an application OS identity."""
    from .store import credentials

    role = db.info.user
    if role not in RUNTIME or not (secret := credentials(role)).get('password'):
        raise ValueError('database_role_verification_requires_runtime_credentials')
    for other in (BOOTSTRAP, *ROLES):
        if other == role:
            continue
        try:
            candidate = psycopg.connect(host=db.info.host, port=db.info.port, dbname=db.info.dbname,
                                        user=other, connect_timeout=3, **secret)
        except psycopg.OperationalError:
            continue
        with candidate:
            raise ValueError('database_socket_accepted_another_role')
    return role


def enable(db):
    """Provision a migrated project database. Configure socket auth before cutover."""
    from .store import Store

    _assert_bootstrap(db)
    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(120012)')
        Store(db).require_current_schema()
        for role in ROLES:
            if not db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                db.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB '
                                   'NOCREATEROLE NOREPLICATION NOBYPASSRLS').format(sql.Identifier(role)))
        _validate_roles(db)
        if db.execute('''SELECT 1 FROM pg_namespace WHERE nspname='public'
                AND pg_get_userbyid(nspowner)<>'pg_database_owner' ''').fetchone():
            raise ValueError('database_role_public_schema_owner_unexpected')
        _transfer(db, BOOTSTRAP, MIGRATOR)
        db.execute(sql.SQL('REVOKE CONNECT, TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(db.info.dbname)))
        db.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(
            sql.Identifier(db.info.dbname), identifiers(RUNTIME)))
        db.execute(sql.SQL('REVOKE CREATE ON SCHEMA public FROM PUBLIC'))
        db.execute(sql.SQL('GRANT SET ON PARAMETER temp_file_limit TO {}').format(sql.Identifier(WEB)))
        _compaction_grant(db, 'GRANT', 'TO')
        _grant_policy(db)


def migrate(db):
    """Update packaged SQL and operational grants as one transaction."""
    from .store import Store

    if db.info.user != MIGRATOR:
        raise ValueError('database_migration_requires_migrator')
    with db.transaction():
        Store(db).migrate()
        _grant_policy(db)


def rollback(db):
    """Restore legacy app-schema ownership and remove runtime access; keep data and ledger."""
    _assert_bootstrap(db)
    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(120012)')
        _validate_roles(db)
        project = sql.Identifier(db.info.dbname)
        db.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM {}').format(project, identifiers(RUNTIME)))
        db.execute(sql.SQL('GRANT CONNECT, TEMPORARY ON DATABASE {} TO PUBLIC').format(project))
        for schema in SCHEMAS:
            namespace = sql.Identifier(schema)
            for kind in ('TABLES', 'SEQUENCES'):
                db.execute(sql.SQL('REVOKE ALL ON ALL {} IN SCHEMA {} FROM {}').format(
                    sql.SQL(kind), namespace, identifiers(ROLES)))
            db.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM {}').format(namespace, identifiers(ROLES)))
        _transfer(db, MIGRATOR, BOOTSTRAP)
        # Only column grants need a separate revoke; table ACLs do not cover them.
        for table, columns in WEB_COLUMNS.items():
            schemas = ('public', *COHORTS) if table in (
                'current_pregame_calculation', 'current_pregame_price', 'current_pregame_revision'
            ) else ('public',)
            for schema in schemas:
                _revoke_updates(db, schema, table, columns, WEB)
        db.execute(sql.SQL('''REVOKE INSERT (id,feed,receipt_day,received_at,bytes,body)
            ON public.odds_archive_stage FROM {}''').format(sql.Identifier(COLLECTOR)))
        _revoke_updates(db, 'public', 'odds_archive_usage', ('staged_bytes',), COLLECTOR)
        for table, columns in {
            'odds_archive_stage': ('batch_id',),
            'odds_archive_usage': ('staged_bytes',),
            'odds_archive_feed_status': ('verified', 'verified_file_bytes', 'last_verified_at', 'last_verified_file'),
        }.items():
            _revoke_updates(db, 'public', table, columns, ARCHIVE)
        db.execute(sql.SQL('REVOKE SET ON PARAMETER temp_file_limit FROM {}').format(sql.Identifier(WEB)))
        _compaction_grant(db, 'REVOKE', 'FROM')


def _revoke_updates(db, schema, table, columns, role):
    db.execute(sql.SQL('REVOKE UPDATE ({}) ON TABLE {} FROM {}').format(
        identifiers(columns), sql.Identifier(schema, table), sql.Identifier(role)))
