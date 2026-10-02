"""Public documents + explicitly synthetic examples; no account or API access."""
from copy import deepcopy
from decimal import Decimal
import hashlib,json,unittest
from pathlib import Path
from unittest.mock import patch
from app.collection import public_contracts as pc
from app.fees import calculate,replay
from app.fees.public_bindings import bind,us_execution
from app.fee_example import scenario
from app.resolution import core
from app.resolution.source_adapters import adapt,derive,kalshi_account_report
from app.normalization.score_lines import orient_descriptor,payout

ROOT=Path(__file__).resolve().parents[1]

def binding(series):
 d=json.loads((ROOT/'app/fixtures/native-scope-bindings-v1.json').read_text())
 return next(x for x in d['bindings'] if x['series_ticker']==series)

def adapter_binding(source='kalshi',mid='K',eid='E',outcome='yes'):
 return dict(source=source,native=dict(event_id=eid,market_id=mid,outcome_id=outcome),source_event_id=eid,
 target={'market_identity':{'competition':'NFL','family':'moneyline'}},contract=source+':'+outcome,period='first_half')

class PublicContracts(unittest.TestCase):
 def test_all_public_sources_are_retained_and_baseline_252_preserved(self):
  d=pc.load()
  for s in d['sources'].values():
   p=ROOT/s['path'];self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),s['sha256'],s['id'])
   self.assertTrue(s['clause']);self.assertTrue(s['applicability']);self.assertIn('effective_date',s)
  original=json.loads((ROOT/'evidence/public-contract-bindings-20260930-v1/baseline.json').read_text())
  for p in ['evidence/source-engineering-extension-20260930-v1/requirement-status.json','evidence/source-engineering-extension-20260930-v1/external-blockers.json','app/fixtures/source-bindings-current.json','app/fixtures/fee-schedules-v1.json','app/normalization/college-2026-27.json','app/dashboard/native_book_comparison.py','app/collection/native_score_binding.py']:
   if p=='app/collection/native_score_binding.py':
    # V2 admission repair is authorized to change current code. The historical
    # implementation stays byte-exact in the consumed package; default-policy
    # replay parity is separately exercised across every retained native record.
    import zipfile
    with zipfile.ZipFile(ROOT/'scripts/v1_coverage_package/SOURCE.zip') as sealed:
     self.assertEqual(hashlib.sha256(sealed.read(p)).hexdigest(),original[p],p)
   else:self.assertEqual(hashlib.sha256((ROOT/p).read_bytes()).hexdigest(),original[p],p)
  self.assertEqual(hashlib.sha256((ROOT/'evidence/public-contract-integration-20261001-v1/verification/pre-repair-session_history.py').read_bytes()).hexdigest(),original['app/dashboard/session_history.py'])
 def test_exact_preseason_stage_and_conflicts_never_calendar_inferred(self):
  kwargs=dict(source='kalshi',event_id='KXNBAGAME-26OCT03MIATOR',competition='NBA',participants=['NBA:MIA','NBA:TOR'],scheduled_start='2026-10-03T23:00:00Z')
  r=pc.event_identity(**kwargs);self.assertEqual(r['enrichment']['stage'],'preseason')
  self.assertEqual(r['enrichment']['season'],'2026-2027')
  r=pc.event_identity(**kwargs,provider_stage='regular_season');self.assertEqual(r['original']['provider_stage'],'regular_season');self.assertTrue(r['conflicts'])
  self.assertEqual(pc.event_identity(**dict(kwargs,scheduled_start='2026-10-03T23:10:00Z'))['status'],'UNBOUND')
  self.assertEqual(pc.event_identity(**dict(kwargs,event_id='guessed'))['status'],'UNBOUND')
 def test_nhl_label_and_start_mismatch_remain_explicit(self):
  r=pc.event_identity(source='polymarket_us',event_id='127804',competition='NHL',participants=['NHL:NYI','NHL:TOR'],scheduled_start='2026-09-30T23:30:00Z',provider_label='nhl-2025')
  self.assertEqual(r['status'],'ENRICHED_WITH_CONFLICT');self.assertEqual(r['enrichment']['stage'],'regular_season')
  r=pc.event_identity(source='kalshi',event_id='KXNHLGAME-26SEP30LACOL',competition='NHL',participants=['NHL:LA','NHL:COL'],scheduled_start='2026-10-01T02:10:00Z')
  self.assertEqual(r['status'],'UNBOUND')
 def test_membership_exact_365_and_original_identities(self):
  r=pc.college_registry();self.assertEqual(len([e for e in r.entities.values() if e.get('league')=='NCAAB']),365)
  self.assertIn('NCAAB:M:D1:ALA',r.entities);self.assertNotIn('NCAAB:M:D1:NCAA8',r.entities)
  self.assertTrue(all(m['academic_year']==2027 and m['division']==1 for m in pc.load()['ncaab_membership']['members']))
 def test_us_types_exclude_team_totals_and_generic_period_inference(self):
  for native in ('football_team_first_half_winner','football_team_first_half_spread','football_game_first_half_total'):
   r=pc.us_type({'metadata':{'market_sport_type':native}},competition='NFL');self.assertEqual(r['period'],'first_half')
  for native in ('football_team_first_half_total','moneyline','hockey_team_first_period_winner'):
   self.assertEqual(pc.us_type({'sportsMarketType':native},competition='NFL')['status'],'UNBOUND')
  r=pc.us_type({'metadata':{'market_sport_type':'baseball_team_first_five_total','outcome_strike':'2.5'}},competition='MLB')
  self.assertEqual(r['period'],'first_5');self.assertEqual(r['strike_magnitude'],'2.5')
  self.assertFalse(pc.us_selector('EXACT','spread')['collection_authorized'])
 def test_missing_offerings_are_not_negative_samples(self):
  self.assertEqual(pc.load()['offerings']['documented_non_support'],[])
  r=pc.odds_outright(dict(sport_key='americanfootball_nfl_super_bowl_winner',bookmakers=[dict(key='novig',markets=[dict(key='outrights',outcomes=[dict(name='Team',price='8')])])]),'NFL')
  self.assertEqual(r['outcomes'][0]['decimal_odds'],'8');self.assertIn('Source contract payout/fee terms',r['missing'])
  with self.assertRaises(ValueError):pc.odds_outright(dict(sport_key='afc_winner'),'NFL')
 def test_nfl_h1_strict_total_no_sportsbook_push(self):
  native=dict(rules_primary='If Pittsburgh and Cleveland collectively score more than 20 points in the 1st half of their game, then the market resolves to Yes.',strike_type='greater',floor_strike=20,cap_strike=None)
  d=pc.descriptor(native,binding('KXNFL1HTOTAL'))['descriptor']
  domain,sides=orient_descriptor(dict(competition='NFL',home='NFL:PIT',away='NFL:CLE'),d)
  self.assertEqual([payout(s,dict(representative='20')) for s in sides],['0','1'])
  self.assertEqual(domain['domain'],'combined_score')
  r=pc.period_decision(binding('KXNFL1HTOTAL'),completed=True,resumption_within_window=False)
  self.assertEqual(r['payout_basis'],'existing_score_predicate')
  r=pc.period_decision(binding('KXNFL1HTOTAL'),completed=False,resumption_within_window=False)
  self.assertIsNone(r['payout_basis'])
 def test_hockey_completed_period_template_and_tie_unknown_only(self):
  e=dict(competition='NHL',home='NHL:TOR',away='NHL:NYI')
  for p in ['period_1','period_2','period_3']:
   d=pc.hockey_period_template(family='moneyline',period=p,participant='NHL:TOR')['descriptor']
   domain,sides=orient_descriptor(e,d)
   self.assertEqual([payout(s,dict(representative='1')) for s in sides],['1','0'])
   self.assertEqual([payout(s,dict(representative='0')) for s in sides],[None,None])
   self.assertEqual(d['segment_start'],d['segment_end']);self.assertEqual(d['overtime'],'excluded')
 def test_novig_h1_shared_fraction_not_stake_refund(self):
  r=pc.novig_h1_descriptor(participant='NFL:PIT',yes_id='PIT',no_id='CLE')
  _,sides=orient_descriptor(dict(competition='NFL',home='NFL:PIT',away='NFL:CLE'),r['descriptor'])
  self.assertEqual([payout(s,dict(representative='0')) for s in sides],['0.5','0.5'])
  self.assertEqual(r['status'],'IMPLEMENTED_AWAITING_REAL_SOURCE_EVIDENCE')
 def test_championship_categories_field_and_exception_precedence(self):
  field=pc.load()['fields']['NFL']['members'];self.assertEqual(len(field),32)
  b=binding('KXSB');r=pc.championship_payout(b,participant=field[0],field=field,winners=field[:3])
  self.assertEqual(r['yes'],'0.33');self.assertEqual(r['no'],'0.67')
  r=pc.championship_payout(b,participant=field[0],field=field,cancellation=True,eligible=field[:3]);self.assertEqual(r['yes'],'0.33')
  b=binding('KXNFLAFCCHAMP');r=pc.championship_payout(b,participant=field[0],field=field,cancellation=True,eligible=field[:3]);self.assertIsNone(r['yes'])
  r=pc.championship_payout(b,participant=field[0],field=field,cancellation=True,eligible=field[:3],earlier_steps_unavailable=True);self.assertEqual(r['yes'],'0.33')
  self.assertEqual(len(pc.load()['fields']['AAC']['members']),14)
 def test_settlement_dimensions_remain_independent(self):
  p=pc.settlement_profile(binding('KXMLBF5TOTAL'));self.assertEqual(p['dimensions']['listed_pitchers']['value'],'action_all_starting_pitcher_changes_valid')
  self.assertIsNone(p['dimensions']['deadlines']['value'])
  self.assertEqual(p['payouts']['canceled']['kind'],'unknown')

