"""Raw values survive failed normalization, changing prices and snapshot paging."""
from copy import deepcopy
from unittest import TestCase,skipUnless
from unittest.mock import patch
from psycopg.types.json import Jsonb
from tests import test_sc02_sql as base
from tests.test_current_service import native_fixture
from app.collection.bulk_checkpoint import save_images
from app.dashboard.raw_price_api import RawReads
from app.storage import raw_prices

@skipUnless(base.SOCKET,'Disposable SQL harness required')
class RawPrices(TestCase):
    connect=classmethod(base.SQL.connect.__func__)
    setUpClass=classmethod(base.SQL.setUpClass.__func__)
    tearDownClass=classmethod(base.SQL.tearDownClass.__func__)

    def test_complete_coherent_pages_and_exact_depth(self):
        _,b=native_fixture();books=[]
        for n in range(115):
            x=deepcopy(b);x['raw']['ref']['market_id']='raw-page-'+str(n).zfill(3);books.append(x)
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):save_images('kalshi',books,'rejected')
        reads=RawReads(self.connect)
        try:
            first=reads.read(dict(search='raw-page-',limit='50'))
            self.assertEqual(first['total_books'],115)
            self.assertTrue(all(b['status']=='unqualified' for b in first['books']))
            captured=first['books'][0]
            newer=deepcopy(books[0]);newer['raw']['received_at']='2099-01-01T00:00:00Z'
            with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):save_images('kalshi',[newer],'pending')
            rows=list(first['books']);offset=first['next_offset']
            while offset is not None:
                page=reads.read(dict(search='raw-page-',limit='50',offset=str(offset),token=first['token']))
                rows+=page['books'];offset=page['next_offset']
            self.assertEqual(len({r['id'] for r in rows}),115)
            self.assertEqual(reads.read(dict(search='raw-page-',limit='50',token=first['token']))['books'][0]['revision'],captured['revision'])
            fresh=reads.read(dict(search='raw-page-',limit='50'))
            self.assertNotEqual(fresh['books'][0]['revision'],captured['revision'])
            q={k:captured[k] for k in ('kind','venue','sport','event_id','market_id','revision')};q['token']=first['token']
            q.update(outcome=captured['observations'][0]['outcome_id'],side='asks')
            detail=reads.detail(q)
            self.assertEqual(detail['revision'],captured['revision'])
            self.assertEqual(detail['depth_page']['levels'],books[0]['outcomes'][0]['asks']['levels'])
        finally:reads.close()

    def test_aggregate_alternates_invalid_values_and_delete(self):
        from app.storage.aggregate_receipts import save
        from app.storage.store import now

        event=dict(id='raw-alternate',away_team='A',home_team='B',bookmakers=[dict(key='novig',markets=[dict(key='alternate_spreads',outcomes=[dict(name='A',point='-2.5',price='NaN'),dict(name='A',point='-3.5',price='2.0')])])])
        with self.connect() as db:
            save(db, kind='alternate', sport='NFL', event_id=event['id'], received_at=now(),
                 cycle_id='cycle', receipt_sha256='hash', disposition='pending', payload=event)
            rows=raw_prices.page(db,dict(event_id=event['id']),0,100,{})
            self.assertEqual(len(rows),1)
            self.assertEqual(len(rows[0]['observations']),2)
            self.assertEqual(rows[0]['observations'][0]['disposition'],'invalid_price')
            self.assertEqual(rows[0]['financial']['state'],'unavailable')
            db.execute("DELETE FROM current_aggregate_receipt WHERE provider='the_odds_api' AND kind='alternate' AND event_id=%s",(event['id'],))
            self.assertEqual(raw_prices.total(db,dict(event_id=event['id'])),0)

    def test_aggregate_receipt_upgrade_preserves_scope_and_raw_display(self):
        from uuid import uuid4
        from psycopg import sql
        from app.storage.store import Store

        name = 'prediction_arb_aggregate_upgrade_' + uuid4().hex[:8]
        featured = dict(id='f', away_team='Away', home_team='Home',
                        bookmakers=[dict(key='novig', last_update='2026-11-10T21:00:00Z',
                                         markets=[dict(key='h2h', outcomes=[dict(name='Home', price='2.01')])])])
        alternate = dict(id='a', away_team='Away', home_team='Home',
                         bookmakers=[dict(key='pinnacle', last_update='2026-11-10T21:00:10Z',
                                          markets=[dict(key='alternate_spreads',
                                                        outcomes=[dict(name='Away', point='1.5', price='2.08')])])])
        featured_payload = dict(events=[featured], dispositions=[{'source': 'legacy'}])
        census_payload = [{'id': 'f'}, {'id': 'a'}]
        receipt = '2026-11-10T21:00:17Z'
        with self.connect('prediction_arb') as control:
            control.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            try:
                with self.connect(name) as db:
                    Store(db).migrate(through='083_publication_member_order.sql')
                    db.execute('INSERT INTO current_acquisition_aggregate VALUES (%s,%s,%s)',
                               ('NFL', receipt, Jsonb(featured_payload)))
                    db.execute('INSERT INTO current_acquisition_alternate VALUES (%s,%s,%s,%s,%s,%s,%s)',
                               ('NFL', 'a', receipt, 'cycle', 'alternate-digest', 'admitted_exact_lines', Jsonb(alternate)))
                    db.execute('INSERT INTO current_acquisition_event_census VALUES (%s,%s,%s,%s,%s)',
                               ('NFL', 'cycle', receipt, 'census-digest', Jsonb(census_payload)))
                    before = db.execute('SELECT * FROM raw_aggregate_display ORDER BY kind').fetchall()
                    Store(db).migrate(through='089_acquisition_receipts.sql')
                    self.assertEqual(db.execute('SELECT * FROM raw_aggregate_display ORDER BY kind').fetchall(), before)
                    rows = {r['kind']:r for r in db.execute('SELECT * FROM current_aggregate_receipt').fetchall()}
                    self.assertEqual({kind:r['payload'] for kind,r in rows.items()},
                        dict(featured=featured_payload, alternate=alternate, census=census_payload))
                    self.assertEqual({kind:r['receipt_sha256'] for kind,r in rows.items()},
                        dict(featured=None, alternate='alternate-digest', census='census-digest'))
                    from datetime import datetime
                    self.assertEqual({r['received_at'] for r in rows.values()}, {datetime.fromisoformat(receipt)})
                    self.assertEqual(db.execute("SELECT relkind FROM pg_class WHERE oid='raw_aggregate_display'::regclass").fetchone()['relkind'], 'v')
            finally:
                control.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))

    def test_sync_is_independent_of_old_price_and_revoked_on_generation(self):
        row=dict(kind='native',venue='kalshi',runtime_id='r',connection_generation=2,census_generation='c',generation='c',withdrawn=False,market_id='m',disposition='pending')
        owner=dict(active=True,healthy=True,runtime_id='r',status=dict(sources=[dict(provider='kalshi',metrics=dict(stream_connected=True,synchronization=dict(generation=2,current=True,continuity_intact=True)))]))
        self.assertEqual(raw_prices.status(row,owner),'synchronized')
        self.assertEqual(raw_prices.status(dict(row,connection_generation=1),owner),'last_known')
        self.assertEqual(raw_prices.status(row,dict(owner,global_stopped=True)),'last_known')
        self.assertEqual(raw_prices.status(row,dict(owner,healthy=False)),'last_known')

    def test_top_page_does_not_transfer_wire_depth(self):
        _,book=native_fixture();book['raw']['ref']['market_id']='raw-no-wire'
        book['raw']['json_text']='private-wire-depth-marker'
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):save_images('kalshi',[book],'pending')
        reads=RawReads(self.connect)
        try:
            page=reads.read(dict(search='raw-no-wire'))
            self.assertNotIn('json_text',page['books'][0]['provenance']['raw'])
            b=page['books'][0];q={k:b[k] for k in ('kind','venue','sport','event_id','market_id','revision')};q['token']=page['token']
            self.assertEqual(reads.detail(q)['native_wire'],'private-wire-depth-marker')
        finally:reads.close()

    def test_filters_and_expiry_are_explicit(self):
        from app.dashboard.local_security import PublicRequestError
        _,book=native_fixture();book['raw']['ref']['market_id']='filter-raw-only'
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):save_images('kalshi',[book],'rejected')
        reads=RawReads(self.connect)
        try:
            page=reads.read(dict(search='filter-raw-only',venue='kalshi',state='unqualified'))
            self.assertEqual(page['total_books'],1)
            with self.assertRaises(PublicRequestError):reads.read(dict(token=page['token'],venue='polymarket_us'))
            reads.frames[page['token']]['expires']=0
            with self.assertRaises(PublicRequestError):reads.read(dict(token=page['token'],search='filter-raw-only',venue='kalshi',state='unqualified'))
            self.assertFalse(reads.frames)
        finally:reads.close()


