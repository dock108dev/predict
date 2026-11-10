"""Polymarket US standard taker fees through the ordinary offer and inspection payloads."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction

import pytest

from app.comparison.current_dependencies import instant
from app.comparison.inspection_math import offer_disclosures, offer_math
from app.comparison.snapshot_polymarket_fee import CUTOVER, order_fee
from app.dashboard.fee_coverage import census
from app.dashboard.trade_desk import page
from app.storage import comparison_snapshot as snapshots, ordinary_publication as live
from app.storage.current_rows import contract_id
from tests.test_trade_desk import quote

AT = instant('2026-11-10T02:00:00Z')


def fill(price, quantity, at=None):
    item = dict(price=price, quantity=quantity)
    return dict(item, trade_time=at) if at else item


@pytest.mark.parametrize(('tier', 'fee'), [('0.095', '2.38'), ('0.085', '2.12'),
                                           ('0.075', '1.88'), ('0.0695', '1.74')])
def test_standard_tiers_at_midpoint(tier, fee):
    audit = order_fee('market', inserted_at=CUTOVER, evaluated_at=CUTOVER,
                      fills=[fill('0.50', '100')], tier=tier)
    assert audit['entry_fees'] == fee
    assert Fraction(audit['entry_cash_requirement']) == 50 + Fraction(fee)
    assert audit['entry_cash_requirement'] == audit['entry_balance_debit']


def test_half_even_ties_and_cumulative_cap_only_reduce():
    def calculate(fills):
        return order_fee('market', inserted_at=CUTOVER, evaluated_at=CUTOVER, fills=fills)
    assert calculate([fill('0.50', '60')])['entry_fees'] == '1.42'  # Exact $1.425.
    assert calculate([fill('0.50', '20')])['entry_fees'] == '0.48'  # Exact $0.475.
    for count, charges, total in [('2', ['0.05', '0.05', '0.04'], '0.14'),
                                  ('1', ['0.02', '0.02', '0.02'], '0.06')]:
        audit = calculate([fill('0.50', count)] * 3)
        assert [x['amount'] for x in audit['trace']] == charges
        assert audit['entry_fees'] == total
    audit = calculate([fill('0.10', '10'), fill('0.50', '10')])
    assert [x['amount'] for x in audit['trace']] == ['0.09', '0.23']


def test_order_inserted_before_cutover_keeps_its_coefficient_after_cutover():
    earlier = '2026-11-06T17:59:59.999999Z'
    before = order_fee('market', inserted_at=earlier, evaluated_at=CUTOVER,
                       fills=[fill('0.50', '50', earlier), fill('0.50', '50', CUTOVER)])
    at = order_fee('market', inserted_at=CUTOVER, evaluated_at=CUTOVER, fills=[fill('0.50', '100')])
    assert before['schedule']['coefficient'] == '0.0695' and before['entry_fees'] == '1.74'
    assert at['schedule']['coefficient'] == '0.095' and at['entry_fees'] == '2.38'
    with pytest.raises(ValueError, match='at or after insertion'):
        order_fee('market', inserted_at=CUTOVER, evaluated_at=CUTOVER,
                  fills=[fill('0.50', '100', earlier)])


def native(phase, side, *, at=AT):
    start = (at + timedelta(seconds=120 if phase == 'scheduled' else -120)).isoformat()
    row = quote('pmus-offer', 'polymarket_us')
    row.pop('reference')
    source = dict(provider='polymarket_us', native_event_id='game', native_market_id='market',
                  native_outcome_id='instrument', native_side=side, quote_side='buy')
    original = dict(value='0.30' if side == 'Short' else '0.55', units='usd_per_contract',
                    payout='1', payout_units='USD', quantity_units='contracts')
    if side == 'Short':
        original.update(native_value='0.70', native_units='usd_per_contract',
                        transformation='one_minus_native_bid')
    row.update(start_at=start, source=source, original=original,
               times=dict(source_at=at.isoformat(), received_at=at.isoformat()))
    record = dict(event=dict(scheduled_start=start, status={'live': phase == 'live'}), quote=row.copy(),
                  comparison_source_metadata=dict(native_key=['polymarket_us', 'game', 'market', 'instrument', side],
                      native_market_type='basketball_team_full_game_spread',
                      public_retail_observation=dict(market_id='market', instrument_id='instrument', long=side == 'Long',
                          values=dict(minimumTradeQty='1', orderPriceMinTickSize='0.01', feeCoefficient='0.0695'))))
    return dict(row, original_record=record)


def inputs_for(row, *refs, at=AT):
    deps = {contract_id(r['original_record']): [r['id'], 'contract', 'event', 'receipt'] for r in (row, *refs)}
    return dict(quotes=[row], captured_at=at.isoformat(), dependencies=deps, policy_identity='policy',
                epoch='epoch', id='capture', games=[], references=list(refs), sources={}, issues={}, capture_seconds=0)


SETTINGS = {'revision': 'settings', 'benchmark_venue': 'pinnacle'}
OWNER = dict(healthy=True, active=True)


def project(result, inputs, *, pinnacle='unavailable', pmus='available', at=AT):
    return live.project(result, inputs['dependencies'], OWNER,
                        dict(polymarket_us={'state': pmus}, pinnacle={'state': pinnacle}),
                        at=at, policy='policy', epoch='epoch')


@pytest.mark.parametrize('phase', ['scheduled', 'live'])
@pytest.mark.parametrize('side', ['Long', 'Short'])
def test_ordinary_standalone_fee_reaches_desk_and_inspection_without_pinnacle(phase, side):
    row = native(phase, side)
    inputs = inputs_for(row)
    result = project(snapshots.defer_details(live.prices(inputs, SETTINGS)), inputs)
    current, = result['rows']
    view = page(result, {'basis': 'conservative'}, ('ev', None, 0, 25))
    card, = view['rows'][0]['offers']
    assert card['current'] and card['game_state'] == phase
    assert not card['reference_current'] and card['conservative'] is None and card['after_fee'] is None
    fee = card['trade_fee']
    assert fee['available'] and fee['classification'] == 'conservative'
    assert fee['trade_fee_usd'] == '0.02'
    assert fee['evidence']['acquired_price_usd'] == row['original']['value']
    assert fee['evidence']['native_side'] == side and fee['evidence']['phase'] == phase
    assert fee['evidence']['coefficient'] == '0.095'
    expanded = snapshots.expand_row(current)
    assert offer_math(expanded)['trade_fee'] == fee
    assert '0.095' in offer_disclosures(expanded, inputs['captured_at'], [row])['starting_fee_terms']['values'][1][1]
    counts = census(result, [])
    assert counts['total']['covered'] == 1
    assert counts['total']['any_after_fee_ev'] == counts['total']['exact_pinnacle_reference'] == 0
    assert counts['by_scope'][0]['phase'] == ('in_game' if phase == 'live' else 'pregame')
    assert not project(live.prices(inputs, SETTINGS), inputs, pmus='paused')['rows'][0]['trade_fee']['available']


def test_documented_period_and_review_boundary():
    end = instant('2026-11-11T01:58:05Z')
    at = end - timedelta(seconds=1)
    row = native('scheduled', 'Long', at=at)
    row['market']['period'] = 'first_half'
    meta = row['original_record']['comparison_source_metadata']
    meta['native_market_type'] = 'basketball_team_first_half_spread'
    inputs = inputs_for(row, at=at)
    ready = live.prices(inputs, SETTINGS)
    assert project(ready, inputs, at=at)['rows'][0]['trade_fee']['available']
    expired, = project(ready, inputs, at=end)['rows']
    assert expired['price_current'] and not expired['trade_fee']['available']
    assert expired['trade_fee']['reason'] == 'conditional_fee_review_expired_or_not_effective'
    meta['native_market_type'] = 'basketball_team_full_game_spread'
    assert not live.prices(inputs, SETTINGS)['rows'][0]['trade_fee']['available']


def test_retained_native_long_and_short_metadata_bind_without_an_account_tier():
    from app.comparison.conditional_benchmark import basis
    from app.comparison.snapshot_fee_outcome import outcome
    from app.comparison.snapshot_fee_scope import applicability
    from tests.test_ev09_n01 import retained

    bundle, _ = retained()
    checked = {}
    for record in bundle['records']:
        native_quote = record['quote']
        if native_quote['venue'] != 'polymarket_us':
            continue
        market = record['market_identity']
        row = dict(native_quote, fee_applicability=applicability(record),
                   league=record['event']['competition'], market=dict(market='winner', period=market['period']))
        # Evaluate a counterfactual new order at the retained native price.
        fee = outcome(row, at=AT, phase='scheduled', review=basis('polymarket_us', at=AT))
        assert fee['available'] and fee['trade_fee_usd'] == '0.02'
        checked[fee['evidence']['native_side']] = fee['evidence']['acquired_price_usd']
    assert checked == {'Long': '0.5750', 'Short': '0.4275'}


@pytest.mark.parametrize(('field', 'value', 'reason'), [
    ('native_value', '0.65', 'polymarket_short_acquisition_price_unbound'),
    ('is_combo', True, 'polymarket_fee_product_scope_unbound'),
    ('long', True, 'polymarket_fee_product_scope_unbound'),
    ('minimumTradeQty', '2', 'polymarket_one_claim_quantity_unsupported'),
])
def test_offer_scope_fails_closed(field, value, reason):
    row = native('scheduled', 'Short')
    retail = row['original_record']['comparison_source_metadata']['public_retail_observation']
    target = row['original'] if field == 'native_value' else retail['values'] if field == 'minimumTradeQty' else retail
    target[field] = value
    inputs = inputs_for(row)
    current, = project(live.prices(inputs, SETTINGS), inputs)['rows']
    assert current['price_current']
    assert not current['trade_fee']['available'] and current['trade_fee']['reason'] == reason


@pytest.mark.parametrize('phase', ['scheduled', 'live'])
def test_ordinary_after_fee_ev_requires_both_current_reference_and_settlement(phase):
    from tests.test_snapshot_benchmark import execution, references

    original = execution(native='no', cost='0.30')
    record = original['original_record']
    short = native(phase, 'Short')
    source = dict(record['quote']['source'], **short['source'])
    source['native_outcome_id'] = 'no'
    original.update(start_at=short['start_at'], source=source, original=short['original'], times=short['times'])
    record['quote'].update(source=source, original=short['original'], times=short['times'])
    record['event'].update(scheduled_start=short['start_at'], status={'live': phase == 'live'})
    meta = short['original_record']['comparison_source_metadata']
    meta['native_market_type'] = 'basketball_team_full_game_total'
    meta['native_key'][3] = 'no'
    meta['public_retail_observation']['instrument_id'] = 'no'
    record['comparison_source_metadata'].update(meta)

    refs = references()
    for ref in refs:
        reference_record = ref['original_record']
        reference_record['event']['scheduled_start'] = short['start_at']
        reference_quote = reference_record['quote']
        reference_quote['times'] = short['times']
        reference_quote['provider_clocks'] = dict(book=AT.isoformat(), market=AT.isoformat(), selected_basis='market')
        ref.update(source=reference_quote['source'], times=short['times'])
    inputs = inputs_for(original, *refs)
    calculated = snapshots.calculate(inputs)
    ready = live.bind(deepcopy(calculated), inputs, 'ready')
    ready = snapshots.unpack(snapshots.pack_read(snapshots.defer_details(ready)), lazy=True)
    current, = project(ready, inputs, pinnacle='available')['rows']
    assert current['exact_pinnacle_reference_current'] and current['trade_fee']['available']
    assert current['conditional_return_percent'] is None
    assert Fraction(current['conservative_return_percent']) == 25
    withdrawn, = project(ready, inputs, pinnacle='paused')['rows']
    assert withdrawn['trade_fee']['available'] and withdrawn['conservative_return_percent'] is None

    row, = calculated['rows']
    row['snapshot_benchmark']['selected_identity']['equality_basis'] = 'assumed'
    ready = live.bind(calculated, inputs, 'ready')
    current, = project(ready, inputs, pinnacle='available')['rows']
    assert current['exact_pinnacle_reference_current'] and current['trade_fee']['available']
    assert current['conservative_return_percent'] is None


@pytest.mark.parametrize('side', ['Long', 'Short'])
def test_nba_full_game_winner_ev_uses_observed_overtime_and_completed_game_rule(side):
    from tests.test_snapshot_benchmark import execution, references

    deadline = instant('2026-11-11T01:58:05Z')
    at = deadline - timedelta(seconds=1)
    native_side = native('scheduled', side, at=at)
    outcome_id = 'yes' if side == 'Long' else 'no'
    row = execution(native=outcome_id, family='moneyline', line=None)
    record = row['original_record']
    source = dict(record['quote']['source'], **native_side['source'])
    source['native_outcome_id'] = outcome_id
    row.update(league='NBA', market=dict(market='winner', period='full_game', line=None),
               start_at=native_side['start_at'], source=source, original=native_side['original'],
               times=native_side['times'], binding={'verified': True})
    record['quote'].update(source=source, original=row['original'], times=row['times'])
    record['selection']['predicate'] = 'win' if side == 'Long' else 'not_win'
    meta = record['comparison_source_metadata']
    meta.update(native_side['original_record']['comparison_source_metadata'])
    meta['native_market_type'] = 'basketball_team_full_game_winner'
    meta['native_key'][3] = outcome_id
    meta['public_retail_observation']['instrument_id'] = outcome_id
    overtime = dict(basis='selected_source_description', overtime='included', text='overtime is included')
    meta['scoring_scope']['evidence'] = [overtime]

    refs = references(family='moneyline', line='0')
    for item in [row, *refs]:
        original = item['original_record']
        original['event'].update(competition='NBA', scheduled_start=row['start_at'])
        original['market_identity'].update(competition='NBA', scheduled_start=row['start_at'])
        quote = original['quote']
        quote.update(times=row['times'],
                     provider_clocks=dict(book=at.isoformat(), market=at.isoformat(), selected_basis='market'))
        item.update(source=quote['source'], times=quote['times'])

    def projected(when=at):
        inputs = inputs_for(row, *refs, at=at)
        ready = live.bind(snapshots.calculate(inputs), inputs, 'ready')
        return project(snapshots.defer_details(ready), inputs, at=when, pinnacle='available')

    result = projected()
    current, = result['rows']
    counts = census(result, [])['total']
    assert counts['current'] == counts['covered'] == counts['exact_pinnacle_reference'] == 1
    assert counts['any_after_fee_ev'] == 1
    model = snapshots.expand_row(current)['conservative_trade_benchmark']
    risk = Fraction(row['original']['value']) + Fraction('0.02')
    assert Fraction(model['return_percent']) == 100 * (Fraction(current['probability']) - risk) / risk
    assert not model['full_state_net_ev']
    assert model['evidence']['completed_game_rule']['url'] == 'https://official.nba.com/rule-no-5-scoring-and-timing/'

    expired = census(projected(deadline), [])
    assert expired['total']['current'] == expired['total']['exact_pinnacle_reference'] == 1
    assert expired['total']['covered'] == expired['total']['any_after_fee_ev'] == 0
    assert expired['missing_reasons'] == {'conditional_fee_review_expired_or_not_effective': 1}

    # Matching may still know the overtime scope without the exact wording.
    # The new settlement qualification needs the selected market's wording.
    meta['scoring_scope']['evidence'] = [{'overtime': 'included'}]
    counts = census(projected(), [])['total']
    assert counts['covered'] == counts['exact_pinnacle_reference'] == 1
    assert counts['any_after_fee_ev'] == 0


@pytest.mark.parametrize(('price', 'covered'), [('0.0075', False), ('0.01', True),
                                                ('0.99', True), ('0.9925', False)])
def test_in_game_fee_keeps_documented_price_limits_in_current_denominator(price, covered):
    row = native('live', 'Long')
    row['original']['value'] = price
    retail = row['original_record']['comparison_source_metadata']['public_retail_observation']
    retail['values']['orderPriceMinTickSize'] = '0.0025'
    inputs = inputs_for(row)
    counts = census(project(live.prices(inputs, SETTINGS), inputs), [])
    assert counts['total']['current'] == 1 and counts['total']['covered'] == int(covered)
    assert counts['missing_reasons'] == ({} if covered else {'PMUS documented price range .01 through .99': 1})
