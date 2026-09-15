"""Disposable-only tests and UI. Never uses the default owner connector."""
import sys, json, unittest
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))

def connect(database='prediction_arb'):
    return psycopg.connect(host='/tmp/prediction-arb-13c.WapyUo/socket',port=55439,
        user='prediction_arb',dbname=database,autocommit=True,row_factory=dict_row)

import app.storage, app.storage.store, app.dashboard.pipeline, app.dashboard.repository
for module in (app.storage,app.storage.store,app.dashboard.pipeline,app.dashboard.repository):
    module.connect=connect
from app.storage import Store
from app.dashboard.controller import Controller
from app.dashboard.pipeline import Pipeline

if __name__=='__main__':
    with connect('postgres') as db:
        if not db.execute("SELECT 1 FROM pg_database WHERE datname='prediction_arb'").fetchone():
            db.execute('CREATE DATABASE prediction_arb')
    with connect() as db:Store(db).migrate()
    if '--serve' not in sys.argv:
        suite=unittest.defaultTestLoader.loadTestsFromName('integration_tests.test_dashboard_storage')
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        sys.exit(not result.wasSuccessful())
    fixtures=json.loads((ROOT/'tests/fixtures/saved_session_status.json').read_text())
    with connect() as db:
        for fixture in fixtures:
            s=fixture['session']
            if db.execute('SELECT 1 FROM capture_session WHERE id=%s',(s['id'],)).fetchone():continue
            db.execute("INSERT INTO capture_session(id,environment,evidence_class,started_at,state,config,provenance) VALUES(%s,%s,%s,%s,%s,'{}',%s)",(s['id'],s['environment'],s['evidence_class'],s['started_at'],s['state'],fixture['source']))
            for e in fixture['coverage']:Store(db).event(s['id'],e['kind'],e['detail'],at=e.get('original_time'))
    # Isolated port only; same server code with its fixed origin/Host allowlist
    # changed in memory. Live is explicitly unavailable in this harness.
    import app.dashboard.server as server
    exec(compile(Path(server.__file__).read_text().replace('127.0.0.1:8765','127.0.0.1:8873'),server.__file__,'exec'),server.__dict__)
    class SyntheticOnly(Controller):
        async def start(self,mode,values):
            if mode!='synthetic':raise ValueError('Isolated verification: synthetic only')
            return await super().start(mode,values)
    from aiohttp import web
    web.run_app(server.create_app(SyntheticOnly()),host='127.0.0.1',port=8873)