class PublicFees(unittest.TestCase):
 def test_us_successor_fractional_fee_and_exact_replay(self):
  c=scenario('polymarket_us',quantity='3.12');c['market_id']='M';c['trade_time']='2026-09-30T12:00:00Z';c['calculation_time']=c['trade_time']
  c=bind(c,market=dict(id='M',feeCoefficient='0.0695',isCombo=False),instrument=dict(market_id='M',source='SYNTHETIC exact instrument',fractionalQtyScale='100'))
  r=calculate(c);self.assertEqual(r['formula_support'],'implemented');self.assertEqual(r['schedule']['coefficient'],'0.0695');self.assertEqual(replay(r),r)
  c['quantity_scale_evidence']['market_id']='different';self.assertIsNone(calculate(c)['entry_fees'])
 def test_fixed_point_execution_commission_is_not_inferred_from_price(self):
  r=us_execution(dict(order=dict(priceScale='100',fractionalQuantityScale='100'),lastPx='97',lastShares='312',commissionNotionalCollected='100'))
  self.assertEqual(Decimal(r['price']),Decimal('.97'));self.assertEqual(Decimal(r['quantity']),Decimal('3.12'));self.assertEqual(Decimal(r['commission_usd']),Decimal('.01'))
  r=us_execution(dict(order=dict(priceScale='100',fractionalQuantityScale='100'),lastPx='97',lastShares='312'));self.assertEqual(Decimal(r['commission_usd']),0)
 def test_novig_native_cent_units_phase_and_fee_object(self):
  c=scenario('novig',quantity='10000');c['api_regime']='v3';c['market_id']='M';c['fills'][0].update(unit='novig_v3_contracts',event_status_at_match='OPEN_INGAME')
  c=bind(c,market=dict(marketId='M',fee=dict(coefficient='0.03',makerCredit='0.5',charged='WHEN_LIVE')))
  r=calculate(c);self.assertEqual(Decimal(r['entry_notional']),50);self.assertEqual(Decimal(r['entry_fees']),Decimal('.75'));self.assertEqual(replay(r),r)
  c['fills'][0]['event_status_at_match']='OPEN_PREGAME';self.assertEqual(Decimal(calculate(c)['entry_fees']),0)
  c['fills'][0]['unit']='contracts'
  with self.assertRaises(ValueError):calculate(c)
 def test_prophetx_per_market_rule_and_rounding_scenario(self):
  c=scenario('prophetx','straight');c=bind(c);c['fills']=[];c['market_cashflows']=dict(market_id=c['market_id'],stake_usd='150',gross_payouts={'win':'200'},complete_market=True)
  r=calculate(c);self.assertEqual(r['outcomes']['win']['settlement_fee_unrounded'],'1.00');self.assertIsNone(r['outcomes']['win']['net_payout'])
  c['settlement_rounding']='cent_half_up';self.assertEqual(Decimal(calculate(c)['outcomes']['win']['net_payout']),199)
 def test_account_membership_is_input_not_secret_lookup(self):
  c=scenario('kalshi');self.assertEqual(bind(c,membership='non_direct')['balance_precision'],'0.01')
  c.pop('balance_precision',None);self.assertEqual(bind(c,membership='direct')['balance_precision'],'0.0001')
  c=bind(c,membership='direct');c['settlement_contract_kind']='scalar';r=calculate(c);self.assertTrue(all(v['net_payout'] is None for v in r['outcomes'].values()))

