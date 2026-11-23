"""Frozen pull scope replacement, exact headline selection and passive exports."""

from copy import deepcopy
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from psycopg.types.json import Jsonb

from app.dashboard.local_security import PublicRequestError
from app.dashboard.research_api import CatalogReads, mount
from app.dashboard.request_guard import dashboard_guard
from app.storage import acquisition_snapshot as acquisition, market_board
from app.storage.store import stamp
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_ev_movement import offer
from app.comparison.reference_scope import REQUEST_BOOKS
from app.collection.sportsgameodds_transport import ODD_IDS


AT = '2026-11-22T22:00:02Z'
SCOPE = dict(eventIDs='source-game',bookmakerID=','.join(REQUEST_BOOKS),
    oddID=','.join(ODD_IDS),includeAltLines=True)


def captured_offer(*, ev='1/10', line='-3', venue='kalshi', main='main', family='spread', side='home'):
    value = offer(line=line,book=venue,side=side)
    value['main'] = dict(status=main,source='source_reported')
    value['calculation_payload']['raw']['net_ev'] = ev
    value['record']['market_identity']['family'] = family
    if family == 'moneyline':
        value['record']['selection'].update(predicate='win',signed_line=None)
        value['record']['market_identity']['line'] = None
    elif family == 'total':
        value['record']['selection']['predicate'] = side
    return value


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class MarketBoardSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        with self.connect() as db:
            db.execute('TRUNCATE public.market_pull CASCADE')

    def start(self, db, *, scope=None):
        return acquisition.start(db,scope or SCOPE,at=stamp(AT),event=dict(title='Away at Home',
            league='NBA',starts_at='2026-11-23T01:00:00Z'))

    def assert_exact_headline(self, expected, actual):
        # List rows carry a compact projection; exact detail restores the full
        # immutable calculation and every supporting reference candidate.
        for key in ('id','revision','pull_id','exact_bet_id','outcome','side','line',
                    'venue','price','price_units','main_role','calculation','times','fee_mode'):
            self.assertEqual(expected[key],actual[key],key)
        for key in ('book','probability','selection_policy'):
            self.assertEqual((expected.get('reference') or {}).get(key),
                             (actual.get('reference') or {}).get(key),key)

    def publish(self, db, pull_id, *offers, state='complete', transform=None, canonical_game_id=None):
        from app.comparison.acquisition import validate

        provenance = dict(pull_id=pull_id,attempt_id='accepted:'+pull_id,
            receipt_sha256='fixture-receipt:'+pull_id,received_at=AT)
        db.execute('''INSERT INTO public.market_pull_receipt
            (pull_id,attempt_id,receipt_sha256,received_at,membership) VALUES(%s,%s,%s,%s,%s)''',
            (pull_id,provenance['attempt_id'],provenance['receipt_sha256'],AT,
             Jsonb(dict(event_ids=['source-game'],next_cursor_present=False))))
        for item in offers:
            item['record']['comparison_source_metadata']['acquisition'] = dict(provenance)
            item['calculation_payload']['reference']['required_input_prices'] = [
                dict(acquisition=dict(provenance),received_at=AT) for _ in range(4)]
            item['calculation_payload']['acquisition'] = validate([dict(provenance) for _ in range(5)])
            if transform:
                transform(item)
        snapshot = dict(event=dict(title='Away at Home',competition='NBA',
            scheduled_start='2026-11-23T01:00:00Z'),offers=list(offers),references=[],raw_quotes=[],
            times=dict(received_at=AT,captured_at=AT),fee_mode=dict(enabled=False))
        if canonical_game_id:
            snapshot['canonical_game_id'] = canonical_game_id
        acquisition.store_evidence(db,pull_id,snapshot)
        projection = acquisition.compact_snapshot(snapshot,pull_id)
        for family in acquisition.FAMILIES:
            selected = dict(projection,offers=[value for value in projection['offers']
                if value['record']['market_identity']['family']==family])
            db.execute('''UPDATE public.market_pull_scope SET state=%s,snapshot=%s
                WHERE pull_id=%s AND family=%s''', (state,Jsonb(selected),pull_id,family))
        db.execute('UPDATE public.market_pull SET state=%s WHERE pull_id=%s',(state,pull_id))
        return snapshot

    async def test_exact_main_winner_and_independent_markets_rank_before_paging(self):
        with self.connect() as db:
            pull = self.start(db)
            self.publish(db,pull,captured_offer(ev='1/10',line='-3'),
                captured_offer(ev='1/5',line='-3.5',venue='novig'),
                captured_offer(ev='1/2',line='-4',main='alternate'),
                captured_offer(ev='9/10',line='-5',main='unknown'),
                captured_offer(ev='3/10',family='moneyline'))
            page = market_board.markets(db,{},limit=1)
            self.assertEqual(page['total'],3)
            moneyline, = page['rows']
            self.assertEqual(moneyline['family'],'moneyline')
            self.assertEqual(moneyline['headline']['calculation']['net_ev_percent'],'30')
            second, = market_board.markets(db,{},offset=1,limit=1)['rows']
            self.assertEqual(second['family'],'spread')
            self.assertEqual(second['headline']['venue'],'novig')
            self.assertEqual(second['headline']['line'],'-3.5')
            exact = market_board.detail(db,market_id=second['id'],pull_id=pull,
                offer_id=second['headline']['id'],revision=second['headline']['revision'])
            self.assert_exact_headline(second['headline'],exact['selected_offer'])
            self.assertEqual(len(exact['offers']),4)
            widened = market_board.markets(db,dict(include_alternates='1'))['rows'][0]
            self.assertEqual(widened['headline']['main_role'],'alternate')
            self.assertEqual(widened['headline']['line'],'-4')
            self.assertEqual(market_board.markets(db,dict(calculation_status='positive'))['total'],2)
            self.assertEqual(market_board.markets(db,dict(calculation_status='unavailable'))['total'],1)

    async def test_new_full_attempt_suppresses_old_ev_but_narrow_attempt_does_not(self):
        with self.connect() as db:
            previous = self.start(db)
            self.publish(db,previous,captured_offer())
            narrow = self.start(db,scope=dict(SCOPE,bookmakerID='kalshi'))
            self.assertEqual(market_board.markets(db,{})['rows'][0]['pull_id'],previous)
            newest = self.start(db)
            rows = market_board.markets(db,{})['rows']
            self.assertEqual({value['pull_id'] for value in rows},{newest})
            spread = next(value for value in rows if value['family']=='spread')
            self.assertIsNone(spread['headline'])
            self.assertEqual(spread['state'],'in_progress')
            self.assertEqual(spread['previous_capture']['pull_id'],previous)
            acquisition.finish(db,newest,'failed',details=dict(reason='fixture_receipt_failed'))
            failed = next(value for value in market_board.markets(db,{})['rows'] if value['family']=='spread')
            self.assertEqual(failed['reason'],'fixture_receipt_failed')
            self.assertIsNone(failed['headline'])
            older = market_board.detail(db,market_id=spread['id'],pull_id=previous)
            self.assertEqual(older['offers'][0]['calculation']['status'],'positive')
            self.assertIn(narrow,{item['pull_id'] for item in older['history']})

    async def test_delayed_old_completion_cannot_overwrite_new_complete_missing_inputs(self):
        with self.connect() as db:
            older = self.start(db)
            newer = self.start(db)
            missing = captured_offer(ev=None)
            missing['reason'] = 'No matching reference pair in this pull'
            self.publish(db,newer,missing)
            self.publish(db,older,captured_offer(ev='1/2'))
            current = next(value for value in market_board.markets(db,{})['rows'] if value['family']=='spread')
            self.assertEqual(current['pull_id'],newer)
            self.assertIsNone(current['headline'])
            self.assertEqual(market_board.markets(db,dict(calculation_status='positive'))['total'],0)

    async def test_expired_sql_lease_reopens_exact_pull_revision_without_substitution(self):
        with self.connect() as db:
            pull = self.start(db)
            self.publish(db,pull,captured_offer(ev='0'))
        reads = CatalogReads(self.connect)
        try:
            listing = reads.markets(dict(calculation_status='zero'))
            current, = listing['rows']
            selected = current['headline']
            query = dict(token=listing['token'],market_id=current['id'],pull_id=pull,
                offer_id=selected['id'],revision=selected['revision'])
            before = reads.market(query)
            reads.close(listing['token'])
            with self.connect() as db:
                newer = self.start(db)
                self.publish(db,newer,captured_offer(ev='1/5'))
            after = reads.market(query)
            self.assertEqual(before['selected_offer'],after['selected_offer'])
            self.assertEqual(after['selected_offer']['calculation']['status'],'zero')
            self.assertEqual(after['provider_requests'],0)
            self.assertEqual(after['scheduled_calculations'],0)
            with self.assertRaisesRegex(PublicRequestError,'revision differs'):
                reads.market(dict(query,revision='changed'))
        finally:
            reads.close()

    async def test_http_headline_click_and_export_bind_same_offer_and_leave_acquisition_unchanged(self):
        with self.connect() as db:
            pull = self.start(db)
            self.publish(db,pull,captured_offer(ev='1/10',line='-3'),
                captured_offer(ev='-1/20',line='-3.5',venue='novig'))
            before = db.execute('SELECT count(*) n FROM public.market_pull').fetchone()['n']
        reads = CatalogReads(self.connect)
        app = web.Application(middlewares=[dashboard_guard(MagicMock(database_mode=True),logger=MagicMock())])
        with patch('app.dashboard.research_api.CatalogReads',return_value=reads):
            mount(app)
        async with TestClient(TestServer(app)) as client:
            response = await client.get('/api/research/markets?calculation_status=positive')
            self.assertEqual(response.status,200)
            listing = await response.json()
            row, = listing['rows']
            exact_query = dict(token=listing['token'],market_id=row['id'],pull_id=row['pull_id'],
                offer_id=row['headline']['id'],revision=row['headline']['revision'])
            detail = await (await client.get('/api/research/market',params=exact_query)).json()
            export = await client.get('/api/research/market-export',params=exact_query)
            self.assertEqual(export.status,200)
            downloaded = await export.json()
            self.assertEqual(downloaded['selected_offer'],detail['selected_offer'])
            self.assert_exact_headline(row['headline'],downloaded['selected_offer'])
            self.assertEqual(downloaded['selected_offer']['line'],'-3')
            self.assertEqual(len(downloaded['offers']),2)
            self.assertEqual(downloaded['provider_requests'],0)
            invalid = await client.get('/api/research/market-export',params=dict(exact_query,revision='changed'))
            self.assertEqual(invalid.status,422)
            self.assertEqual((await client.get('/api/research/markets?sort=arbitrary')).status,422)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM public.market_pull').fetchone()['n'],before)

    async def test_reader_refuses_cached_ev_without_matching_accepted_membership(self):
        def wrong_pull(item):
            item['calculation_payload']['acquisition']['pull_id'] = 'another-pull'

        def missing_receipt(item):
            for required in item['calculation_payload']['acquisition']['required_inputs']:
                required['attempt_id'] = 'unaccepted-attempt'

        def missing_reference_witness(item):
            item['calculation_payload']['acquisition']['required_inputs'] = item['calculation_payload']['acquisition']['required_inputs'][:1]

        for transform in (wrong_pull,missing_receipt,missing_reference_witness):
            with self.subTest(transform=transform.__name__), self.connect() as db:
                pull = self.start(db)
                self.publish(db,pull,captured_offer(),transform=transform)
                current = next(value for value in market_board.markets(db,{})['rows'] if value['family']=='spread')
                self.assertIsNone(current['headline'])
                self.assertEqual(market_board.markets(db,dict(calculation_status='positive'))['total'],0)
                detail = market_board.detail(db,market_id=current['id'],pull_id=pull)
                self.assertIsNone(detail['offers'][0]['calculation']['net_ev_ratio'])

    async def test_real_checkpoint_builder_exact_offer_and_all_reference_inputs_reproduce(self):
        from tests.test_market_snapshot_arbs_sql import SnapshotArbsSQL
        from app.research.ev_movement import reproduce_checkpoint

        with self.connect() as db:
            pull,_ = SnapshotArbsSQL.capture(self,db)
            positive = market_board.markets(db,dict(calculation_status='positive'))
            self.assertGreater(positive['total'],0)
            selected = positive['rows'][0]
            headline = selected['headline']
            evidence = market_board.detail(db,market_id=selected['id'],pull_id=pull,
                offer_id=headline['id'],revision=headline['revision'])
            self.assert_exact_headline(headline,evidence['selected_offer'])
            self.assertGreater(len(evidence['reference_inputs']),0)
            witness = evidence['selected_offer']['calculation_payload']['acquisition']
            self.assertTrue(witness['eligible'])
            self.assertGreaterEqual(len(witness['required_inputs']),5)
            reproduced = reproduce_checkpoint(evidence['snapshot'])
            self.assertGreater(reproduced['numeric_screen_results'],0)

    async def test_optional_age_filter_uses_reference_clocks_before_headline_selection(self):
        with self.connect() as db:
            now = db.execute('SELECT transaction_timestamp() at').fetchone()['at']
            recent,stale = now.isoformat(),(now-timedelta(minutes=20)).isoformat()
            highest = captured_offer(ev='1/2')
            lower = captured_offer(ev='1/10',venue='novig')
            for value in (highest,lower):
                value['record']['quote']['times']['source_at'] = recent

            def source_clocks(item):
                clock = stale if item['record']['quote']['venue']=='kalshi' else recent
                for price in item['calculation_payload']['reference']['required_input_prices']:
                    price['source_at'] = clock

            pull = self.start(db)
            self.publish(db,pull,highest,lower,transform=source_clocks)
            unrestricted = next(value for value in market_board.markets(db,{})['rows'] if value['family']=='spread')
            self.assertEqual(unrestricted['headline']['venue'],'kalshi')
            limited = next(value for value in market_board.markets(db,dict(max_age_minutes='10'))['rows'] if value['family']=='spread')
            self.assertEqual(limited['headline']['venue'],'novig')
            self.assertEqual(limited['pull_id'],pull)

    async def test_moneyline_only_covering_scope_replaces_only_moneyline(self):
        with self.connect() as db:
            first = self.start(db)
            self.publish(db,first,captured_offer(family='moneyline'),captured_offer(),
                captured_offer(family='total',side='over',line='220.5'))
            previous = {value['family']:value for value in market_board.markets(db,{})['rows']}
            moneyline_odds = sorted(odd for odd in ODD_IDS if '-ml-' in odd)
            narrow = self.start(db,scope=dict(SCOPE,oddID=','.join(moneyline_odds)))
            scopes = list(db.execute('SELECT family FROM public.market_pull_scope WHERE pull_id=%s',(narrow,)))
            self.assertEqual([value['family'] for value in scopes],['moneyline'])
            pending = {value['family']:value for value in market_board.markets(db,{})['rows']}
            self.assertEqual(pending['moneyline']['pull_id'],narrow)
            self.assertIsNone(pending['moneyline']['headline'])
            for family in ('spread','total'):
                self.assertEqual(pending[family],previous[family])
            acquisition.finish(db,narrow,'failed',details=dict(reason='moneyline_receipt_failed'))
            failed = {value['family']:value for value in market_board.markets(db,{})['rows']}
            self.assertEqual(failed['moneyline']['state'],'failed')
            self.assertIsNone(failed['moneyline']['headline'])
            for family in ('spread','total'):
                self.assertEqual(failed[family],previous[family])
            completed = self.start(db,scope=dict(SCOPE,oddID=','.join(moneyline_odds)))
            self.publish(db,completed,captured_offer(family='moneyline',ev='-1/20'))
            replaced = {value['family']:value for value in market_board.markets(db,{})['rows']}
            self.assertEqual(replaced['moneyline']['pull_id'],completed)
            self.assertEqual(replaced['moneyline']['headline']['calculation']['status'],'negative')
            for family in ('spread','total'):
                self.assertEqual(replaced[family],previous[family])

    async def test_pending_and_failed_full_attempt_keep_established_game_identity(self):
        with self.connect() as db:
            older = self.start(db)
            self.publish(db,older,captured_offer(),canonical_game_id='canonical:established-game')
            previous = {value['family']:value for value in market_board.markets(db,{})['rows']}
            newer = self.start(db)
            for expected in ('in_progress','failed'):
                if expected=='failed':
                    acquisition.finish(db,newer,'failed',details=dict(reason='fixture_failed'))
                current = {value['family']:value for value in market_board.markets(db,{})['rows']}
                for family,value in current.items():
                    self.assertEqual(value['id'],previous[family]['id'])
                    self.assertEqual(value['game_id'],'canonical:established-game')
                    self.assertEqual(value['identity_status'],'canonical')
                    self.assertEqual(value['state'],expected)
                    self.assertIsNone(value['headline'])
                    self.assertEqual(value['previous_capture']['pull_id'],older)
                    evidence = market_board.detail(db,market_id=value['id'],pull_id=newer)
                    self.assertEqual(evidence['row']['id'],value['id'])
                    self.assertEqual(evidence['row']['sport'],'NBA')
                    self.assertEqual(stamp(evidence['row']['start_at']),stamp(value['start_at']))
                    self.assertEqual(evidence['offers'],[])
                    previous_evidence = market_board.detail(db,market_id=value['id'],pull_id=older)
                    self.assertEqual(previous_evidence['row']['id'],value['id'])
