"""Owner-requested conservative fee estimates, separate from verified-fee ranking."""
from fractions import Fraction as F
import json
from .conditional_benchmark import basis
from .current_dependencies import instant
from .cashflows import exact_wire as wire
from .snapshot_fee_scope import ROOT, RANKING_BASIS

POLICY=ROOT/'app/fixtures/conservative-conditional-fees-policy-20261104.json'


def prophetx_nhl_taker_order(fills, *, coefficient):
    """Price ordered (contracts, price) fills of one new NHL taker order."""
    quantity = cost = fee = carry = F(0)
    trace = []
    rate = F(coefficient)
    if not 0 <= rate <= 1:
        raise ValueError('prophetx_invalid_nhl_taker_coefficient')
    for contracts, price in fills:
        contracts, price = F(contracts), F(price)
        if contracts <= 0 or not 0 < price < 1:
            raise ValueError('prophetx_invalid_nhl_fill')
        notional = contracts * price
        raw = rate * notional * (1 - price)
        adjusted = raw + carry
        # The prior remainder can be negative, but is never below -$0.005.
        charge = F((100 * adjusted + F(1, 2)) // 1, 100)
        remainder = adjusted - charge
        trace.append(dict(quantity=wire(contracts), price_usd=wire(price),
            raw_fill_fee_usd=wire(raw), carry_in_usd=wire(carry),
            fee_usd=wire(charge), carry_out_usd=wire(remainder)))
        quantity += contracts
        cost += notional
        fee += charge
        carry = remainder
    if not trace:
        raise ValueError('prophetx_nhl_fills_required')
    return quantity, cost, fee, trace


def prophetx_market_commission(*, rate, cost_basis, gross_payout):
    """Price settlement from the combined cashflows of a single market."""
    raw = F(rate) * max(F(0), F(gross_payout) - F(cost_basis))
    cents = raw * 100
    # Keep the retail estimate's conservative ceiling. Venue rounding is unverified.
    return raw, F(-(-cents.numerator // cents.denominator), 100)


def prophetx_public_fee(row, *, at, review=None, quantity=None, fills=None):
    """Resolve the retail estimate at modeled order placement.

    Pass order placement as a UTC timestamp string. ProphetX defaults to one
    claim at the offered price. For a sized NHL order,
    supply a quantity at that price or its ordered (quantity, price) taker fills.
    """
    result = dict(available=False, reason='conservative_trade_fee_estimate_not_applicable')
    if row['venue'] != 'prophetx':
        return result
    try:
        at = instant(at)
        policy = json.loads(POLICY.read_bytes())
        if at < instant(policy['enabled_at']):
            raise ValueError('conservative_fee_policy_not_effective')
        if at >= instant(row['start_at']):
            raise ValueError('conditional_pregame_ended')
        if row['market']['period'] != 'full_game' or row['market']['market'] not in ('winner', 'spread', 'total'):
            raise ValueError('conditional_pregame_straight_mapping_unsupported')
        evidence = review if review is not None else basis('prophetx', at=at)
        result['evidence'] = evidence
        if evidence.get('unavailable_reason'):
            raise ValueError(evidence['unavailable_reason'])
        if not instant(evidence['reviewed_at']) <= at < instant(evidence['review_before']):
            raise ValueError('conditional_fee_review_expired_or_not_effective')
        if 'nhl_taker_coefficient' in evidence:
            policy = dict(policy, version='public-straight-trades-20261105',
                prophetx=evidence['applicability'], public_schedule=evidence['version'])
        source, original = row['source'], row['original']
        if (source['provider'] != 'the_odds_api' or source['native_side'] != 'bookmaker_outcome'
                or original['units'] != 'decimal_odds'):
            raise ValueError('prophetx_public_site_straight_mapping_unsupported')
        captured_cost = row.get('cost_per_normal_claim')
        price = 1 / F(original['value']) if captured_cost is None else F(captured_cost)
        if not 0 < price < 1:
            raise ValueError('conditional_invalid_odds')
        size = F(1) if quantity is None else F(quantity)
        if size <= 0:
            raise ValueError('prophetx_positive_quantity_required')

        fill_count = 1
        if row['league'] == 'NHL' and 'nhl_taker_coefficient' in evidence:
            order = ((size, price),) if fills is None else fills
            filled, cost, fee, trace = prophetx_nhl_taker_order(order, coefficient=evidence['nhl_taker_coefficient'])
            if quantity is not None and size != filled:
                raise ValueError('prophetx_nhl_fill_quantity_mismatch')
            size, fill_count = filled, len(trace)
            risk, receipt = cost + fee, size
            assumptions = ['Public retail NHL straight contract modeled as taker fills of one new order.',
                'Each fill rounds half up to cents and carries the remainder to the next fill of that order.',
                'A marketable limit order is modeled. The site deducts market-order fees from the entered amount.',
                'The aggregate price does not establish executable depth or actual fills.']
            treatment = 'upfront_public_site_nhl_taker_fee'
            details = dict(rounding='half_up_cent_with_order_carry', rounding_trace=trace)
        else:
            if fills is not None:
                raise ValueError('prophetx_nhl_taker_schedule_required')
            risk = size * price
            raw, fee = prophetx_market_commission(rate=evidence['fee_rate'], cost_basis=risk, gross_payout=size)
            receipt = size - fee
            assumptions = ['Aggregate price mapped to a public retail straight trade.',
                'Commission applies only to positive net gains in that market.',
                'Standalone position held to settlement with no other positions in this market.',
                'The estimate rounds commission up to cents. Venue settlement rounding is unverified.']
            treatment = 'commission_deducted_from_winning_market_gains'
            details = dict(raw_winning_fee_usd=wire(raw), rounding='assumed_ceiling_cent',
                netting_scope='one_position_per_market')
        result.update(available=True, reason=None, classification='conservative_trade_fee_estimate',
            fee_authority='reviewed_public_schedule_with_explicit_conservative_assumptions',
            account_verified=False, ranking_eligible=False, ranking_basis=RANKING_BASIS,
            trade_fee_usd=wire(fee), fee_payment=treatment, normalization_risk_usd=wire(risk),
            normal_win_receipt_usd=wire(receipt), win_profit_usd=wire(receipt - risk), loss_profit_usd=wire(-risk),
            percentage_denominator='maximum_modeled_loss_in_decisive_states',
            quantity=wire(size), quantity_unit='USD normal claim', fill_count=fill_count, liquidity_role='taker',
            assumptions=assumptions, evidence=evidence, policy=policy, details=details,
            source_times=row['times'], full_state_net_ev=False, execution_qualified=False)
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        result['reason'] = str(exc)
    return result


def fee_model(row, *, at, review=None):
    if row['venue'] == 'prophetx':
        return prophetx_public_fee(row, at=at, review=review)
    if row['venue'] == 'kalshi':
        try:
            selected = review if review is not None else basis('kalshi', at=instant(at))
            return kalshi_public_fee(row, at=at, review=selected)
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
            return dict(available=False, reason='kalshi_public_fee_evidence_unavailable')
    return dict(available=False, reason='conservative_trade_fee_estimate_not_applicable')


def metric(row, *, at, review=None):
    if row['venue'] in ('kalshi','prophetx') and row.get('gross_return_percent') is None:
        return dict(available=False,reason='supported_decisive_benchmark_required')
    result=fee_model(row,at=at,review=review)
    try:
        if result['available']:
            p=F(row['probability'])
            fee=F(result['trade_fee_usd'])
            if result['fee_payment']=='commission_deducted_from_winning_market_gains':
                fee*=p
            ev=p*F(result['win_profit_usd'])+(1-p)*F(result['loss_profit_usd'])
            result.update(expected_trade_fee_usd=wire(fee),scenario_net_usd=wire(ev),
                return_percent=wire(100*ev/F(result['normalization_risk_usd'])),selected_decisive_probability=wire(p))
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        return dict(available=False, reason=str(exc))
    if result['reason']=='conditional_fee_review_expired_or_not_effective':
        result.pop('evidence',None)
    return result


def kalshi_public_fee(row, *, at, review, quantity='1'):
    """Price one public exchange taker fill without personal membership facts.

    Exact market metadata and the reviewed time window are mandatory; unknown
    intermediary charges remain outside this exchange-only public estimate.
    """
    from .snapshot_fee_scope import kalshi_scenarios
    result=dict(available=False,reason='kalshi_public_fee_evidence_unavailable')
    try:
        when=instant(at)
        if review and review.get('unavailable_reason'):
            raise ValueError(review['unavailable_reason'])
        if not review or not instant(review['reviewed_at']) <= when < instant(review['review_before']):
            raise ValueError('conditional_fee_review_expired_or_not_effective')
        if row['market']['period'] != 'full_game' or row['market']['market'] not in ('winner','spread','total'):
            raise ValueError('kalshi_series_fee_scope_unbound')
        scenarios,evidence=kalshi_scenarios(row, review, when, quantity=quantity)
        selected=max(scenarios,key=lambda item:F(item['fee']))
        result.update(available=True,reason=None,classification='conservative_trade_fee_estimate',
            fee_authority='public_exchange_schedule',account_verified=False,ranking_eligible=False,
            ranking_basis=RANKING_BASIS,trade_fee_usd=wire(F(selected['fee'])),
            normalization_risk_usd=wire(F(selected['risk'])),
            normal_win_receipt_usd=wire(F(quantity)),win_profit_usd=wire(F(quantity)-F(selected['risk'])),
            loss_profit_usd=wire(-F(selected['risk'])),fee_payment='at_fill',liquidity_role='taker',
            quantity=str(quantity),quantity_unit='USD payout contracts',fill_count=1,evidence=evidence,
            assumptions=['One immediate taker fill at the displayed acquisition price.',
                'Higher exchange charge across the documented direct and non-direct rounding cases.',
                'Public exchange-only estimate; any intermediary charge is separate.'],
            details=dict(rounding_trace=selected['rounding_trace'],resolved_terms=selected['resolved_terms'],
                         membership='unverified',scenarios=scenarios))
    except (OSError,ValueError,KeyError,TypeError,ArithmeticError) as exc:
        result['reason']=str(exc)
    return result
