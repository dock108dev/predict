from datetime import date, timedelta
from hashlib import sha256
import json
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import Mock

import httpx
from psycopg.errors import RaiseException
from psycopg.types.json import Jsonb

from app.collection import mens_d1_cbbd as cbbd
from app.collection import mens_d1_jobs as jobs
from app.collection import mens_d1_public_export as public_export
from app.collection.mens_d1_source import SourceReceipt, load_membership, source_url
from app.research import records
from app.storage import mens_d1_coverage as coverage
from app.storage.store import stamp
from tests.latest_board_fixture import SOCKET, LatestBoardFixture
from tests.test_mens_d1_daily_jobs import api_game


DAY = date(2026, 11, 24)
MORNING = stamp('2026-11-24T09:15:00Z')
TIP = '2026-11-25T01:00:00+00:00'


def authority(max_credits=20):
    return jobs.Authority('fixture-window', MORNING - timedelta(days=1), MORNING + timedelta(days=3),
                          max_credits, max_credits, 'fixture-key')


def evidence(url, at, *, body=None):
    html = '<main>authored source fixture</main>'
    data = json.dumps(dict(data=dict(rawHtml=html, links=[url]))).encode() if body is None else body
    return SourceReceipt(url, at, at + timedelta(seconds=1), final_url=url, status_code=200,
                         transport_status=200, raw_body=data, raw_html=html, links=(url,), credits_used=1)


def game(identity, names, *, starts_at=TIP, neutral=None, gender='men', state='scheduled', scores=None):
    membership = load_membership(DAY)
    teams = []
    for index, (role, name) in enumerate(zip(('away', 'home'), names, strict=True)):
        evidence = membership.lookup(name.lower(), name) if gender == 'men' else membership.unresolved()
        teams.append(dict(source_team_id=name.lower(), name=name, display_role=role, membership=evidence,
                          score=scores[index] if scores else None, period_scores=None))
    division = {row['membership']['division'] for row in teams}
    state_name = ('excluded' if gender != 'men' or 'non_d1' in division else
                  'eligible' if division == {'d1'} else 'unresolved')
    return dict(source_game_id=identity, native_game_id='fixture-' + identity, gender=gender, date=str(DAY),
        source_date=str(DAY), source_time='8:00pm', source_timezone='ET', scheduled_start=starts_at,
        neutral_site=neutral, membership_status=state_name, membership_reason=state_name,
        membership_version=membership.version, teams=teams, status=state,
        source_url=source_url(DAY, 'schedule'))


