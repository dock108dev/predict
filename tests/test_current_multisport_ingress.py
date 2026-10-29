"""General native transport/admission/scheduling; all observations are synthetic."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from app.collection.current_native import NativeWorker, balanced_markets
from app.collection.current_policy import DEFAULT, validate, native_scope, native_markets, aggregate_scope, aggregate_markets
from app.collection.admission_enrichment import us_score
from app.collection.public_contracts import us_type
from tests.multisport_fixtures import SPORTS, FAMILIES, source_case, fake_discovery, current_book


def worker(venue, sports=SPORTS, families=FAMILIES, **limits):
    published=[]
    config=validate(dict(deepcopy(DEFAULT),native_sports=list(sports),native_families=list(families),**limits))
    service=SimpleNamespace(config=config,dispatch=True,catalog=lambda v,c:published.append(deepcopy(c)),
        issue=lambda *a:None,source_state=lambda *a:None)
    return NativeWorker(service,venue),published


class AdmissionDiagnostics(unittest.TestCase):
    def test_existing_score_facts_and_exact_identity_blockers_are_retained(self):
        from app.collection.current_native import identity_diagnostics
        markets=[]
        for sport in ('NBA','MLB'):
            for fam in ('spread','total'):
                mid=sport+'-'+fam
                markets.append(dict(id=mid,exclusion='native_scope_predicate_review_required',
                    v1_raw_binding=dict(status='IDENTITY_BLOCKED',predicate=['combined','45.5',[]],
                        source_predicate=dict(family=fam,line='45.5'),
                        blockers=['Exact game identity facts unavailable: season, stage'])))
        markets.append(dict(id='winner-selected',v1_raw_binding=dict(status='IDENTITY_BLOCKED',
            predicate=[dict(native_id='yes',participant='NBA:BOS',predicate='win')],
            blockers=['Exact game identity facts unavailable: season, stage'])))
        markets.append(dict(id='line-unparsed',exclusion='native_scope_predicate_review_required',
            v1_raw_binding=dict(status='IDENTITY_BLOCKED',predicate=None,
                blockers=['Exact literal score/outcome predicate or canonical participant unavailable'])))
        entries,omitted=identity_diagnostics(dict(events=[],markets=markets),['winner-selected'])
        self.assertEqual(omitted,0);self.assertEqual(entries[0]['id'],'winner-selected')
        for entry in entries:
            self.assertEqual(entry['source_predicate_present'],entry['id'] not in ('winner-selected','line-unparsed'))
            self.assertEqual(entry['predicate_present'],entry['id']!='line-unparsed')
            self.assertTrue(entry['binding_blockers'])
        self.assertTrue(all(m.get('exclusion')=='native_scope_predicate_review_required' for m in markets if m['id']!='winner-selected'))

    def test_diagnostics_have_fixed_byte_and_entry_bounds(self):
        from app.collection.current_native import identity_diagnostics
        import json
        markets=[dict(id='market-'+str(i),exclusion='native_scope_predicate_review_required',
            v1_raw_binding=dict(status='IDENTITY_BLOCKED',blockers=['missing '+('x'*250)]*6)) for i in range(512)]
        entries,omitted=identity_diagnostics(dict(events=[],markets=markets),['market-511'])
        self.assertEqual(entries[0]['id'],'market-511')
        self.assertLessEqual(len(entries),200)
        self.assertLessEqual(len(json.dumps(entries,separators=(',',':')).encode()),24*1024)
        self.assertEqual(len(entries)+omitted,512)
        self.assertGreater(omitted,0)


class Configuration(unittest.TestCase):
    def test_legacy_fallback_and_explicit_native_transition_preserve_aggregate_request_identity(self):
        legacy=dict(deepcopy(DEFAULT),sports=['NFL'],families=['moneyline'],aggregate_sports=[])
        legacy.pop('native_sports');legacy.pop('native_families')
        before=validate(legacy)
        after=validate(dict(before,native_sports=list(SPORTS),native_families=list(FAMILIES)))
        self.assertEqual(native_scope(before),['NFL']);self.assertEqual(native_markets(before),['moneyline'])
        self.assertEqual(native_scope(after),list(SPORTS));self.assertEqual(native_markets(after),list(FAMILIES))
        self.assertEqual(aggregate_scope(before),aggregate_scope(after));self.assertEqual(aggregate_markets(before),aggregate_markets(after))
        self.assertEqual({k:v for k,v in before.items() if not k.startswith('native_')},
            {k:v for k,v in after.items() if not k.startswith('native_')})
        pinned=validate(dict(after,aggregate_sports=['MLB']))
        self.assertEqual(aggregate_scope(pinned),['MLB']);self.assertEqual(aggregate_markets(pinned),('h2h',))
        for key,value in (('native_sports',['NFL','NFL']),('native_sports',['soccer']),('native_families',['futures'])):
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate(dict(after,**{key:value}))

    def test_league_and_family_subscription_round_robin_share_one_cap(self):
        events={};markets=[]
        for sport in SPORTS:
            for family in FAMILIES:
                eid=sport+'-'+family;events[eid]=dict(competition=sport)
                markets.extend(dict(id=eid+'-'+str(i),event_id=eid,market_type=family) for i in range(6))
        seen=set()
        for offset in range(18):
            chosen=balanced_markets(markets,2,list(FAMILIES),events=events,offset=offset)
            self.assertEqual(len(chosen),2)
            seen.update((events[m['event_id']]['competition'],m['market_type']) for m in chosen)
        self.assertEqual(seen,{(s,f) for s in SPORTS for f in FAMILIES})


class NativeMatrix(unittest.IsolatedAsyncioTestCase):
    async def test_generated_source_type_matrix_uses_real_discovery_and_admission(self):
        for sport in SPORTS:
            for family in FAMILIES:
                for venue in ('kalshi','polymarket_us'):
                    with self.subTest(sport=sport,family=family,venue=venue):
                        w,published=worker(venue,[sport],[family])
                        cases=[];calls=fake_discovery(w,cases)
                        observed_pages=[];get=w.get
                        async def retained_get(*args,**kwargs):
                            result=await get(*args,**kwargs)
                            observed_pages.extend(deepcopy(w.pages))
                            return result
                        w.get=retained_get
                        await w.discover()  # No game exists when the worker starts.
                        self.assertEqual(w.markets,{})
                        case=source_case(sport,family,'after-start-'+sport+'-'+family)
                        cases.append(case)
                        await w.discover()
                        self.assertEqual(len(w.markets),1)
                        market=published[-1]['markets'][0];binding=market['v1_raw_binding']
                        self.assertEqual((market['market_type'],market['period']),(family,'full_game'))
                        self.assertEqual(binding['status'],'BOUND_RAW_PREDICATE',binding['blockers'])
                        self.assertEqual(binding['identity']['competition'],sport)
                        # Exercise the actual ordinary ingress normalization,
                        # including phase, native input and scoring metadata.
                        from app.comparison.combined_native import normalize
                        at=datetime.now(timezone.utc).isoformat()
                        catalog=dict(id='fake-catalog',record=dict(source=venue,value=dict(inventory=published[-1])))
                        observations=[dict(type='prediction_book',source=venue,observed_at=at,book=current_book(case,venue))]
                        rows,excluded=normalize(catalog,[dict(id='fake-book',record=dict(retained_at=at,value=dict(observations=observations)))],at=at,include_missing=True)
                        self.assertEqual(excluded,[])
                        self.assertEqual(len(rows),2)
                        from app.storage.schedule_metadata import witness
                        schedule=witness(rows[0]['event'])
                        self.assertIsNotNone(schedule)
                        self.assertEqual(schedule['start'],case['event']['scheduled_start'])
                        self.assertTrue(all(proof['body_sha256'] in {page['body_sha256'] for page in observed_pages}
                            for proof in schedule['proofs']))
                        self.assertTrue(all(proof['body_sha256'] in {proof['body_sha256'] for proof in rows[0]['event']['provenance']}
                            for proof in schedule['proofs']))
                        self.assertTrue(all(r['comparison_source_metadata']['phase']=='pregame' for r in rows))
                        self.assertTrue(all(r['comparison_source_metadata']['scoring_scope']['status']=='supported' for r in rows))
                        self.assertTrue(all(r['comparison_source_metadata']['same_outcome']['reason'] is None for r in rows))
                        self.assertTrue(all(r['comparison_source_metadata']['source_predicate'] is not None for r in rows) if family!='moneyline' else True)
                        self.assertTrue(all('UNSEEN-' in c['events']['kalshi']['event_ticker'] for c in cases))
                        self.assertLessEqual(len(calls),DEFAULT['discovery_pages'])

    async def test_recurring_shared_caps_are_fair_across_leagues_and_families(self):
        cases=[source_case(s,f,s+'-'+f) for s in SPORTS for f in FAMILIES]
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                w,_=worker(venue,events_per_source=2,markets_per_source=2)
                calls=fake_discovery(w,cases);seen=set()
                for _ in range(2):
                    before=len(calls);await w.discover()
                    self.assertLessEqual(len(calls)-before,DEFAULT['discovery_pages'])
                    self.assertEqual(len(w.markets),len(cases))
                    events={e['id']:e for e in w.catalog['events']}
                    seen.update((events[m['event_id']]['competition'],m['market_type']) for m in w.catalog['markets'] if m['id'] in w.markets)
                self.assertEqual(seen,{(s,f) for s in SPORTS for f in FAMILIES})
                for key in ('requests_per_source','connections_per_source','source_bytes','rediscovery_seconds','discovery_pages'):
                    self.assertEqual(w.config[key],DEFAULT[key])

    async def test_nonempty_listings_with_omitted_metadata_are_budget_limited_not_empty(self):
        from app.comparison.coverage import CoverageLedger
        cases=[source_case(s,f,'capacity-'+s+'-'+f) for s in SPORTS for f in FAMILIES]
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                w,_=worker(venue,events_per_source=2,markets_per_source=2)
                w.service.coverage=CoverageLedger({venue:list(SPORTS)},FAMILIES)
                fake_discovery(w,cases);await w.discover()
                limited=[]
                for finding in w.findings:
                    if not finding.get('queried') or not finding.get('rows'):continue
                    for family in ([finding['family']] if finding['family'] else FAMILIES):
                        latest=w.service.coverage.family_observations[(finding['sport'],venue,family)]['latest']
                        self.assertNotEqual(latest['status'],'no_offerings_returned')
                        self.assertNotEqual(latest['reason'],'query_empty')
                        if latest['status']=='not_checked':
                            limited.append(latest)
                            self.assertEqual(latest['reason'],'query_capacity')
                            self.assertIsNone(latest['offered']['markets']);self.assertIsNone(latest['offered']['quotes'])
                self.assertEqual(limited,[])
                # A genuinely empty bounded source listing retains its meaning.
                w,_=worker(venue,['NFL'],['moneyline'])
                w.service.coverage=CoverageLedger({venue:['NFL']},['moneyline'])
                fake_discovery(w,[]);await w.discover()
                latest=w.service.coverage.family_observations[('NFL',venue,'moneyline')]['latest']
                self.assertEqual((latest['status'],latest['reason']),('no_offerings_returned','query_empty'))

    async def test_known_peer_priority_stays_inside_fair_league_cells(self):
        at=datetime.now(timezone.utc)
        early=source_case('NFL','moneyline','early-no-peer',clock=at)
        peer=source_case('NFL','moneyline','later-known-peer',clock=at+timedelta(hours=1))
        nba=source_case('NBA','moneyline','other-league',clock=at)
        other,catalogs=worker('polymarket_us',['NFL'],['moneyline'])
        fake_discovery(other,[peer]);await other.discover()
        w,_=worker('kalshi',['NFL','NBA'],['moneyline'],markets_per_source=2)
        w.service.sink=SimpleNamespace(reducer=SimpleNamespace(inventory={'polymarket_us':catalogs[-1]}))
        fake_discovery(w,[early,peer,nba]);await w.discover()
        selected=set(w.markets)
        self.assertIn(peer['markets']['kalshi']['ticker'],selected)
        self.assertIn(nba['markets']['kalshi']['ticker'],selected)
        self.assertIn(early['markets']['kalshi']['ticker'],selected)
        self.assertEqual(w.metrics['known_peer_priority_markets'],1)
        for _ in range(3):
            await w.discover();selected.update(w.markets)
            self.assertEqual(len(w.markets),3)
        self.assertIn(early['markets']['kalshi']['ticker'],selected)

    async def test_recurring_listing_pages_reach_new_events_after_a_busy_first_page(self):
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                cases=[source_case('NFL','moneyline','first-page-'+str(i)) for i in range(6)]
                nba=source_case('NBA','moneyline','other-cell');cases.append(nba)
                w,published=worker(venue,['NFL','NBA'],['moneyline'])
                calls=fake_discovery(w,cases);await w.discover()
                unseen=source_case('NFL','moneyline','new-after-start-page-two')
                cases.append(unseen)
                before=len(calls);await w.discover()
                events={e['id'] for e in published[-1]['events']}
                expected=unseen['events'][venue].get('event_ticker',unseen['events'][venue].get('id'))
                self.assertIn(expected,events)
                self.assertTrue(any(m.raw.ref.event_id==expected for m in w.markets.values()))
                listing_calls=[c for c in calls[before:] if c['field']=='events']
                self.assertEqual(len(listing_calls),2 if venue=='kalshi' else 3)
                nfl=next(c for c in listing_calls if c['params'].get('series_ticker')=='KXNFLGAME' or c['params'].get('tagSlug')=='nfl')
                self.assertEqual(nfl['params'].get('cursor') if venue=='kalshi' else nfl['params'].get('offset'),
                    None if venue=='kalshi' else 0)
                first_nfl=next(c for c in calls[:before] if c['field']=='events' and
                    (c['params'].get('series_ticker')=='KXNFLGAME' or c['params'].get('tagSlug')=='nfl'))
                self.assertEqual({k:v for k,v in nfl['params'].items() if k not in ('cursor','offset')},
                    {k:v for k,v in first_nfl['params'].items() if k not in ('cursor','offset')})
                finding=next(f for f in w.findings if f['sport']=='NFL')
                self.assertTrue(finding['traversal_exhausted'])
                self.assertLessEqual(len(calls)-before,DEFAULT['discovery_pages'])
                self.assertIn(nba['markets'][venue].get('ticker',nba['markets'][venue].get('id')),w.markets)
                # A completed traversal resets on the next normal due pass.
                before=len(calls);await w.discover()
                nfl=next(c for c in calls[before:] if c['field']=='events' and
                    (c['params'].get('series_ticker')=='KXNFLGAME' or c['params'].get('tagSlug')=='nfl'))
                self.assertEqual(nfl['params'].get('cursor','') if venue=='kalshi' else nfl['params']['offset'],'' if venue=='kalshi' else 0)

    async def test_total_without_game_id_uses_only_observed_embedded_market_locator(self):
        case=source_case('NHL','total','no-game-id');case['events']['polymarket_us'].pop('gameId')
        w,_=worker('polymarket_us',['NHL'],['total']);calls=fake_discovery(w,[case]);await w.discover()
        self.assertEqual(len(w.markets),1)
        self.assertEqual(calls[-1]['path'],'/v1/events/'+case['events']['polymarket_us']['id'])

    async def test_missing_predicate_keeps_native_total_subscribable(self):
        case=source_case('NBA','total','unknown-predicate')
        case['markets']['polymarket_us']['description']='This full game total has unavailable exact predicate wording. Full game includes overtime.'
        case['events']['polymarket_us']['markets']=[deepcopy(case['markets']['polymarket_us'])]
        w,published=worker('polymarket_us',['NBA'],['total']);fake_discovery(w,[case]);await w.discover()
        self.assertEqual(len(w.markets),1)
        self.assertEqual(published[-1]['markets'][0]['v1_raw_binding']['status'],'IDENTITY_BLOCKED')
        self.assertIn('Exact signed line',published[-1]['markets'][0]['v1_raw_binding']['blockers'][0])
        from app.comparison.combined_native import normalize
        from app.comparison.same_outcome import record_identity
        at=datetime.now(timezone.utc).isoformat()
        observations=[dict(type='prediction_book',source='polymarket_us',observed_at=at,
            book=current_book(case,'polymarket_us',price='0.537'))]
        rows,excluded=normalize(dict(id='fake-catalog',record=dict(source='polymarket_us',value=dict(inventory=published[-1]))),
            [dict(id='fake-book',record=dict(retained_at=at,value=dict(observations=observations)))],at=at,include_missing=True)
        self.assertEqual(excluded,[]);self.assertEqual(len(rows),2)
        for row in rows:
            self.assertEqual(row['quote']['original']['value'],'0.537')
            self.assertEqual(row['quote']['source']['native_market_id'],case['markets']['polymarket_us']['id'])
            self.assertEqual(row['comparison_source_metadata']['original_wording']['description'],case['markets']['polymarket_us']['description'])
            self.assertFalse(row['verified'])
            self.assertEqual(row['comparison_source_metadata']['same_outcome']['reason'],'comparison_predicate_missing')
            self.assertIsNone(row['comparison_source_metadata']['same_outcome']['predicate'])
            self.assertEqual(record_identity(row)['reason'],'comparison_predicate_missing')
        from app.dashboard.current_normalized import catalog_from_normalized
        from app.dashboard.current_state import unavailable
        from app.dashboard.current_contract import serialize
        from app.comparison.occurrence_matching import OccurrenceResolver
        envelope=unavailable();envelope.update(clock_at=at,projected_at=at)
        envelope['source_status']['polymarket_us']['state']='available'
        rendered=serialize(catalog_from_normalized(envelope,rows,occurrence_resolver=OccurrenceResolver(),include_profiles=False))
        quotes=[q for e in rendered['events'] for g in e['groups'] for o in g['outcomes'] for q in o['quotes'].values()]
        self.assertEqual(len(quotes),2)
        self.assertTrue(all(q['original']['value']=='0.537' and not q['binding']['verified'] for q in quotes))
        self.assertTrue(all(q['native_contract']['same_outcome']['reason']=='comparison_predicate_missing' for q in quotes))

    async def test_missing_integer_equality_keeps_both_original_prices_visible(self):
        from app.comparison.combined_native import normalize
        from app.comparison.same_outcome import record_identity
        case=source_case('MLB','total','unknown-equality',line='45')
        w,published=worker('polymarket_us',['MLB'],['total']);fake_discovery(w,[case]);await w.discover()
        at=datetime.now(timezone.utc).isoformat()
        observations=[dict(type='prediction_book',source='polymarket_us',observed_at=at,
            book=current_book(case,'polymarket_us',price='0.491'))]
        rows,excluded=normalize(dict(id='fake-catalog',record=dict(source='polymarket_us',value=dict(inventory=published[-1]))),
            [dict(id='fake-book',record=dict(retained_at=at,value=dict(observations=observations)))],at=at,include_missing=True)
        self.assertEqual(excluded,[]);self.assertEqual(len(rows),2)
        for row in rows:
            self.assertEqual(row['quote']['original']['value'],'0.491')
            self.assertEqual(row['comparison_source_metadata']['same_outcome']['reason'],'comparison_equality_missing')
            self.assertIn('equality',record_identity(row)['missing_fields'])

    async def test_unqualified_semantics_do_not_block_raw_subscription(self):
        for venue in ('kalshi','polymarket_us'):
            case=source_case('NCAAB','total','missing-schedule')
            if venue=='kalshi':case['milestone']['type']='unrecognized_schedule_kind'
            else:case['events'][venue]['teams'][0]['league']='nba'
            w,_=worker(venue,['NCAAB'],['total']);fake_discovery(w,[case]);await w.discover()
            self.assertTrue(w.markets)
            self.assertTrue(any(m.get("exclusion") or m.get("v1_raw_binding",{}).get("status")!="BOUND_RAW_PREDICATE" for m in w.catalog["markets"]))


class Equality(unittest.TestCase):
    def test_explicit_native_sport_and_coarse_family_conflicts_reject(self):
        for sport in SPORTS:
            case=source_case(sport,'spread','conflict-'+sport)
            native=case['markets']['polymarket_us']
            native['marketType']='moneyline'
            rejected=us_type(native,competition=sport)
            self.assertEqual(rejected['status'],'UNBOUND');self.assertIn('families conflict',rejected['reason'])
        case=source_case('NHL','total','sport-conflict')
        native=case['markets']['polymarket_us'];native['metadata']=dict(event_subcategory='FOOTBALL')
        rejected=us_type(native,competition='NHL')
        self.assertEqual(rejected['status'],'UNBOUND');self.assertIn('sport conflicts',rejected['reason'])

    def test_integer_total_unknown_predicate_and_refund_are_distinct(self):
        for sport in SPORTS:
            case=source_case(sport,'total','integer-'+sport,line='45')
            native=case['markets']['polymarket_us']
            event=dict(competition=sport,participants={t['name']:cid for t,cid in zip(case['events']['polymarket_us']['teams'],(case['event']['home'],case['event']['away']))})
            locator=us_type(native,competition=sport)
            unknown=us_score(native,locator,event)
            self.assertEqual(unknown['equality_treatment'],'unknown')
            self.assertIn('equality',unknown['missing'][0])
            native['description']+=' Equality is settled as No.'
            predicate=us_score(native,locator,event)
            self.assertEqual(predicate['equality_treatment'],'predicate');self.assertEqual(predicate['outcomes'][1]['operator'],'le')
            native['description']=native['description'].replace(' Equality is settled as No.','')
            native['description']+=' If the total is exactly 45 '+unknown['unit']+', both sides are refunded.'
            refund=us_score(native,locator,event)
            self.assertEqual(refund['equality_treatment'],'refund');self.assertEqual(refund['outcomes'][1]['operator'],'lt')


class AggregateHold(unittest.IsolatedAsyncioTestCase):
    async def test_native_scope_transition_does_not_dispatch_or_mutate_held_aggregate(self):
        from tests.test_current_aggregate import SchedulerTests
        fixture=SchedulerTests(methodName='test_running_app_without_tabs_dispatches')
        await fixture.asyncSetUp()
        try:
            await fixture.scheduler.step()  # Fake initial accounting evidence only.
            fixture.q.pause('owner_hold')
            before=deepcopy(fixture.q._read());calls=deepcopy(fixture.wire.calls)
            request_scope=(aggregate_scope(fixture.service.config),aggregate_markets(fixture.service.config))
            fixture.service.config=validate(dict(fixture.service.config,native_sports=list(SPORTS),native_families=list(FAMILIES)))
            from app.collection.current_quota import QuotaStop
            with self.assertRaises(QuotaStop):await fixture.scheduler.step()
            self.assertEqual(fixture.wire.calls,calls)
            self.assertEqual(fixture.q._read(),before)
            self.assertEqual((aggregate_scope(fixture.service.config),aggregate_markets(fixture.service.config)),request_scope)
        finally:await fixture.asyncTearDown()


if __name__=='__main__':unittest.main()
