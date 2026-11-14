from fractions import Fraction
from unittest.mock import patch

import pytest

from app.dashboard.local_security import PublicRequestError
from app.dashboard.replay_api import load
from app.comparison.inspection_math import starting_fee_terms
from app.comparison.inspection_settlement import settlement_terms


def test_practice_move_ranks_using_actual_cent_allocation():
    query = dict(dataset='practice', view='arbs', stake='100', positive='on')
    assert load(dict(query, frame='initial'))['total'] == 0
    result = load(dict(query, frame='changed'))
    (group,) = result['rows']
    (pair,) = group['pairs']
    math = pair['inspection']
    assert [leg['allocation_usd'] for leg in math['legs']] == ['48.84', '51.16']
    assert [leg['win_receipt_usd'] for leg in math['legs']] == ['107.448', '107.436']
    assert math['minimum_profit_usd'] == '7.436'
    assert Fraction(pair['assumed_scenario']['scenario_minimum_usd']) == Fraction(1700, 291)
    assert Fraction(math['ideal_profit_usd']) > Fraction(math['minimum_profit_usd'])
    assert load(dict(query, frame='changed', profit='7.44'))['total'] == 0


def test_replay_detail_is_revision_bound_and_never_reads_live_data():
    query = dict(dataset='practice', view='ev', basis='before', group='offer')
    with patch('app.storage.odds_replay.connect', side_effect=AssertionError('live data connection')):
        page = load(dict(query, frame='initial'))
        assert page['replay']['synthetic'] is True
        assert page['coverage'] == dict(offers=6, current=6, before=6, reviewed=0, conservative=0, sportsbooks=0)
        modeled = load(dict(query, frame='initial', basis='conservative'))
        assert Fraction(modeled['rows'][0]['score']) == Fraction(900, 101)
        assert modeled['rows'][0]['offers'][0]['metric'] == 'net_return_percent'
        reviewed = load(dict(query, frame='initial', basis='reviewed'))
        assert all(group['score'] is None for group in reviewed['rows'])
        (offer,) = page['rows'][0]['offers']
        selection = dict(query, id=offer['id'], result_id=offer['evidence_result_id'])
        detail = load(dict(selection, frame='initial'), details=True)
        assert detail['inspection']['reviewed']['available'] is False
        assert detail['inspection']['starting_fee_terms']['values'] == [['Fictional assumption', '1% of acquisition cost']]
        assert detail['inspection']['assumed_scenario']['upfront_fees_usd'] == ['100/101']
        with pytest.raises(PublicRequestError, match='revision changed'):
            load(dict(selection, frame='changed'), details=True)


def test_saved_starting_terms_survive_missing_tier_and_expired_review():
    at = '2026-11-08T04:00:10+00:00'
    us = starting_fee_terms({'venue': 'polymarket_us'}, at)
    assert us['values'] == [['Historical assumption', '0.0695 taker coefficient'],
                            ['Recorded taker tiers', '0.095 / 0.085 / 0.075 / 0.0695']]
    nhl = starting_fee_terms({'venue': 'prophetx', 'league': 'NHL'}, at)
    assert nhl['in_review_window'] is False
    assert nhl['values'] == [['Recorded public NHL taker formula', '0.035 × price × (1 − price) per contract']]


@pytest.mark.parametrize(('treatment', 'payout', 'refund_fees', 'expected'), [
    ('fraction', '1/2', 'not_applicable', ('0.5', '0.2')),
    ('stake_refund', None, 'retained', ('0.3', '0')),
    ('predicate', None, 'not_applicable', ('0', '-0.3')),
])
def test_inspection_distinguishes_fractional_settlement_refund_and_loss(treatment, payout, refund_fees, expected):
    row = dict(cost_per_normal_claim='0.30', market={'market': 'winner'})
    original = dict(binding={'verified': True}, native_contract={'same_outcome': {
        'predicate': {'domain': 'home_margin', 'operator': 'lt', 'threshold': '0', 'subject_id': None},
        'equality': dict(treatment=treatment, payout=payout, refund_fees=refund_fees, unknown_reason=None),
        'scoring': {'overtime': 'included', 'score_domain': 'integer'},
    }})
    result = settlement_terms(row, original)
    tie = result['outcomes'][2]
    assert tie['label'] == 'Game ends tied'
    assert (tie['payout_usd'], tie['profit_usd']) == expected
    assert result['outcomes'][3]['payout_usd'] is None
    assert settlement_terms(row)['outcomes'][2]['payout_usd'] is None
