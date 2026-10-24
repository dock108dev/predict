"""Authored regression cases for current source/contract matching repairs."""
from copy import deepcopy
from datetime import datetime
from unittest import TestCase

from app.collection.native_score_binding import bind as score
from app.collection.v1_comparison import bind
from app.comparison.event_eligibility import assess
from app.comparison.event_links import EventLinks
from app.comparison.occurrence_matching import OccurrenceResolver
from app.dashboard.current_normalized import catalog_from_normalized
from app.dashboard.current_contract import drain, serialize_steps, quotes_of
from tests import test_source_local_contract as local_contract
from tests.test_ev02_occurrence import rows, AT, START, envelope


class MixedContext(TestCase):
    def test_new_shared_context_does_not_erase_old_price_or_promote_contract(self):
        raw,record=local_contract.SourceLocalContract().record('NBA')
        record['event'].update(season='2026-2027',stage='regular_season')
        record['comparison_source_metadata']=dict(comparison_admission=dict(
            supported=False,reason='comparison_context_missing',missing_fields=['season','stage']))
        before=deepcopy(record)
        output=catalog_from_normalized(raw,[record],include_profiles=False,source_rules={},selected_applicability={})
        output=drain(serialize_steps(output,allow_synthetic=True,prices_only=True))
        q=quotes_of(output['events'][0]['groups'][0]['outcomes'][0])[0]
        self.assertEqual(q['original'],record['quote']['original'])
        self.assertEqual(q['times'],record['quote']['times'])
        self.assertEqual(q['source'],record['quote']['source'])
        self.assertFalse(q['binding']['verified'])
        self.assertFalse(q['comparison']['eligible'])
        self.assertEqual(record,before)
        for field in ('season','stage'):
            contradictory=deepcopy(record);contradictory['market_identity'][field]='contradictory'
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'binding conflict'):
                catalog_from_normalized(raw,[contradictory],include_profiles=False,source_rules={},selected_applicability={})

    def test_missing_market_context_needs_explicit_display_refusal(self):
        raw,record=local_contract.SourceLocalContract().record('NBA')
        record['event'].update(season='2026-2027',stage='regular_season')
        with self.assertRaisesRegex(ValueError,'binding conflict'):
            catalog_from_normalized(raw,[record],include_profiles=False,source_rules={},selected_applicability={})


class SourceMappings(TestCase):
    def test_institutional_names_are_shared_without_sharing_native_ids(self):
        from app.collection.admission_enrichment import resolve_team
        for name,cid in [('Sam Houston','NCAAF:NCAA624'),('Appalachian St.','NCAAF:NCAA27'),('Illinois','NCAAF:NCAA301')]:
            with self.subTest(name=name):
                self.assertEqual(resolve_team(dict(name=name,id='authored-unmapped-us-id'),'NCAAF','polymarket_us'),cid)
        self.assertIsNone(resolve_team(dict(name='Illinois',id='70ddf80a-3853-481a-9903-05200c42c955'),'NCAAF','kalshi'))

    def test_winner_uses_structured_team_id_and_source_registry_together(self):
        event=dict(id='authored-ncaaf',competition='NCAAF',identity='resolved',season='2026',stage='regular_season',
            participants={'Appalachian State University':'NCAAF:NCAA27','James Madison University':'NCAAF:NCAA317'},
            home='NCAAF:NCAA27',away='NCAAF:NCAA317',scheduled_start=START)
        native=dict(yes_sub_title='Appalachian St.',custom_strike=dict(football_team='7d548f70-b3f7-480b-9ee9-cd6b600bbffc'),
            rules_primary='If Appalachian St. wins the authored college football game, then the market resolves to Yes.')
        market=dict(id='authored-market',event_id=event['id'],market_type='moneyline',period='full_game',_native=native)
        value=bind(event,market,'kalshi',policy='manual-comparison-2')
        self.assertEqual(value['status'],'BOUND_RAW_PREDICATE')
        self.assertEqual([(p['participant'],p['predicate']) for p in value['predicate']],
            [('NCAAF:NCAA27','win'),('NCAAF:NCAA27','not_win')])
        native['custom_strike']['football_team']='70ddf80a-3853-481a-9903-05200c42c955'
        self.assertEqual(bind(event,market,'kalshi',policy='manual-comparison-2')['status'],'IDENTITY_BLOCKED')

    def test_passive_total_literal_checks_exact_strike_unit_period_and_scope(self):
        native=dict(strike_type='greater',floor_strike='235.5',cap_strike=None,
            rules_primary='If over 235.5 total points are scored in the authored Pro Basketball game, then the market resolves to Yes.')
        scope=dict(sport='NBA',period='full_game',family='total')
        fact=score(native,scope,revised=True)
        self.assertEqual(fact['participant'],'combined');self.assertEqual(fact['line'],'235.5')
        self.assertEqual([p['operator'] for p in fact['outcomes']],['gt','le'])
        for changed in (dict(floor_strike='236.5'),dict(rules_primary=native['rules_primary'].replace('total points','team points')),
                        dict(rules_primary=native['rules_primary'].replace('points','runs')),
                        dict(rules_primary=native['rules_primary'].replace('game','1st half game'))):
            with self.subTest(changed=changed):self.assertIsNone(score(dict(native,**changed),scope,revised=True))
        self.assertIsNone(score(native,dict(scope,period='first_half'),revised=True))
        self.assertIsNone(score(native,dict(scope,family='spread'),revised=True))


