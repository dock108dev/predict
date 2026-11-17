from contextlib import closing
from fractions import Fraction
import sqlite3
from unittest.mock import patch

import pytest

from app.dashboard.local_security import PublicRequestError
from app.dashboard.replay_api import load
from app.storage import odds_replay
from app.storage.comparison_snapshot import pack, unpack
from app.comparison.inspection_math import starting_fee_terms
from app.comparison.inspection_settlement import settlement_terms
from tests.replay_fixture import write_archives


@pytest.fixture
def saved_archives(tmp_path, monkeypatch):
    write_archives(tmp_path)
    monkeypatch.setattr(odds_replay, 'DIRECTORY', tmp_path)


def test_saved_prices_show_prefee_payoff_and_withhold_after_fee_payoff(saved_archives):
    query = dict(dataset='frozen', view='arbs', stake='100')
    assert load(dict(query, positive='on'))['total'] == 0
    result = load(dict(query, dataset='preview'))
    (group,) = result['rows']
    (pair,) = group['pairs']
    math = pair['inspection']
    assert [leg['allocation_usd'] for leg in math['legs']] == ['48.84', '51.16']
    assert [leg['win_receipt_usd'] for leg in math['legs']] == ['107.448', '107.436']
    assert math['minimum_profit_usd'] == '7.436'
    assert pair['score'] is None
    assert pair['retail_payoff']['available'] is False
    assert pair['retail_payoff']['reason'] == 'pair_missing_leg_fees'
    assert Fraction(math['ideal_profit_usd']) > Fraction(math['minimum_profit_usd'])
    assert load(dict(query, dataset='preview', positive='on'))['total'] == 0
    assert load(dict(query, dataset='preview', profit='7.44'))['total'] == 0


def test_replay_detail_is_revision_bound_and_never_reads_live_data(saved_archives):
    query = dict(dataset='frozen', view='ev', basis='before', group='offer')
    with patch('app.storage.odds_replay.connect', side_effect=AssertionError('live data connection')):
        page = load(query)
        assert page['replay']['synthetic'] is False
        assert page['coverage'] == dict(offers=6, current=6, before=6, reviewed=0, conservative=0, sportsbooks=6,
                                        after_fees=0)
        sportsbook_view = load(dict(query, basis='sportsbooks'))
        assert all(group['offers'][0]['value_basis'] == 'before' for group in sportsbook_view['rows'])
        modeled = load(dict(query, basis='conservative'))
        assert all(group['score'] is None for group in modeled['rows'])
        assert all(group['offers'][0]['value'] is None for group in modeled['rows'])
        reviewed = load(dict(query, basis='reviewed'))
        assert all(group['score'] is None for group in reviewed['rows'])
        offer = next(group['offers'][0] for group in page['rows'] if group['offers'][0]['id'] == 'practice-offer-0')
        assert offer['value'] == '10'
        assert offer['fair_reference']['method'] == 'authored_probability'
        selection = dict(query, id=offer['id'], result_id=offer['evidence_result_id'])
        detail = load(selection, details=True)
        assert detail['inspection']['reviewed']['available'] is False
        assert detail['inspection']['starting_fee_terms'] is None
        assert detail['inspection']['assumed_scenario']['available'] is False
        assert detail['inspection']['trade_fee']['reason'] == 'synthetic_account_terms_unavailable'
        with pytest.raises(PublicRequestError, match='revision changed'):
            load(dict(selection, dataset='preview'), details=True)


def test_saved_list_and_detail_use_the_same_per_offer_pregame_cutoff(saved_archives):
    path = odds_replay.DIRECTORY / 'frozen.sqlite3'
    offer_id = 'practice-offer-0'
    with closing(sqlite3.connect(path)) as db, db:
        board = unpack(db.execute("SELECT payload FROM archive WHERE kind='board'").fetchone()[0])
        offer = next(row for row in board['rows'] if row['id'] == offer_id)
        offer['captured_at'] = offer['start_at']
        db.execute("UPDATE archive SET payload=? WHERE kind='board'", (pack(board),))
        (payload,) = db.execute('SELECT payload FROM detail WHERE id=?', (offer_id,)).fetchone()
        detail = unpack(payload)
        detail['row']['captured_at'] = offer['captured_at']
        db.execute('UPDATE detail SET payload=? WHERE id=?', (pack(detail), offer_id))

    query = dict(dataset='frozen', view='ev', basis='before', group='offer')
    default = load(query)
    assert default['archive_counts']['observations'] == 5
    assert default['archive_counts']['pairs'] == 0
    assert offer_id not in {offer['id'] for group in default['rows'] for offer in group['offers']}
    selection = dict(query, id=offer_id, result_id=board['id'])
    with pytest.raises(PublicRequestError, match='Offer unavailable'):
        load(selection, details=True)
    opted_in = load(query, allow_live=True)
    assert opted_in['archive_counts']['observations'] == 6
    assert opted_in['archive_counts']['pairs'] == 1
    assert load(selection, details=True, allow_live=True)['row']['id'] == offer_id


