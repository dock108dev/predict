"""Capability and authored complete-matrix/partial-period ingress controls."""
from copy import deepcopy
import unittest

from app.collection.current_policy import DEFAULT
from app.collection.current_native import balanced_markets, fair_metadata_bindings, unique_metadata_counts
from app.comparison.capabilities import inventory,SPORTS,CORE_FAMILIES,SOURCES
from app.comparison.same_outcome import record_identity
from tests.broad_pipeline_fixtures import captured_core_matrix,captured_partial,partial_case


class CapabilityInventory(unittest.TestCase):
    def test_matrix_uses_actual_independent_configuration_and_preserves_reference_role(self):
        config=dict(deepcopy(DEFAULT),native_sports=list(SPORTS),native_families=list(CORE_FAMILIES))
        before=deepcopy(config);cells=inventory(config)
        core=[c for c in cells if c['period']=='full_game' and c['family'] in CORE_FAMILIES]
        self.assertEqual(len(core),len(SPORTS)*len(SOURCES)*len(CORE_FAMILIES))
        self.assertEqual(sum(c['configured'] for c in core),36+9)
        for cell in core:
            self.assertTrue(cell['normalization_supported'])
            self.assertEqual(cell['comparison_supported'],cell['source']!='pinnacle')
            self.assertEqual(cell['acquisition_provider'],cell['source'] if cell['source'] in ('kalshi','polymarket_us') else 'the_odds_api')
        self.assertEqual(config,before)

    def test_encountered_types_and_periods_stay_explicit_without_claiming_acquisition(self):
        cells=inventory(DEFAULT,[dict(league='NBA',source='kalshi',family='team_total',period='first_quarter')])
        extra=next(c for c in cells if c['family']=='team_total' and c['period']=='first_quarter')
        self.assertTrue(extra['encountered']);self.assertFalse(extra['configured'])
        self.assertFalse(extra['comparison_supported'])
        self.assertIn('team_total_subject_binding_unimplemented',extra['capability_reasons'])
        half=next(c for c in cells if (c['league'],c['source'],c['family'],c['period'])==('NBA','kalshi','total','first_half'))
        self.assertTrue(half['normalization_supported']);self.assertTrue(half['comparison_supported'])
        self.assertFalse(half['configured']);self.assertFalse(half['acquisition_enabled'])
        self.assertFalse(half['discovery_supported'])

    def test_disable_switches_are_operational_without_erasing_implemented_capability(self):
        cells=inventory(dict(deepcopy(DEFAULT),enabled=False,aggregate_enabled=False))
        self.assertFalse(any(c['acquisition_enabled'] for c in cells))
        self.assertTrue(any(c['configured'] and c['comparison_supported'] for c in cells))


class FairSelection(unittest.TestCase):
    def test_dense_families_cannot_consume_all_exact_metadata_locators(self):
        refs=[];markets=[]
        for family,suffix,count in (('moneyline','winner',30),('spread','spread',20),('total','total',1)):
            for index in range(count):
                mid=family+str(index);refs.append(dict(id=mid,slug=mid))
                markets.append(dict(id=mid,sportsMarketType='basketball_team_full_game_'+suffix))
        seen=set()
        for offset in range(30):
            selected=fair_metadata_bindings(dict(market_bindings=refs),dict(markets=markets),list(CORE_FAMILIES),offset)
            self.assertEqual(len(selected),3)
            self.assertEqual({next(m['sportsMarketType'] for m in markets if m['id']==r['id']) for r in selected},
                {'basketball_team_full_game_'+suffix for suffix in ('winner','spread','total')})
            seen.update(r['id'] for r in selected)
        self.assertEqual(seen,{r['id'] for r in refs})

    def test_periods_share_one_rotating_source_cap(self):
        markets=[dict(id=period+str(i),event_id=period,market_type='total',period=period)
                 for period,count in (('full_game',50),('first_half',1)) for i in range(count)]
        events={period:dict(competition='NBA') for period in ('full_game','first_half')}
        self.assertEqual({balanced_markets(markets,1,['total'],events=events,offset=i)[0]['period'] for i in range(2)},
            {'full_game','first_half'})

    def test_unique_metadata_deduplicates_native_units_and_keeps_missing_outcomes_unknown(self):
        row=dict(id='market',event_id='event',_native=dict(marketSides=[dict(id='long'),dict(id='short')]))
        self.assertEqual(unique_metadata_counts([row,row],'polymarket_us'),dict(games=1,markets=1,quotes=2))
        row['_native']['marketSides']=[dict(id=None)]
        self.assertIsNone(unique_metadata_counts([row],'polymarket_us')['quotes'])


