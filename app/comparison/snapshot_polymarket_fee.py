"""Standard Polymarket US retail taker estimate for one modeled order."""
from fractions import Fraction
from functools import lru_cache

from app.collection.public_contracts import load
from app.fees.engine import Registry, calculate

from .cashflows import exact_wire as wire
from .snapshot_fee_scope import RANKING_BASIS
from .snapshot_identity import DECISIVE_EQUALITY_BASIS

CUTOVER = '2026-11-06T18:00:00Z'
STANDARD_TIERS = ('0.095', '0.085', '0.075', '0.0695')
PROFILE = 'standard_retail_taker_high_tier'
URL = 'https://docs.polymarket.us/fees'


@lru_cache(maxsize=len(STANDARD_TIERS))
def _registry(tier):
    if tier not in STANDARD_TIERS:
        raise ValueError('Unrecognized standard Polymarket US taker tier')
    standard = dict(venue='polymarket_us', product='standard_contract',
                    maker_coefficient='0', sources=[URL])
    return Registry(dict(schema=1, schedules=[
        dict(standard, version='pmus-standard-2026-10-28', coefficient='0.0695',
             effective_from='2026-10-29T02:00:00Z', effective_to=CUTOVER),
        dict(standard, version='pmus-standard-tiers-2026-11-06', coefficient=tier,
             effective_from=CUTOVER, effective_to=None),
    ]))


def order_fee(market_id, *, inserted_at, evaluated_at, fills, tier=STANDARD_TIERS[0]):
    """Price chronological taker fills of a single standard order, with zero rebates."""
    return calculate(dict(
        venue='polymarket_us', environment='production', market_id=market_id,
        product='standard_contract', order_inserted_at=inserted_at,
        trade_time=evaluated_at, calculation_time=evaluated_at,
        applicability_evidence={'profile': PROFILE}, complete_order_history=True,
        fills=[dict(fill, fill_id=str(i), order_id='modeled-order', role='taker', unit='contracts')
               for i, fill in enumerate(fills)],
    ), _registry(tier))


def public_fee(row, *, at, phase, review, quantity='1'):
    try:
        if review.get('profile') != PROFILE or review['fee_rate'] != STANDARD_TIERS[0]:
            raise ValueError('polymarket_standard_retail_review_unavailable')
        source = row['source']
        original = row['original']
        scope = row['fee_applicability'] or {}
        market = row['market']
        retail = scope.get('retail') or {}
        side = source.get('native_side')
        event_id, market_id, outcome_id = (source.get(k) for k in (
            'native_event_id', 'native_market_id', 'native_outcome_id'))
        native_type = scope.get('native_market_type')
        try:
            native = load('us_types', native_type)
        except KeyError:
            native = {}
        if (source.get('provider') != 'polymarket_us' or source.get('quote_side') != 'buy'
                or side not in ('Long', 'Short') or not all((event_id, market_id, outcome_id))
                or scope.get('native_key') != ['polymarket_us', event_id, market_id, outcome_id, side]
                or native.get('period') != market['period']
                or native.get('family') != market['market'].replace('winner', 'moneyline')
                or row['league'] not in native.get('competitions', [])
                or retail.get('market_id') != market_id or retail.get('instrument_id') != outcome_id
                or retail.get('long') is not (side == 'Long') or retail.get('is_combo') is True):
            raise ValueError('polymarket_fee_product_scope_unbound')
        if (original['units'] != 'usd_per_contract' or original.get('quantity_units') != 'contracts'
                or original.get('payout_units') != 'USD' or Fraction(original.get('payout', '0')) != 1):
            raise ValueError('conditional_standard_contract_mapping_unsupported')
        price = Fraction(original['value'])
        if side == 'Short' and (original.get('transformation') != 'one_minus_native_bid'
                or original.get('native_units') != 'usd_per_contract'
                or price != 1 - Fraction(original['native_value'])):
            raise ValueError('polymarket_short_acquisition_price_unbound')
        # Listing metadata establishes the order grid. The public schedule,
        # rather than a listing coefficient, supplies the insertion-time tier.
        values = retail.get('values') or {}
        if not all(k in values for k in ('minimumTradeQty', 'orderPriceMinTickSize')):
            raise ValueError('polymarket_selected_order_grid_unbound')
        minimum, tick = Fraction(values['minimumTradeQty']), Fraction(values['orderPriceMinTickSize'])
        size = Fraction(quantity)
        if minimum <= 0 or size < minimum or size % minimum:
            raise ValueError('polymarket_one_claim_quantity_unsupported' if size == 1 else 'pair_size_unsupported')
        if tick <= 0 or price % tick:
            raise ValueError('polymarket_selected_price_grid_conflict')

        when = at.isoformat()
        audit = order_fee(market_id, inserted_at=when, evaluated_at=when,
                          fills=[dict(price=original['value'], quantity=wire(size))])
        if audit['entry_fees'] is None:
            raise ValueError('; '.join(audit['unsupported']))
        schedule = audit['schedule']
        evidence = dict(review, coefficient=schedule['coefficient'], effective_from=schedule['effective_from'],
                        order_inserted_at=when, phase=phase, market_id=market_id, instrument_id=outcome_id,
                        native_side=side, acquired_price_usd=original['value'])
        return dict(available=True, reason=None, evidence=evidence, trade_fee_usd=audit['entry_fees'],
                    quantity=wire(size), quantity_unit='USD payout contracts', fill_count=1,
                    liquidity_role='taker', fee_payment='at_fill', assumptions=[
                        f"Standard taker coefficient {schedule['coefficient']} at modeled order insertion.",
                        'One immediate fill at the displayed acquisition price. Assumed rebates are $0.',
                        'Personal tiers and overrides require separate account evidence.',
                    ])
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError) as exc:
        return dict(available=False, reason=str(exc))


