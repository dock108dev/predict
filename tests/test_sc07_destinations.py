"""Authored offline destination boundaries; no provider or market qualification."""
from copy import deepcopy
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app.comparison import scanner_destinations
from app.comparison.current_dependencies import digest
from tests.test_sc02_projection import frame
from tests.test_sc03_tickets import catalog


class DestinationGuards(TestCase):
    def setUp(self):
        self.items = frame()[0]['instruments']
        self.catalog = catalog(self.items)
        # Exercise the actual consumer bytecode with optimization enabled.
        namespace = dict(__file__=scanner_destinations.__file__,
                         __package__=scanner_destinations.__package__)
        source = Path(scanner_destinations.__file__).read_text()
        exec(compile(source, scanner_destinations.__file__, 'exec', optimize=1), namespace)
        self.optimized = namespace['Destinations']

    def unsafe_route(self, template):
        result = deepcopy(self.catalog)
        route = result['routes']['authored_route_0']
        route['template'] = template
        route['evidence']['retained']['documented_template'] = template
        route['evidence']['sha256'] = digest(route['evidence']['retained'])
        market = result['markets'][0]
        market['url'] = template.replace('{market}', '0')
        market['evidence']['retained']['url'] = market['url']
        market['evidence']['sha256'] = digest(market['evidence']['retained'])
        return result

    def test_optimized_execution_preserves_url_and_evidence_guards(self):
        with patch('socket.socket.connect', side_effect=AssertionError('test_provider_request')):
            self.assertEqual(self.optimized(self.catalog).resolve(self.items[0])['state'], 'verified')
            for url in ('http://kalshi.com/authored-fixture/{market}',
                        'https://other.test/authored-fixture/{market}',
                        'https://kalshi.com/authored-fixture/{market}?op_order_side=yes',
                        'https://kalshi.com/'):
                with self.subTest(url=url):
                    result = self.optimized(self.unsafe_route(url)).resolve(self.items[0])
                    self.assertEqual(result['state'], 'unavailable')
                    self.assertIsNone(result['url'])
            forged = deepcopy(self.catalog)
            forged['markets'][0]['evidence']['sha256'] = '0' * 64
            self.assertEqual(self.optimized(forged).resolve(self.items[0])['state'], 'unavailable')

    def test_malformed_route_expansion_fails_closed(self):
        for consumer in (scanner_destinations.Destinations, self.optimized):
            for suffix in ('{market.missing}', '{market[999]}'):
                with self.subTest(consumer=consumer, suffix=suffix):
                    result = consumer(self.unsafe_route('https://kalshi.com/' + suffix)).resolve(self.items[0])
                    self.assertEqual(result['state'], 'unavailable')
                    self.assertIsNone(result['url'])

    def test_duplicate_exact_bindings_are_ambiguous(self):
        self.catalog['markets'].append(deepcopy(self.catalog['markets'][0]))
        for consumer in (scanner_destinations.Destinations, self.optimized):
            result = consumer(self.catalog).resolve(self.items[0])
            self.assertEqual(result['reason'], 'verified_exact_market_destination_missing')
            self.assertIsNone(result['url'])
