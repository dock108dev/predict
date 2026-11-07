"""Trade-fee scenario on an exact aggregate benchmark; never full-outcome EV."""
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from .current_dependencies import digest, instant
from .net_costs import wire

ROOT=Path(__file__).resolve().parents[2]


@lru_cache(maxsize=4)
def _verified(raw, body, venue):
    basis=json.loads(raw)
    if sha256(body).hexdigest()!=basis['sha256'] or basis['fee_rate']!={'novig':'0','polymarket_us':'0.0695','kalshi':'0.07','prophetx':'0.02'}[venue]:
        raise ValueError('conditional_fee_evidence_invalid')
    return basis


def basis(venue='novig', *, at=None):
    name={'novig':'novig','polymarket_us':'polymarket-us','kalshi':'kalshi','prophetx':'prophetx'}[venue]
    path=ROOT/f'app/fixtures/{name}-conditional-fees-20261028.json'
    if at is not None:
        # A substantive new review is prospective. Never fill the expired gap
        # or relabel an immutable result computed with the earlier evidence.
        for date in ('20261028','20261030','20261103','20261104','20261105'):
            reviewed=ROOT/f'app/fixtures/{name}-conditional-fees-review-{date}.json'
            if reviewed.exists() and at>=instant(json.loads(reviewed.read_bytes())['reviewed_at']):path=reviewed
    raw=path.read_bytes()
    item=json.loads(raw)
    path=Path(item['path'])
    if path.is_absolute() or '..' in path.parts:raise ValueError('conditional_fee_evidence_path')
    return deepcopy(_verified(raw,(ROOT/path).read_bytes(),venue))


def rounded_cents(value):
    cents=Fraction(value)*100
    whole,remainder=divmod(cents.numerator,cents.denominator)
    if 2*remainder>cents.denominator or (2*remainder==cents.denominator and whole%2):whole+=1
    return Fraction(whole,100)


