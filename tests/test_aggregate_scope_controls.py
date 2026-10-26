"""Disposable scope/transport controls. No authentic account or provider I/O."""
import json
from datetime import timedelta
import unittest
from unittest.mock import patch
from app.collection.current_quota import QuotaStop
from tests import test_current_aggregate as fixtures
from tests.test_current_service import native_fixture
from tests import test_current_conservative_recovery as recovery_fixtures
from app.collection.current_conservative import digest
from app.dashboard.current_contract import stamp


class ConfiguredAggregateScope(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.SchedulerTests.asyncSetUp
    asyncTearDown=fixtures.SchedulerTests.asyncTearDown

    async def test_manual_refresh_uses_same_families_as_scheduled_request(self):
        self.service.config.update(families=['moneyline'])
        await self.scheduler.step()
        await self.scheduler.refresh(['MLB'],'CONTROLLED-winner-only',reference=True)
        paid=[r for r in self.wire.calls if r['path'].endswith('/odds')]
        self.assertEqual(len(paid),2)
        self.assertEqual(paid[0],paid[1])
        self.assertEqual(paid[1]['params']['markets'],'h2h')
        self.assertEqual(paid[1]['params']['bookmakers'],'novig,prophetx,pinnacle')

    async def test_unconfigured_refresh_refuses_before_reservation_or_secret(self):
        before=self.q._read()
        with patch.object(self.scheduler,'key_loader',side_effect=AssertionError('secret access')):
            with self.assertRaisesRegex(QuotaStop,'scope_not_configured'):
                await self.scheduler.refresh(['NFL'],'CONTROLLED-unconfigured')
        self.assertEqual(self.q._read(),before)
        self.assertEqual(self.wire.calls,[])

    async def test_all_six_requests_include_each_selected_family(self):
        from app.collection.current_policy import SPORTS,aggregate_requests
        self.service.config.update(aggregate_sports=list(SPORTS),families=['moneyline','spread','total'])
        expected=aggregate_requests(self.service.config)
        with patch.object(self.scheduler,'admit_response'):
            await self.scheduler.step()
        paid=[r for r in self.wire.calls if r['path'].endswith('/odds')]
        self.assertEqual(paid,expected)
        self.assertEqual(len(paid),6)
        self.assertTrue(all(r['params']['markets']=='h2h,spreads,totals' for r in paid))
        self.assertEqual(self.q.snapshot()['used'],38)
        self.assertEqual(self.scheduler.metrics['worst_case_credits'],18)
        expected[0]['params']['markets']='CONTROLLED-mutated'
        self.assertEqual(expected[1]['params']['markets'],'h2h,spreads,totals')

    async def test_transport_failure_retains_safe_cause_and_native_prices(self):
        cat,book=native_fixture();self.service.catalog('kalshi',cat);self.service.book('kalshi',book)
        self.wire.phase='awaiting_headers'
        self.wire.error=TimeoutError('apiKey=CONTROLLED-secret')
        with self.assertRaisesRegex(QuotaStop,'transport_uncertain'):await self.scheduler.step()
        attempt=self.q._read()['attempts'][self.scheduler.issue_context['attempt_id']]
        self.assertEqual(attempt['transport_diagnostic']['category'],'timeout')
        self.assertEqual(attempt['transport_diagnostic']['transport_phase'],'awaiting_headers')
        self.assertIsNone(attempt['response_receipt'])
        self.assertNotIn('charged',attempt)
        self.assertNotIn('CONTROLLED-secret',json.dumps(attempt))
        self.assertEqual(len(self.wire.calls),1)
        self.assertEqual({q['quote']['venue'] for q in self.store.index(self.store.snapshot()).values()},{'kalshi'})

    async def test_recovered_accounting_wait_replaces_only_old_hold_status(self):
        await self.scheduler.step()
        # The shared fixture pins the schedule to 14:00 UTC, but the ledger
        # uses real time. Explicitly keep this scenario before its next cycle
        # even when the suite runs after the fixture's 14:15 UTC due time.
        self.q.transact(lambda value,at:value.update(
            next_due_at=(stamp(at)+timedelta(minutes=15)).isoformat()))
        self.service.states['novig']=dict(state='unavailable',reason_code='aggregate_transport_uncertain',reason='old hold')
        self.service.states['prophetx']=dict(state='unavailable',reason_code='aggregate_decimal_price',reason='bad original')
        count=len(self.wire.calls)
        await self.scheduler.step()
        self.assertEqual(self.service.states['novig']['reason_code'],'aggregate_budget_delayed')
        self.assertEqual(self.service.states['novig']['state'],'budget_delayed')
        self.assertEqual(self.service.states['prophetx']['reason_code'],'aggregate_decimal_price')
        self.assertEqual(len(self.wire.calls),count)


class ThreeUnresolvedAttempts(unittest.TestCase):
    setUp=recovery_fixtures.ConservativeRecovery.setUp
    tearDown=recovery_fixtures.ConservativeRecovery.tearDown
    evidence=recovery_fixtures.ConservativeRecovery.evidence
    activate=recovery_fixtures.ConservativeRecovery.activate
    due=recovery_fixtures.ConservativeRecovery.due
    reserve_cycle=recovery_fixtures.ConservativeRecovery.reserve_cycle

    def test_fresh_exact_set_adds_authority_without_assigning_three_charges(self):
        self.activate()
        originals={self.aid:self.old}
        for hour,used in ((20,653),(21,656)):
            self.at=f'2026-10-03T{hour}:00:00+00:00'
            aid,_=self.reserve_cycle();self.q.dispatched(aid,self.owner)
            self.q.record_response(aid,None,interruption='aggregate_transport_uncertain')
            originals[aid]=self.q._read()['attempts'][aid]
            self.q.pause('aggregate_transport_uncertain')
            self.at=f'2026-10-03T{hour}:03:00+00:00'
            covered={k:digest(a) for k,a in self.q._read()['attempts'].items() if a['state']=='uncertain'}
            self.activate(self.evidence(used,recovery_id=f'exact-{hour}'),covered=covered,identity=f'exact-{hour}')
        self.assertEqual(self.q.snapshot()['reserved'],9)
        self.assertEqual(self.q.snapshot()['unresolved_attempts'],3)
        self.assertEqual(self.q.snapshot()['covered_uncertain_attempts'],3)
        self.assertIsNone(self.q.snapshot()['pause'])
        self.assertEqual(self.q.snapshot()['available'],100000-656-9-50)
        for aid,original in originals.items():
            self.assertEqual(self.q._read()['attempts'][aid],original)
            self.assertNotIn('charged',original)
        self.assertEqual(len(self.q._read()['conservative_recoveries']),3)


class AggregateAdmissionMatrix(unittest.TestCase):
    def test_six_leagues_three_families_keep_original_reference_facts(self):
        from app.collection.current_policy import SPORTS
        from app.reference.product import SPORT_KEYS
        from app.collection.current_aggregate_admission import admit_venues
        for sport in SPORTS:
            with self.subTest(league=sport):
                data=json.loads(fixtures.body('NFL',books=('novig','prophetx','pinnacle')))
                data[0].update(sport_key=SPORT_KEYS[sport],id='CONTROLLED-'+sport)
                raw=json.dumps(data).encode()
                batches,rejected=admit_venues(raw,sport,'2026-10-03T00:00:01Z',include_reference=True)
                self.assertEqual(rejected,{})
                self.assertEqual(set(batches),{'novig','prophetx','pinnacle'})
                for venue,rows in batches.items():
                    self.assertEqual(len(rows),6)
                    self.assertEqual({r['market_identity']['family'] for r in rows},{'moneyline','spread','total'})
                    for record in rows:
                        quote=record['quote']
                        self.assertEqual(record['event']['competition'],sport)
                        self.assertEqual(quote['venue'],venue)
                        self.assertEqual(quote['original']['value'],'2.5000' if venue=='novig' else '2.0')
                        self.assertEqual(quote['times']['source_at'],'2026-10-03T00:00:00Z')
                        self.assertEqual(quote['times']['received_at'],'2026-10-03T00:00:01Z')
                        self.assertEqual(quote['provider_clocks']['book'],'2026-10-03T00:00:00Z')
                        self.assertEqual(quote['provider_clocks']['market'],'2026-10-03T00:00:00Z')
