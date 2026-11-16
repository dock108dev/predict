"""The current desk and saved reads share exact occurrence and clock fixtures."""
from datetime import timedelta
import json
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from psycopg.types.json import Jsonb

from app.collection.sportsgameodds_current_rows import event_record
from app.comparison.event_eligibility import assess
from app.comparison.game_phase import price_phase
from app.dashboard import replay_api, snapshot_api
from app.normalization.college_registry import aggregate_registry
from app.storage import ordinary_publication as live
from app.storage.store import hashed, stamp
from tests.latest_board_fixture import LatestBoardFixture, SOCKET


def test_reschedule_needs_bound_schedule_history():
    start = '2026-11-15T18:30:00Z'
    old = '2026-11-15T17:00:00Z'
    seen = '2026-11-15T18:00:00Z'
    event = dict(event_id='authored-reschedule', league='NFL', starts_at=start,
                 previous_starts_at=[old], status=dict(live=False, started=False),
                 teams=dict(home=dict(name='Detroit Lions'), away=dict(name='New England Patriots')))
    linked = event_record(event, 'a'*64, seen, aggregate_registry())
    assert price_phase(linked, {}, seen) == dict(state='scheduled', reason=None, basis='linked_reschedule')
    assert assess(linked, seen)['eligible']
    for change in (dict(original_start=None, previous_starts_at=[]), dict(schedule_metadata=None), dict(competition='MLB')):
        ambiguous = dict(linked, **change)
        assert price_phase(ambiguous, {}, seen)['reason'] == 'event_reschedule_unlinked'
        assert not assess(ambiguous, seen)['eligible']
    delayed = dict(linked, status=dict(status='delayed'))
    assert price_phase(delayed, {}, seen)['reason'] == 'event_postponed'
    successive = event_record(dict(event, previous_starts_at=[old, '2026-11-15T17:45:00Z']),
                               'b'*64, seen, aggregate_registry())
    assert 'original_start' not in successive and assess(successive, seen)['eligible']