def nba_completed_game_rule(row, identity, predicate, source_scope):
    """Qualify decisive NBA winner math using the selected market's overtime terms."""
    if (row['league'] != 'NBA' or row['market']['market'] != 'winner'
            or row['market']['period'] != 'full_game'
            or (row.get('fee_applicability') or {}).get('native_market_type') != 'basketball_team_full_game_winner'
            or identity.get('equality_basis') != DECISIVE_EQUALITY_BASIS
            or predicate.get('domain') != 'home_margin' or predicate.get('threshold') != '0'
            or predicate.get('operator') not in ('gt', 'ge', 'lt', 'le')
            or identity.get('scoring', {}).get('overtime') != 'included'):
        return None
    overtime = next((fact for fact in source_scope.get('evidence', [])
                     if fact.get('basis') == 'selected_source_description' and fact.get('overtime') == 'included'
                     and fact.get('text')), None)
    if overtime:
        return dict(url='https://official.nba.com/rule-no-5-scoring-and-timing/', section='IV',
                    selected_market_overtime=overtime['text'])
    return None


def conservative_metric(row, fee, witnesses, phase, *, source_scope=None):
    """Decisive-only after-fee EV on an exact and phase-aligned Pinnacle frame."""
    if not fee.get('available'):
        return dict(available=False, reason=fee.get('reason'))
    ref = row.get('reference_calculation') or {}
    benchmark = row.get('snapshot_benchmark') or {}
    identity = benchmark.get('selected_identity') or {}
    predicate = benchmark.get('selected_predicate')
    missing = dict(available=False, reason='polymarket_exact_reference_or_settlement_missing')
    if (not ref.get('available') or ref.get('venue') != 'pinnacle'
            or len(witnesses) != 2 or len({w.get('dependency') for w in witnesses}) != 2
            or not all(w.get('expected') is not None and not w['reasons']
                       and w['lifecycle']['state'] == phase for w in witnesses)
            or identity.get('scoring_basis') != 'retained source scoring evidence'
            or not predicate or row.get('gross_return_percent') is None):
        return missing
    evidence = fee['evidence']
    if identity.get('equality_basis') != 'retained predicate/equality':
        completed_game_rule = nba_completed_game_rule(row, identity, predicate, source_scope or {})
        if not completed_game_rule:
            return missing
        evidence = dict(evidence, completed_game_rule=completed_game_rule)
    try:
        probability = Fraction(row['probability'])
        cost = Fraction(fee['evidence']['acquired_price_usd'])
        charge = Fraction(fee['trade_fee_usd'])
        if not 0 < probability < 1 or cost != Fraction(row['cost_per_normal_claim']):
            return missing
    except (KeyError, ValueError, TypeError, ArithmeticError):
        return missing
    risk = cost + charge
    return dict(available=True, reason=None, classification='conservative_trade_fee_estimate',
                account_verified=False, execution_qualified=False, full_state_net_ev=False,
                ranking_basis=RANKING_BASIS, percentage_denominator='acquisition_plus_modeled_trade_fee',
                normalization_risk_usd=wire(risk), normal_win_receipt_usd='1',
                win_profit_usd=wire(1-risk), loss_profit_usd=wire(-risk),
                scenario_net_usd=wire(probability-risk), return_percent=wire(100*(probability-risk)/risk),
                selected_decisive_probability=wire(probability), expected_trade_fee_usd=wire(charge),
                condition='Conditional on decisive settlement with the exact Pinnacle reference.',
                exclusions=['ties', 'pushes', 'voids', 'cancellations', 'multi-price fills'],
                evidence=evidence, **{key: fee[key] for key in ('trade_fee_usd', 'quantity', 'quantity_unit',
                                           'fill_count', 'liquidity_role', 'fee_payment', 'assumptions')})
