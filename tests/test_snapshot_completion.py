"""Independent arithmetic and identity regressions for the ordinary product."""
from copy import deepcopy
from fractions import Fraction as F

import pytest

from app.comparison.conditional_benchmark import snapshot_metric, rounded_cents
from app.comparison.snapshot_identity import project, games
from app.comparison.snapshot_math import assumptions
from app.comparison.snapshot_named_benchmark import references, bind
from app.storage.comparison_snapshot import probability
from app.dashboard.snapshot_api import selected_references
from tests.test_snapshot_identity import quote
from tests import test_current_benchmark as benchmark_fixture

AT=benchmark_fixture.AT
from app.dashboard.comparison_board import price
from app.dashboard.current_contract import serialize


def test_ncaaf_missing_context_is_not_a_sport_specific_exclusion():
    qs=[quote(),quote('kalshi','peer')]
    for q in qs:
        q['league']='NCAAF';r=q['original_record'];r['event']['competition']='NCAAF'
        r['comparison_source_metadata']['source_predicate']['competition']='NCAAF'
        q['same_outcome']['reason']='comparison_context_missing'
    original=deepcopy(qs)
    result=project(qs,{},leagues=('NCAAF',),preserve_known=True)
    assert all(q['snapshot_supported'] for q in result)
    assert result[0]['same_outcome']['key']==result[1]['same_outcome']['key']
    assert qs==original
    qs[1]['original_record']['event']['scheduled_start']='2026-11-04T00:00:00Z'
    result=project(qs,{},leagues=('NCAAF',),preserve_known=True)
    assert result[0]['game_key']!=result[1]['game_key']
    # NCAAB's declared overtime assumption must never spill into football.
    qs[0]['original_record']['comparison_source_metadata']['scoring_scope']['evidence']=[]
    assert not project(qs,{'scoring':'ncaab_full_game_overtime'},leagues=('NCAAF',),preserve_known=True)[0]['snapshot_supported']


def test_catalog_merge_keeps_names_and_split_destinations():
    inputs=dict(games=[dict(game_key='a',title='A',participants=[dict(id='BAL',name='Baltimore Ravens',role='home')]),
                       dict(game_key='b',title='B',participants=[dict(id='JAX',name='Jacksonville Jaguars',role='away')])],
                quotes=[dict(game_key='a'),dict(game_key='b'),dict(game_key='a')])
    result=games(inputs,[dict(game_key='merged'),dict(game_key='merged'),dict(game_key='separate')])
    assert set(result)=={'merged','separate'}
    assert result['merged']['title']=='Jacksonville Jaguars at Baltimore Ravens'
    assert len(result['merged']['participants'])==2


def fee_row(venue='novig',cost='2'):
    return dict(id='fixture',venue=venue,probability='3/5',gross_return_percent='20',
        start_at='2026-11-05T00:00:00Z',market=dict(period='full_game',market='winner'),
        source=dict(provider='the_odds_api' if venue=='novig' else venue,
                    native_side='bookmaker_outcome' if venue=='novig' else 'Long'),
        original=dict(value=cost,units='decimal_odds' if venue=='novig' else 'usd_per_contract',
                      quantity_units='contracts',payout_units='USD',payout='1'),times={},reference={})


def test_reviewed_fee_scenario_has_its_own_denominator_and_interval():
    at='2026-11-04T02:00:00Z'
    row=fee_row();before=deepcopy(row);m=snapshot_metric(row,at=at)
    assert m['available'] and F(m['return_percent'])==20
    assert F(m['trade_fee_usd'])==0 and row==before
    row=fee_row('polymarket_us','0.50');m=snapshot_metric(row,at=at)
    # 0.0695 × .5 × .5 = .017375, rounded to .02. Risk is .52,
    # expected receipt .60; .08/.52 = 2/13, before rebates/buffer.
    assert F(m['trade_fee_usd'])==F(2,100)
    assert F(m['normalization_risk_usd'])==F(52,100)
    assert F(m['return_percent'])==F(200,13)
    assert rounded_cents('0.025')==F(2,100)
    assert rounded_cents('0.035')==F(4,100)
    for stamp in ('2026-11-02T02:00:00Z','2026-11-07T02:00:00Z'):
        assert not snapshot_metric(row,at=stamp)['available']
    row['probability']=None;row['gross_return_percent']=None
    assert not snapshot_metric(row,at=at)['available']
    assert not snapshot_metric(fee_row('kalshi','.5'),at=at)['available']


@pytest.mark.parametrize('venue',['novig','prophetx'])
def test_named_benchmark_uses_selected_book_and_exact_originals(venue):
    from app.collection.current_aggregate_admission import admit
    from tests.test_current_aggregate import body
    from app.dashboard.current_contract import identity
    from app.storage.store import hashed
    state=serialize(benchmark_fixture.BenchmarkTests().raw(),allow_synthetic=True)
    q=benchmark_fixture.BenchmarkTests().quote(state)
    row=price(q);row.update(id='execution',league='MLB',game_key='game',binding=q['binding'])
    witnesses=[r for r in admit(body(books=(venue,)),'MLB',AT,venue=venue) if r['market_identity']['family']=='moneyline']
    record=next(r for r in witnesses if r['selection']['participant']==row['selection']['participant'])
    row.update(original_record=record,source=record['quote']['source'])
    # Author 2 and 3 as an independently checked 3/5 and 2/5 pair.
    for r in witnesses:r['quote']['original']['value']='2' if r is record else '3'
    rows=[dict(row,venue=venue,id=str(i),original_record=r,source=r['quote']['source']) for i,r in enumerate(witnesses)]
    settings=assumptions({'benchmark_venue':venue})[0]
    refs=references(rows,[],settings);before=deepcopy(rows)
    selected=bind([dict(row,original_record=record)],refs,settings)[0]
    p,reason=probability(selected,settings,AT)
    assert reason is None and F(p)==F(3,5)
    assert selected['reference']['bookmaker']==venue
    assert selected['reference']['selection_digest']==identity('binding',row['binding']['selection'])
    assert {r['id'] for r in selected_references(selected,row,refs)}=={hashed(r['quote']['source']) for r in witnesses}
    assert rows==before
    assert bind([row],refs[:1],settings)[0]['reference'] is None


def test_failed_equality_projection_preserves_verified_source_local_price():
    q=quote();q['league']='NCAAF';r=q['original_record'];r['event']['competition']='NCAAF'
    r['comparison_source_metadata']['source_predicate']['competition']='NCAAF'
    r['comparison_source_metadata']['scoring_scope']['evidence']=[]
    q['same_outcome']['reason']='comparison_equality_missing';q['binding']={'verified':True}
    before=deepcopy(q)
    out=project([q],{'scenario':'decisive_only'},leagues=('NCAAF',),preserve_known=True)
    assert out==[before]
