"""Snapshot unknown context never becomes factual admission."""
from copy import deepcopy
from unittest import TestCase
from app.comparison.snapshot_identity import project
from app.comparison.same_outcome import descriptor
from app.comparison.snapshot_math import assumptions


def quote(provider='polymarket_us', event_id='game', family='total', line='135.5', native='yes'):
    selection=dict(participant='combined',predicate='over' if native=='yes' else 'under',signed_line=line)
    if family=='spread':selection.update(participant='home',predicate='cover',signed_line=line)
    if family=='moneyline':selection.update(participant='home',predicate='win',signed_line=None)
    event=dict(id=event_id,competition='NCAAB',sport='basketball',home='home',away='away',
        participants={'Home':'home','Away':'away'},season=None,stage=None,scheduled_start='2026-11-03T00:00:00Z')
    source=dict(provider=provider,native_event_id=event_id,native_outcome_id=native,binding_version='test')
    market=dict(family=family,line=None if family=='moneyline' else line,period='full_game')
    meta=dict(comparison_admission=dict(supported=False,reason='comparison_context_missing',missing_fields=['season','stage']),
        scoring_scope=dict(scoring={'overtime':'unknown'},evidence=[{'overtime':'included'}],conflicts=[]))
    if family!='moneyline':meta['source_predicate']=dict(family=family,line=line,period='full_game',competition='NCAAB',unit='points',
        participant=selection['participant'],outcomes=[dict(native_id='yes',operator='gt'),dict(native_id='no',operator='le')])
    r=dict(event=event,market_identity=market,selection=selection,comparison_source_metadata=meta,
        quote=dict(source=source,venue=provider,provenance={},original=dict(value='0.4',units='usd_per_contract',payout='1',payout_units='USD',quantity_units='contracts')))
    return dict(id=provider+event_id+native,league='NCAAB',original_record=r,game_key=event_id,native_contract={},same_outcome={'supported':False})


class SnapshotIdentity(TestCase):
    def test_unknown_context_literal_predicate_and_strict_unchanged(self):
        q=quote();before=deepcopy(q);r=project([q],{})[0]
        self.assertTrue(r['snapshot_supported']);self.assertEqual(q,before)
        self.assertEqual(r['snapshot_identity']['observed_context'],dict(season=None,stage=None))
        self.assertFalse(r['snapshot_identity']['strict_verified'])
        self.assertEqual(descriptor(q['original_record'],scoring={'overtime':'included'})['reason'],'comparison_context_missing')

    def test_unique_exact_schedule_cross_source(self):
        rows=project([quote(),quote('kalshi','other')],{})
        self.assertEqual(rows[0]['same_outcome']['key'],rows[1]['same_outcome']['key'])
        self.assertEqual(len(rows[0]['snapshot_identity']['members']),2)

    def test_known_context_contradiction_and_duplicate_games(self):
        for field in ['season','stage']:
            a,b=quote(),quote('kalshi','other')
            a['original_record']['event'][field]='a';b['original_record']['event'][field]='b'
            self.assertTrue(all(not r['snapshot_supported'] for r in project([a,b],{})))
        rows=project([quote(),quote('kalshi','one'),quote('kalshi','two')],{})
        self.assertTrue(all(not r['snapshot_supported'] for r in rows))

    def test_schedule_roles_and_shared_id_conflicts(self):
        for change in [{'scheduled_start':'2026-11-03T01:00:00Z'},{'home':'other'}]:
            a,b=quote(),quote('kalshi','other');b['original_record']['event'].update(change)
            rows=project([a,b],{})
            self.assertNotEqual(rows[0]['game_key'],rows[1]['game_key'])
            for q in [a,b]:q['original_record']['event']['shared_provider_ids']={'typed':'same'}
            self.assertTrue(all(not r['snapshot_supported'] for r in project([a,b],{})))

    def test_native_side_line_period_predicate_checks(self):
        a=quote();b=quote(native='no');rows=project([a,b],{})
        self.assertTrue(all(r['snapshot_supported'] for r in rows));self.assertNotEqual(rows[0]['same_outcome']['key'],rows[1]['same_outcome']['key'])
        for field,value in [('line','136.5'),('period','first_half'),('family','spread')]:
            q=quote();q['original_record']['market_identity'][field]=value
            self.assertFalse(project([q],{})[0]['snapshot_supported'])
        q=quote();q['original_record']['quote']['source']['native_outcome_id']='absent'
        self.assertFalse(project([q],{})[0]['snapshot_supported'])
        self.assertTrue(project([quote(family='spread',line='-3.5')],{})[0]['snapshot_supported'])

    def test_winner_equality_only_under_declared_conditional_domain(self):
        q=quote(family='moneyline')
        self.assertFalse(project([q],{})[0]['snapshot_supported'])
        r=project([q],{'scenario':'decisive_only'})[0]
        self.assertTrue(r['snapshot_supported']);self.assertIn('excludes equal',r['snapshot_identity']['equality_basis'])
        self.assertFalse(project([q],{'scenario':'refund_other'})[0]['snapshot_supported'])

    def test_scoring_assumption_cannot_override_observation_or_conflicts(self):
        a=quote();a['original_record']['comparison_source_metadata']['scoring_scope']['evidence']=[]
        self.assertFalse(project([a],{})[0]['snapshot_supported'])
        settings=assumptions({'scoring':'ncaab_full_game_overtime'})[0]
        r=project([a],settings)[0];self.assertTrue(r['snapshot_supported']);self.assertIsNotNone(r['snapshot_identity']['assumption'])
        a['original_record']['comparison_source_metadata']['scoring_scope']['evidence']=[{'overtime':'excluded'}]
        self.assertEqual(project([a],settings)[0]['snapshot_identity']['scoring']['overtime'],'excluded')
