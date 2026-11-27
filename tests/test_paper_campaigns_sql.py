"""Disposable scheduled run publication, immutable inputs and passive rollups."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction as F
from unittest import skipUnless
from unittest.mock import patch

from app.research import paper, paper_campaigns as campaigns, workspace
from app.storage import paper_result_queue as queue
from app.storage.store import encoded, hashed, stamp
from psycopg.types.json import Jsonb
from tests.latest_board_fixture import SOCKET
from tests.test_paper_campaigns import config, fixed_config
from tests.test_paper_experiments import frozen_priced, linear
from tests.test_paper_experiments_sql import ResearchWorkspaceFixture


@skipUnless(SOCKET,'Disposable PostgreSQL required')
class CampaignSQL(ResearchWorkspaceFixture):
    async def asyncSetUp(self):
        with self.connect() as db:
            db.execute('''TRUNCATE public.ev_experiment_game,public.ev_experiment_record,public.paper_campaign,
                public.research_workspace_run,public.paper_result_input CASCADE''')
            db.execute('INSERT INTO public.ev_experiment_accounting(singleton) VALUES (true) ON CONFLICT DO NOTHING')

    async def test_discovery_keeps_canonical_and_new_revisions_and_leaves_archived_rows(self):
        await super().asyncSetUp()
        with self.connect() as db:
            archived = campaigns.create(db, config(), discoverable=False)
            canonical = campaigns.configuration(fixed_config(name='Win $10'))
            db.execute('INSERT INTO public.paper_campaign VALUES (%s,DEFAULT,%s,%s)',
                       (campaigns.WIN_10_CAMPAIGN, Jsonb(canonical), len(encoded(canonical))))
            assert [campaign['id'] for campaign in campaigns.index(db, active_only=True)] == [campaigns.WIN_10_CAMPAIGN]
            db.execute('UPDATE public.paper_campaign_day SET next_check_at=%s', (self.at,))
            with patch.object(campaigns.queue, 'utc', return_value=self.at), \
                    patch.object(campaigns.queue, '_late_capture_due', return_value=False), \
                    patch.object(campaigns.mens_d1, 'daily_population') as read_capture:
                assert campaigns.tick(db) is None
                read_capture.assert_not_called()
            current = campaigns.create(db, fixed_config(name='New experiment'))
            revised = campaigns.create(db, fixed_config(name='New experiment', target_profit_usd='11', supersedes=current['id']))
            assert [campaign['id'] for campaign in campaigns.index(db, active_only=True)] == [
                campaigns.WIN_10_CAMPAIGN, revised['id']]
            assert {campaign['id'] for campaign in campaigns.index(db)} == {
                campaigns.WIN_10_CAMPAIGN, archived['id'], current['id'], revised['id']}
            assert campaigns.view(db, current['id'])['config']['target_profit_usd'] == '10'
            assert len(campaigns.view(db, archived['id'])['days']) == 7
            with_floor = campaigns.create(db, fixed_config(name='Win $10', minimum_stake_usd='1.00',
                                                            supersedes=campaigns.WIN_10_CAMPAIGN))
            newer = campaigns.create(db, fixed_config(name='Created afterward'))
            assert [campaign['id'] for campaign in campaigns.index(db, active_only=True)] == [
                with_floor['id'], newer['id'], revised['id']]
            assert campaigns.view(db, with_floor['id'])['config']['minimum_stake_usd'] == '1'
            assert 'minimum_stake_usd' not in campaigns.view(db, campaigns.WIN_10_CAMPAIGN)['config']
            latest = campaigns.create(db, fixed_config(name='Win $10', minimum_stake_usd='2',
                                                        supersedes=with_floor['id']))
            discovery = campaigns.discovery(db)
            assert [campaign['id'] for campaign in discovery['campaigns']] == [
                latest['id'], newer['id'], revised['id']]
            assert discovery['successors'] == {
                campaigns.WIN_10_CAMPAIGN: latest['id'], with_floor['id']: latest['id'],
                current['id']: revised['id'],
            }

    async def test_ui_configuration_queues_seven_days_and_publishes_repriced_snapshot_once(self):
        await super().asyncSetUp()
        with self.connect() as db:
            event=self.game('game','2026-11-23T18:00:00Z')
            from app.research import experiment
            experiment.discover(db,[event],at=self.at)
            self.capture(db,'early',event)
            self.advance(db,stamp('2026-11-23T17:50:00Z'))
            self.capture(db,'late',event)
            parent=workspace._definition(db,workspace.PILOT_VERSION)
            frozen=hashed(parent)
            campaign=campaigns.create(db,config())
            assert campaigns.create(db,config())['id']==campaign['id']
            assert db.execute('SELECT count(*) n FROM public.paper_campaign_day').fetchone()['n']==7
            assert campaigns.view(db, campaign['id'], 'best_venue')['weekly'] is None
            db.execute('UPDATE public.paper_campaign_day SET next_check_at=%s',(self.at,))
            population=dict(kind='reconciled_occurrences',source='fixture',membership_version='fixture',
                revision='p'*64,observed_at=self.at.isoformat(),expected_games=None,
                games=[dict(scope_state='eligible',paper_eligible=True,provider_event_id='game',
                            occurrence_id='game',title='Away at game',starts_at=event['starts_at'])])
            with patch.object(campaigns.queue,'utc',return_value=self.at), \
                    patch.object(campaigns.queue,'_late_capture_due',return_value=False), \
                    patch.object(campaigns.mens_d1,'daily_population',return_value=population), \
                    patch.object(campaigns.mens_d1,'daily_recovery',return_value={}), \
                    patch.object(paper.math,'calculate',side_effect=linear):
                run_id=campaigns.tick(db)
            assert run_id, db.execute('SELECT state,last_error FROM public.paper_campaign_day ORDER BY game_date').fetchall()
            run=workspace.run_detail(db,run_id)
            assert run['definition']['campaign_id']==campaign['id']
            assert run['report']['policy']['sizing_scale_usd']=='250'
            assert hashed(workspace._definition(db,workspace.PILOT_VERSION))==frozen
            assert queue.read(db,run_id,status_only=True)['pending']
            assert campaigns.view(db,campaign['id'],'best_venue')['days'][0]['run_id']==run_id
            # Unchanged capture evidence must reopen the same run, never compound stake.
            with patch.object(campaigns.queue,'utc',return_value=self.at+timedelta(minutes=16)), \
                    patch.object(campaigns.queue,'_late_capture_due',return_value=False), \
                    patch.object(campaigns.mens_d1,'daily_population',return_value=population):
                assert campaigns.tick(db)==run_id
            assert db.execute('SELECT count(*) n FROM public.research_workspace_run WHERE id=%s',(run_id,)).fetchone()['n']==1

            # An expired claim survives process exit. A fresh worker can still
            # examine a historical day when original evidence changes later.
            later = self.at + timedelta(days=8)
            db.execute('UPDATE public.paper_campaign_day SET next_check_at=%s', (later + timedelta(days=1),))
            db.execute('''UPDATE public.paper_campaign_day SET next_check_at=%s,lease_until=%s
                WHERE campaign_id=%s AND game_date=%s''', (self.at, later-timedelta(seconds=1),
                campaign['id'], '2026-11-23'))
            population['revision'] = 'q'*64
            with self.connect() as restarted, patch.object(campaigns.queue,'utc',return_value=later), \
                    patch.object(campaigns.queue,'_late_capture_due',return_value=False), \
                    patch.object(campaigns.mens_d1,'daily_population',return_value=population), \
                    patch.object(campaigns.mens_d1,'daily_recovery',return_value={}), \
                    patch.object(paper.math,'calculate',side_effect=linear):
                replacement = campaigns.tick(restarted)
            assert replacement and replacement != run_id
            published = campaigns.view(db, campaign['id'], 'best_venue')['days'][0]
            assert published['run_id'] == replacement
            assert [snapshot['id'] for snapshot in published['snapshots']] == [replacement, run_id]
            assert workspace._run(db, replacement)['supersedes'] == run_id

            unchanged = campaigns.create(db, dict(config(), supersedes=campaign['id']))
            assert unchanged == campaign
            revised_config = dict(config(), supersedes=campaign['id'], kelly_multiplier='1/80')
            revision = campaigns.create(db, revised_config)
            assert revision['id'] != campaign['id'] and revision['supersedes'] == campaign['id']
            assert campaigns.create(db, revised_config) == revision
            assert campaigns.view(db, campaign['id'], 'best_venue')['days'][0]['run_id'] == replacement

    async def test_paired_sizing_rolls_back_together_and_grades_both_arrival_orders(self):
        from app.dashboard import paper_results_view
        from app.research import experiment

        await super().asyncSetUp()
        with self.connect() as db:
            event = self.game('paired', '2026-11-23T18:00:00Z')
            experiment.discover(db, [event], at=self.at)
            self.capture(db, 'early', event)
            self.advance(db, stamp('2026-11-23T17:50:00Z'))
            task = experiment.due(db, at=self.at)[0]
            offer = frozen_priced('+300', venue='prophetx')
            record = offer['record']
            record['event'].update(scheduled_start=event['starts_at'], competition='NCAAB')
            record['market_identity']['rules'] = 'sportsgameodds-unverified-1'
            record['result_policy'] = 'sportsgameodds-unverified-1:spread'
            record['quote']['source'].update(native_event_id='paired', native_outcome_id='points-home-game-sp-home',
                                             native_line='-3')
            snapshot = dict(event=dict(home='home', away='away', competition='NCAAB', scheduled_start=event['starts_at']),
                            source_event=dict(event_id='paired'), offers=[offer], coverage=dict(incomplete=False))
            assert experiment.capture(db, task['game_id'], 'late', snapshot, token=task['token'],
                requested_at=self.at, received_at=self.at, known_at=self.at)['state'] == 'captured'
            body = fixed_config(end_date='2026-11-24')
            with patch.object(queue, 'utc', return_value=self.at):
                campaign = campaigns.create(db, body)
                assert campaigns.create(db, body) == campaign
                assert [day['replay_state'] for day in campaigns.view(db, campaign['id'])['days']] == [
                    'replay_queued', 'scheduled']
                db.execute('''UPDATE public.paper_campaign_day SET lease_until=%s
                    WHERE campaign_id=%s AND game_date=%s''',
                    (self.at + timedelta(minutes=1), campaign['id'], '2026-11-23'))
                assert campaigns.view(db, campaign['id'])['days'][0]['replay_state'] == 'replaying'
                db.execute('UPDATE public.paper_campaign_day SET lease_until=NULL WHERE campaign_id=%s',
                           (campaign['id'],))
            population = dict(kind='reconciled_occurrences', source='fixture', membership_version='fixture',
                revision='p'*64, observed_at=self.at.isoformat(), expected_games=None,
                games=[dict(scope_state='eligible', paper_eligible=True, provider_event_id='paired',
                            occurrence_id='paired', title='Away at paired', starts_at=event['starts_at'])])
            real_publish = workspace._publish

            def deny_second(db, day, parent, definition, report, *, details):
                if definition['sizing_mode'] == 'kelly':
                    raise RuntimeError('fixture failure during second mode publication')
                return real_publish(db, day, parent, definition, report, details=details)

            with (patch.object(queue, '_late_capture_due', return_value=False),
                  patch.object(campaigns.mens_d1, 'daily_population', return_value=population),
                  patch.object(campaigns.mens_d1, 'daily_recovery', return_value={})):
                with patch.object(queue, 'utc', return_value=self.at), patch.object(workspace, '_publish', deny_second):
                    assert campaigns.tick(db) is None
                assert db.execute('SELECT count(*) n FROM public.research_workspace_run').fetchone()['n'] == 0
                current = campaigns.view(db, campaign['id'])['days'][0]
                assert current['state'] == 'failed'
                assert current['error'] == campaigns.REPLAY_FAILED
                legacy = 'OperationalError: synthetic path and token'
                db.execute("UPDATE public.paper_campaign_day SET last_error=%s WHERE state='failed'", (legacy,))
                assert campaigns.view(db, campaign['id'])['days'][0]['error'] == campaigns.REPLAY_FAILED
                assert db.execute("SELECT last_error FROM public.paper_campaign_day WHERE state='failed'"
                                  ).fetchone()['last_error'] == legacy
                self.advance(db, stamp('2026-11-23T18:10:00Z'))
                with self.connect() as restarted, patch.object(queue, 'utc', return_value=self.at):
                    primary = campaigns.tick(restarted)
                assert primary, campaigns.view(db, campaign['id'])['days'][0]
                first_day, future_day = campaigns.view(db, campaign['id'])['days']
                pair = first_day['run_ids']
                assert first_day['run_id'] == pair['fixed_profit'] == primary
                assert future_day['state'] == 'scheduled' and not future_day['run_ids']
                assert stamp(future_day['next_check_at']) == stamp('2026-11-24T00:00:00-05:00')
                assert first_day['comparison']['jointly_qualifying_quotes'] == 1
                pending = campaigns.view(db, campaign['id'], 'best_venue', mode='fixed_profit',
                                         include_comparison=False)
                assert pending['weekly'] is None and pending['reported_days'] == 0
                assert pending['selection'] == pending['days'][0]['selection']
                assert pending['selection']['tickets'] == 1
                assert F(pending['selection']['stake_exact_usd']) > 0
                assert F(pending['selection']['expected_profit_exact_usd']) > 0
                assert F(pending['selection']['expected_roi']) == (
                    F(pending['selection']['expected_profit_exact_usd']) / F(pending['selection']['stake_exact_usd']))
                bucket = next(b for b in pending['selection']['odds_buckets'] if b['id'] == 'plus_300_to_500')
                assert bucket['stake_share'] == '1' and bucket['summary']['tickets'] == 1
                assert bucket['summary']['resolved'] == 0 and bucket['summary']['pnl_usd'] is None
                assert pending['days'][0]['run_ids'] == {'fixed_profit': primary}
                assert pending['comparison'] is None and 'comparison' not in pending['days'][0]
                first = {mode: workspace.run_detail(db, run_id) for mode, run_id in pair.items()}
                assert all(run['sizing_runs'] == pair for run in first.values())
                assert len({run['report']['as_of'] for run in first.values()}) == 1
                assert len({run['report']['games'][0]['checkpoint_id'] for run in first.values()}) == 1
                assert first['fixed_profit']['definition']['policy']['target_profit_usd'] == '10'
                assert first['kelly']['definition']['policy']['kelly_multiplier'] == '1/40'
                assert 'kelly_multiplier' not in first['fixed_profit']['definition']['policy']
                policies = [first[mode]['definition']['policy'] for mode in ('fixed_profit', 'kelly')]
                replay = dict(population=deepcopy(population), as_of=first['fixed_profit']['report']['as_of'], evidence=True)
                with patch.object(experiment, '_closure', wraps=experiment._closure) as closure:
                    streamed = paper.scoped_reports(db, '2026-11-23', policies, **replay)
                    assert closure.call_count == 1
                independent = [paper.report(db, '2026-11-23', policy=policy, **replay) for policy in policies]
                assert encoded(streamed) == encoded(independent)
                assert queue.process_one(db) and queue.process_one(db)
                assert all(queue.read(db, run_id)['report']['games'][0]['result']['state'] == 'pending'
                           for run_id in pair.values())
                self.advance(db, stamp('2026-11-23T20:00:00Z'))
                observed = self.at.isoformat()
                final = dict(event, source='sportsgameodds', final=True, result='completed', home_score=92,
                             away_score=80, received_at=observed, knowledge_at=observed,
                             receipt_sha256=hashed(['paired-result', 92]))
                assert experiment.observe_outcomes(db, [final], at=self.at)['matched'] == 1
                assert queue.dispatch(db) == 1
                assert queue.process_one(db) and queue.process_one(db)
                new_config = fixed_config(name='Different date range and target', end_date='2026-11-23',
                                          target_profit_usd='13', portfolios=['all_venues'])
                with patch.object(queue, 'utc', return_value=self.at):
                    assert campaigns.tick(db) == primary
                    second = campaigns.create(db, new_config)
                    assert campaigns.tick(db)
                assert queue.process_one(db) and queue.process_one(db)
                assert queue.process_one(db) is None
                second_day = campaigns.view(db, second['id'])['days'][0]
                assert campaigns.view(db, second['id'])['variant'] == 'all_venues'
                revised_config = dict(new_config, supersedes=second['id'], target_profit_usd='17')
                revision = campaigns.create(db, revised_config)
                assert (revision['supersedes'], revision['target_profit_usd']) == (second['id'], '17')
                assert campaigns.create(db, revised_config) == revision

            for identity, run_ids, variant in ((campaign['id'], pair, 'best_venue'),
                                              (second['id'], second_day['run_ids'], 'all_venues')):
                observed_trade = {}
                for mode, run_id in run_ids.items():
                    view = paper_results_view.read(db, run_id, variant=variant, version_id=None, status_only=False)
                    report = view['report']
                    assert report['status'] == 'graded', report['portfolios'][variant]['tickets']
                    assert report['sizing_policy']['sizing_mode'] == mode
                    trade = paper_results_view.export(view, 'trades')['rows'][0]
                    observed_trade[mode] = trade
                    campaign_trades = campaigns.trades(db, identity, variant, mode)
                    ledger, = campaign_trades['trades']
                    assert (ledger['id'], ledger['run_id'], ledger['result_id'], ledger['league']) == (
                        trade['id'], run_id, view['version']['id'], 'NCAAB')
                    rollup = campaigns.view(db, identity, variant, mode=mode)
                    assert rollup['reported_days'] == 1
                    daily = rollup['days'][0]['analysis']['summary']
                    weekly = rollup['weekly']['summary']
                    for field in ('stake_exact_usd', 'return_exact_usd', 'pnl_exact_usd'):
                        assert trade[field] == ledger[field] == daily[field] == weekly[field] == campaign_trades['summary'][field]
                    for field in ('resolved', 'tickets', 'roi_percent'):
                        assert campaign_trades['summary'][field] == weekly[field]
                    assert F(weekly['roi']) == F(trade['pnl_exact_usd']) / F(trade['stake_exact_usd'])
                    assert rollup['selection']['tickets'] == 1
                    assert F(rollup['selection']['stake_exact_usd']) == F(trade['stake_exact_usd'])
                    assert F(rollup['selection']['expected_profit_exact_usd']) == F(trade['expected_profit_exact_usd'])
                    assert F(rollup['selection']['expected_roi']) == F(trade['ev'])
                    odds_buckets = rollup['selection']['odds_buckets']
                    assert odds_buckets == rollup['days'][0]['selection']['odds_buckets']
                    assert odds_buckets == report['portfolios'][variant]['odds_buckets']
                    assert odds_buckets == paper_results_view.export(view, 'report')['report']['portfolios'][variant]['odds_buckets']
                    assert 'odds_buckets' not in queue.read(db, run_id)['report']['portfolios'][variant]
                    assert F(weekly['pnl_vs_expected_exact_usd']) == (
                        F(trade['pnl_exact_usd']) - F(trade['expected_profit_exact_usd']))
                assert observed_trade['fixed_profit']['id'] != observed_trade['kelly']['id']
                assert observed_trade['fixed_profit']['frozen_quote_id'] == observed_trade['kelly']['frozen_quote_id']
                fixed = observed_trade['fixed_profit']
                assert F(fixed['pnl_exact_usd']) == F(fixed['sizing']['modeled_win_profit_usd'])
                assert fixed['sizing']['target_profit_usd'] == ('10' if identity == campaign['id'] else '13')

    async def test_all_sports_campaign_replays_other_leagues_and_keeps_results_separate(self):
        from app.research import experiment

        await super().asyncSetUp()
        nba = dict(self.game('NBA game', '2026-11-23T18:00:00Z'), league='NBA')
        college = self.game('D1 game', '2026-11-23T18:05:00Z')
        offers = [frozen_priced('+550', line='-3'), frozen_priced('+399', line='-4', main=False),
                  frozen_priced('+400', line='-5', main=False)]
        for offer in offers:
            record = offer['record']
            record['event'].update(scheduled_start=nba['starts_at'], competition='NBA')
            record['market_identity']['rules'] = 'sportsgameodds-unverified-1'
            record['result_policy'] = 'sportsgameodds-unverified-1:spread'
            record['quote']['source'].update(native_event_id=nba['source_event_id'],
                native_outcome_id='points-home-game-sp-home', native_line=record['selection']['signed_line'])
        snapshot = dict(event=dict(home='home', away='away', competition='NBA', scheduled_start=nba['starts_at']),
                        source_event=dict(event_id=nba['source_event_id']), offers=offers, coverage=dict(incomplete=False))
        config = fixed_config(name='Win $25 across all sports', end_date='2026-12-07',
                              scope=campaigns.ALL_SPORTS, market_scope=paper.MAIN_SPREADS_TOTALS,
                              alternate_odds_below='+400', target_profit_usd='25',
                              kelly_comparison=False, portfolios=['all_venues'])
        for field in ('kelly_multiplier', 'reference_bankroll_usd'):
            config.pop(field)
        with self.connect() as db, patch.object(queue, '_late_capture_due', return_value=False):
            experiment.discover(db, [nba], at=self.at)
            for checkpoint, at in (('early', self.at), ('late', stamp('2026-11-23T17:50:00Z'))):
                self.advance(db, at)
                task, = experiment.due(db, at=self.at)
                assert task['checkpoint'] == checkpoint
                assert experiment.capture(db, task['game_id'], checkpoint, snapshot, token=task['token'],
                    requested_at=at, received_at=at, known_at=at)['state'] == 'captured'
            experiment.discover(db, [college], at=self.at)
            self.advance(db, stamp('2026-11-23T18:01:00Z'))
            # The basketball slate does not have to exist for the provider-tracked replay.
            with patch.object(queue, 'utc', return_value=self.at):
                campaign = campaigns.create(db, config)
                assert campaign == campaigns.create(db, dict(config, alternate_odds_below='400'))
                assert len(campaigns.view(db, campaign['id'])['days']) == 15
                assert not campaigns.trades(db, campaign['id'])['trades']
                run_id = campaigns.tick(db)
            assert run_id
            run = workspace.run_detail(db, run_id)['report']
            assert run['policy']['leagues'] == campaign['leagues']
            assert run['policy']['alternate_odds_below'] == '400'
            assert run['policy']['budget_cap'] is None and 'minimum_stake_usd' not in run['policy']
            assert {game['title'] for game in run['games']} == {nba['title'], college['title']}
            tickets = run['portfolios']['all_venues']['tickets']
            assert {F(ticket['posted_odds']) for ticket in tickets} == {399, 550}
            assert all(ticket['sizing']['target_profit_usd'] == '25' for ticket in tickets)
            with patch.object(queue, 'utc', return_value=self.at):
                pending = campaigns.trades(db, campaign['id'])
            assert pending['summary']['resolved'] == 0
            assert pending['summary']['tickets'] == len(tickets)
            assert pending['summary']['pnl_usd'] is pending['summary']['roi_percent'] is None
            pending = pending['trades']
            assert {trade['screen_ev'] for trade in pending} == {ticket['screen_ev'] for ticket in tickets}
            assert {trade['game_title'] for trade in pending} == {nba['title']}
            assert {trade['league'] for trade in pending} == {'NBA'}
            assert {trade['game_date'] for trade in pending} == {'2026-11-23'}
            assert all(trade['pnl_usd'] is None and trade['result_id'] is None and trade['grade']['state'] == 'pending'
                       and trade['run_id'] == run_id for trade in pending)

            # A final attaches via the result queue while the opportunity snapshot stays fixed.
            first_result = queue.process_one(db)
            assert first_result
            self.advance(db, stamp('2026-11-23T20:00:00Z'))
            observed = self.at.isoformat()
            final = dict(nba, source='sportsgameodds', final=True, result='completed', home_score=92,
                         away_score=80, received_at=observed, knowledge_at=observed,
                         receipt_sha256=hashed(['nba-result', 92]))
            assert experiment.observe_outcomes(db, [final], at=self.at)['matched'] == 1
            assert queue.dispatch(db) == 1
            latest_result = queue.process_one(db)
            assert latest_result and latest_result != first_result
            report = queue.read(db, run_id)['report']
            assert {game['title']: game['result']['state'] for game in report['games']} == {
                nba['title']: 'final', college['title']: 'pending',
            }
            assert {ticket['grade']['state'] for ticket in report['portfolios']['all_venues']['tickets']} == {'win'}
            with patch.object(queue, 'utc', return_value=self.at):
                graded = campaigns.trades(db, campaign['id'])['trades']
                assert campaigns.tick(db) == run_id
            assert len(graded) == len(pending)
            assert {trade['result_id'] for trade in graded} == {latest_result}
            assert {trade['grade']['state'] for trade in graded} == {'win'}

            self.advance(db, self.at + timedelta(minutes=16))
            moved = [dict(event, starts_at=event['starts_at'].replace('11-23', '11-24'))
                     for event in (nba, college)]
            assert experiment.discover(db, moved, at=self.at)['rescheduled'] == 2
            with patch.object(queue, 'utc', return_value=self.at):
                replacement = campaigns.tick(db)
                campaign_view = campaigns.view(db, campaign['id'])
                assert not campaigns.trades(db, campaign['id'])['trades']
            assert replacement and replacement != run_id
            assert workspace._run(db, replacement)['supersedes'] == run_id
            assert workspace.run_detail(db, replacement)['report']['games'] == []
            assert len(workspace.run_detail(db, run_id)['report']['games']) == 2
            assert campaign_view['selection'] is None

    async def test_depth_receipts_replace_a_partial_main_and_pin_all_campaign_views(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        from app.dashboard import research_workspace_api
        from app.dashboard.request_guard import dashboard_guard
        from app.research import experiment, paper_depth
        from app.storage import experiment_depth
        from tests.test_experiment_depth_execution import receipt

        await super().asyncSetUp()
        day = '2026-11-23'
        game = self.game('depth', f'{day}T18:00:00Z')
        main = frozen_priced('+300', venue='novig', line='-10.5')
        alternate = frozen_priced('+300', venue='novig', line='-16.5', main=False)
        for offer in (main, alternate):
            record = offer['record']
            record['event'].update(scheduled_start=game['starts_at'], competition='NCAAB')
            record['market_identity']['rules'] = 'sportsgameodds-unverified-1'
            record['result_policy'] = 'sportsgameodds-unverified-1:spread'
            record['quote']['source'].update(native_event_id=game['source_event_id'],
                native_outcome_id='points-home-game-sp-home', native_line=record['selection']['signed_line'])
        snapshot = dict(event=dict(home='home', away='away', competition='NCAAB', scheduled_start=game['starts_at']),
                        source_event=dict(event_id=game['source_event_id']), offers=[main, alternate],
                        coverage=dict(incomplete=False))
        config = fixed_config(name='Win $25 depth', end_date=day, scope=campaigns.ALL_SPORTS,
                              market_scope=paper.MAIN_SPREADS_TOTALS, alternate_odds_below='400',
                              target_profit_usd='25', kelly_comparison=False, portfolios=['best_venue'],
                              portfolio_rule=paper.MAIN_FIRST_ONE_PER_GAME, depth_policy=paper_depth.VERSION)
        for field in ('kelly_multiplier', 'reference_bankroll_usd'):
            config.pop(field)
        grading_clock = queue.utc
        with (self.connect() as db, patch.object(queue, '_late_capture_due', return_value=False),
              patch.object(queue, 'utc', side_effect=lambda: self.at),
              patch.object(campaigns.mens_d1, 'daily_population', return_value=None)):
            campaign = campaigns.create(db, config)
            assert campaign['leagues'] == ['NCAAB']
            experiment.discover(db, [game], at=self.at)
            for checkpoint, at in (('early', self.at), ('late', stamp(f'{day}T17:50:00Z'))):
                self.advance(db, at)
                task, = experiment.due(db, at=self.at)
                frozen = experiment.capture(db, task['game_id'], checkpoint, snapshot, token=task['token'],
                    requested_at=at, received_at=at, known_at=at)
                assert frozen['state'] == 'captured'
            before = campaigns.tick(db)
            old = workspace.run_detail(db, before, export=True)
            assert old['depth_receipts'] == {}
            assert old['report']['depth_analysis']['scenarios']['quoted']['unknown_reasons'] == {'no_decision_receipt': 1}
            assert not old['report']['portfolios']['best_venue']['tickets']

            # An independently known receipt may reach storage after the odds checkpoint.
            observations = {
                experiment_depth.offer_key(main['record']): receipt(('0.25', 2000)),
                experiment_depth.offer_key(alternate['record']): receipt(('0.25', 4000)),
            }
            evidence = experiment_depth.save(db, task, known_at=self.at, observations=observations)
            self.advance(db, self.at + timedelta(minutes=16))
            after = campaigns.tick(db)
            assert after != before
            run = workspace.run_detail(db, after, export=True)
            assert set(run['depth_receipts']) == {evidence['id']}
            assert workspace.run_detail(db, before, export=True)['depth_receipts'] == {}
            candidate, = run['report']['portfolios']['best_venue']['tickets']
            assert F(candidate['line']) == F('-16.5')
            assert candidate['depth']['status'] == 'full_size'
            assert candidate['depth']['modeled_native_quantity'] == '3333'
            assert candidate['depth']['modeled_win_profit_usd'] == '24.9975'
            assert run['report']['depth_analysis']['scenarios']['depth']['replacements'] == 1
            target = stamp(task['target_at'])
            followup = experiment_depth.save(db, task, kind='followup', origin_id=evidence['id'],
                known_at=target + timedelta(seconds=29),
                cutoff_at=target + timedelta(seconds=30), observations={
                    experiment_depth.offer_key(main['record']): receipt(reason='followup_cache_reuse'),
                })
            self.advance(db, self.at + timedelta(minutes=16))
            assert campaigns.tick(db) == after
            self.advance(db, stamp(f'{day}T20:00:00Z'))
            observed = self.at.isoformat()
            final = dict(game, source='sportsgameodds', final=True, result='completed', home_score=96,
                         away_score=75, received_at=observed, knowledge_at=observed,
                         receipt_sha256=hashed(['depth-result', 96]))
            assert experiment.observe_outcomes(db, [final], at=self.at)['matched'] == 1
            with patch.object(queue, 'utc', side_effect=grading_clock):
                assert queue.dispatch(db) == 1
                assert queue.process_one(db)
                assert queue.process_one(db)
            ledger = campaigns.trades(db, campaign['id'])
            assert ledger['trades'][0]['grade']['state'] == 'win'
            assert F(ledger['summary']['pnl_exact_usd']) == F('24.9975')

        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        research_workspace_api.mount(app, campaigns_only=True)
        route = f'{research_workspace_api.BASE}/campaigns/{campaign["id"]}'
        with (patch.object(research_workspace_api, 'connect', side_effect=self.connect),
              patch.object(queue, 'utc', side_effect=lambda: self.at)):
            async with TestClient(TestServer(app)) as client:
                trades = await client.get(route + '/trades')
                days = await client.get(route)
                export = await client.get(route + '/trades', params=dict(export='1'))
                assert trades.status == days.status == export.status == 200
                values, by_day, bundle = await trades.json(), await days.json(), await export.json()
                assert values['depth_analysis'] == by_day['days'][0]['depth_analysis'] == bundle['depth_analysis']
                assert values['trades'][0]['id'] == bundle['trades'][0]['id'] == candidate['id']
                dispositions = {row['depth']['status']: row['depth'] for row in values['depth_candidates']}
                assert dispositions['partial_size']['available_purchase_usd'] == '5'
                assert dispositions['partial_size']['available_gross_win_profit_usd'] == '15'
                assert set(bundle['depth_receipts']) == {evidence['id']}
                assert bundle['depth_followups'][evidence['id']]['id'] == followup['id']
                assert values['depth_followup_analysis']['cache_reuse_sides'] == 1
                assert values['depth_followup_analysis'] == by_day['days'][0]['depth_followup_analysis']

    async def test_all_sports_prospective_cutover_clips_decisions_and_finishes_grades(self):
        from app.collection.experiment_depth import targets
        from app.research import experiment, paper_depth
        from app.storage import experiment_depth
        from tests.test_experiment_depth_execution import receipt

        await super().asyncSetUp()
        now = queue.utc()
        start = (now.astimezone(campaigns.EASTERN) + timedelta(days=2)).replace(
            hour=18, minute=0, second=0, microsecond=0)
        day = str(start.date())
        first = start - timedelta(minutes=10)
        retirement = first + timedelta(minutes=5)
        moments = (first-timedelta(minutes=5), first, retirement)
        fixtures = {}
        for label, at in zip(('before_start', 'eligible', 'at_retirement'), moments, strict=True):
            game = dict(self.game(label, (at+timedelta(minutes=10)).isoformat()), league='NBA')
            offer = frozen_priced('+300', venue='novig', line='-5.5')
            record = offer['record']
            record['event'].update(scheduled_start=game['starts_at'], competition='NBA')
            record['market_identity']['rules'] = 'sportsgameodds-unverified-1'
            record['result_policy'] = 'sportsgameodds-unverified-1:spread'
            record['quote']['source'].update(native_event_id=label,
                native_outcome_id='points-home-game-sp-home', native_line='-5.5')
            snapshot = dict(event=dict(home='home', away='away', competition='NBA',
                                       scheduled_start=game['starts_at'], title=game['title']),
                            source_event=dict(event_id=label),
                            offers=[offer], coverage=dict(incomplete=False))
            fixtures[label] = game, snapshot, offer

        body = fixed_config(name='Win $25 prospective', start_date=day, end_date=str(start.date()+timedelta(days=1)),
                            scope=campaigns.ALL_SPORTS, market_scope=paper.MAIN_SPREADS_TOTALS,
                            alternate_odds_below='400', target_profit_usd='25', kelly_comparison=False,
                            portfolios=['best_venue'], portfolio_rule=paper.MAIN_FIRST_ONE_PER_GAME)
        for name in ('kelly_multiplier', 'reference_bankroll_usd'):
            body.pop(name)
        with (self.connect() as db, patch.object(queue, 'utc', side_effect=lambda: self.at),
              patch.object(queue, '_late_capture_due', return_value=False),
              patch.object(campaigns.mens_d1, 'daily_population', return_value=None)):
            self.advance(db, now)
            db.execute('ALTER TABLE public.ev_experiment_depth ALTER COLUMN recorded_at SET DEFAULT public.workspace_fixture_now()')
            active = campaigns.create(db, dict(body, name='Unrelated quote campaign'))
            config = dict(body, depth_policy=paper_depth.ALL_SPORTS_VERSION, prospective_start_at=first.isoformat())
            prepared = campaigns.create(db, config)
            assert set(prepared['leagues']) == {'NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL'}
            assert 'minimum_stake_usd' not in prepared
            with self.assertRaisesRegex(workspace.SelectionError, 'in the future'):
                campaigns.create(db, dict(config, prospective_start_at=(now-timedelta(seconds=1)).isoformat()))
            cutoff = campaigns.retire(db, prepared['id'], {'cutoff_at': retirement.isoformat()})
            assert stamp(cutoff['cutoff_at']) == retirement
            assert campaigns.retire(db, prepared['id'], {'cutoff_at': retirement.isoformat()}) == cutoff
            with self.assertRaisesRegex(workspace.SelectionError, 'already has a retirement'):
                campaigns.retire(db, prepared['id'], {'cutoff_at': (retirement+timedelta(seconds=5)).isoformat()})

            self.advance(db, first-timedelta(hours=1))
            experiment.discover(db, [value[0] for value in fixtures.values()], at=self.at)
            for task in experiment.due(db, at=self.at, limit=3):
                _, snapshot, _ = fixtures[task['event']['source_event_id']]
                assert experiment.capture(db, task['game_id'], 'early', snapshot, token=task['token'],
                    requested_at=self.at, received_at=self.at, known_at=self.at)['state'] == 'captured'
            evidence_ids = {}
            expected_targets = ([], ['eligible'], [])
            for at, expected in zip(moments, expected_targets, strict=True):
                query_at = at-timedelta(seconds=1)
                assert [task['source_event_id'] for task in targets(db, query_at)] == expected
                if at == retirement:
                    next_campaign = campaigns.create(db, dict(config, name='Unrelated depth campaign',
                                                               prospective_start_at=retirement.isoformat()))
                    assert [task['source_event_id'] for task in targets(db, query_at)] == ['at_retirement']
                self.advance(db, at)
                task, = experiment.due(db, at=at)
                label = task['event']['source_event_id']
                game, snapshot, offer = fixtures[label]
                assert experiment.capture(db, task['game_id'], 'late', snapshot, token=task['token'],
                    requested_at=at, received_at=at, known_at=at)['state'] == 'captured'
                bound = dict(receipt(('0.25', 4000)), received_at=at.isoformat(),
                    valid_until=(at+timedelta(seconds=5)).isoformat(),
                    contract=dict(league='NBA', family='spread', period='full_game', starts_at=game['starts_at'],
                        selected_side='home', signed_line='-5.5', phase='pregame',
                        settlement=dict(available=True, rule_id='fixture', overtime='included',
                                        equality='not_feasible')))
                stored = experiment_depth.save(db, task, known_at=at,
                    observations={experiment_depth.offer_key(offer['record']): bound})
                evidence_ids[label] = stored['id']
            for _ in range(3):
                assert campaigns.tick(db)
            saved = campaigns.view(db, prepared['id'])
            retired_run = saved['days'][0]['run_id']
            saved_run = workspace.run_detail(db, retired_run, export=True)
            policy = saved_run['report']['policy']
            assert stamp(policy['prospective_start_at']) == first
            assert stamp(policy['decision_before']) == retirement
            assert policy['depth_execution_version'] == paper_depth.FIXED_PROFIT_VERSION
            assert set(saved_run['depth_receipts']) == {evidence_ids['eligible']}
            selected, = saved_run['report']['portfolios']['best_venue']['tickets']
            assert selected['title'] == fixtures['eligible'][0]['title']
            assert saved['days'][1]['replay_state'] == 'retired'
            assert {row['game_title'] for row in campaigns.trades(db, active['id'])['trades']} == {
                game['title'] for game, _, _ in fixtures.values()}
            assert [row['game_title'] for row in campaigns.trades(db, next_campaign['id'])['trades']] == [
                fixtures['at_retirement'][0]['title']]
            assert prepared['id'] not in [value['id'] for value in campaigns.index(db, active_only=True)]
            assert db.execute('SELECT payload FROM public.paper_campaign WHERE id=%s', (prepared['id'],)).fetchone()[
                'payload'] == {key: value for key, value in prepared.items() if key != 'id'}

            # Publication uses the captured trade even though the campaign has retired.
            self.advance(db, retirement+timedelta(hours=3))
            game = fixtures['eligible'][0]
            observed = self.at.isoformat()
            final = dict(game, source='sportsgameodds', final=True, result='completed', home_score=96, away_score=80,
                         received_at=observed, knowledge_at=observed, receipt_sha256=hashed(['retired-grade', 96]))
            assert experiment.observe_outcomes(db, [final], at=self.at)['matched'] == 1
            assert queue.dispatch(db) == 1
            assert queue.process_one(db)
            assert queue.process_one(db)
            assert queue.process_one(db)
            ledger = campaigns.trades(db, prepared['id'], export=True)
            trade, = ledger['trades']
            assert trade['run_id'] == retired_run and trade['grade']['state'] == 'win'
            assert F(trade['pnl_exact_usd']) == F('24.9975')
            assert set(ledger['depth_receipts']) == {evidence_ids['eligible']}
            assert workspace.run_detail(db, retired_run, export=True) == saved_run

    async def test_campaign_trade_route_reads_multiple_saved_dates_and_selected_portfolio(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        from app.dashboard import research_workspace_api
        from app.dashboard.request_guard import dashboard_guard
        from app.research import experiment

        await super().asyncSetUp()
        runs = {}
        with (self.connect() as db, patch.object(queue, '_late_capture_due', return_value=False),
              patch.object(queue, 'utc', side_effect=lambda: self.at),
              patch.object(campaigns.mens_d1, 'daily_recovery', return_value={}),
              patch.object(paper.math, 'calculate', side_effect=linear)):
            saved = campaigns.create(db, config())
            identity = saved['id']
            for day in ('2026-11-23', '2026-11-24'):
                self.advance(db, stamp(f'{day}T17:00:00Z'))
                game = self.game(f'game-{day}', f'{day}T18:00:00Z')
                experiment.discover(db, [game], at=self.at)
                self.capture(db, 'early', game)
                self.advance(db, stamp(f'{day}T17:50:00Z'))
                self.capture(db, 'late', game)
                population = dict(kind='reconciled_occurrences', source='fixture', membership_version='fixture',
                    revision=hashed([day]), observed_at=self.at.isoformat(), expected_games=None,
                    games=[dict(scope_state='eligible', paper_eligible=True, provider_event_id=game['source_event_id'],
                                occurrence_id=game['source_event_id'], title=game['title'], starts_at=game['starts_at'])])
                with patch.object(campaigns.mens_d1, 'daily_population', return_value=population):
                    runs[day] = campaigns.tick(db)
                assert runs[day]
                db.execute('UPDATE public.paper_campaign_day SET next_check_at=%s WHERE campaign_id=%s AND game_date=%s',
                           (self.at + timedelta(days=2), identity, day))

        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        research_workspace_api.mount(app, campaigns_only=True)
        route = f'{research_workspace_api.BASE}/campaigns/{identity}/trades'
        # A saved run remains available even if the browser checks before its game date.
        with (patch.object(research_workspace_api, 'connect', side_effect=self.connect),
              patch.object(queue, 'utc', return_value=stamp('2026-11-23T18:00:00Z'))):
            async with TestClient(TestServer(app)) as client:
                response = await client.get(route, params=dict(mode='kelly', variant='all_venues'))
                assert response.status == 200, await response.text()
                payload = await response.json()
                assert (payload['id'], payload['mode'], payload['variant']) == (identity, 'kelly', 'all_venues')
                assert payload['provider_requests'] == payload['orders_submitted'] == 0
                rows = payload['trades']
                assert {row['game_date']: row['run_id'] for row in rows} == runs
                assert len({row['id'] for row in rows}) == len(rows)
                assert all(row['result_id'] is None and row['grade']['state'] == 'pending' for row in rows)
                assert payload['summary']['tickets'] == len(rows)
                assert payload['summary']['resolved'] == 0

                best = await client.get(route, params=dict(variant='best_venue'))
                assert best.status == 200, await best.text()
                best_rows = (await best.json())['trades']
                assert len(best_rows) == len(runs) < len(rows)
                assert {row['id'] for row in best_rows} <= {row['id'] for row in rows}
                bad_mode = await client.get(route, params=dict(mode='fixed_profit'))
                assert bad_mode.status == 422

    def test_last_game_date_has_next_day_finals_and_correction_jobs(self):
        from app.collection import mens_d1_jobs
        from app.storage.mens_d1_coverage import EASTERN

        monday = stamp('2026-11-30T04:00:00-05:00')
        with self.connect() as db:
            mens_d1_jobs.plan(db, monday, None, None, source_id=mens_d1_jobs.CBBD, configured=True)
            rows = db.execute('''SELECT purpose,due_at,state FROM public.mens_d1_job
                WHERE game_date='2026-11-29' AND source=%s AND kind='results' ORDER BY due_at''',
                (mens_d1_jobs.CBBD,)).fetchall()
        assert [(r['purpose'], r['due_at'].astimezone(EASTERN).isoformat(), r['state']) for r in rows] == [
            ('results_morning', '2026-11-30T05:30:00-05:00', 'pending'),
            ('results_corrections', '2026-11-30T12:30:00-05:00', 'pending'),
            ('results_unresolved_followup', '2026-12-01T05:30:00-05:00', 'pending'),
        ]
