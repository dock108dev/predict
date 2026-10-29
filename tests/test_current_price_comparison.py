"""Authored current-peer selection, exact arithmetic and frozen-input aging."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction
from types import SimpleNamespace
from unittest import TestCase

from app.dashboard.comparison_board import entries, gross_comparison, quote_key, age_gross_comparison
from app.storage.comparison_board import ReadContext
from app.storage.store import stamp
from tests.test_ev09_n01 import AT, retained


class CurrentPriceComparison(TestCase):
    def test_frame_local_identity_reuse_preserves_every_comparison(self):
        cache={}
        for event,group,q in entries(self.state):
            for current_only in (False,True):
                expected=gross_comparison(q,group,event,self.state,self.at,current_only=current_only)
                actual=gross_comparison(q,group,event,self.state,self.at,current_only=current_only,identity_cache=cache)
                self.assertEqual(actual,expected)
        self.assertLessEqual(len(cache),len(entries(self.state)))

    def setUp(self):
        context=ReadContext(SimpleNamespace(db=None),at=AT,frame=dict(epoch='authored-current-peer',
            revision='fixture',records=deepcopy(retained()[0]['records'])))
        self.state=context.observation_bundles()[0]['state_inputs'];self.at=stamp(AT)
        from tests.multisport_fixtures import compatible_winner_equality
        compatible_winner_equality(self.state)
        self.event,self.group,self.selected=next((e,g,q) for e,g,q in entries(self.state) if q['venue']=='novig')
        self.peers=[q for e,g,q in entries(self.state) if q['venue'] in ('prophetx','polymarket_us')
            and q['binding']['selection']==self.selected['binding']['selection']]
        # Outcome ids may be native-specific; comparison's semantic keys govern.
        if len(self.peers)!=2:
            self.peers=[q for e,g,q in entries(self.state) if q['venue'] in ('prophetx','polymarket_us')
                and q['binding']['selection']['participant']==self.selected['binding']['selection']['participant']]
        for _,_,q in entries(self.state):
            # These vectors isolate original-clock policy. Complete-book
            # confirmation currentness has its own independent regressions.
            q.pop('book_confirmation',None)
            q['state']='available';q['times'].update(source_at=(self.at-timedelta(seconds=1)).isoformat(),received_at=self.at.isoformat())
        self.old=next(q for q in self.peers if q['venue']=='prophetx')
        self.current=next(q for q in self.peers if q['venue']=='polymarket_us')
        self.old['original']['value']='3'
        self.old['times'].update(source_at=(self.at-timedelta(days=2)).isoformat(),received_at=self.at.isoformat())

    def compare(self,**kwargs):
        return gross_comparison(self.selected,self.group,self.event,self.state,self.at,**kwargs)

    def test_cheaper_history_preserved_beside_current_peer_with_exact_sign_units(self):
        historical=self.compare();current=self.compare(current_only=True)
        self.assertEqual(historical['comparison_quote_id'],quote_key(self.old))
        self.assertEqual(historical['display_status'],'last_known')
        self.assertEqual(current['comparison_quote_id'],quote_key(self.current))
        self.assertEqual(current['display_status'],'current')
        self.assertEqual(current['unit'],'cents')
        exact=Fraction(int(current['exact']['numerator']),int(current['exact']['denominator']))
        self.assertEqual(exact,(Fraction(self.current['original']['value'])-1/Fraction(self.selected['original']['value']))*100)
        self.assertLess(exact,0)
        self.assertEqual(current['inputs'][0]['times'],self.selected['times'])
        self.assertEqual(current['inputs'][1]['native_side'],self.current['source']['native_side'])

    def test_current_candidate_lowest_price_and_existing_deterministic_tie(self):
        self.old['times']['source_at']=(self.at-timedelta(seconds=1)).isoformat()
        self.assertEqual(self.compare(current_only=True)['comparison_quote_id'],quote_key(self.old))
        self.old['original']['value']='2';self.current['original']['value']='0.5'
        self.assertEqual(self.compare(current_only=True)['comparison_quote_id'],min(quote_key(p) for p in self.peers))

    def test_selected_or_peer_health_expiry_stop_and_unknown_clocks(self):
        for edit in ('selected_expired','peer_expired','peer_clock_unknown','stop','runtime_failure'):
            with self.subTest(edit=edit):
                q=deepcopy(self.selected);p=deepcopy(self.current)
                states={}
                if edit=='selected_expired':self.selected['times']['source_at']=(self.at-timedelta(days=2)).isoformat()
                elif edit=='peer_expired':self.current['times']['source_at']=(self.at-timedelta(days=2)).isoformat()
                elif edit=='peer_clock_unknown':self.current['times']['source_at']=None
                else:states[self.current['venue']]=dict(state='stopped' if edit=='stop' else 'unavailable')
                self.assertFalse(self.compare(current_only=True,source_states=states)['available'])
                self.selected.clear();self.selected.update(q);self.current.clear();self.current.update(p)

    def test_unavailable_reasons_distinguish_stale_missing_and_unsupported_peers(self):
        self.current['times']['source_at']=(self.at-timedelta(days=2)).isoformat()
        expired=self.compare(current_only=True)
        self.assertEqual(expired['reason_code'],'comparison_peers_not_current')
        self.assertIn('source_expired',expired['reason_codes'])
        age_gross_comparison(expired,self.at+timedelta(seconds=1))
        self.assertIn('source_expired',expired['reason_codes'])
        self.selected['times']['source_at']=(self.at-timedelta(days=2)).isoformat()
        self.assertEqual(self.compare(current_only=True)['reason_code'],'comparison_selected_not_current')
        self.selected['times']['source_at']=(self.at-timedelta(seconds=1)).isoformat()
        for peer in self.peers:peer['binding']['verified']=False
        self.assertEqual(self.compare(current_only=True)['reason_code'],'comparison_peer_matching_unsupported')
        for _,_,peer in entries(self.state):
            if peer['venue']!=self.selected['venue'] and peer['binding']['selection']['participant']==self.selected['binding']['selection']['participant']:
                peer['binding']['selection']['predicate']='not_win'
        self.assertEqual(self.compare(current_only=True)['reason_code'],'comparison_peer_missing')
        self.selected['times']['source_at']=(self.at-timedelta(days=2)).isoformat()
        missing=self.compare(current_only=True)
        self.assertEqual(missing['reason_code'],'comparison_selected_not_current')
        self.assertIn('comparison_peer_missing',missing['reason_codes'])
        self.assertIn('source_expired',missing['reason_codes'])

    def test_freshness_boundary_uses_original_source_maximum_age(self):
        self.current['times'].update(source_at=self.at.isoformat(),received_at=self.at.isoformat())
        self.current['freshness_policy']=dict(maximum_age_seconds=15)
        boundary=self.at+timedelta(seconds=15)
        for at,available in ((boundary-timedelta(microseconds=1),True),
                             (boundary,True),(boundary+timedelta(microseconds=1),False)):
            with self.subTest(at=at.isoformat()):
                actual=gross_comparison(self.selected,self.group,self.event,self.state,at,current_only=True)
                self.assertEqual(actual['available'],available)

    def test_original_clock_aging_and_frozen_pair(self):
        self.current['freshness_policy']=dict(maximum_age_seconds=15)
        captured=self.compare(current_only=True);before=deepcopy(captured)
        self.current['original']['value']='0.9999';self.current['times']['source_at']=self.at.isoformat()
        age_gross_comparison(captured,self.at+timedelta(seconds=20))
        self.assertEqual(captured['display_status'],'last_known')
        for key in ('exact','value','comparison_quote_id'):
            self.assertEqual(captured[key],before[key])
        self.assertEqual([i['times'] for i in captured['inputs']],[i['times'] for i in before['inputs']])

    def test_future_candidate_boundary_requires_reselection_in_background(self):
        self.old['times'].update(source_at=(self.at+timedelta(seconds=2)).isoformat(),received_at=(self.at+timedelta(seconds=2)).isoformat())
        current=self.compare(current_only=True)
        self.assertEqual(current['comparison_quote_id'],quote_key(self.current))
        self.assertEqual(stamp(current['selection_valid_until']),self.at+timedelta(seconds=2))
        age_gross_comparison(current,self.at+timedelta(seconds=3))
        self.assertEqual(current['display_status'],'pending')
        self.assertIn('comparison_selection_boundary',current['reason_codes'])
        self.assertEqual(current['comparison_quote_id'],quote_key(self.current))

    def test_candidate_mapping_interval_boundary_cannot_silently_keep_current(self):
        self.old['times']['source_at']=(self.at-timedelta(seconds=1)).isoformat()
        self.old['occurrence_link']=dict(version='predict-occurrence-match-1',edges=['a'*64],
            effective_from=(self.at+timedelta(seconds=2)).isoformat(),effective_until=None)
        current=self.compare(current_only=True)
        self.assertEqual(current['comparison_quote_id'],quote_key(self.current))
        self.assertEqual(stamp(current['selection_valid_until']),self.at+timedelta(seconds=2))
        age_gross_comparison(current,self.at+timedelta(seconds=3))
        self.assertEqual(current['display_status'],'pending')
        self.assertIn('comparison_selection_boundary',current['reason_codes'])
        self.assertEqual(current['comparison_quote_id'],quote_key(self.current))
