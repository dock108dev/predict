"""Prospective fee reviews and exact NHL scoring evidence boundaries."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import pytest
from app.comparison.conditional_benchmark import basis,attach
from app.comparison.current_dependencies import instant
from app.comparison import native_scoring_scope as scope
from tests.test_native_scoring_registry import winners,AT


@pytest.mark.parametrize('venue',['novig','polymarket_us'])
def test_new_fee_review_never_retroactively_covers_expired_interval(venue):
    old=basis(venue);end=instant(old['review_before'])
    assert basis(venue,at=end)['version']==old['version']
    new=basis(venue,at=instant('2026-10-29T01:00:00Z'))
    assert new['supersedes']==old['version'] and new['review_decision']
    start=instant(new['reviewed_at'])
    assert start>end
    assert basis(venue,at=start-timedelta(microseconds=1))==old
    assert basis(venue,at=start)==new
    assert basis(venue)['review_before']==old['review_before']
    q=dict(venue=venue,source=dict(provider='the_odds_api' if venue=='novig' else venue,
        native_side='bookmaker_outcome' if venue=='novig' else 'Long'),
        original=dict(value='2' if venue=='novig' else '.5',units='decimal_odds' if venue=='novig' else 'usd_per_contract',
            payout='1',payout_units='USD',quantity_units='contracts'),times={})
    raw=dict(revision='captured',gross_decisive_benchmark=dict(available=True,selected_decisive_probability='1/2',state='numeric_current',reference_revision='ref'))
    def metric(at):return attach(deepcopy(raw),q,at=at,event={'start_at':'2026-10-31T00:00:00Z'},group={'period':'full_game','market':'total'})['conditional_trade_benchmark']
    assert metric(end)['reason']=='conditional_fee_review_expired_or_not_effective'
    assert metric(start)['available'] and metric(start)['evidence']==new
    assert metric(instant(new['review_before']))['reason']=='conditional_fee_review_expired_or_not_effective'


def hockey_record():
    r=deepcopy(next(r for r in winners() if r['quote']['venue']=='kalshi'))
    r['event']['competition']='NHL';r['market_identity'].update(competition='NHL',family='total',line='6.5')
    r['selection'].update(participant=None,predicate='over',signed_line='6.5')
    r['comparison_source_metadata']['series_id']='KXNHLTOTAL'
    return r


def test_hockey_review_binds_official_score_but_not_winner_or_exceptions():
    r=hockey_record();before=deepcopy(r)
    result=scope.resolve(r,at=AT)
    assert result['status']=='supported' and result['scoring']['shootout']=='official_final_score'
    assert r==before
    meta=r['comparison_source_metadata']
    for container in (meta['original_wording'],meta['combined_native_binding']['original_terms']):
        container['description']='Including overtime but excluding shootout.'
    result=scope.resolve(r,at=AT)
    assert result['scoring']['shootout']=='excluded'
    winner=next(r for r in scope.source_rules() if r['native_type']=='KXNHLGAME')
    assert winner['overtime']=='unknown' and not winner['evidence_available']


def test_hockey_supporting_source_hash_failure_withdraws_new_default():
    original=Path.read_bytes
    def read(path):
        return b'changed league rule evidence' if path.name=='nhl-2026-27-rule84.txt' else original(path)
    with patch.object(Path,'read_bytes',read):
        rules=scope._build_source_rules()
    for r in rules:
        if r['native_type'] in ('KXNHLSPREAD','KXNHLTOTAL'):
            assert not r['evidence_available'] and r.get('shootout') is None


def test_unbound_fees_keep_gross_without_inventing_a_zero_charge():
    for venue in ('prophetx','kalshi'):
        raw=dict(revision='original',gross_decisive_benchmark=dict(available=True,return_percent='-2'))
        out=attach(deepcopy(raw),dict(venue=venue),at=None,event={},group={})
        assert out['gross_decisive_benchmark']==raw['gross_decisive_benchmark']
        assert out['conditional_trade_benchmark']['available'] is False
        assert 'trade_fee_usd' not in out['conditional_trade_benchmark']


def test_missing_aggregate_reference_does_not_report_a_native_identity_failure():
    from app.comparison.bound_finance import gross_quote
    from types import SimpleNamespace
    r=gross_quote(dict(revision='original'),dict(source={'provider':'the_odds_api'},times={}),{},
        at=None,event={},group={},policy=SimpleNamespace(benchmark_venue='pinnacle'))
    assert r['gross_decisive_benchmark']['reason']=='exact_pinnacle_opposition_unavailable'
