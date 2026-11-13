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


def test_november_7_fee_review_is_prospective_and_does_not_invent_us_account_tier():
    from tests.test_snapshot_completion import fee_row
    from app.comparison.conditional_benchmark import snapshot_metric
    from fractions import Fraction
    novig=basis('novig',at=instant('2026-11-08T00:00:00Z'))
    at=novig['reviewed_at']
    row=fee_row();row['start_at']='2026-11-09T00:00:00Z'
    checked=snapshot_metric(row,at=at)
    assert checked['available'] and Fraction(checked['trade_fee_usd'])==0
    assert Fraction(checked['return_percent'])==20
    assert basis('novig',at=instant(at)-timedelta(microseconds=1))['version']!=novig['version']
    row=fee_row('polymarket_us','.50');row['start_at']='2026-11-09T00:00:00Z'
    checked=snapshot_metric(row,at=at)
    assert not checked['available']
    assert checked['reason']=='polymarket_account_taker_fee_tier_unbound'
    assert checked['evidence']['fee_rate'] is None
    assert 'trade_fee_usd' not in checked


def test_november_9_novig_review_restores_only_current_pregame_terms():
    from app.comparison.conditional_benchmark import snapshot_metric
    from tests.test_snapshot_completion import fee_row

    review = basis('novig', at=instant('2026-11-10T00:00:00Z'))
    start = instant(review['reviewed_at'])
    end = instant(review['review_before'])
    row = fee_row()
    row['start_at'] = '2026-11-11T00:00:00Z'

    before = snapshot_metric(row, at=(start - timedelta(microseconds=1)).isoformat())
    assert before['reason'] == 'conditional_fee_review_expired_or_not_effective'
    current = snapshot_metric(row, at=start.isoformat())
    assert current['available'] and current['trade_fee_usd'] == '0'
    assert current['evidence']['version'] == 'novig-conditional-20261109-review'
    renewed = basis('novig', at=end)
    assert renewed['version'] == 'novig-conditional-20261110-review'
    assert instant(renewed['reviewed_at']) < end
    assert snapshot_metric(row, at=end.isoformat())['evidence']['version'] == renewed['version']

    row['start_at'] = '2026-11-09T00:00:00Z'
    assert not snapshot_metric(row, at=start.isoformat())['available']


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


def test_hockey_review_binds_official_score_without_overriding_exceptions():
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
    assert winner['overtime']=='included' and winner['evidence_available']
    assert winner['contract_terms_url'].endswith('/HOCKEYWINNINGINPERIOD.pdf')
    original=deepcopy(next(r for r in winners() if r['quote']['venue']=='kalshi'))
    original['event']['competition']='NHL';original['market_identity']['competition']='NHL'
    original['comparison_source_metadata']['series_id']='KXNHLGAME'
    original['comparison_scope']={'overtime':'unknown'}
    at=instant(winner['evidence']['reviewed_at'])
    assert scope.resolve(original,at=(at-timedelta(microseconds=1)).isoformat())['overtime']=='unknown'
    assert scope.resolve(original,at=at.isoformat())['scoring']['shootout']=='official_final_score'


def test_hockey_supporting_source_hash_failure_withdraws_new_default():
    original=Path.read_bytes
    def read(path):
        return b'changed league rule evidence' if path.name=='nhl-2026-27-rule84.txt' else original(path)
    with patch.object(Path,'read_bytes',read):
        rules=scope._build_source_rules()
    for r in rules:
        if r['native_type'] in ('KXNHLGAME','KXNHLSPREAD','KXNHLTOTAL'):
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


def test_november_7_kalshi_review_retains_exact_public_terms_without_account_claim():
    import json
    from app.comparison.snapshot_fee_scope import kalshi_scenarios,kalshi_account
    from app.comparison.conditional_benchmark import ROOT
    evidence=basis('kalshi',at=instant('2026-11-08T02:00:00Z'))
    assert evidence['version']=='kalshi-conditional-20261107-review'
    start=instant(evidence['reviewed_at'])
    assert basis('kalshi',at=start-timedelta(microseconds=1))['version']!=evidence['version']
    body=json.loads((ROOT/evidence['path']).read_bytes())
    assert len(body['series'])==18 and body['event_changes']['cursor']==''
    for ticker,row in body['series'].items():
        event=ticker+'-SYNTHETIC';market=event+'-A'
        q=dict(league=row['league'],market={'market':row['family'].replace('moneyline','winner')},
            source=dict(provider='kalshi',native_event_id=event,native_market_id=market,native_side='yes',native_outcome_id='yes'),
            fee_applicability=dict(series_id=ticker,native_key=['kalshi',event,market,'yes','yes']),
            original=dict(value='.5',units='usd_per_contract',quantity_units='contracts',payout_units='USD',payout='1'))
        scenarios,_=kalshi_scenarios(q,evidence,start)
        assert all(not x['account_verified'] and not x['ranking_eligible'] for x in scenarios)
        assert all(x['resolved_terms']['fee_multiplier']==str(row['response']['series']['fee_multiplier']) for x in scenarios)
    with patch('app.comparison.snapshot_fee_scope.ACCOUNT_PATH',ROOT/'.local/nonexistent-disposable-account-fact'):
        with pytest.raises(ValueError,match='kalshi_account_membership_unbound'):kalshi_account(start)
