"""Unrounded EV partitions, counterfactual selection and tenfold Kelly reduction."""
from fractions import Fraction as F
from unittest.mock import patch

import pytest

from app.research import paper, paper_campaigns as campaigns, workspace
from tests.test_paper_experiments import AT, linear, priced
from tests.test_ev_movement import checkpoint


def config():
    return dict(name='NCAAB week',start_date='2026-11-23',end_date='2026-11-29',
                minimum_ev='.04',kelly_multiplier='.025',reference_bankroll_usd='10000',
                bucket_edges=['.04','.08','.15','.25'])


def ticket(identity,ev,*,screen=None,bet=None,venue='kalshi',state='loss'):
    return dict(id=identity,game_id='g',ev=ev,screen_ev=screen or ev,
                equivalent_bet_id=bet or identity,venue=venue,stake_exact_usd='10',
                expected_profit_exact_usd=str(10*F(ev)),return_exact_usd='0',grade=dict(state=state))


def test_continuous_buckets_and_overlapping_thresholds_use_unrounded_ev():
    rows=[ticket(str(i),v) for i,v in enumerate(['.04','.079999999','.08','.14999999','.15','.25'])]
    value=campaigns.analysis(rows,['.04','.08','.15','.25'],'all_venues')
    assert [b['summary']['tickets'] for b in value['buckets']]==[2,2,1,1]
    assert [b['summary']['tickets'] for b in value['thresholds']]==[6,4,2,1]
    assert sum(F(b['summary']['stake_exact_usd']) for b in value['buckets'])==F(value['summary']['stake_exact_usd'])


def test_higher_threshold_reselects_best_venue_from_qualifying_pool():
    rows=[ticket('a','.09',screen='.079',bet='same'),ticket('b','.085',screen='.10',bet='same',venue='novig')]
    assert campaigns.select(rows,F('.04'),'best_venue')[0]['id']=='a'
    assert campaigns.select(rows,F('.08'),'best_venue')[0]['id']=='b'
    assert len(campaigns.select(rows,F('.04'),'all_venues'))==2


@pytest.mark.parametrize('odds,expected',[('-110','11.00'),('+300','3.33'),('+3000','.33')])
def test_one_tenth_of_previous_quarter_kelly_is_one_fortieth(odds,expected):
    policy=dict(paper.POLICY,kelly_multiplier='1/40',sizing_scale_usd='250')
    with patch.object(paper.math,'calculate',side_effect=linear):
        rows,gaps=paper.candidates(checkpoint(priced(odds)),game_id='g',checkpoint_id='late',at=AT,policy=policy)
    assert not gaps
    assert F(rows[0]['stake_usd'])==F(expected)


def test_schedule_configuration_is_versioned_and_rejects_missing_boundaries():
    value=campaigns.configuration(config())
    assert value['start_date']=='2026-11-23' and value['end_date']=='2026-11-29'
    assert F(value['kelly_multiplier'])==F(1,40)
    for edges in (['.05','.08'],['.04','.04'],['.08','.04'],[]):
        with pytest.raises(workspace.SelectionError):
            campaigns.configuration(dict(config(),bucket_edges=edges))
