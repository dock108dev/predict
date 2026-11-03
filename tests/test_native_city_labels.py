"""Retained NHL city labels must agree with exact native milestone IDs."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import unittest
from app.adapters import kalshi
from app.collection.prediction_discovery import participant_mapping
from app.normalization.native_registry import native_registry

class NativeCityLabels(unittest.TestCase):
    def event(self, *, home='5b474f02-be1a-4aee-8200-4c4eb6e557e9',title='Minnesota vs Washington'):
        # Retained /events proof 3c2c820d943029469af78fcdcefa6f8bf4e85d1eb5c15faadff61a25de4cdeb2.
        eid='KXNHLGAME-26NOV01MINWSH'
        row=dict(event_ticker=eid,series_ticker='KXNHLGAME',title=title)
        milestone=dict(id='14141b9d-a17f-5c54-9f33-f8003db11fc2',category='Sports',type='hockey_match',
            title=title.replace(' vs ',' at '),start_date='2026-11-01T20:30:00Z',related_event_tickers=[eid],
            details=dict(main_game_event_ticker=eid,away_team_id='1cee0410-99f1-43a2-a67c-4e6a3b968a9c',home_team_id=home))
        response=kalshi.Response(json.dumps(dict(events=[row],milestones=[milestone])), '/trade-api/v2/events',datetime(2026,10,31,tzinfo=timezone.utc))
        return kalshi.parse_event(response,row,'KXNHLGAME')

    def test_retained_city_title_and_native_team_ids_agree(self):
        value,mapping=participant_mapping(self.event(),live=True)
        self.assertEqual(mapping,{'Minnesota':'NHL:MIN','Washington':'NHL:WSH'})
        self.assertTrue(all(p.resolution.status=='resolved' for p in value.participants))
        self.assertEqual({p.role:p.resolution.canonical_id for p in value.participants},{'away':'NHL:MIN','home':'NHL:WSH'})

    def test_known_different_team_still_conflicts_and_alias_is_scoped(self):
        value,_=participant_mapping(self.event(home='1cee0410-99f1-43a2-a67c-4e6a3b968a9c'),live=True)
        # Duplicate native role IDs cannot establish the exact role relation.
        self.assertFalse(any(p.role for p in value.participants))
        value,_=participant_mapping(self.event(title='Minnesota vs Boston'),live=True)
        self.assertEqual(value.participants[1].resolution.status,'conflicting')
        r=native_registry(live=True)
        self.assertNotEqual(r.resolve('team','Washington',league='NBA',venue='kalshi').canonical_id,'NHL:WSH')
        self.assertEqual(r.resolve('team','Washington',league='NHL',venue='polymarket_us').status,'unknown')