class NativeOccurrenceAliases(TestCase):
    def record(self,native,link='main-game'):
        row=rows('kalshi',native)[0]
        row['event']['observed_identity_facts']=[dict(main_game_event_ticker=link)]
        return row

    def test_explicit_main_game_link_joins_families_and_keeps_native_identity(self):
        inputs=[self.record(n) for n in ('main-game','spread-event','total-event')]
        originals=deepcopy(inputs)
        result=OccurrenceResolver(links=EventLinks()).resolve(inputs,clock=AT)
        self.assertEqual(len({r['event']['game_id'] for r in result}),1)
        for before,after in zip(originals,result):
            self.assertEqual(after['quote']['source'],before['quote']['source'])
            self.assertEqual(after['quote']['times'],before['quote']['times'])
            self.assertEqual(after['quote']['occurrence_match']['original_event'],before['event'])
            self.assertEqual(after['quote']['occurrence_match']['method'],'shared_native_event')
        self.assertEqual(inputs,originals)

    def test_other_game_number_role_and_schedule_do_not_inherit_alias(self):
        for change in (dict(game_number=2),dict(scheduled_start='2026-10-15T00:15:00Z'),dict(home='other-team')):
            left=self.record('one');left['event']['game_number']=1
            right=self.record('two');right['event'].update(change)
            result=OccurrenceResolver(links=EventLinks()).resolve([left,right],clock=AT)
            self.assertTrue(all(r['quote']['occurrence_match']['status']=='unresolved' for r in result))
        different=self.record('two','another-main-game')
        result=OccurrenceResolver(links=EventLinks()).resolve([self.record('one'),different],clock=AT)
        self.assertTrue(all(r['quote']['occurrence_match']['status']=='unresolved' for r in result))

    def test_hockey_spelling_has_one_projected_event_and_exact_originals(self):
        inputs=rows()+rows('the_odds_api','aggregate',venue='novig')
        for index,r in enumerate(inputs):
            r['event'].update(competition='NHL',sport='hockey' if index<2 else 'ice_hockey')
            r['market_identity'].update(competition='NHL',sport=r['event']['sport'])
        originals=deepcopy(inputs)
        resolved=OccurrenceResolver(links=EventLinks()).resolve(inputs,clock=AT)
        output=catalog_from_normalized(envelope(),resolved,include_profiles=False,source_rules={},selected_applicability={})
        self.assertEqual(len(output['events']),1)
        for before,after in zip(originals,resolved):
            self.assertEqual(after['quote']['occurrence_match']['original_event'],before['event'])
            self.assertEqual(after['quote']['source'],before['quote']['source'])

    def test_native_family_aliases_do_not_compete_with_shared_provider_witness(self):
        inputs=[self.record(n) for n in ('main-game','spread-event','total-event')]
        inputs+=rows('polymarket_us','us',shared={'sportradar':'explicit-game'})[:1]
        inputs+=rows('the_odds_api','aggregate',venue='novig')[:1]
        result=OccurrenceResolver(links=EventLinks()).resolve(inputs,clock=AT)
        self.assertTrue(all(r['quote']['occurrence_match']['status']=='matched' for r in result))
        self.assertEqual(len({r['event']['game_id'] for r in result}),1)
        self.assertTrue(all(len(r['quote']['occurrence_match']['members'])==5 for r in result))


