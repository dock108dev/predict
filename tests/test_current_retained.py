"""Ordinary retained startup: isolated replay, no credential or acquisition I/O."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.collection.current_aggregate_admission import diagnostic
from app.collection.current_policy import DEFAULT
from app.collection.current_service import CurrentService
from app.collection.local_ownership import LocalOwnership
from app.dashboard.current_state import CurrentStore
from tests.test_current_aggregate import body


class OrdinaryRetained(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.at = '2026-10-03T00:00:01+00:00'
        value = diagnostic(body('NFL'), 'NFL', self.at, {})
        (self.root/'NFL.json').write_text(json.dumps(value))
        self.service = CurrentService(dict(DEFAULT, enabled=False), directory=self.root/'service',
            ownership=LocalOwnership(self.root/'owner'), retained_directory=self.root)
        self.store = CurrentStore(self.service)

    async def asyncTearDown(self):
        await self.store.close()
        self.temp.cleanup()

    async def test_disabled_dispatch_restores_original_clocks_and_funded_history(self):
        with patch('app.collection.current_aggregate.credential', side_effect=AssertionError('credential read')):
            await self.service.start(self.store)
            self.assertEqual(self.store._input_epoch, 0)
            await asyncio.wait_for(self.service.bootstrap_task, 10)
        self.assertFalse(self.service.dispatch)
        self.assertFalse(self.service.workers)
        self.assertIsNone(self.service.ownership.file)
        self.assertFalse(list((self.root/'service').glob('attempt-*.json')))
        quotes = [x['quote'] for x in self.store.index(self.store._state).values()]
        self.assertTrue(quotes)
        self.assertTrue(all(q['times']['received_at']==self.at for q in quotes))
        self.assertTrue(all(q['times']['source_at']=='2026-10-03T00:00:00Z' for q in quotes))
        self.assertTrue(all(q['stale'] for q in quotes))
        self.assertEqual(self.store._state['estimate_policy']['capital_ceiling_usd'], '1000')
        await self.service.close()
        self.assertEqual(self.store.admission.page()['status'], 'stopped')
        self.assertEqual(self.store.admission.page()['rows'], [])
        self.assertTrue(self.service.cleanup_complete)

    async def test_stop_before_bootstrap_complete_never_republishes(self):
        await self.service.start(self.store)
        await self.service.close()
        await asyncio.sleep(0)
        self.assertTrue(self.service.bootstrap_task.done())
        self.assertEqual(self.store.admission.page()['rows'], [])
        self.assertEqual(self.store._input_epoch, 0)

    async def test_bad_other_sport_keeps_independent_valid_records(self):
        from app.collection.current_retained import prepare
        (self.root/'MLB.json').write_text('{bad json')
        config = dict(DEFAULT, enabled=False, aggregate_sports=['NFL','MLB'])
        raw, _, refused = prepare(self.service._retained_sink.envelope, config, self.root)
        self.assertTrue(raw['events'])
        self.assertEqual(refused, ['MLB'])


class SynchronousConstruction(unittest.TestCase):
    def test_ordinary_app_constructs_before_event_loop(self):
        from app.dashboard.current_state import CURRENT_KEY
        from app.dashboard.opportunity_board import create_app
        with tempfile.TemporaryDirectory() as directory:
            service = CurrentService(dict(DEFAULT, enabled=False), retained_directory=Path(directory))
            app = create_app(sessions={}, current_provider=service)
            store = app[CURRENT_KEY]
            self.assertIsNone(store.admission.latest)
            async def check():
                await service.start(store)
                await service.bootstrap_task
                await store.close()
            asyncio.run(check())


class OrdinaryReference(unittest.TestCase):
    def test_retained_opposition_preserves_originals_and_refuses_misbinding(self):
        from app.collection.current_retained import prepare
        from app.dashboard.current_state import unavailable
        from app.dashboard.current_contract import serialize, quotes_of
        from app.comparison.current_dependencies import references
        from app.comparison.estimated_ev import _reference
        from app.comparison.domain import CanonicalSelection
        at = '2026-10-03T00:00:01+00:00'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            value = diagnostic(body('NFL', books=('novig','pinnacle')), 'NFL', at, {})
            (path/'NFL.json').write_text(json.dumps(value))
            raw = unavailable()
            with patch('app.collection.current_sink.utc', return_value=at):
                raw, _, _ = prepare(raw, dict(DEFAULT,aggregate_sports=['NFL']), path)
            raw['clock_at'] = at
            state = serialize(raw, allow_synthetic=False, details=True)
        event = state['events'][0]
        q = next(q for g in event['groups'] if g['market']=='winner'
            for o in g['outcomes'] for q in quotes_of(o) if q['venue']=='novig')
        values = references(q, state['comparison_profiles'])
        roles = {p['role']:p['id'] for p in event['participants']}
        weight, reference = _reference(q, values, roles)
        self.assertEqual(weight, __import__('fractions').Fraction(1,2))
        self.assertEqual([r.source_at for r in reference.outcomes], ['2026-10-03T00:00:00Z']*2)
        self.assertTrue(all(r.received_at==at for r in reference.outcomes))
        self.assertEqual(CanonicalSelection.from_dict(values['identity']['payload']['selection']).scope.overtime,'unknown')
        self.assertEqual([r.decimal_odds.original for r in reference.outcomes], ['2.0']*2)
        for field, replacement in (('source',dict(values['reference']['payload']['outcomes'][0]['source'],native_event_id='other')),
                ('decimal_odds','9.9'),('source_at','2026-10-03T00:00:01Z')):
            bad = deepcopy(values)
            bad['reference']['payload']['outcomes'][0][field] = replacement
            with self.assertRaises(ValueError):
                _reference(q,bad,roles)


if __name__ == '__main__':
    unittest.main()
