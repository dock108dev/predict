"""Received-data inspection must survive failed calculation and source updates."""

from copy import deepcopy
from unittest import TestCase, skipUnless
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from psycopg.types.json import Jsonb

from app.collection.sportsgameodds_current_rows import current_rows
from app.dashboard.research_api import CatalogReads, mount
from app.dashboard.request_guard import dashboard_guard
from app.storage import research_catalog as catalog
from app.storage.current_rows import CurrentRowStore, contract_id
from app.storage.sportsgameodds_reference import (
    offer_quote_link, prepare_frames, prepare_page, upsert_frames, upsert_rows,
)
from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import AT, PregameFixture, page, parse


class Classification(TestCase):
    def test_exact_zero_negative_positive_and_unknown_remain_distinct(self):
        for ratio, status, percent in (('0', 'zero', '0'), ('-1/200', 'negative', '-1/2'), ('1/25', 'positive', '4')):
            with self.subTest(ratio=ratio):
                value = catalog.calculation_state({'raw': {'net_ev': ratio}}, None, contract_id='contract')
                self.assertEqual((value['status'], value['net_ev_percent']), (status, percent))
        missing = catalog.calculation_state(None, 'fee_unknown', contract_id='contract')
        self.assertEqual(missing['status'], 'unavailable')
        self.assertIsNone(missing['net_ev_percent'])
        self.assertEqual(missing['reason'], 'fee_unknown')


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class ResearchCatalogSQL(PregameFixture):
    def ingest_linked(self, db, data):
        parsed = parse(data)
        refs = prepare_page(parsed)
        records = current_rows(parsed, parsed.receipt_sha256)[0]
        witnesses = {ref['id']: ref for ref in refs}
        links = {contract_id(record): offer_quote_link(record, witnesses) for record in records}
        with db.transaction():
            upsert_rows(db, refs)
            upsert_frames(db, prepare_frames(parsed, refs))
            CurrentRowStore(db).upsert_records(records, now=AT, quote_links=links)
        return refs

    async def test_source_catalog_survives_fee_refusal_and_keeps_ambiguous_book(self):
        data = page()
        for odd in data['data'][0]['odds'].values():
            odd['byBookmaker']['polymarket'] = deepcopy(odd['byBookmaker']['fanduel'])
        with self.connect() as db:
            refs = self.ingest_linked(db, data)
            self.process(db)
            target = db.execute("SELECT k.contract_id FROM current_pregame_calculation k JOIN current_offer_storage o USING(contract_id) JOIN current_contract_storage c ON c.id=k.contract_id WHERE o.sgo_quote_id IS NOT NULL AND c.venue='prophetx' LIMIT 1").fetchone()['contract_id']
            db.execute('''UPDATE current_pregame_calculation SET reason='fee_unknown',payload=NULL,
                net_ev=NULL,opportunity_score=NULL WHERE contract_id=%s''', (target,))
            db.execute('DELETE FROM current_pregame_price WHERE contract_id=%s', (target,))
        reads = CatalogReads(self.connect)
        try:
            captured = reads.read({'provider': 'sportsgameodds', 'limit': '100'})
            self.assertEqual(captured['total'], len(refs))
            self.assertEqual(captured['counts']['source_events'], 1)
            self.assertEqual(captured['provider_requests'], 0)
            self.assertEqual(captured['scheduled_calculations'], 0)
            row = next(row for row in captured['rows'] if row['identity']['contract_id'] == target)
            self.assertIsNotNone(row['price'])
            self.assertIsNone(row['calculation']['net_ev_percent'])
            self.assertEqual(row['calculation']['reason'], 'fee_unknown')
            detail = reads.detail(dict(token=captured['token'], id=row['id'], revision=row['revision']))
            self.assertIsNone(detail['fee_input'])
            self.assertIsNotNone(detail['normalized_record']['quote']['times']['received_at'])
            self.assertEqual(detail['source_input']['price_american'], row['price'])
            ambiguous = next(row for row in captured['rows'] if row['original_bookmaker_id'] == 'polymarket')
            self.assertEqual(ambiguous['represented_venue'], 'polymarket_us')
            self.assertEqual(ambiguous['venue_equivalence'], 'unestablished')
            self.assertEqual(ambiguous['calculation']['reason'], 'provider_venue_fee_applicability_unestablished')
            trusted = [row for row in captured['rows'] if row['original_bookmaker_id'] in ('fanduel', 'draftkings')]
            self.assertTrue(trusted)
            self.assertTrue(all(row['identity']['contract_id'] is None for row in trusted))
        finally:
            reads.close()

    async def test_snapshot_keeps_source_and_calculation_revision_after_new_receipt(self):
        with self.connect() as db:
            self.ingest_linked(db, page())
            self.process(db)
        reads = CatalogReads(self.connect)
        try:
            first = reads.read({'provider': 'sportsgameodds', 'limit': '100'})
            selected = next(row for row in first['rows'] if row['identity']['contract_id'])
            query = dict(token=first['token'], id=selected['id'], revision=selected['revision'])
            original = reads.detail(query)
            with self.connect() as db:
                qid = selected['id'].removeprefix('sgo:')
                # A new received clock must not mutate the captured read.
                db.execute("UPDATE sgo_quote_revision SET facts=jsonb_set(facts,'{received_at}',%s) WHERE id=%s AND is_current",
                    (Jsonb('2026-11-18T20:00:00Z'), qid))
            again = reads.detail(query)
            self.assertEqual(again, original)
            fresh = reads.read({'provider': 'sportsgameodds', 'limit': '100'})
            latest = next(row for row in fresh['rows'] if row['id'] == selected['id'])
            self.assertNotEqual(latest['revision'], selected['revision'])
            self.assertEqual(latest['calculation_revision'], selected['calculation_revision'])
        finally:
            reads.close()

    async def test_http_export_is_the_captured_record_and_passive_reads_do_not_write(self):
        with self.connect() as db:
            self.ingest_linked(db, page())
            self.process(db)
            before = list(db.execute('SELECT * FROM current_pregame_calculation ORDER BY contract_id'))
        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        with patch('app.dashboard.research_api.connect', side_effect=self.connect):
            mount(app)
            async with TestClient(TestServer(app)) as client:
                response = await client.get('/api/research/catalog?provider=sportsgameodds&limit=100')
                self.assertEqual(response.status, 200, await response.text())
                value = await response.json()
                row = next(row for row in value['rows'] if row['identity']['contract_id'])
                query = dict(token=value['token'], id=row['id'], revision=row['revision'])
                detail_response = await client.get('/api/research/input', params=query)
                self.assertEqual(detail_response.status, 200, await detail_response.text())
                detail = await detail_response.json()
                exported = await client.get('/api/research/export', params=query)
                self.assertEqual(exported.status, 200)
                self.assertEqual(await exported.json(), detail)
                self.assertEqual(detail['revision'], row['revision'])
                self.assertEqual(detail['provider_requests'], 0)
                rejected = await client.get('/api/research/catalog?calculation_status=profits_only')
                self.assertEqual(rejected.status, 422)
        with self.connect() as db:
            self.assertEqual(list(db.execute('SELECT * FROM current_pregame_calculation ORDER BY contract_id')), before)

    async def test_withdrawn_and_unmatched_source_values_are_not_qualification_filtered(self):
        with self.connect() as db:
            refs = self.ingest_linked(db, page())
            withdrawn = refs[0]['id']
            db.execute('''INSERT INTO sgo_line_presence(quote_id,event_id,bookmaker_id,odd_id,last_seen,scope_received,expired)
                SELECT id,event_id,bookmaker_id,facts->>'odd_id',received_order,received_order,true
                FROM sgo_quote_revision WHERE id=%s AND is_current''', (withdrawn,))
        reads = CatalogReads(self.connect)
        try:
            captured = reads.read({'provider': 'sportsgameodds', 'limit': '100'})
            self.assertEqual(captured['total'], len(refs))
            selected = next(row for row in captured['rows'] if row['id'] == 'sgo:'+withdrawn)
            self.assertFalse(selected['available'])
            self.assertEqual(selected['availability_reason'], 'line_withdrawn')
            self.assertEqual(selected['calculation']['freshness'], 'source_unavailable')
            self.assertIsNotNone(selected['price'])
        finally:
            reads.close()

    async def test_rejected_native_book_keeps_received_values_and_original_wire(self):
        from app.collection.bulk_checkpoint import save_images
        from tests.test_current_service import native_fixture

        _, book = native_fixture()
        book['raw']['ref']['market_id'] = 'research-rejected-native'
        book['raw']['json_text'] = '{"native_wire":"portable captured input"}'
        with patch('app.collection.bulk_checkpoint.connect', side_effect=self.connect):
            save_images('kalshi', [book], 'rejected')
        reads = CatalogReads(self.connect)
        try:
            captured = reads.read({'provider': 'kalshi', 'search': 'research-rejected-native'})
            row, = captured['rows']
            self.assertEqual(row['kind'], 'raw')
            self.assertIsNone(row['identity']['contract_id'])
            self.assertTrue(row['raw_observations'])
            detail = reads.detail(dict(token=captured['token'], id=row['id'], revision=row['revision']))
            self.assertEqual(detail['source_input']['validation'], 'rejected')
            self.assertEqual(detail['native_wire'], book['raw']['json_text'])
            self.assertEqual(detail['original_response']['state'], 'native_current_wire_retained')
            self.assertEqual(detail['provider_requests'], 0)
        finally:
            reads.close()

    async def test_unestablished_us_alias_retains_old_numeric_witness_without_applicable_ev(self):
        data = page()
        for odd in data['data'][0]['odds'].values():
            odd['byBookmaker']['polymarket'] = deepcopy(odd['byBookmaker']['fanduel'])
        with self.connect() as db:
            self.ingest_linked(db, data)
            self.process(db)
            legacy = deepcopy(db.execute('SELECT payload FROM current_pregame_calculation WHERE payload IS NOT NULL LIMIT 1').fetchone()['payload'])
            legacy['raw']['net_ev'] = '1/10'
            legacy['display']['net_ev'] = '+10.00%'
            poly = db.execute("SELECT id FROM current_contract WHERE venue='polymarket_us' LIMIT 1").fetchone()['id']
            legacy['id'] = poly
            # The repaired writer need not create a calculation for this alias.
            # Explicitly inject the older writer's numeric result to exercise
            # read-time withholding before any rebuild can replace it.
            inserted = db.execute('''INSERT INTO public.current_pregame_calculation
                (contract_id,game_key,bet_id,league,family,venue,start_at,main,input_revision,
                 version,valid_until,net_ev,opportunity_score,reason,payload)
                SELECT %s,game_key,bet_id,league,family,'polymarket_us',start_at,main,input_revision,
                    version,valid_until,0.1,1,NULL,%s FROM public.current_pregame_calculation
                WHERE payload IS NOT NULL LIMIT 1
                ON CONFLICT(contract_id) DO UPDATE SET reason=NULL,payload=excluded.payload,
                    net_ev=excluded.net_ev,opportunity_score=excluded.opportunity_score
                RETURNING contract_id''', (poly, Jsonb(legacy))).fetchone()
            self.assertEqual(inserted['contract_id'], poly)
        reads = CatalogReads(self.connect)
        try:
            filters = dict(provider='sportsgameodds', original_bookmaker_id='polymarket')
            captured = reads.read(filters)
            selected = next(row for row in captured['rows'] if row['identity']['contract_id'] == poly)
            self.assertIsNotNone(selected['price'])
            self.assertEqual(selected['calculation']['status'], 'unavailable')
            self.assertIsNone(selected['calculation']['net_ev_percent'])
            self.assertEqual(selected['calculation']['reason'], 'provider_venue_fee_applicability_unestablished')
            detail = reads.detail(dict(token=captured['token'], id=selected['id'], revision=selected['revision']))
            self.assertIsNone(detail['calculation_payload'])
            self.assertIsNone(detail['fee_input'])
            self.assertEqual(detail['historical_conditional_calculation'], legacy)
            self.assertEqual(reads.read(dict(filters, calculation_status='positive'))['total'], 0)
            self.assertEqual(reads.read(dict(filters, calculation_status='negative'))['total'], 0)
            from app.research.records import preserve_conditional
            with self.connect() as db:
                prior = preserve_conditional(db, legacy, record={'retained_source': True}, fee_input={'conditional': True})
                db.execute('''UPDATE public.current_pregame_calculation SET reason=%s,
                    payload=NULL,net_ev=NULL,opportunity_score=NULL WHERE contract_id=%s''',
                    ('provider_venue_fee_applicability_unestablished', poly))
            rebuilt = reads.read(filters)
            selected = next(row for row in rebuilt['rows'] if row['identity']['contract_id'] == poly)
            detail = reads.detail(dict(token=rebuilt['token'], id=selected['id'], revision=selected['revision']))
            self.assertIsNone(detail['calculation_payload'])
            self.assertEqual(detail['historical_conditional_calculation'], legacy)
            self.assertEqual(detail['historical_conditional_history'][0]['id'], prior['id'])
        finally:
            reads.close()

    async def test_cohort_http_download_contains_complete_frozen_input_and_result_evidence(self):
        from datetime import timedelta
        from app.research import records
        from app.storage.store import stamp

        at = stamp(AT)
        with self.connect() as db:
            self.ingest_linked(db, page())
            self.process(db)
            row = db.execute('''SELECT k.payload,p.record,p.fee_input
                FROM current_pregame_calculation k JOIN current_pregame_price p USING(contract_id)
                WHERE k.payload IS NOT NULL LIMIT 1''').fetchone()
            payload = row['payload']
            case = dict(case_key='http-export-case', event_id=payload['game_key'],
                starts_at=payload['kickoff'], family=payload['family'], period=payload['period'],
                line=row['record']['market_identity']['line'])
            cohort = records.declare(db, name='portable-http-frozen-evidence', cases=[case],
                designation='synthetic_demonstration', horizons=[3600], at=at-timedelta(minutes=1))
            observed = records.observe(db, cohort['id'], case['case_key'], payload, known_at=at,
                record=row['record'], fee_input=row['fee_input'])
            records.capture_due(db, at=at+timedelta(seconds=1), cohort_id=cohort['id'])
            records.annotate(db, cohort['id'], case['case_key'], 'sporting',
                dict(source='portable-fixture-score', final=True, result='completed',
                    home_score=100, away_score=90, published_at=None,
                    observed_at=(at+timedelta(hours=2)).isoformat()), at=at+timedelta(hours=2))
            records.evaluate(db, cohort['id'], as_of=at+timedelta(hours=3), persist=True)
            before = list(db.execute('SELECT * FROM public.research_record ORDER BY id'))
        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        with patch('app.dashboard.research_api.connect', side_effect=self.connect):
            mount(app)
            async with TestClient(TestServer(app)) as client:
                detail = await client.get('/api/research/cohorts', params={'id': cohort['id']})
                self.assertEqual(detail.status, 200, await detail.text())
                self.assertNotIn('records', await detail.json())
                response = await client.get('/api/research/cohorts', params={'id': cohort['id'], 'export': '1'})
                self.assertEqual(response.status, 200, await response.text())
                self.assertIn('attachment', response.headers['Content-Disposition'])
                exported = await response.json()
                self.assertEqual(exported['cohort_id'], cohort['id'])
                self.assertEqual(exported['provider_requests'], 0)
                self.assertEqual(exported['manifest']['record_count'], len(exported['records']))
                self.assertTrue({'cohort', 'observation', 'capture', 'sporting', 'evaluation'} <= {r['kind'] for r in exported['records']})
                self.assertTrue(all(r['recorded_at'] for r in exported['records']))
                observed_export = next(r for r in exported['records'] if r['id'] == observed['id'])
                frozen = observed_export['payload']['snapshot']['inputs']
                self.assertEqual(frozen['source_record'], row['record'])
                self.assertEqual(frozen['fee_input'], row['fee_input'])
                self.assertEqual(frozen['calculation']['fee']['cashflows'], payload['fee']['cashflows'])
                self.assertEqual((await client.get('/api/research/cohorts?export=1')).status, 422)
        with self.connect() as db:
            self.assertEqual(before, list(db.execute('SELECT * FROM public.research_record ORDER BY id')))

    async def test_cohort_api_exposes_counted_retention_gaps_and_keeps_prior_counts_null(self):
        from datetime import timedelta
        from app.research import records
        from app.storage.store import stamp

        at = stamp(AT)
        with self.connect() as db:
            self.ingest_linked(db, page())
            self.process(db)
            row = db.execute('''SELECT k.payload,p.record,p.fee_input
                FROM current_pregame_calculation k JOIN current_pregame_price p USING(contract_id)
                WHERE k.payload IS NOT NULL LIMIT 1''').fetchone()
            payload = row['payload']
            case = dict(case_key='http-retention-case', event_id=payload['game_key'],
                starts_at=payload['kickoff'], family=payload['family'], period=payload['period'],
                line=row['record']['market_identity']['line'])
            cohort = records.declare(db, name='portable-http-retention-coverage', cases=[case],
                designation='synthetic_demonstration', horizons=[3600], at=at-timedelta(minutes=1))
            records.note_prior_retention_gap(db, first_observed_at=at-timedelta(minutes=5),
                evidence_reference='portable-fixture:previous-uncounted-window')
            previous = records.status(db)['retention_dispositions']
            with patch.object(records, 'OBSERVATION_BYTE_CAP', 1):
                with self.assertRaisesRegex(ValueError, 'research_retention_capacity'):
                    records.observe(db, cohort['id'], case['case_key'], payload, known_at=at,
                        record=row['record'], fee_input=row['fee_input'])
            with patch.object(records, 'TOTAL_BYTE_CAP', 1):
                self.assertEqual(records.capture_due(db, at=at+timedelta(seconds=1), cohort_id=cohort['id']), [])
            before_records = list(db.execute('SELECT * FROM public.research_record ORDER BY id'))
            before_counts = list(db.execute('SELECT * FROM public.research_retention_disposition ORDER BY cohort_id,case_key,slot'))
        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        with patch('app.dashboard.research_api.connect', side_effect=self.connect):
            mount(app)
            async with TestClient(TestServer(app)) as client:
                response = await client.get('/api/research/cohorts')
                self.assertEqual(response.status, 200, await response.text())
                status = (await response.json())['research_retention']
                self.assertEqual(status['retention_dispositions']['observation_refusals'], previous['observation_refusals']+1)
                self.assertEqual(status['retention_dispositions']['capture_refusals'], previous['capture_refusals']+1)
                self.assertEqual(status['observation_byte_cap'], records.OBSERVATION_BYTE_CAP)
                self.assertGreaterEqual(status['observation_bytes'], 0)
                self.assertIsNone(status['retention_accounting']['prior_refused_attempts'])
                self.assertIsNone(status['retention_accounting']['prior_affected_cases'])
                self.assertIsNotNone(status['retention_accounting']['coverage_started_at'])
                detail = await (await client.get('/api/research/cohorts', params={'id': cohort['id']})).json()
                self.assertEqual(detail['research_retention'], status)
                exported = await (await client.get('/api/research/cohorts', params={'id': cohort['id'], 'export': '1'})).json()
                self.assertEqual(exported['research_retention'], status)
                self.assertEqual(exported['retention_dispositions'][0]['capture_refusals'], 1)
                self.assertIsNone(exported['research_retention']['retention_accounting']['prior_refused_attempts'])
        with self.connect() as db:
            self.assertEqual(before_records, list(db.execute('SELECT * FROM public.research_record ORDER BY id')))
            self.assertEqual(before_counts, list(db.execute('SELECT * FROM public.research_retention_disposition ORDER BY cohort_id,case_key,slot')))
