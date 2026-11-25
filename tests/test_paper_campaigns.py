"""Unrounded EV partitions, counterfactual selection and tenfold Kelly reduction."""
from fractions import Fraction as F
from unittest.mock import patch

import pytest

from app.research import paper, paper_campaigns as campaigns, paper_evidence, paper_results, workspace
from tests.test_paper_experiments import AT, linear, priced
from tests.test_ev_movement import checkpoint


def config():
    return dict(name='NCAAB week',start_date='2026-11-23',end_date='2026-11-29',
                minimum_ev='.04',kelly_multiplier='.025',reference_bankroll_usd='10000',
                bucket_edges=['.04','.08','.15','.25'])


def fixed_config(**overrides):
    return dict(dict(config(), scope='mens-d1', portfolios=['best_venue', 'all_venues'],
                     sizing_mode='fixed_profit', target_profit_usd='10', kelly_comparison=True), **overrides)


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


def test_freshness_uses_original_clocks_and_reselects_before_best_venue():
    receive = '2026-11-23T18:00:00Z'
    timestamps = ['2026-11-23T17:59:00Z', '2026-11-23T17:58:59.999999999Z',
                  '2026-11-23T17:55:00Z', '2026-11-23T17:54:59Z',
                  None, '2026-11-23T18:00:00.000000001Z']
    rows = [dict(ticket(str(i), ev, bet='same' if i in (0,1) else None),
                 times=dict(source_at=source, received_at=receive),
                 capture_origin='reconstructed' if i == 1 else 'frozen')
            for i, (source, ev) in enumerate(zip(timestamps, ('.085', '.25', '.04', '.04', '.04', '.04')))]
    references = [dict(source_at=timestamps[0], received_at=receive), dict(source_at=timestamps[2], received_at=receive)]
    document = dict(report=dict(portfolios=dict(all_venues=dict(tickets=rows))), witnesses={
        '0': dict(sized_calculation=dict(reference=dict(required_input_prices=references)))})
    tickets = campaigns.analysis_tickets(document, document['report'])
    edges = ['.04', '.08', '.15', '.25']
    value = campaigns.quality(tickets, edges, 'all_venues', inputs='result')
    assert [b['tickets'] for b in value['target_quote_age'].values()] == [1, 2, 1, 1, 1]
    assert value['reference_quote_age']['over_60_to_300']['tickets'] == 1
    best = campaigns.quality(tickets, edges, 'best_venue', inputs='result')
    assert best['target_quote_age']['up_to_60']['tickets'] == 0
    assert best['fresh_target_only']['summary']['expected_profit_exact_usd'] == '17/20'
    assert [b['summary']['tickets'] for b in best['fresh_target_only']['thresholds']] == [1, 1, 0, 0]
    assert value['version'] != best['version']
    assert paper_evidence.reference_age(dict(reference=dict(prices=references + [{}]))) is None


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


def test_other_targets_kelly_only_and_portfolios_normalize_saved_configuration():
    value = campaigns.configuration(fixed_config(target_profit_usd='12.50', portfolios=['all_venues']))
    assert value['target_profit_usd'] == '25/2'
    assert campaigns.modes(value) == ['fixed_profit', 'kelly']
    assert value['portfolios'] == ['all_venues']
    assert F(value['kelly_multiplier']) == F(1, 40)
    assert value['sizing_rule'] == paper.FIXED_PROFIT_RULE
    fixed_only = {key: val for key, val in fixed_config(kelly_comparison=False).items()
                  if key not in ('kelly_multiplier', 'reference_bankroll_usd')}
    assert campaigns.modes(campaigns.configuration(fixed_only)) == ['fixed_profit']
    kelly_only = dict(config(), sizing_mode='kelly', scope='mens-d1', portfolios=['best_venue'])
    assert campaigns.modes(campaigns.configuration(kelly_only)) == ['kelly']
    for invalid in (fixed_config(target_profit_usd='0'), fixed_config(kelly_comparison='true'),
                    fixed_config(scope='unsupported'), fixed_config(portfolios=[]), fixed_config(portfolios=[{}]),
                    fixed_config(kelly_comparison=False), dict(kelly_only, target_profit_usd='10')):
        with pytest.raises(workspace.SelectionError):
            campaigns.configuration(invalid)


def test_comparison_uses_frozen_quote_and_reselects_best_from_full_pool():
    def row(identity, quote, ev, *, bet='same', venue='kalshi'):
        return dict(ticket(identity, ev, bet=bet, venue=venue), frozen_quote_id=quote,
                    label='Home -3', family='spread', line='-3')

    def report(rows, exclusions=()):
        return dict(games=[dict(status='captured', sizing_exclusions=exclusions)],
                    portfolios=dict(all_venues=dict(tickets=rows)))

    kalshi, novig = row('k1', 'a', '.1'), row('k2', 'b', '.05', venue='novig')
    fixed_other = row('f2', 'b', '.05', venue='novig')
    fixed_extra = row('f3', 'c', '.06', bet='another')
    paired = dict(fixed_profit=report([fixed_other, fixed_extra],
                                    [dict(frozen_quote_id='a', reason='sized_ev_below_4pct')]),
                  kelly=report([kalshi, novig]))
    best = campaigns.sizing_comparison(paired, F('.04'), 'best_venue', details=True)
    assert best['counts'] == dict(jointly_qualifying_quotes=1, fixed_profit_only_qualifying_quotes=1,
        kelly_only_qualifying_quotes=1, jointly_selected_quotes=0, fixed_profit_only_selected_quotes=2,
        kelly_only_selected_quotes=1, venue_changes=1)
    assert best['changes'][0]['fixed_profit']['reason'] == 'sized_ev_below_4pct'
    assert best['changes'][1]['fixed_profit']['ticket_id'] == 'f2'
    assert best['changes'][1]['kelly']['qualifies'] and not best['changes'][1]['kelly']['selected']
    all_venues = campaigns.sizing_comparison(paired, F('.04'), 'all_venues', details=True)
    assert all_venues['counts']['jointly_selected_quotes'] == 1
    assert all_venues['counts']['venue_changes'] == 0


def test_portfolio_status_explains_independent_grading_and_zero_trade_evidence():
    graded = ticket('settled', '.04')
    pending = dict(ticket('pending', '.04', state='pending'), return_exact_usd=None)
    report = dict(games=[dict(capture_status='captured')], portfolios={
        'best_venue': dict(summary=paper_results._summary([graded])),
        'all_venues': dict(summary=paper_results._summary([graded, pending]))})
    assert paper_results.portfolio_status(report, 'best_venue') == 'graded'
    assert paper_results.portfolio_status(report, 'all_venues') == 'partially_graded'
    report['portfolios']['best_venue']['summary'] = paper_results._summary([])
    assert paper_results.portfolio_status(report, 'best_venue') == 'no_selected_tickets'
    report['games'].append(dict(capture_status='claimed'))
    assert paper_results.portfolio_status(report, 'best_venue') == 'collecting'
    report['games'] = [dict(capture_status='missed')]
    assert paper_results.portfolio_status(report, 'best_venue') == 'no_usable_capture'
