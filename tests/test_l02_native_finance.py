"""Retained native witnesses plus disposable authority/fee mutation fixtures."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction as F
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.storage.comparison_snapshot import calculate
from app.storage import ordinary_publication as live
from app.storage.store import stamp
from app.comparison.snapshot_conservative import metric as conservative
from app.comparison.conditional_benchmark import snapshot_metric, basis
from app.comparison.snapshot_fee_scope import RANKING_BASIS
from tests.test_snapshot_benchmark import execution, references, inputs

FIXTURE=Path(__file__).parent/'fixtures/l02-native-20261104.json'


def retained():
    return json.loads(FIXTURE.read_bytes())['inputs']


@pytest.mark.parametrize('league',['NFL','NCAAF','NBA','NCAAB','MLB','NHL'])
@pytest.mark.parametrize('family,line',[('moneyline','0'),('spread','-3.5'),('total','135.5')])
def test_general_classes_require_exact_source_scoring(league,family,line):
    q=execution(family=family,line=line);refs=references(family,line)
    for item in [q,*refs]:
        r=item['original_record'];r['event']['competition']=league;r['market_identity']['competition']=league
        item['league']=league
        if item in refs:item['market']['competition']=league
        meta=r['comparison_source_metadata']
        meta['scoring_scope']['scoring'].update(extra_innings='included' if league=='MLB' else 'not_applicable',
            shootout='official_final_score' if league=='NHL' else 'not_applicable')
        if meta.get('source_predicate'):
            meta['source_predicate'].update(competition=league,unit='runs' if league=='MLB' else 'goals' if league=='NHL' else 'points')
    row=calculate(inputs([q],refs))['rows'][0]
    assert F(row['probability'])==F(3,5)
    assert F(row['reference_calculation']['fair_decimal_odds'])==F(5,3)
    q['original_record']['comparison_source_metadata']['scoring_scope']['evidence']=[{'overtime':'excluded'}]
    assert calculate(inputs([q],refs))['rows'][0]['probability'] is None


def test_retained_native_prices_probability_and_ev_independent_oracle():
    for inp in retained():
        before=deepcopy(inp);out=calculate(inp)
        for row in out['rows']:
            if row['probability'] is None:continue
            ref=row['reference_calculation'];pair=ref['pair'];i=ref['selected']
            assert len(pair)==2
            weights=[1/F(w['original']['value']) for w in pair]
            p=weights[i]/sum(weights)
            assert F(row['probability'])==p
            assert F(ref['fair_decimal_odds'])==1/p
            o=row['original'];cost=F(o['value']) if o['units']=='usd_per_contract' else 1/F(o['value'])
            if o.get('transformation')=='one_minus_native_bid':assert cost+F(o['native_value'])==1
            assert F(row['gross_return_percent'])==100*(p-cost)/cost
            fee=row['conditional_trade_benchmark']
            if fee.get('available'):
                risk=F(fee['normalization_risk_usd']);charge=F(fee['trade_fee_usd'])
                assert risk==cost+charge
                assert F(fee['return_percent'])==100*(p-risk)/risk
                assert fee['ranking_basis']==RANKING_BASIS
            if row['venue'] in ('kalshi','polymarket_us'):
                assert row['snapshot_benchmark']['selected_predicate']
                assert row['reference_calculation']['selected_id']==pair[i]['id']
        assert inp==before
        for venue in ('kalshi','polymarket_us'):
            assert {r['market']['market'] for r in out['rows'] if r['venue']==venue and r['probability'] is not None}=={'winner','spread','total'}
        nos=[r for r in out['rows'] if r['venue']=='kalshi' and r['source']['native_side']=='no' and r['market']['market']=='winner']
        assert nos and all(r['selection']['predicate']=='not_win' for r in nos)


def test_wrong_occurrence_line_or_missing_scoring_cannot_borrow_probability():
    inp=next(x for x in retained() if x['quotes'][0]['league']=='NBA')
    q=next(q for q in inp['quotes'] if q['venue']=='kalshi' and q['market']['market']=='spread')
    for change in ('occurrence','line','scoring'):
        x=deepcopy(inp);r=next(r for r in x['quotes'] if r['id']==q['id'])['original_record']
        if change=='occurrence':
            r['event']['scheduled_start']='2026-11-07T00:30:00Z'
            r['market_identity']['scheduled_start']=r['event']['scheduled_start']
        elif change=='line':r['market_identity']['line']='-99.5'
        else:r['comparison_source_metadata']['scoring_scope']['conflicts']=['conflicting_source_overtime']
        result=next(r for r in calculate(x)['rows'] if r['id']==q['id'])
        assert result['probability'] is None


def test_public_estimates_are_not_account_facts_and_use_total_risk():
    out=calculate(next(x for x in retained() if x['quotes'][0]['league']=='NFL'))
    at='2026-11-04T23:30:00Z'
    for venue in ('kalshi','prophetx'):
        row=next(r for r in out['rows'] if r['venue']==venue and r['gross_return_percent'] is not None)
        row['conditional_trade_benchmark']=snapshot_metric(row,at=at)
        estimate=conservative(row,at=at)
        assert estimate['available'],estimate
        assert not estimate['account_verified'] and not estimate['ranking_eligible']
        p=F(row['probability']);cost=F(row['cost_per_normal_claim'])
        if venue=='kalshi':
            raw=F('0.07')*cost*(1-cost);cents=(cost+raw)*100
            risk=F(-(-cents.numerator//cents.denominator),100)
            assert F(estimate['normalization_risk_usd'])==risk
            assert F(estimate['return_percent'])==100*(p-risk)/risk
            assert row['conditional_trade_benchmark']['reason']=='kalshi_account_membership_unbound'
        else:
            cents=F('.02')*(1-cost)*100;fee=F(-(-cents.numerator//cents.denominator),100)
            assert F(estimate['return_percent'])==100*(p*(1-fee)-cost)/cost
            assert F(estimate['normalization_risk_usd'])==cost
            assert row['conditional_trade_benchmark']['reason']=='prophetx_account_fee_model_and_rate_unbound'
        assert conservative(row,at=estimate['evidence']['review_before'])['available'] is False


def test_kalshi_account_authority_can_enable_exact_engine_without_promoting_assumption():
    row=next(r for r in calculate(retained()[1])['rows'] if r['venue']=='kalshi' and r['gross_return_percent'] is not None)
    with patch('app.comparison.snapshot_fee_scope.kalshi_account',return_value=dict(
            membership='direct',review_before='2026-11-05T00:00:00Z',evidence={'fixture':'disposable authored account fact'})):
        fee=snapshot_metric(row,at='2026-11-04T23:30:00Z')
    assert fee['available'],fee
    p=F(row['probability']);cost=F(row['original']['value'])
    raw=F('.07')*cost*(1-cost);six=raw*10**6;trade=F(-(-six.numerator//six.denominator),10**6)
    units=(cost+trade)*10000;risk=F(-(-units.numerator//units.denominator),10000)
    assert F(fee['normalization_risk_usd'])==risk
    assert F(fee['return_percent'])==100*(p-risk)/risk
    assert fee['evidence']['review_before']=='2026-11-05T00:00:00Z'


def test_selected_coefficient_quantity_and_native_series_conflicts_fail_closed():
    out=calculate(retained()[1])
    for venue in ('kalshi','polymarket_us'):
        row=next(r for r in out['rows'] if r['venue']==venue and r['gross_return_percent'] is not None)
        row=deepcopy(row)
        if venue=='kalshi':row['fee_applicability']['series_id']='KXFAKE'
        else:row['fee_applicability']['retail']['values']['feeCoefficient']='0.001'
        result=snapshot_metric(row,at='2026-11-04T23:30:00Z')
        assert not result['available']
        assert row['gross_return_percent'] is not None


def test_native_current_reference_replacement_fee_expiry_and_retained_identity():
    inp=retained()[1];at=stamp('2026-11-04T23:30:00Z')
    result=calculate(inp)
    for row in result['rows']:
        row['conditional_trade_benchmark']=snapshot_metric(row,at=at.isoformat())
        row['conditional_return_percent']=row['conditional_trade_benchmark'].get('return_percent')
    out=live.bind(result,inp,'ready');current=deepcopy(inp['dependencies'])
    # Authored clocks isolate withdrawal behavior from the capture's real latency.
    for row in out['rows']:
        auth=row['current_authority']
        for w in [auth['price'],*auth['references']]:w.update(reasons=[],current_until=(at+timedelta(hours=1)).isoformat())
    owner=dict(healthy=True,active=True);states={v:{'state':'available'} for v in ('kalshi','polymarket_us','novig','prophetx','pinnacle')}
    def read():return live.project(out,current,owner,states,at=at,policy=inp['policy_identity'],epoch=inp['epoch'])
    selected=next(r for r in out['rows'] if r['venue']=='polymarket_us' and r['gross_return_percent'] is not None)
    identity=selected['economic_revision'];original=deepcopy(selected)
    first=next(r for r in read()['rows'] if r['id']==selected['id']);assert first['price_current']
    witnesses = selected['current_authority']['references']
    for incomplete in (witnesses[:1], [witnesses[0], witnesses[0]]):
        selected['current_authority']['references'] = incomplete
        partial = next(r for r in read()['rows'] if r['id'] == selected['id'])
        assert partial['price_current'] and partial['gross_return_percent'] is None
        assert 'reference_evidence_missing' in partial['current_reasons']
    selected['current_authority']['references'] = witnesses
    selected['current_authority']['fee_until']=at.isoformat()
    fee_expired=next(r for r in read()['rows'] if r['id']==selected['id'])
    assert fee_expired['gross_return_percent']==original['gross_return_percent']
    assert fee_expired['conditional_return_percent'] is None
    assert fee_expired['metric_status']['after_trade_fee_ev']['reasons']==['conditional_fee_review_expired_or_not_effective']
    ref=selected['current_authority']['references'][0]['dependency'];current[ref][0]='new_reference_price'
    replaced=next(r for r in read()['rows'] if r['id']==selected['id'])
    assert replaced['price_current'] and replaced['probability'] is None
    assert replaced['metric_status']['before_fee_ev']['state']=='withdrawn'
    assert replaced['price_revision']==original['price_revision'] and replaced['economic_revision']==identity
    assert selected['probability']==original['probability']  # selected immutable evidence unaffected


def test_ordinary_chunk_encoding_preserves_exact_unicode_and_fraction_strings():
    from app.storage.comparison_snapshot import pack,unpack
    from app.storage.store import encoded
    import gzip
    value=dict(rows=[dict(name='NO — équipe',price='129/400',nested={'z':1,'a':None})]*10000)
    data=pack(value,fast=True)
    assert unpack(data)==value
    assert gzip.decompress(data)==encoded(value)


def test_read_codec_preserves_large_integers_and_rejects_nonfinite_numbers():
    from app.storage.comparison_snapshot import pack_read,unpack
    value=dict(rows=[dict(price='129/400',name='NO — équipe',integer=2**90)])
    packed=pack_read(value)
    assert not packed.startswith(b'PJ1')
    assert unpack(packed)==value
    value['rows'][0]['integer']=123
    packed=pack_read(value)
    assert packed.startswith(b'PJ1')
    assert unpack(packed)==value
    value['rows'][0]['integer']=float('nan')
    with pytest.raises(ValueError):pack_read(value)


def test_new_prophetx_schedule_scopes_nhl_taker_fee_to_one_new_order():
    row=next(r for r in calculate(retained()[1])['rows'] if r['venue']=='prophetx' and r['gross_return_percent'] is not None)
    row=dict(row,league='NHL',start_at='2026-11-08T12:00:00Z',cost_per_normal_claim='0.4',probability='0.45')
    at='2026-11-06T12:00:00Z'
    fee=conservative(row,at=at)
    assert fee['available'] and not fee['ranking_eligible']
    assert F(fee['trade_fee_usd'])==F('0.01')
    assert F(fee['normalization_risk_usd'])==F('0.41')
    assert F(fee['return_percent'])==100*F('0.04')/F('0.41')
    assert F(fee['normal_win_receipt_usd'])==1
    other=conservative(dict(row,league='NBA'),at=at)
    assert F(other['trade_fee_usd'])==F('0.02') and F(other['normalization_risk_usd'])==F('0.4')
