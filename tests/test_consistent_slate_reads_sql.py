"""Authored multi-page Odds reads while real disposable-SQL owners publish.

Both native workers use fake discovery/book transport and unchanged source caps.
Four bounded batches accumulate 60 authored occurrences across six leagues and
three families. No owner database, configuration, credentials or provider is used.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.collection.current_native import NativeWorker
from app.collection.runtime_client import RuntimeClient
from app.storage import latest_board as latest
from app.storage.current_rows import CurrentRowStore
from tests import test_latest_board_sql as sql_fixtures
from tests import test_multisport_pipeline_sql as multisport_sql
from tests.multisport_fixtures import SPORTS, FAMILIES, current_book, fake_discovery, source_case


VENUES = ('kalshi', 'polymarket_us')
# This lane verifies read identity, paging and eviction, not a machine's speed.
# Production response deadlines are exercised in test_selected_read_work.py.
SEMANTIC_READ_SECONDS = 30


@skipUnless(sql_fixtures.SOCKET, 'Explicit disposable consistent-read PostgreSQL lane required')
class ConsistentSlateReadsSQL(IsolatedAsyncioTestCase):
    connect = classmethod(sql_fixtures.LatestBoardSQL.connect.__func__)
    setUpClass = classmethod(sql_fixtures.LatestBoardSQL.setUpClass.__func__)
    tearDownClass = classmethod(sql_fixtures.LatestBoardSQL.tearDownClass.__func__)
    asyncSetUp = multisport_sql.AutomaticMultisportSQL.asyncSetUp

    async def api(self):
        from app.dashboard.comparison_board_api import mount, READ_WORK
        app = web.Application()
        mount(app, RuntimeClient(connector=self.connect))
        app[READ_WORK].work_seconds = SEMANTIC_READ_SECONDS
        client = TestClient(TestServer(app))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        return client, app

    async def publication(self, count, *, accepts=None):
        def capture():
            with self.connect() as db:
                return latest.snapshot(db)
        for _ in range(300):
            # Polling must not block HTTP completion or the runtime heartbeat.
            frame = await asyncio.to_thread(capture)
            games = frame['status'].get('games', [])
            if len(games) == count and len(frame['rows']) == count and (accepts is None or accepts(frame)):
                return frame
            await asyncio.sleep(.1)
        self.fail(dict(games=len(games), rows=len(frame['rows']),
            observation_error=self.owner.observation_error, estimate_error=self.owner.estimate_error,
            errors=frame['status'].get('observation_errors')))

    async def page(self, client, previous=None, *, changes=None, status=200):
        query = dict(view='odds', filter='all', offset='0', limit='50')
        if previous is not None:
            query.update(offset=str(previous['coverage']['next_offset']),
                expected_revision=previous['read_revision'], read_token=previous['read_token'])
        query.update(changes or {})
        reply = await client.get('/api/boards/slate', params=query)
        result = await reply.json()
        self.assertEqual(reply.status, status, result)
        self.assertEqual(result['provider_requests'], 0)
        return result

    def ingress_books(self, workers, cases, *, price=None, generation=1):
        for venue, worker in workers.items():
            worker.metrics['connections'] = generation
            worker.lifecycle.begin_connection(generation)
            for case in cases:
                worker.queue_book(current_book(case, venue, clock=case['clock'],
                    price=price or ('0.48' if venue == 'kalshi' else '0.53')))
            worker.flush_books()
            self.assertIsNone(self.service.sink.error)
        self.state.write(self.service)
        self.owner.wake.set()

    def client_accumulator(self, pages):
        """Use the ordinary browser helper on the actual HTTP/SQL wire bodies."""
        harness = r"""
