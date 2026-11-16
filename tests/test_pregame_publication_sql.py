"""End-to-end pregame publication using admitted receipts and disposable PostgreSQL."""
from datetime import timedelta
import os
from pathlib import Path
import re
from time import monotonic
from fractions import Fraction
import json
from threading import Event
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from psycopg.types.json import Jsonb

from app.collection.current_database import DatabaseIngressSink
from app.collection.sportsgameodds_adapter import parse_page
from app.collection.sportsgameodds_current_rows import current_rows
from app.dashboard.snapshot_api import mount
from app.storage import comparison_snapshot, ordinary_publication, sgo_native_catalog
from app.storage.sportsgameodds_reference import prepare_frames, prepare_page
from app.storage.current_rows import event_id
from app.storage.store import exact_time, hashed, stamp
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_sgo_native_binding import EVENT, HOME, SGO, fixture, receipt
from tests.test_sportsgameodds_adapter import response

API = '/api/comparison-current'
BROWSE = dict(layout='desk', phase='pregame', browse_odds='1', lines='all', summary='1')
RANKED = dict(layout='desk', phase='pregame', ranked='1', basis='sportsbooks', summary='1')


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class PregamePublicationSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.at = stamp('2026-11-16T19:06:03Z')
        self.kickoff = stamp('2026-11-17T03:00:00Z')
        self.service.config.update(aggregate_provider='sportsgameodds', direct_novig_enabled=False,
                                   sports=['NCAAB', 'NHL'], families=['moneyline', 'spread'])
        self.service.states['sportsgameodds'] = {'state': 'available'}
        self.state.write(self.service)
        self.sink = DatabaseIngressSink(SimpleNamespace(provider=self.service), self.service.config)
        self.enterContext(patch('app.collection.current_database.connect', side_effect=self.connect))
        self.enterContext(patch('app.collection.current_database.utc', side_effect=lambda: self.at.isoformat()))
        self.enterContext(patch('app.storage.ordinary_publication.utc', side_effect=lambda: self.at.isoformat()))
        self.enterContext(patch('app.storage.comparison_snapshot.utc', side_effect=lambda: self.at.isoformat()))
        self.enterContext(patch('app.dashboard.snapshot_api.connect', side_effect=self.connect))
        self.enterContext(patch('app.comparison.public_sportsbook_estimate.read_captures', return_value={}))
        self.enterContext(patch('app.comparison.public_sportsbook_estimate.retained_prices', return_value={}))
        with self.connect() as db:
            db.execute('TRUNCATE current_event, comparison_publication, sgo_event_evidence, sgo_quote_revision CASCADE')
            db.execute("INSERT INTO comparison_publication(kind,id,generation,facts) VALUES ('live','',0,'{}')")
        self.app = web.Application()
        mount(self.app)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    def raw(self, *, league='NCAAB', game='texas-southern-ucsd', teams=('Texas Southern Tigers', 'UC San Diego Tritons')):
        raw = response()
        event, = raw['data']
        event.update(leagueID=league, eventID=game)
        event['status']['startsAt'] = self.kickoff.isoformat()
        for role, name in zip(('home', 'away'), teams, strict=True):
            event['teams'][role]['names']['long'] = name
        return raw, event

    def sides(self, event, *, family='ml', left='+1400', right='-4000'):
        home, = event['odds'].values()
        book = dict(available=True, odds=left, lastUpdatedAt=self.at.isoformat())
        opposite = dict(book, odds=right)
        if family == 'ml':
            home.update(oddID='points-home-game-ml-home', opposingOddID='points-away-game-ml-away', betTypeID='ml')
        else:
            book.update(spread='1.5')
            opposite.update(spread='-1.5')
        home['byBookmaker'] = {'fanduel': book, 'novig': dict(book, odds='+1900')}
        away = dict(home, oddID=home['opposingOddID'], opposingOddID=home['oddID'],
                    statEntityID='away', sideID='away', byBookmaker={'fanduel': opposite})
        event['odds'] = {odd['oddID']: odd for odd in (home, away)}
        return home['byBookmaker'], away['byBookmaker']

    def admit_page(self, raw):
        receipt = self.at.isoformat()
        parsed = parse_page(json.dumps(raw).encode(), receipt)
        records, _ = current_rows(parsed, parsed.receipt_sha256)
        refs = prepare_page(parsed)
        self.sink.prepare(dict(type='current_aggregate_records', source='sportsgameodds',
            sport=parsed.events[0]['league'], records=records, sgo_reference_rows=refs,
            sgo_event_frames=prepare_frames(parsed, refs), receipt_sha256=parsed.receipt_sha256,
            event_scopes={event['event_id']: event['league'] for event in parsed.events},
            complete_venues=[], received_at=receipt), self.service.states, Event())

    def publish(self, *, failed=False):
        self.state.write(self.service)
        with self.connect() as db:
            result = ordinary_publication.turn(db)
        self.assertEqual(bool(result['errors']), failed, result['errors'])
        return result

    async def read(self, query, path=API):
        response = await self.client.get(path, params=query)
        self.assertEqual(response.status, 200, await response.text())
        self.assertNotIn('dependencies;', response.headers.get('Server-Timing', ''))
        return await response.json()

    def novig(self, page):
        self.assertEqual(page['provider_requests'], 0)
        rows = [offer for group in page['rows'] for offer in group['offers'] if offer['venue'] == 'novig']
        offer, = rows
        return offer

    async def test_aged_price_and_reference_publish_together_until_authoritative_start(self):
        raw, event = self.raw()
        home, away = self.sides(event)
        self.admit_page(raw)
        self.publish()

        browse = await self.read(BROWSE)
        original = self.novig(browse)
        expected = (Fraction(1, 15) / (Fraction(1, 15) + Fraction(40, 41))) * 20 - 1
        self.assertEqual(round(float(100 * expected), 2), 27.93)
        self.assertEqual(original['odds']['american'], '+1900')
        self.assertEqual(Fraction(original['before_fee']), 100 * expected)
        self.assertFalse(original['trade_fee_available'])
        self.assertEqual(original['sportsbook']['prices'][0]['price_american'], '+1400')
        scope = dict(BROWSE, game_key=browse['rows'][0]['game_key'])
        selection = dict(layout='desk', phase='pregame', id=original['id'], quote_key=original['desk_quote_key'],
                         basis='sportsbooks')

        async def same_price_and_math(price, before):
            for query in (dict(BROWSE, refresh='1'), scope, RANKED):
                item = self.novig(await self.read(query))
                self.assertEqual((item['odds']['american'], Fraction(item['before_fee'])), (price, before))
            item = (await self.read(selection, API + '/selection'))['row']
            self.assertEqual((item['odds']['american'], Fraction(item['before_fee'])), (price, before))

        # Cross the former reference and offer cutoffs, then publish a partial
        # page. Different source clocks are preserved even when the offer is omitted.
        self.at += timedelta(hours=3)
        offer = home.pop('novig')
        self.admit_page(raw)
        self.publish()
        await same_price_and_math('+1900', 100 * expected)

        # Interrupt optional work after committing the new input. A restarted
        # worker (new turn/connection) can seal it without a new provider receipt.
        home['novig'] = dict(offer, odds='+2100', lastUpdatedAt=self.at.isoformat())
        self.at += timedelta(seconds=1)
        self.admit_page(raw)
        with patch.object(comparison_snapshot, 'calculate', side_effect=RuntimeError('interrupted fixture calculation')):
            self.publish(failed=True)
        await same_price_and_math('+1900', 100 * expected)
        self.publish()
        probability = Fraction(41, 641)
        await same_price_and_math('+2100', 100 * (22 * probability - 1))
        latest = await self.read(RANKED)
        self.assertGreater(latest['generation'], browse['generation'])
        update = await self.read(dict(layout='desk', phase='pregame', after=browse['update_cursor']), API + '/updates')
        self.assertTrue(update['changed'])

        self.at += timedelta(seconds=1)
        home['novig'] = dict(offer, odds='+900')
        self.admit_page(raw)
        self.publish()
        await same_price_and_math('+2100', 100 * (22 * probability - 1))

        # Advance the authoritative start without publishing prices again.
        self.at += timedelta(seconds=1)
        corrected = self.at + timedelta(minutes=1)
        event['status']['startsAt'] = corrected.isoformat()
        event['odds'] = {}
        self.admit_page(raw)
        revised = await self.read(dict(BROWSE, refresh='1'))
        self.assertEqual(stamp(revised['refresh_at']), corrected)
        self.at = corrected
        for query in (dict(BROWSE, refresh='1'), scope, RANKED, dict(RANKED, view='arbs')):
            page = await self.read(query)
            self.assertEqual(page['rows'], [])
            self.assertEqual(page['generation'], revised['generation'])
        self.assertIsNone((await self.read(selection, API + '/selection'))['row'])

    async def test_quote_details_follow_linked_sources_corrected_start(self):
        raw, event = self.raw()
        self.sides(event)
        self.admit_page(raw)
        self.publish()
        corrected = self.at + timedelta(hours=1)
        linked = 'linked-source-correction'
        provider = 'oddslink_public_board'
        with self.connect() as db:
            stored = db.execute("SELECT facts FROM current_event WHERE provider='sportsgameodds'").fetchone()['facts']
            facts = dict(stored, id=linked, scheduled_start=corrected.isoformat())
            db.execute('''INSERT INTO current_event
                (id, provider, native_event_id, competition, scheduled_start, expires_order, facts, revision)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                (event_id(provider, linked), provider, linked, facts['competition'], facts['scheduled_start'],
                 exact_time(facts['scheduled_start']), Jsonb(facts), hashed(facts)))

        # Supply a previously verified occurrence binding in the published packet.
        # Its second source moves kickoff while prices stay on the old generation.
        unpack = comparison_snapshot.unpack

        def linked_publication(*args, **kwargs):
            result = unpack(*args, **kwargs)
            row, = result['rows']
            authority = dict(row['current_authority'], occurrence_id='reviewed-occurrence')
            sibling = dict(row, id='linked-offer', venue='prophetx',
                           source=dict(row['source'], provider=provider, native_event_id=linked),
                           current_authority=dict(authority, price=dict(authority['price'], dependency='f' * 64)))
            return dict(result, rows=[dict(row, current_authority=authority), sibling])

        with patch.object(comparison_snapshot, 'unpack', side_effect=linked_publication):
            browse = await self.read(dict(BROWSE, refresh='1'))
            self.assertEqual(stamp(browse['refresh_at']), corrected)
            original = self.novig(browse)
            selection = dict(layout='desk', phase='pregame', id=original['id'], quote_key=original['desk_quote_key'])
            detail = await self.read(selection, API + '/selection')
            self.assertEqual(stamp(detail['row']['start_at']), corrected)
            self.at = corrected
            detail = await self.read(selection, API + '/selection')
            self.assertEqual(detail['generation'], browse['generation'])
            self.assertTrue(detail['withdrawn_from_phase'])
            self.assertIsNone(detail['row'])

    async def test_novig_catalog_publishes_zero_fee_and_same_after_fee_estimate(self):
        raw, event = self.raw(league='NHL', game=SGO, teams=('Seattle Kraken', 'Carolina Hurricanes'))
        home, _ = self.sides(event, family='sp')
        event['links'] = dict(bookmakers=dict(novig=f'https://novig.com/event-markets/{EVENT}/sportsgameodds'))
        home['novig']['deeplink'] = f'https://novig.com/events/{HOME}/sportsgameodds'
        self.admit_page(raw)
        self.publish()
        before = self.novig(await self.read(dict(BROWSE, refresh='1')))
        self.assertEqual(before['trade_fee_reason'], 'sgo_native_catalog_unavailable')
        self.assertIsNone(before['after_fee'])

        self.at += timedelta(minutes=4)
        official, market = fixture()[1:]
        official['startsTs'] = market['startsTs'] = int(self.kickoff.timestamp() * 1000)
        from app.collection.novig_v3_public import NovigPublicDiscovery

        public = NovigPublicDiscovery(SimpleNamespace(config=self.service.config,
            dispatch=True, globally_stopped=False, paused_sources=set()))

        async def catalog_read(path, params):
            body = official if path.endswith(EVENT) else dict(items=[market])
            return body, receipt(path, self.at.isoformat())

        with patch.object(public, 'read', side_effect=catalog_read), \
                patch('app.collection.novig_v3_public.connect', side_effect=self.connect), \
                patch('app.collection.novig_v3_public.now', side_effect=lambda: self.at.isoformat()):
            await public.poll_sgo_catalog()
        self.assertEqual(public.metrics['sgo_catalog_events'], 1)
        with self.connect() as db:
            self.assertIn(SGO, sgo_native_catalog.read(db, [SGO]))
        self.publish()
        after = self.novig(await self.read(dict(BROWSE, refresh='1')))
        self.assertEqual(after['trade_fee']['trade_fee_usd'], '0')
        self.assertEqual(after['after_fee'], before['before_fee'])
        ranked = self.novig(await self.read(RANKED))
        selected = (await self.read(dict(layout='desk', phase='pregame', id=after['id'],
                                         quote_key=after['desk_quote_key']), API + '/selection'))['row']
        for other in (ranked, selected):
            self.assertEqual((other['economic_revision'], other['after_fee'], other['trade_fee']['trade_fee_usd']),
                             (after['economic_revision'], after['after_fee'], '0'))
        self.assertTrue(after['posted_price'])
        self.assertTrue(selected['trade_preview']['fee_available'])
        self.assertEqual(selected['trade_preview']['fee_at_entry_usd'], '0')

        self.at += timedelta(hours=3)
        home['fanduel'].update(available=False, lastUpdatedAt=self.at.isoformat())
        self.admit_page(raw)
        self.publish()
        no_reference = self.novig(await self.read(dict(BROWSE, refresh='1')))
        self.assertEqual(no_reference['trade_fee']['trade_fee_usd'], '0')
        self.assertIsNone(no_reference['before_fee'])
        self.assertIsNone(no_reference['after_fee'])
        unranked = self.novig(await self.read(RANKED))
        self.assertEqual(unranked['reason'], 'reference_price_missing')
        self.assertEqual(unranked['trade_fee'], no_reference['trade_fee'])
        census = await self.read(dict(phase='pregame'), API + '/fee-coverage')
        self.assertEqual(census['generation'], (await self.read(RANKED))['generation'])
        self.assertEqual((census['total']['current'], census['total']['covered']), (1, 1))

    @skipUnless(os.getenv('PREDICT_PREGAME_BROWSER'), 'Opt in with disposable PostgreSQL and Playwright')
    async def test_open_browser_observes_price_publication_and_kickoff(self):
        from playwright.async_api import async_playwright, expect

        raw, event = self.raw()
        self.kickoff = self.at + timedelta(hours=4)
        event['status']['startsAt'] = self.kickoff.isoformat()
        home, _ = self.sides(event)
        self.admit_page(raw)
        self.publish()
        static = Path(__file__).resolve().parents[1] / 'app/dashboard/opportunity_static/current'

        async def desk(_):
            return web.FileResponse(static / 'desk.html')

        app = web.Application()
        for url in ('/', '/ev', '/arbs', '/browse-odds', '/game'):
            app.router.add_get(url, desk)
        app.router.add_static('/view/current', static)
        mount(app)
        async with TestServer(app) as server, async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=os.getenv('PREDICT_CI_CHROMIUM'))
            tab = await browser.new_page()
            await tab.clock.install(time=self.at)
            base = str(server.make_url('/')).rstrip('/')

            def is_list(response):
                return API + '?' in response.url

            def has_filter(response, name, value=None):
                values = parse_qs(urlsplit(response.url).query).get(name, ())
                return is_list(response) and (value in values if value is not None else bool(values))

            async def navigate(path):
                started = monotonic()
                mode = 'browse_odds' if path == '/browse-odds' else 'ranked'
                async with tab.expect_response(lambda response: has_filter(response, mode, '1')) as request:
                    await tab.goto(base + path)
                response = await request.value
                self.assertEqual(response.status, 200)
                page = await response.json()
                self.assertTrue(page['rows'], (response.url, page.get('offer_count'), page.get('coverage'),
                                               page.get('calculation_missing'), page.get('generation')))
                print(f"{path}: HTTP {response.status}, {monotonic()-started:.3f}s browser, "
                      f"generation {page['generation']}, {page['offer_count']} offers, "
                      f"{response.headers.get('server-timing')}")
                return page

            baseline = await navigate('/ev')
            await expect(tab.locator('#results')).to_contain_text('+27.93%')
            await expect(tab.locator('#notice')).to_contain_text('Odds may be delayed.')
            self.at += timedelta(hours=3)
            await tab.clock.fast_forward(3 * 3600 * 1000)
            await expect(tab.locator('#results')).to_contain_text('+27.93%')
            browse = await navigate('/browse-odds')
            await expect(tab.locator('#results')).to_contain_text('+1900')
            async with tab.expect_response(lambda response: has_filter(response, 'game_key')) as request:
                await tab.get_by_role('link', name='Open Game').first.click()
            game_response = await request.value
            game = await game_response.json()
            self.assertEqual(game_response.status, 200)
            print(f"Open Game: generation {game['generation']}, {game['offer_count']} offers, "
                  f"{game_response.headers.get('server-timing')}")
            self.assertEqual(self.novig(browse)['economic_revision'], self.novig(game)['economic_revision'])

            home['novig'].update(odds='+2100', lastUpdatedAt=self.at.isoformat())
            self.admit_page(raw)
            self.publish()
            async with tab.expect_response(is_list) as request:
                await tab.get_by_role('button', name='Refresh list').click()
            manual_response = await request.value
            manual = await manual_response.json()
            self.assertEqual(manual_response.status, 200)
            print(f"Refresh list: generation {manual['generation']}, {manual['offer_count']} offers, "
                  f"{manual_response.headers.get('server-timing')}")
            self.assertEqual(self.novig(manual)['odds']['american'], '+2100')
            self.assertGreater(manual['generation'], baseline['generation'])
            await expect(tab.locator('#results')).to_contain_text('+2100')
            self.at += timedelta(seconds=10)
            home['novig'].update(odds='+2200', lastUpdatedAt=self.at.isoformat())
            self.admit_page(raw)
            self.publish()
            async with tab.expect_response(is_list) as request:
                await tab.clock.fast_forward(10_000)
            automatic_response = await request.value
            automatic = await automatic_response.json()
            self.assertEqual(automatic_response.status, 200)
            print(f"Auto-update: generation {automatic['generation']}, {automatic['offer_count']} offers, "
                  f"{automatic_response.headers.get('server-timing')}")
            self.assertEqual(self.novig(automatic)['odds']['american'], '+2200')
            await expect(tab.locator('#results')).to_contain_text('+2200')

            def is_selection(response):
                return API + '/selection?' in response.url

            async with tab.expect_response(is_selection) as request:
                await tab.get_by_role('button', name=re.compile(r'Novig.*\+2200.*Quote details')).click()
            self.assertEqual((await request.value).status, 200)
            drawer = tab.get_by_role('dialog')
            await expect(drawer).to_contain_text('+2200')
            await expect(drawer.get_by_text('Trade preview', exact=True)).to_be_visible()

            self.at += timedelta(seconds=10)
            corrected = self.at + timedelta(minutes=5)
            event['status']['startsAt'] = corrected.isoformat()
            event['odds'] = {}
            self.admit_page(raw)
            async with tab.expect_response(is_selection) as request:
                await tab.clock.fast_forward(10_000)
            refreshed_detail = await (await request.value).json()
            self.assertEqual(stamp(refreshed_detail['row']['start_at']), corrected)
            self.assertEqual(refreshed_detail['generation'], automatic['generation'])
            await expect(drawer).not_to_contain_text('Pregame closed')

            remaining = corrected - self.at
            self.at = corrected
            await tab.clock.fast_forward(int(remaining.total_seconds()*1000) + 100)
            await expect(tab.locator('#results')).not_to_contain_text('+2200')
            await expect(drawer).to_contain_text('Pregame closed')
            await browser.close()