class AuthoredIngress(unittest.IsolatedAsyncioTestCase):
    async def test_joint_six_league_two_native_three_family_ingress(self):
        rows,books=await captured_core_matrix()
        self.assertEqual(len(rows),72);self.assertEqual(len(books),36)
        self.assertEqual({(r['event']['competition'],r['quote']['venue'],r['market_identity']['family']) for r in rows},
            {(sport,source,family) for sport in SPORTS for source in ('kalshi','polymarket_us') for family in CORE_FAMILIES})
        self.assertTrue(all(r['comparison_source_metadata']['scoring_scope']['status']=='supported' for r in rows))

    async def test_explicit_partial_scoring_reaches_shared_native_comparison(self):
        scopes=[(sport,family,'first_half',venue) for sport in ('NFL','NCAAF','NBA','NCAAB')
                for family in CORE_FAMILIES for venue in ('kalshi','polymarket_us')]
        scopes += [('MLB',family,period,'kalshi') for period,families in
                   (('first_3',('moneyline',)),('first_5',CORE_FAMILIES)) for family in families]
        for sport,family,period,venue in scopes:
            with self.subTest(sport=sport,family=family,period=period,venue=venue):
                case=partial_case(sport,family,period,'partial-'+sport+'-'+family+'-'+period)
                rows,excluded,book,catalog=await captured_partial(case,venue)
                self.assertEqual(excluded,[],catalog);self.assertEqual(len(rows),2,catalog)
                self.assertTrue(all(r['market_identity']['period']==period for r in rows))
                for row in rows:
                    scope=row['comparison_source_metadata']['scoring_scope']
                    self.assertEqual(scope['status'],'supported',scope)
                    self.assertEqual(scope['overtime'],'excluded')
                    self.assertTrue(record_identity(row)['supported'],record_identity(row))
                    self.assertEqual(row['quote']['times']['source_at'],book['raw']['exchange_at'])
                    self.assertEqual(row['quote']['original']['value'],'0.51')

    async def test_partial_later_scoring_missing_or_contradictory_never_inherits_full_game_default(self):
        for clause in ('', 'Overtime is included.', 'Overtime is excluded. Overtime is included.'):
            case=partial_case('NBA','total','first_half','partial-scope-refusal')
            case['markets']['kalshi']['rules_secondary']=clause
            rows,excluded,_,_=await captured_partial(case,'kalshi')
            self.assertEqual(excluded,[]);self.assertEqual(len(rows),2)
            for row in rows:
                self.assertFalse(record_identity(row)['supported'])
                self.assertEqual(row['quote']['original']['value'],'0.51')

    async def test_partial_comparison_keys_keep_period_and_native_complement_distinct(self):
        case=partial_case('NFL','moneyline','first_half','shared-period-key')
        kalshi,_,_,_=await captured_partial(case,'kalshi')
        retail,_,_,_=await captured_partial(case,'polymarket_us')
        yes=next(r for r in kalshi if r['quote']['source']['native_side']=='yes')
        no=next(r for r in kalshi if r['quote']['source']['native_side']=='no')
        long=next(r for r in retail if r['quote']['source']['native_side']=='Long')
        self.assertEqual(record_identity(yes)['key'],record_identity(long)['key'])
        self.assertNotEqual(record_identity(yes)['key'],record_identity(no)['key'])
        full=deepcopy(yes);full['market_identity']['period']='full_game'
        full['comparison_source_metadata']['same_outcome']['scoring']['overtime']='included'
        self.assertNotEqual(record_identity(yes)['key'],record_identity(full)['key'])


if __name__=='__main__':unittest.main()
