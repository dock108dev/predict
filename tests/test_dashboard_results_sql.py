"""Real publication/read integration on the disposable project test cluster."""
from unittest import skipUnless
from unittest.mock import patch
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from app.storage.dashboard_results import read
from app.storage.slate_reads import CapturedReads
from app.comparison.estimated_policy import DEFAULT_POLICY

@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class DashboardSQL(LatestBoardFixture):
    async def test_publication_window_counts_immutable_tokens_and_no_request_finance(self):
        self.reconcile()
        reads=CapturedReads(resource_bytes=lambda:0)
        with self.connect() as db:
            self.assertGreater(db.execute('SELECT count(*) n FROM latest_dashboard').fetchone()['n'],0)
            with patch('app.storage.latest_board.calculate_current',side_effect=AssertionError('request finance forbidden')):
                first=read(db,DEFAULT_POLICY,reads=reads)
                # Maintenance removes duplicated child inventories; the independent
                # membership owner must still support ordinary Dashboard reads.
                db.execute("UPDATE current_result_unit SET facts=facts-'unit_inventory'")
                second=read(db,DEFAULT_POLICY,reads=reads)
            self.assertEqual(first['revision'],second['revision'])
            self.assertEqual(first['provider_requests'],0)
            self.assertNotEqual(first['slates']['ev']['read_token'],second['slates']['ev']['read_token'])
            self.assertGreater(first['slates']['ev']['counts']['evaluated'],0)
            for slate in first['slates'].values():
                self.assertTrue(slate['games'])
                self.assertIn('blocked',slate['counts'])
                for board in slate['boards']:
                    for row in board['rows']:
                        self.assertEqual(row['details']['read_token'],slate['read_token'])
                        saved,selected_token=reads.selection(slate['read_token'],board['game_key'])
                        units=saved['facts']['result_units']
                        selected=units[row['result_unit_id']]['facts']
                        self.assertEqual(selected['context']['context_id'],row['details']['context_id'])
                        self.assertIn('selected_frame',selected)
                        reads.discard(selected_token)
