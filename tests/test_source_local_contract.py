"""Authored source-local observations keep unknown comparison context explicit."""
from copy import deepcopy
from unittest import TestCase

from app.comparison.event_links import provider_key
from app.dashboard.current_contract import drain, quotes_of, serialize_steps
from app.dashboard.current_normalized import catalog_from_normalized
from tests.current_fixture import fixture


class SourceLocalContract(TestCase):
    def record(self, league='NBA'):
        raw=fixture()
        quote=deepcopy(raw['events'][0]['groups'][0]['outcomes'][0]['quotes']['kalshi'])
        event=dict(id='syn:source-local-'+league,sport='baseball' if league=='MLB' else 'basketball',
            competition=league,season=None,stage=None,home=league+':HOME',away=league+':AWAY',
            participants={'Authored home':league+':HOME','Authored away':league+':AWAY'},
            scheduled_start=raw['events'][0]['start_at'],title='Authored away at Authored home',
            game_id=None,game_number=None,original_start=None,schedule_status=None)
        quote['source'].update(provider='kalshi',native_event_id=event['id'],
            native_market_id=event['id']+'-HOME',native_outcome_id='yes',native_side='yes')
        market=dict(event=provider_key('kalshi',event),sport=event['sport'],competition=league,
            season=None,stage=None,scheduled_start=event['scheduled_start'],family='moneyline',
            period='full_game',line=None,outcome_set='syn:two-native-outcomes',rules='syn:unknown-scoring')
        selections=[dict(participant=event[role],predicate='win' if role=='home' else 'not_win',
                         signed_line=None,label='Authored home'+(' wins' if role=='home' else ' does not win'))
                    for role in ('home','away')]
        # Native NO is the selected team's complement, not an inferred opponent win.
        selections[1]['participant']=event['home']
        record=dict(event=event,market_identity=market,period_boundary='Original full-game terms; scoring unknown',
            anchor_participant=None,selection=selections[0],outcome_selections=selections,
            quote=quote,orientation_evidence=['syn:explicit-source-local-roles'],verified=False,
            outcome_cardinality=2,event_scope=dict(policy='native-event-unverified-2',source='kalshi',native_event_id=event['id']))
        envelope={k:deepcopy(v) for k,v in raw.items() if k!='events'}
        return envelope,record

    def adapted(self, envelope, record):
        return catalog_from_normalized(envelope,[record],include_profiles=False,
                                       source_rules={},selected_applicability={})

    def validated(self, raw):
        return drain(serialize_steps(raw,allow_synthetic=True,prices_only=True))

    def test_nullable_native_context_preserves_observation_and_never_verifies_it(self):
        for league in ('NBA','MLB'):
            with self.subTest(league=league):
                envelope,record=self.record(league)
                original=deepcopy(record)
                value=self.validated(self.adapted(envelope,record))
                event=value['events'][0]
                self.assertIsNone(event['season']);self.assertIsNone(event['stage'])
                self.assertTrue(event['event_discriminator'].startswith('comparison-provider-occurrence-1:'))
                self.assertEqual(event['start_at'],record['event']['scheduled_start'])
                self.assertEqual({p['role'] for p in event['participants']},{'home','away'})
                quote=quotes_of(event['groups'][0]['outcomes'][0])[0]
                self.assertEqual(quote['source'],record['quote']['source'])
                self.assertEqual(quote['original'],record['quote']['original'])
                self.assertEqual(quote['times'],record['quote']['times'])
                self.assertFalse(quote['binding']['verified']);self.assertFalse(quote['comparison']['eligible'])
                self.assertNotIn('display_group',event['groups'][0])
                self.assertEqual(record,original)

    def test_provider_identity_is_stable_when_context_arrives_without_a_join(self):
        envelope,record=self.record()
        before=self.validated(self.adapted(envelope,record))
        enriched=deepcopy(record)
        for context in (enriched['event'],enriched['market_identity']):
            context.update(season='2026-2027',stage='regular_season')
        after=self.validated(self.adapted(envelope,enriched))
        old_event,new_event=before['events'][0],after['events'][0]
        self.assertEqual(old_event['id'],new_event['id'])
        old=quotes_of(old_event['groups'][0]['outcomes'][0])[0]
        new=quotes_of(new_event['groups'][0]['outcomes'][0])[0]
        self.assertEqual(old['id'],new['id']);self.assertEqual(old['source'],new['source'])
        self.assertEqual(new_event['season'],'2026-2027');self.assertEqual(new_event['stage'],'regular_season')
        verified=deepcopy(enriched);verified['verified']=True
        verified['event_scope']['policy']='native-provider-event-1'
        self.assertEqual(self.validated(self.adapted(envelope,verified))['events'][0]['id'],new_event['id'])
        changed=deepcopy(enriched)
        changed['event']['id']='syn:different-source-event'
        changed['event_scope']['native_event_id']=changed['event']['id']
        changed['quote']['source']['native_event_id']=changed['event']['id']
        changed['market_identity']['event']=provider_key('kalshi',changed['event'])
        self.assertNotEqual(self.adapted(envelope,changed)['events'][0]['id'],new_event['id'])

    def test_absent_optional_context_becomes_null_without_inventing_values(self):
        envelope,record=self.record()
        for context in (record['event'],record['market_identity']):
            context.pop('season');context.pop('stage')
        event=self.validated(self.adapted(envelope,record))['events'][0]
        self.assertIsNone(event['season']);self.assertIsNone(event['stage'])

    def test_nullable_context_does_not_accept_verified_or_shared_bindings(self):
        envelope,record=self.record()
        verified=deepcopy(record);verified['verified']=True
        verified['event_scope']['policy']='native-provider-event-1'
        with self.assertRaisesRegex(ValueError,'unverified source-local'):
            self.adapted(envelope,verified)
        raw=self.adapted(envelope,record)
        q=quotes_of(raw['events'][0]['groups'][0]['outcomes'][0])[0]
        q['binding']['verified']=True
        with self.assertRaisesRegex(ValueError,'verified selection'):
            self.validated(raw)
        raw=self.adapted(envelope,record)
        raw['events'][0]['event_discriminator']='predict-occurrence-1:syn:shared'
        with self.assertRaisesRegex(ValueError,'source-local'):
            self.validated(raw)
        raw=self.adapted(envelope,record)
        raw['events'][0]['event_discriminator']='syn:legacy-event'
        with self.assertRaisesRegex(ValueError,'source-local'):
            self.validated(raw)

    def test_source_identity_roles_schedule_and_context_conflicts_remain_invalid(self):
        for field in ('id','home','scheduled_start'):
            envelope,record=self.record();record['event'][field]=None
            with self.subTest(field=field),self.assertRaises((ValueError,KeyError,TypeError)):
                self.adapted(envelope,record)
        envelope,record=self.record();record['market_identity']['season']='2026-2027'
        with self.assertRaisesRegex(ValueError,'market/event binding'):
            self.adapted(envelope,record)
        envelope,record=self.record();raw=self.adapted(envelope,record)
        raw['events'][0]['participants'][0]['role']='unknown'
        with self.assertRaisesRegex(ValueError,'home and away'):
            self.validated(raw)
        for field in ('season','stage'):
            envelope,record=self.record();raw=self.adapted(envelope,record)
            raw['events'][0][field]=''
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'nonempty'):
                self.validated(raw)
