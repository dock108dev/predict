"""The ordinary fee result and coverage do not depend on an EV calculation."""
from datetime import timedelta
from fractions import Fraction
from unittest.mock import patch

from app.comparison.conditional_benchmark import basis
from app.comparison.current_dependencies import instant
from app.comparison.snapshot_fee_outcome import EXPIRED, outcome, unavailable
from app.dashboard.fee_coverage import census
from app.dashboard.trade_desk import offer
from app.storage import comparison_snapshot as snapshots, ordinary_publication as live
from app.storage.current_rows import contract_id
from tests.test_trade_desk import quote


def test_price_only_publication_keeps_novig_fee_without_pinnacle_until_review_expires():
    review = basis('novig', at=instant('2026-11-09T20:00:00Z'))
    end = instant(review['review_before'])
    at = end - timedelta(seconds=1)
    start = (end + timedelta(hours=1)).isoformat()
    row = quote('offer', 'novig')
    row.pop('reference')
    row.update(start_at=start, source=dict(provider='the_odds_api', native_event_id='game',
        native_market_id='alternate_spread', native_outcome_id='away-2.5', native_side='bookmaker_outcome'),
        times=dict(source_at=at.isoformat(), received_at=at.isoformat()))
    record = dict(event={'start_at': start}, quote=row.copy())
    row['original_record'] = record
    deps = {contract_id(record): ['price', 'contract', 'event', 'receipt']}
    inputs = dict(quotes=[row], captured_at=at.isoformat(), dependencies=deps, policy_identity='policy',
                  epoch='epoch', id='capture', games=[], references=[], sources={}, issues=[], capture_seconds=0)
    from app.comparison import snapshot_fee_outcome
    original_basis = snapshot_fee_outcome.basis
    def captured_basis(venue, *, at):
        return review if venue == 'novig' else original_basis(venue, at=at)
    with patch.object(snapshot_fee_outcome, 'basis', side_effect=captured_basis):
        result = snapshots.defer_details(live.prices(inputs, {'revision': 'settings'}))
    owner = dict(healthy=True, active=True)
    states = dict(novig={'state': 'available'}, pinnacle={'state': 'unavailable'})

    def projected(when, **changes):
        return live.project(result, deps, dict(owner, **changes), states, at=when,
                            policy='policy', epoch='epoch')['rows'][0]

    current = offer(projected(at), 'conditional_return_percent')
    assert current['current'] and not current['reference_current']
    assert current['before_fee'] is None and current['after_fee'] is None
    assert current['trade_fee']['classification'] == 'exact_public'
    assert Fraction(current['trade_fee']['trade_fee_usd']) == 0
    assert current['trade_fee']['fee_cashflows'] == {'at_fill_usd': '0'}

    expired = projected(end)
    assert expired['price_current']
    assert expired['trade_fee']['reason'] == EXPIRED
    assert not expired['trade_fee']['available']
    assert projected(at, global_stopped=True)['trade_fee']['reason'] == 'fee_source_price_not_current'
    assert result['rows'][0]['trade_fee']['available']


def test_live_and_unbound_markets_have_no_inferred_novig_fee():
    at = instant('2026-11-09T20:00:00Z')
    review = basis('novig', at=at)
    row = quote('offer', 'novig')
    assert outcome(row, at=at, phase='live', review=review)['reason'] == 'novig_native_market_phase_and_book_missing'
    row['market']['period'] = 'first_half'
    assert outcome(row, at=at, phase='scheduled', review=review)['reason'] == 'fee_straight_market_scope_unbound'


def test_unfiltered_census_deduplicates_offers_and_keeps_gaps_and_ev_separate():
    supported = quote('novig-alt-1', 'novig')
    source = dict(provider='the_odds_api', native_event_id='game', native_market_id='line-2.5',
                  native_outcome_id='team', native_side='bookmaker_outcome')
    supported.update(current_authority={'price': {'dependency': 'source-alt-1'}}, source=source,
                     game_state='scheduled', trade_fee={'available': True, 'classification': 'exact_public'})
    alternate = dict(supported, id='novig-alt-2', market=dict(supported['market'], line='3.5'),
                     source=dict(source, native_market_id='alternate:line-3.5'),
                     current_authority={'price': {'dependency': 'source-alt-2'}})
    duplicate = dict(supported, id='repeat-presentation', source=dict(source, native_market_id='alternate:line-2.5'),
                     current_authority={'price': {'dependency': 'source-repeat'}})
    live_unknown = quote('live-offer', 'kalshi')
    live_unknown.update(current_authority={'price': {'dependency': 'source-live'}}, game_state='live',
                        trade_fee=unavailable('live_market_fee_evidence_unbound'))
    retained = quote('old-offer', 'prophetx', current=False)
    retained.update(current_authority={'price': {'dependency': 'source-old'}}, game_state='scheduled',
                    price_reasons=['source_expired'])
    rows = [supported, alternate, duplicate, live_unknown, retained]
    inventory = [dict(id='source-'+key, venue=venue, league='NBA', family='spread', period='full_game')
                 for key, venue in [('alt-1', 'novig'), ('alt-2', 'novig'), ('live', 'kalshi'), ('waiting', 'kalshi')]]
    pairs = [dict(before_fees=True, legs=[supported['id'], live_unknown['id']])]
    counts = census(dict(rows=rows, publication={}), inventory, pairs=pairs, policy='policy')
    assert counts['total']['current'] == 3
    assert counts['total']['covered'] == 2 and counts['total']['uncovered'] == 1
    assert counts['total']['any_after_fee_ev'] == 0 and counts['total']['retained_unavailable'] == 1
    assert counts['duplicate_published_rows'] == 1
    assert counts['current_presentation_rows'] == 4
    assert counts['published_source_price_keys'] == 5
    assert counts['published_working_prices'] == 3 and counts['unpublished_working_prices'] == 1
    assert counts['published_without_working_price'] == 2
    assert counts['pair_coverage'] == {'current_before_fee_pairs': 1, 'both_legs_have_normalized_fee': 0}
    assert next(row for row in counts['by_scope'] if row['phase'] == 'in_game')['uncovered'] == 1
    assert counts['retained_price_gap_reasons'] == {'source_expired': 1}
    assert counts['missing_reasons'] == {'live_market_fee_evidence_unbound': 1}
