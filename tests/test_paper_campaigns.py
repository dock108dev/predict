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


def test_expected_roi_is_stake_weighted_and_gap_uses_only_graded_trades():
    graded = dict(ticket('graded', '.10', state='win'), return_exact_usd='12')
    pending = dict(ticket('pending', '.20', state='pending'), stake_exact_usd='30',
                   expected_profit_exact_usd='6', return_exact_usd=None)
    summary = campaigns.analysis([graded, pending], ['.04'], 'all_venues')['summary']
    assert F(summary['expected_profit_exact_usd']) == 7
    assert F(summary['expected_roi']) == F(7, 40)
    assert summary['expected_roi_percent'] == '17.50'
    assert F(summary['resolved_expected_profit_exact_usd']) == 1
    assert F(summary['pnl_vs_expected_exact_usd']) == 1
    empty = campaigns.analysis([], ['.04'], 'all_venues')['summary']
    assert empty['expected_roi'] is None and empty['pnl_vs_expected_exact_usd'] is None


def test_posted_odds_buckets_partition_exact_boundaries_and_unavailable_prices():
    quotes = ('-101', '-100', '+100', '+100.01', '+199.999', '+200', '+300',
              '+499.999', '+500', '+999.999', '+1000', None, '+99', 'bad')
    rows = [dict(ticket(str(i), '.05'), posted_odds=quote) for i, quote in enumerate(quotes)]
    buckets = campaigns.odds_buckets(rows)
    assert [(b['id'], b['summary']['tickets']) for b in buckets] == [
        ('favorites', 1), ('even_money', 2), ('plus_100_to_200', 2), ('plus_200_to_300', 1),
        ('plus_300_to_500', 2), ('plus_500_to_1000', 2), ('plus_1000_and_up', 1), ('unavailable', 3),
    ]
    assert sum(F(b['stake_share']) for b in buckets) == 1
    assert buckets[-1]['stake_share_percent'] == '21.43'
    assert all(b['stake_share'] is None for b in campaigns.odds_buckets([]))


def test_settings_normalize_minimum_stake_and_custom_odds_boundaries():
    defaults = campaigns.configuration(fixed_config())
    assert campaigns.configuration(fixed_config(odds_bucket_edges=['+200', '300', '500', '1000'])) == defaults
    configured = campaigns.configuration(fixed_config(minimum_stake_usd='1.25', odds_bucket_edges=['+275', '750']))
    assert configured['minimum_stake_usd'] == '5/4'
    assert configured['odds_bucket_edges'] == ['275', '750']
    rows = [dict(ticket(str(i), '.05'), posted_odds=value) for i, value in enumerate(('+274.9', '+275', '+750'))]
    buckets = campaigns.odds_buckets(rows, configured['odds_bucket_edges'])
    assert [(b['id'], b['summary']['tickets']) for b in buckets if b['summary']['tickets']] == [
        ('plus_100_to_275', 1), ('plus_275_to_750', 1), ('plus_750_and_up', 1),
    ]
    for minimum in ('0', '-1', '1/0', 1):
        with pytest.raises(workspace.SelectionError, match='positive minimum stake'):
            campaigns.configuration(fixed_config(minimum_stake_usd=minimum))
    for edges in ([], ['100'], ['+200', '200'], ['300', '250'], ['+300.25'], [200], ['1234567890']):
        with pytest.raises(workspace.SelectionError, match='whole-number odds boundaries'):
            campaigns.configuration(fixed_config(odds_bucket_edges=edges))


def test_one_bet_per_game_configuration_only_offers_the_single_ticket_portfolio():
    rule = paper.MAIN_FIRST_ONE_PER_GAME
    configured = campaigns.configuration(fixed_config(portfolio_rule=rule, portfolios=['best_venue']))
    assert configured['portfolio_rule'] == rule
    assert configured['portfolios'] == ['best_venue']
    assert 'portfolio_rule' not in campaigns.configuration(fixed_config())
    for portfolios, value in ((['all_venues'], rule), (['best_venue', 'all_venues'], rule),
                              (['best_venue'], 'unsupported')):
        with pytest.raises(workspace.SelectionError, match='one-bet-per-game rule'):
            campaigns.configuration(fixed_config(portfolio_rule=value, portfolios=portfolios))


def test_ev_thresholds_reselect_a_single_pick_from_the_frozen_candidate_pool():
    rule = paper.MAIN_FIRST_ONE_PER_GAME
    main = dict(ticket('main', '.05'), probability='0.55',
                portfolio_selection=dict(tier='main', distance_points='0', line_role='main'))
    near = dict(ticket('near', '.12'), probability='0.29',
                portfolio_selection=dict(tier='nearby_alternate', distance_points='2', line_role='alternate'))
    far = dict(ticket('far', '.18'), probability='0.40',
               portfolio_selection=dict(tier='nearby_alternate', distance_points='7', line_role='alternate'))
    rows = [far, near, main]
    assert [t['id'] for t in campaigns.select(rows, F('.04'), 'best_venue', rule)] == ['main']
    assert [t['id'] for t in campaigns.select(rows, F('.08'), 'best_venue', rule)] == ['near']
    summary = campaigns.analysis(rows, ['.04', '.08', '.15'], 'best_venue', rule)
    assert [F(t['summary']['expected_roi']) for t in summary['thresholds']] == [F('.05'), F('.12'), F('.18')]
    assert [t['summary']['tickets'] for t in summary['thresholds']] == [1, 1, 1]


def test_posted_odds_uses_selected_portfolio_and_keeps_unpublished_grades_pending():
    rows = [dict(ticket('winner', '.06', bet='shared', state='win'), posted_odds='+500',
                 stake_usd='10', return_exact_usd='20'),
            dict(ticket('alternate', '.05', bet='shared', venue='novig'), posted_odds='+1000', stake_usd='10'),
            dict(ticket('pending', '.20'), posted_odds='+550', stake_usd='30', expected_profit_exact_usd='6'),
            dict(ticket('other_pending', '.10'), posted_odds='+1000', stake_usd='2', expected_profit_exact_usd='1/5')]
    report = dict(portfolios=dict(best_venue=dict(tickets=[rows[0]])))
    selected = campaigns.select(rows, F('.04'), 'best_venue')
    buckets = {b['id']: b for b in campaigns.odds_buckets(campaigns._selection_rows(selected, report, 'best_venue'))}
    group = buckets['plus_500_to_1000']
    assert F(group['stake_share']) == F(20, 21)
    assert group['summary']['tickets'] == 2 and group['summary']['resolved'] == 1
    assert F(group['summary']['stake_exact_usd']) == 40
    assert F(group['summary']['expected_roi']) == F(33, 200)
    assert F(group['summary']['roi_stake_exact_usd']) == 10
    assert F(group['summary']['roi']) == 1
    unresolved = buckets['plus_1000_and_up']['summary']
    assert unresolved['tickets'] == 1 and unresolved['resolved'] == 0
    assert unresolved['pnl_exact_usd'] is None and unresolved['roi'] is None


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