from unittest import IsolatedAsyncioTestCase

@skipUnless(base.SOCKET,'Disposable SQL harness required')
class RawHTTP(IsolatedAsyncioTestCase):
    connect=classmethod(base.SQL.connect.__func__)
    setUpClass=classmethod(base.SQL.setUpClass.__func__)
    tearDownClass=classmethod(base.SQL.tearDownClass.__func__)

    async def test_http_pages_originals_and_complete_streamed_export(self):
        import json
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.raw_price_api import mount
        from app.dashboard.request_guard import dashboard_guard
        _,book=native_fixture();book['raw']['ref']['market_id']='http-raw-input'
        with patch('app.collection.bulk_checkpoint.connect',side_effect=self.connect):save_images('kalshi',[book],'pending')
        app=web.Application(middlewares=[dashboard_guard(None,logger=__name__)])
        with patch('app.dashboard.raw_price_api.connect',side_effect=self.connect):
            mount(app)
            async with TestClient(TestServer(app)) as client:
                response=await client.get('/api/raw/prices?limit=100');self.assertEqual(response.status,200)
                page=await response.json();b=next(b for b in page['books'] if b['market_id']=='http-raw-input')
                q={k:b[k] for k in ('kind','venue','sport','event_id','market_id','revision')};q['token']=page['token']
                response=await client.get('/api/raw/inputs',params=q)
                self.assertEqual(response.status,200);detail=await response.json();self.assertEqual(detail['revision'],b['revision'])
                response=await client.get('/api/raw/export');self.assertEqual(response.status,200)
                lines=[json.loads(line) for line in (await response.text()).splitlines()]
                self.assertTrue(lines[-1]['export_complete'])
                self.assertEqual(lines[-1]['books'],page['total_books'])
                exported=next(v for v in lines if v.get('market_id')=='http-raw-input')
                self.assertEqual(exported['observations'],b['observations'])
                self.assertTrue(any('depth' in v for v in lines))
                self.assertTrue(any('native_wire' in v for v in lines))
                observation=b['observations'][0]
                calculation_q=dict(q,outcome=observation['outcome_id'],side=observation['side'])
                response=await client.get('/api/raw/calculations',params=calculation_q)
                self.assertEqual(response.status,200)
                self.assertEqual((await response.json())['state'],'unavailable')
                self.assertEqual((await client.get('/api/raw/prices?limit=101')).status,422)
                self.assertEqual((await client.delete('/api/raw/read',params={'token':page['token']},headers={'Origin':str(client.make_url('/')).rstrip('/'),'Content-Type':'application/json'})).status,200)
                self.assertEqual((await client.get('/api/raw/inputs',params=q)).status,422)

    def test_aborted_snapshot_is_closed_and_refresh_recovers(self):
        import psycopg
        from app.dashboard.local_security import PublicRequestError
        reads=RawReads(self.connect)
        opened=[]
        def fail_sql(db,*args):
            opened.append(db)
            db.execute('SELECT 1/0')
        try:
            # First-page failure never leaves an undisclosed lease consuming capacity.
            for _ in range(9):
                with patch.object(raw_prices,'headers',side_effect=fail_sql):
                    with self.assertRaises(psycopg.errors.DivisionByZero):reads.read({})
                self.assertEqual(reads.frames,{})
                self.assertTrue(opened[-1].closed)
            first=reads.read({});token=first['token'];db=reads.frames[token]['db']
            with patch.object(raw_prices,'headers',side_effect=fail_sql):
                with self.assertRaises(psycopg.errors.DivisionByZero):reads.read({'token':token})
            self.assertTrue(db.closed)
            with self.assertRaises(PublicRequestError):reads.read({'token':token})
            self.assertNotEqual(reads.read({})['token'],token)
        finally:reads.close()

    def test_invalid_selection_keeps_healthy_snapshot_but_sql_failure_retires_it(self):
        import psycopg
        from app.dashboard.local_security import PublicRequestError
        reads=RawReads(self.connect)
        try:
            token=reads.read({})['token'];db=reads.frames[token]['db']
            query=dict(token=token,kind='native',venue='kalshi',sport='NFL',
                event_id='absent',market_id='absent',revision='absent')
            with self.assertRaises(PublicRequestError):reads.detail(query)
            self.assertIn(token,reads.frames)
            self.assertFalse(db.closed)
            try:db.execute('SELECT 1/0')
            except psycopg.errors.DivisionByZero:pass
            with self.assertRaises(psycopg.errors.InFailedSqlTransaction):reads.detail(query)
            self.assertTrue(db.closed)
            self.assertNotIn(token,reads.frames)
        finally:reads.close()


