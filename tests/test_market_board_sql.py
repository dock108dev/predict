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
CBB_GAME = 'South Carolina Gamecocks at Arizona State Sun Devils'


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


def cbb_offers():
    return [captured_offer(family=family, side=side, line=line, venue=venue, ev=ev)
            for family, side, line, venues in (
                ('moneyline', 'home', None, [('novig', '1/5'), ('kalshi', '1/10')]),
                ('spread', 'home', '-3.5', [('kalshi', '1/12'), ('novig', '1/14')]),
                ('total', 'over', '152.5', [('prophetx', '1/16'), ('kalshi', '1/18')]),
            ) for venue, ev in venues]


def test_dashboard_exact_groups_survive_legacy_projections_without_merging_other_contracts():
    from app.comparison.acquisition import validate

    offers = cbb_offers()
    different_line = captured_offer(line='-4.5', venue='novig', ev='1/30')
    different_period = captured_offer(line='-3.5', venue='novig', ev='1/31')
    different_period['record']['market_identity']['period'] = 'first_half'
    different_rules = captured_offer(line='-3.5', venue='novig', ev='1/32')
    different_rules['record']['market_identity']['rules'] = 'regulation_only'
    snapshot = dict(event=dict(title=CBB_GAME), offers=[*offers,different_line,different_period,different_rules])
    pull = 'south-carolina-arizona-state-pull'
    provenance = dict(pull_id=pull,attempt_id='accepted:'+pull,
        receipt_sha256='fixture-receipt:'+pull,received_at=AT)
    for item in snapshot['offers']:
        item['record']['comparison_source_metadata']['acquisition'] = dict(provenance)
        item['calculation_payload']['reference']['required_input_prices'] = [
            dict(acquisition=dict(provenance),received_at=AT) for _ in range(4)]
        item['calculation_payload']['acquisition'] = validate([dict(provenance) for _ in range(5)])
    compact = acquisition.compact_snapshot(snapshot, pull)
    candidates = [dict(quote=item['display_offer'], outcome_key=None, game_id='canonical-cbb-game',
                      event_id='source-game', game=CBB_GAME, league='NCAAB', eligible_until=AT, display={},
                      start_at=AT, family=item['display_offer']['family'], period=item['display_offer']['period'],
                      pull_id=pull, effective_ev=item['display_offer']['calculation']['net_ev_ratio'],
                      liquidity=dict(status='unknown', reason='book_unobserved'), line_role='main')
                  for item in compact['offers']]
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = dict(entries=candidates[::-1], price_available=True,
        inputs_unavailable=False, pull_incomplete=False, expired_positive=False)
    at = stamp(AT)
    options = dict(at=at, until=at + timedelta(hours=24), freshness_seconds=1800, sport='NCAAB')
    with patch('app.comparison.fee_mode.read', return_value=dict(enabled=False)), \
            patch('app.storage.acquisition_snapshot.read_snapshot', return_value=snapshot) as read:
        legacy = market_board.dashboard(db, **options)
        read.assert_called_once_with(db, pull)
        read.reset_mock()
        for candidate, item in zip(candidates, compact['offers']):
            candidate['outcome_key'] = item['dashboard_outcome_key']
        assert legacy == market_board.dashboard(db, **options)
        paged = market_board.dashboard(db, **options, limit=2, offset=1)
        read.assert_not_called()
    assert legacy['total'] == paged['total'] == 6
    assert [row['venue'] for row in legacy['rows'][:3]] == ['novig', 'kalshi', 'prophetx']
    assert [len(row['other_quotes']) for row in legacy['rows']] == [1, 1, 1, 0, 0, 0]
    assert paged['rows'] == legacy['rows'][1:3]


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class MarketBoardSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        with self.connect() as db:
            db.execute('TRUNCATE public.market_pull CASCADE')

    def start(self, db, *, scope=None, game='Away at Home', league='NBA'):
        return acquisition.start(db,scope or SCOPE,at=stamp(AT),event=dict(title=game,
            league=league,starts_at='2026-11-23T01:00:00Z'))

    def assert_exact_headline(self, expected, actual):
        # List rows carry a compact projection; exact detail restores the full
        # immutable calculation and every supporting reference candidate.
        for key in ('id','revision','pull_id','exact_bet_id','outcome','side','line',
                    'venue','price','price_units','main_role','calculation','times','fee_mode'):
            self.assertEqual(expected[key],actual[key],key)
        for key in ('book','probability','selection_policy'):
            self.assertEqual((expected.get('reference') or {}).get(key),
                             (actual.get('reference') or {}).get(key),key)

    def publish(self, db, pull_id, *offers, state='complete', transform=None, canonical_game_id=None,
                game='Away at Home', league='NBA', legacy_projection=False):
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
        snapshot = dict(event=dict(title=game,competition=league,
            scheduled_start='2026-11-23T01:00:00Z'),offers=list(offers),references=[],raw_quotes=[],
            times=dict(received_at=AT,captured_at=AT),fee_mode=dict(enabled=False))
        if canonical_game_id:
            snapshot['canonical_game_id'] = canonical_game_id
        acquisition.store_evidence(db,pull_id,snapshot)
        projection = acquisition.compact_snapshot(snapshot,pull_id)
        if legacy_projection:
            for value in projection['offers']:
                value.pop('dashboard_outcome_key')
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

    async def test_dashboard_ranks_offers_and_withholds_stale_or_partial_evidence(self):
        from app.comparison import fee_mode
        from app.storage.current_rows import event_id
        from app.storage.sportsgameodds_reference import quote_identity

        at = stamp(AT)
        until = at + timedelta(hours=24)
        options = dict(at=at, until=until, freshness_seconds=1800)
        with self.connect() as db:
            fee_mode.set_enabled(db, False)
            pull = self.start(db)
            self.publish(db, pull, captured_offer(ev='1/10'),
                         captured_offer(ev='1/5', venue='novig'), captured_offer(ev='-1/5', venue='prophetx'),
                         captured_offer(ev='1/2', line='-4', main='alternate'))
            with db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                first = market_board.dashboard(db, **options, limit=1)
                second = market_board.dashboard(db, **options, offset=1, limit=1)
            self.assertEqual(first['total'], 1)
            high, = first['rows']
            self.assertEqual(second['rows'], [])
            low, negative = high['other_quotes']
            self.assertEqual((high['venue'], low['venue'], negative['venue']), ('novig', 'kalshi', 'prophetx'))
            filtered = market_board.dashboard(db, **options, sport='NBA', family='spread', venue='kalshi', limit=1)
            self.assertEqual((filtered['total'], filtered['rows']),
                (1, [dict(low, bet_id=high['bet_id'], other_quotes=[])]))
            self.assertEqual(market_board.dashboard(db, **options, sport='NHL')['total'], 0)
            self.assertEqual(market_board.dashboard(db, **options, family='total')['total'], 0)
            self.assertEqual(market_board.dashboard(db, **options, venue='prophetx')['total'], 0)
            self.assertEqual(stamp(high['kickoff']), stamp('2026-11-23T01:00:00Z'))
            original = market_board.detail(db, market_id=high['market_id'], pull_id=high['pull_id'],
                                          offer_id=high['id'], revision=high['revision'])
            self.assertEqual(original['selected_offer']['calculation']['net_ev_ratio'], '1/5')
            self.assertEqual(stamp(high['eligible_until']), at + timedelta(minutes=30))
            stale = market_board.dashboard(db, **dict(options, at=at + timedelta(minutes=30)))
            self.assertEqual(stale['total'], 0)
            self.assertTrue(stale['availability']['expired_positive'])
            fee_mode.set_enabled(db, True)
            repriced = market_board.dashboard(db, **options)
            self.assertEqual(repriced['total'], 0)
            self.assertTrue(repriced['availability']['expired_positive'])
            fee_mode.set_enabled(db, False)

            quote = quote_identity('source-game', 'fanduel', 'withdrawn-home-spread', '-3')
            db.execute('''INSERT INTO public.sgo_quote_revision
                       (id,event_id,bookmaker_id,revision,source_order,received_order,expires_at,facts,is_current)
                       VALUES(%s,'source-game','fanduel','known',0,0,%s,%s,true)''',
                       (quote, until, Jsonb(dict(market='spread', period='full_game', side='home', line='-3', available=False))))
            withdrawn = market_board.dashboard(db, **options)
            self.assertEqual(withdrawn['total'], 0)
            self.assertTrue(withdrawn['availability']['expired_positive'])
            # Explicitly retained withdrawal affects current eligibility only.
            self.assertEqual(original['selected_offer'], market_board.detail(
                db, market_id=high['market_id'], pull_id=pull, offer_id=high['id'], revision=high['revision'])['selected_offer'])
            db.execute('DELETE FROM public.sgo_quote_revision WHERE id=%s', (quote,))

            known = event_id('sportsgameodds', 'source-game')
            db.execute('''INSERT INTO public.current_event
                       (id,provider,native_event_id,competition,scheduled_start,expires_order,revision,facts)
                       VALUES(%s,'sportsgameodds','source-game','NBA',%s,0,'known','{"status":{"started":true}}')''',
                       (known, high['kickoff']))
            started = market_board.dashboard(db, **options)
            self.assertEqual(started['total'], 0)
            self.assertTrue(started['availability']['expired_positive'])
            db.execute('DELETE FROM public.current_event WHERE id=%s', (known,))

            newer = self.start(db)
            acquisition.finish(db, newer, 'partial', details={'reason': 'fixture_incomplete'})
            pending = market_board.dashboard(db, **options)
            self.assertEqual(pending['total'], 0)
            self.assertTrue(pending['availability']['inputs_unavailable'])

    async def test_dashboard_south_carolina_arizona_state_six_quotes_for_three_bets(self):
        self.assert_cbb_grouped_dashboard(legacy_projection=False)

    async def test_dashboard_south_carolina_arizona_state_groups_legacy_projections(self):
        self.assert_cbb_grouped_dashboard(legacy_projection=True)

    def assert_cbb_grouped_dashboard(self, *, legacy_projection):
        from app.comparison import fee_mode

        at = stamp(AT)
        options = dict(at=at, until=at + timedelta(hours=24), freshness_seconds=1800, sport='NCAAB')
        with self.connect() as db:
            fee_mode.set_enabled(db, False)
            pull = self.start(db, game=CBB_GAME, league='NCAAB')
            self.publish(db, pull, *cbb_offers(), game=CBB_GAME, league='NCAAB',
                         legacy_projection=legacy_projection)
            board = market_board.dashboard(db, **options)
            self.assertEqual(board['total'], 3)
            self.assertEqual([row['family'] for row in board['rows']], ['moneyline', 'spread', 'total'])
            self.assertEqual([row['venue'] for row in board['rows']], ['novig', 'kalshi', 'prophetx'])
            self.assertEqual([len(row['other_quotes']) for row in board['rows']], [1, 1, 1])
            self.assertEqual({row['game'] for row in board['rows']}, {CBB_GAME})
            self.assertEqual(market_board.dashboard(db, **options, limit=1, offset=1)['rows'], board['rows'][1:2])
            filtered = market_board.dashboard(db, **options, venue='kalshi', limit=1)
            self.assertEqual((filtered['total'], filtered['rows'][0]['venue']), (3, 'kalshi'))
            self.assertEqual(filtered['rows'][0]['other_quotes'], [])
            saved = board['rows'][0]['other_quotes'][0]
            evidence = market_board.detail(db, market_id=saved['market_id'], pull_id=saved['pull_id'],
                                           offer_id=saved['id'], revision=saved['revision'])
            self.assertEqual(evidence['selected_offer']['venue'], 'kalshi')

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
            self.assertTrue(all((item.get('facts') or item)['venue'] not in
                ('kalshi','polymarket_us','novig','prophetx','polymarket','prophetexchange')
                for item in evidence['reference_inputs']))
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

    async def test_history_returns_original_market_identity_before_canonical_link_existed(self):
        with self.connect() as db:
            earlier = self.start(db)
            self.publish(db,earlier,captured_offer(family='moneyline'))
            source_row = next(value for value in market_board.markets(db,{})['rows'] if value['family']=='moneyline')
            later = self.start(db)
            self.publish(db,later,captured_offer(family='moneyline'),canonical_game_id='canonical:established-game')
            canonical_row = next(value for value in market_board.markets(db,{})['rows'] if value['family']=='moneyline')
            self.assertNotEqual(source_row['id'],canonical_row['id'])
            evidence = market_board.detail(db,market_id=canonical_row['id'],pull_id=later)
            previous = next(value for value in evidence['history'] if value['pull_id']==earlier)
            self.assertEqual(previous['market_id'],source_row['id'])
            self.assertEqual(evidence['row']['previous_capture']['market_id'],source_row['id'])
            original = market_board.detail(db,market_id=previous['market_id'],pull_id=previous['pull_id'])
            self.assertEqual(original['row']['id'],source_row['id'])
            self.assertEqual(original['offers'][0]['id'],source_row['headline']['id'])
            self.assertEqual(original['offers'][0]['revision'],source_row['headline']['revision'])
            with self.assertRaisesRegex(PublicRequestError,'Unknown market'):
                market_board.detail(db,market_id=canonical_row['id'],pull_id=earlier)
