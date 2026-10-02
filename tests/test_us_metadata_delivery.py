"""Actual local HTTP boundary, ordinary semantic selection, durability and replay."""
import unittest
from tests.us_metadata_delivery_rehearsal import run_isolated as run


class LocalTransportIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_complete_larger_metadata_and_exact_boundary(self):
        for scenario in ('large_valid', 'realistic_nested_large', 'exact_boundary',
                         'exact_boundary_incompressible', 'chunked_large', 'legacy_exact_boundary'):
            with self.subTest(scenario=scenario):
                result = await run(scenario)
                self.assertTrue(result['us_usable'])
                self.assertTrue(result['exact_fresh_reopening'])
                self.assertEqual(result['paired_cards'], 0)

    async def test_failed_source_isolated_and_precisely_reopened(self):
        for scenario in ('inventory_overflow', 'entity_overflow', 'malformed', 'truncated', 'long_content_length',
                         'short_content_length', 'valid_prefix_excess', 'wire_overflow', 'unsupported_encoding', 'unexpected_envelope',
                         'redirect', 'timeout', 'body_timeout', 'changed_terms', 'unknown_terms', 'structure_overflow',
                         'secret_echo', 'secret_echo_html', 'secret_echo_overflow', 'secret_echo_timeout', 'legacy_overflow'):
            with self.subTest(scenario=scenario):
                result = await run(scenario)
                self.assertTrue(result['us_failure_reason'])
                self.assertEqual(result['kalshi_replayed_frames'], 55)
                self.assertEqual(result['subscriptions'], ['kalshi'])

    async def test_all_terminal_ends_promptly(self):
        result = await run('both_terminal')
        self.assertEqual(result['terminal_reason'], 'all_selected_sources_terminal_no_permitted_work')
        self.assertLess(result['seconds'], 5)
        self.assertTrue(result['cleanup_complete'])


if __name__ == '__main__':
    unittest.main()
