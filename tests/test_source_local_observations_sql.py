"""Source-local native prices survive incomplete comparison context.

All source responses/books are authored fake transport. SQL tests require the
maintained explicitly disposable PostgreSQL lane; none touches owner SQL,
runtime/configuration, credentials or providers. Real workers, admission, SQL,
background publication and the ordinary Odds/inputs API run without event lists.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, skipUnless
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.collection.current_native import NativeWorker
from app.collection.current_policy import DEFAULT, validate
from app.collection.runtime_client import RuntimeClient
from app.comparison.combined_native import normalize
from app.comparison.event_links import provider_key
from app.storage import latest_board as latest
from app.storage.current_rows import CurrentRowStore
from tests import test_latest_board_sql as sql_fixtures, test_multisport_pipeline_sql as multisport_sql
from tests.multisport_fixtures import SPORTS, FAMILIES, current_book, fake_discovery, source_case
from tests.source_local_fixtures import member, restore_context, source_local_case


VENUES = ('kalshi', 'polymarket_us')


class SourceLocalAdmission(IsolatedAsyncioTestCase):
    async def test_source_linked_spread_uses_own_scheduled_main_game_witness(self):
        case=source_local_case('NBA','spread',uuid4().hex[:10])
        case['milestone']['details']['main_game_event_ticker']='authored-linked-main'
        case['milestone']['related_event_tickers'].append('authored-linked-main')
        published=[];config=validate(dict(deepcopy(DEFAULT),native_sports=['NBA'],native_families=['spread'],aggregate_enabled=False))
        service=SimpleNamespace(config=config,dispatch=True,catalog=lambda _,value:published.append(deepcopy(value)),
            issue=lambda *args:None,source_state=lambda *args:None)
        worker=NativeWorker(service,'kalshi');self.addAsyncCleanup(worker.close)
        fake_discovery(worker,[case]);await worker.discover()
        book=current_book(case,'kalshi');at=book['raw']['received_at']
        rows,excluded=normalize(dict(id='authored-catalog',record=dict(source='kalshi',value=dict(inventory=published[-1]))),
            [dict(id='authored-book',record=dict(retained_at=at,value=dict(observations=[dict(type='prediction_book',source='kalshi',observed_at=at,book=book)])))],at=at)
        self.assertFalse(excluded);self.assertEqual(len(rows),2)
        for row in rows:
            meta=row['comparison_source_metadata']
            self.assertEqual(meta['phase'],'pregame')
            self.assertEqual(meta['combined_native_binding']['phase_facts'][0]['main_game_event_ticker'],'authored-linked-main')
            self.assertEqual(row['quote']['times']['source_at'],book['raw']['exchange_at'])

    async def test_generated_missing_context_matrix_retains_original_native_inputs(self):
        """Exercise every parser/type before SQL, using the ordinary reducer."""
        for league in SPORTS:
            for family in FAMILIES:
                for venue in VENUES:
                    with self.subTest(league=league, family=family, venue=venue):
                        case = source_local_case(league, family, uuid4().hex[:10])
                        published = []
                        config = validate(dict(deepcopy(DEFAULT), native_sports=[league],
                                               native_families=[family], aggregate_enabled=False))
                        service = SimpleNamespace(config=config, dispatch=True,
                            catalog=lambda _, value: published.append(deepcopy(value)),
                            issue=lambda *args: None, source_state=lambda *args: None)
                        worker = NativeWorker(service, venue)
                        self.addAsyncCleanup(worker.close)
                        cases = []
                        calls = fake_discovery(worker, cases)
                        await worker.discover()
                        self.assertFalse(worker.markets)
                        cases.append(case)
                        await worker.discover()
                        self.assertEqual(len(worker.markets), 1)
                        book = current_book(case, venue, price='0.487')
                        at = book['raw']['received_at']
                        observations = [dict(type='prediction_book', source=venue,
                                             observed_at=at, book=book)]
                        rows, excluded = normalize(dict(id='fake-source-catalog', record=dict(
                            source=venue, value=dict(inventory=published[-1]))),
                            [dict(id='fake-source-book', record=dict(retained_at=at,
                                  value=dict(observations=observations)))], at=at,
                            include_missing=True)
                        self.assertEqual(excluded, [])
                        self.assertEqual(len(rows), 2)
                        for row in rows:
                            self.assertIsNone(row['event']['season'])
                            self.assertIsNone(row['event']['stage'])
                            self.assertEqual(row['event']['competition'], league)
                            self.assertEqual(row['event']['scheduled_start'], case['event']['scheduled_start'])
                            self.assertEqual(row['market_identity']['event'], provider_key(venue, row['event']))
                            self.assertFalse(row['verified'])
                            self.assertEqual(row['event_scope'], dict(policy='native-event-unverified-2',
                                source=venue, native_event_id=member(case, venue)[1]))
                            admission = row['comparison_source_metadata']['comparison_admission']
                            self.assertFalse(admission['supported'])
                            self.assertEqual(admission['reason'], 'comparison_context_missing')
                            self.assertTrue({'season', 'stage'} <= set(admission['missing_fields']))
                            self.assertEqual(row['quote']['original']['value'], '0.487')
                            self.assertEqual(row['quote']['times']['source_at'], book['raw']['exchange_at'])
                            self.assertEqual(row['quote']['times']['received_at'], book['raw']['received_at'])
                            self.assertEqual(row['quote']['depth'], [dict(price='0.487', quantity='10')])
                        self.assertTrue(calls)

    async def test_provider_event_key_keeps_namespace_and_ignores_later_optional_context(self):
        event = dict(id='same-native-id', competition='MLB', home='MLB:BOS', away='MLB:NYY',
                     scheduled_start='2026-10-20T20:00:00+00:00', season=None, stage=None)
        first = provider_key('kalshi', event)
        self.assertNotEqual(first, provider_key('polymarket_us', event))
        self.assertNotEqual(first, provider_key('kalshi', dict(event, id='different-native-id')))
        self.assertEqual(first, provider_key('kalshi', dict(event, season='2026', stage='regular_season')))


@skipUnless(sql_fixtures.SOCKET, 'Explicit disposable source-local PostgreSQL lane required')
class SourceLocalObservationsSQL(IsolatedAsyncioTestCase):
    connect = classmethod(sql_fixtures.LatestBoardSQL.connect.__func__)
    setUpClass = classmethod(sql_fixtures.LatestBoardSQL.setUpClass.__func__)
    tearDownClass = classmethod(sql_fixtures.LatestBoardSQL.tearDownClass.__func__)
    asyncSetUp = multisport_sql.AutomaticMultisportSQL.asyncSetUp

    async def api(self):
        from app.dashboard.comparison_board_api import mount
        app = web.Application()
        mount(app, RuntimeClient(connector=self.connect))
        client = TestClient(TestServer(app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        return client

    def records(self):
        with self.connect() as db:
            return CurrentRowStore(db).capture()['records']

    async def test_shared_event_context_arrives_before_every_contract_rebinds(self):
        case=source_local_case('NBA','moneyline',uuid4().hex[:10],clock=datetime.now(timezone.utc))
        await self.ingress([case])
        expected={member(case,venue) for venue in VENUES}
        _,before=await self.published(expected,prices=4)
        originals={tuple(q['source'][k] for k in ('provider','native_event_id','native_outcome_id')):
            (q['original'],q['times']) for board in before.values() for q in board['prices']}
        record=next(r for r in self.records() if r['quote']['venue']=='kalshi')
        record['event'].update(season='2026-2027',stage='regular_season')
        record['market_identity'].update(season='2026-2027',stage='regular_season')
        record['comparison_source_metadata'].pop('comparison_admission')
        record['verified']=True;record['event_scope']['policy']='native-provider-event-1'
        with self.connect() as db:CurrentRowStore(db).upsert_records([record])
        self.owner.wake.set()
        def updated(prices):
            return all('source_observation_changed' not in q['freshness']['reasons']
                and not q['observation_display']['publication_reason_codes'] for q in prices)
        _,after=await self.published(expected,prices=4,accept=updated)
        with self.connect() as db:
            catalog=latest.read_context(db).catalog()
            self.assertEqual(catalog.get('provider_requests'),0)
            self.assertTrue(any(r['event']['season']=='2026-2027' and r['market_identity']['season'] is None
                for r in CurrentRowStore(db).capture()['records'] if r['quote']['venue']=='kalshi'))
        client=await self.api();rendered=await self.read_boards(client,after)
        self.assert_unavailable(rendered)
        for board in rendered.values():
            for q in board['prices']:
                key=tuple(q['source'][k] for k in ('provider','native_event_id','native_outcome_id'))
                self.assertEqual((q['original'],q['times']),originals[key])
                await self.inputs(client,board,q)

    async def test_future_postponed_prices_survive_without_current_pregame_authority(self):
        case=source_local_case('NBA','moneyline',uuid4().hex[:10],clock=datetime.now(timezone.utc))
        await self.ingress([case]);expected={member(case,venue) for venue in VENUES}
        await self.published(expected,prices=4)
        records=self.records()
        for row in records:row['event']['status']=dict(status='postponed')
        with self.connect() as db:CurrentRowStore(db).upsert_records(records)
        self.owner.wake.set()
        def postponed(prices):
            return all('event_postponed' in q['freshness']['reasons'] for q in prices)
        _,boards=await self.published(expected,prices=4,accept=postponed)
        self.assert_unavailable(boards)
        for board in boards.values():
            for q in board['prices']:
                self.assertEqual(q['freshness']['status'],'historical')
                self.assertTrue(q['observed_depth']['available'])

    def sql_identities(self):
        with self.connect() as db:
            return dict(events={(r['provider'], r['native_event_id']): r['id']
                for r in db.execute('SELECT id,provider,native_event_id FROM current_event')},
                contracts={(r['venue'], r['native_market_id'], r['native_outcome_id'], r['native_side']): r['id']
                for r in db.execute('SELECT id,venue,native_market_id,native_outcome_id,native_side FROM current_contract')})

    async def ingress(self, cases):
        workers = {venue: NativeWorker(self.service, venue) for venue in VENUES}
        calls = {venue: fake_discovery(worker, []) for venue, worker in workers.items()}
        for worker in workers.values():
            self.addAsyncCleanup(worker.close)
            await worker.discover()
        self.assertEqual(self.records(), [])
        # New source identities appear after both actual background owners start.
        for venue, worker in workers.items():
            calls[venue] = fake_discovery(worker, cases)
            await worker.discover()
            self.assertEqual(len(worker.markets), len(cases), worker.catalog.get('excluded_catalog'))
            for case in cases:
                book = current_book(case, venue, price='0.48' if venue == 'kalshi' else '0.53')
                try:
                    self.service.book(venue, book)
                except ValueError:
                    self.fail((venue, self.service.sink.error, self.service.sink.exclusions))
        self.state.write(self.service)
        self.owner.wake.set()
        return workers, calls

    async def published(self, expected, *, prices, accept=None):
        """Observe publication before any page request; HTTP cannot create it."""
        for _ in range(100):
            with self.connect() as db:
                frame = latest.snapshot(db)
            games = [g for g in frame['status'].get('games', [])
                     if set(map(tuple, g['members'])) & expected]
            boards = {g['game_key']: latest.board(frame, g['game_key'], view='odds', filter='all')
                      for g in games if g['game_key'] in frame['rows']}
            rows = [q for board in boards.values() for q in board['prices']]
            if len(rows) == prices and {tuple((q['source']['provider'], q['source']['native_event_id']))
                                        for q in rows} == expected and (accept is None or accept(rows)):
                return games, boards
            await asyncio.sleep(.1)
        self.fail((self.owner.observation_error, self.owner.estimate_error,
                   frame['status'].get('observation_errors'), frame['status'].get('games')))

    async def read_boards(self, client, boards):
        out = {}
        for key in boards:
            reply = await client.get('/api/boards/odds', params=dict(game=key, filter='all'))
            self.assertEqual(reply.status, 200, await reply.text())
            out[key] = await reply.json()
            self.assertEqual(out[key]['provider_requests'], 0)
        return out

    async def inputs(self, client, board, selected):
        reply = await client.get('/api/boards/inputs', params=dict(game=board['game_key'],
            quote=selected['quote_id'], context_id=selected['inputs_identity']['context_id']))
        self.assertEqual(reply.status, 200, await reply.text())
        result = await reply.json()
        self.assertEqual(result['provider_requests'], 0)
        self.assertEqual(result['evidence']['source'], selected['source'])
        self.assertEqual(result['evidence']['original'], selected['original'])
        self.assertEqual(result['evidence']['times'], selected['times'])
        self.assertEqual(result['evidence']['depth'], selected['observed_depth']['levels'])
        return result

    def assert_unavailable(self, boards):
        prices = [q for board in boards.values() for q in board['prices']]
        self.assertTrue(prices)
        self.assertFalse(any(q['current_comparison']['available'] for q in prices))
        self.assertFalse(any(q['gross_comparison']['available'] for q in prices))

    async def missing_context_case(self, league, family):
        case = source_local_case(league, family, uuid4().hex[:10], clock=datetime.now(timezone.utc))
        workers, calls = await self.ingress([case])
        records = self.records()
        self.assertEqual(len(records), 4)
        for row in records:
            venue = row['quote']['venue']
            self.assertEqual(row['market_identity']['event'], provider_key(venue, row['event']))
            self.assertIsNone(row['event']['season'])
            self.assertIsNone(row['event']['stage'])
            self.assertEqual(row['event']['scheduled_start'], case['event']['scheduled_start'])
            self.assertEqual(row['event']['home'], case['event']['home'])
            self.assertEqual(row['event']['away'], case['event']['away'])
            self.assertFalse(row['verified'])
            admission = row['comparison_source_metadata']['comparison_admission']
            self.assertEqual(admission['reason'], 'comparison_context_missing')
            self.assertTrue({'season', 'stage'} <= set(admission['missing_fields']))
        expected = {member(case, venue) for venue in VENUES}
        games, stored = await self.published(expected, prices=4)
        self.assertEqual(len(games), 2)
        self.assertTrue(all(len(g['members']) == 1 for g in games))
        self.assert_unavailable(stored)
        counts = {venue: len(value) for venue, value in calls.items()}
        client = await self.api()
        rendered = await self.read_boards(client, stored)
        self.assert_unavailable(rendered)
        for board in rendered.values():
            for quote in board['prices']:
                self.assertEqual(quote['event']['league'], league)
                self.assertEqual(quote['market']['market'], 'winner' if family == 'moneyline' else family)
                self.assertEqual(quote['original']['value'], '0.48' if quote['venue'] == 'kalshi' else '0.53')
                self.assertEqual(quote['observed_depth']['levels'], [dict(price=quote['original']['value'], quantity='10')])
                self.assertFalse(quote['same_outcome']['supported'])
                self.assertEqual(quote['same_outcome']['reason'], 'comparison_context_missing')
                await self.inputs(client, board, quote)
        self.assertEqual({venue: len(value) for venue, value in calls.items()}, counts)
        self.assertNotIn('the_odds_api', self.service.workers)
        return dict(case=case, workers=workers, calls=calls, client=client,
                    games=games, boards=rendered, identities=self.sql_identities())

    async def test_mlb_later_context_keeps_local_game_and_frozen_native_observation(self):
        original = source_case('MLB', 'total', uuid4().hex[:10])
        case = source_local_case('MLB', 'total', original['token'], clock=original['clock'],
                                 missing_occurrence=True)
        workers, calls = await self.ingress([case])
        expected = {member(case, venue) for venue in VENUES}
        games, before = await self.published(expected, prices=4)
        self.assertEqual(len(games), 2)
        identities = self.sql_identities()
        client = await self.api()
        before = await self.read_boards(client, before)
        old_inputs = []
        for board in before.values():
            old_inputs.append(await self.inputs(client, board, board['prices'][0]))
        frozen = deepcopy(old_inputs)
        originals = {tuple(q['source'][k] for k in ('provider', 'native_event_id', 'native_outcome_id')):
                     (q['original'], q['times']) for board in before.values() for q in board['prices']}
        # A later ordinary rediscovery brings explicit season/stage, but not the
        # missing MLB original-occurrence facts. A changed metadata binding may
        # require a fresh source image; rediscovery cannot renew a held clock.
        restore_context(case, original)
        for worker in workers.values():
            await worker.discover()
        for row in self.records():
            source = row['quote']['source']
            key = tuple(source[k] for k in ('provider', 'native_event_id', 'native_outcome_id'))
            old_original, old_times = originals[key]
            self.assertEqual(row['quote']['original'], old_original)
            self.assertEqual({k: row['quote']['times'][k] for k in ('source_at', 'received_at')},
                             {k: old_times[k] for k in ('source_at', 'received_at')})
        fresh = {}
        for venue in VENUES:
            book = current_book(case, venue, price='0.48' if venue == 'kalshi' else '0.53')
            fresh[venue] = book
            self.service.book(venue, book)
        self.state.write(self.service)
        self.owner.wake.set()
        for _ in range(100):
            records = self.records()
            if len(records) == 4 and all(r['event'].get('season') == original['event']['season']
                                        for r in records):
                break
            await asyncio.sleep(.1)
        self.assertTrue(all(r['event'].get('season') == original['event']['season'] for r in records))
        self.assertTrue(all(r['event'].get('stage') == 'regular_season' for r in records))
        self.assertEqual(self.sql_identities(), identities)
        _, after = await self.published(expected, prices=4, accept=lambda rows: all(
            q['times']['received_at'] == fresh[q['venue']]['raw']['received_at'] for q in rows))
        self.assertEqual(set(before), set(after))
        self.assert_unavailable(after)
        for board in after.values():
            for quote in board['prices']:
                book = fresh[quote['venue']]
                self.assertEqual(quote['times']['source_at'], book['raw']['exchange_at'])
                self.assertEqual(quote['times']['received_at'], book['raw']['received_at'])
        self.assertEqual(old_inputs, frozen)
        self.assertTrue(all(calls.values()))

    async def test_full_context_later_keeps_sql_native_ids_and_old_inputs_detached(self):
        setup = await self.missing_context_case('NBA', 'spread')
        case = setup['case']
        original = source_case('NBA', 'spread', case['token'], clock=case['clock'])
        before = deepcopy(setup['boards'])
        restore_context(case, original)
        for worker in setup['workers'].values():
            await worker.discover()
        # Metadata completion can revoke an old book binding. Only this new
        # authored source image may provide a new price/receipt clock.
        fresh = {}
        for venue in VENUES:
            fresh[venue] = current_book(case, venue,
                price='0.48' if venue == 'kalshi' else '0.53')
            self.service.book(venue, fresh[venue])
        self.state.write(self.service)
        self.owner.wake.set()
        for _ in range(100):
            rows = self.records()
            if len(rows) == 4 and all(r['event'].get('stage') == 'regular_season' for r in rows):
                break
            await asyncio.sleep(.1)
        self.assertTrue(all(r['event'].get('stage') == 'regular_season' for r in rows))
        self.assertEqual(self.sql_identities(), setup['identities'])
        expected = {member(case, venue) for venue in VENUES}
        await self.published(expected, prices=4, accept=lambda rows: all(
            q['times']['received_at'] == fresh[q['venue']]['raw']['received_at'] for q in rows))
        # A newly justified derived match may change the current group, but a
        # saved old response never gains that match or newly computed finance.
        self.assertEqual(setup['boards'], before)
        self.assert_unavailable(before)
        for board in before.values():
            selected = board['prices'][0]
            reply = await setup['client'].get('/api/boards/inputs', params=dict(
                game=board['game_key'], quote=selected['quote_id'],
                context_id=selected['inputs_identity']['context_id']))
            self.assertEqual(reply.status, 409, await reply.text())
            self.assertEqual((await reply.json())['provider_requests'], 0)

    async def test_distinct_same_team_native_games_are_not_merged(self):
        clock = datetime.now(timezone.utc)
        cases = [source_local_case('MLB', 'moneyline', uuid4().hex[:10], clock=clock,
                                   missing_occurrence=True) for _ in range(2)]
        await self.ingress(cases)
        self.assertEqual(len(self.records()), 8)
        identities = self.sql_identities()
        self.assertEqual(len(identities['events']), 4)
        expected = {member(case, venue) for case in cases for venue in VENUES}
        games, boards = await self.published(expected, prices=8)
        self.assertEqual(len(games), 4)
        self.assertTrue(all(len(g['members']) == 1 for g in games))
        self.assert_unavailable(boards)

    async def test_conflicting_explicit_context_does_not_borrow_peer_qualification(self):
        case = source_case('NBA', 'total', uuid4().hex[:10])
        case['milestone']['details']['season'].pop('type')
        case['events']['polymarket_us']['season'] = '2027'
        await self.ingress([case])
        self.assertEqual(len(self.records()), 4)
        expected = {member(case, venue) for venue in VENUES}
        games, boards = await self.published(expected, prices=4)
        self.assertEqual(len(games), 2)
        self.assert_unavailable(boards)
        records = self.records()
        self.assertTrue(all(r['event']['stage'] is None for r in records if r['quote']['venue'] == 'kalshi'))
        self.assertTrue(all(r['event']['season'] == '2027' for r in records if r['quote']['venue'] == 'polymarket_us'))

    async def test_source_aging_and_stop_preserve_original_inputs_without_dispatch(self):
        setup = await self.missing_context_case('NFL', 'moneyline')
        counts = {venue: len(value) for venue, value in setup['calls'].items()}
        original = deepcopy(setup['boards'])
        future = datetime.now(timezone.utc) + timedelta(seconds=31)
        with self.connect() as db:
            aged = latest.snapshot(db, at=future.isoformat())
        for key, before in original.items():
            after = latest.board(aged, key, view='odds', filter='all')
            self.assertEqual([(q['original'], q['times']) for q in after['prices']],
                             [(q['original'], q['times']) for q in before['prices']])
            self.assertTrue(all(q['freshness']['status'] == 'historical' for q in after['prices']))
            self.assertFalse(any(q['current_comparison']['available'] for q in after['prices']))
        self.service.dispatch = False
        self.state.write(self.service)
        stopped = await self.read_boards(setup['client'], setup['boards'])
        self.assert_unavailable(stopped)
        for key, board in stopped.items():
            self.assertTrue(all(q['freshness']['status'] == 'historical' for q in board['prices']))
            self.assertEqual([(q['original'], q['times']) for q in board['prices']],
                             [(q['original'], q['times']) for q in original[key]['prices']])
        self.assertEqual({venue: len(value) for venue, value in setup['calls'].items()}, counts)
        self.assertNotIn('the_odds_api', self.service.workers)


def matrix_test(league, family):
    async def test(self):
        await self.missing_context_case(league, family)
    return test


for _league in SPORTS:
    for _family in FAMILIES:
        setattr(SourceLocalObservationsSQL, 'test_missing_context_' + _league + '_' + _family,
                matrix_test(_league, _family))
