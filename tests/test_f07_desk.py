"""Disposable price, fee, settlement and route fixtures for the ordinary desk."""
from fractions import Fraction as F
from pathlib import Path
import unittest

import pytest
from aiohttp.test_utils import make_mocked_request

from app.comparison.snapshot_fee_outcome import EXPIRED, outcome
from app.comparison.snapshot_math import before_fee_pair
from app.comparison.snapshot_pair_fees import pair_fees
from app.dashboard.multi_game_server import create_app
from app.dashboard.trade_desk import page
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner
from tests.test_f06_prophetx_retail import AT, retail_row, review  # noqa: F401
from tests.test_trade_desk import quote, result


def paired(league, review):
    left = retail_row(league, '0.4')
    left.update(captured_at=AT.isoformat(), game_state='scheduled')
    right = quote('novig-offer', 'novig', operator='le', threshold=-1)
    right.update(start_at=left['start_at'], cost_per_normal_claim='0.5', league=league, game_state='scheduled')
    left['trade_fee'] = outcome(left, at=AT, phase='scheduled', review=review)
    right['trade_fee'] = dict(available=True, classification='exact_public', fee_cashflows={'at_fill_usd': '0'},
                              evidence={'fee_rate': '0'})
    return left, right


def shown_pair(left, right):
    proof = before_fee_pair(left, right, 'exact-market')
    pair = dict(left, id='arb', legs=[left['id'], right['id']], before_fees=proof)
    view = page(result(left, right), {'stake': '100'},
                ('arbs', 'gross_return_percent', 0, 25), captured_pairs=[pair], policy='policy')
    assert view['provider_requests'] == 0
    return view['rows'][0]['pairs'][0]


@pytest.mark.parametrize('league,fill_fee,settlement_fee,profits', [
    ('NHL', '0.93', '0', ('10.17', '10.19')),
    ('NBA', '0', '1.34', ('9.76', '11.12')),
])
def test_stakes_fees_and_completed_game_payoffs(league, fill_fee, settlement_fee, profits, review):
    pair = shown_pair(*paired(league, review))
    assert [leg['allocation_usd'] for leg in pair['inspection']['legs']] == ['44.44', '55.56']
    retail = pair['retail_payoff']
    assert retail['available']
    first, second = retail['legs']
    assert first['at_fill_usd'] == fill_fee
    assert first['settlement_usd'] == {'first_wins': settlement_fee, 'second_wins': '0'}
    assert second['at_fill_usd'] == '0'
    assert F(retail['funding_usd']) == 100 + F(fill_fee)
    assert tuple(state['net_profit_usd'] for state in retail['states'].values()) == profits


def test_stale_terms_keep_supported_leg_and_withhold_net_payoff(review):
    left, right = paired('NHL', review)
    expired = dict(review, review_before=AT.isoformat())
    left['trade_fee'] = outcome(left, at=AT, phase='scheduled', review=expired)
    pair = shown_pair(left, right)
    assert pair['inspection']['minimum_profit_usd'] == '11.1'
    retail = pair['retail_payoff']
    assert not retail['available'] and 'states' not in retail
    assert retail['legs'][0] == {'available': False, 'reason': EXPIRED}
    assert retail['legs'][1]['at_fill_usd'] == '0'


def test_independent_payoff_uses_working_capture_clock(review):
    from app.dashboard.coverage_finance_inputs import _retail_payoff

    left, right = paired('NHL', review)
    proof = before_fee_pair(left, right, 'exact-market')
    pair = dict(before_fees=proof, legs=[left['id'], right['id']])
    rows = {row['id']: row for row in (left, right)}
    del left['captured_at']
    audited = _retail_payoff(pair, rows, captured_at=AT.isoformat())
    assert audited['available'] and audited['legs'][0]['at_fill_usd'] == '0.93'


def test_sized_live_novig_fee_is_unavailable_with_only_one_claim_evidence(review):
    left, right = paired('NHL', review)
    left['game_state'] = 'live'
    right['game_state'] = 'live'
    right['trade_fee']['evidence'] = {}
    retail = shown_pair(left, right)['retail_payoff']
    assert not retail['available'] and retail['legs'][0]['at_fill_usd'] == '0.93'
    assert retail['legs'][1]['reason'] == 'pair_fee_size_unverified'