def persist(db, at, rows, *, kind='schedule', purpose='schedule_morning', error=None):
    if kind != 'schedule' or purpose != 'schedule_morning':
        jobs._job(db, DAY, purpose, kind, at, at + timedelta(hours=2))
    job, attempt = jobs.claim(db, at, authority())
    assert job['purpose'] == purpose
    receipt = evidence(attempt['request_url'], at)
    jobs.finish(db, job, attempt, receipt.received_at, receipt=receipt, rows=rows,
                membership_version=load_membership(DAY).version, error=error)
    return attempt


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class MensD1CoverageSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        with self.connect() as db:
            db.execute('TRUNCATE public.mens_d1_source_state,public.mens_d1_job CASCADE')
            db.execute('TRUNCATE public.ev_experiment_record CASCADE')

    async def test_configured_cbbd_scheduler_retains_revisions_finals_and_raw_receipts(self):
        at = MORNING
        credential = None
        rows = [api_game(), api_game(121, homeTeamId=100, homeTeam='Duke', awayTeamId=617,
                                     awayTeam='Fredonia State', awayConference=None)]
        paths = []

        def transport(request):
            paths.append(request.url.path)
            if request.url.path == '/info':
                return httpx.Response(200, json=dict(remainingCalls=7, monthlyLimit=1000, tierName='Free',
                    resetAt='2026-12-01T00:00:00Z', sharedPool=True, products=['cfb', 'cbb']))
            return httpx.Response(200, json=rows)

        worker = SimpleNamespace(experiment_late_waiting=False, experiment_reserved_requests=0)
        runtime = SimpleNamespace(acquisition_pressure=Mock(return_value=False), global_stopped=False,
            paused_sources=set(), storage_interval_requested=False, stopping=Mock(is_set=Mock(return_value=False)),
            service=SimpleNamespace(config={'enabled': True}, dispatch=True, workers={'sportsgameodds': worker}))
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            scheduler = jobs.DailyCoverageJobs(runtime, connector=self.connect,
                authority_loader=lambda _: (None, jobs.BLOCKED_REASON), cbbd_credential=lambda: credential,
                cbbd_account=lambda key, **kw: cbbd.verify_account(key, client=client, **kw),
                cbbd_fetch=lambda url, **kw: cbbd.fetch_games(url, client=client, **kw), now=lambda: at)
            await scheduler.tick()
            with self.connect() as db:
                state = coverage.read_status(db, at=at)
                self.assertEqual((state['source'], state['state'], state['reason']),
                                 (jobs.CBBD, 'disabled', cbbd.KEY_UNAVAILABLE))
                self.assertEqual(state['credits']['requests'], 0)
                self.assertIsNotNone(state['next_run_at'])
            self.assertEqual(paths, [])
            credential = 'fixture-cbbd-key'
            runtime.paused_sources.add(jobs.CBBD)
            await scheduler.tick()
            self.assertEqual(paths, [])
            runtime.paused_sources.clear()
            await scheduler.tick()
            with self.connect() as db:
                before = coverage.read_coverage(db, DAY, at=max(coverage.utc(), at))
                original = coverage.read_receipt(db, before['source_receipt_id'])
                self.assertEqual(before['source_mode'], 'daily_source')
                self.assertEqual(before['counts']['source_eligible'], 1)
                self.assertEqual(before['counts']['expected'], None)
                self.assertEqual(len(before['source_revisions']), 1)
                self.assertEqual(original['requested_at'], at.isoformat())
                self.assertNotIn('raw_body', original)
                self.assertEqual(original['body_sha256'], db.execute(
                    'SELECT body_sha256 FROM public.mens_d1_receipt WHERE id=%s', (original['id'],)).fetchone()['body_sha256'])

            at = stamp('2026-11-24T18:30:01Z')
            rows[0]['startDate'] = '2026-11-25T01:30:00Z'
            rows[1]['status'] = 'cancelled'
            rows.append(api_game(122, homeTeamId=100, homeTeam='Duke', awayTeamId=102, awayTeam='North Carolina'))
            worker.experiment_late_waiting = True
            await scheduler.tick()
            self.assertEqual(paths, ['/info', '/games'])
            worker.experiment_late_waiting = False
            await scheduler.tick()

            at = stamp('2026-11-25T10:45:00Z')
            rows[0].update(status='final', homePoints=81, awayPoints=76)
            await scheduler.tick()

        self.assertEqual(paths, ['/info', '/games'] * 3)
        with self.connect() as db:
            as_of = max(coverage.utc(), at)
            state = coverage.read_status(db, at=as_of)
            self.assertEqual(state['source'], jobs.CBBD)
            self.assertEqual(state['credits']['requests'], 3)
            self.assertEqual(state['credits']['confirmed'], 3)
            value = coverage.read_coverage(db, DAY, at=as_of)
            games = {row['source_game_id']: row for row in value['games']}
            self.assertEqual(value['counts']['expected'], None)
            self.assertEqual(value['counts']['source_eligible'], 2)
            self.assertEqual(len(value['source_revisions']), 2)
            self.assertEqual(games['cbbd:120']['schedule']['starts_at'], '2026-11-25T01:30:00+00:00')
            self.assertIn('rescheduled', {entry['change'] for entry in games['cbbd:120']['schedule_changes']})
            self.assertEqual(games['cbbd:120']['result_state'], 'final')
            self.assertEqual(games['cbbd:120']['match_state'], 'source_only')
            self.assertEqual(games['cbbd:121']['schedule']['status'], 'cancelled')
            self.assertIn('cbbd:122', games)
            self.assertEqual(coverage.read_receipt(db, original['id']), original)

    def test_cbbd_unknown_call_is_retained_and_blocks_remaining_single_call(self):
        approved = cbbd.Account(stamp('2026-11-01T00:00:00Z'), stamp('2026-12-01T00:00:00Z'), 1000, 1,
                                'Free', 'fixture-cbbd-key')
        with self.connect() as db:
            jobs.plan(db, MORNING, approved, None, source_id=jobs.CBBD)
            _, attempt = jobs.claim(db, MORNING, approved, source_id=jobs.CBBD)
        restart = MORNING + timedelta(minutes=20)
        with self.connect() as db:
            jobs.plan(db, restart, approved, None, source_id=jobs.CBBD)
            self.assertIsNone(jobs.claim(db, restart + timedelta(minutes=20), approved, source_id=jobs.CBBD))
            state = coverage.read_status(db, at=restart)
            self.assertEqual(state['credits']['held'], 1)
            self.assertEqual(state['credits']['unconfirmed_dispatches'], 1)
            self.assertEqual(db.execute('SELECT disposition FROM public.mens_d1_attempt WHERE id=%s',
                                       (attempt['id'],)).fetchone()['disposition'], 'unknown')

    def test_restart_recovers_lease_and_keeps_unconfirmed_credit_held(self):
        with self.connect() as db:
            approved = authority(1)
            jobs.plan(db, MORNING, approved, None)
            before = db.execute('SELECT count(*) n FROM public.mens_d1_job').fetchone()['n']
            job, attempt = jobs.claim(db, MORNING, approved)
            self.assertEqual(job['purpose'], 'schedule_morning')
            self.assertEqual(records.retention_usage(db)['daily_coverage_reserved_bytes'], jobs.MAX_STORAGE_RESERVATION)
        restart = MORNING + timedelta(minutes=4)
        with self.connect() as db:
            jobs.plan(db, restart, approved, None)
            self.assertEqual(db.execute('SELECT count(*) n FROM public.mens_d1_job').fetchone()['n'], before)
            self.assertEqual(records.retention_usage(db)['daily_coverage_reserved_bytes'], 0)
            state = coverage.read_status(db, at=restart)
            self.assertEqual(state['credits']['held'], 1)
            self.assertEqual(state['credits']['unconfirmed_dispatches'], 1)
            self.assertGreater(stamp(state['next_run_at']), restart)
            after_result_due = restart + timedelta(hours=2)
            status_with_overdue = coverage.read_status(db, at=after_result_due)
            self.assertGreater(stamp(status_with_overdue['next_run_at']), after_result_due)
            self.assertGreater(status_with_overdue['overdue_jobs'], 0)
            self.assertIn('results_unresolved_followup', {row['purpose'] for row in state['jobs']
                if row['game_date'] == str(DAY)})
            self.assertIsNone(jobs.claim(db, restart + timedelta(minutes=20), approved))
            self.assertEqual(db.execute('SELECT count(*) n FROM public.mens_d1_attempt').fetchone()['n'], 1)
            self.assertEqual(db.execute('SELECT disposition FROM public.mens_d1_attempt WHERE id=%s',
                (attempt['id'],)).fetchone()['disposition'], 'unknown')

    def test_offline_public_export_is_idempotent_and_preserves_observation_and_final(self):
        headers = sorted(public_export.REQUIRED_FIELDS)
        at = min(coverage.utc() - timedelta(seconds=1), MORNING)
        base = dict(Id='120', SourceId='241', Season='2027', StartDate='2026-11-25T04:59:00Z', StartTimeTbd='false',
            NeutralSite='true', Status='final', Venue='Neutral fixture', HomeTeamId='262', HomeTeam='Seattle U',
            HomeConference='WCC', HomePoints='91', HomePeriodPoints='[38,43,10]', AwayTeamId='151',
            AwayTeam='Loyola Chicago', AwayConference='A-10', AwayPoints='88', AwayPeriodPoints='[40,41,7]')
        placeholder = dict(base, Id='121', SourceId='242', StartDate='2026-11-24T05:00:00Z',
                           StartTimeTbd='true', Status='scheduled')
        excluded = dict(base, Id='122', SourceId='243', AwayTeamId='617', AwayTeam='Fredonia State', AwayConference='')
        unresolved = dict(base, Id='123', SourceId='244', AwayTeamId='1217', AwayTeam='TBD', AwayConference='')
        receipt = encoded_fixture = json.dumps(dict(source=public_export.SOURCE, source_url=public_export.URL,
            source_terms_url=public_export.TERMS, acquisition=public_export.ACQUISITION, observed_at=at.isoformat(),
            query=dict(season=2027, startDateRange='2026-11-24T05:00:00Z', endDateRange='2026-11-25T04:59:59Z'),
            headers=headers, pages=[[list(row[key] for key in headers)
                    for row in (base, placeholder, excluded, unresolved)]], last_page=True)).encode()
        with self.connect() as db:
            public_export.attach(db, encoded_fixture)
            public_export.attach(db, encoded_fixture)
            value = coverage.read_coverage(db, DAY, at=coverage.utc())
            self.assertEqual(value['source_mode'], 'retrospective_public_export')
            self.assertIsNone(value['counts']['expected'])
            self.assertEqual(value['counts']['source_eligible'], 1)
            self.assertEqual(value['counts']['source_returned_mens_games'], 4)
            self.assertEqual(value['counts']['excluded'], 2)
            self.assertEqual(value['counts']['unresolved_membership'], 1)
            self.assertIsNotNone(value['population']['binding_revision_id'])
            games = {row['native_game_id']: row for row in value['games']}
            self.assertEqual(games['120']['match_state'], 'source_only')
            self.assertEqual(games['120']['result']['overtime_periods'], 1)
            self.assertEqual(games['120']['result']['teams'][1]['score'], 91)
            self.assertEqual(games['121']['scope_reason'], 'superseded_source_placeholder')
            self.assertIsNone(games['121']['schedule']['starts_at'])
            self.assertEqual(games['123']['scope_state'], 'unresolved')
            source_receipt = coverage.read_receipt(db, value['source_receipt_id'])
            self.assertEqual(source_receipt['body_sha256'], sha256(receipt).hexdigest())
            self.assertIsNone(source_receipt['requested_at'])
            self.assertNotIn('raw_body', source_receipt)
            self.assertEqual(len(value['source_revisions']), 1)
            self.assertEqual(len(value['result_source_revisions']), 1)
            self.assertEqual(coverage.read_coverage(db, DAY, at=at)['counts']['source_eligible'], None)
            usage = db.execute('SELECT count(*) AS n,sum(charged_credits) AS charged FROM public.mens_d1_attempt').fetchone()
            self.assertEqual(usage, {'n': 2, 'charged': 0})
            official = dict(version=public_export.CORROBORATION_VERSION, observed_at=coverage.clock(coverage.utc()),
                public_export_body_sha256=sha256(receipt).hexdigest(), games=[dict(date=str(DAY),
                    source_game_id='cbbd:123', source_url='https://fixture.invalid/boxscore', publisher='Fixture recap',
                    scheduled_start=None, status='final', teams=[dict(name='Seattle University', score=83),
                        dict(name='Duke', score=80)])])
            proof = public_export.attach_corroborations(db, json.dumps(official).encode())
            self.assertEqual(public_export.attach_corroborations(db, json.dumps(official).encode()), proof)
            updated = coverage.read_coverage(db, DAY, at=coverage.utc())
            self.assertEqual(updated['population_revision'], value['population_revision'])
            self.assertEqual(updated['counts']['source_eligible'], 1)
            self.assertEqual(updated['counts']['source_corroborated_additional_eligible'], 1)
            game_with_proof = next(game for game in updated['games'] if game['source_game_id'] == 'cbbd:123')
            self.assertEqual(game_with_proof['scope_state'], 'unresolved')
            self.assertEqual(game_with_proof['teams'][0]['name'], 'TBD')
            witness, = game_with_proof['official_source_evidence']
            self.assertEqual(witness['id'], proof['retained_corroborations'][0])
            self.assertEqual(witness['status'], 'final')
            self.assertEqual(witness['teams'][1]['score'], 80)
            midnight = dict(official, games=[dict(official['games'][0], source_game_id='cbbd:120',
                scheduled_start='2026-11-25T05:00:00Z', teams=[dict(name='Seattle University', score=91),
                    dict(name='Loyola Chicago', score=88)])])
            public_export.attach_corroborations(db, json.dumps(midnight).encode())
            shifted = coverage.read_coverage(db, DAY, at=coverage.utc())
            self.assertEqual(shifted['counts']['source_official_eastern_date_conflicts'], 1)
            self.assertEqual(shifted['counts']['source_eligible'], 1)
            dated_game = next(game for game in shifted['games'] if game['source_game_id'] == 'cbbd:120')
            self.assertEqual(dated_game['official_source_evidence'][0]['eastern_game_date'], '2026-11-25')
            self.assertEqual(dated_game['schedule']['source_date'], str(DAY))

            # The newer authenticated revision preserves the original public-export evidence and its citations.
            api_at = coverage.utc()
            account = cbbd.Account(api_at - timedelta(days=1), api_at + timedelta(days=1), 1000, 999,
                                   'Free', 'fixture-cbbd-key')
            jobs._job(db, DAY, 'schedule_authenticated_fixture', 'schedule', api_at,
                      api_at + timedelta(hours=1), source_id=jobs.CBBD)
            job, attempt = jobs.claim(db, api_at, account, source_id=jobs.CBBD)
            parsed = db.execute('SELECT facts FROM public.mens_d1_revision WHERE id=%s',
                                (value['source_revisions'][0]['id'],)).fetchone()['facts']
            api_receipt = evidence(attempt['request_url'], api_at, body=b'[]')
            jobs.finish(db, job, attempt, api_receipt.received_at, receipt=api_receipt, rows=parsed,
                        membership_version=load_membership(DAY).version)
            midnight_start = '2026-11-25T05:00:00Z'
            frame = dict(starts_at=midnight_start, received_at=api_at.isoformat(), receipt_sha256='b' * 64,
                         event_context=dict(league='NCAAB', phase='pregame', status={}, teams=dict(
                             home=dict(id='SEATTLE_NCAAB', name='Seattle University'),
                             away=dict(id='LOYOLA_CHICAGO_NCAAB', name='Loyola Chicago'))))
            db.execute("""INSERT INTO public.sgo_event_evidence(kind,event_id,received_order,expires_at,payload_bytes,facts)
                VALUES ('frame','midnight-provider',1,%s,1,%s)""", (stamp(midnight_start) + timedelta(days=1), Jsonb(frame)))
            as_of = max(coverage.utc(), api_receipt.received_at)
            coverage_today = coverage.read_coverage(db, DAY, at=as_of)
            self.assertEqual(coverage_today['source_revisions'][0]['parser_version'], cbbd.PARSER_VERSION)
            ledger = {row['source_game_id']: row for row in coverage_today['occurrences'] if row.get('source_game_id')}
            self.assertNotIn('cbbd:121', ledger)
            self.assertIn('cbbd:121', {row['source_game_id'] for row in ledger['cbbd:120']['source_records']})
            self.assertEqual(ledger['cbbd:120']['day_applicability'], 'other_date')
            self.assertEqual(ledger['cbbd:120']['provider_event_id'], 'midnight-provider')
            self.assertFalse(ledger['cbbd:120']['paper_eligible'])
            self.assertEqual(ledger['cbbd:120']['result_state'], 'final')
            self.assertEqual(len(ledger['cbbd:120']['official_source_evidence']), 1)
            self.assertEqual(ledger['cbbd:123']['scope_state'], 'eligible')
            self.assertEqual(ledger['cbbd:123']['result_state'], 'final')
            self.assertEqual(ledger['cbbd:123']['teams'][1]['name'], 'Duke')
            self.assertIsNone(ledger['cbbd:123']['observation']['known_before_tminus10'])
            self.assertIsNone(ledger['cbbd:123']['observation']['source_identity_known_at'])
            tomorrow = coverage.read_coverage(db, DAY + timedelta(days=1), at=as_of)
            occurrence, = [row for row in tomorrow['occurrences'] if row.get('provider_event_id') == 'midnight-provider']
            self.assertEqual(occurrence['occurrence_id'], ledger['cbbd:120']['occurrence_id'])
            self.assertTrue(occurrence['paper_eligible'])
            self.assertEqual(occurrence['eastern_game_date'], '2026-11-25')
            self.assertEqual(coverage.read_reconciled_population(db, DAY, at=as_of),
                             coverage.read_reconciled_population(db, DAY, at=as_of + timedelta(seconds=1)))

            midnight['games'][0]['scheduled_start'] = '2026-11-25T05:01:00Z'
            with self.assertRaisesRegex(ValueError, 'official_game_cross_date_identity_unverified'):
                public_export.attach_corroborations(db, json.dumps(midnight).encode())

    def test_coalesces_overdue_schedule_and_preserves_challenge_vs_empty(self):
        observed = stamp('2026-11-24T15:15:00Z')
        with self.connect() as db:
            jobs.plan(db, observed, authority(), None)
            attempt = persist(db, observed, None, purpose='schedule_before_first_tip',
                              error='sports_reference_challenge_or_login')
            morning = db.execute("SELECT state FROM public.mens_d1_job WHERE game_date=%s AND purpose='schedule_morning'",
                                 (DAY,)).fetchone()
            self.assertEqual(morning['state'], 'coalesced')
            at = max(coverage.utc(), observed) + timedelta(seconds=5)
            report = coverage.read_coverage(db, DAY, at=at)
            self.assertEqual(report['source_state'], 'failed')
            self.assertIsNone(report['counts']['expected'])
            self.assertEqual(report['source_state_reason'], 'sports_reference_challenge_or_login')
            self.assertEqual(coverage.read_receipt(db, report['last_source_attempt']['id'])['raw_html'],
                             '<main>authored source fixture</main>')
            with self.assertRaises(RaiseException):
                db.execute("DELETE FROM public.mens_d1_receipt WHERE attempt_id=%s", (attempt['id'],))
            retry = observed + timedelta(minutes=16)
            persist(db, retry, [], purpose='schedule_before_first_tip')
            report = coverage.read_coverage(db, DAY, at=max(coverage.utc(), retry) + timedelta(seconds=5))
            self.assertEqual(report['source_state'], 'verified')
            self.assertEqual(report['counts']['expected'], 0)

    def test_protected_late_capture_is_not_delayed_or_charged_by_daily_job(self):
        with self.connect() as db:
            jobs.plan(db, MORNING, authority(), None)
            db.execute("""INSERT INTO public.ev_experiment_record(id,kind,refs,payload,payload_bytes)
                VALUES('fixture-policy','policy',ARRAY[]::text[],'{}',2),
                      ('fixture-schedule','schedule',ARRAY[]::text[],'{}',2)""")
            db.execute("""INSERT INTO public.ev_experiment_game
                (id,policy_id,provider,source_event_id,event,discovered_at,first_observed_at,schedule_id)
                VALUES('protected','fixture-policy','sportsgameodds','fixture-id','{}',%s,%s,'fixture-schedule')""",
                (MORNING, MORNING))
            due, deadline = MORNING + timedelta(seconds=30), MORNING + timedelta(seconds=90)
            db.execute("""INSERT INTO public.ev_experiment_task(game_id,checkpoint,schedule_id,target_at,deadline_at)
                VALUES('protected','late','fixture-schedule',%s,%s)""", (due, deadline))
            self.assertIsNone(jobs.claim(db, MORNING, authority()))
            task = db.execute("SELECT state,target_at FROM public.ev_experiment_task WHERE game_id='protected'").fetchone()
            self.assertEqual((task['state'], task['target_at']), ('pending', due))
            plan = db.execute("SELECT last_reason FROM public.mens_d1_job WHERE game_date=%s AND purpose='schedule_morning'",
                              (DAY,)).fetchone()
            self.assertEqual(plan['last_reason'], 'protected_tminus10_capture_due')
            self.assertEqual(coverage.read_status(db, at=MORNING)['credits']['requests'], 0)

    def test_exact_neutral_binding_and_append_result_revisions(self):
        with self.connect() as db:
            jobs.plan(db, MORNING, authority(), None)
            game_rows = [game('neutral', ('Duke', 'North Carolina'), neutral=True),
                         game('non-d1', ('Ecclesia', 'Grambling')),
                         game('women', ('Duke', 'North Carolina'), gender='women'),
                         game('unknown', ('Mystery School', 'Grambling'))]
            persist(db, MORNING, game_rows)
            frame = dict(starts_at=TIP, received_at=MORNING.isoformat(), receipt_sha256='a' * 64, members=[['a']],
                event_context=dict(league='NCAAB', phase='pregame', teams=dict(
                    home=dict(id='duke', name='Duke'), away=dict(id='unc', name='North Carolina')), status={}))
            db.execute("""INSERT INTO public.sgo_event_evidence(kind,event_id,received_order,expires_at,payload_bytes,facts)
                VALUES ('frame','fixture-odds',1,%s,1,%s)""", (stamp(TIP) + timedelta(days=1), Jsonb(frame)))
            at = max(coverage.utc(), MORNING) + timedelta(seconds=5)
            payload = coverage.read_coverage(db, DAY, at=at)
            matched = next(row for row in payload['games'] if row['source_game_id'] == 'neutral')
            self.assertEqual(matched['provider_event_id'], 'fixture-odds')
            self.assertEqual(matched['match_reason'], 'canonical_participants_and_start_agree_display_order_differs')
            self.assertEqual(payload['counts']['source_returned_mens_games'], 3)
            self.assertIsNone(payload['counts']['expected'])
            self.assertEqual(payload['counts']['source_eligible'], 1)
            self.assertEqual(payload['counts']['excluded'], 2)
            self.assertEqual(payload['counts']['unresolved_membership'], 1)
            self.assertTrue(coverage.retain_bindings(db, DAY, at=at))
            repeat = MORNING + timedelta(minutes=5)
            persist(db, repeat, game_rows, purpose='schedule_fixture_repeat')
            unchanged = coverage.read_population(db, DAY, at=max(coverage.utc(), repeat) + timedelta(seconds=5))
            self.assertEqual(payload['population_revision'], unchanged['revision'])
            self.assertNotEqual(payload['source_receipt_id'], unchanged['schedule_receipt_id'])
            changed = [game('neutral', ('Duke', 'North Carolina'), starts_at='2026-11-25T01:30:00Z', neutral=True),
                       *game_rows[1:]]
            now = stamp('2026-11-24T18:30:00Z')
            persist(db, now, changed, purpose='schedule_afternoon')
            latest = coverage.read_coverage(db, DAY, at=max(coverage.utc(), now) + timedelta(seconds=5))
            self.assertNotEqual(payload['population_revision'], latest['population_revision'])
            revised = next(row for row in latest['games'] if row['source_game_id'] == 'neutral')
            self.assertEqual(revised['match_state'], 'schedule_conflict')
            self.assertEqual([change['change'] for change in revised['schedule_changes']], ['added', 'rescheduled'])
            self.assertEqual(len(latest['source_revisions']), 3)
            # An index score and later conflicting detail both stay available.
            result_at = stamp('2026-11-25T16:00:00Z')
            rows = [game('neutral', ('North Carolina', 'Duke'), neutral=True, state='final', scores=[83, 80])]
            persist(db, result_at, rows, kind='results', purpose='fixture_result')
            detail_at = result_at + timedelta(minutes=2)
            detail = [dict(game('neutral', ('North Carolina', 'Duke'), neutral=True,
                                state='final', scores=[84, 80]), detail_reason='index_detail_score_conflict')]
            jobs._job(db, DAY, 'fixture_detail', 'detail', detail_at, detail_at + timedelta(hours=1),
                      data=dict(url=source_url(DAY, 'results'), reason='index_confirmation'))
            job, attempt = jobs.claim(db, detail_at, authority())
            receipt = evidence(attempt['request_url'], detail_at)
            jobs.finish(db, job, attempt, receipt.received_at, receipt=receipt, rows=detail,
                        membership_version=load_membership(DAY).version)
            latest = coverage.read_coverage(db, DAY, at=max(coverage.utc(), detail_at) + timedelta(seconds=5))
            revised = next(row for row in latest['games'] if row['source_game_id'] == 'neutral')
            self.assertEqual(revised['result_state'], 'conflicting')
            self.assertEqual([r['teams'][0]['score'] for r in revised['result_revisions']], [84, 83])
            self.assertEqual(revised['result']['teams'][0]['period_scores'], None)
            corrected_at = detail_at + timedelta(minutes=5)
            corrected = [game('neutral', ('North Carolina', 'Duke'), neutral=True, state='final', scores=[84, 80])]
            persist(db, corrected_at, corrected, kind='results', purpose='fixture_result_correction')
            latest = coverage.read_coverage(db, DAY, at=max(coverage.utc(), corrected_at) + timedelta(seconds=5))
            revised = next(row for row in latest['games'] if row['source_game_id'] == 'neutral')
            self.assertEqual(revised['result_state'], 'final')
            self.assertEqual(len(latest['result_source_revisions']), 3)


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class LateCaptureForecastSQL(LatestBoardFixture):
    def test_forecast_partitions_exact_scopes_and_accounts_for_the_shared_lane(self):
        from app.research import experiment
        from app.research.capture_forecast import late_capture_forecast

        at = MORNING + timedelta(minutes=4)
        target = at + timedelta(minutes=1)

        def event(index, begins):
            return dict(event_id=f'forecast-game-{index}', source_event_id=f'forecast-game-{index}',
                league='NCAAB', home='Duke', away='Gonzaga', starts_at=begins.isoformat(),
                title='Gonzaga at Duke', provider='sportsgameodds', status={})

        def retained_batch(db, size, seconds):
            claimed = at - timedelta(minutes=30 + size)
            end = claimed + timedelta(seconds=seconds)
            for member in range(size):
                pull_id = f'forecast-receipt-{size}-{member}'
                details = dict(batch=dict(size=size), attempt_id=f'forecast-attempt-{size}',
                    dispatch_at=(claimed + timedelta(seconds=1)).isoformat(),
                    timings=dict(claimed_at=claimed.isoformat(), batch_work_started_at=claimed.isoformat(),
                        response_received_at=(claimed + timedelta(seconds=2)).isoformat(),
                        persistence_checked_at=end.isoformat()))
                db.execute("""INSERT INTO public.market_pull(pull_id,requested_at,request_scope,state,details)
                    VALUES(%s,%s,'{}','complete',%s)""", (pull_id, claimed, Jsonb(details)))

        with self.connect() as db:
            db.execute("TRUNCATE public.ev_experiment_record CASCADE")
            db.execute("TRUNCATE public.market_pull CASCADE")
            db.execute("INSERT INTO public.ev_experiment_accounting(singleton) VALUES(true) ON CONFLICT DO NOTHING")
            begins = target + timedelta(minutes=10)
            experiment.discover(db, [event(index, begins) for index in range(27)]
                + [event(27, begins + timedelta(seconds=30))], at=at)
            retained_batch(db, 1, 7)
            retained_batch(db, 2, 7)
            retained_batch(db, 24, 44)
            policy = experiment._policy(db)
            policy.pop('id')
            policy['requested_scope']['bookmakers'] = policy['requested_scope']['bookmakers'][:-1]
            separate_scope, _ = experiment._write(db, 'policy', policy)
            db.execute("""UPDATE public.ev_experiment_game SET policy_id=%s
                WHERE source_event_id='forecast-game-0'""", (separate_scope,))
            forecast = late_capture_forecast(db, at=at, headroom_bytes=100_000_000)
            first, second = forecast['windows']
            self.assertEqual(first['scheduled_tasks'], 27)
            self.assertEqual(first['planned_batch_sizes'], [24, 2, 1])
            self.assertEqual(first['planned_event_requests'], 3)
            self.assertEqual(first['maximum_event_objects'], 27)
            self.assertEqual(first['competing_non_late_tasks'], 28)
            self.assertEqual(first['ordinary_discovery_slot_at'], target.isoformat())
            self.assertEqual(first['tasks_without_storage_reservation'], 27)
            self.assertFalse(first['current_headroom_below_unreserved_claim_floor'])
            self.assertTrue(late_capture_forecast(db, at=at, headroom_bytes=0)['windows'][0]
                            ['current_headroom_below_unreserved_claim_floor'])
            self.assertEqual(first['estimated_window_service_p95_seconds'], 58)
            self.assertEqual(second['estimated_window_service_p95_seconds'], 7)
            self.assertEqual(second['measured_competing_lane_seconds'], 28)
            self.assertEqual(forecast['current_execution_latency']['observed_physical_requests'], 3)
            self.assertEqual(forecast['current_execution_latency']['stage_p95_seconds']['provider_response'], 1)
