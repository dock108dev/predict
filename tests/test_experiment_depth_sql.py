"""Schedule identity, public-depth storage and collector recovery in disposable SQL."""
import asyncio
from contextlib import closing, nullcontext
from datetime import timedelta, timezone
from functools import partial
from multiprocessing import get_context
from pathlib import Path
import signal
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

import psycopg
from psycopg.types.json import Jsonb

from app.collection import experiment_depth as collector
from app.collection.experiment_depth_stage import DepthStage
from app.collection.native_trading import NativeTrading
from app.research import experiment
from app.storage import experiment_depth as depth
from app.storage.store import encoded, hashed
from tests.latest_board_fixture import LatestBoardFixture, SOCKET


def captured_book(known):
    received = known - timedelta(milliseconds=90)
    evidence = dict(path='/native/book', status=200, sha256=hashed('fixture-book'),
                    requested_at=depth.clock(received - timedelta(milliseconds=30)),
                    received_at=depth.clock(received))
    identification = dict(path='/native/market', sha256=hashed('fixture-contract'),
                          observed_at=depth.clock(known - timedelta(seconds=2)))
    return {'fixture-offer': dict(venue='kalshi', market_id='fixture-contract', complete=True,
        levels=[dict(price='2/5', size='100')], receipts=[evidence], identity_receipts=[identification])}


def wide_novig_book(known, task):
    """A broad spread inventory with several crowded, two-sided books."""
    from email.utils import format_datetime

    from app.collection.novig_experiment_depth import (
        CUTOVER_DATE_UTC, PublicBookDepth, PublicEventDepth, book_depth, catalog_depth,
    )

    def identity(*parts):
        return str(uuid5(NAMESPACE_URL, ':'.join(map(str, parts))))

    received = known - timedelta(milliseconds=90)
    evidence = dict(path='/v3/public/catalog/markets', status=200, sha256=hashed('fixture-catalog'),
        date=format_datetime(received.astimezone(timezone.utc), usegmt=True), age='0',
        **{'cache-control': 'public, max-age=10'},
        requested_at=depth.clock(received - timedelta(milliseconds=30)), received_at=depth.clock(received))
    event_id = identity('event')
    start = task['target_at'] + timedelta(minutes=10)
    terms = (dict(coefficient='0.06', makerCredit='0.25', charged='WHEN_LIVE') if known < CUTOVER_DATE_UTC
             else dict(coefficient='0.03', makerCredit='0.25', charged='ALWAYS'))
    selected = replay_offer(task)['record']
    observations = {}
    for number in range(66):
        market_id = identity('market', number)
        line = f'{number}.5'
        subjects = [identity('subject', side) for side in ('away', 'home')]
        outcome_ids = [identity('outcome', number, side) for side in ('away', 'home')]
        labels = [f'Away -{line}', f'Home +{line}']
        outcomes = [dict(outcomeId=outcome, name=label, subjectId=subject, status='TBD',
                         bid=dict(price='0.75', qty=30 if number < 5 else 4000))
                    for outcome, label, subject in zip(outcome_ids, labels, subjects, strict=True)]
        market = dict(eventId=event_id, marketId=market_id, marketType='SPREAD', status='OPEN',
                      startsTs=int(start.timestamp()*1000), strike=line, outcomes=outcomes, receipt=evidence,
                      fee=terms, voids='FMV')
        catalog = PublicEventDepth({market_id: market}, (evidence,))
        book_receipt = dict(evidence, path=f'/v3/public/markets/{market_id}/book',
                            sha256=hashed(['fixture-book', number]), **{'cache-control': 'public, max-age=5'})
        for index, side in enumerate(('away', 'home')):
            binding = dict(venue='novig', league='NCAAB', family='spread', selected_side=side,
                signed_line=('-' if index == 0 else '') + line, starts_at=depth.clock(start),
                event_id=event_id, market_id=market_id, outcome_id=outcome_ids[index],
                opposite_outcome_id=outcome_ids[1-index], phase='scheduled', phase_verified=True,
                available=True, revision=hashed(['identity', market_id]))
            observation = catalog_depth(binding, catalog, known)
            if number < 5:
                orders = [dict(orderId=identity('order', number, side, order),
                           price=f'0.{750 - (order // 30) * 5:03d}', qty=1)
                          for order in range(480)]
                book = dict(marketId=market_id, seq=number, orders={outcome_ids[1-index]: orders})
                observation = book_depth(binding, PublicBookDepth(book, book_receipt), known, catalog=observation)
            assert observation['reason'] is None
            observation.update(identity_receipts=[dict(observed_at=depth.clock(received),
                path=f'/v3/public/catalog/events/{event_id}', sha256=hashed('fixture-event')),
                dict(observed_at=depth.clock(received), path=evidence['path'], sha256=hashed('fixture-market'))])
            key = depth.offer_key(selected) if number == 10 and side == 'home' else hashed([market_id, side])
            observations[key] = observation
    return observations


def replay_offer(task):
    from tests.test_paper_experiments import frozen_priced

    start = task['target_at'] + timedelta(minutes=10)
    offer = frozen_priced('+300', venue='novig', line='10.5')
    record = offer['record']
    record['event'].update(scheduled_start=depth.clock(start), competition='NCAAB')
    record['market_identity']['rules'] = 'sportsgameodds-unverified-1'
    record['result_policy'] = 'sportsgameodds-unverified-1:spread'
    record['quote']['source'].update(native_event_id='fixture-restart-game',
        native_outcome_id='points-home-game-sp-home', native_line='10.5')
    return offer