def test_exact_line_split_payout_is_a_separate_settlement_case(review):
    left, right = paired('NBA', review)
    for row in (left, right):
        row['same_outcome']['key'][10] = ['fraction', ['half'], [1, 2]]
    right['same_outcome']['key'][9][2] = [-2, 1]
    retail = shown_pair(left, right)['retail_payoff']
    assert retail['legs'][0]['settlement_usd']['equality'] == '0.23'
    assert retail['states']['equality'] == {'net_receipt_usd': '110.88', 'net_profit_usd': '10.88'}


@pytest.mark.parametrize('venue,amount', [('kalshi', '1.75'), ('polymarket_us', '2.38')])
def test_native_sized_fee_reuses_selected_terms_and_rounds_at_size(venue, amount):
    from app.comparison.inspection_math import pair_math
    from app.comparison.snapshot_fee_scope import applicability
    from app.comparison.conditional_benchmark import basis
    from tests.test_f04_kalshi_public import input_row
    from tests.test_f05_polymarket_public import AT as PM_AT, native

    if venue == 'kalshi':
        row, terms, at = input_row()
    else:
        at = PM_AT
        row = native('scheduled', 'Long')
        row['original']['value'] = '0.50'
        row['fee_applicability'] = applicability(row['original_record'])
        terms = basis(venue, at=at)
    row['captured_at'] = at.isoformat()
    row['trade_fee'] = outcome(row, at=at, phase='scheduled', review=terms)
    proof = dict(value='0', weights=['0.5', '0.5'],
                 settlement_payouts={'first_wins': ['1', '0'], 'second_wins': ['0', '1']})
    other = dict(venue='novig', game_state='scheduled', trade_fee=dict(available=True,
                 classification='exact_public', fee_cashflows={'at_fill_usd': '0'}, evidence={'fee_rate': '0'}))
    priced = pair_fees(proof, pair_math(proof, F(100)), [row, other])
    assert priced['available'] and priced['legs'][0]['at_fill_usd'] == amount
    assert priced['minimum_net_profit_usd'] == '-' + amount
    unaligned = pair_fees(proof, pair_math(proof, F('100.02')), [row, other])
    assert not unaligned['available'] and unaligned['legs'][1]['at_fill_usd'] == '0'


def test_native_pair_models_equal_whole_claims_under_a_non_grid_stake():
    from app.comparison.conditional_benchmark import basis
    from app.comparison.inspection_math import pair_math
    from app.comparison.snapshot_fee_scope import applicability
    from tests.test_f04_kalshi_public import input_row
    from tests.test_f05_polymarket_public import AT as pmus_at, native

    kalshi, terms, at = input_row()
    pmus = native('scheduled', 'Long')
    pmus['original']['value'] = '0.55'
    pmus['fee_applicability'] = applicability(pmus['original_record'])
    for row, review, clock in ((kalshi, terms, at), (pmus, basis('polymarket_us', at=pmus_at), pmus_at)):
        row['captured_at'] = clock.isoformat()
        row['trade_fee'] = outcome(row, at=clock, phase='scheduled', review=review)
    proof = dict(value='-100/21', weights=['10/21','11/21'],
                 settlement_payouts={'first_wins':['1','0'],'second_wins':['0','1']})
    priced = pair_fees(proof, pair_math(proof, F('100.02')), [kalshi, pmus])
    assert priced['available'] and priced['sizing']['quantity'] == '95'
    assert priced['sizing']['acquisition_usd'] == '99.75'
    assert priced['sizing']['unused_stake_usd'] == '0.27'
    assert [leg['acquisition_usd'] for leg in priced['legs']] == ['47.5','52.25']
    assert {state['net_receipt_usd'] for state in priced['states'].values()} == {'95'}
    assert F(priced['minimum_net_profit_usd']) < 0


