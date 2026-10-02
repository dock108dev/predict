"""Prevent routine accounting from restoring withdrawn gates or overwriting seals."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from scripts.write_v1_beta_coverage_status import ROOT, write_status


class WorkflowPolicy(unittest.TestCase):
    def test_generation_keeps_acceptance_and_historical_status_unchanged(self):
        paths = [ROOT / 'docs/beta-coverage-acceptance.md',
                 ROOT / 'evidence/v1-counterpart-completion-20261001-v1/beta-coverage-status.json']
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        with tempfile.TemporaryDirectory() as directory:
            status = write_status(Path(directory) / 'accounting')
            self.assertEqual(status['current_valid_retained_pairs'], 15)
            self.assertEqual(status['remaining_requirements'], 48)
            self.assertEqual(sum(x['requirements'] for x in status['sports'].values()), 63)
            self.assertNotIn('minimum_valid_retained_pairs', status)
            self.assertNotIn('met', status)
            self.assertFalse(status['authorization_changed'])
            self.assertEqual(status['authority'], 'docs/configuration.md#saved-review-and-live-collection')
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])

    def test_historical_and_document_destinations_are_rejected(self):
        for path in ['evidence/v1-counterpart-completion-20261001-v1',
                     'scripts/v1_counterpart_package', 'docs',
                     'evidence/private-beta-workflow-20261001-v1']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                write_status(ROOT / path)


class SelectedCatalog(unittest.IsolatedAsyncioTestCase):
    async def test_details_does_not_project_unselected_archives(self):
        from unittest.mock import patch
        from aiohttp.test_utils import TestClient, TestServer
        from app.dashboard.coverage_owner import CoverageOwner
        from app.dashboard.multi_game_server import create_app
        from app.dashboard import session_history
        folder = ROOT / 'evidence/v1-admission-delivery-repair-20261001-v1/saved/offline-v1-repair-713fd0fa-20261001'
        sid = folder.name
        with tempfile.TemporaryDirectory() as directory:
            owner = CoverageOwner(Path(directory)/'legacy', pilot_output=Path(directory)/'sessions', product_mode=True)
            with patch.object(owner, 'history_paths', return_value={sid: folder, 'unselected': Path(directory)/'unreadable'}), patch('app.dashboard.session_history.load', wraps=session_history.load) as reader:
                client = TestClient(TestServer(create_app(owner=owner, sessions={}, watch_path=Path(directory)/'watches.json')))
                await client.start_server()
                try:
                    response = await client.get('/api/sessions', params={'session': sid+'~unused'})
                    self.assertEqual(response.status, 200, await response.text())
                    catalog = await response.json()
                    self.assertTrue(catalog)
                    self.assertTrue(all(row['hash'] == sid for row in catalog))
                    self.assertEqual(reader.call_count, 1)
                    self.assertEqual(reader.call_args.args[0], folder)
                finally:
                    await client.close()


class FeeEnvelope(unittest.TestCase):
    def test_fee_changes_route_is_not_an_event_detail(self):
        from app.collection.native_payload import envelope, validate_envelope
        path = '/trade-api/v2/events/fee_changes'
        self.assertEqual(envelope(path), 'event_fee_changes')
        validate_envelope({'event_fee_changes': [], 'cursor': ''}, path)
        self.assertEqual(envelope('/trade-api/v2/events/KXNFLGAME-EXACT'), 'event')