def test_live_state_clock_cannot_be_inferred_from_a_fresh_book():
    start, source, receipt = '2026-11-15T18:30:00Z', '2026-11-15T18:30:02Z', '2026-11-15T18:30:03Z'
    quote = dict(source=dict(provider='polymarket_us'), times=dict(source_at=source, received_at=receipt))
    event = dict(scheduled_start=start, status=dict(live=True, observed_at='2026-11-15T18:29:59Z'))
    assert price_phase(event, quote, receipt)['reason'] == 'post_start_game_state_unverified'
    event['status']['observed_at'] = '2026-11-15T18:30:04Z'
    assert price_phase(event, quote, receipt)['reason'] == 'event_state_future'
    event['status']['observed_at'] = start
    phase = price_phase(event, quote, receipt)
    assert phase['state'] == 'live' and phase['observed_at'] == start
    assert stamp(phase['current_until']) == stamp(source) + timedelta(seconds=15)


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class CurrentSlateLifecycle(LatestBoardFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.at = stamp(self.first['start_at']) - timedelta(hours=1)
        self.state.write(self.service)
        self.fresh_sources()
        for target in ('app.storage.comparison_snapshot.utc', 'app.storage.ordinary_publication.utc'):
            change = patch(target, side_effect=lambda: self.at.isoformat())
            change.start()
            self.addCleanup(change.stop)
        with self.connect() as db:
            db.execute('TRUNCATE comparison_policy_revision,comparison_snapshot_result,comparison_snapshot CASCADE')
            db.execute("INSERT INTO comparison_publication(kind,id,generation,facts) VALUES('live','',0,'{}')")

    def admit_aggregate(self, row, *, sports):
        from app.collection.current_database import DatabaseIngressSink

        self.service.config.update(aggregate_provider='sportsgameodds', sports=sports)
        self.state.write(self.service)
        sink = DatabaseIngressSink(SimpleNamespace(provider=self.service), self.service.config)
        with patch('app.collection.current_database.connect', self.connect), \
             patch('app.collection.current_database.utc', return_value=self.at.isoformat()):
            sink.prepare(row, self.service.states)

    async def test_admitted_sgo_live_price_serves_before_ordinary_head(self):
        from app.collection.sportsgameodds_adapter import parse_page
        from app.collection.sportsgameodds_current_rows import current_rows
        from app.storage.sportsgameodds_reference import prepare_frames, prepare_page
        from tests.test_sportsgameodds_adapter import response

        self.service.config['live_enabled'] = True
        raw = response()
        event, = raw['data']
        event['status'].update(startsAt=(self.at - timedelta(seconds=6)).isoformat(), started=True, live=True)
        event['teams']['home']['names']['long'] = 'Detroit Pistons'
        event['teams']['away']['names']['long'] = 'Boston Celtics'
        source_at = (self.at - timedelta(seconds=3)).isoformat()
        odd, = event['odds'].values()
        first = dict(odd['byBookmaker']['book'], lastUpdatedAt=source_at)
        odd['byBookmaker'] = dict(novig=first, prophetx=dict(first, odds='+104'), kalshi=first)

        def admit(received_at):
            page = parse_page(json.dumps(raw).encode(), received_at)
            records, _ = current_rows(page, page.receipt_sha256)
            references = prepare_page(page)
            self.admit_aggregate(dict(type='current_aggregate_records', source='sportsgameodds',
                sport='NBA', records=records, sgo_reference_rows=references,
                sgo_event_frames=prepare_frames(page, references), receipt_sha256=page.receipt_sha256,
                event_scopes={event['eventID']: 'NBA'}, complete_venues=[], received_at=received_at), sports=['NBA'])

        admit((self.at - timedelta(seconds=1)).isoformat())
        # Same original source clock, newer receipt. The independently
        # selected reference retains the first price. The executable display
        # owner has the exact linked revision for the amended price.
        odd['byBookmaker']['novig'] = dict(first, odds='+106')
        admit(self.at.isoformat())
        app = web.Application()
        snapshot_api.mount(app)
        query = dict(layout='desk', view='odds', browse_odds='1', phase='live', lines='all', summary='1')
        with patch.object(snapshot_api, 'connect', self.connect):
            async with TestClient(TestServer(app)) as client:
                response = await client.get('/api/comparison-current', params=query)
                self.assertEqual(response.status, 200, await response.text())
                board = await response.json()
                self.assertEqual(board['generation'], 0)
                self.assertEqual(board['publication']['current_prices'], 2)
                offers = {o['venue']: o for row in board['rows'] for o in row['offers']}
                self.assertEqual(set(offers), {'novig', 'prophetx'})
                novig = offers['novig']
                self.assertEqual(novig['odds']['american'], '+106')
                self.assertEqual((novig['source_clock_at'], novig['received_at']), (source_at, self.at.isoformat()))
                self.assertTrue(novig['live_aggregate_desk'] and novig['current'])
                self.assertIsNone(novig['value'])
                self.assertFalse(novig['trade_fee_available'])
                selection = dict(layout='desk', id=novig['id'], phase='live')
                response = await client.get('/api/comparison-current/selection', params=selection)
                detail = await response.json()
                self.assertEqual(detail['row']['price_revision'], novig['price_revision'])
                self.assertEqual(detail['evidence']['inspection']['original']['value'], '+106')
                direct = dict(query, game_key=board['rows'][0]['game_key'])
                response = await client.get('/api/comparison-current', params=direct)
                self.assertIn(novig['id'], [o['id'] for r in (await response.json())['rows'] for o in r['offers']])

                with self.connect() as db:
                    self.assertTrue(live.turn(db)['published'])
                response = await client.get('/api/comparison-current', params=query)
                published = await response.json()
                self.assertGreater(published['generation'], 0)
                self.assertIn(novig['id'], [o['id'] for r in published['rows'] for o in r['offers']])

                self.state.write(self.service, paused_sources=['novig'])
                response = await client.get('/api/comparison-current', params=query)
                self.assertEqual({o['venue'] for r in (await response.json())['rows'] for o in r['offers']}, {'prophetx'})
                self.at += timedelta(seconds=16)
                self.state.write(self.service)
                response = await client.get('/api/comparison-current', params=query)
                self.assertFalse((await response.json())['rows'])

    async def test_admitted_live_oddslink_price_uses_independent_current_sporting_state(self):
        from app.collection.oddslink_prophetx import SOURCE
        from app.storage.store import exact_time

        self.service.config['live_enabled'] = True
        start = self.at - timedelta(minutes=5)
        source_at = self.at - timedelta(seconds=4)
        home, away = 'Arizona Wildcats', 'Utah Utes'
        native_event = dict(id='independent-fixture', competition='NCAAF', scheduled_start=start.isoformat(),
                            home='NCAAF:NCAA29', away='NCAAF:NCAA732',
                            status=dict(live=True, observed_at=source_at.isoformat()))
        event_id = hashed(['polymarket_us', native_event['id']])
        with self.connect() as db:
            db.execute('INSERT INTO current_event VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                       (event_id, 'polymarket_us', native_event['id'], 'NCAAF', start.isoformat(),
                        exact_time((start + timedelta(hours=24)).isoformat()), Jsonb(native_event), hashed(native_event)))
        capture = dict(sport_key='ncaaf', received_at=self.at.isoformat(), generated_at=self.at.isoformat(),
            sha256='a'*64, fixtures=[dict(id='public-ncaaf-fixture', sport_key='ncaaf', commence_time=start.isoformat(),
                in_play=True, home_team=home, away_team=away, bookmakers=[dict(key='prophetx', kind='exchange',
                    last_update=source_at.isoformat(), markets={'h2h':[dict(name=home, price=-110), dict(name=away, price=105)]})])])
        self.admit_aggregate(dict(type='oddslink_prophetx_records', source=SOURCE, sport='NCAAF', capture=capture),
                             sports=['NCAAF'])
        app = web.Application()
        snapshot_api.mount(app)
        query = dict(layout='desk', view='odds', browse_odds='1', phase='live', lines='all', summary='1')
        with patch.object(snapshot_api, 'connect', self.connect):
            async with TestClient(TestServer(app)) as client:
                response = await client.get('/api/comparison-current', params=query)
                self.assertEqual(response.status, 200, await response.text())
                board = await response.json()
                self.assertEqual(board['generation'], 0)
                quotes = [o for row in board['rows'] for o in row['offers']]
                self.assertEqual({o['odds']['american'] for o in quotes}, {'-110', '+105'})
                self.assertEqual({o['source_clock_at'] for o in quotes}, {source_at.isoformat()})
                self.assertTrue(all(o['current'] and o['value'] is None for o in quotes))
                native_event['status'] = dict(ended=True, observed_at=self.at.isoformat())
                with self.connect() as db:
                    db.execute('UPDATE current_event SET facts=%s,revision=%s WHERE id=%s',
                               (Jsonb(native_event), hashed(native_event), event_id))
                response = await client.get('/api/comparison-current', params=query)
                self.assertFalse((await response.json())['rows'])

    async def test_current_and_saved_routes_after_kickoff_stop_and_cancellation(self):
        with self.connect() as db:
            turn = live.turn(db)
            self.assertTrue(turn['published'], turn)
        app = web.Application()
        snapshot_api.mount(app)
        replay_api.mount(app)
        browse = dict(layout='desk', view='odds', browse_odds='1', lines='all', summary='1', limit='1')
        unpaged = dict(browse, limit='25')

        async def get(client, query, path='/api/comparison-current'):
            response = await client.get(path, params=query)
            self.assertEqual(response.status, 200, await response.text())
            return await response.json()

        with patch.object(snapshot_api, 'connect', self.connect), patch.object(replay_api, 'connect', self.connect):
            async with TestClient(TestServer(app)) as client:
                first = await get(client, browse)
                self.assertEqual(first['phase'], 'pregame')
                self.assertGreaterEqual(first['total'], 2)
                next_page = await get(client, dict(browse, offset='1', browse_id=first['browse_id']))
                row = next_page['rows'][0]
                game, start = row['game_key'], stamp(row['start_at'])
                candidate = next(offer for offer in row['offers'] if offer.get('evidence_result_id'))
                chosen = dict(unpaged, game_key=game, game_capture=candidate['evidence_result_id'])
                direct = await get(client, chosen)
                self.assertTrue(direct['rows'])
                old = await get(client, dict(layout='desk', id=candidate['id']), '/api/comparison-current/selection')
                self.assertEqual(old['row']['id'], candidate['id'])

                # The exact current event withdrawal takes effect before another publication.
                with self.connect() as db:
                    packed = live.status(db)
                    head = snapshot_api.snapshots.unpack(db.execute(
                        'SELECT result FROM comparison_snapshot_result WHERE id=%s', (packed['result_id'],)
                    ).fetchone()['result'], lazy=True, db=db)
                    source = next(r['source'] for r in head['rows'] if r['id'] == candidate['id'])
                    event_id = hashed([source['provider'], source['native_event_id']])
                    original = db.execute('SELECT facts,revision FROM current_event WHERE id=%s', (event_id,)).fetchone()
                    facts = dict(original['facts'], status=dict(status='cancelled', observed_at=self.at.isoformat()))
                    db.execute('UPDATE current_event SET facts=%s,revision=%s WHERE id=%s',
                               (Jsonb(facts), hashed(facts), event_id))
                cancelled = await get(client, chosen)
                self.assertFalse(cancelled['rows'])
                self.assertEqual(cancelled['retained_game']['lifecycle'], 'event_cancelled')
                self.assertEqual(cancelled['retained_game']['game_key'], game)
                with self.connect() as db:
                    db.execute('UPDATE current_event SET facts=%s,revision=%s WHERE id=%s',
                               (Jsonb(original['facts']), original['revision'], event_id))

                # A stale head, an existing page token and a real Stop all respect kickoff.
                self.at = start
                self.state.write(self.service, global_stopped=True)
                withdrawn = await get(client, chosen)
                self.assertFalse(withdrawn['rows'])
                self.assertEqual(withdrawn['retained_game']['result_id'], candidate['evidence_result_id'])
                self.assertFalse((await get(client, dict(chosen, phase='live')))['rows'])
                inspected = await get(client, dict(layout='desk', id=candidate['id']), '/api/comparison-current/selection')
                self.assertIsNone(inspected['row'])
                paged = await get(client, dict(browse, offset='1', browse_id=first['browse_id']))
                self.assertNotIn(game, [r['game_key'] for r in paged['rows'] if not r.get('withdrawn')])
                current_slates = await get(client, dict(unpaged, search=row['game_title']))
                self.assertNotIn(game, [r['game_key'] for r in current_slates['rows']])

                saved = dict(unpaged, dataset='retained', **{k: withdrawn['retained_game'][k]
                                                            for k in ('game_key', 'result_id')})
                capture = await get(client, saved, '/api/odds-replay')
                self.assertEqual(capture['replay']['captured_at'], withdrawn['retained_game']['captured_at'])
                self.assertTrue(capture['rows'])
                captured_quote = next(offer for r in capture['rows'] for offer in r['offers'] if offer['id'] == candidate['id'])
                detail = await get(client, dict(saved, id=captured_quote['id']), '/api/odds-replay/details')
                self.assertEqual(detail['row']['price_revision'], captured_quote['price_revision'])
                self.assertEqual(detail['row']['times']['source_at'], captured_quote['source_clock_at'])

    async def test_live_route_requires_post_start_original_price(self):
        self.service.config['live_enabled'] = True
        self.state.write(self.service)
        with self.connect() as db:
            turn = live.turn(db)
            self.assertTrue(turn['published'], turn)
            head = live.status(db)
            row = db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s', (head['result_id'],)).fetchone()
            result = snapshot_api.snapshots.unpack(row['result'], lazy=True, db=db)
        source = next(r['source'] for r in result['rows'] if r['venue'] == 'novig' and r['market']['period'] == 'full_game')
        records = [r for r in self.records if r['quote']['source']['provider'] == source['provider']
                   and r['quote']['source']['native_event_id'] == source['native_event_id']]
        self.assertTrue(records)
        self.at = stamp(records[0]['event']['scheduled_start']) + timedelta(seconds=2)
        for record in records:
            record['event']['status'] = dict(live=True, observed_at=self.at.isoformat())
            record['quote']['times'].update(source_at=self.at.isoformat(), received_at=self.at.isoformat())
            record['quote'].get('provider_clocks', {}).update(book=self.at.isoformat(), market=self.at.isoformat())
        self.state.write(self.service)
        self.admit(records)
        with self.connect() as db:
            turn = live.turn(db)
            self.assertTrue(turn['published'], turn)
        app = web.Application()
        snapshot_api.mount(app)
        query = dict(layout='desk', view='odds', browse_odds='1', phase='live', lines='all', summary='1')
        with patch.object(snapshot_api, 'connect', self.connect):
            async with TestClient(TestServer(app)) as client:
                response = await client.get('/api/comparison-current', params=query)
                board = await response.json()
                live_quotes = [o for row in board['rows'] for o in row['offers']]
                self.assertTrue(live_quotes, board)
                self.assertTrue(all(o['current'] and o['game_state'] == 'live' for o in live_quotes))
                self.assertTrue(all(stamp(o['source_clock_at']) >= stamp(records[0]['event']['scheduled_start'])
                                    for o in live_quotes))
                self.at += timedelta(seconds=16)
                self.state.write(self.service)
                response = await client.get('/api/comparison-current', params=query)
                self.assertFalse((await response.json())['rows'])