class SourceAdapters(unittest.TestCase):
 def test_kalshi_binary_and_scalar_ignore_prices_and_missing_clocks(self):
  c=adapter_binding();m=dict(market=dict(ticker='K',event_ticker='E',result='yes',yes_bid_dollars='0.13'))
  p=derive('kalshi_market',json.dumps(m),c);self.assertEqual(p['payout']['value'],'1');self.assertIsNone(p['published_at'])
  m['market'].update(result='scalar',notional_value_dollars='1',settlement_value_dollars='0.306')
  c['native']['outcome_id']='no';self.assertEqual(derive('kalshi_market',json.dumps(m),c)['payout']['value'],'0.694')
  del m['market']['settlement_value_dollars']
  with self.assertRaises(KeyError):derive('kalshi_market',json.dumps(m),c)
 def test_us_present_zero_and_local_correction_lineage(self):
  c=adapter_binding('polymarket_us','M','E','long');c.update(instrument_symbol='SYMBOL',instrument_market_id='M',side='long')
  m=dict(symbol='SYMBOL',priceScale='100',stats=dict(settlementPx='0',settlementPreliminary=False,settlementPriceCalculationMethod='SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_1',settlementSetTime='2026-09-30T12:00:00Z'))
  r=adapt('us_instrument',json.dumps(m),c,url='https://example.invalid/SYNTHETIC-selected-settlement',received_at='2026-09-30T13:00:00Z',evidence_mode='synthetic');core.validate(r);self.assertEqual(r['payload']['payout']['value'],'0')
  m['stats'].update(settlementPx='100',settlementSetTime='2026-09-30T14:00:00Z')
  new=adapt('us_instrument',json.dumps(m),c,url=r['raw']['url'],received_at='2026-09-30T15:00:00Z',evidence_mode='synthetic',previous=r)
  self.assertEqual(new['payload']['supersedes'],[r['id']]);self.assertIsNone(new['payload']['published_at']);core.validate(new)
  forged=deepcopy(new);envelope=json.loads(forged['raw']['body']);envelope['normalized']['payout']['value']='0'
  forged=core.record('venue',json.dumps(envelope),url=r['raw']['url'],path=['normalized'],received_at=new['received_at'],evidence_mode='synthetic')
  with self.assertRaises(ValueError):core.validate(forged)
  c['instrument_symbol']='symbol'
  with self.assertRaises(ValueError):derive('us_instrument',json.dumps(m),c)
 def test_novig_complete_grade_group_fmv_push_and_remediation(self):
  c=adapter_binding('novig','M','E','A');m=dict(marketId='M',eventId='E',status='SETTLED',voids='FMV',outcomes=[dict(outcomeId='A',status='0.3'),dict(outcomeId='B',status='0.7')])
  p=derive('novig_v3_market',json.dumps(m),c);self.assertEqual(p['payout']['value'],'0.3');self.assertEqual(p['status'],'void')
  m['outcomes'][1]['status']='PUSH'
  with self.assertRaises(ValueError):derive('novig_v3_market',json.dumps(m),c)
  m['voids']='PUSH';m['outcomes'][0]['status']='PUSH';self.assertEqual(derive('novig_v3_market',json.dumps(m),c)['payout']['kind'],'stake_refund')
  m['status']='CLOSED'
  for o in m['outcomes']:o['status']='TBD'
  self.assertEqual(derive('novig_v3_market',json.dumps(m),c)['status'],'pending')
 def test_prophetx_order_decision_does_not_infer_winning_amount(self):
  c=adapter_binding('prophetx','2','3','4');c['order_id']='ORDER'
  m=dict(data=dict(market_id=2,sport_event_id=3,outcome_id=4,order_id='ORDER',winning_status='profit',status='closed',price='1.7',profit='70'))
  p=derive('prophetx_order',json.dumps(m),c);self.assertEqual(p['status'],'settled');self.assertIsNone(p['payout'])
  m['data']['winning_status']='draw';self.assertEqual(derive('prophetx_order',json.dumps(m),c)['payout']['kind'],'stake_refund')
 def test_legacy_adapter_envelope_remains_exact_after_versioned_lineage_repair(self):
  c=adapter_binding('polymarket_us','M','E','long');c.update(instrument_symbol='SYMBOL',instrument_market_id='M',side='long')
  prior=dict(source=c['source'],source_event_id=c['source_event_id'],native=c['native'],contract=c['contract'],target=c['target'],period=c['period'],source_at='2026-09-30T12:00:00Z',id='SYNTHETIC-old-id');c['prior']=prior
  body=json.dumps(dict(symbol='SYMBOL',priceScale='100',stats=dict(settlementPx='100',settlementPreliminary=False,settlementPriceCalculationMethod='SETTLEMENT_PRICE_CALCULATION_METHOD_EVENT_TIER_1',settlementSetTime='2026-09-30T14:00:00Z')))
  old=derive('us_instrument',body,c);self.assertNotIn('decoder_version',old['adapter'])
  envelope=json.dumps(dict(source_adapter=dict(format='us_instrument',original_body=body,binding=c),normalized=old))
  record=core.record('venue',envelope,url='https://example.invalid/SYNTHETIC-legacy-adapter',path=['normalized'],received_at='2026-09-30T15:00:00Z',evidence_mode='synthetic');core.validate(record);self.assertEqual(record['payload'],old)
 def test_kalshi_report_net_fee_and_pre_fee_face_are_separate(self):
  r=kalshi_account_report({'35':'UMS','55':'K','20105':'report','730':'30.60','parties':[{'20109':'P','1705':'PAYOUT','1704':'30.6030','137':'0.00006','138':'USD'}]},ticker='K',party_id='P')
  self.assertEqual(r['yes_fraction'],'0.306');self.assertEqual(r['gross_before_fee_usd'],'30.60306')
  self.assertIsNone(r['correction_lineage'])