def attach(result, q, *, at, event, group):
    gross=result.get('gross_decisive_benchmark') or {}
    venue=q['venue']
    if not gross.get('available'):
        return result
    if venue=='prophetx':
        result['conditional_trade_benchmark']=dict(available=False,reason=(
            'prophetx_account_fee_model_and_rate_unbound' if venue=='prophetx'
            else 'kalshi_instrument_fee_schedule_unbound'))
        result['revision']=digest(dict(financial_revision=result['revision'],conditional_trade_benchmark=result['conditional_trade_benchmark']))
        return result
    if venue not in ('novig','polymarket_us','kalshi'):return result
    metric=dict(available=False,reason=None)
    try:
        evidence=basis(venue,at=at)
        if not instant(evidence['reviewed_at'])<=at<instant(evidence['review_before']):
            raise ValueError('conditional_fee_review_expired_or_not_effective')
        metric['evidence']=evidence
        if at>=instant(event['start_at']):raise ValueError('conditional_pregame_ended')
        if (group['period']!='full_game' or group['market'] not in ('winner','spread','total')
                or q.get('comparison_input_refs',{}).get('phase')=='live'):
            raise ValueError('conditional_pregame_straight_mapping_unsupported')
        p=Fraction(gross['selected_decisive_probability']);original=q['original']
        exclusions=['ties','pushes','voids','cancellations','asymmetric exceptional settlement','account funding and withdrawal costs','taxes']
        if venue=='novig':
            if q['source']['provider']!='the_odds_api' or q['source']['native_side']!='bookmaker_outcome' or original['units']!='decimal_odds':
                raise ValueError('conditional_pregame_straight_mapping_unsupported')
            odds=Fraction(original['value'])
            if odds<=1:raise ValueError('conditional_invalid_odds')
            risk=1/odds;fee=Fraction(0);receipt=Fraction(1);value=p*odds-1
            condition='The aggregate Novig offer maps to a pregame straight trade under the reviewed fee schedule, with the same decisive outcome as the exact selected reference pair.'
            formula='Conditional net per USD 1 risk = decisive benchmark probability × decimal odds − 1 − trade fee.'
            label='one USD normal claim, one-fill scenario'
        elif venue=='polymarket_us':
            if (q['source']['provider']!='polymarket_us' or q['source']['native_side'] not in ('Long','Short')
                    or original['units']!='usd_per_contract' or original.get('quantity_units')!='contracts'
                    or original.get('payout_units')!='USD' or Fraction(original.get('payout','0'))!=1):
                raise ValueError('conditional_standard_contract_mapping_unsupported')
            scope=q.get('fee_applicability') or {}
            if scope:
                from app.collection.public_contracts import load
                native=load('us_types').get(scope.get('native_market_type'),{})
                retail=scope.get('retail') or {};values=retail.get('values') or {}
                if (native.get('period')!='full_game' or native.get('family')!=group['market'].replace('winner','moneyline')
                        or q['league'] not in native.get('competitions',[]) or retail.get('market_id')!=q['source']['native_market_id']
                        or retail.get('instrument_id')!=q['source']['native_outcome_id']):
                    raise ValueError('polymarket_fee_product_scope_unbound')
                if values.get('feeCoefficient')!='0.0695':raise ValueError('polymarket_selected_fee_coefficient_unbound')
                minimum=Fraction(values['minimumTradeQty'])
                if minimum<=0 or 1%minimum:raise ValueError('polymarket_one_claim_quantity_unsupported')
                tick=Fraction(values['orderPriceMinTickSize'])
                if tick<=0 or Fraction(original['value'])%tick:raise ValueError('polymarket_selected_price_grid_conflict')
            cost=Fraction(original['value'])
            if not Fraction(1,100)<=cost<=Fraction(99,100):raise ValueError('conditional_fee_price_range_unsupported')
            fee=rounded_cents(Fraction(evidence['fee_rate'])*cost*(1-cost))
            risk=cost+fee;receipt=Fraction(1);value=(p-cost-fee)/risk
            condition='Exactly one standard non-combo sports contract is acquired as taker in one fill at the captured Long or complemented Short acquisition cost, and settles to the decisive outcome represented by the exact reference pair. This is a hypothetical fill, not a depth or funding assertion.'
            formula='One-fill fee = round-half-even cents(0.0695 × cost × (1 − cost)); conditional net = decisive probability − cost − fee; return = 100 × net / (cost + fee).'
            label='one-contract, one-fill scenario'
            exclusions+=['account-specific rebates','split-fill fee adjustments']
        else:
            from .snapshot_fee_scope import kalshi_scenarios, kalshi_account
            scenarios,evidence=kalshi_scenarios(q,evidence,at)
            for scenario in scenarios:
                risk=Fraction(scenario['risk']);fee=Fraction(scenario['fee'])
                scenario.update(return_percent=wire(100*(p-risk)/risk),scenario_net_usd=wire(p-risk))
            metric.update(evidence=evidence,fee_scenarios=scenarios)
            account=kalshi_account(at)
            selected=next(s for s in scenarios if s['membership']==account['membership'])
            risk=Fraction(selected['risk']);fee=Fraction(selected['fee']);receipt=Fraction(1);value=(p-risk)/risk
            evidence=dict(evidence,account=account,review_before=min(evidence['review_before'],account['review_before'],key=instant))
            metric['rounding_trace']=selected['rounding_trace']
            metric['resolved_terms']=selected['resolved_terms']
            label='one-contract, one-fill scenario'
            condition='One binary USD 1 claim acquired as taker in one fill under exact series/event fee metadata and evidenced direct-account precision. No actual fill or executable depth claim.'
            formula='Shared fee engine: ceil six decimals(0.07 × series/event multiplier × cost × (1 − cost)); align cost plus fee to account precision; return = 100 × (decisive probability − total risk) / total risk.'
        from .snapshot_fee_scope import RANKING_BASIS
        metric.update(available=True,state=gross['state'],ranking_basis=RANKING_BASIS,
            quantity='1',quantity_unit='USD normal claim',liquidity_role='taker',fill_count=1,
            percentage_denominator='acquisition_plus_modeled_trade_fee',
            applicability=deepcopy(q.get('fee_applicability')),net_per_dollar_risk=wire(value),return_percent=wire(100*value),
            trade_fee_usd=wire(fee),normalization_risk_usd=wire(risk),normal_win_receipt_usd=wire(receipt),
            normalization_label=label,scenario_net_usd=wire(value*risk),
            selected_decisive_probability=wire(p),source_times=deepcopy(q['times']),
            reference_revision=gross['reference_revision'],evidence=evidence,
            classification='conditional_trade_fee_benchmark',calibrated=False,execution_qualified=False,
            condition=condition,exclusions=exclusions,
            missing=['full-outcome probabilities','instrument-level settlement mapping','native quantity and executable depth'],
            formula=formula,
            meaning='Conditional trade-fee benchmark; not calibrated full net EV, an executable fill or covered arbitrage.')
    except (OSError,ValueError,KeyError,TypeError,ArithmeticError) as exc:
        metric['reason']=str(exc)
    result['conditional_trade_benchmark']=metric
    result['revision']=digest(dict(financial_revision=result['revision'],conditional_trade_benchmark=metric))
    return result


def snapshot_metric(row, *, at):
    """Adapt a captured decisive benchmark to the same reviewed fee owner.

    A normalized one-fill scenario is separate from requested funding and from
    user-configured upfront fees. Historical captures keep their review interval.
    """
    if row.get('gross_return_percent') is None:
        return dict(available=False, reason='reference_probability_unavailable' if row.get('probability') is None else 'source_price_or_selection_unsupported', detail=row.get('probability_missing'))
    reference=row.get('snapshot_benchmark') or row.get('reference') or {}
    result=dict(revision=digest([row['id'],reference]),gross_decisive_benchmark=dict(
        available=True,state='captured',selected_decisive_probability=row['probability'],reference_revision=digest(reference)))
    result=attach(result,row,at=instant(at),event={'start_at':row['start_at']},group=row['market'])
    return result.get('conditional_trade_benchmark',dict(available=False,reason='reviewed_trade_fee_scenario_unavailable'))
