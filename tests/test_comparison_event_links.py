"""Independent authored occurrence/link cases, no owner state or acquisition."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from app.comparison.event_links import ProviderEdge, EventLinks, provider_key, reviewed_links
from app.collection.current_aggregate_admission import admit
from app.collection.current_overlap import associate
from app.dashboard.current_normalized import catalog_from_normalized
from app.dashboard.current_contract import serialize
from tests.current_fixture import fixture as raw

AT = datetime(2026, 10, 8, 20, tzinfo=timezone.utc)
START = '2026-10-09T00:15:00Z'
SHIFT = '2026-10-09T00:18:00Z'
EVENT = '259b5df9aa0d10257f56de78523495e0'
OCCURRENCE = 'aa6b58bf-4feb-11f1-abca-2c54536568a9'


def edge(provider='the_odds_api', native=EVENT, occurrence=OCCURRENCE):
    return ProviderEdge(provider, native, occurrence, 'NFL', 'NFL:DAL', 'NFL:TB', 'a'*64,
                        '2026-10-07T00:00:00Z', '2026-10-07T00:00:00Z', '2026-10-09T00:15:00Z', 'authored', 'manual_review')


def body(start=START, id_=EVENT):
    return json.dumps([dict(id=id_, sport_key='americanfootball_nfl', commence_time=start,
         home_team='Dallas Cowboys', away_team='Tampa Bay Buccaneers', bookmakers=[dict(key='novig',
         last_update='2026-10-08T19:59:00Z', markets=[dict(key='h2h', outcomes=[dict(name='Dallas Cowboys', price='2'),
         dict(name='Tampa Bay Buccaneers', price='3')])])])]).encode()


class EventLinkCases(unittest.TestCase):
    def test_same_provider_id_time_shift_preserves_current_event_group_outcome_quote(self):
        before=admit(body(), 'NFL', AT.isoformat());after=admit(body(SHIFT), 'NFL', AT.isoformat())
        self.assertEqual(before[0]['market_identity']['event'], after[0]['market_identity']['event'])
        envelope=raw();envelope['events']=[]
        def clean(rows):
            values=deepcopy(rows)
            for row in values:
                row['quote']['provenance']=dict(mode='synthetic',real_source=False,fixture='authored-time-shift')
            return [{k:v for k,v in row.items() if not k.startswith('_')} for row in values]
        a=catalog_from_normalized(envelope,clean(before));b=catalog_from_normalized(envelope,clean(after))
        a=serialize(a,allow_synthetic=True);b=serialize(b,allow_synthetic=True)
        for x,y in zip(a['events'],b['events']):
            self.assertEqual(x['id'],y['id']);self.assertNotEqual(x['start_at'],y['start_at'])
            self.assertEqual(x['groups'][0]['id'],y['groups'][0]['id'])
            self.assertEqual([o['id'] for o in x['groups'][0]['outcomes']],[o['id'] for o in y['groups'][0]['outcomes']])
            self.assertEqual([o['quotes']['novig']['id'] for o in x['groups'][0]['outcomes']],[o['quotes']['novig']['id'] for o in y['groups'][0]['outcomes']])
        self.assertEqual(before[0]['_instrument'],after[0]['_instrument'])

    def test_rematch_doubleheader_and_swapped_roles_are_distinct(self):
        r=admit(body(), 'NFL', AT.isoformat())[0];e=r['event']
        for change in [dict(id='rematch'),dict(id='doubleheader-two'),dict(home=e['away'],away=e['home'])]:
            self.assertNotEqual(provider_key('the_odds_api',e),provider_key('the_odds_api',dict(e,**change)))

    def test_conflicting_edges_roles_expiry_replacement_and_supersession(self):
        e=edge();links=EventLinks([e,edge(occurrence='different')])
        self.assertEqual(links.resolve('the_odds_api',EVENT,'NFL','NFL:DAL','NFL:TB',AT)[1],'provider_edge_conflict')
        self.assertEqual(EventLinks([e]).resolve('the_odds_api',EVENT,'NFL','NFL:TB','NFL:DAL',AT)[1],'provider_edge_role_conflict')
        late=datetime(2026,10,9,0,18,tzinfo=timezone.utc)
        self.assertEqual(EventLinks([e]).resolve('the_odds_api',EVENT,'NFL','NFL:DAL','NFL:TB',late)[1],'provider_edge_expired_or_not_effective')
        self.assertEqual(EventLinks([e]).resolve('the_odds_api','replacement','NFL','NFL:DAL','NFL:TB',AT)[1],'provider_edge_review_required')
        new=replace(e, occurrence_id='replacement-occurrence', effective_from='2026-10-08T00:00:00Z', supersedes=(e.id,))
        resolved,reason=EventLinks([e,new]).resolve('the_odds_api',EVENT,'NFL','NFL:DAL','NFL:TB',AT)
        self.assertIsNone(reason);self.assertEqual(resolved.occurrence_id,'replacement-occurrence')
        with self.assertRaises(ValueError):EventLinks([replace(e,supersedes=('b'*64,))])

    def test_crosswalk_serialization_review_bound_and_no_name_time_fallback(self):
        links=EventLinks([edge()]);self.assertEqual(links.to_dict(),EventLinks.from_dict(json.loads(json.dumps(links.to_dict()))).to_dict())
        for i in range(64):links.review('kalshi',str(i),'b'*64,'provider_edge_review_required')
        with self.assertRaises(ValueError):links.review('kalshi','overflow','b'*64,'provider_edge_review_required')
        records=admit(body(),'NFL',AT.isoformat());native=deepcopy(records[0]);native['quote']['source']['provider']='kalshi';native['quote']['source']['native_event_id']='native-one'
        native['event']['game_id']=OCCURRENCE;native['result_policy']='predict-direct-win-1:normal-full-game-win'
        output=associate([native],records,links=EventLinks(),clock=AT)
        self.assertEqual(output[0]['event_scope'],records[0]['event_scope'])
        self.assertIn('provider_edge_review_required',output[0]['orientation_evidence'][-1])
        joined=associate([native],records,links=EventLinks([edge(),edge('kalshi','native-one')]),clock=AT)
        self.assertNotIn('event_scope',joined[0]);self.assertEqual(joined[0]['event']['game_id'],OCCURRENCE)
        self.assertEqual(joined[0]['quote']['source'],records[0]['quote']['source'])

    def test_supersession_consumption_is_global_transitive_and_never_resurrects(self):
        old=replace(edge('kalshi','one'),effective_until=None,home_id='NFL:TB',away_id='NFL:DAL')
        middle=replace(old,home_id='NFL:DAL',away_id='NFL:TB',effective_from='2026-10-07T12:00:00Z',effective_until='2026-10-08T12:00:00Z',supersedes=(old.id,))
        newest=replace(middle,effective_from='2026-10-08T12:00:00Z',effective_until='2026-10-09T00:15:00Z',supersedes=(middle.id,))
        other=edge('polymarket_us','two')
        links=EventLinks([old,middle,newest,other])
        for provider,id_ in [('kalshi','one'),('polymarket_us','two')]:
            resolved,reason=links.resolve(provider,id_,'NFL','NFL:DAL','NFL:TB',AT)
            self.assertIsNone(reason);self.assertEqual(resolved.occurrence_id,OCCURRENCE)
        expired=datetime(2026,10,9,1,tzinfo=timezone.utc)
        self.assertIsNone(links.resolve('kalshi','one','NFL','NFL:TB','NFL:DAL',expired)[0])

    def test_dated_dallas_link_is_expired_and_has_no_private_paths(self):
        links=reviewed_links();self.assertIsNone(links.resolve('the_odds_api',EVENT,'NFL','NFL:DAL','NFL:TB',datetime(2026,10,9,1,tzinfo=timezone.utc))[0])
        text=(Path(__file__).resolve().parents[1]/'app/fixtures/comparison-event-links-v1.json').read_text()
        self.assertNotIn('.local',text)

if __name__ == '__main__':unittest.main()
