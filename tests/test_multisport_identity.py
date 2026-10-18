"""Exact scoring identity across the source/type capability matrix (synthetic)."""
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
import json
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from app.comparison.domain import ExactNumber, ScorePredicate
from app.comparison.same_outcome import selection_identity, record_identity, candidate_identity
from app.comparison.native_scoring_scope import attach
from app.comparison.occurrence_matching import OccurrenceResolver
from app.comparison.event_links import EventLinks
from app.comparison.combined_native import normalize
from tests.multisport_fixtures import SPORTS, FAMILIES, source_case, fake_discovery, current_book
from tests.test_current_multisport_ingress import worker


def equality(treatment='predicate', payout=None):
    return dict(treatment=treatment,payout=payout,refund_fees='unknown' if treatment=='stake_refund' else 'not_applicable',unknown_reason=None)


class ExactOutcomeIdentity(TestCase):
    def identity(self, *, family='spread', participant='NFL:HOME', kind='cover', line='-3.5',
                 operator=None, threshold=None, equal=None, overtime='included', occurrence='new-game', league='NFL'):
        event=dict(competition=league,home='NFL:HOME',away='NFL:AWAY')
        predicate=None if operator is None else dict(domain='combined_score' if family=='total' else 'home_margin',operator=operator,threshold=threshold,subject_id=None)
        return selection_identity(event,family,'full_game',dict(overtime=overtime),
            dict(participant=participant,predicate=kind,signed_line=line),predicate=predicate,
            equality=equal,normal_payout=dict(payout='1',payout_units='USD',quantity_units='contracts'),occurrence=occurrence)

    def test_integer_domain_equivalence_is_proven_but_inclusive_boundaries_differ(self):
        half=self.identity(operator='gt',threshold='3.5',equal=equality('not_feasible'))
        integer=self.identity(operator='ge',threshold='4',equal=equality())
        strict=self.identity(line='-3',operator='gt',threshold='3',equal=equality())
        inclusive=self.identity(line='-3',operator='ge',threshold='3',equal=equality())
        self.assertTrue(half['supported']);self.assertEqual(half['key'],integer['key'])
        self.assertTrue(strict['supported']);self.assertTrue(inclusive['supported'])
        self.assertEqual(strict['key'],half['key']);self.assertNotEqual(strict['key'],inclusive['key'])
        self.assertEqual(json.loads(json.dumps(half['key'])),half['key'])
        self.assertEqual(ScorePredicate('home_margin','gt',ExactNumber('3.5')).integer_key,
            ScorePredicate('home_margin','ge',ExactNumber('4')).integer_key)

    def test_away_handicap_reverses_orientation_and_native_complements_are_explicit(self):
        away=self.identity(participant='NFL:AWAY',line='3.5')
        exact=self.identity(participant='NFL:AWAY',line='3.5',operator='lt',threshold='3.5')
        self.assertEqual(away['key'],exact['key'])
        self.assertNotEqual(away['key'],self.identity()['key'])
        home_no=self.identity(family='moneyline',kind='not_win',line=None,equal=equality())
        away_yes=self.identity(family='moneyline',participant='NFL:AWAY',kind='win',line=None,equal=equality())
        self.assertNotEqual(home_no['key'],away_yes['key'])

    def test_integer_total_refund_and_half_point_loss_remain_different(self):
        over45=self.identity(family='total',participant=None,kind='over',line='45',equal=equality('stake_refund'))
        over455=self.identity(family='total',participant=None,kind='over',line='45.5')
        self.assertTrue(over45['supported']);self.assertTrue(over455['supported'])
        self.assertNotEqual(over45['key'],over455['key'])
        fraction=self.identity(family='total',participant=None,kind='over',line='45',equal=equality('fraction','0.5'))
        self.assertNotEqual(fraction['key'],over45['key'])
        unknown=self.identity(family='total',participant=None,kind='over',line='45')
        self.assertEqual(unknown['reason'],'comparison_equality_missing')

    def test_game_league_scope_and_normal_payout_are_independent_identity_dimensions(self):
        original=self.identity()
        for args in (dict(occurrence='another-game'),dict(league='NCAAF'),dict(overtime='excluded')):
            with self.subTest(args=args):self.assertNotEqual(original['key'],self.identity(**args)['key'])
        self.assertEqual(self.identity(overtime='unknown')['reason'],'comparison_scoring_scope_missing')