class PregameEligibility(TestCase):
    def test_boston_missing_overtime_keeps_prices_and_refuses_comparison(self):
        from app.dashboard.comparison_board import entries, gross_comparison
        inputs=rows('kalshi','authored-boston')+rows('polymarket_us','authored-boston-us')
        mapping={'NFL:BUF':'NBA:BOS','NFL:LAR':'NBA:NYK'}
        for r in inputs:
            r['event'].update(sport='basketball',competition='NBA',season='2026-2027',
                home='NBA:NYK',away='NBA:BOS',participants={'Boston Celtics':'NBA:BOS','New York Knicks':'NBA:NYK'})
            r['market_identity'].update(sport='basketball',competition='NBA',season='2026-2027')
            for selection in [r['selection'],*r['outcome_selections']]:selection['participant']=mapping[selection['participant']]
            r['comparison_scope']=dict(overtime='unknown')
            source=r['quote']['source']
            if r['quote']['venue']=='kalshi':
                side='yes' if r['selection']['predicate']=='win' else 'no'
                source.update(native_side=side,native_outcome_id=side)
            else:source['native_side']='Long' if r['selection']['predicate']=='win' else 'Short'
            terms=dict(rules_primary='Authored Boston winner terms with no overtime declaration')
            r['comparison_source_metadata']=dict(native_key=[r['quote']['venue'],*[source[k] for k in
                ('native_event_id','native_market_id','native_outcome_id','native_side')]],
                native_terms=terms,original_wording=dict(terms),series_id='KXNBAGAME',
                native_market_type='basketball_team_full_game_winner')
        raw=catalog_from_normalized(envelope(),inputs,occurrence_resolver=OccurrenceResolver(links=EventLinks()),
            include_profiles=False,source_rules={},selected_applicability={})
        state=drain(serialize_steps(raw,allow_synthetic=True,prices_only=True))
        self.assertEqual(len(entries(state)),4)
        at=datetime.fromisoformat(AT.replace('Z','+00:00'))
        for event,group,quote in entries(state):
            self.assertTrue(quote['original']['value'])
            value=gross_comparison(quote,group,event,state,at)
            self.assertFalse(value['available'])
            self.assertEqual(quote['native_contract']['scope_evidence']['overtime'],'unknown')
            self.assertIn('overtime',quote['native_contract']['scope_evidence']['missing_fields'])

    def test_schedule_passage_never_means_completion_or_settlement(self):
        e=dict(scheduled_start=START)
        self.assertEqual(assess(e,AT)['state'],'scheduled')
        self.assertEqual(assess(e,START)['state'],'scheduled_start_passed')
        for state,expected in [('postponed','postponed'),('final','verified_completed'),('unknown','unknown')]:
            value=assess(dict(e,status=dict(status=state)),AT)
            self.assertFalse(value['eligible']);self.assertEqual(value['state'],expected)
            self.assertNotIn('settlement',value)
        self.assertEqual(assess(dict(e,observed_identity_facts=[dict(status='postponed')]),AT)['state'],'postponed')
        self.assertEqual(assess(dict(status={}),AT)['state'],'unknown')

    def test_phase_and_original_price_aging_obey_source_status(self):
        from app.comparison.source_inputs import _phase
        from app.dashboard.comparison_board import freshness
        r=rows()[0];r['event']['status']=dict(status='postponed')
        at=datetime.fromisoformat(AT.replace('Z','+00:00'))
        self.assertEqual(_phase(r,dict(phase='pregame'),at),'unknown')
        projected=dict(start_at=START)
        r['quote']['occurrence_match']=dict(original_event=r['event'])
        result=freshness(r['quote'],{},projected,at,financial=False)
        self.assertIn('event_postponed',result['reasons'])
        self.assertEqual(result['status'],'historical')
