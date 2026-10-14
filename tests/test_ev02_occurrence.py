"""Independent authored Bills/Rams vectors; never current venue coverage."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from app.comparison.event_links import EventLinks, ProviderEdge, provider_key
from app.comparison.occurrence_matching import OccurrenceResolver
from app.dashboard.current_normalized import catalog_from_normalized
from app.dashboard.current_contract import serialize, packed, quotes_of, validate_snapshot
from app.dashboard.current_incremental import project

AT = '2026-10-11T12:00:00Z'
START = '2026-10-13T00:15:00Z'
HOME = 'NFL:LAR'
AWAY = 'NFL:BUF'


def rows(provider='kalshi', native='authored-k', *, venue=None, binary=True, shared=None, overtime='included'):
    venue=venue or provider
    e=dict(id=native,sport='american_football',competition='NFL',season='2026',stage='regular_season',
           scheduled_start=START,home=HOME,away=AWAY,participants={'Los Angeles Rams':HOME,'Buffalo Bills':AWAY},
           title='Buffalo Bills at Los Angeles Rams')
    if shared:e['shared_provider_ids']=shared
    sels=[dict(participant=AWAY,predicate='win',signed_line=None,label='Buffalo Bills'),
          dict(participant=AWAY if binary else HOME,predicate='not_win' if binary else 'win',
               signed_line=None,label='Buffalo Bills does not win' if binary else 'Los Angeles Rams')]
    out=[]
    for i,sel in enumerate(sels):
        side=('YES','NO') if venue=='kalshi' else ('LONG','SHORT') if venue=='polymarket_us' else ('win','win')
        source=dict(provider=provider,native_event_id=native,native_market_id=native+'-market',
                    native_outcome_id=native+'-'+str(i),native_side=side[i],binding_id='authored-'+str(i),
                    binding_version='authored-predicate-1',native_line=None,quote_side='buy')
        q=dict(id='',revision=1,venue=venue,source=source,
               original=dict(value='0.40' if i==0 else '0.60',units='usd_per_contract',payout='1',
                             payout_units='USD',quantity_units='contracts',role='comparison'),
               times=dict(source_at=AT,received_at=AT,projected_at=AT,source_time_kind='synthetic'),
               state='available',rule_note='Authored tie '+('half' if binary else 'loss')+'; refunds unknown',
               provenance=dict(mode='synthetic',real_source=False,fixture='EV02 authored',sha256='a'*64),
               freshness_policy=dict(version='authored-age',maximum_age_seconds=3600))
        out.append(dict(event=deepcopy(e),market_identity=dict(event=provider_key(provider,e),sport=e['sport'],
                        competition='NFL',season='2026',stage='regular_season',scheduled_start=START,
                        family='moneyline',period='full_game',line=None,outcome_set=native+'-domain',rules=native+'-rules'),
                        period_boundary='Authored full game',comparison_scope=dict(overtime=overtime),
                        anchor_participant=None,selection=deepcopy(sel),quote=q,orientation_evidence=['authored:orientation'],
                        verified=provider=='the_odds_api',outcome_cardinality=2,outcome_selections=deepcopy(sels),
                        result_policy=native+'-payout-policy',event_scope=dict(
                            policy='aggregate-provider-event-2' if provider=='the_odds_api' else 'native-event-unverified-2',
                            source=provider,native_event_id=native)))
    return out


def edge(provider='kalshi', native='authored-k', oid='authored-game'):
    return ProviderEdge(provider,native,oid,'NFL',HOME,AWAY,'b'*64,
                        '2026-10-10T00:00:00Z','2026-10-10T00:00:00Z',
                        '2026-10-14T00:00:00Z','authored','manual_review')


def envelope(revision=1):
    return dict(schema='predict-current-1',mode='synthetic',runtime_id='ev02-authored',state_revision=revision,
                clock_at=AT,projected_at=AT,state='available',events=[],source_status={
                    v:dict(state='available') for v in ('kalshi','polymarket_us','novig','prophetx')})


class OccurrenceCases(unittest.TestCase):
    def resolver(self, **kw):return OccurrenceResolver(links=EventLinks(),**kw)
    def resolve(self, records, resolver=None):return (resolver or self.resolver()).resolve(records,clock=AT)
    def audit(self, record):return record['quote']['occurrence_match']

    def test_shared_ids_reviewed_edges_and_precedence(self):
        a=rows(shared={'sportradar':'authored-shared'})
        b=rows('polymarket_us','authored-us',shared={'sportradar':'authored-shared'})
        joined=self.resolve(a+b)
        self.assertEqual(len({self.audit(r)['occurrence_id'] for r in joined}),1)
        self.assertTrue(all(self.audit(r)['method']=='shared_provider_id' and not self.audit(r)['estimated'] for r in joined))
        links=EventLinks([edge(),edge('polymarket_us','authored-us')])
        joined=OccurrenceResolver(links=links).resolve(rows()+rows('polymarket_us','authored-us'),clock=AT)
        self.assertEqual({self.audit(r)['occurrence_id'] for r in joined},{'authored-game'})
        self.assertEqual(len(joined[0]['quote']['occurrence_link']['edges']),2)

    def test_unattributed_vendor_id_does_not_invent_shared_provider_membership(self):
        a=rows();b=rows('polymarket_us','u')
        for r in a:r['event']['observed_identity_facts']=[dict(source_id='coincident-id')]
        for r in b:r['event']['_native']=dict(sportradarGameId='coincident-id')
        joined=self.resolve(a+b)
        self.assertTrue(all(self.audit(r)['estimated'] for r in joined))
        for r in a+b:r['event']['season']=r['event']['stage']='unverified'
        joined=self.resolve(a+b)
        self.assertIsNone(self.audit(joined[0])['occurrence_id'])
        for r in a:r['event']['observed_identity_facts'][0]['source_provider']='sportradar'
        joined=self.resolve(a+b)
        self.assertTrue(all(self.audit(r)['method']=='shared_provider_id' for r in joined))

    def test_unique_metadata_aliases_and_originals(self):
        a=rows();b=rows('polymarket_us','authored-us')
        for r in b:
            r['event']['away']='alias:BUF';r['event']['participants']['Buffalo Bills']='alias:BUF'
            for s in [r['selection'],*r['outcome_selections']]:s['participant']='alias:BUF'
        originals=deepcopy(a+b)
        joined=self.resolve(a+b,self.resolver(aliases={'alias:BUF':AWAY}))
        self.assertTrue(all(self.audit(r)['estimated'] for r in joined))
        self.assertEqual(len({r['event']['game_id'] for r in joined}),1)
        for original,r in zip(originals,joined):
            self.assertEqual(original['quote']['times'],r['quote']['times'])
            self.assertEqual(original['quote']['source'],r['quote']['source'])
            self.assertEqual(original['quote']['original'],r['quote']['original'])
            self.assertEqual(original['event'],self.audit(r)['original_event'])
        self.assertEqual(originals,a+b)

    def test_repeat_games_doubleheaders_and_ambiguous_candidates(self):
        a=rows();b=rows('polymarket_us','u1');c=rows('polymarket_us','u2')
        joined=self.resolve(a+b+c)
        self.assertTrue(all(self.audit(r)['status']=='unresolved' for r in joined))
        for i,batch in enumerate((b,c),1):
            for r in batch:r['event']['game_number']=i
        for r in a:r['event']['game_number']=1
        joined=self.resolve(a+b+c)
        self.assertEqual(self.audit(joined[0])['occurrence_id'],self.audit(joined[2])['occurrence_id'])
        self.assertIsNone(self.audit(joined[4])['occurrence_id'])

    def test_neutral_reversed_order_roles_conflicts_and_shared_conflict(self):
        a=rows();b=rows('polymarket_us','u')
        for r in b:r['event']['participants']=dict(reversed(list(r['event']['participants'].items())))
        self.assertTrue(all(self.audit(r)['status']=='matched' for r in self.resolve(a+b)))
        for r in b:r['event']['home'],r['event']['away']=AWAY,HOME
        self.assertTrue(all(self.audit(r)['status']=='unresolved' for r in self.resolve(a+b)))
        for r in a+b:r['event']['neutral_venue']=True
        self.assertTrue(all(self.audit(r)['status']=='matched' for r in self.resolve(a+b)))
        for r in b:r['event']['source_participant_roles']=dict(home=HOME,away=AWAY)
        self.assertEqual(self.audit(self.resolve(a+b)[2])['conflicts'],['source_role_or_identity_conflict'])
        for r in a+b:r['event']['shared_provider_ids']={'sportradar':'same'}
        for r in b:r['event']['season']='2027'
        self.assertTrue(all(self.audit(r)['status']=='unresolved' for r in self.resolve(a+b)))

    def test_reschedule_replacement_and_changed_ids_reviewed_continuity(self):
        resolver=self.resolver();a=rows()+rows('polymarket_us','u')
        first=self.resolve(a,resolver)
        for r in a:
            r['event']['scheduled_start']='2026-10-15T00:15:00Z'
            r['market_identity']['scheduled_start']=r['event']['scheduled_start']
        second=self.resolve(a,resolver)
        self.assertEqual(first[0]['event']['game_id'],second[0]['event']['game_id'])
        replacement=rows('polymarket_us','replacement')
        for r in replacement:r['event']['replacement_game_id']='different-game'
        self.assertTrue(all(self.audit(r)['status']=='unresolved' for r in self.resolve(rows()+replacement)))
        links=EventLinks([edge(),edge('polymarket_us','replacement')])
        joined=OccurrenceResolver(links=links).resolve(rows()+replacement,clock=AT)
        self.assertEqual({self.audit(r)['occurrence_id'] for r in joined},{'authored-game'})

    def test_expiry_and_supersession_do_not_resurrect_or_fall_back(self):
        old=edge();new=replace(old,effective_from='2026-10-10T01:00:00Z',effective_until='2026-10-11T00:00:00Z',supersedes=(old.id,))
        joined=OccurrenceResolver(links=EventLinks([old,new])).resolve(rows()+rows('polymarket_us','u'),clock=AT)
        self.assertIsNone(self.audit(joined[0])['occurrence_id'])
        self.assertIn('provider_edge_expired_or_not_effective',self.audit(joined[0])['conflicts'])

    def test_local_reviewed_override_after_incomplete_metadata(self):
        records=rows()+rows('polymarket_us','u')
        for r in records:r['event']['season']='unverified'
        override=EventLinks([edge(),edge('polymarket_us','u')])
        result=self.resolve(records,self.resolver(overrides=override))
        self.assertTrue(all(self.audit(r)['method']=='local_reviewed_override' for r in result))

    def test_missing_actual_context_stays_unknown_after_estimated_join(self):
        a=rows();b=rows('the_odds_api','a',venue='novig',binary=False)
        for r in b:
            r['event']['season']=r['market_identity']['season']='unverified'
            r['event']['stage']=r['market_identity']['stage']='unverified'
        joined=self.resolve(a+b)
        self.assertTrue(self.audit(joined[2])['estimated'])
        self.assertEqual(joined[2]['event']['season'],'unverified')
        self.assertEqual(joined[2]['event']['stage'],'unverified')
        self.assertNotIn('probability',joined[2]['quote'])

    def test_separate_team_binaries_and_stable_projected_ids_after_schedule_change(self):
        records=rows()+rows('polymarket_us','u')
        rams=rows()
        for r in rams:
            r['market_identity']['family']='team_binary'
            r['result_policy']+='-rams'
            r['quote']['source']['native_market_id']+='-rams'
            r['quote']['source']['native_outcome_id']+='-rams'
            for s in [r['selection'],*r['outcome_selections']]:
                s['participant']=HOME;s['label']='Los Angeles Rams' if s['predicate']=='win' else 'Rams does not win'
        records+=rams;resolver=self.resolver()
        first=serialize(catalog_from_normalized(envelope(),records,occurrence_resolver=resolver),allow_synthetic=True)
        for r in records:
            r['event']['scheduled_start']='2026-10-15T00:15:00Z'
            r['market_identity']['scheduled_start']=r['event']['scheduled_start']
        second=serialize(catalog_from_normalized(envelope(),records,occurrence_resolver=resolver),allow_synthetic=True)
        def ids(payload):
            return [(e['id'],[(g['id'],g['display_group']['id'],[(o['id'],[q['id'] for q in quotes_of(o)]) for o in g['outcomes']]) for g in e['groups']]) for e in payload['events']]
        self.assertEqual(ids(first),ids(second))
        self.assertEqual(sum(len(quotes_of(o)) for g in first['events'][0]['groups'] for o in g['outcomes']),6)
        self.assertEqual(len({g['display_group']['id'] for g in first['events'][0]['groups']}),1)

    def test_reviewed_interval_clock_invalidation_and_reproduction(self):
        old=edge();early=replace(old,effective_until='2026-10-11T12:10:00Z')
        resolver=OccurrenceResolver(links=EventLinks([early]))
        raw=catalog_from_normalized(envelope(),rows(),occurrence_resolver=resolver)
        full=serialize(raw,allow_synthetic=True)
        previous,known,bounds,_,_=project(raw,serialize(envelope(),allow_synthetic=True),{}, {},allow_synthetic=True)
        later=deepcopy(raw);later['clock_at']='2026-10-11T12:11:00Z';later['state_revision']=2
        value,_,_,_,metrics=project(later,previous,known,bounds,allow_synthetic=True)
        self.assertEqual(packed(value),packed(serialize(later,allow_synthetic=True)))
        self.assertEqual(metrics['projected_groups'],1)
        quote=next(iter(value['events'][0]['groups'][0]['outcomes'][0]['quotes'].values()))
        self.assertIn('occurrence_link_expired_or_not_effective',quote['comparison']['reasons'])
        self.assertEqual(quote['times'],next(iter(full['events'][0]['groups'][0]['outcomes'][0]['quotes'].values()))['times'])

    def test_group_contracts_periods_projection_and_no_acquisition(self):
        records=rows()+rows('polymarket_us','u')+rows('the_odds_api','a',venue='novig',binary=False)
        resolver=self.resolver()
        with patch('socket.create_connection',side_effect=AssertionError('acquisition forbidden')):
            raw=catalog_from_normalized(envelope(),records,occurrence_resolver=resolver)
            full=serialize(raw,allow_synthetic=True)
            incremental,known,bounds,_,_=project(raw,serialize(envelope(),allow_synthetic=True),{}, {},allow_synthetic=True)
        self.assertEqual(packed(full),packed(incremental));validate_snapshot(full,allow_synthetic=True)
        event=full['events'][0];self.assertEqual(len(full['events']),1)
        self.assertEqual(len(event['groups']),3)  # distinct payout/predicate policies
        self.assertEqual(len({g['display_group']['id'] for g in event['groups']}),1)
        qs=[q for g in event['groups'] for o in g['outcomes'] for q in quotes_of(o)]
        self.assertEqual(len(qs),6);self.assertEqual({q['source']['native_side'] for q in qs},{'YES','NO','LONG','SHORT','win'})
        self.assertEqual({q['revision'] for q in qs},{1})
        again,_,_,_,metrics=project(raw,full,known,bounds,allow_synthetic=True)
        self.assertEqual(packed(full),packed(again));self.assertEqual(metrics['reused_groups'],3)
        for r in records:r['quote']['rule_note']+=' different refund'
        changed=catalog_from_normalized(envelope(2),records,occurrence_resolver=resolver)
        value,_,_,_,metrics=project(changed,full,known,bounds,allow_synthetic=True)
        self.assertEqual(packed(value),packed(serialize(changed,allow_synthetic=True)))
        self.assertEqual(metrics['projected_groups'],3)
        for r in records[-2:]:r['comparison_scope']['overtime']='excluded'
        separated=catalog_from_normalized(envelope(),records,occurrence_resolver=resolver)
        self.assertEqual(len({g['display_group']['id'] for g in separated['events'][0]['groups']}),2)
        for r in records[-2:]:r['market_identity']['period']='first_half'
        separated=catalog_from_normalized(envelope(),records,occurrence_resolver=resolver)
        self.assertEqual(len({g['display_group']['id'] for g in separated['events'][0]['groups']}),2)


if __name__ == '__main__':unittest.main()