class CapturedAssociation(TestCase):
    def test_different_input_or_bid_complement_never_associates(self):
        from app.storage.raw_calculations import matches,read
        b=dict(provider='kalshi',venue='kalshi',event_id='e',market_id='m',revision='raw-new')
        o=dict(outcome_id='yes',native_side='yes',side='asks')
        p=dict(quote_id='q',venue='kalshi',source=dict(provider='kalshi',native_event_id='e',native_market_id='m',native_outcome_id='yes',native_side='yes',quote_side='buy'),original=dict(value='0.41'),times=dict(received_at='old'))
        self.assertTrue(matches(p,b,o))
        self.assertFalse(matches(p,b,dict(o,side='bids')))
        self.assertFalse(matches(p,b,dict(o,native_side='no')))
        self.assertFalse(matches(dict(p,original=dict(transformation='one_minus_native_bid')),b,o))
        from app.storage import ordinary_evidence as evidence
        row=dict(p,id='r',game_key='g')
        member=dict(id='result',snapshot_id='capture',rows=[row],pairs=[],
                    captured_at='old',calculated_at='old',assumptions={'revision':'old-policy'})
        index={evidence.event_id(dict(provider='kalshi',native_event_id='e')):[{'member_id':'result'}]}
        with patch.object(evidence,'members',return_value=index), patch.object(evidence,'read_member',return_value=member):
            result=read(None,b,o)
        self.assertEqual(result['state'],'captured_result')
        self.assertFalse(result['results'][0]['current_eligibility'])
        self.assertEqual(result['results'][0]['captured_inputs'][0]['times']['received_at'],'old')
        self.assertEqual(result['results'][0]['raw_revision'],'raw-new')

    def test_rotating_partial_coverage_keeps_exact_current_image_status(self):
        from app.storage.raw_prices import status,state_expression
        metrics=dict(stream_connected=True,invalid_current_market_ids=[],synchronization=dict(
            current=False,continuity_intact=True,generation=7,oldest_processing_delay_seconds=.3,
            coverage_state='rotating_partial',deferred_markets=1000))
        owner=dict(active=True,healthy=True,runtime_id='run',status=dict(sources=[dict(provider='kalshi',metrics=metrics)]))
        row=dict(kind='native',venue='kalshi',runtime_id='run',connection_generation=7,
            census_generation='census',generation='census',market_id='m',withdrawn=False,disposition='accepted')
        self.assertEqual(status(row,owner),'synchronized')
        self.assertEqual(state_expression(owner)[1][-1],'synchronized')
        self.assertEqual(status(dict(row,connection_generation=6),owner),'last_known')
        metrics['synchronization']['oldest_processing_delay_seconds']=3
        self.assertEqual(status(row,owner),'delayed')
        self.assertEqual(state_expression(owner)[1][-1],'delayed')
        metrics['invalid_current_market_ids']=['m']
        self.assertEqual(status(row,owner),'last_known')

    def test_aggregate_refresh_is_separate_and_stop_keeps_last_known(self):
        from app.storage.raw_prices import status,source_information,state_expression
        row=dict(kind='featured',venue='novig')
        owner=dict(active=True,healthy=True,status=dict(quota=dict(next_due_at='2099-01-01T00:00:00Z')))
        with __import__('unittest.mock',fromlist=['patch']).patch('app.storage.raw_prices.datetime') as clock:
            clock.now.return_value.hour=12
            self.assertEqual(status(row,owner),'aggregate')
            clock.now.return_value.hour=1
            self.assertEqual(status(row,owner),'last_known')
            self.assertEqual(source_information(owner,'novig')['refresh_status'],'outside_operating_hours')
        self.assertEqual(source_information(owner,'novig')['refresh_seconds'],900)
        self.assertEqual(status(row,dict(owner,global_stopped=True)),'last_known')
        expression,args=state_expression(dict(owner,global_stopped=True))
        self.assertEqual(args[0],'last_known')