class PublicRoutes(__import__('tests.test_source_bindings_routes',fromlist=['Routes']).Routes):
 async def test_public_details_math_download_replay_and_original_reopening(self):
  from urllib.parse import urlencode
  from app.dashboard.math_scenarios import replay as replay_math
  with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('No credential lookup')):
   response=await self.client.get('/api/public-contracts?download=true');self.assertEqual(response.status,200)
   downloaded=await response.json();self.assertFalse(downloaded['collection_authorized'])
   self.assertEqual(downloaded['registry_sha256'],pc.load()['sha256'])
   from app.dashboard.session_projection import stable
   self.assertEqual(downloaded['sha256'],stable({k:v for k,v in downloaded.items() if k!='sha256'}))
   g=next(g for g in self.snapshot['games'] if 'polymarket_us' in g['sources']);query=dict(capture=self.sid,cutoff=self.snapshot['durable_cursor'],game=g['id'])
   response=await self.client.get('/api/public-contracts?'+urlencode(query));self.assertEqual(response.status,200)
   ordinary=await response.json();response=await self.client.get('/api/public-contracts?'+urlencode(dict(query,download='true')))
   self.assertEqual(await response.json(),ordinary)
   c=scenario('polymarket_us',quantity='3.12');c['market_id']=g['sources']['polymarket_us']['market_id'];c['trade_time']=c['calculation_time']='2026-09-30T12:00:00Z'
   req=dict(session=self.sid+'~'+g['id'],hash=self.sid,cutoff=self.snapshot['durable_cursor'],public_contract=dict(version=pc.VERSION,kind='fees',context=c,
     market=dict(id=c['market_id'],isCombo=False,feeCoefficient='0.0695'),instrument=dict(market_id=c['market_id'],source='SYNTHETIC fixed-point instrument',fractionalQtyScale='100')))
   origin=str(self.client.make_url('')).rstrip('/')
   response=await self.client.post('/api/math-scenario',json=req,headers={'Origin':origin});self.assertEqual(response.status,200,await response.text())
   value=await response.json();self.assertEqual(value['public_contract_calculation']['fee_audit']['formula_support'],'implemented');self.assertEqual(replay_math(value),value)
   response=await self.client.get('/api/math-scenario-download?sha256='+value['sha256']);self.assertEqual(await response.json(),value)
   response=await self.client.post('/api/math-scenario',json={'replay':value},headers={'Origin':origin});self.assertEqual(await response.json(),value)
   from app.dashboard.session_history import load
   self.assertEqual(self.snapshot,load(self.folder))
 async def test_public_controls_do_not_authorize_collection(self):
  for q in ('start=true','capture=missing','cutoff=wrong','download=yes','download=true&download=false'):
   response=await self.client.get('/api/public-contracts?'+q);self.assertEqual(response.status,422)

