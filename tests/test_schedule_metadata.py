"""Authored metadata witnesses; price clocks provide no schedule authority."""
from copy import deepcopy
from unittest import TestCase
from app.storage.schedule_metadata import VERSION, binding, choose, project, diagnostic
from app.storage.store import hashed


def evidence(event, received='2026-10-17T12:00:00Z', authority='authored-milestone'):
    event=deepcopy(event)
    value=dict(version=VERSION,native_event_id=event['id'],authority=['kalshi','milestone',authority],
        start=event['scheduled_start'],received_at=received,
        proofs=[dict(path='/trade-api/v2/milestones',received_at=received,body_sha256=hashed([authority,received,event['scheduled_start']]))])
    value['revision']=hashed(value);event['schedule_metadata']=value
    return event


class ScheduleMetadata(TestCase):
    def setUp(self):
        self.old=evidence(dict(id='authored-native-event',sport='baseball',competition='MLB',
            home='MLB:CLE',away='MLB:TB',participants={'Cleveland':'MLB:CLE','Tampa Bay':'MLB:TB'},
            scheduled_start='2026-10-18T21:00:00Z',season=None,stage=None))
        self.new=evidence(dict(self.old,scheduled_start='2026-10-18T21:08:00Z'),'2026-10-17T13:00:00Z')
        self.contract=dict(market_identity=dict(scheduled_start=self.old['scheduled_start']),
            comparison_source_metadata=dict(schedule_binding=binding(self.old)))

    def test_revision_is_explicit_detached_and_unknown_context_stays_unknown(self):
        original=deepcopy(self.contract)
        self.assertEqual(choose(self.old,self.new),self.new)
        result=project(self.new,self.contract)
        self.assertEqual(self.contract,original)
        self.assertEqual(result['market_identity']['scheduled_start'],self.new['scheduled_start'])
        audit=result['comparison_source_metadata']['schedule_reconciliation']
        self.assertEqual(audit['original_derived_start'],self.old['scheduled_start'])
        self.assertEqual(result['comparison_source_metadata']['schedule_binding'],original['comparison_source_metadata']['schedule_binding'])
        self.assertNotIn('original_start',self.new)
        self.assertIsNone(self.new['season'])

    def test_out_of_order_metadata_cannot_regress_even_when_price_is_new(self):
        self.assertEqual(choose(self.new,self.old),self.new)
        self.assertEqual(project(self.old,dict(self.contract,market_identity=dict(scheduled_start=self.new['scheduled_start'])) )['market_identity']['scheduled_start'],self.new['scheduled_start'])

    def test_equal_clock_and_unrelated_witnesses_refuse_without_arbitrary_order(self):
        for candidate in (evidence(dict(self.old,scheduled_start=self.new['scheduled_start'])),
                          evidence(self.new,'2026-10-17T14:00:00Z','different-milestone')):
            with self.subTest(candidate=candidate):
                for a,b in ((self.old,candidate),(candidate,self.old)):
                    result=choose(a,b)
                    self.assertIn('schedule_conflict',result)
                    self.assertNotIn('schedule_reconciliation',project(result,self.contract)['comparison_source_metadata'])

    def test_legacy_or_tampered_bindings_never_supply_missing_authority(self):
        for prior in ({},dict(self.contract['comparison_source_metadata']['schedule_binding'],metadata=None)):
            value=deepcopy(self.contract);value['comparison_source_metadata']['schedule_binding']=prior
            self.assertEqual(project(self.new,value),value)
        changed=deepcopy(self.new);changed['schedule_metadata']['received_at']='2026-10-17T14:00:00Z'
        self.assertEqual(project(changed,self.contract),self.contract)

    def test_distinct_native_occurrence_and_doubleheader_number_never_reconcile(self):
        for change in (dict(id='rematch'),dict(game_number=2),dict(original_start='2026-10-18T20:00:00Z'),
                       dict(observed_identity_facts=[dict(id='replacement-game',source_id='other')]),
                       dict(shared_provider_ids={'sportradar':'another-game'})):
            candidate=evidence(dict(self.new,**change),'2026-10-17T14:00:00Z')
            self.assertEqual(project(candidate,self.contract),self.contract)

    def test_precise_missing_fact_diagnostic(self):
        row=dict(self.contract,event=self.new,quote=dict(source=dict(provider='kalshi',native_event_id=self.new['id'],native_market_id='total-10',native_outcome_id='yes')))
        self.assertEqual(diagnostic(row)['reason'],'schedule_binding_unverified')

    def test_malformed_comparison_metadata_stays_with_the_isolated_validator(self):
        broken=dict(self.contract,market_identity=dict(scheduled_start='not-a-date'))
        self.assertEqual(project(self.new,broken),broken)
        self.assertIsNone(diagnostic(dict(broken,event=self.new,quote={})))
