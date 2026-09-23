"""Selection policy is shared by HTTP routes and direct product callers."""
import unittest
from unittest.mock import AsyncMock, Mock
from multidict import MultiDict
from aiohttp.test_utils import AioHTTPTestCase

from app.dashboard import product_view
from app.dashboard.multi_game import rank_filter
from app.dashboard.multi_game_server import create_app
from app.dashboard.query_policy import validate_http_query, validate_assumptions
from app.dashboard.session_projection import SessionProjection
from app.reference.multi_page import rank_research


class DirectPolicy(unittest.TestCase):
    def test_invalid_choices_do_not_fall_through_in_direct_callers(self):
        for call in (
            lambda: rank_filter([], sort='typo'),
            lambda: rank_filter([], freshness='fresh'),
            lambda: rank_research([], sort='typo'),
            lambda: product_view.dashboard({}, {'view': 'typo'}, {}),
            lambda: product_view.calculate({}, {}, {'scenario': 'free'}),
        ):
            with self.subTest(call=call), self.assertRaisesRegex(ValueError, 'Unknown'):
                call()

    def test_duplicate_selectors_and_blank_probability_basis(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            validate_http_query(MultiDict([('cutoff', 'a'), ('cutoff', 'b')]))
        for basis in ('', '   ', '\t\n'):
            assumptions = {'game~side': {'probability': '0', 'basis': basis}}
            for call in (lambda: validate_assumptions(assumptions),
                         lambda: product_view.dashboard({}, {'view': 'ev'}, assumptions)):
                with self.subTest(basis=basis), self.assertRaisesRegex(ValueError, 'explicit source or basis'):
                    call()
        value = {'game~side': {'probability': '0', 'basis': ' explicit input '}}
        self.assertIs(validate_assumptions(value), value)
        self.assertEqual(value['game~side']['basis'], ' explicit input ')

    def test_removed_helpers_and_unused_state_do_not_return(self):
        self.assertFalse(hasattr(product_view, 'reference_for'))
        p = SessionProjection()
        p.apply(dict(type='session_started', session_id='synthetic',
                     observed_at='2026-09-23T12:00:00+00:00', spec={'mode': 'mock'}))
        before = p.chain
        p.apply(dict(type='multi_game_selection', session_id='synthetic',
                     observed_at='2026-09-23T12:00:00+00:00', games=[], coverage={}))
        self.assertEqual(p.cursor, 2)
        self.assertNotEqual(p.chain, before)
        self.assertFalse(hasattr(p, 'legacy'))


class RoutePolicy(AioHTTPTestCase):
    async def get_application(self):
        self.owner = Mock()
        self.owner.session = None
        self.owner.active.return_value = False
        self.owner.saved.return_value = []
        self.owner.close = AsyncMock()
        return create_app(owner=self.owner, sessions={})

    async def test_all_selection_routes_reject_before_loading_data(self):
        for route in ('dashboard', 'calculate', 'sessions', 'resolution'):
            for query in ('sort=typo', 'view=typo', 'scenario=free',
                          'cutoff=a&cutoff=b', 'quantity=NaN'):
                with self.subTest(route=route, query=query):
                    response = await self.client.get('/api/' + route + '?' + query)
                    self.assertEqual(response.status, 422, await response.text())
        self.owner.saved.assert_not_called()
