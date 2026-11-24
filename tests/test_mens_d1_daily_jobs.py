from datetime import date, timedelta
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch

from app.collection import mens_d1_jobs as jobs
from app.storage import mens_d1_coverage as coverage
from app.storage.store import stamp


class DailyAuthority(TestCase):
    def test_defaults_to_disabled_even_when_key_exists(self):
        with patch.object(jobs, 'read_file', return_value=None), patch.dict(
            jobs.os.environ, {'FIRECRAWL_API_KEY': 'fixture-secret'}
        ):
            self.assertEqual(jobs.authority(stamp('2026-11-24T16:00:00Z')), (None, jobs.BLOCKED_REASON))

    def test_eastern_day_boundaries_use_actual_dst_transition(self):
        fall_back = date(2026, 11, 1)
        a = coverage.eastern_time(fall_back).astimezone(jobs.coverage.utc().tzinfo)
        b = coverage.eastern_time(fall_back + timedelta(days=1)).astimezone(jobs.coverage.utc().tzinfo)
        self.assertEqual(b - a, timedelta(hours=25))


class DailyRuntime(IsolatedAsyncioTestCase):
    async def test_disabled_owner_plans_without_fetch_or_claim(self):
        worker = SimpleNamespace(experiment_late_waiting=False, experiment_reserved_requests=1)
        runtime = SimpleNamespace(acquisition_pressure=Mock(return_value=False), global_stopped=False,
            paused_sources=set(), storage_interval_requested=False, stopping=Mock(is_set=Mock(return_value=False)),
            service=SimpleNamespace(config={'enabled': True}, dispatch=True, workers={'sportsgameodds': worker}))
        fetch = Mock()
        at = stamp('2026-11-24T16:00:00Z')
        scheduler = jobs.DailyCoverageJobs(runtime, fetch=fetch, now=lambda: at,
                                          authority_loader=lambda at: (None, jobs.BLOCKED_REASON))
        self.assertTrue(scheduler.pressure())
        with patch.object(scheduler, '_prepare', return_value=None) as prepare:
            await scheduler.tick()
        prepare.assert_called_once_with(at, None, jobs.BLOCKED_REASON, False)
        fetch.assert_not_called()
        self.assertTrue(await scheduler.wait_idle())
