"""End-to-end pregame publication using admitted receipts and disposable PostgreSQL."""
from asyncio import Event as AsyncEvent, create_task, to_thread, wait_for
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
from urllib.parse import parse_qs, urlencode, urlsplit

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
from tests.test_pregame_reference import rule

API = '/api/comparison-current'
BROWSE = dict(layout='desk', phase='pregame', browse_odds='1', lines='all', summary='1')
RANKED = dict(layout='desk', phase='pregame', ranked='1', basis='sportsbooks', summary='1', board='0')


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
            db.execute('TRUNCATE current_event, comparison_publication, sgo_event_evidence, sgo_quote_revision, pregame_unit_board CASCADE')
            db.execute("INSERT INTO comparison_publication(kind,id,generation,facts) VALUES ('live','',0,'{}')")
        from app.dashboard.request_guard import dashboard_guard

        self.app = web.Application(middlewares=[dashboard_guard(lambda: 'sportsgameodds', logger=__name__)])
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

    def browser_server(self):
        static = Path(__file__).resolve().parents[1] / 'app/dashboard/opportunity_static/current'

        async def desk(_):
            return web.FileResponse(static / 'desk.html')

        app = web.Application()
        for url in ('/', '/ev', '/arbs', '/browse-odds', '/game'):
            app.router.add_get(url, desk)
        app.router.add_static('/view/current', static)
        mount(app)
        return TestServer(app)

    async def test_retained_kalshi_games_admit_exact_direct_winner(self):
        from copy import deepcopy

        from app.collection.current_service import prepare_catalog
        from app.collection.v1_comparison import REPAIR_POLICY, annotate

        captures = json.loads((Path(__file__).parent / 'fixtures/sprint1-kalshi-retained.json').read_text())
        for capture in captures:
            with self.subTest(event=capture['event']['id']):
                event = deepcopy(capture['event'])
                # The retained catalog export was taken after kickoff. Use its
                # immutable occurrence/market metadata. Model the pregame phase
                # for Central Arkansas, whose retained milestone had advanced.
                # The native book clocks remain part of the captured evidence.
                event.pop('exclusion', None)
                for fact in event['observed_identity_facts']:
                    fact['status'] = 'scheduled'
                books = [r['image'] for r in capture['images'].values()]
                self.at = max(stamp(b['raw']['received_at']) for b in books) + timedelta(milliseconds=25)
                self.assertLess(self.at, stamp(event['scheduled_start']))
                # The later discovery receipt cannot authorize a historical
                # read. The replay uses the independently reviewed kickoff.
                if stamp(event['schedule_metadata']['received_at']) > self.at:
                    event.pop('schedule_metadata')
                self.state.write(self.service)
                inventory = dict(events=[event], markets=capture['markets'])
                annotate(inventory, 'kalshi', policy=REPAIR_POLICY)
                catalog = prepare_catalog({}, 'kalshi', inventory)
                quoted_ids = {book['raw']['ref']['market_id'] for book in books}
                header = dict(source='kalshi', session_id='pregame-retained-replay', observed_at=self.at.isoformat())

                def ingest(value):
                    self.sink.reducer, _, _ = self.sink.prepare(value, self.service.states)

                def replay(chosen):
                    prior = self.sink.reducer.generation
                    ingest(dict(header, type='coverage_inventory', inventory=chosen,
                                generation=(prior or 0) + 1, previous_generation=prior))
                    ingest(dict(header, type='prediction_books', observations=[dict(
                        header, type='prediction_book', book=book) for book in books]))

                refused = deepcopy(catalog)
                bad = next(m for m in refused['kalshi']['markets'] if m['id'] in quoted_ids)
                bad['_native']['rules_primary'] = bad['_native']['rules_primary'].replace('Nov 16', 'Nov 23')
                annotate(refused['kalshi'], 'kalshi', policy=REPAIR_POLICY)
                self.assertIn('Exact retained winner predicate conflicts with current native contract',
                              bad['v1_raw_binding']['blockers'])
                replay(refused)
                with self.connect() as db:
                    refused_count = db.execute("SELECT count(*) n FROM current_contract "
                        "WHERE facts#>>'{source,native_market_id}'=%s", (bad['id'],)).fetchone()['n']
                self.assertEqual(refused_count, 0)

                replay(catalog)
                with self.connect() as db:
                    exact_offers = db.execute('''SELECT c.id,o.price_value,o.source_at,o.received_at
                        FROM current_offer o JOIN current_contract c ON c.id=o.contract_id
                        JOIN current_event e ON e.id=c.event_id WHERE e.native_event_id=%s''', (event['id'],)).fetchall()
                self.assertTrue(exact_offers, self.sink.exclusions)
                native_clocks = {(stamp(b['raw']['exchange_at']), stamp(b['raw']['received_at'])) for b in books}
                self.assertEqual({(stamp(o['source_at']), stamp(o['received_at'])) for o in exact_offers}, native_clocks)
                publication = self.publish()
                browse = await self.read(dict(BROWSE, league='NCAAB'))
                exact_keys = {row['id'] for row in exact_offers}
                groups = [g for g in browse['rows'] if any(o['desk_quote_key'] in exact_keys for o in g['offers'])]
                self.assertTrue(groups, (publication['component_trace'], browse.get('total')))
                group = groups[0]
                offer = next(o for o in group['offers'] if o['desk_quote_key'] in exact_keys)
                game = await self.read(dict(BROWSE, game_key=group['game_key']))
                exact = await self.read(dict(layout='desk', phase='pregame', id=offer['id'],
                                             quote_key=offer['desk_quote_key']), API + '/selection')
                self.assertEqual(exact['row']['source']['provider'], 'kalshi')
                native_fill = exact['row']['valuation']['fill_evidence']
                self.assertIsNotNone(native_fill)
                self.assertEqual(stamp(native_fill['received_at']), stamp(offer['received_at']))
                self.assertEqual(exact['row']['source']['native_event_id'], event['id'])
                self.assertEqual(exact['row']['original'], offer['original'])
                self.assertIn(offer['id'], {o['id'] for g in game['rows'] for o in g['offers']})
                self.assertEqual(browse['provider_requests'], 0)
                self.assertEqual(exact['provider_requests'], 0)
                census = await self.read(dict(phase='pregame', funnel='1'), API + '/fee-coverage')
                cell = next(c for c in census['synchronized_funnel']['cohorts'] if c['provider'] == 'kalshi'
                            and c['league'] == 'NCAAB' and c['family'] == 'winner')
                self.assertGreater(cell['desk_access']['available_in_exact_browse'], 0)
                if os.getenv('PREDICT_PREGAME_BROWSER'):
                    from playwright.async_api import async_playwright, expect

                    async with self.browser_server() as server, async_playwright() as pw:
                        browser = await pw.chromium.launch(executable_path=os.getenv('PREDICT_CI_CHROMIUM'))
                        tab = await browser.new_page()
                        await tab.clock.install(time=self.at)
                        await tab.goto(str(server.make_url('/browse-odds')))
                        await expect(tab.locator(f'[data-offer-id="{offer["id"]}"]')).to_be_visible()
                        await tab.get_by_role('link', name='Open Game').first.click()
                        async with tab.expect_response(lambda result: API + '/selection?' in result.url) as request:
                            await tab.locator(f'[data-offer-id="{offer["id"]}"]').click()
                        inspected = await (await request.value).json()
                        self.assertEqual(inspected['row']['source'], exact['row']['source'])
                        self.assertEqual(inspected['provider_requests'], 0)
                        await browser.close()

    async def test_aged_price_and_reference_publish_together_until_authoritative_start(self):
        # Authored rules isolate the positive reference/lifecycle path. The
        # real retained book lacks a jurisdiction witness.
        self.enterContext(patch('app.storage.pregame_reference_publication.reviewed_rules',
                                return_value=lambda *_: rule()))
        self.enterContext(patch('app.storage.pregame_reference_publication.venue_rules',
                                return_value=(rule(), None)))
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
        self.assertEqual(original['quote_freshness'], 'fresh')
        self.assertFalse(original['trade_fee_available'])
        self.assertEqual(original['sportsbook']['prices'][0]['price_american'], '+1400')
        reference_id = original['pregame_reference']['snapshot_id']
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
        old = self.novig(await self.read(dict(BROWSE, refresh='1')))
        self.assertEqual(old['quote_freshness'], 'retained')
        self.assertEqual(old['source_clock_at'], original['source_clock_at'])
        self.assertEqual(old['pregame_reference']['snapshot_id'], reference_id)

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
        from app.storage.ordinary_desk_projection import DeskFragments
        read_fragment = DeskFragments.read

        def linked_publication(*args, **kwargs):
            result = read_fragment(*args, **kwargs)
            row, = result['rows']
            authority = dict(row['current_authority'], occurrence_id='reviewed-occurrence')
            sibling = dict(row, id='linked-offer', venue='prophetx',
                           source=dict(row['source'], provider=provider, native_event_id=linked),
                           current_authority=dict(authority, price=dict(authority['price'], dependency='f' * 64)))
            return dict(result, rows=[dict(row, current_authority=authority), sibling])

        with patch.object(DeskFragments, 'read', linked_publication):
            browse = await self.read(dict(BROWSE, refresh='1'))
            self.assertEqual(stamp(browse['refresh_at']), corrected)
            self.assertEqual({stamp(game['start_at']) for game in browse['games']}, {corrected})
            game_key, = {group['game_key'] for group in browse['rows']}
            opened = await self.read(dict(BROWSE, game_key=game_key))
            self.assertEqual({stamp(group['start_at']) for group in opened['rows']}, {corrected})
            self.assertEqual({offer['venue'] for group in opened['rows'] for offer in group['offers']},
                             {'novig', 'prophetx'})
            self.assertEqual(opened['provider_requests'], 0)
            original = self.novig(browse)
            selection = dict(layout='desk', phase='pregame', id=original['id'], quote_key=original['desk_quote_key'])
            detail = await self.read(selection, API + '/selection')
            self.assertEqual(stamp(detail['row']['start_at']), corrected)
            self.at = corrected
            detail = await self.read(selection, API + '/selection')
            self.assertEqual(detail['generation'], browse['generation'])
            self.assertTrue(detail['withdrawn_from_phase'])
            self.assertIsNone(detail['row'])

    async def test_novig_catalog_publishes_zero_fee_with_settlement_gap(self):
        from app.comparison.sgo_native_binding import settlement_profile

        profile = settlement_profile('NHL', 'spread', Fraction('1.5'), 'FMV')
        sportsbook = rule(**{k: profile[k] for k in ('scope', 'extra_innings', 'shootout', 'shootout_count')})
        self.enterContext(patch('app.storage.pregame_reference_publication.reviewed_rules',
                                return_value=lambda *_: sportsbook))
        raw, event = self.raw(league='NHL', game=SGO, teams=('Seattle Kraken', 'Carolina Hurricanes'))
        home, _ = self.sides(event, family='sp')
        event['links'] = dict(bookmakers=dict(novig=f'https://novig.com/event-markets/{EVENT}/sportsgameodds'))
        home['novig']['deeplink'] = f'https://novig.com/events/{HOME}/sportsgameodds'
        self.admit_page(raw)
        self.publish()
        before = self.novig(await self.read(dict(BROWSE, refresh='1')))
        self.assertEqual(before['trade_fee_reason'], 'sgo_native_catalog_unavailable')
        self.assertIsNone(before['after_fee'])
        after_fee_query = dict(RANKED, basis='after_fees')
        empty = await self.read(after_fee_query)
        self.assertEqual(empty['rows'], [])
        self.assertIn('sgo_native_catalog_unavailable', empty['calculation_missing'])

        self.at += timedelta(minutes=4)
        # Adopting reviewed retail terms is enough to calculate a typed
        # pregame straight. No direct price or catalog response is required.
        from app.collection.public_fee_refresh import refresh_product
        from app.fees import product_schedules

        key = 'novig:pregame_straight'
        approved = product_schedules.approved(key)

        async def read_terms(url, _limit):
            self.assertEqual(url, approved['url'])
            return (product_schedules.ROOT / approved['reference']).read_bytes(), dict(status=200)

        product_state = await refresh_product(key, {}, read_terms, clock=lambda: self.at.isoformat())
        self.assertTrue(product_state['last_verified']['standing_public_terms'])
        with self.connect() as db:
            product_schedules.write(db, key, product_state)
        self.publish()
        retail = self.novig(await self.read(dict(BROWSE, refresh='1')))
        self.assertEqual(retail['trade_fee']['trade_fee_usd'], '0')
        retail_detail = (await self.read(dict(layout='desk', phase='pregame', id=retail['id'],
            quote_key=retail['desk_quote_key'], basis='after_fees', preview_amount='10', unit_usd='25'), API + '/selection'))['row']
        self.assertEqual(retail_detail['trade_fee']['evidence']['basis'], 'reviewed_retail_pregame_straight')
        self.assertEqual(retail_detail['trade_preview']['fee_at_entry_usd'], '0')

        self.at += timedelta(seconds=1)
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
        self.assertIsNone(after['sportsbook_after_fee'])
        self.assertIsNone(after['after_fee'])
        self.assertTrue(after['pregame_reference']['available'])
        settlement_reason = 'settlement_exceptional_cashflows_unverified_or_different'
        self.assertEqual(after['settlement_assessment']['reason'], settlement_reason)
        ranked = self.novig(await self.read(RANKED))
        self.assertEqual((await self.read(after_fee_query))['rows'], [])
        selected = (await self.read(dict(layout='desk', phase='pregame', id=after['id'],
                                         quote_key=after['desk_quote_key'], basis='after_fees', preview_amount='10', unit_usd='25'), API + '/selection'))['row']
        for other in (ranked, selected):
            self.assertEqual((other['economic_revision'], other['sportsbook_after_fee'], other['trade_fee']['trade_fee_usd']),
                             (after['economic_revision'], after['sportsbook_after_fee'], '0'))
            self.assertIsNone(other['after_fee'])
        self.assertIsNone(selected['value'])
        self.assertEqual(selected['reason'], settlement_reason)
        self.assertTrue(after['posted_price'])
        blocked = selected['valuation']
        self.assertEqual(blocked['display']['fee'], '$0.00')
        self.assertEqual(blocked['reasons']['settlement'], 'settlement_novig_void_fair_value_unverified')
        self.assertNotIn('net_ev', blocked['raw'])
        self.assertTrue(selected['trade_preview']['fee_available'])
        self.assertEqual(selected['trade_preview']['fee_at_entry_usd'], '0')
        self.assertEqual(selected['trade_fee']['evidence']['schedule_version'], 'novig-v3-observed-20260930')
        self.assertFalse(selected['trade_preview']['rounding_trace'][0]['charged'])
        self.assertIsNone(selected['trade_preview'].get('estimated_return_percent'))
        census = await self.read(dict(phase='pregame'), API + '/fee-coverage')
        self.assertEqual(census['total']['posted_modeled_after_fee'], 0)
        self.assertEqual(census['posted_settlement_missing_reasons'][settlement_reason], 1)
        self.assertEqual(census['total']['reviewed_after_fee_ev'], 0)
        self.assertIsNotNone(census['published_at'])

        self.at += timedelta(hours=3)
        home['fanduel'].update(available=False, lastUpdatedAt=self.at.isoformat())
        self.admit_page(raw)
        self.publish()
        no_reference = self.novig(await self.read(dict(BROWSE, refresh='1')))
        self.assertEqual(no_reference['trade_fee']['trade_fee_usd'], '0')
        self.assertIsNone(no_reference['before_fee'])
        self.assertIsNone(no_reference['after_fee'])
        unranked = self.novig(await self.read(RANKED))
        self.assertEqual(unranked['reason'], 'reference_quote_withdrawn')
        self.assertEqual(unranked['trade_fee'], no_reference['trade_fee'])
        self.assertEqual((await self.read(after_fee_query))['rows'], [])
        census = await self.read(dict(phase='pregame'), API + '/fee-coverage')
        self.assertEqual(census['generation'], (await self.read(RANKED))['generation'])
        self.assertEqual((census['total']['current'], census['total']['covered']), (1, 1))
        self.assertEqual(census['total']['posted_modeled_after_fee'], 0)

        self.at += timedelta(seconds=1)
        with self.connect() as db:
            catalog = sgo_native_catalog.read(db, [SGO])[SGO]
            catalog.pop('revision')
            catalog['observed_at'] = self.at.isoformat()
            catalog['expires_at'] = (self.at + timedelta(minutes=15)).isoformat()
            catalog['event']['startsTs'] += 60_000
            for contract in catalog['markets'].values():
                contract['startsTs'] = catalog['event']['startsTs']
            sgo_native_catalog.write(db, SGO, catalog)
        self.publish()
        contradicted = self.novig(await self.read(dict(BROWSE, refresh='1')))
        self.assertEqual(contradicted['odds'], after['odds'])
        self.assertFalse(contradicted['trade_fee_available'])
        self.assertEqual(contradicted['trade_fee_reason'], 'sgo_native_kickoff_conflict')
        census = await self.read(dict(phase='pregame'), API + '/fee-coverage')
        self.assertEqual(census['posted_fee_missing_reasons']['sgo_native_kickoff_conflict'], 1)

    async def test_saint_marys_published_unit_selection_and_replacement(self):
        from tests.test_pregame_valuation import fixture_terms

        rules = dict(rule(), outcomes=['home', 'away'])
        self.enterContext(patch('app.storage.pregame_reference_publication.reviewed_rules',
                                return_value=lambda *_: rules))
        self.enterContext(patch('app.storage.pregame_reference_publication.venue_rules',
                                return_value=(rules, None)))

        def freeze_fixture(_db, inputs):
            for q in inputs['quotes']:
                if q['venue'] in ('prophetx', 'novig'):
                    terms = fixture_terms(entry_rate='0.03')
                    terms['cash_terms']['flat_entry_usd'] = '0.02'
                    q['valuation_fill_terms'] = terms

        self.enterContext(patch('app.storage.pregame_valuation_inputs.freeze', side_effect=freeze_fixture))
        raw, event = self.raw(game='synthetic-saint-marys', teams=("Saint Mary's Gaels", "Gonzaga Bulldogs"))
        home, away = self.sides(event, family='sp', left='-110', right='-110')
        home['fanduel']['spread'] = '-18.5'
        away['fanduel']['spread'] = '18.5'
        home['prophetx'] = dict(home['novig'], spread='-18.5', odds='+112')
        home['novig'].update(spread='-18.5', odds='-110')
        self.admit_page(raw)
        self.publish()

        async def listed():
            browse = await self.read(BROWSE)
            offer, = [o for g in browse['rows'] for o in g['offers'] if o['venue'] == 'prophetx']
            return offer

        def query(offer, **extra):
            return dict(layout='desk', phase='pregame', id=offer['id'], quote_key=offer['desk_quote_key'], **extra)

        async def selected(offer, **extra):
            packet = await self.read(query(offer, **extra), API + '/selection')
            self.assertEqual(packet['provider_requests'], 0)
            model = packet['row']['valuation']
            self.assertEqual(model['member_result_id'], offer['evidence_result_id'])
            self.assertEqual(model['publication_id'], packet['result_id'])
            return model

        first = await listed()
        self.assertIsNone((await selected(first))['selected_usd'])
        positive = await selected(first, unit_usd='25', expected_member=first['evidence_result_id'])
        self.assertEqual(positive['evidence_class'], 'fixture')
        self.assertEqual(positive['fill']['stake_usd'], '24.25')
        self.assertEqual(positive['fees']['entry_usd'], '0.75')
        self.assertEqual(positive['states']['win']['net_receipt_usd'], '51.41')
        self.assertEqual((positive['display']['after_fee_odds'], positive['display']['net_ev'],
                          positive['display']['opportunity_score']), ('+106', '+2.82%', '267'))
        invalid = await self.client.get(API + '/selection', params=query(first, unit_usd='0.001'))
        self.assertEqual(invalid.status, 422)

        board_query = dict(RANKED, board='1', lines='main', limit='1')
        self.assertEqual((await self.read({k:v for k,v in board_query.items() if k != 'board'}))['state'], 'unit_needed')
        self.assertEqual((await self.read(dict(board_query, unit_usd='25')))['state'], 'valuation_pending')
        self.assertEqual((await self.read(dict(board_query, unit_usd='25.00')))['state'], 'valuation_pending')
        first_job = self.publish()['unit_board']
        self.assertEqual(first_job['unit_cents'], 2500)
        self.assertTrue(first_job['published'], first_job)
        board_25 = await self.read(dict(board_query, unit_usd='25'))
        self.assertEqual(board_25['board_state'], 'populated', board_25)
        self.assertEqual(board_25['total'], 1)
        quote_25 = board_25['rows'][0]['offers'][0]
        self.assertEqual(quote_25['valuation_summary']['display'], positive['display'])
        self.assertEqual(quote_25['valuation_summary']['reference'],
                         dict(book='fanduel', selected_price='-110', conditioning=None,
                              fair_odds=dict(american='+100', decimal='2', reason=None)))
        exact_board_query = query(quote_25, unit_usd='25', board_id=board_25['board_id'],
                                  expected_member=quote_25['evidence_result_id'])
        exact = await self.read(exact_board_query, API + '/selection')
        self.assertEqual(exact['row']['valuation']['raw'], positive['raw'])
        self.assertEqual(exact['comparison'][0]['offer_id'], quote_25['id'])
        self.assertEqual(exact['comparison'][0]['reference_snapshot_id'], positive['reference_snapshot_id'])
        self.assertEqual([m['venue'] for m in exact['comparison']], ['prophetx', 'novig'])
        self.assertEqual(exact['comparison'][1]['status'], 'qualified')
        self.assertLess(Fraction(exact['comparison'][1]['raw']['net_ev']), 0)
        # Exercise out-of-band authority changes while the same board remains sealed.
        from app.fees import schedule_lifecycle

        contract = quote_25['desk_quote_key']
        with self.connect() as db:
            original_offer = db.execute('SELECT facts FROM current_offer_storage WHERE contract_id=%s',
                                        (contract,)).fetchone()['facts']
            original_contract = db.execute('SELECT facts FROM current_contract_storage WHERE id=%s',
                                           (contract,)).fetchone()['facts']
            original_schedule = schedule_lifecycle.read(db)
            mutations = [
                ('phase_price_unavailable',
                    lambda: db.execute('UPDATE current_offer_storage SET facts=%s WHERE contract_id=%s',
                                       (Jsonb(dict(original_offer, state='unavailable')), contract)),
                    lambda: db.execute('UPDATE current_offer_storage SET facts=%s WHERE contract_id=%s',
                                       (Jsonb(original_offer), contract))),
                ('venue_settlement_rules_unverified',
                    lambda: db.execute("UPDATE current_contract_storage SET facts=jsonb_set(facts, "
                                       "'{market_identity,rules}', to_jsonb('withdrawn-fixture-rule'::text)) WHERE id=%s", (contract,)),
                    lambda: db.execute('UPDATE current_contract_storage SET facts=%s WHERE id=%s',
                                       (Jsonb(original_contract), contract))),
                ('public_fee_schedule_refresh_pending',
                    lambda: schedule_lifecycle.write(db, dict(review_required=dict(reason='fixture_fee_withdrawn'))),
                    lambda: schedule_lifecycle.write(db, original_schedule) if original_schedule is not None else
                        db.execute("DELETE FROM public_fee_schedule WHERE venue='prophetx'")),
            ]
            for reason, withdraw, restore in mutations:
                with self.subTest(guard=reason):
                    try:
                        withdraw()
                        unavailable = await self.read(exact_board_query, API + '/selection')
                        self.assertEqual((unavailable['row'], unavailable['reason']), (None, reason))
                        held = await self.read(dict(board_query, unit_usd='25', refresh='1'))
                        self.assertEqual((held['board_id'], held['board_state']), (board_25['board_id'], 'empty'))
                    finally:
                        restore()
        pending = await self.read(dict(board_query, unit_usd='12'))
        self.assertEqual(pending['state'], 'valuation_pending')
        self.assertEqual(pending['selected_usd'], '12')
        self.assertEqual(pending['rows'], [])
        self.assertEqual(self.publish()['unit_board']['unit_cents'], 1200)
        board_12 = await self.read(dict(board_query, unit_usd='12'))
        self.assertEqual(board_12['rows'][0]['offers'][0]['valuation_summary']['display']['net_ev'], '+2.73%')
        wrong_cursor = await self.read(dict(board_query, unit_usd='12', offset='1', board_cursor=board_25['board_cursor']))
        self.assertEqual(wrong_cursor['state'], 'page_changed')
        self.assertNotEqual(board_12['board_id'], board_25['board_id'])
        self.assertFalse(self.publish()['unit_board'])
        if output := os.getenv('PREDICT_SPRINT4_FIXTURE_OUTPUT'):
            folder = Path(output)
            folder.mkdir(exist_ok=True, parents=True)
            for name, data in [('saint-marys-25-board', board_25), ('saint-marys-12-board', board_12),
                               ('saint-marys-25-selection', exact)]:
                (folder / (name + '.json')).write_text(json.dumps(data, indent=2) + '\n')

        if os.getenv('PREDICT_PREGAME_BROWSER'):
            await self._verify_saint_marys_chromium()
        if output := os.getenv('PREDICT_SPRINT3_POSITIVE_OUTPUT'):
            Path(output).write_text(json.dumps(positive, indent=2) + '\n')

        self.at += timedelta(seconds=5)
        home['prophetx'].update(lastUpdatedAt=self.at.isoformat(), odds='+110')
        self.admit_page(raw)
        from app.storage import pregame_unit_board

        # Commit a normal successor root while the board worker is paused.
        with patch.object(pregame_unit_board, 'service', return_value={}):
            self.publish()
        old_board = await self.read(dict(board_query, unit_usd='25', refresh='1'))
        self.assertEqual(old_board['board_id'], board_25['board_id'])
        self.assertTrue(old_board['replacement_pending'])
        changed = await self.read(exact_board_query, API + '/selection')
        self.assertEqual(changed['reason'], 'unit_publication_changed')
        self.assertTrue(self.publish()['unit_board']['published'])
        obsolete = await self.read(query(first, unit_usd='25', expected_member=first['evidence_result_id']), API + '/selection')
        self.assertIsNone(obsolete['row'])
        self.assertEqual(obsolete['reason'], 'unit_publication_changed')
        second = await listed()
        replacement = await selected(second, unit_usd='25')
        self.assertEqual(replacement['display']['net_ev'], '+1.85%')

        self.at += timedelta(seconds=5)
        persisted = away.pop('fanduel')
        self.admit_page(raw)
        self.publish()
        retained = await selected(await listed(), unit_usd='25')
        self.assertEqual(retained['reference_snapshot_id'], replacement['reference_snapshot_id'])
        self.assertEqual(retained['display']['net_ev'], '+1.85%')

        def publish_negative():
            self.at += timedelta(seconds=5)
            home['prophetx'].update(lastUpdatedAt=self.at.isoformat(), odds='-110')
            self.admit_page(raw)
            with patch.object(pregame_unit_board, 'service', return_value={}):
                self.publish()

        def commit_negative():
            for _ in range(3):
                self.publish()

        if os.getenv('PREDICT_PREGAME_BROWSER'):
            await self._verify_refresh_to_negative(publish_negative, commit_negative)
        else:
            publish_negative()
            commit_negative()
        no_positive = await self.read(dict(board_query, unit_usd='25', refresh='1'))
        self.assertEqual(no_positive['board_state'], 'empty')
        self.assertGreater(no_positive['qualified_board_offer_count'], 0)
        current_exact = await self.read(query(quote_25, unit_usd='25', refresh='1', board_id=no_positive['board_id']),
                                        API + '/selection')
        self.assertEqual(current_exact['row']['valuation']['display']['net_ev'], '-7.41%')

        self.at += timedelta(seconds=5)
        away['fanduel'] = dict(persisted, available=False, lastUpdatedAt=self.at.isoformat())
        self.admit_page(raw)
        withdrawn_board = await self.read(dict(board_query, unit_usd='25', refresh='1'))
        self.assertEqual(withdrawn_board['board_state'], 'empty')
        self.assertIn('reference_quote_withdrawn', withdrawn_board['calculation_missing'])
        self.publish()
        gone = await listed()
        blocked = await selected(gone, unit_usd='25')
        self.assertEqual(blocked['reasons']['reference'], 'reference_quote_withdrawn')
        self.assertNotIn('net_ev', blocked['raw'])
        self.assertEqual(blocked['fees']['entry_usd'], '0.75')

        self.at = self.kickoff
        ended_board = await self.read(dict(board_query, unit_usd='25', refresh='1'))
        self.assertEqual(ended_board['board_state'], 'empty')
        self.assertEqual(ended_board['matched_offer_count'], 0)
        ended = await self.read(query(gone, unit_usd='25'), API + '/selection')
        self.assertTrue(ended['withdrawn_from_phase'])
        self.assertIsNone(ended['row'])

    async def test_selected_unit_order_eligibility_and_pagination(self):
        from app.storage import pregame_unit_board
        from tests.test_pregame_valuation import fixture_terms

        rules = dict(rule(), outcomes=['home', 'away'])
        self.enterContext(patch('app.storage.pregame_reference_publication.reviewed_rules',
                                return_value=lambda *_: rules))
        self.enterContext(patch('app.storage.pregame_reference_publication.venue_rules',
                                return_value=(rules, None)))

        def freeze_fixture(_db, inputs):
            for quote in inputs['quotes']:
                terms = fixture_terms(entry_rate='0.03')
                terms['cash_terms']['flat_entry_usd'] = '0.02'
                quote['valuation_fill_terms'] = terms

        self.enterContext(patch('app.storage.pregame_valuation_inputs.freeze', side_effect=freeze_fixture))
        raw, event = self.raw(game='score-control', teams=("Saint Mary's Gaels", "Gonzaga Bulldogs"))
        home, away = self.sides(event, family='sp', left='-110', right='-110')
        home['fanduel'].update(spread='-18.5', altLines=[dict(home['fanduel'], spread='-19.5')])
        away['fanduel'].update(spread='18.5', altLines=[dict(away['fanduel'], spread='19.5')])
        home['novig'].update(spread='-18.5', odds='+109')
        home['prophetx'] = dict(home['novig'], odds='+112', altLines=[dict(home['novig'], spread='-19.5', odds='+140')])
        self.admit_page(raw)
        raw, event = self.raw(game='ev-control', teams=('Kansas Jayhawks', 'Northern Arizona Lumberjacks'))
        home, _ = self.sides(event, left='+500', right='-550')
        home['prophetx'] = dict(home.pop('novig'), odds='+550')
        self.admit_page(raw)
        board = dict(RANKED, board='1', unit_usd='25', lines='main', limit='1')
        self.assertEqual((await self.read(board))['state'], 'valuation_pending')
        for _ in range(3):
            if self.publish()['unit_board'].get('published'):
                break
        first = await self.read(board)
        self.assertEqual(first['total'], 2, first)
        next_page = await self.read(dict(board, offset='1', board_cursor=first['board_cursor']))
        score_winner, = first['rows']
        ev_winner, = next_page['rows']
        self.assertIn('Saint Mary', score_winner['game_title'])
        self.assertLess(Fraction(score_winner['score']), Fraction(ev_winner['score']))
        self.assertGreater(Fraction(score_winner['opportunity_score']), Fraction(ev_winner['opportunity_score']))
        self.assertEqual(score_winner['offers'][0]['venue'], 'prophetx')
        self.assertEqual(ev_winner['offers'][0]['valuation_summary']['reference']['fair_odds'],
                         dict(american='+508', decimal='79/13', reason=None))
        self.assertEqual((await self.read(dict(board, venue='novig')))['rows'][0]['offers'][0]['venue'], 'novig')
        expanded = await self.read(dict(board, lines='all', limit='10'))
        self.assertEqual(expanded['total'], 3)
        self.assertEqual(expanded['rows'][0]['line_role'], 'alternate')
        if os.getenv('PREDICT_PREGAME_BROWSER'):
            await self._verify_ticket_order(score_winner, ev_winner)

        # Simulate an ordinary publication advancing between the expensive
        # member calculation and the atomic pointer compare-and-swap.
        from app.storage import ordinary_publication as live
        started = pregame_unit_board.assemble
        with self.connect() as db:
            pregame_unit_board.request(db, 1200)
            prior = live.status(db)
            owner, states = live.authority(db, at=self.at, include_diagnostics=False)
            epoch = str(db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch'])

            def replacement(*args, **kwargs):
                result = started(*args, **kwargs)
                with self.connect() as other:
                    other.execute("UPDATE comparison_publication SET result_id=NULL WHERE kind='live' AND id=''")
                return result

            with patch.object(pregame_unit_board, 'assemble', side_effect=replacement):
                stale = pregame_unit_board.turn(db, head=prior, owner=owner, states=states, epoch=epoch, at=self.at)
            self.assertTrue(stale['superseded'])
            self.assertIsNone(pregame_unit_board.read(db, 1200)['board_id'])
            db.execute("UPDATE comparison_publication SET result_id=%s WHERE kind='live' AND id=''", (prior['result_id'],))
        recovered = self.publish()['unit_board']
        self.assertEqual(recovered['unit_cents'], 1200)
        self.assertTrue(recovered['published'])
        self.assertEqual(recovered['member_builds'], 0)
        self.assertGreater(recovered['member_reuses'], 0)

    async def _verify_ticket_order(self, score_winner, ev_winner):
        from playwright.async_api import async_playwright, expect

        async with self.browser_server() as server, async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=os.getenv('PREDICT_CI_CHROMIUM'))
            tab = await browser.new_page()
            await tab.clock.install(time=self.at)
            stale = False

            async def one_per_page(route):
                nonlocal stale
                url = urlsplit(route.request.url)
                query = parse_qs(url.query)
                self.assertEqual(query['lines'], ['main'])
                query['limit'] = ['1']
                if stale and query.get('offset') == ['1']:
                    stale = False
                    query['board_cursor'] = ['0' * 64]
                await route.continue_(url=url._replace(query=urlencode(query, doseq=True)).geturl())

            await tab.route('**/api/comparison-current?*', one_per_page)
            await tab.goto(str(server.make_url('/')))
            await tab.get_by_label('Unit size').select_option('25.00')
            board = tab.locator('.pregame-ticket')
            await expect(board).to_have_attribute('data-group-id', score_winner['id'])
            await tab.get_by_role('button', name='Next').click()
            await expect(board).to_have_attribute('data-group-id', ev_winner['id'])
            await tab.get_by_role('button', name='Previous').click()
            await expect(board).to_have_attribute('data-group-id', score_winner['id'])
            stale = True
            await tab.get_by_role('button', name='Next').click()
            await expect(tab.locator('#notice')).to_contain_text('Return to the first page.')
            await expect(board).to_have_attribute('data-group-id', score_winner['id'])
            await tab.get_by_role('button', name='Next').click()
            await expect(board).to_have_attribute('data-group-id', ev_winner['id'])
            await browser.close()

    async def _verify_refresh_to_negative(self, publish_negative, commit_negative):
        from playwright.async_api import async_playwright, expect

        async with self.browser_server() as server, async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=os.getenv('PREDICT_CI_CHROMIUM'))
            tab = await browser.new_page()
            await tab.clock.install(time=self.at)
            await tab.goto(str(server.make_url('/')))
            await tab.get_by_label('Unit size').select_option('25.00')
            opener = tab.get_by_role('button', name=re.compile('Compare prices'))
            await opener.click()
            drawer = tab.get_by_role('dialog')
            offer = drawer.locator('.comparison-offer.selected')
            await expect(offer).to_contain_text('+1.85%')
            await drawer.get_by_role('button', name='Close').click()
            publish_negative()
            await tab.get_by_role('button', name='Refresh list').click()
            await expect(tab.locator('#previous-results')).to_contain_text('Prices are updating.')
            await expect(tab.locator('.pregame-ticket')).to_contain_text('+1.85%')
            await opener.click()
            await expect(drawer).to_contain_text('This offer or its calculation changed.')
            await expect(drawer).not_to_contain_text('+1.85%')
            commit_negative()
            await drawer.get_by_role('button', name='Refresh calculation').click()
            await expect(drawer).to_contain_text('Unit $25')
            await expect(offer).to_contain_text('-7.41%')
            await drawer.get_by_role('button', name='Close').click()
            await expect(tab.get_by_role('heading', name='No positive Net EV offers at this unit size.')).to_be_visible()
            await browser.close()

    async def test_selected_unit_read_budget_recovers_from_blocked_postgres(self):
        raw, event = self.raw()
        self.sides(event)
        self.admit_page(raw)
        self.publish()
        board = dict(RANKED, board='1', unit_usd='25', refresh='1')
        await self.read(board)
        self.assertTrue(self.publish()['unit_board']['published'])
        with self.connect() as db, db.transaction():
            db.execute('LOCK comparison_publication IN ACCESS EXCLUSIVE MODE')
            blocked = await self.client.get(API, params=board)
            self.assertEqual(blocked.status, 503)
            self.assertEqual((await blocked.json())['state'], 'read_failed')
            self.assertIn('request_wait;', blocked.headers['Server-Timing'])
        recovered = await self.read(board)
        self.assertEqual(recovered['board_state'], 'empty')
        self.assertEqual(recovered['provider_requests'], 0)
        if os.getenv('PREDICT_PREGAME_BROWSER'):
            await self._verify_browser_read_failure()

    async def _verify_browser_read_failure(self):
        from playwright.async_api import async_playwright, expect

        async with self.browser_server() as server, async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=os.getenv('PREDICT_CI_CHROMIUM'))
            width = int(os.getenv('PREDICT_SPRINT5_WIDTH', '1440'))
            tab = await browser.new_page(viewport={'width': width, 'height': 880})
            await tab.clock.install(time=self.at)
            async with tab.expect_response(lambda response: API + '?' in response.url):
                await tab.goto(str(server.make_url('/ev')))
            unit = tab.get_by_label('Unit size')
            locked, release = Event(), Event()

            def block_reads():
                with self.connect() as db, db.transaction():
                    db.execute("SET LOCAL lock_timeout='1s'")
                    db.execute('LOCK comparison_publication IN ACCESS EXCLUSIVE MODE')
                    locked.set()
                    release.wait(6)

            blocker = create_task(to_thread(block_reads))
            try:
                self.assertTrue(await to_thread(locked.wait, 2))
                async with tab.expect_response(lambda response: API + '?' in response.url and
                                               'unit_usd=25.00' in response.url, timeout=4000) as failed:
                    await unit.select_option('25.00')
                response = await failed.value
                self.assertEqual(response.status, 503)
                await expect(tab.get_by_role('heading', name='Opportunities could not be loaded')).to_be_visible()
                await expect(tab.locator('#results').get_by_role('link', name='Browse Odds')).to_be_visible()
            finally:
                release.set()
                await blocker
            if output := os.getenv('PREDICT_SPRINT5_SCREENSHOTS'):
                folder = Path(output)
                folder.mkdir(exist_ok=True, parents=True)
                await tab.screenshot(path=folder / f'fixture-read-failed-{width}.png', timeout=4000)
            async with tab.expect_response(lambda response: API + '?' in response.url and
                                           'refresh=1' in response.url) as retry:
                await tab.get_by_role('button', name='Retry', exact=True).click()
            response = await retry.value
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['provider_requests'], 0)
            await expect(tab.get_by_role('heading', name='No offers qualify for Net EV at this unit size.')).to_be_visible()

            locked.clear()
            release.clear()
            blocker = create_task(to_thread(block_reads))
            try:
                self.assertTrue(await to_thread(locked.wait, 2))
                async with tab.expect_response(lambda response: API + '?' in response.url and
                                               'browse_odds=1' in response.url, timeout=4000) as failed:
                    await tab.goto(str(server.make_url('/browse-odds')))
                self.assertEqual((await failed.value).status, 503)
                await expect(tab.locator('#notice')).to_have_text('Prices could not be loaded.')
                await expect(tab.locator('.missing-quote')).to_have_count(0)
            finally:
                release.set()
                await blocker
            async with tab.expect_response(lambda response: API + '?' in response.url and
                                           'refresh=1' in response.url) as retry:
                await tab.get_by_role('button', name='Retry', exact=True).click()
            self.assertEqual((await (await retry.value).json())['provider_requests'], 0)
            await expect(tab.get_by_role('link', name='Open Game').first).to_be_visible()
            await browser.close()

    async def _verify_saint_marys_chromium(self):
        from playwright.async_api import async_playwright, expect

        server = self.browser_server()
        await server.start_server()
        self.addAsyncCleanup(server.close)
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=os.getenv('PREDICT_CI_CHROMIUM'))
            try:
                width = int(os.getenv('PREDICT_SPRINT5_WIDTH', '1440'))
                tab = await browser.new_page(viewport={'width': width, 'height': 880})
                errors = []
                tab.on('pageerror', lambda error: errors.append(str(error)))
                await tab.clock.install(time=self.at)
                await tab.goto(str(server.make_url('/')))
                await expect(tab.get_by_role('heading', name='Choose a unit size to rank offers after fees.')).to_be_visible()
                await expect(tab.locator('#results').get_by_role('link', name='Browse Odds')).to_be_visible()
                await tab.goto(str(server.make_url('/ev')))
                await expect(tab.get_by_role('heading', name='Choose a unit size to rank offers after fees.')).to_be_visible()
                await expect(tab.locator('#results').get_by_role('link', name='Browse Odds')).to_be_visible()
                unit = tab.get_by_label('Unit size')
                await expect(unit).to_have_value('')

                async def capture(state):
                    if output := os.getenv('PREDICT_SPRINT5_SCREENSHOTS'):
                        folder = Path(output)
                        folder.mkdir(exist_ok=True, parents=True)
                        await tab.screenshot(path=folder / f'fixture-{state}-{width}.png', animations='disabled')

                await capture('first-use')
                await unit.select_option('25.00')
                board = tab.locator('.pregame-ticket')
                await expect(board).to_contain_text('267')
                await expect(board).to_contain_text('+2.82%')
                await expect(board).to_contain_text('FanDuel -110')
                await expect(board).to_contain_text('+100')
                await expect(board).to_contain_text('+106')
                await expect(board).to_contain_text('+112')
                self.assertTrue(await board.evaluate("""ticket => {
                    const metrics = ticket.querySelector('.ticket-metrics').getBoundingClientRect();
                    const compare = ticket.querySelector('.ticket-compare').getBoundingClientRect();
                    return metrics.right <= compare.left || metrics.bottom <= compare.top;
                }"""))
                await capture('populated-25')
                opener = tab.get_by_role('button', name=re.compile('Compare prices for Saint Mary', re.I))
                await opener.press('Enter')
                dialog = tab.get_by_role('dialog')
                await expect(dialog).to_contain_text('Unit $25')
                await expect(dialog.locator('.comparison-offer').nth(1)).to_contain_text('-7.41%')
                await expect(dialog).to_contain_text('Fair win chance')
                await expect(dialog).to_contain_text('50.00%')
                details = dialog.locator('.comparison-offer.selected summary')
                await details.click()
                await expect(dialog.get_by_text('$51.41 returned', exact=False)).to_be_visible()
                await details.click()
                await capture('comparison-25')
                await tab.keyboard.press('Escape')
                await expect(opener).to_be_focused()
                await opener.click()
                await tab.go_back()
                await expect(opener).to_be_focused()
                self.assertTrue(await tab.evaluate('document.documentElement.scrollWidth === innerWidth'))
                if width == 390:
                    await tab.set_viewport_size({'width': width, 'height': 480})
                    await opener.scroll_into_view_if_needed()
                    previous_y = await tab.evaluate('window.scrollY')
                    self.assertGreater(previous_y, 0)
                    await opener.press('Enter')
                    await tab.keyboard.press('Escape')
                    await expect(opener).to_be_focused()
                    self.assertEqual(await tab.evaluate('window.scrollY'), previous_y)
                    await tab.set_viewport_size({'width': width, 'height': 880})
                await unit.select_option('12.00')
                await expect(board).to_contain_text('259')
                await expect(board).to_contain_text('+2.73%')
                await expect(board).not_to_contain_text('267')
                await tab.goto(str(server.make_url('/ev')))
                await expect(unit).to_have_value('12.00')
                await expect(board).to_contain_text('+2.73%')

                async def fail_once(route):
                    await route.fulfill(status=503, json=dict(schema='predict-pregame-board-1', state='read_failed'))

                board_pattern = '**/api/comparison-current?*'
                await tab.route(board_pattern, fail_once, times=1)
                await tab.get_by_role('button', name='Refresh list').click()
                await expect(tab.locator('#previous-results')).to_contain_text('Showing previous results.')
                await expect(board).to_contain_text('+2.73%')
                await tab.get_by_role('button', name='Retry').click()
                await expect(tab.locator('#previous-results')).to_be_hidden()

                board_delayed, board_release, board_done = AsyncEvent(), AsyncEvent(), AsyncEvent()
                async def delay_old_board(route):
                    query = parse_qs(urlsplit(route.request.url).query)
                    if query.get('unit_usd') != ['25.00']:
                        await route.continue_()
                        return
                    response = await route.fetch()
                    self.assertEqual(response.status, 200)
                    board_delayed.set()
                    await board_release.wait()
                    from playwright.async_api import Error
                    try:
                        await route.fulfill(response=response)
                    except Error:
                        # The newer unit aborts the request at the browser boundary.
                        pass
                    finally:
                        board_done.set()

                await tab.route(board_pattern, delay_old_board)
                await unit.select_option('25.00')
                await wait_for(board_delayed.wait(), 5)
                await expect(tab.get_by_role('heading', name='Calculating opportunities for $25')).to_be_visible()
                await unit.select_option('12.00')
                await expect(board).to_contain_text('259')
                board_release.set()
                await wait_for(board_done.wait(), 5)
                await expect(board).not_to_contain_text('267')
                await opener.click()
                await expect(dialog).to_contain_text('Unit $12')
                await expect(dialog).to_contain_text('+2.73%')
                await dialog.get_by_role('button', name='Close', exact=True).click()
                await tab.unroute(board_pattern, delay_old_board)
                await tab.goto(str(server.make_url('/browse-odds?league=NCAAB')))
                await tab.get_by_role('link', name=re.compile('open game', re.I)).first.click()
                tile = tab.get_by_role('button', name=re.compile(r'ProphetX.*\+112.*Quote details'))
                await expect(tile).to_be_visible()
                outcome = tab.get_by_role('row').filter(has=tile)
                await expect(outcome.locator('.matrix-fair-odds')).to_contain_text('+100')
                await expect(outcome.locator('.matrix-fair-odds')).to_contain_text('FanDuel')
                await outcome.get_by_role('button', name=re.compile('Same-line sportsbook quotes')).press('Enter')
                books = tab.get_by_role('dialog', name='Same-line sportsbook quotes')
                await expect(books.get_by_text('FanDuel')).to_be_visible()
                await expect(books.get_by_text('-110', exact=True).first).to_be_visible()
                await tab.keyboard.press('Escape')
                await tile.press('Enter')
                drawer = tab.get_by_role('dialog')
                self.assertFalse(errors, errors)
                amount = drawer.get_by_label('Maximum upfront cost')
                await expect(amount).to_have_value('12.00')
                async def enter(value):
                    await amount.fill(value)
                    await amount.press('Tab')
                await enter('25')
                await expect(drawer).to_contain_text('$24.25')
                await expect(drawer).to_contain_text('$0.75')
                await expect(drawer).to_contain_text('$51.41 returned')
                await expect(drawer).to_contain_text('+106')
                await expect(drawer).to_contain_text('+2.82%')
                await expect(drawer).to_contain_text('267')
                await expect(drawer).to_contain_text('Test fixture')
                # Hold an older successful calculation at the network boundary.
                # The later size must win even if the older response arrives last.
                pending, release = AsyncEvent(), AsyncEvent()
                async def delay_one_size(route):
                    query = parse_qs(urlsplit(route.request.url).query)
                    if query.get('unit_usd') != ['35.00']:
                        await route.continue_()
                        return
                    response = await route.fetch()
                    self.assertEqual(response.status, 200)
                    pending.set()
                    await release.wait()
                    await route.fulfill(response=response)
                pattern = '**/api/comparison-current/selection?*'
                await tab.route(pattern, delay_one_size)
                await enter('35')
                await wait_for(pending.wait(), 5)
                await enter('12')
                await expect(drawer).to_contain_text('$11.63')
                await expect(drawer).to_contain_text('$0.37')
                await expect(drawer).to_contain_text('$24.66 returned')
                await expect(drawer).to_contain_text('+105')
                await expect(drawer).to_contain_text('+2.73%')
                await expect(drawer).to_contain_text('259')
                async with tab.expect_response(lambda r: 'unit_usd=35.00' in r.url):
                    release.set()
                await expect(drawer).to_contain_text('$11.63')
                await expect(amount).to_have_value('12')
                await tab.unroute(pattern, delay_one_size)
                await enter('')
                await expect(drawer).not_to_contain_text('+2.73%')
                await expect(drawer).to_contain_text('Enter a maximum upfront cost')
                self.assertFalse(errors, errors)
            finally:
                await browser.close()

    @skipUnless(os.getenv('PREDICT_PREGAME_BROWSER'), 'Opt in with disposable PostgreSQL and Playwright')
    async def test_open_browser_observes_price_publication_and_kickoff(self):
        from playwright.async_api import async_playwright, expect

        raw, event = self.raw()
        self.kickoff = self.at + timedelta(hours=4)
        event['status']['startsAt'] = self.kickoff.isoformat()
        home, _ = self.sides(event)
        self.admit_page(raw)
        self.publish()
        async with self.browser_server() as server, async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=os.getenv('PREDICT_CI_CHROMIUM'))
            tab = await browser.new_page()
            await tab.clock.install(time=self.at)
            base = str(server.make_url('/')).rstrip('/')

            def is_list(response):
                return API + '?' in response.url

            def has_filter(response, name, value=None):
                values = parse_qs(urlsplit(response.url).query).get(name, ())
                return is_list(response) and (value in values if value is not None else bool(values))

            async def navigate(path, *, has_rows=True):
                started = monotonic()
                mode = 'browse_odds' if path == '/browse-odds' else 'ranked'
                async with tab.expect_response(lambda response: has_filter(response, mode, '1')) as request:
                    await tab.goto(base + path)
                response = await request.value
                self.assertEqual(response.status, 200)
                page = await response.json()
                self.assertEqual(bool(page['rows']), has_rows, (response.url, page.get('offer_count'),
                    page.get('coverage'), page.get('calculation_missing'), page.get('generation')))
                print(f"{path}: HTTP {response.status}, {monotonic()-started:.3f}s browser, "
                      f"generation {page['generation']}, {page['offer_count']} offers, "
                      f"{response.headers.get('server-timing')}")
                return page

            baseline = await navigate('/ev', has_rows=False)
            await expect(tab.get_by_label('Calculation basis')).to_be_hidden()
            await expect(tab.get_by_role('heading', name='Choose a unit size to rank offers after fees.')).to_be_visible()
            async with tab.expect_response(lambda response: has_filter(response, 'unit_usd', '25.00')) as request:
                await tab.get_by_label('Unit size').select_option('25.00')
            self.assertEqual((await (await request.value).json())['state'], 'valuation_pending')
            self.publish()
            await tab.get_by_role('button', name='Refresh list').click()
            await expect(tab.get_by_role('heading', name='No offers qualify for Net EV at this unit size.')).to_be_visible()
            await expect(tab.locator('#results').get_by_role('link', name='Browse Odds')).to_be_visible()
            await expect(tab.locator('#notice')).to_contain_text('Odds may be delayed.')
            await navigate('/browse-odds')
            self.at += timedelta(hours=3)
            await tab.clock.fast_forward(3 * 3600 * 1000)
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
            await drawer.get_by_text('Calculation details', exact=True).click()
            await expect(drawer.get_by_text('Named sportsbook reference', exact=True)).to_be_visible()
            await expect(drawer.get_by_text('Settlement assessment', exact=True)).to_be_visible()

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