const fs = require('node:fs'), assert = require('node:assert/strict');
const path = require('node:path'), {pathToFileURL} = require('node:url');
(async () => {
  const pages = JSON.parse(fs.readFileSync(0, 'utf8'));
  const asset = name => pathToFileURL(path.resolve('app/dashboard/opportunity_static/current', name)).href;
  const moduleURL = asset('board-client.js');
  const {defaults, LatestRead, readSlate} = await import(moduleURL);
  const {relativeAge, observationState} = await import(asset('board-elements.js'));
  let index = 0;
  const requests = [];
  const reader = new LatestRead(async url => {
    const query = new URL(url, 'http://127.0.0.1').searchParams;
    assert(url.startsWith('/api/boards/slate?'));
    assert.equal(query.get('offset'), String(pages[index].coverage.offset));
    assert.equal(query.get('limit'), '50');
    if (index) {
      assert.equal(query.get('read_token'), pages[0].read_token);
      assert.equal(query.get('expected_revision'), pages[0].read_revision);
    } else assert.equal(query.has('read_token'), false);
    requests.push(url);
    return new Response(JSON.stringify(pages[index++]), {status: 200});
  });
  const value = await readSlate(reader, {...defaults, view: 'odds', filter: 'all'});
  assert.equal(value.coverage.complete, true);
  assert.equal(value.coverage.returned_games, pages[0].games.length);
  assert.equal(new Set(value.boards.map(b => b.game_key)).size, pages[0].games.length);
  assert.equal(value.coverage.page_count, pages.length);
  assert.equal(index, pages.length);
  const price = value.boards[0].prices[0], frozen = JSON.stringify(price);
  const instant = Date.parse(price.times.source_at);
  assert.equal(relativeAge(price.times.source_at, instant + 2000), '2s old');
  assert.equal(relativeAge(price.times.source_at, instant + 32000), '32s old');
  if (['current', 'pending'].includes(price.observation_display?.state) && price.observation_display.current_until)
    assert.equal(observationState(price, Date.parse(price.observation_display.current_until) + 1), 'last_known');
  assert.equal(JSON.stringify(price), frozen, 'age formatting does not mutate original prices or clocks');
  console.log(JSON.stringify({games: value.games.length, pages: index, provider_requests: 0, local_requests: requests.length}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run(['node', '-e', harness], input=json.dumps(pages), text=True,
            capture_output=True, cwd=Path(__file__).resolve().parents[1], timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['games'], pages[0]['coverage']['total_games'])

    async def test_sixty_games_complete_despite_books_and_publication_changes(self):
        cases = []
        workers = {venue: NativeWorker(self.service, venue) for venue in VENUES}
        calls = {venue: fake_discovery(worker, cases) for venue, worker in workers.items()}
        for worker in workers.values():
            self.addAsyncCleanup(worker.close)
            await worker.discover()
        with self.connect() as db:
            self.assertEqual(CurrentRowStore(db).capture()['records'], [])

        # Real source limits remain 20 markets/24 events/36 pages. Distinct SQL
        # occurrences accumulate through recurring bounded worker discovery.
        clock = datetime.now(timezone.utc) - timedelta(seconds=2)
        authored = [source_case(SPORTS[index % len(SPORTS)],
            FAMILIES[(index // len(SPORTS)) % len(FAMILIES)], uuid4().hex[:10], clock=clock)
            for index in range(60)]
        for generation, offset in enumerate(range(0, len(authored), 15), 1):
            cases[:] = authored[offset:offset + 15]
            for worker in workers.values():
                await worker.discover()
                self.assertEqual(len(worker.markets), len(cases))
                self.assertLessEqual(len(worker.markets), self.config['markets_per_source'])
            self.ingress_books(workers, cases, generation=generation)
            await self.publication(offset + len(cases))
        initial = await self.publication(60)
        # A page decodes only its requested stored view; projection preserves
        # exactly the same source clocks, aging and dependency assessments.
        with self.connect() as db:
            full = latest.snapshot(db)
            projected = latest.snapshot(db, at=full['at'], view='odds')
        for key in full['rows']:
            self.assertEqual(set(projected['rows'][key]['facts']['boards']), {'odds'})
            self.assertEqual(latest.board(projected,key,view='odds',filter='all'),
                latest.board(full,key,view='odds',filter='all'))
        self.assertEqual({game['league'] for game in initial['status']['games']}, set(SPORTS))
        with self.connect() as db:
            admitted = CurrentRowStore(db).capture()['records']
        self.assertEqual(len(admitted), 240)
        self.assertEqual({record['market_identity']['family'] for record in admitted}, set(FAMILIES))
        client, _ = await self.api()
        first = await self.page(client)
        self.assertEqual(first['coverage']['total_games'], 60)
        self.assertEqual(first['coverage']['returned_games'], 50)
        self.assertFalse(first['coverage']['complete'])
        self.assertEqual(len(first['games']), 60)
        selected_board = first['boards'][0]
        selected = selected_board['prices'][0]
        old_selection = dict(game=selected_board['game_key'], quote=selected['quote_id'],
            context_id=selected['inputs_identity']['context_id'])
        reply = await client.get('/api/boards/inputs', params=old_selection)
        if reply.status != 200:
            from app.storage.comparison_board import observation_identity
            with self.connect() as db:
                diagnostic = latest.snapshot(db)
                context = latest.read_context(db)
                bundle = context.observation_bundles(game=selected_board['game_key'])[0]
                self.fail(dict(response=await reply.json(),
                    selected=old_selection, current=observation_identity(bundle, context),
                    saved=diagnostic['rows'][selected_board['game_key']]['facts']['observation_context'],
                    observation_reasons=selected_board['observation_reasons']))
        frozen_inputs = await reply.json()
        self.assertEqual(frozen_inputs['provider_requests'], 0)
        self.assertEqual(frozen_inputs['evidence']['original'], selected['original'])
        self.assertEqual(frozen_inputs['evidence']['times'], selected['times'])
        frozen_copy = deepcopy(frozen_inputs)

        # Slow runners can cross the native 30-second age boundary between a
        # publication and Details. The same original remains inspectable, with
        # truthful expired freshness, until its actual source facts change.
        def aged_context(*args, **kwargs):
            context=latest.read_context(*args, **kwargs)
            context.at=(datetime.fromisoformat(context.at)+timedelta(seconds=31)).isoformat()
            return context
        with patch('app.dashboard.comparison_board_api.read_context',side_effect=aged_context):
            aged_reply=await client.get('/api/boards/inputs',params=old_selection)
            aged_inputs=await aged_reply.json()
        self.assertEqual(aged_reply.status,200,aged_inputs)
        self.assertEqual(aged_inputs['evidence']['original'],selected['original'])
        self.assertEqual(aged_inputs['evidence']['times'],selected['times'])
        self.assertIn('source_expired',aged_inputs['evidence']['freshness']['reasons'])

        # Change an already selected actual source book, and admit a new game,
        # after page one. The same background publisher, not HTTP, owns both.
        selected_event = selected['source']['native_event_id']
        changed = next(case for case in authored if selected_event in
            (case['events']['kalshi']['event_ticker'], case['events']['polymarket_us']['id']))
        late = source_case('NHL', 'total', uuid4().hex[:10], clock=datetime.now(timezone.utc))
        cases[:] = [changed, late]
        for worker in workers.values():
            await worker.discover()
        original_clock = changed['clock']
        changed['clock'] = datetime.now(timezone.utc)
        self.ingress_books(workers, cases, price='0.67', generation=5)
        changed['clock'] = original_clock

        def changed_published(frame):
            game = selected_board['game_key']
            return any(price['original']['value'] == '0.67'
                for price in latest.board(frame, game, view='odds', filter='all')['prices'])

        published = await self.publication(61, accepts=changed_published)
        self.assertNotEqual(published['read_revision'], first['read_revision'])
        calls_after_ingress = {venue: len(value) for venue, value in calls.items()}
        # Captured prices/receipt clocks cannot silently change while the age
        # projection continues forward. A token cannot authorize frozen Details.
        repeated_first = await self.page(client, changes=dict(read_token=first['read_token'],
            expected_revision=first['read_revision']))
        old_quote = next(price for board in repeated_first['boards'] for price in board['prices']
            if price['quote_id'] == selected['quote_id'])
        self.assertEqual(old_quote['original'], selected['original'])
        self.assertEqual(old_quote['times'], selected['times'])
        self.assertGreaterEqual(old_quote['observation_display']['source_age_seconds'],
            selected['observation_display']['source_age_seconds'])
        self.assertEqual(frozen_inputs, frozen_copy)
        reply = await client.get('/api/boards/inputs', params=old_selection)
        self.assertEqual(reply.status, 409, await reply.text())
        refusal = await reply.json()
        self.assertEqual(refusal['provider_requests'], 0)
        self.assertEqual(refusal['reason'], 'current_inputs_changed_or_removed')

        pages = [first]
        while pages[-1]['coverage']['next_offset'] is not None:
            pages.append(await self.page(client, pages[-1]))
        self.assertEqual([page['coverage']['returned_games'] for page in pages], [50, 10])
        captured_keys = [board['game_key'] for page in pages for board in page['boards']]
        self.assertEqual(len(captured_keys), 60)
        self.assertEqual(len(set(captured_keys)), 60)
        self.assertEqual(set(captured_keys), {game['game_key'] for game in first['games']})
        for page in pages:
            for field in ('read_token', 'read_revision', 'read_at', 'as_of', 'epoch', 'games'):
                self.assertEqual(page[field], first[field])
            self.assertEqual(page['errors'], [])
        await asyncio.to_thread(self.client_accumulator, pages)

        fresh = await self.page(client)
        self.assertNotEqual(fresh['read_token'], first['read_token'])
        self.assertEqual(fresh['coverage']['total_games'], 61)
        self.assertEqual(len({game['game_key'] for game in fresh['games']} - set(captured_keys)), 1)
        fresh_pages = [fresh]
        while fresh_pages[-1]['coverage']['next_offset'] is not None:
            fresh_pages.append(await self.page(client, fresh_pages[-1]))
        self.assertEqual(len({board['game_key'] for page in fresh_pages for board in page['boards']}), 61)
        new_quote = next(price for page in fresh_pages for board in page['boards']
            for price in board['prices'] if price['quote_id'] == selected['quote_id'])
        self.assertEqual(new_quote['original']['value'], '0.67')
        self.assertNotEqual(new_quote['times']['received_at'], selected['times']['received_at'])
        await asyncio.to_thread(self.client_accumulator, fresh_pages)

        crossed = await self.page(client)
        for changes in (dict(view='ev'), dict(filter='positive'), dict(amount='71'),
                dict(limit='20'), dict(expected_revision=first['read_revision'])):
            result = await self.page(client, crossed, changes=changes, status=409)
            self.assertEqual(result['reason'], 'current_slate_read_context_changed')
        missing_token = await self.page(client, changes=dict(offset='25'), status=409)
        self.assertEqual(missing_token['reason'], 'current_slate_read_token_required')

        from app.dashboard.comparison_board_api import SLATE_READS
        cache = client.server.app[SLATE_READS]
        tabs = [await self.page(client) for _ in range(cache.maximum_frames + 1)]
        self.assertEqual(len({page['read_token'] for page in tabs}), len(tabs))
        self.assertLessEqual(len(cache.frames), cache.maximum_frames)
        self.assertLessEqual(cache.retained_bytes, cache.maximum_bytes)
        evicted = await self.page(client, tabs[0], status=409)
        self.assertEqual(evicted['reason'], 'current_slate_read_expired')
        before_expiry = cache.clock
        cache.clock = lambda: before_expiry() + cache.ttl_seconds + 1
        expired = await self.page(client, tabs[-1], status=409)
        self.assertEqual(expired['reason'], 'current_slate_read_expired')
        self.assertEqual(cache.retained_bytes, 0)
        self.assertEqual(len(cache.frames), 0)
        cache.clock = before_expiry
        capacity = cache.maximum_bytes
        cache.maximum_bytes = 1
        refused = await self.page(client, status=409)
        self.assertEqual(refused['reason'], 'current_slate_read_capacity')
        cache.maximum_bytes = capacity
        recovered = await self.page(client)
        self.assertEqual(recovered['coverage']['total_games'], 61)

        # Runtime, explicit Stop, observation authority and reset epoch withdraw
        # existing reads before another page can be adopted.
        for label in ('stop', 'observation_authority', 'runtime_replacement', 'epoch_reset'):
            with self.subTest(withdrawal=label):
                captured = await self.page(client)
                if label == 'stop':
                    self.service.dispatch = False
                elif label == 'observation_authority':
                    self.service.background_calculations['observations'] = 'stopped'
                elif label == 'runtime_replacement':
                    self.service.runtime_id = str(uuid4())
                else:
                    with self.connect() as db:
                        db.execute('UPDATE current_row_epoch SET epoch=%s WHERE singleton=true', (str(uuid4()),))
                self.state.write(self.service)
                refused = await self.page(client, captured, status=409)
                self.assertEqual(refused['reason'], 'current_slate_read_authority_changed')
                self.service.dispatch = True
                self.service.background_calculations['observations'] = 'running'
                self.state.write(self.service)
        self.assertEqual({venue: len(value) for venue, value in calls.items()}, calls_after_ingress)
        self.assertFalse(self.service.workers.get('the_odds_api'))
        output = os.environ.get('PREDICT_CI_REPORT_ROOT')
        if output:
            receipt = dict(evidence='authored_disposable_postgresql_not_installed_observation',
                ingress=dict(games=60, native_outcomes=240, sports=list(SPORTS), families=list(FAMILIES),
                    workers=list(VENUES), batches=4, batch_games=15,
                    markets_per_source=self.config['markets_per_source'],
                    events_per_source=self.config['events_per_source'],
                    discovery_pages=self.config['discovery_pages']),
                captured=dict(games=len(captured_keys), unique_games=len(set(captured_keys)),
                    page_games=[page['coverage']['returned_games'] for page in pages],
                    changed_publication_revision=published['read_revision'] != first['read_revision'],
                    selected_original_preserved=old_quote['original'] == selected['original'],
                    selected_clocks_preserved=old_quote['times'] == selected['times']),
                fresh=dict(games=fresh['coverage']['total_games'], selected_price=new_quote['original']['value'],
                    page_games=[page['coverage']['returned_games'] for page in fresh_pages]),
                ordinary_javascript='readSlate/LatestRead/SlateAccumulator and clock formatting on actual HTTP bodies',
                bounds=dict(expired=True, evicted=True, explicit_capacity_refusal=True, recovered=True),
                withdrawals=['stop', 'observation_authority', 'runtime_replacement', 'epoch_reset'],
                frozen_inputs='changed exact source inputs explicitly refused', provider_requests=0)
            (Path(output) / 'consistent-slate-reads.json').write_text(json.dumps(receipt, indent=2) + '\n')
