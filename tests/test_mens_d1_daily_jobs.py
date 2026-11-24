from datetime import date, timedelta
import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import httpx

from app.collection import mens_d1_cbbd as cbbd
from app.collection import mens_d1_jobs as jobs
from app.storage import mens_d1_coverage as coverage
from app.storage.store import stamp


def api_game(identity=120, **overrides):
    return dict(dict(id=identity, sourceId=str(identity + 1000), season=2027, startDate='2026-11-25T01:00:00Z',
        startTimeTbd=False, neutralSite=True, status='scheduled', venue='Fixture Arena', homeTeamId=262,
        homeTeam='Seattle U', homeConference='WCC', homePoints=None, homePeriodPoints=None,
        awayTeamId=151, awayTeam='Loyola Chicago', awayConference='A-10', awayPoints=None, awayPeriodPoints=None),
        **overrides)


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


class CollegeBasketballDataAPI(TestCase):
    def test_keyed_monthly_account_and_eastern_day_filter(self):
        day = date(2026, 11, 1)
        now = lambda: stamp('2026-11-01T08:00:00Z')
        observed = []

        def fixture(request):
            self.assertEqual(request.method, 'GET')
            self.assertEqual(request.url.host, 'api.collegebasketballdata.com')
            self.assertEqual(request.headers['authorization'], 'Bearer fixture-cbbd-key')
            observed.append(request.url.path)
            if request.url.path == '/info':
                return httpx.Response(200, json=dict(remainingCalls=3, monthlyLimit=1000, tierName='Free',
                    resetAt='2026-12-01T00:00:00Z', sharedPool=True, products=['cfb', 'cbb']))
            query = parse_qs(urlsplit(str(request.url)).query)
            self.assertEqual(query, dict(season=['2027'], startDateRange=['2026-11-01T04:00:00+00:00'],
                endDateRange=['2026-11-02T04:59:59.999000+00:00']))
            return httpx.Response(200, json=[])

        with httpx.Client(transport=httpx.MockTransport(fixture)) as client:
            account, reason = cbbd.verify_account('fixture-cbbd-key', client=client, now=now)
            self.assertIsNone(reason)
            self.assertEqual(account.remaining, 3)
            self.assertEqual(account.window_id, 'cbbd:2026-12-01')
            receipt = cbbd.fetch_games(cbbd.source_url(day), api_key=account.key, client=client, now=now)
        self.assertEqual(observed, ['/info', '/games'])
        self.assertEqual(receipt.credits_used, 1)
        self.assertEqual(cbbd.parse_games(receipt, day=day, kind='schedule'), [])

    def test_credentials_never_follow_redirects_or_enter_receipts(self):
        day = date(2026, 11, 24)
        url = cbbd.source_url(day)
        token = 'fixture-cbbd-secret'
        for code, expected in ((302, 'cbbd_api_unexpected_http_status'), (403, cbbd.ACCESS_DENIED),
                               (429, cbbd.RATE_LIMITED), (200, 'cbbd_api_credential_echo_discarded')):
            observed = []

            def fixture(request):
                observed.append(str(request.url))
                return httpx.Response(code, headers={'Location': 'https://fixture.invalid'},
                                      content=token.encode() if code == 200 else b'{}')

            with self.subTest(code=code), httpx.Client(transport=httpx.MockTransport(fixture), follow_redirects=True) as client:
                receipt = cbbd.fetch_games(url, api_key=token, client=client)
                self.assertEqual(observed, [url])
                self.assertEqual(receipt.error, expected)
                self.assertNotIn(token.encode(), receipt.raw_body)

    def test_partial_unscored_final_stays_unresolved_and_receipt_cannot_mix_dates(self):
        day = date(2026, 11, 24)
        body = [api_game(status='final', awayPoints=76, homePeriodPoints=[38, 42]),
                api_game(121, status='cancelled'), api_game(122)]
        url = cbbd.source_url(day)
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
            receipt = cbbd.fetch_games(url, api_key='fixture-cbbd-key', client=client)
            rows = cbbd.parse_games(receipt, day=day, kind='results')
            self.assertEqual([(row['source_game_id'], row['status']) for row in rows],
                             [('cbbd:120', 'incomplete'), ('cbbd:121', 'cancelled'), ('cbbd:122', 'scheduled')])
            self.assertEqual(rows[0]['detail_reason'], 'source_final_score_unavailable')
            self.assertEqual(rows[0]['membership_status'], 'eligible')
            self.assertEqual(json.loads(receipt.raw_body), body)
            body[0]['startDate'] = '2026-11-25T05:00:00Z'
            other = cbbd.fetch_games(url, api_key='fixture-cbbd-key', client=client)
            with self.assertRaises(cbbd.SourcePageError):
                cbbd.parse_games(other, day=day, kind='schedule')


class DailyRuntime(IsolatedAsyncioTestCase):
    async def test_disabled_owner_plans_without_fetch_or_claim(self):
        worker = SimpleNamespace(experiment_late_waiting=False, experiment_reserved_requests=1)
        runtime = SimpleNamespace(acquisition_pressure=Mock(return_value=False), global_stopped=False,
            paused_sources=set(), storage_interval_requested=False, stopping=Mock(is_set=Mock(return_value=False)),
            service=SimpleNamespace(config={'enabled': True}, dispatch=True, workers={'sportsgameodds': worker}))
        fetch = Mock()
        at = stamp('2026-11-24T16:00:00Z')
        scheduler = jobs.DailyCoverageJobs(runtime, fetch=fetch, now=lambda: at,
                                          cbbd_credential=lambda: None,
                                          authority_loader=lambda at: (None, jobs.BLOCKED_REASON))
        self.assertTrue(scheduler.pressure())
        with (patch.object(scheduler, '_prepare', return_value=None) as prepare,
              patch.object(scheduler, '_prepare_cbbd', return_value=None) as prepare_cbbd):
            await scheduler.tick()
        prepare.assert_called_once_with(at, None, jobs.BLOCKED_REASON, False)
        prepare_cbbd.assert_called_once_with(at, None)
        fetch.assert_not_called()
        self.assertTrue(await scheduler.wait_idle())