def run_depth_collector(database, stage_path, task, mode, events):
    """Run the actual collector loop in a process that the test can kill."""
    connector = partial(LatestBoardFixture.connect, database)
    target, deadline = task['target_at'], task['deadline_at']
    known = target - timedelta(seconds=1) if mode == 'stage' else deadline + timedelta(seconds=1)

    class DepthProbe(collector.ExperimentDepth):
        def _bindings(self, _task, _at):
            return {'fixture-offer': ({}, None)}, None, [], None, {}, {}, (), {}

        async def _capture(self, *args):
            self.dashboard = None  # This probe exercises only the frozen lane.
            await super()._capture(*args)

        async def _observe(self, *_args, **_kwargs):
            if mode != 'stage':
                events.send(('unexpected_venue_request', None))
                raise AssertionError('Recovery dispatched a venue request')
            return wide_novig_book(known, task), {}

        def _persist(self, payload):
            admission = (patch.object(experiment, '_admit', side_effect=ValueError('research_retention_capacity'))
                         if mode == 'storage_deferred' else nullcontext())
            try:
                with admission:
                    saved = super()._persist(payload)
            except Exception as exc:
                events.send(('publication_deferred', str(exc)))
                raise
            if mode == 'after_commit':
                events.send(('after_commit', saved['id']))
                Event().wait()
            return saved

    async def idle_dashboard(*_args):
        await asyncio.Future()

    async def main():
        worker = SimpleNamespace(controls=lambda: dict(stopped=False, source_paused=False),
                                 now=lambda: known, experiment_late_windows=[(target, deadline)])
        service = SimpleNamespace(dispatch=True, globally_stopped=False,
            paused_sources={'sportsgameodds'} if mode == 'paused' else set(),
            workers={'sportsgameodds': worker}, config=dict(requests_per_source=0, source_bytes=0))
        owner = DepthProbe(service, connector=connector, now=lambda: known, stage_path=stage_path)
        with patch.object(NativeTrading, 'run', idle_dashboard):
            await owner.start()
            try:
                while True:
                    if events.poll():
                        return
                    state = owner.progress
                    if mode == 'stage' and state.get('pending'):
                        events.send(('captured', state['pending']))
                        await asyncio.Future()
                    if mode == 'paused' and state['state'] == 'paused':
                        events.send(('paused', None))
                        await asyncio.Future()
                    await asyncio.sleep(0.02)
            finally:
                await owner.close()

    asyncio.run(main())


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class ExperimentDepthSQL(LatestBoardFixture):
    def declare(self, db, *, event_id, at=None):
        at = at or experiment.utc()
        start = at + timedelta(minutes=10, seconds=20)
        event = dict(provider='sportsgameodds', source_event_id=event_id, event_id=hashed(event_id),
                     league='NCAAB', home='home', away='away', title='Away at Home',
                     starts_at=depth.clock(start), status={})
        experiment.discover(db, [event], at=at)
        row = db.execute("""SELECT t.* FROM public.ev_experiment_task t
                            JOIN public.ev_experiment_game g ON g.id=t.game_id
                            WHERE t.checkpoint='late' AND g.source_event_id=%s""", (event_id,)).fetchone()
        return at, row, event

    async def test_replay_pins_unique_decision_and_rejects_later_receipts(self):
        with self.connect() as db:
            at, task, event = self.declare(db, event_id='depth-schedule-one',
                                           at=experiment.utc() - timedelta(seconds=60))
            evidence = dict(received_at=depth.clock(at), requested_at=depth.clock(at), path='/public',
                            age='NaN', date='Fri, 27 Nov 2026 15:00:00 GMT')
            observations = {'offer1': dict(venue='novig', levels=[], complete=True, receipts=[evidence]),
                            'offer2': dict(venue='novig', levels=[], complete=True, receipts=[evidence])}
            saved = depth.save(db, task, known_at=at, observations=observations)
            self.assertEqual(len(saved['http_receipts']), 1)
            self.assertIsNone(saved['metrics']['max_response_age_seconds'])
            self.assertEqual(saved, depth.save(db, task, known_at=at, observations={}))
            task_ref = (task['game_id'], task['schedule_id'], task['target_at'])
            self.assertEqual(depth.read(db, *task_ref), saved)
            self.assertEqual(depth.input_ids(db, [task_ref]), {task['game_id']: saved['id']})
            self.assertEqual(depth.read_ids(db, [saved['id']]), {saved['id']: saved})
            with self.assertRaises(psycopg.DatabaseError), db.transaction():
                db.execute('DELETE FROM public.ev_experiment_depth WHERE id=%s', (saved['id'],))
            later = task['target_at'] + timedelta(seconds=30)
            with self.assertRaisesRegex(ValueError, 'experiment_depth_cutoff'):
                depth.save(db, task, known_at=later, observations={})
            with self.assertRaisesRegex(ValueError, 'experiment_depth_receipt_clock'):
                depth.save(db, task, known_at=at, observations={'later': {
                    'receipts': [dict(evidence, received_at=depth.clock(later))]}})
            microsecond = at.replace(microsecond=123456)
            submicrosecond = depth.clock(microsecond).replace('.123456+', '.1234561+')
            with self.assertRaisesRegex(ValueError, 'experiment_depth_receipt_clock'):
                depth.normalize(task, known_at=microsecond, observations={'later': {
                    'receipts': [dict(evidence, requested_at=depth.clock(microsecond), received_at=submicrosecond)]}})
            followup = depth.save(db, task, known_at=later, observations={}, kind='followup',
                                  cutoff_at=later, origin_id=saved['id'])
            self.assertEqual(depth.read(db, *task_ref, kind='followup')['id'], followup['id'])
            self.assertEqual(depth.followups(db, [saved['id']]), {saved['id']: followup})
            self.assertEqual(depth.input_ids(db, [task_ref]), {task['game_id']: saved['id']})

            changed = dict(event, starts_at=depth.clock(experiment.stamp(event['starts_at']) + timedelta(hours=2)))
            experiment.discover(db, [changed], at=at)
            revised = db.execute("""SELECT * FROM public.ev_experiment_task
                WHERE game_id=%s AND checkpoint='late'""", (task['game_id'],)).fetchone()
            revised_ref = (revised['game_id'], revised['schedule_id'], revised['target_at'])
            self.assertIsNone(depth.read(db, *revised_ref))
            self.assertEqual(depth.input_ids(db, [revised_ref]), {})
            self.assertEqual(depth.read(db, *task_ref)['id'], saved['id'])

    async def test_candidate_admission_and_nonblocking_writer_leave_sgo_task_untouched(self):
        with self.connect() as db:
            _, task, event = self.declare(db, event_id='depth-active-campaign')
            db.execute("UPDATE public.ev_experiment_game SET early_id=schedule_id WHERE id=%s", (task['game_id'],))
            at = experiment.utc()
            self.assertEqual(collector.targets(db, at), [])
            config = dict(depth_policy=depth.POLICY)
            campaign_id = hashed(config)
            db.execute('INSERT INTO public.paper_campaign VALUES (%s,DEFAULT,%s,%s)',
                       (campaign_id, Jsonb(config), len(encoded(config))))
            db.execute("""INSERT INTO public.paper_campaign_day(campaign_id,game_date)
                VALUES (%s,(%s::timestamptz AT TIME ZONE 'America/New_York')::date)""",
                (campaign_id, event['starts_at']))
            at = experiment.utc()
            self.assertIn(task['game_id'], [row['game_id'] for row in collector.targets(db, at)])
            self.assertEqual(collector.targets(db, at, exclude=[(task['game_id'], task['schedule_id'])]), [])
            self.assertIn(task['game_id'], [row['game_id'] for row in collector.targets(
                db, at, exclude=[(task['game_id'], 'preceding-schedule')])])
            with self.assertRaisesRegex(BlockingIOError, 'protected_tminus10_capture_due'):
                depth.save(db, task, known_at=at, observations={}, protect_checkpoint=True)
            with self.connect() as writer, writer.transaction():
                experiment._lock(writer)
                with self.assertRaisesRegex(BlockingIOError, 'experiment_depth_writer_busy'):
                    depth.save(db, task, known_at=at, observations={})
            after = db.execute("""SELECT * FROM public.ev_experiment_task
                WHERE game_id=%s AND checkpoint='late'""", (task['game_id'],)).fetchone()
            self.assertEqual(task, after)


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class ExperimentDepthRecoverySQL(LatestBoardFixture):
    async def asyncSetUp(self):
        directory = TemporaryDirectory(prefix='predict-native-depth-')
        self.addCleanup(directory.cleanup)
        self.stage_path = Path(directory.name) / 'depth.sqlite3'
        with self.connect() as db:
            db.execute('TRUNCATE ev_experiment_record,ev_experiment_game,ev_experiment_task,'
                       'ev_experiment_accounting,paper_campaign CASCADE')
            db.execute('INSERT INTO ev_experiment_accounting(singleton) VALUES(true)')

    def fixture_game(self, db, *, seconds_ago=2, event_id='fixture-restart-game', with_replay=False):
        from app.research import paper, paper_campaigns, paper_depth
        from tests.test_paper_campaigns import fixed_config

        target = experiment.utc().replace(microsecond=0) - timedelta(seconds=seconds_ago)
        declared = target - timedelta(minutes=1)
        event = dict(provider='sportsgameodds', source_event_id=event_id,
                     event_id=hashed(event_id), league='NCAAB', home='home',
                     away='away', title='Away at Home', starts_at=depth.clock(target + timedelta(minutes=10)), status={})
        experiment.discover(db, [event], at=declared)
        claim, = experiment.due(db, at=declared)
        offers = [replay_offer(dict(target_at=target))] if with_replay else []
        early = self.write_checkpoint(db, claim, declared, offers=offers)
        self.assertEqual(early['state'], 'captured')
        config = dict(depth_policy=depth.POLICY)
        if with_replay:
            day = str(paper_campaigns._target_day(target))
            body = fixed_config(name='Win $25 wide native book', start_date=day, end_date=day,
                scope=paper_campaigns.ALL_SPORTS, market_scope=paper.MAIN_SPREADS_TOTALS,
                alternate_odds_below='400', target_profit_usd='25', kelly_comparison=False,
                portfolios=['best_venue'], portfolio_rule=paper.MAIN_FIRST_ONE_PER_GAME,
                depth_policy=paper_depth.ALL_SPORTS_VERSION, prospective_start_at=depth.clock(target))
            body.pop('kelly_multiplier')
            body.pop('reference_bankroll_usd')
            config = dict(paper_campaigns.configuration(body), discoverable=True)
        campaign = hashed(config)
        db.execute('INSERT INTO public.paper_campaign VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                   (campaign, declared, Jsonb(config), len(encoded(config))))
        db.execute("""INSERT INTO public.paper_campaign_day(campaign_id,game_date)
            VALUES (%s,(%s::timestamptz AT TIME ZONE 'America/New_York')::date) ON CONFLICT DO NOTHING""",
            (campaign, event['starts_at']))
        task = db.execute("SELECT * FROM ev_experiment_task WHERE checkpoint='late' AND game_id=%s",
                          (claim['game_id'],)).fetchone()
        return task, event

    def write_checkpoint(self, db, claim, known, *, offers=()):
        event = claim['event']
        snapshot = dict(event=dict(home=event['home'], away=event['away'], competition=event['league'],
            scheduled_start=event['starts_at']), times=dict(received_at=depth.clock(known),
            known_at=depth.clock(known)), offers=list(offers), coverage=dict(incomplete=False),
            source_event=dict(event_id=event['source_event_id']))
        return experiment.capture(db, claim['game_id'], claim['checkpoint'], snapshot,
            token=claim['token'], requested_at=known, received_at=known, known_at=known,
            defer_comparison=True)

    def start_collector(self, task, mode):
        context = get_context('spawn')
        monitor, sender = context.Pipe()
        process = context.Process(target=run_depth_collector,
            args=(self.name, self.stage_path, task, mode, sender))
        process.start()
        sender.close()
        self.addCleanup(monitor.close)
        self.addCleanup(self.stop_collector, process)
        return process, monitor

    def stop_collector(self, process):
        if process.is_alive():
            process.kill()
        process.join(timeout=5)
        self.assertFalse(process.is_alive(), 'Collector process did not stop')

    async def message(self, process, monitor):
        async with asyncio.timeout(15):
            while not monitor.poll():
                self.assertTrue(process.is_alive(), f'Collector exited {process.exitcode}')
                await asyncio.sleep(0.02)
        return monitor.recv()

    def staged(self):
        if not self.stage_path.exists():
            return []
        with closing(sqlite3.connect(self.stage_path.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            return list(map(dict, db.execute('SELECT * FROM staged_receipts')))

    async def wait_until_drained(self, process, monitor):
        async with asyncio.timeout(15):
            while self.staged():
                self.assertTrue(process.is_alive(), f'Collector exited {process.exitcode}')
                self.assertFalse(monitor.poll(), 'Unexpected collector event')
                await asyncio.sleep(0.02)

    def receipt_rows(self, db):
        return db.execute('SELECT id,known_at,cutoff_at,recorded_at,payload FROM ev_experiment_depth').fetchall()

    def dispositions(self):
        with closing(sqlite3.connect(self.stage_path.as_uri() + '?mode=ro', uri=True)) as db:
            return db.execute('SELECT reason,receipt_id FROM disposition ORDER BY sequence').fetchall()

    def stage_decision(self, task, *, book=captured_book):
        stage = DepthStage(self.stage_path)
        stage.initialize()
        known = task['target_at'] - timedelta(seconds=1)
        payload = depth.normalize(task, known_at=known, observations=book(known))
        stage.put(payload, task['deadline_at'], experiment.utc())
        return stage, payload

    async def test_kill_after_capture_and_after_commit_recovers_once_through_pause_and_sgo_lock(self):
        from app.research import paper_campaigns, paper_depth, workspace

        with self.connect() as db, self.connect() as writer:
            task, _ = self.fixture_game(db, with_replay=True)
            with writer.transaction():
                experiment._lock(writer)
                capture, capture_events = self.start_collector(task, 'stage')
                self.assertEqual(await self.message(capture, capture_events), ('captured', 1))
                original_stage, = self.staged()
                self.assertGreater(len(original_stage['body']), 512 * 1024)
                self.assertEqual(self.receipt_rows(db), [])
                self.stop_collector(capture)
                self.assertEqual(capture.exitcode, -signal.SIGKILL)

                # The restarted collector's clock has crossed T−9 while
                # PostgreSQL still has the protected writer's transaction.
                publisher, publish_events = self.start_collector(task, 'after_commit')
                self.assertEqual(await self.message(publisher, publish_events),
                                 ('publication_deferred', 'experiment_depth_writer_busy'))
                self.assertEqual(self.staged(), [original_stage])
                self.assertEqual(self.receipt_rows(db), [])
                late, = experiment.due(writer, at=experiment.utc(), late_only=True)
                checkpoint = self.write_checkpoint(writer, late, experiment.utc(), offers=[replay_offer(task)])
                self.assertEqual(checkpoint['state'], 'captured')
                self.assertLessEqual(experiment.stamp(checkpoint['recorded_at']), task['deadline_at'])
            self.assertLessEqual(experiment._dbclock(db), task['deadline_at'])

            event, receipt_id = await self.message(publisher, publish_events)
            self.assertEqual(event, 'after_commit')
            committed, = self.receipt_rows(db)
            self.assertEqual(receipt_id, committed['id'])
            self.assertEqual(receipt_id, original_stage['receipt_id'])
            self.assertEqual(self.staged(), [original_stage])
            self.stop_collector(publisher)
            self.assertEqual(publisher.exitcode, -signal.SIGKILL)

            paused, paused_events = self.start_collector(task, 'paused')
            self.assertEqual(await self.message(paused, paused_events), ('paused', None))
            self.assertEqual(self.staged(), [original_stage])
            self.assertEqual(self.receipt_rows(db), [committed])
            self.stop_collector(paused)

            resumed, resumed_events = self.start_collector(task, 'recover')
            await self.wait_until_drained(resumed, resumed_events)
            self.assertEqual(self.receipt_rows(db), [committed])
            known = task['target_at'] - timedelta(seconds=1)
            self.assertEqual(committed['known_at'], known)
            self.assertEqual(committed['cutoff_at'], task['target_at'])
            self.assertGreaterEqual(committed['recorded_at'], experiment.stamp(checkpoint['recorded_at']))
            body = committed['payload']
            self.assertEqual(hashed(body), receipt_id)
            expected = depth.normalize(task, known_at=known, observations=wide_novig_book(known, task))
            self.assertEqual(body, expected)
            self.assertEqual(encoded(body), original_stage['body'])
            self.assertEqual(db.execute('SELECT payload_bytes FROM ev_experiment_depth').fetchone()['payload_bytes'],
                             len(original_stage['body']))
            self.assertEqual(self.dispositions(), [('published', receipt_id)])
            # Replay the fixture game date even when capture starts just before
            # midnight Eastern and the fixture's kickoff is after midnight.
            replay_at = task['target_at'] + timedelta(minutes=10)
            with (patch.object(paper_campaigns.queue, 'utc', return_value=replay_at),
                  patch.object(paper_campaigns.mens_d1, 'daily_population', return_value=None)):
                run_id = paper_campaigns.tick(db)
            self.assertIsNotNone(run_id)
            run = workspace.run_detail(db, run_id, export=True)
            self.assertEqual(run['depth_receipts'], {receipt_id: dict(expected, id=receipt_id)})
            self.assertEqual(run['report']['policy']['depth_execution_version'], paper_depth.FIXED_PROFIT_VERSION)
            game, = run['report']['games']
            self.assertEqual(game['depth_receipt_id'], receipt_id)
            self.assertEqual(game['checkpoint_id'], checkpoint['id'])
            tickets = run['report']['portfolios']['best_venue']['tickets']
            self.assertEqual(len(tickets), 1, game)
            ticket, = tickets
            self.assertEqual(ticket['depth']['status'], 'full_size')
            selected = expected['observations'][depth.offer_key(replay_offer(task)['record'])]
            self.assertEqual(ticket['depth']['market_id'], selected['market_id'])

    async def test_official_shadow_replays_from_the_original_receipt_and_saved_checkpoint(self):
        from app.collection.native_trading_identity import native_event, record, expected
        from app.comparison.scanner_kalshi import resolve
        from app.research import paper_campaigns, paper_depth, records, workspace
        from app.storage.acquisition_snapshot import observe_checkpoint_commit
        from tests.test_scanner_kalshi import AT as kalshi_at, inputs

        with self.connect() as db:
            task, event = self.fixture_game(db, with_replay=True)
            known = task['target_at'] - timedelta(seconds=1)
            legacy_record = replay_offer(task)['record']
            book = wide_novig_book(known, task)[depth.offer_key(legacy_record)]
            official_event = native_event('novig', book['event_id'], 'NCAAB', event['starts_at'],
                dict(home=event['home'], away=event['away']), dict(home='Home', away='Away'), proof={})
            official_record = record('novig', official_event, book['market_id'], book['outcome_id'],
                'buy', 'spread', 'home', '10.5', settlement=book['contract']['settlement'])
            cid = expected(official_record)['contract_id']
            candidate = dict(record=official_record, book=book,
                game_link=dict(status='matched', sgo_start=event['starts_at'], canonical_game_id='canonical:fixture'),
                reference=dict(probability='3/5', prices=[dict(source_at=depth.clock(known), received_at=depth.clock(known))]),
                reference_reason=None, catalog_committed_at=None, book_committed_at=None)
            policies = {
                'kalshi': dict(price_bands=[['.01', '.99', '.01']],
                    fee=dict(model='kalshi_direct_taker_bound', terms=resolve(*inputs(), at=kalshi_at)['fee'])),
                'polymarket_us': dict(quantity_increment='.01', price_bands=[['.01', '.99', '.01']],
                    fee=dict(model='polymarket_us_standard_taker_bound', coefficient='.095')),
                'prophetx': dict(quantity_unit='usd_stake', quantity_increment='.01', quantity_minimum='1',
                    legal_prices=['.4'], fee=dict(model='prophetx_market_commission', rate='.02',
                        rounding='nearest_cent_profit_then_commission', schedule_revision='fixture')),
            }
            official_books = {cid: candidate}
            for venue, policy in policies.items():
                evidence = dict(requested_at=depth.clock(known-timedelta(milliseconds=50)),
                    received_at=depth.clock(known), sha256=hashed(['native-book', venue]))
                exchange = native_event(venue, venue+'-event', 'NCAAB', event['starts_at'],
                    dict(home=event['home'], away=event['away']), dict(home='Home', away='Away'), proof=evidence)
                quote = record(venue, exchange, venue+'-market', 'home-outcome', 'buy',
                    'spread', 'home', '10.5', settlement=book['contract']['settlement'])
                exact = expected(quote)
                exchange_book = dict(venue=venue, event_id=exchange['id'], market_id=venue+'-market',
                    outcome_id='home-outcome', opposite_outcome_id='away-outcome', native_side='buy',
                    valid_until=depth.clock(task['target_at']+timedelta(seconds=1)),
                    received_at=depth.clock(known), source_at=depth.clock(known), receipts=[evidence],
                    contract=dict(exact, phase='pregame', settlement=book['contract']['settlement']), reason=None,
                    levels=[dict(price='.4', quantity='100')], payout_usd='1', complete=True,
                    **dict(dict(quantity_increment='1'), **policy))
                official_books[exact['contract_id']] = dict(candidate, record=quote, book=exchange_book)
            shadow = dict(candidates=official_books, source_gaps={})
            with self.assertRaisesRegex(ValueError, 'experiment_depth_receipt_clock'):
                late_reference = dict(candidate, reference=dict(prices=[dict(
                    source_at=depth.clock(known), received_at=depth.clock(task['target_at']+timedelta(seconds=1)))]))
                depth.normalize(task, known_at=known, observations={}, official_shadow=dict(shadow, candidates={cid: late_reference}))
            payload = depth.normalize(task, known_at=known, observations={})
            stage = DepthStage(self.stage_path)
            stage.initialize()
            receipt_id = stage.put(payload, task['deadline_at'], known)
            claim, = experiment.due(db, late_only=True)
            checkpoint = self.write_checkpoint(db, claim, experiment.utc(), offers=[replay_offer(task)])
            pull_id = hashed(['official-shadow', checkpoint['id']])
            attempt_id, body_hash = hashed('attempt'), hashed('original-sgo-sportsbook-price')
            db.execute('''INSERT INTO market_pull (pull_id, requested_at, request_scope,state,details)
                    VALUES (%s,%s,%s,'complete',%s)''', (pull_id, task['target_at'],
                    Jsonb(dict(eventIDs=event['source_event_id'])), Jsonb(dict(
                        attempt_id=attempt_id, receipt_sha256=body_hash,
                        checkpoint_identity=dict(id=checkpoint['id'], schedule_id=task['schedule_id']),
                        timings=dict(checkpoint_recorded_at=checkpoint['recorded_at'])))))
            db.execute('''INSERT INTO market_pull_scope (pull_id,event_id,family,coverage,state)
                    VALUES (%s,%s,'spread','{}','complete')''', (pull_id, event['source_event_id']))
            db.execute('''INSERT INTO market_pull_receipt (pull_id,attempt_id,receipt_sha256,received_at,membership)
                    VALUES (%s,%s,%s,%s,%s)''', (pull_id, attempt_id, body_hash, task['target_at'],
                    Jsonb(dict(event_ids=[event['source_event_id']]))))
            staged, = stage.entries()
            restarted = DepthStage(self.stage_path)
            restarted.initialize()
            saved = depth.publish(db, restarted.load(staged))
            self.assertEqual(depth.publish(db, restarted.load(staged)), saved)
            restarted.finish(staged, 'published', receipt_id)
            self.assertEqual(restarted.entries(), [])
            self.assertEqual(saved['id'], receipt_id)
            shadow_payload = depth.normalize_shadow(task, origin_id=receipt_id, known_at=known, evidence=shadow)
            shadow_bundle = depth.publish_shadow(db, shadow_payload)
            game_id = task['game_id']
            from app.comparison import experiment_depth_execution as execution

            def tick():
                db.execute('UPDATE paper_campaign_day SET next_check_at=%s', (task['target_at'],))
                with (patch.object(paper_campaigns.queue, 'utc', return_value=task['target_at']+timedelta(minutes=10)),
                      patch.object(paper_campaigns.mens_d1, 'daily_population', return_value=None)):
                    return paper_campaigns.tick(db)

            actual_evaluator = execution.evaluate_official

            def wide_evaluation(evidence, **options):
                evaluated = actual_evaluator(evidence, **options)
                if evidence['book']['venue'] == 'novig':
                    evaluated['execution_audit'] = 'x' * records.EVALUATION_RECORD_BYTE_CAP
                return evaluated

            save_attachment = paper_depth.save_shadows

            def exhausted_headroom(conn, identity, refs):
                used = records.retention_usage(conn)
                with patch.object(records, 'TOTAL_BYTE_CAP', used['total'] + used['reserved']):
                    save_attachment(conn, identity, refs)

            with patch.object(execution, 'evaluate_official', side_effect=wide_evaluation) as wide:
                with patch.object(paper_depth, 'save_shadows', side_effect=exhausted_headroom):
                    unverified_run = tick()
                self.assertIsNotNone(unverified_run)
                wide.assert_not_called()
                unverified_export = workspace.run_detail(db, unverified_run, export=True)
                unavailable = workspace.official_shadow_export(db, unverified_run, game_id)
                self.assertEqual(unavailable['status'], 'shadow_attachment_unavailable')
                self.assertEqual(tick(), unverified_run)
                self.assertEqual(workspace.run_detail(db, unverified_run, export=True), unverified_export)
                shadow_export = workspace.official_shadow_export(db, unverified_run, game_id)
                self.assertGreater(len(encoded(shadow_export)), records.EVALUATION_RECORD_BYTE_CAP)
                size = db.execute('SELECT payload_bytes FROM research_workspace_run WHERE id=%s',
                                  (unverified_run,)).fetchone()['payload_bytes']
                self.assertLess(size, records.EVALUATION_RECORD_BYTE_CAP)
            unverified_shadow = workspace.official_shadow_export(db, unverified_run, game_id)
            self.assertEqual(unverified_shadow['decision']['sgo_checkpoint']['status'], 'checkpoint_commit_unverified')
            self.assertFalse(any(item['qualified'] for item in unverified_shadow['decision']['candidates']))
            identity = dict(checkpoint_id=checkpoint['id'],
                            **{key: task[key] for key in ('game_id', 'schedule_id', 'target_at', 'deadline_at')})
            self.assertTrue(observe_checkpoint_commit(db, pull_id, **identity))
            self.assertFalse(observe_checkpoint_commit(db, pull_id, **identity))
            run_id = tick()
            self.assertNotEqual(run_id, unverified_run)
            self.assertEqual(workspace.run_detail(db, unverified_run, export=True), unverified_export)
            self.assertEqual(workspace.official_shadow_export(db, unverified_run, game_id), unverified_shadow)
            export = workspace.run_detail(db, run_id, export=True)
            self.assertEqual(export['depth_receipts'][receipt_id], dict(payload, id=receipt_id))
            self.assertEqual(export['report']['portfolios']['best_venue']['count'], 0)
            self.assertNotIn('official_shadow_replay', export['report'])
            verified_shadow = workspace.official_shadow_export(db, run_id, game_id)
            replay = verified_shadow['decision']
            self.assertEqual(replay['depth_receipt_id'], receipt_id)
            self.assertEqual(verified_shadow['shadow_receipt']['id'], shadow_bundle['id'])
            self.assertEqual(replay['sgo_checkpoint']['status'], 'checkpoint_committed_by_deadline')
            self.assertEqual(replay['sgo_checkpoint']['receipt_sha256'], body_hash)
            executions = {execution['venue']: execution for execution in replay['candidates']}
            self.assertEqual(set(executions), {'novig', 'kalshi', 'polymarket_us', 'prophetx'})
            self.assertTrue(all(execution['qualified'] for execution in executions.values()), executions)
            self.assertEqual(executions['novig']['contract_id'], cid)
            campaign_id = export['definition']['campaign_id']
            campaign_export = paper_campaigns.trades(db, campaign_id, export=True)
            self.assertEqual(campaign_export['official_shadow_exports'], {run_id: export['official_shadow_export']})
            legacy_version, legacy_id = hashed('legacy-shadow-definition'), hashed('legacy-shadow-report')
            db.execute('''INSERT INTO research_workspace_definition (version,id,supersedes,payload_bytes,payload)
                SELECT %s,id,supersedes,payload_bytes,payload-'official_shadow_attachment'
                FROM research_workspace_definition WHERE version=%s''', (legacy_version, export['definition']['version']))
            legacy_shadow = dict(policy=depth.OFFICIAL_SHADOW_POLICY, decisions=[replay])
            db.execute('''INSERT INTO research_workspace_run
                (id,definition_version,game_date,report_revision,observed_at,summary,payload_bytes,payload)
                SELECT %s,%s,game_date,report_revision,observed_at,summary,payload_bytes,
                jsonb_set(payload,'{report,official_shadow_replay}',%s)
                FROM research_workspace_run WHERE id=%s''', (legacy_id, legacy_version, Jsonb(legacy_shadow), run_id))
            legacy_export = workspace.run_detail(db, legacy_id, export=True)
            self.assertEqual(legacy_export['report']['official_shadow_replay'], legacy_shadow)
            self.assertNotIn('official_shadow_export', legacy_export)
            db.execute('TRUNCATE public.market_pull CASCADE')  # Disposable cluster: simulate acquisition retention.
            self.assertEqual(workspace.run_detail(db, run_id, export=True), export)
            self.assertEqual(paper_campaigns.trades(db, campaign_id, export=True), campaign_export)
            self.assertEqual(workspace.official_shadow_export(db, run_id, game_id), verified_shadow)
            self.assertEqual(workspace.run_detail(db, legacy_id, export=True), legacy_export)
            another = dict(event, source_event_id='fixture-new-scheduled-game', event_id=hashed('fixture-new-scheduled-game'))
            experiment.discover(db, [another], at=task['target_at']-timedelta(minutes=1))
            later_run = tick()
            self.assertNotEqual(later_run, run_id)
            self.assertEqual(workspace.official_shadow_export(db, later_run, game_id)['decision'], replay)

    async def test_slow_shadow_cannot_spend_the_original_completion_clock(self):
        with self.connect() as db:
            task, event = self.fixture_game(db, with_replay=True)
        task = dict(task, event=event, source_event_id=event['source_event_id'], all_sports=True)
        known = task['target_at']-timedelta(milliseconds=100)
        now = [known]
        started, release = asyncio.Event(), asyncio.Event()

        class CaptureProbe(collector.ExperimentDepth):
            def _bindings(self, *_):
                return {'empty': ({}, None)}, None, [], None, {}, {}, (), {}

            async def _prospective_native(self, *_):
                return {}

            def _still_targeted(self, _):
                return True

            async def _observe(self, *_args, **_kwargs):
                await started.wait()
                return {}, {}

            async def _observe_shadow(self, *_):
                started.set()
                await release.wait()
                now[0] = known+timedelta(milliseconds=150)
                return dict(candidates={}, source_gaps={})

        worker = SimpleNamespace(controls=lambda: {})
        service = SimpleNamespace(dispatch=True, globally_stopped=False, paused_sources=set(),
                                  workers={'sportsgameodds': worker})
        owner = CaptureProbe(service, connector=self.connect, stage_path=self.stage_path, now=lambda: now[0])
        owner.dashboard = object()
        owner.stage.initialize()
        await owner._capture((None, None), task)
        staged = owner.stage.entries()[0]
        original = owner.stage.load(staged)
        self.assertEqual(original, depth.normalize(task, known_at=known, observations={}))
        original_id = staged['receipt_id']
        self.assertFalse(owner.shadow_stage.path.exists())
        release.set()
        await asyncio.gather(*owner.shadow_jobs)
        shadow_entry, = owner.shadow_stage.entries()
        shadow = owner.shadow_stage.load(shadow_entry)
        self.assertEqual(shadow['origin_id'], original_id)
        self.assertEqual(shadow['reason'], 'experiment_depth_shadow_cutoff')
        self.assertEqual(shadow['official_shadow']['candidates'], {})

        # A new collector can reopen the original and shadow spool independently.
        restarted = CaptureProbe(service, connector=self.connect, stage_path=self.stage_path, now=lambda: now[0])
        with self.connect() as db:
            with self.assertRaisesRegex(BlockingIOError, 'experiment_depth_shadow_original_pending'):
                depth.publish_shadow(db, shadow)
            claim, = experiment.due(db, late_only=True)
            checkpoint = self.write_checkpoint(db, claim, experiment.utc(), offers=[replay_offer(task)])
        self.assertEqual(restarted._publish_staged(staged), ('published', original_id))
        disposition, saved_shadow = restarted._publish_shadow_staged(shadow_entry)
        self.assertEqual(disposition, 'experiment_depth_shadow_cutoff')
        self.assertEqual(saved_shadow, shadow_entry['receipt_id'])
        with self.connect() as db:
            saved = depth.read_ids(db, [original_id])[original_id]
            self.assertEqual(saved, dict(original, id=original_id))
            self.assertEqual(depth.publish_shadow(db, shadow)['id'], saved_shadow)
            self.assertEqual(depth.shadow_inputs(db, [original_id])[original_id], dict(id=saved_shadow,
                checkpoint_id=checkpoint['id'], reason='experiment_depth_shadow_cutoff'))
        self.assertEqual(restarted.stage.entries(), [])
        self.assertEqual(restarted.shadow_stage.entries(), [])

    async def test_sql_headroom_admits_pilot_then_records_shadow_refusal(self):
        from app.research import records

        with self.connect() as db:
            task, _ = self.fixture_game(db, with_replay=True)
            claim, = experiment.due(db, late_only=True)
            checkpoint = self.write_checkpoint(db, claim, experiment.utc(), offers=[replay_offer(task)])
            usage = records.retention_usage(db)
        known = task['target_at']-timedelta(milliseconds=100)
        owner = collector.ExperimentDepth(SimpleNamespace(), connector=self.connect, stage_path=self.stage_path)
        owner.stage.initialize()
        original_id = owner._stage(task, known_at=known, observations=captured_book(known))
        staged, = owner.stage.entries()
        body = dict(candidates={}, source_gaps={'fixture': 'x' * (128 * 1024)})
        owner._stage_shadow(task, original_id, known, body, None)
        shadow_entry, = owner.shadow_stage.entries()
        # Set the real logical guard between the two actual measured admissions.
        capacity = usage['total'] + usage['reserved'] + staged['payload_bytes'] + shadow_entry['payload_bytes']//2
        with patch.object(records, 'TOTAL_BYTE_CAP', capacity):
            self.assertEqual(owner._publish_staged(staged), ('published', original_id))
            reason, shadow_id = owner._publish_shadow_staged(shadow_entry)
        self.assertEqual(reason, 'research_retention_capacity')
        self.assertNotEqual(shadow_id, shadow_entry['receipt_id'])
        with self.connect() as db:
            original = depth.read_ids(db, [original_id])[original_id]
            self.assertNotIn('official_shadow', original)
            self.assertEqual(original['known_at'], depth.clock(known))
            status = depth.read_shadow_ids(db, [shadow_id])[shadow_id]
            self.assertEqual(status['origin_id'], original_id)
            self.assertEqual(status['checkpoint_id'], checkpoint['id'])
            self.assertEqual(status['official_shadow']['source_gaps'], {'scope': reason})

    async def test_invalid_and_oversized_shadow_leave_the_original_receipt_untouched(self):
        cases = {
            'experiment_depth_shadow_evidence_invalid': dict(candidates={'malformed': {}}, source_gaps={}),
            'experiment_depth_shadow_capacity': dict(candidates={}, source_gaps={'large': 'x' * depth.MAX_BYTES}),
        }
        owner = collector.ExperimentDepth(SimpleNamespace(), connector=self.connect, stage_path=self.stage_path)
        owner.stage.initialize()
        with self.connect() as db:
            for reason, evidence in cases.items():
                with self.subTest(reason=reason):
                    task, _ = self.fixture_game(db, event_id=reason, with_replay=True)
                    known = task['target_at']-timedelta(milliseconds=100)
                    original_id = owner._stage(task, known_at=known, observations={})
                    original, = owner.stage.entries()
                    original_payload = owner.stage.load(original)
                    shadow_id = owner._stage_shadow(task, original_id, known, evidence, None)
                    shadow, = owner.shadow_stage.entries()
                    self.assertEqual(shadow['receipt_id'], shadow_id)
                    self.assertEqual(owner.shadow_stage.load(shadow)['reason'], reason)
                    self.assertEqual(owner.stage.load(original), original_payload)
                    claim, = experiment.due(db, late_only=True)
                    self.write_checkpoint(db, claim, experiment.utc(), offers=[replay_offer(task)])
                    self.assertEqual(owner._publish_staged(original), ('published', original_id))
                    self.assertEqual(owner._publish_shadow_staged(shadow), (reason, shadow_id))

    async def test_storage_deferral_keeps_decision_and_separate_followup(self):
        with self.connect() as db:
            task, _ = self.fixture_game(db, seconds_ago=70)
            stage, decision = self.stage_decision(task, book=lambda known: wide_novig_book(known, task))
            self.assertGreater(len(encoded(decision)), 512 * 1024)
            later = task['target_at'] + timedelta(seconds=15)
            followup = depth.normalize(task, kind='followup', origin_id=hashed(decision),
                cutoff_at=later, known_at=later, observations=captured_book(later))
            stage.put(followup, task['deadline_at'], experiment.utc())
            before = self.staged()
            deferred, deferred_events = self.start_collector(task, 'storage_deferred')
            self.assertEqual(await self.message(deferred, deferred_events),
                             ('publication_deferred', 'research_retention_capacity'))
            self.assertEqual(self.staged(), before)
            self.assertEqual(self.receipt_rows(db), [])
            self.assertEqual(self.dispositions(), [])
            self.stop_collector(deferred)

            recovered, recovered_events = self.start_collector(task, 'recover')
            await self.wait_until_drained(recovered, recovered_events)
            reference = (task['game_id'], task['schedule_id'], task['target_at'])
            self.assertEqual(depth.read(db, *reference), dict(decision, id=hashed(decision)))
            self.assertEqual(depth.followups(db, [hashed(decision)]),
                             {hashed(decision): dict(followup, id=hashed(followup))})
            self.assertEqual(self.dispositions(), [('published', hashed(decision)), ('published', hashed(followup))])

    async def test_smaller_receipts_pass_capacity_limited_decision_then_campaign_replays_original(self):
        from app.collection import current_storage_policy, mens_d1_jobs
        from app.research import paper_campaigns, workspace

        with self.connect() as db, self.connect() as writer:
            task, _ = self.fixture_game(db, with_replay=True)
            late, = experiment.due(db, at=experiment.utc(), late_only=True)
            checkpoint = self.write_checkpoint(db, late, experiment.utc(), offers=[replay_offer(task)])
            self.assertEqual(checkpoint['state'], 'captured')
            stage, wide = self.stage_decision(task, book=lambda known: wide_novig_book(known, task))
            self.assertGreater(len(encoded(wide)), 512 * 1024)
            later = task['target_at'] + timedelta(seconds=15)
            observed = task['target_at'] + timedelta(seconds=1)
            followup = depth.normalize(task, kind='followup', origin_id=hashed(wide),
                cutoff_at=later, known_at=observed, observations=captured_book(observed))
            stage.put(followup, task['deadline_at'], experiment.utc())
            small = []
            for label in ('first', 'second'):
                other, _ = self.fixture_game(db, seconds_ago=90, event_id=f'fixture-{label}-small-receipt')
                _, payload = self.stage_decision(other)
                small.append(payload)
            original = {row['receipt_id']: row for row in self.staged()}
            cap = current_storage_policy.sql_usage(db) + experiment.sql_runway_bytes(64 * 1024)
            now = task['deadline_at'] + timedelta(seconds=1)
            owner = collector.ExperimentDepth(SimpleNamespace(), connector=self.connect,
                                              now=lambda: now, stage_path=self.stage_path)
            with (patch.object(owner, 'enabled', return_value=True),
                  patch.object(owner, '_near_checkpoint', return_value=False),
                  patch.object(owner, '_targets', return_value=[])):
                with patch.object(current_storage_policy, 'SQL_BYTE_CAP', cap):
                    await owner.tick(None)
                    self.assertEqual([row['id'] for row in self.receipt_rows(db)], [hashed(small[0])])
                    with writer.transaction():
                        experiment._lock(writer)
                        await owner.tick(None)
                    self.assertEqual(owner.progress['reason'], 'experiment_depth_writer_busy')
                    with patch.object(mens_d1_jobs, '_late_capture_due', return_value=True):
                        await owner.tick(None)
                    self.assertEqual(owner.progress['reason'], 'protected_tminus10_capture_due')
                    self.assertEqual(self.dispositions(), [('published', hashed(small[0]))])
                    await owner.tick(None)
                    await owner.tick(None)
                    self.assertEqual(owner.progress['reason'], 'research_sql_runway')
                    self.assertEqual(self.dispositions(), [('published', hashed(payload)) for payload in small])
                    self.assertEqual({row['receipt_id']: row for row in self.staged()},
                        {hashed(payload): original[hashed(payload)] for payload in (wide, followup)})
                await owner.tick(None)
                await owner.tick(None)
                await owner.tick(None)

            self.assertEqual(self.staged(), [])
            self.assertEqual(self.dispositions(), [('published', hashed(payload)) for payload in (*small, wide, followup)])
            rows = {row['id']: row for row in self.receipt_rows(db)}
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[hashed(wide)]['payload'], wide)
            self.assertEqual(rows[hashed(wide)]['known_at'], experiment.stamp(wide['known_at']))
            self.assertEqual(rows[hashed(wide)]['cutoff_at'], task['target_at'])
            replay_at = task['target_at'] + timedelta(minutes=10)
            with (patch.object(paper_campaigns.queue, 'utc', return_value=replay_at),
                  patch.object(paper_campaigns.mens_d1, 'daily_population', return_value=None)):
                run_id = paper_campaigns.tick(db)
            self.assertIsNotNone(run_id)
            run = workspace.run_detail(db, run_id, export=True)
            self.assertEqual(run['depth_receipts'], {hashed(wide): dict(wide, id=hashed(wide))})
            game = next(game for game in run['report']['games'] if game['checkpoint_id'] == checkpoint['id'])
            self.assertEqual(game['depth_receipt_id'], hashed(wide))

    async def test_superseded_and_cancelled_schedules_are_disposed(self):
        with self.connect() as db:
            old, event = self.fixture_game(db, seconds_ago=90)
            self.stage_decision(old)
            experiment.discover(db, [dict(event, starts_at=depth.clock(
                experiment.stamp(event['starts_at']) + timedelta(hours=2)))])
            cancelled, event = self.fixture_game(db, seconds_ago=90, event_id='fixture-cancelled-game')
            self.stage_decision(cancelled)
            experiment.discover(db, [dict(event, status={'cancelled': True})])

            recovered, events = self.start_collector(cancelled, 'recover')
            await self.wait_until_drained(recovered, events)
            self.assertEqual(self.receipt_rows(db), [])
            self.assertEqual(self.dispositions(), [('schedule_no_longer_current', None)] * 2)

    async def test_corrupt_and_late_staged_evidence_is_disposed(self):
        with self.connect() as db:
            corrupt, _ = self.fixture_game(db, seconds_ago=90)
            self.stage_decision(corrupt)
            malformed, _ = self.fixture_game(db, seconds_ago=90, event_id='fixture-malformed-deadline')
            self.stage_decision(malformed)
            late, _ = self.fixture_game(db, seconds_ago=90, event_id='fixture-late-evidence')
            _, payload = self.stage_decision(late)
            after_cutoff = depth.clock(late['target_at'] + timedelta(seconds=1))
            known = experiment.stamp(payload['known_at'])
            past_cutoff = captured_book(known)
            past_cutoff['fixture-offer']['receipts'][0]['received_at'] = after_cutoff
            with self.assertRaisesRegex(ValueError, 'experiment_depth_receipt_clock'):
                depth.normalize(late, known_at=known, observations=past_cutoff)

            evidence = next(iter(payload['http_receipts'].values()))
            evidence['received_at'] = after_cutoff
            with closing(sqlite3.connect(self.stage_path)) as spool, spool:
                spool.execute("UPDATE staged SET body=? WHERE game_id=?", (b'corrupt', corrupt['game_id']))
                spool.execute("UPDATE staged SET deadline_at=? WHERE game_id=?",
                              ('bad timestamp', malformed['game_id']))
                # A checksum match alone cannot make a post-cutoff receipt causal.
                spool.execute("UPDATE staged SET body=?,receipt_id=? WHERE game_id=?",
                              (encoded(payload), hashed(payload), late['game_id']))

            recovered, events = self.start_collector(late, 'recover')
            await self.wait_until_drained(recovered, events)
            self.assertEqual(self.receipt_rows(db), [])
            self.assertEqual(self.dispositions(), [
                ('experiment_depth_stage_checksum', None), ('experiment_depth_stage_deadline', None),
                ('experiment_depth_receipt_clock', None)])
