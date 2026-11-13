"""Exercise the Admin read boundary with an isolated PostgreSQL database."""

import asyncio
import os
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest
from psycopg import errors

from app.dashboard import admin_database as browser
from app.dashboard.request_guard import dashboard_guard
from app.storage import store


@pytest.fixture
def database():
    socket = os.environ.get('DA_TEST_PGSOCKET', '')
    if not socket.startswith('/tmp/predict-pg-'):
        pytest.skip('Run through scripts/ci/postgres.py with a disposable database')
    assert (store.ROOT / '.local/pgsocket').resolve() == Path(socket).resolve()
    with store.connect() as db:
        db.execute('CREATE SCHEMA "Admin Fixture"')
        db.execute('''CREATE TABLE "Admin Fixture"."Stored Values" (
            id bigint PRIMARY KEY, "odd column" text, price numeric(32, 10),
            marker text DEFAULT 'fixture', CONSTRAINT positive_id CHECK (id > 0)
        )''')
        db.execute('CREATE INDEX fixture_price ON "Admin Fixture"."Stored Values"(price)')
        db.execute('''INSERT INTO "Admin Fixture"."Stored Values"
            SELECT n, CASE n WHEN 1 THEN repeat('雪', 16001) WHEN 2 THEN '' WHEN 3 THEN 'NULL' END,
            1234567890123456789.1234567890, 'fixture'
            FROM generate_series(30, 1, -1) n''')
        db.execute('CREATE VIEW "Admin Fixture".latest AS SELECT id FROM "Admin Fixture"."Stored Values"')
        db.execute('CREATE TABLE "Admin Fixture".empty(id int)')
        db.execute('CREATE TABLE "Admin Fixture".p(id int) PARTITION BY RANGE (id)')
        db.execute('CREATE TABLE "Admin Fixture".p_first PARTITION OF "Admin Fixture".p FOR VALUES FROM (1) TO (10)')
    yield store.connect
    with store.connect() as db:
        db.execute('DROP SCHEMA "Admin Fixture" CASCADE')


def test_postgres_enforces_read_only(database):
    with pytest.raises(errors.ReadOnlySqlTransaction), browser.inspection(database) as db:
        assert db.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
        db.execute('DELETE FROM "Admin Fixture"."Stored Values"')


def test_catalog_structure_and_paged_rows(database):
    asyncio.run(check_http(database))


async def check_http(database):
    app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
    browser.mount(app, database)
    root = '/api/admin/database/'
    selection = dict(schema='Admin Fixture', name='Stored Values')
    async with TestClient(TestServer(app)) as client:
        async def get(view, **params):
            async with client.get(root + view, params=params) as response:
                assert response.status == 200, await response.text()
                assert response.headers['Cache-Control'] == 'no-store'
                return await response.json()

        catalog = await get('catalog')
        assert 'Admin Fixture' in catalog['schemas']
        assert not any(name.startswith('pg_') or name == 'information_schema' for name in catalog['schemas'])
        assert any(o['name'] == 'p_first' and o['partition'] for o in catalog['relations'])
        structure = await get('structure', **selection)
        assert [(c['name'], c['type'], c['nullable']) for c in structure['columns'][:3]] == [
            ('id', 'bigint', False), ('odd column', 'text', True), ('price', 'numeric(32,10)', True)]
        assert "fixture" in structure['columns'][3]['expression']
        assert 'positive_id' in {c['name'] for c in structure['constraints']}
        assert 'fixture_price' in {i['name'] for i in structure['indexes']}
        view = await get('structure', schema=selection['schema'], name='latest')
        assert 'SELECT' in view['view_sql']
        part = await get('structure', schema=selection['schema'], name='p_first')
        assert part['parents'] == [dict(schema=selection['schema'], name='p')]
        first = await get('rows', **selection)
        assert first['primary_key'] == ['id'] and first['next_offset'] == 25
        assert first['rows'][0][0] == dict(text='1', more=False)
        assert first['rows'][0][2] == dict(text='1234567890123456789.1234567890', more=False)
        assert first['rows'][1][1] == dict(text='', more=False)
        assert first['rows'][2][1] == dict(text='NULL', more=False)
        assert first['rows'][3][1] is None
        second = await get('rows', **selection, offset=25)
        assert [row[0]['text'] for row in second['rows']] == ['26', '27', '28', '29', '30']
        assert second['next_offset'] is None and second['previous_offset'] == 0
        assert (await get('rows', schema=selection['schema'], name='empty'))['rows'] == []
        cell = await get('cell', **selection, offset=0, column='odd column')
        assert first['rows'][0][1]['more'] and len(cell['text']) == browser.CELL_CHUNK
        tail = await get('cell', **selection, offset=0, column='odd column', start=cell['next_start'])
        assert tail['text'] == '雪' and tail['next_start'] is None
        assert tail['fingerprint'] == cell['fingerprint']

        for view, params, status in [
            ('rows', dict(schema='pg_catalog', name='pg_class'), 404),
            ('rows', dict(schema=selection['schema'], name='missing'), 404),
            ('rows', dict(selection, offset='-1'), 422),
            ('rows', dict(selection, sql='unsupported'), 422),
            ('cell', dict(selection, column='missing'), 404),
        ]:
            async with client.get(root + view, params=params) as response:
                assert response.status == status
        async with client.get(root + 'catalog', headers={'Sec-Fetch-Site': 'same-site'}) as response:
            assert response.status == 403
        async with client.get(root + 'catalog', headers={'Host': 'external.invalid'}) as response:
            assert response.status == 403
        async with client.post(root + 'rows', json={}, headers={'Origin': str(client.make_url('/')).rstrip('/')}) as response:
            assert response.status == 405
