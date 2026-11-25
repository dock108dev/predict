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
            db.execute('TRUNCATE public.ev_experiment_game,public.ev_experiment_record,public.paper_campaign CASCADE')
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
                    rollup = campaigns.view(db, identity, variant, mode=mode)
                    assert rollup['reported_days'] == 1
                    daily = rollup['days'][0]['analysis']['summary']
                    weekly = rollup['weekly']['summary']
                    for field in ('stake_exact_usd', 'return_exact_usd', 'pnl_exact_usd'):
                        assert trade[field] == daily[field] == weekly[field]
                    assert F(weekly['roi']) == F(trade['pnl_exact_usd']) / F(trade['stake_exact_usd'])
                assert observed_trade['fixed_profit']['id'] != observed_trade['kelly']['id']
                assert observed_trade['fixed_profit']['frozen_quote_id'] == observed_trade['kelly']['frozen_quote_id']
                fixed = observed_trade['fixed_profit']
                assert F(fixed['pnl_exact_usd']) == F(fixed['sizing']['modeled_win_profit_usd'])
                assert fixed['sizing']['target_profit_usd'] == ('10' if identity == campaign['id'] else '13')

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
