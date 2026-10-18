"""Authored retained metric cohorts; no accounts, clocks or providers mutated."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from app.collection.current_policy import DEFAULT
from app.comparison.broad_coverage import build, select, merge_queries, COUNT_KEYS
from app.comparison.coverage import CoverageLedger, SPORTS, FAMILIES

AT='2026-10-17T16:00:00Z'


def config(**changes):
    return dict(deepcopy(DEFAULT),sports=list(SPORTS),native_sports=list(SPORTS),**changes)


def owner(**changes):
    return dict(dict(runtime_id='authored-coverage',healthy=True,active=True,
        states={v:dict(state='available') for v in ('kalshi','polymarket_us','novig','prophetx','pinnacle')},
        status={},paused_sources=[]),**changes)


def observation(sport='NFL',venue='kalshi',family='moneyline',period='full_game',suffix='one',
                source_at='2026-10-17T15:59:00Z',outcome='home',published=True):
    quote=dict(venue=venue,source=dict(provider=venue if venue in ('kalshi','polymarket_us') else 'the_odds_api',
        native_event_id=sport+'-game',native_market_id=family+'-'+period,native_outcome_id=outcome+'-'+suffix,native_side='yes'),
        original=dict(value='0.4100',units='usd_per_contract',payout='1',payout_units='USD',quantity_units='contracts'),
        times=dict(source_at=source_at,received_at='2026-10-17T15:59:01Z'),state='available')
    record=dict(event=dict(competition=sport,id=sport+'-game',scheduled_start='2026-10-18T16:00:00Z',title=sport+' authored fixture',identity='resolved'),
        market_identity=dict(family=family,period=period),quote=quote)
    price=dict(deepcopy(quote),quote_id=venue+'-'+suffix,
        occurrence_match=dict(status='matched',occurrence_id=sport+'-same-game'),
        same_outcome=dict(supported=True,key=[sport,family,period,outcome],missing_fields=[]),
        gross_comparison=dict(available=True,display_status='current'),
        current_comparison=dict(available=True,display_status='current'),
        observation_display=dict(publication_reason_codes=[]),inputs_identity=dict(game_key=sport+'-game',quote_id=venue+'-'+suffix))
    return record, price if published else None


def payload():
    rows=[];prices=[]
    for sport in SPORTS:
        for family in FAMILIES:
            for venue in ('kalshi','polymarket_us'):
                r,p=observation(sport,venue,family,suffix=sport+'-'+family)
                rows.append(r);prices.append(p)
    return build(rows,prices,config=config(),owner=owner(),at=AT)


class BroadCoverage(unittest.TestCase):
    def test_complete_shared_matrix_and_same_cohort_ratios(self):
        value=payload();counts=value['global_totals']
        self.assertEqual(counts['retained_observations'],36)
        self.assertEqual(counts['supported_comparison_observations'],36)
        self.assertEqual(counts['current_comparison_observations'],36)
        self.assertEqual(counts['underlying_pairs'],18)
        self.assertEqual(counts['signed_comparison_directions'],36)
        self.assertEqual(counts['displayed_comparison_directions'],36)
        self.assertEqual(counts['displayed_current_comparison_directions'],36)
        self.assertEqual(counts['comparable_outcomes'],18)
        self.assertEqual(counts['matched_occurrences'],6)
        self.assertEqual(value['ratios']['supported_peer']['value'],1)
        self.assertEqual({(c['sport'],c['venue'],c['family']) for c in value['cells'] if c['period']=='full_game' and c['family'] in FAMILIES},
            {(s,v,f) for s in SPORTS for v in ('kalshi','polymarket_us','novig','prophetx','pinnacle') for f in FAMILIES})
        self.assertEqual(value['provider_requests'],0)

    def test_native_sides_pairs_directions_outcomes_and_reference_are_separate(self):
        samples=[observation(venue=v,suffix=n) for v,n in [('kalshi','a'),('kalshi','b'),('polymarket_us','c'),('novig','d'),('pinnacle','ref')]]
        rows=[r for r,p in samples];prices=[p for r,p in samples]
        value=build(rows+[deepcopy(rows[0])],prices,config=config(),owner=owner(),at=AT)
        counts=value['global_totals']
        self.assertEqual(counts['retained_observations'],5)
        self.assertEqual(counts['retained_comparison_observations'],4)
        self.assertEqual(counts['retained_reference_observations'],1)
        self.assertEqual(counts['underlying_pairs'],5)
        self.assertEqual(counts['signed_comparison_directions'],10)
        self.assertEqual(counts['displayed_comparison_directions'],4)
        self.assertEqual(counts['displayed_current_comparison_directions'],4)
        self.assertEqual(counts['comparable_outcomes'],1)
        self.assertEqual(value['ratios']['supported_peer']['denominator'],4)
        reference=next(c for c in value['cells'] if c['id']=='NFL|pinnacle|moneyline|full_game')
        self.assertIsNone(reference['ratios']['supported_peer']['value'])
        self.assertEqual(reference['counts']['underlying_pairs'],0)
        selected=select(value,venue='kalshi',league='NFL',market='winner',period='full_game')
        self.assertEqual(selected['filtered_totals']['retained_observations'],2)
        self.assertEqual(selected['filtered_totals']['underlying_pairs'],4)
        self.assertEqual(selected['filtered_totals']['comparable_outcomes'],1)
        self.assertEqual(selected['filtered_totals']['matched_occurrences'],1)
        self.assertEqual(selected['global_totals'],counts)
        self.assertEqual(selected['hidden_by_filter_observations'],3)

    def test_query_window_unique_unknown_failed_empty_partial_and_no_universe_funnel(self):
        ledger=CoverageLedger({v:SPORTS for v in ('kalshi','polymarket_us','novig','prophetx','pinnacle')})
        ledger.observe('NFL','kalshi',family='moneyline',checked_at='2026-10-17T14:00:00Z',status='offerings_returned',
            offered=dict(games=8,markets=10,quotes=20),unique_offered=dict(games=7,markets=9,quotes=None),completeness='partial')
        ledger.observe('NFL','polymarket_us',family='moneyline',checked_at='2026-10-17T14:00:00Z',status='no_offerings_returned',
            offered=dict(games=0,markets=0,quotes=0),unique_offered=dict(games=0,markets=0,quotes=0),completeness='complete',reason='query_empty')
        ledger.observe('NFL','novig',family='moneyline',checked_at='2026-10-17T14:00:00Z',status='failed_source',reason='source_failed')
        value=build([],[],config=config(),owner=owner(),at=AT,queries=ledger.snapshot()['cells'])
        cells={c['venue']:c for c in value['cells'] if c['sport']=='NFL' and c['family']=='moneyline' and c['period']=='full_game'}
        self.assertEqual(cells['kalshi']['discovery']['games'],7)
        self.assertEqual(cells['kalshi']['discovery']['reported_counts']['games'],8)
        self.assertIsNone(cells['kalshi']['discovery']['native_outcomes'])
        self.assertEqual(cells['polymarket_us']['discovery']['native_outcomes'],0)
        self.assertIsNone(cells['novig']['discovery']['games'])
        self.assertIsNone(cells['novig']['ratios']['supported_peer']['value'])
        self.assertIn('Provider-universe',cells['kalshi']['discovery']['window_note'])
        self.assertEqual(cells['kalshi']['counts']['retained_observations'],0)

    def test_exact_query_clock_and_last_success_survive_runtime_restart(self):
        ledger=CoverageLedger({'kalshi':SPORTS})
        checked='2026-10-17T14:00:00Z'
        ledger.observe('NFL','kalshi',family='total',checked_at=checked,status='offerings_returned',
            unique_offered=dict(games=2,markets=3,quotes=6),completeness='partial')
        old=merge_queries(ledger.snapshot()['cells'])
        restarted=CoverageLedger({'kalshi':SPORTS})
        retained=merge_queries(restarted.snapshot()['cells'],old)
        value=build([],[],config=config(),owner=owner(),at=AT,queries=retained)
        cell=next(c for c in value['cells'] if c['id']=='NFL|kalshi|total|full_game')
        self.assertEqual(cell['discovery']['checked_at'],checked)
        self.assertEqual(cell['discovery']['games'],2)
        self.assertEqual(cell['discovery']['completeness'],'partial')
        restarted.observe('NFL','kalshi',family='total',checked_at='2026-10-17T15:00:00Z',status='failed_source',reason='source_failed')
        failed=merge_queries(restarted.snapshot()['cells'],retained)
        value=build([],[],config=config(),owner=owner(),at=AT,queries=failed)
        cell=next(c for c in value['cells'] if c['id']=='NFL|kalshi|total|full_game')
        self.assertEqual(cell['discovery']['checked_at'],'2026-10-17T15:00:00Z')
        self.assertIsNone(cell['discovery']['games'])
        self.assertEqual(cell['discovery']['last_success']['checked_at'],checked)
        self.assertEqual(cell['discovery']['last_success']['unique_offered']['games'],2)

    def test_clock_aging_and_publication_do_not_refresh_original_input(self):
        samples=[observation(),observation(venue='polymarket_us',suffix='peer')]
        rows=[r for r,p in samples];prices=[p for r,p in samples]
        before=deepcopy(rows)
        later=build(rows,prices,config=config(),owner=owner(),at='2026-10-17T16:15:01Z')
        self.assertEqual(later['global_totals']['current_observations'],0)
        self.assertEqual(later['global_totals']['last_known_observations'],2)
        self.assertEqual(later['global_totals']['supported_comparison_observations'],2)
        self.assertEqual(later['global_totals']['current_comparison_observations'],0)
        self.assertEqual(rows,before)
        rows[0]['quote']['times']['source_at']=None
        unknown=build(rows,prices,config=config(),owner=owner(),at=AT)
        self.assertEqual(unknown['global_totals']['unknown_age_observations'],1)
        self.assertEqual(unknown['global_totals']['pending_observations'],1)
        self.assertEqual(unknown['global_totals']['supported_comparison_observations'],0)

    def test_displayed_differences_are_separate_from_eligible_pair_directions(self):
        samples=[observation(venue=v,suffix=str(n)) for n,v in enumerate(('kalshi','kalshi','polymarket_us','novig'))]
        rows=[r for r,p in samples];prices=[p for r,p in samples]
        prices[0]['gross_comparison'].update(display_status='unknown')
        prices[1]['gross_comparison'].update(display_status='last_known')
        prices[2]['gross_comparison'].update(display_status='pending')
        prices[0]['current_comparison'].update(display_status='unknown')
        prices[1]['current_comparison'].update(display_status='last_known')
        prices[2]['current_comparison'].update(display_status='pending')
        value=build(rows,prices,config=config(),owner=owner(),at=AT)
        counts=value['global_totals']
        self.assertEqual(counts['signed_comparison_directions'],10)
        self.assertEqual(counts['displayed_comparison_directions'],4)
        self.assertEqual(counts['displayed_current_comparison_directions'],1)
        filtered=select(value,venue='kalshi')
        self.assertEqual(filtered['filtered_totals']['displayed_comparison_directions'],2)
        self.assertEqual(filtered['filtered_totals']['displayed_current_comparison_directions'],0)

    def test_unsupported_native_price_and_binding_do_not_count_supported_pairs(self):
        for defect in ('zero_price','binding_unverified','expired_link'):
            with self.subTest(defect=defect):
                samples=[observation(),observation(venue='polymarket_us',suffix='peer')]
                rows=[r for r,p in samples];prices=[p for r,p in samples]
                for row,price in zip(rows,prices):
                    if defect=='zero_price':
                        row['quote']['original']['value']='0'
                        price['original']['value']='0'
                        code='comparison_native_unsupported'
                    elif defect=='binding_unverified':
                        row['quote']['binding']=dict(verified=False)
                        code='comparison_native_unsupported'
                    else:
                        price['occurrence_link']=dict(version='predict-occurrence-match-1',edges=['a'*64],
                            effective_from='2026-10-16T00:00:00Z',effective_until='2026-10-17T15:00:00Z')
                        code='comparison_mapping_unavailable'
                    for name in ('gross_comparison','current_comparison'):
                        price[name]=dict(available=False,reason_code=code,display_status='unavailable')
                value=build(rows,prices,config=config(),owner=owner(),at=AT)
                counts=value['global_totals']
                self.assertEqual(counts['retained_observations'],2)
                self.assertEqual(counts['supported_comparison_observations'],0)
                self.assertEqual(counts['current_comparison_observations'],0)
                self.assertEqual(counts['underlying_pairs'],0)
                self.assertEqual(counts['displayed_comparison_directions'],0)
                self.assertEqual(counts['displayed_current_comparison_directions'],0)
                cell=next(c for c in value['cells'] if c['id']=='NFL|kalshi|moneyline|full_game')
                reason='native_price_or_binding_unsupported' if defect!='expired_link' else 'occurrence_identity_unresolved'
                self.assertIn(reason,{r['code'] for r in cell['reasons']})
                self.assertIn(code,cell['examples'][0]['diagnostic_codes'])

    def test_captured_source_unavailability_survives_later_healthy_owner(self):
        for captured in ('raw','published'):
            with self.subTest(captured=captured):
                samples=[observation(),observation(venue='polymarket_us',suffix='peer')]
                rows=[r for r,p in samples];prices=[p for r,p in samples]
                if captured=='raw':rows[0]['quote']['state']='unavailable'
                else:prices[0]['captured_source_state']='unavailable'
                prices[0]['observation_display'].update(state='last_known',source_reason_codes=['captured_source_unavailable'])
                prices[0]['current_comparison'].update(available=False,display_status='unavailable',reason_code='comparison_selected_not_current')
                prices[1]['current_comparison'].update(available=False,display_status='unavailable',reason_code='comparison_peers_not_current')
                value=build(rows,prices,config=config(),owner=owner(),at=AT)
                counts=value['global_totals']
                self.assertEqual(counts['current_observations'],1)
                self.assertEqual(counts['last_known_observations'],1)
                self.assertEqual(counts['supported_comparison_observations'],2)
                self.assertEqual(counts['current_comparison_observations'],0)
                self.assertEqual(counts['displayed_comparison_directions'],2)
                self.assertEqual(counts['displayed_current_comparison_directions'],0)

    def test_operational_disabled_unconfigured_and_unsupported_cells_remain_visible(self):
        value=build([],[],config=config(aggregate_enabled=False),owner=owner(paused_sources=['kalshi']),at=AT,
            encountered=[dict(league='NFL',source='kalshi',family='futures',period='season')])
        cells={c['id']:c for c in value['cells']}
        self.assertEqual(cells['NFL|kalshi|moneyline|full_game']['configuration_state'],'paused')
        self.assertEqual(cells['NFL|novig|moneyline|full_game']['configuration_state'],'disabled')
        self.assertEqual(cells['NFL|kalshi|futures|season']['configuration_state'],'not_configured')
        self.assertEqual(cells['NFL|kalshi|futures|season']['capability']['state'],'unsupported')
        held=build([],[],config=config(),owner=owner(status=dict(quota=dict(pause='quota_unknown',reserved=9,unresolved_attempts=3))),at=AT)
        self.assertTrue(held['aggregate_acquisition']['held'])
        self.assertEqual(next(c for c in held['cells'] if c['id']=='NFL|novig|moneyline|full_game')['configuration_state'],'held')

    def test_overlapping_reason_counts_primary_reconciliation_and_original_examples(self):
        row,price=observation(source_at=None)
        row['comparison_source_metadata']=dict(comparison_admission=dict(reason='comparison_context_missing',missing_fields=['season','stage']))
        failure=dict(members=[['kalshi','NFL-game']],reason='schedule_binding_unverified',schedule_conflicts=[dict(field='scheduled_start',native='2026-10-18T16:00:00Z',retained='2026-10-18T16:08:00Z')])
        value=build([row],[],config=config(),owner=owner(),at=AT,exclusions=[failure])
        cell=next(c for c in value['cells'] if c['id']=='NFL|kalshi|moneyline|full_game')
        reasons={r['code']:r for r in cell['reasons']}
        for code in ('schedule_conflict','comparison_context_missing','unknown_source_clock','waiting_for_publication','cross_source_peer_missing'):
            self.assertEqual(reasons[code]['count'],1)
        self.assertEqual(sum(r['primary_count'] for r in cell['reasons']),1)
        sample=reasons['schedule_conflict']['examples'][0]
        self.assertEqual(sample['original']['value'],'0.4100')
        self.assertIsNone(sample['times']['source_at'])
        self.assertEqual(sample['failed_conditions'][0]['field'],'scheduled_start')
        self.assertEqual(sample['missing_fields'],['season','stage'])
        self.assertEqual(sample['provider_requests'],0)

    def test_successful_scoring_diagnostic_is_not_a_gap(self):
        row,price=observation()
        row['comparison_source_metadata']=dict(scoring_scope=dict(status='supported',reason='selected_scoring_scope_supported'),
            comparison_admission=dict(supported=True,reason='comparison_predicate_supported'))
        peer,peer_price=observation(venue='polymarket_us',suffix='peer')
        value=build([row,peer],[price,peer_price],config=config(),owner=owner(),at=AT)
        cell=next(c for c in value['cells'] if c['id']=='NFL|kalshi|moneyline|full_game')
        self.assertNotIn('scoring_scope_missing_or_conflicting',{r['code'] for r in cell['reasons']})
        self.assertNotIn('selected_scoring_scope_supported',cell['examples'][0]['diagnostic_codes'])

    def test_first_read_unknown_cohort_and_filter_reads_never_invoke_provider(self):
        value=payload();before=deepcopy(value)
        with patch('app.collection.current_native.NativeWorker',side_effect=AssertionError('provider dispatch')):
            for sport in SPORTS:
                filtered=select(value,league=sport)
                self.assertEqual(filtered['filtered_totals']['retained_observations'],6)
        self.assertEqual(value,before)
        with self.assertRaises(ValueError):select(value,league='other')
        self.assertEqual(set(value['global_totals']),set(COUNT_KEYS))


if __name__=='__main__':
    unittest.main()
