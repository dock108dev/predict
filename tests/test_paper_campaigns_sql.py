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
        await super().asyncSetUp()

    def test_ui_configuration_queues_seven_days_and_publishes_repriced_snapshot_once(self):
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