class PayoffSeparation(unittest.TestCase):
 def test_deterministic_arbitrage_without_probability_or_model(self):
  from app.settlement import portfolio
  legs=[dict(cash='0.4',receipts={'A':'1','B':'0'}),dict(cash='0.4',receipts={'A':'0','B':'1'})]
  r=portfolio(legs,['A','B'],complete=True)
  self.assertTrue(r['mathematical_arbitrage']);self.assertEqual(Decimal(r['worst_case_return']),Decimal('.2'));self.assertIsNone(r['expected_net'])

class AdditionalPublicBindings(unittest.TestCase):
 def test_identity_and_typed_metadata_contradictions_are_not_silently_normalized(self):
  r=pc.event_identity(source='kalshi',event_id='KXNBAGAME-26OCT03MIATOR',competition='NBA',participants=['NBA:MIA','NBA:TOR','NBA:MIA'],scheduled_start='2026-10-03T23:00:00Z')
  self.assertEqual(r['status'],'UNBOUND')
  r=pc.us_type(dict(metadata=dict(market_sport_type='basketball_team_full_game_winner',event_subcategory='FOOTBALL')),competition='NBA')
  self.assertEqual(r['status'],'UNBOUND');self.assertIn('conflicts',r['reason'])
 def test_entity_outcome_rules_are_not_achievement_award_share_inheritance(self):
  b=binding('KXNCAAMBACCREG')
  r=pc.entity_outcome(b,achievement_components=[True,None],logic='OR');self.assertEqual(r['yes'],'1')
  self.assertIsNone(pc.entity_outcome(b,achievement_components=[True,None],logic='AND')['yes'])
  self.assertEqual(pc.entity_outcome(b,achieved=True,vacated_before_expiration=True)['yes'],'0')
  self.assertEqual(pc.entity_outcome(b,cancelled=True,official_standings_achievement=False)['yes'],'0')
  self.assertIsNone(pc.entity_outcome(b,cancelled=True)['yes'])
  r=pc.entity_outcome(b,comparative_tied_count=3,comparison_tie_strike=False);self.assertIsNone(r['yes']);self.assertTrue(r['unrounded_comparative_fraction'].startswith('0.333'))
  field=['NCAAB:M:D1:ALA','NCAAB:M:D1:AAMU'];r=pc.championship_payout(b,participant=field[0],field=field,winners=field);self.assertEqual(r['yes'],'1')
  with self.assertRaises(ValueError):pc.award_revision(b,expired=False,eliminated=True,reinstated=True)
 def test_cancellation_allocations_require_eligible_field_and_exact_money(self):
  field=pc.load()['fields']['NFL']['members'];b=binding('KXNFLAFCCHAMP')
  r=pc.championship_payout(b,participant=field[0],field=field,cancellation=True,last_fair={field[0]:'0.8'})
  self.assertIsNone(r['yes'])
  r=pc.championship_payout(b,participant=field[0],field=field,cancellation=True,eligible=field[1:3],last_fair={field[1]:'0.7',field[2]:'0.3'});self.assertEqual(r['yes'],'0')
  with self.assertRaises(ValueError):pc.entity_outcome(binding('KXNCAAMBACCREG'),cancelled=True,venue_fraction=.3)
 def test_all_linked_complete_award_classes_have_scoped_profiles(self):
  catalog=json.loads((ROOT/'app/fixtures/native-scope-bindings-v1.json').read_text())
  for b in catalog['bindings']:
   if b['family']!='futures':continue
   try:row,doc=pc.contract(b)
   except ValueError:continue
   profile=pc.settlement_profile(b);self.assertEqual(profile['actor'],pc.VERSION)
 def test_official_memberships_are_not_current_award_eligibility(self):
  for league,n in [('NBA',30),('MLB',30),('NHL',32),('NFL',32),('NCAAF',138),('NCAAB',365)]:
   r=pc.membership_field(league);self.assertEqual(len(r['field']['members']),n);self.assertFalse(r['award_eligibility_established'])
  self.assertEqual(len(pc.membership_field('NHL','Western')['field']['members']),16)
  self.assertEqual(len(pc.membership_field('MLB','NL')['field']['members']),15)
  with self.assertRaises(ValueError):pc.membership_field('NBA','Eastern')
 def test_retained_awards_without_literal_year_bind_exact_record_and_calendar(self):
  evidence=json.loads((ROOT/'evidence/public-contract-bindings-20260930-v1/public/retained-award-records.json').read_text())
  for association in evidence['associations']:
   n=next(m for m in json.loads(evidence['receipts'][association['source_body_sha256']]['body'])['markets'] if m['ticker']==association['market_id'])
   b=binding(association['series_ticker']);r=pc.award_identity(n,b)
   self.assertEqual(r['status'],'DOCUMENTED_IDENTITY');self.assertEqual(r['season'],'2026')
   if b['series_ticker']=='KXNFLAFCCHAMP':self.assertIsNone(r['predicate']['source_award_calendar_year']);self.assertEqual(len(r['field']),16)
   if b['series_ticker']=='KXNCAAFAAC':self.assertIn(r['participant'],r['field'])
   n['expected_expiration_time']='2028-01-01T00:00:00Z'
   self.assertEqual(pc.award_identity(n,b)['status'],'PARTIAL_AWARD_IDENTITY')
 def test_documented_decimal_odds_and_unresolved_identity_controls(self):
  n=dict(sport_key='baseball_mlb_world_series_winner',bookmakers=[dict(key='synthetic',markets=[dict(key='outrights',outcomes=[dict(name='Athletics',price=8.5)])])])
  self.assertEqual(pc.odds_outright(n,'MLB')['outcomes'][0]['decimal_odds'],'8.5')
  n['bookmakers'][0]['markets'][0]['outcomes'][0]['price']=float('nan')
  with self.assertRaises(ValueError):pc.odds_outright(n,'MLB')
  n=dict(rules_primary='If New York wins the first 5 innings of their game, then the market resolves to Yes.',strike_type='structured',yes_sub_title='New York',custom_strike=dict(baseball_team='NYY'))
  with self.assertRaises(ValueError):pc.descriptor(n,binding('KXMLBF5'),tie_strike_listed=False)
 def test_retained_documented_format_fixtures_all_decode_offline(self):
  fixtures=json.loads((ROOT/'app/fixtures/public-adapter-examples-v1.json').read_text())
  self.assertEqual(fixtures['evidence_mode'],'synthetic')
  for x in fixtures['examples']:
   f=x['format'];body=x['body']
   if f=='us_execution':self.assertEqual(us_execution(body)['quantity'],'3.12');continue
   source=__import__('app.resolution.source_adapters',fromlist=['FORMATS']).FORMATS[f][0]
   if f=='kalshi_market':b=adapter_binding(source,'SYNTHETIC-K','SYNTHETIC-E')
   elif f=='us_instrument':
    b=adapter_binding(source);b.update(instrument_symbol='SYNTHETIC-SYMBOL',instrument_market_id='K',side='long')
   elif f=='us_retail':
    b=adapter_binding(source);b.update(slug='SYNTHETIC-SLUG',slug_market_id='K',side='long')
   elif f=='novig_v3_market':b=adapter_binding(source,'SYNTHETIC-M','SYNTHETIC-E','SYNTHETIC-A')
   elif f=='odds_scores':
    b=adapter_binding(source,'SYNTHETIC-M','SYNTHETIC-ODDS-E');b.update(period='full_game',home_label='SYNTHETIC Home',away_label='SYNTHETIC Away');b['target']['event']=dict(scheduled_start='2026-09-30T00:00:00Z')
   else:
    b=adapter_binding(source,'2','3','4');b['order_id']='SYNTHETIC-ORDER'
   result=derive(f,json.dumps(body),b);self.assertEqual(result['adapter']['kind'],'provider_sporting_result_not_venue_decision' if f=='odds_scores' else 'venue_decision_not_sporting_result')
   if f=='odds_scores':
    self.assertEqual((result['home_score'],result['away_score']),(24,17));self.assertIsNone(result['payout']);self.assertIsNone(result['completion'])
    record=adapt(f,json.dumps(body),b,url='SYNTHETIC://documented-scores',received_at='2026-09-30T03:02:00Z',evidence_mode='synthetic');core.validate(record);self.assertEqual(record['kind'],'sporting')
 def test_us_combo_amendment_and_single_instrument_combo_eligibility(self):
  c=scenario('polymarket_us',price='0.10',quantity='1000');c['trade_time']=c['calculation_time']='2026-09-30T12:00:00Z';c['product']='combo_contract'
  c=bind(c,market=dict(id=c['market_id'],isCombo=True));r=calculate(c);self.assertEqual(Decimal(r['entry_fees']),Decimal('8.88'))
  c['trade_time']=c['calculation_time']='2026-10-01T14:00:00Z';c=bind(c,market=dict(id=c['market_id'],isCombo=True));r=calculate(c);self.assertEqual(Decimal(r['entry_fees']),Decimal('10.19'))
  self.assertEqual(replay(r),r)
  c=scenario('polymarket_us');c['trade_time']=c['calculation_time']='2026-09-30T12:00:00Z'
  c=bind(c,market=dict(id=c['market_id'],feeCoefficient=0.0695,comboEnabled=True,sportsMarketType='basketball_team_full_game_winner'))
  self.assertEqual(calculate(c)['formula_support'],'implemented')
 def test_monthly_risk_volume_and_eastern_calendar(self):
  from app.fees.public_bindings import us_taker_volume
  r=us_taker_volume([dict(fill_id='A',role='taker',action='buy',price='0.1',quantity='1000',trade_time='2026-10-01T03:59:00Z'),dict(fill_id='B',role='taker',action='sell',price='0.9',quantity='1000',trade_time='2026-10-01T04:01:00Z')])
  self.assertEqual(Decimal(r['months']['2026-09']['taker_risk_usd']),100);self.assertEqual(Decimal(r['months']['2026-10']['taker_risk_usd']),100)
 def test_prophetx_tie_scoped_unknown_and_award_reinstatement(self):
  r=pc.prophetx_h1_descriptor(participant='NFL:PIT',selected_id='P',other_id='C')
  _,s=orient_descriptor(dict(competition='NFL',home='NFL:PIT',away='NFL:CLE'),r['descriptor'])
  self.assertEqual([payout(x,dict(representative='1')) for x in s],['1','0']);self.assertEqual([payout(x,dict(representative='0')) for x in s],[None,None])
  r=pc.award_revision(binding('KXSB'),expired=False,eliminated=True,reinstated=True);self.assertFalse(r['correction_edge']);self.assertIsNone(r['successor_market_id'])
 def test_mlb_winner_missing_pitcher_clause_is_not_spread_inheritance(self):
  n=dict(rules_primary='If New York Yankees wins the first 5 innings of their game, then the market resolves to Yes.',strike_type='structured',yes_sub_title='New York Yankees',custom_strike=dict(baseball_team='NYY'))
  d=pc.descriptor(n,binding('KXMLBF5'),tie_strike_listed=False)['descriptor']
  self.assertEqual(d['pitcher_conditions'],'not_specified_in_linked_winner_contract')
  _,s=orient_descriptor(dict(competition='MLB',home='MLB:NYY',away='MLB:BOS'),d);self.assertEqual([payout(x,dict(representative='0')) for x in s],['0.5','0.5'])
 def test_enriched_nba_preseason_uses_exact_source_evidence(self):
  from app.normalization.nba import event_key
  e=dict(competition='NBA',sport='basketball',home='NBA:TOR',away='NBA:MIA',participants={'Toronto Raptors':'NBA:TOR','Miami Heat':'NBA:MIA'},season=None,stage=None,scheduled_start='2026-10-03T23:00:00Z',original_start='2026-10-03T23:00:00Z',schedule_status='scheduled',game_id='SYNTHETIC-exact-public-identity')
  enriched=pc.enrich_event(e,'kalshi','KXNBAGAME-26OCT03MIATOR');self.assertEqual(event_key(enriched)[2],'preseason')
  enriched['home']='NBA:BOS'
  with self.assertRaises(ValueError):event_key(enriched)