class SourceTypeMatrix(IsolatedAsyncioTestCase):
    async def test_every_league_family_pairs_using_own_source_facts_without_event_registry(self):
        paired=0
        with patch('app.comparison.native_scoring_scope.registry',side_effect=AssertionError('No per-game registry')):
            for league in SPORTS:
                for family in FAMILIES:
                    with self.subTest(league=league,family=family):
                        case=source_case(league,family,'identity-'+league+'-'+family)
                        rows=[]
                        for venue in ('kalshi','polymarket_us'):
                            w,published=worker(venue,[league],[family]);fake_discovery(w,[case]);await w.discover()
                            at=datetime.now(timezone.utc).isoformat()
                            catalog=dict(id='generated-catalog',record=dict(source=venue,value=dict(inventory=published[-1])))
                            observation=dict(type='prediction_book',source=venue,observed_at=at,book=current_book(case,venue))
                            values,excluded=normalize(catalog,[dict(id='generated-book',record=dict(retained_at=at,value=dict(observations=[observation])))],at=at)
                            self.assertEqual(excluded,[]);self.assertEqual(len(values),2);rows.extend(values)
                        resolved=OccurrenceResolver(links=EventLinks()).resolve(rows,clock=at)
                        identities={}
                        for row in resolved:
                            row=attach(row,at=at)
                            self.assertEqual(row['comparison_source_metadata']['scoring_scope']['status'],'supported')
                            actual=record_identity(row)
                            self.assertTrue(actual['supported'],actual)
                            self.assertEqual(json.loads(json.dumps(actual['key'])),actual['key'])
                            identities.setdefault(json.dumps(actual['key']),set()).add(row['quote']['venue'])
                            # Dependency neighborhoods use the exact same condition.
                            self.assertTrue(candidate_identity(row)['supported'])
                        common=[venues for venues in identities.values() if len(venues)==2]
                        self.assertEqual(len(common),1 if family=='moneyline' else 2)
                        paired+=len(common)
                        # The display projection must preserve the exact identity
                        # after grouping and SQL-style current-row replay.
                        from types import SimpleNamespace
                        from app.storage.comparison_board import ReadContext, observation_identity
                        from app.dashboard.comparison_board import response
                        from app.comparison.estimated_policy import DEFAULT_POLICY
                        at=datetime.now(timezone.utc).isoformat()
                        context=ReadContext(SimpleNamespace(db=None),at=at,frame=dict(epoch='matrix',revision='matrix-'+league+family,records=rows))
                        bundles=context.observation_bundles()
                        self.assertEqual(len(bundles),1)
                        bundle=bundles[0];bundle['calculation_context']=observation_identity(bundle,context)
                        rendered=response(bundle,None,DEFAULT_POLICY,view='odds',filter='all',at=at)
                        directed=[q for q in rendered['prices'] if q['current_comparison']['available']]
                        self.assertEqual(len(rendered['prices']),4)
                        self.assertEqual(len(directed),2 if family=='moneyline' else 4)
                        self.assertTrue(all(len(q['current_comparison']['input_refs'])==2 for q in directed))
        self.assertEqual(paired,30)

    async def test_missing_equality_retains_price_and_precise_comparison_reason(self):
        case=source_case('NBA','total','unknown-integer',line='45')
        w,published=worker('polymarket_us',['NBA'],['total']);fake_discovery(w,[case]);await w.discover()
        at=datetime.now(timezone.utc).isoformat();observation=dict(type='prediction_book',source='polymarket_us',observed_at=at,book=current_book(case,'polymarket_us'))
        rows,excluded=normalize(dict(id='generated-catalog',record=dict(source='polymarket_us',value=dict(inventory=published[-1]))),[dict(id='generated-book',record=dict(retained_at=at,value=dict(observations=[observation])))],at=at)
        self.assertEqual(excluded,[]);self.assertEqual(len(rows),2)
        for row in rows:
            self.assertEqual(row['quote']['original']['value'],'0.51')
            self.assertEqual(candidate_identity(row)['reason'],'comparison_equality_missing')
            self.assertEqual(row['comparison_source_metadata']['same_outcome']['reason'],'comparison_equality_missing')

    async def test_winner_without_own_tie_equality_fact_keeps_price_without_comparison(self):
        case=source_case('NBA','moneyline','unknown-winner-equality')
        for venue in ('kalshi','polymarket_us'):
            field='rules_secondary' if venue=='kalshi' else 'description'
            case['markets'][venue][field]=case['markets'][venue][field].split(' If the game ends in a tie,')[0]
        case['events']['polymarket_us']['markets']=[deepcopy(case['markets']['polymarket_us'])]
        for venue in ('kalshi','polymarket_us'):
            w,published=worker(venue,['NBA'],['moneyline']);fake_discovery(w,[case]);await w.discover()
            at=datetime.now(timezone.utc).isoformat()
            observation=dict(type='prediction_book',source=venue,observed_at=at,book=current_book(case,venue))
            rows,excluded=normalize(dict(id='generated-catalog',record=dict(source=venue,value=dict(inventory=published[-1]))),
                [dict(id='generated-book',record=dict(retained_at=at,value=dict(observations=[observation])))],at=at)
            self.assertEqual(excluded,[]);self.assertEqual(len(rows),2)
            for row in rows:
                self.assertEqual(row['quote']['original']['value'],'0.51')
                self.assertEqual(row['comparison_source_metadata']['same_outcome']['reason'],'comparison_equality_missing')

    async def test_conflicting_source_fact_or_display_line_withholds_only_comparison(self):
        case=source_case('NBA','spread','conflicting-source-facts')
        w,published=worker('kalshi',['NBA'],['spread']);fake_discovery(w,[case]);await w.discover()
        at=datetime.now(timezone.utc).isoformat()
        observation=dict(type='prediction_book',source='kalshi',observed_at=at,book=current_book(case,'kalshi'))
        rows,_=normalize(dict(id='generated-catalog',record=dict(source='kalshi',value=dict(inventory=published[-1]))),
            [dict(id='generated-book',record=dict(retained_at=at,value=dict(observations=[observation])))],at=at)
        original=rows[0]
        for field in ('line','participant','operator','native_side','family','period','league','unit','source_threshold'):
            with self.subTest(field=field):
                row=deepcopy(original);fact=row['comparison_source_metadata']['source_predicate']
                if field=='line':row['selection']['signed_line']='-999.5'
                elif field=='participant':row['selection']['participant']=row['event']['away']
                elif field=='operator':fact['outcomes'][0]['operator']='lt'
                elif field=='native_side':fact['outcomes'][0]['native_id']='another-native-side'
                elif field=='family':fact['family']='total'
                elif field=='period':fact['period']='first_half'
                elif field=='league':fact['competition']='NCAAB'
                elif field=='source_threshold':fact['source_threshold']='999.5'
                else:fact['unit']='runs'
                before=deepcopy(row['quote']);attached=attach(row,at=at)
                actual=candidate_identity(attached)
                self.assertFalse(actual['supported'],actual)
                self.assertTrue(actual['reason'].startswith('comparison_predicate_'))
                self.assertEqual(attached['quote'],before)