def test_practice_does_not_use_archives_and_selection_requires_exact_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(odds_replay, 'DIRECTORY', tmp_path)
    rows = load(dict(dataset='practice', view='arbs'))['rows']
    payoffs = {row['game_key']: row['pairs'][0]['retail_payoff'] for row in rows}
    positive = payoffs['practice-positive']
    assert (positive['funding_usd'], positive['minimum_net_payout_usd'], positive['minimum_net_profit_usd']) == (
        '100', '125', '25')
    assert {state['net_receipt_usd'] for state in positive['states'].values()} == {'125'}
    assert 'partial_completion' in positive['states_unverified']
    assert not positive['full_arbitrage_qualified']
    assert payoffs['practice-shortfall']['minimum_gross_profit_usd'] == '-0.5'
    assert payoffs['practice-depth']['reason'] == 'pair_execution_depth_insufficient'
    assert payoffs['practice-rules']['reason'] == 'pair_settlement_unverified'
    assert [r['game_key'] for r in load(dict(dataset='practice', view='arbs', positive='on'))['rows']] == [
        'practice-positive']

    ev = load(dict(dataset='practice'))
    offer = ev['rows'][0]['offers'][0]
    query = dict(dataset='practice', id=offer['id'], result_id=ev['replay']['id'])
    detail = load(query, details=True)
    assert detail['provider_requests'] == 0
    assert ev['replay']['synthetic'] is True and 'captured_at' not in ev['replay']
    assert offer['valuation_summary']['display'] == detail['valuation']['display']
    assert detail['valuation']['fees']['entry_usd'] == '0.75'
    assert detail['valuation']['display']['net_ev'] == '+2.82%'
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(PublicRequestError, match='Offer unavailable in this replay revision'):
        load(dict(query, result_id='another-revision'), details=True)


def test_retained_novig_recovers_scoped_zero_without_legacy_reference():
    from app.comparison.conditional_benchmark import reviewed_fee
    from app.dashboard.replay_api import archive_detail, archive_offer
    from app.storage.store import stamp

    at = '2026-11-08T04:00:10Z'
    row = dict(id='novig-selected', venue='novig', kind='single', game_state='scheduled',
        start_at='2026-11-09T01:20:00+00:00', market=dict(market='spread', period='full_game', line='3.5'),
        source=dict(provider='the_odds_api', native_side='bookmaker_outcome'),
        original=dict(value='5', units='decimal_odds', payout='1', payout_units='USD'),
        price_current=True, cost_per_normal_claim='0.2', gross_return_percent='1475/139',
        times=dict(source_at='2026-11-08T03:47:47Z', received_at='2026-11-08T03:47:54Z'),
        reference_calculation=dict(available=True, venue='pinnacle', fair_decimal_odds='4.52'),
        probability='123/556')
    row['conditional_trade_benchmark'] = reviewed_fee(row, at=stamp(at),
        event={'start_at': row['start_at']}, group=row['market'])
    saved = archive_offer(row, at)
    inspected = archive_detail(dict(row=row, captured_at=at), 'capture')['inspection']
    assert saved['trade_fee'] == inspected['trade_fee']
    assert saved['trade_fee']['trade_fee_usd'] == '0'
    assert saved['trade_fee']['classification'] == 'recorded_scope'
    assert saved['gross_return_percent'] is None and inspected['probability'] is None
    assert 'pinnacle' not in str(inspected).casefold()
    changed = archive_offer(dict(row, probability='1/2', gross_return_percent='150'), at)
    assert changed == saved
    forged = dict(row, conditional_trade_benchmark=dict(row['conditional_trade_benchmark'], quantity='2'))
    assert not archive_offer(forged, at).get('trade_fee')


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
