"""Disposable scheduled run publication, immutable inputs and passive rollups."""
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from app.research import paper, paper_campaigns as campaigns, workspace
from app.storage import paper_result_queue as queue
from app.storage.store import hashed, stamp
from tests.latest_board_fixture import SOCKET
from tests.test_paper_campaigns import config
from tests.test_paper_experiments import linear
from tests.test_paper_experiments_sql import ResearchWorkspaceFixture


@skipUnless(SOCKET,'Disposable PostgreSQL required')
class CampaignSQL(ResearchWorkspaceFixture):
    async def asyncSetUp(self):
        with self.connect() as db:
            db.execute('TRUNCATE public.ev_experiment_game,public.ev_experiment_record,public.paper_campaign CASCADE')
            db.execute('INSERT INTO public.ev_experiment_accounting(singleton) VALUES (true) ON CONFLICT DO NOTHING')

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