def test_native_census_distinguishes_unobserved_incompatible_stale_and_pending_peers():
    from app.dashboard.coverage_finance_inputs import _native_pair_input_gaps, _pair_key
    from app.storage.comparison_snapshot import before_fee_pairs

    left = quote('left', 'kalshi', threshold=3)
    right = quote('right', 'polymarket_us', threshold=2, operator='le')
    right['selection'] = dict(participant='away', predicate='cover', signed_line='2.5')
    for row in (left, right):
        row['game_state'] = 'scheduled'
        row['binding'] = {'verified': True}
        row['common_odds'] = {'supported': True}
        row['source'] = dict(provider=row['venue'], native_event_id=row['id'], binding_version='fixture')
        event = dict(id=row['id'], competition='NBA', sport='basketball', home='home', away='away',
                     season='2026', stage='regular_season', scheduled_start=row['start_at'],
                     shared_provider_ids={'sportradar':'fixture'}, participants={'Home':'home', 'Away':'away'})
        row['original_record'] = dict(event=event, selection=row['selection'], market_identity={},
            quote=dict(source=row['source'], venue=row['venue'], provenance={}),
            verified=True, orientation_evidence=[])

    selected = {row['id']: row for row in (left, right)}
    pair, = before_fee_pairs([left, right], at=AT.isoformat())
    working = {left['id']: left}

    def gaps(scoped, prices, captured=(), published=()):
        result = _native_pair_input_gaps(scoped, prices, captured, published, at=AT)
        return {row['venue']: row['reasons'] for row in result}

    assert gaps(working, working) == {'kalshi': {'opposing_price_not_observed': 1}}
    assert gaps(selected, working) == {'kalshi': {'exact_opposing_price_not_current': 1}}
    assert gaps(selected, selected, [pair]) == {
        'kalshi': {'pair_awaiting_publication': 1}, 'polymarket_us': {'pair_awaiting_publication': 1}}
    assert not gaps(selected, selected, [pair], {_pair_key(pair, selected)})
    right['game_state'] = 'live'
    assert gaps(selected, selected, [pair]) == {
        'kalshi': {'opposing_phase_mismatch': 1}, 'polymarket_us': {'opposing_phase_mismatch': 1}}
    right['original_record']['event']['shared_provider_ids'] = {'sportradar':'different'}
    assert gaps(selected, working) == {'kalshi': {'opposing_occurrence_or_settlement_unverified': 1}}


@pytest.mark.parametrize('verified', [False, True])
def test_ordinary_ready_and_pending_publish_only_exact_native_pairs(verified, monkeypatch):
    from copy import deepcopy
    from app.storage import ordinary_publication as ordinary

    left = quote('a', 'kalshi', threshold=3)
    right = quote('b', 'polymarket_us', threshold=2, operator='le')
    for row in (left, right):
        row['binding'] = {'verified': True}
        row['common_odds'] = {'supported': True}
        row['occurrence_match'] = dict(status='matched', estimated=not verified,
                                       method='shared_provider_id' if verified else 'unique_metadata')
    monkeypatch.setattr('app.comparison.snapshot_fee_outcome.reviews',lambda at:{})
    monkeypatch.setattr(ordinary,'quote_authority',lambda *args,**kw:{'reasons':['controlled_source_fixture']})
    settings = dict(benchmark_venue='pinnacle',revision='settings')
    inputs = dict(id='input',captured_at=AT.isoformat(),epoch='epoch',policy_identity='policy',
        quotes=[left,right],references=[],reference_provider='sportsgameodds',games=[],sources={},issues=[],capture_seconds=0)
    pending = ordinary.prices(inputs, settings)
    legacy = dict(id='legacy-assumed-pair',legs=['a','b'],before_fees=before_fee_pair(left,right,'fixture'),math={'available':True})
    ready = ordinary.bind(dict(rows=deepcopy(inputs['quotes']),pairs=[legacy],assumptions=settings),inputs,'ready')
    assert len(ready['pairs']) == len(pending['pairs']) == int(verified)
    if verified:
        assert ready['pairs'][0]['before_fees'] == pending['pairs'][0]['before_fees']
        assert ready['pairs'][0]['before_fees']['authority']['policy'] == 'ordinary-verified-opposition-1'
        assert not ready['pairs'][0]['math']['available']


class FeeViewAssets(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_owner_view_routes_serve_shared_census_modules(self):
        provider = InjectedTestProvider()
        provider.database_mode = True
        app = create_app(owner=owner(), sessions={}, current_provider=provider)
        for path in ('/current/coverage', '/admin?section=fees', '/current/assets/fee-census-view.js',
                     '/current/assets/desk-reasons.js', '/view/current/desk-evidence.js'):
            request = make_mocked_request('GET', path, app=app)
            request._match_info = await app.router.resolve(request)
            assert request.match_info.http_exception is None, path
            response = await request.match_info.handler(request)
            assert Path(response._path).is_file(), path
