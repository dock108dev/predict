"""Source-local observations with authored missing comparison context; no I/O."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.collection.current_sink import normalized_records, source_local_display_binding
from app.collection.native_scope_bindings import series_binding
from app.collection.v1_comparison import bind, REPAIR_POLICY
from app.comparison.event_links import provider_key
from tests.multisport_fixtures import SPORTS, source_case, current_book


CLOCK = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)


def fixture(venue, league='NBA', family='moneyline', token='source-local'):
    case = source_case(league, family, token, clock=CLOCK)
    native = deepcopy(case['markets'][venue]); raw_event = deepcopy(case['events'][venue])
    for field in ('season','stage'):
        raw_event.pop(field,None)
    if league == 'MLB':
        for field in ('gameNumber','originalStartTime','rescheduledFromGameId'):
            raw_event.pop(field,None)
    eid = raw_event.get('event_ticker', raw_event.get('id'))
    mid = native.get('ticker', native.get('id'))
    event = dict(case['event'], id=eid, identity='resolved', title='Authored source event',
        sport={'NFL':'american_football','NCAAF':'american_football','NBA':'basketball',
               'NCAAB':'basketball','MLB':'baseball','NHL':'ice_hockey'}[league],
        participants={case['event']['home']:case['event']['home'],case['event']['away']:case['event']['away']},
        source_participant_roles={role:case['event'][role] for role in ('home','away')},
        season=None, stage=None, _native=raw_event)
    if league == 'MLB':
        for field in ('game_id','game_number','original_start','schedule_status'):
            event[field] = None
    sides = ([dict(id=value, role=value) for value in ('yes','no')] if venue == 'kalshi'
             else [dict(id=side['id'],role='Long' if side['long'] else 'Short') for side in native['marketSides']])
    market = dict(id=mid,event_id=eid,market_type=family,period='full_game',status='active',
        exclusion=None,sides=sides,_native=native,
        native_scope_binding=series_binding(case['series']) if venue == 'kalshi' else None,
        terms={key:native[key] for key in ('description','rules_primary','rules_secondary') if key in native})
    market['v1_raw_binding'] = bind(event,market,venue,policy=REPAIR_POLICY)
    book = current_book(case,venue,clock=CLOCK)
    catalog = dict(events=[event],markets=[market])
    projection = SimpleNamespace(inventory={venue:catalog},books={(venue,eid,mid):dict(book=book)},invalid=set())
    return projection,event,market,book


def normalize(projection, venue):
    with patch('socket.socket.connect',side_effect=AssertionError('No acquisition')):
        return normalized_records(projection,{venue:dict(state='available')},{},
            dated_annotations=False,clock=CLOCK.isoformat())


class SourceLocalSink(unittest.TestCase):
    def test_six_league_winner_prices_keep_null_context_and_exact_native_identity(self):
        for league in SPORTS:
            for venue in ('kalshi','polymarket_us'):
                with self.subTest(league=league,venue=venue):
                    projection,event,market,book = fixture(venue,league)
                    before = deepcopy(projection.inventory)
                    strict = deepcopy(market['v1_raw_binding'])
                    self.assertEqual(strict['status'],'IDENTITY_BLOCKED',strict['blockers'])
                    records,excluded = normalize(projection,venue)
                    self.assertEqual(excluded,[])
                    self.assertEqual(len(records),2)
                    self.assertEqual(projection.inventory,before)
                    self.assertEqual(market['v1_raw_binding'],strict)
                    self.assertEqual({r['quote']['source']['native_outcome_id'] for r in records},
                        {side['id'] for side in market['sides']})
                    for record in records:
                        self.assertIsNone(record['event']['season']);self.assertIsNone(record['event']['stage'])
                        self.assertEqual(record['market_identity']['event'],provider_key(venue,event))
                        self.assertFalse(record['verified'])
                        self.assertEqual(record['period_boundary'],'Original native period; scoring scope recorded separately')
                        self.assertEqual(record['event_scope'],dict(policy='native-event-unverified-2',
                            source=venue,native_event_id=event['id']))
                        q = record['quote'];self.assertEqual(q['original']['value'],'0.51')
                        self.assertEqual(q['rule_note'],'Original native price retained; comparison context is incomplete.')
                        self.assertEqual(q['times']['source_at'],book['raw']['exchange_at'])
                        self.assertEqual(q['times']['received_at'],book['raw']['received_at'])
                        metadata = record['comparison_source_metadata'];admission = metadata['comparison_admission']
                        self.assertFalse(admission['supported']);self.assertEqual(admission['reason'],'comparison_context_missing')
                        self.assertTrue({'season','stage'} <= set(admission['missing_fields']))
                        if league == 'MLB':
                            self.assertTrue({'game_id','game_number','original_start','schedule_status'} <= set(admission['missing_fields']))
                        self.assertEqual(metadata['native_terms'],market['terms'])
                    if venue == 'kalshi':
                        self.assertEqual({r['selection']['predicate'] for r in records},{'win','not_win'})

    def test_existing_score_predicates_survive_context_only_refusal_for_both_sources(self):
        for family in ('spread','total'):
            for venue in ('kalshi','polymarket_us'):
                with self.subTest(family=family,venue=venue):
                    projection,_,market,_ = fixture(venue,'NBA',family)
                    predicate = deepcopy(market['v1_raw_binding']['source_predicate'])
                    if venue == 'kalshi':
                        market['exclusion']='native_scope_predicate_review_required'
                    else:
                        market['subscription_evidence_exclusion']='unresolved_native_sides'
                    records,excluded = normalize(projection,venue)
                    self.assertEqual(excluded,[]);self.assertEqual(len(records),2)
                    self.assertTrue(all(r['comparison_source_metadata']['source_predicate']==predicate for r in records))
                    self.assertTrue(all(r['comparison_source_metadata']['comparison_admission']['supported'] is False for r in records))

    def test_separate_catalog_admission_does_not_change_the_strict_binding_digest(self):
        for venue in ('kalshi','polymarket_us'):
            projection,event,market,_ = fixture(venue,'NBA','spread')
            strict = deepcopy(market['v1_raw_binding'])
            display = source_local_display_binding(event,market,strict,venue)
            self.assertIsNotNone(display)
            market['comparison_admission']=deepcopy(display['comparison_admission'])
            records,excluded = normalize(projection,venue)
            self.assertEqual(excluded,[]);self.assertEqual(len(records),2)
            self.assertEqual(market['v1_raw_binding'],strict)
            self.assertIsNotNone(source_local_display_binding(event,market,strict,venue))
            self.assertTrue(all(r['comparison_source_metadata']['comparison_admission']==market['comparison_admission']
                for r in records))

    def test_missing_mlb_occurrence_context_keeps_same_pair_different_native_events_separate(self):
        keys = []
        for token in ('doubleheader-one','doubleheader-two'):
            projection,_,_,_ = fixture('kalshi','MLB',token=token)
            records,excluded = normalize(projection,'kalshi')
            self.assertEqual(excluded,[]);keys.append(records[0]['market_identity']['event'])
        self.assertNotEqual(keys[0],keys[1])

    def test_legacy_mlb_context_validator_does_not_hide_missing_season_but_schedule_conflict_still_blocks(self):
        for conflict in (False,True):
            projection,event,market,_ = fixture('kalshi','MLB')
            event.update(game_id='source-explicit-game',game_number=1,
                original_start=event['scheduled_start'],schedule_status='original')
            if conflict:
                event['original_start']='2026-10-18T15:00:00+00:00'
            market['v1_raw_binding']=bind(event,market,'kalshi',policy=REPAIR_POLICY)
            self.assertIn('Conflicting or incomplete exact MLB occurrence/home/away identity',
                market['v1_raw_binding']['blockers'])
            records,excluded = normalize(projection,'kalshi')
            if conflict:
                self.assertEqual(records,[]);self.assertEqual(len(excluded),1)
            else:
                self.assertEqual(excluded,[]);self.assertEqual(len(records),2)
                self.assertTrue(all(r['comparison_source_metadata']['comparison_admission']['missing_fields']==['season','stage']
                    for r in records))

    def test_hard_identity_conflicts_and_inexact_roles_or_start_stay_excluded(self):
        for venue in ('kalshi','polymarket_us'):
            for field in ('duplicate','occurrence','roles','start','binding_conflict'):
                with self.subTest(venue=venue,field=field):
                    projection,event,market,_ = fixture(venue)
                    if field == 'duplicate':event['conflicting_duplicate']=True
                    elif field == 'occurrence':event['occurrence_conflict']=True
                    elif field == 'roles':event['source_participant_roles']['home']=event['away']
                    elif field == 'start':event.pop('scheduled_start')
                    else:market['v1_raw_binding']['blockers'].append('Conflicting duplicate native identity')
                    records,excluded = normalize(projection,venue)
                    self.assertEqual(records,[]);self.assertEqual(len(excluded),1)

    def test_missing_typed_predicate_does_not_promote_kalshi_and_unsynchronized_books_do_not_publish(self):
        projection,_,market,_ = fixture('kalshi')
        market['v1_raw_binding']['predicate']=None
        records,excluded = normalize(projection,'kalshi')
        self.assertEqual(records,[]);self.assertEqual(len(excluded),1)
        for venue in ('kalshi','polymarket_us'):
            projection,_,_,book = fixture(venue)
            book['sync']='unsynchronized'
            records,excluded = normalize(projection,venue)
            self.assertEqual(records,[]);self.assertEqual(excluded,[])
