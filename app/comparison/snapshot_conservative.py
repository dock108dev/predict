"""Owner-requested conservative fee estimates, separate from verified-fee ranking."""
from fractions import Fraction as F
import json
from .conditional_benchmark import basis
from .current_dependencies import instant
from .cashflows import exact_wire as wire
from .snapshot_fee_scope import ROOT, RANKING_BASIS

POLICY=ROOT/'app/fixtures/conservative-conditional-fees-policy-20261104.json'


def metric(row, *, at):
    result=dict(available=False,reason='conservative_trade_fee_estimate_not_applicable')
    if row['venue'] not in ('kalshi','prophetx'):return result
    try:
        policy=json.loads(POLICY.read_bytes())
        if instant(at)<instant(policy['enabled_at']):raise ValueError('conservative_fee_policy_not_effective')
        if row.get('gross_return_percent') is None:raise ValueError('supported_decisive_benchmark_required')
        p=F(row['probability']);cost=F(row['cost_per_normal_claim'])
        if instant(at)>=instant(row['start_at']):raise ValueError('conditional_pregame_ended')
        if row['market']['period']!='full_game' or row['market']['market'] not in ('winner','spread','total'):
            raise ValueError('conditional_pregame_straight_mapping_unsupported')
        if row['venue']=='kalshi':
            exact=row['conditional_trade_benchmark']
            scenarios=exact.get('fee_scenarios')
            if not scenarios:raise ValueError(exact.get('reason') or 'kalshi_scoped_fee_evidence_unavailable')
            evidence=exact['evidence']
            chosen=max(scenarios,key=lambda s:F(s['risk']))
            fee=F(chosen['fee']);risk=F(chosen['risk']);win=1-risk;loss=-risk
            expected_fee=fee
            assumptions=['One contract, one taker fill; higher charge across documented membership grids.',
                'Exchange trading fee only. Unknown intermediary/FCM charges are not bounded by this estimate.']
            treatment='upfront_exchange_fee_upper_envelope'
            details=dict(rounding_trace=chosen['rounding_trace'],resolved_terms=chosen['resolved_terms'],
                balance_precision=chosen['balance_precision'],account_membership='unverified')
        else:
            evidence=basis('prophetx',at=instant(at))
            if 'nhl_taker_coefficient' in evidence:
                policy=dict(policy,version='public-straight-trades-20261105',
                    prophetx=evidence['applicability'],public_schedule=evidence['version'])
            s=row['source'];o=row['original']
            if s['provider']!='the_odds_api' or s['native_side']!='bookmaker_outcome' or o['units']!='decimal_odds':
                raise ValueError('prophetx_public_site_straight_mapping_unsupported')
            if row['league']=='NHL' and 'nhl_taker_coefficient' in evidence:
                raw=F(evidence['nhl_taker_coefficient'])*cost*(1-cost)
                fee=F((raw*100+F(1,2))//1,100)
                risk=cost+fee;win=1-risk;loss=-risk;expected_fee=fee
                assumptions=['Public-site NHL straight contract, one USD claim acquired as taker in one fill on a new order.',
                    'Negotiated account terms, rebates and actual execution remain unverified.']
                treatment='upfront_public_site_nhl_taker_fee'
                details=dict(raw_fill_fee_usd=wire(raw),rounding='half_up_cent',prior_order_remainder='0')
            else:
                raw=F(evidence['fee_rate'])*(1-cost)
                cents=raw*100;fee=F(-(-cents.numerator//cents.denominator),100)
                risk=cost;win=1-cost-fee;loss=-cost;expected_fee=p*fee
                assumptions=['Aggregate offer mapped hypothetically to public-site straight trade, not negotiated API terms.',
                    'One USD normal claim and no other positions in the market; fractional stake is a normalization, not an executable size.',
                    'Commission rounded up to cents conservatively; actual site rounding is not verified.']
                treatment='commission_deducted_from_winning_market_gains'
                details=dict(raw_winning_fee_usd=wire(raw),rounding='assumed_ceiling_cent',netting_scope='one_position_per_market')
        if not instant(evidence['reviewed_at'])<=instant(at)<instant(evidence['review_before']):
            raise ValueError('conditional_fee_review_expired_or_not_effective')
        ev=p*win+(1-p)*loss
        result.update(available=True,reason=None,classification='conservative_trade_fee_estimate',
            fee_authority='reviewed_public_schedule_with_explicit_conservative_assumptions',
            account_verified=False,ranking_eligible=False,ranking_basis=RANKING_BASIS,
            return_percent=wire(100*ev/risk),scenario_net_usd=wire(ev),
            trade_fee_usd=wire(fee),expected_trade_fee_usd=wire(expected_fee),
            fee_payment=treatment,normalization_risk_usd=wire(risk),
            normal_win_receipt_usd=wire(1-fee if treatment=='commission_deducted_from_winning_market_gains' else F(1)),
            win_profit_usd=wire(win),loss_profit_usd=wire(loss),selected_decisive_probability=wire(p),
            percentage_denominator='maximum_modeled_loss_in_decisive_states',
            quantity='1',quantity_unit='USD normal claim',fill_count=1,liquidity_role='taker',
            assumptions=assumptions,evidence=evidence,policy=policy,details=details,
            source_times=row['times'],full_state_net_ev=False,execution_qualified=False)
    except (OSError,ValueError,KeyError,TypeError,ArithmeticError) as exc:result['reason']=str(exc)
    return result
