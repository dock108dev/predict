"""Prospective admission implementation with authored clocks/books; no acquisition."""
from copy import deepcopy
from datetime import timedelta
from email.message import Message
from hashlib import sha256
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.collection.coverage import catalog
from app.collection.current_occurrence import annotate, selected_proof, direct
from app.collection.current_policy import DEFAULT
from app.collection.current_service import CurrentService
from app.collection.current_sink import LatestStateSink
from app.comparison.event_evidence import fetch_nfl_events
from app.comparison.event_links import reviewed_links
from app.dashboard.current_contract import quotes_of, stamp, snapshot_inputs
from app.dashboard.current_state import CurrentStore, CurrentStateProvider
from tests.test_current_occurrence import book
from tests.test_comparison_reference_gap import raw, selected

ROOT=Path(__file__).resolve().parents[1]


def selected_catalog(at):
    event=json.loads((ROOT/'app/fixtures/comparison-public-event-response-v1.json').read_text())['events'][0]
    event['markets']=[event['markets'][459]]
    body=json.dumps({'events':[event]}).encode()
    page=dict(source='polymarket_us',path='/v1/events',params={'limit':2,'offset':0},status=200,received_at=at,
        body_b64=base64.b64encode(body).decode(),body_sha256=sha256(body).hexdigest(),
        complete=True,usable_metadata=True,inventory_row=1,v1_comparison_policy='manual-comparison-2')
    c=catalog([page],'polymarket_us',stamp(at),share_identity=False)
    annotate(c,'polymarket_us')
    from app.collection.v1_comparison import annotate as predicates
    predicates(c,'polymarket_us',policy='manual-comparison-2')
    return annotate(c,'polymarket_us')


class ProspectiveAdmission(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.proof=selected_proof();self.at=stamp(self.proof['applicability']['start'])+timedelta(seconds=60)
        self.clock=patch('app.collection.current_occurrence.datetime').start()
        self.clock.now.return_value=self.at
        self.addCleanup(patch.stopall)

    def test_real_review_edges_are_current_only_and_exact(self):
        links=reviewed_links()
        for provider,source in [('the_odds_api','21b26266f3d78af02eb672e606275d95'),('polymarket_us','129629')]:
            edge,reason=links.resolve(provider,source,'NFL','NFL:JAX','NFL:PHI',self.at)
            self.assertIsNone(reason);self.assertEqual(edge.occurrence_id,'b635ddd1-4827-4593-ae8f-f41ae2f8914f')
            self.assertEqual(edge.review_class,'manual_review');self.assertEqual(edge.evidence_class,'retained_reviewed')
            self.assertIsNone(links.resolve(provider,source,'NFL','NFL:JAX','NFL:PHI',stamp('2026-10-09T03:55:16.261974Z'))[0])
            self.assertIsNone(links.resolve(provider,source,'NFL','NFL:PHI','NFL:JAX',self.at)[0])
            self.assertIsNone(links.resolve(provider,source+'-replacement','NFL','NFL:JAX','NFL:PHI',self.at)[0])
            self.assertIsNone(links.resolve(provider,source,'NFL','NFL:JAX','NFL:PHI',stamp(self.proof['applicability']['end']))[0])

    def test_catalog_requires_exact_instrument_rules_roles_and_no_replacement(self):
        for kind in ('good','event','game','provider','role','period','overtime','side','replacement','expired'):
            c=selected_catalog(self.at.isoformat());e=c['events'][0];m=c['markets'][0]
            if kind=='event':e['id']='129630';m['event_id']='129630'
            elif kind=='game':e['_native']['gameId']=19519
            elif kind=='provider':e['_native']['sportradarGameId']='other'
            elif kind=='role':e['source_participant_roles']={'home':'NFL:PHI','away':'NFL:JAX'}
            elif kind=='period':m['_native']['sportsMarketType']='football_team_first_half_winner'
            elif kind=='overtime':m['_native']['description']=m['_native']['description'].replace('Overtime is included if played.','Overtime is excluded.')
            elif kind=='side':m['_native']['marketSides'][0]['id']='2165648'
            elif kind=='replacement':e['_native']['rescheduledFromGameId']=19517
            elif kind=='expired':self.clock.now.return_value=stamp(self.proof['applicability']['end'])
            annotate(c,'polymarket_us')
            self.assertEqual(bool(m.get('direct_win_binding')),kind=='good',kind)
            self.clock.now.return_value=self.at

    def test_direct_correspondence_rejects_old_quotes_short_and_future_receipts(self):
        c=selected_catalog(self.at.isoformat());annotate(c,'polymarket_us');e=c['events'][0];m=c['markets'][0]
        record=dict(event=e,quote=dict(venue='polymarket_us',times=dict(source_at=self.at.isoformat(),received_at=self.at.isoformat())))
        selection=dict(participant='NFL:PHI',predicate='win')
        self.assertTrue(direct(record,m,'2165646',selection,clock=self.at))
        self.assertFalse(direct(record,m,'2165647',dict(participant='NFL:JAX',predicate='win'),clock=self.at))
        self.assertFalse(direct(record,m,'2165647',dict(participant='NFL:PHI',predicate='not_win'),clock=self.at))
        for key in ('source_at','received_at'):
            for when in ('2026-10-09T03:55:16.261974Z',(self.at+timedelta(seconds=1)).isoformat(),None):
                bad=deepcopy(record);bad['quote']['times'][key]=when
                self.assertFalse(direct(bad,m,'2165646',selection,clock=self.at))

    async def test_ordinary_future_quote_reference_profiles_gross_only(self):
        at=self.at.isoformat();service=CurrentService(config=dict(DEFAULT,enabled=False,aggregate_enabled=False))
        envelope=service.initial_state();envelope.update(clock_at=at,projected_at=at)
        class Initial(CurrentStateProvider):
            def initial_state(self):return deepcopy(envelope)
        store=CurrentStore(Initial(),monotonic=lambda:0);service.store=store
        service.sink=LatestStateSink(store,envelope);service.dispatch=True
        service.states={v:dict(s,state='available',reason_code='authored',reason='Authored implementation proof') for v,s in service.states.items()}
        try:
            with patch('app.collection.current_sink.utc',return_value=at):
                c=selected_catalog(at);service.catalog('polymarket_us',c)
                service.books('polymarket_us',[book('polymarket_us',m,at) for m in c['markets']])
                # These hypothetical source clocks and odds prove behavior only.
                event=dict(id='21b26266f3d78af02eb672e606275d95',sport_key='americanfootball_nfl',
                    sport_title='NFL',commence_time='2026-10-11T13:30:00Z',home_team='Jacksonville Jaguars',
                    away_team='Philadelphia Eagles',bookmakers=[dict(key='pinnacle',title='Pinnacle',
                    markets=[dict(key='h2h',outcomes=[dict(name='Jacksonville Jaguars',price='1.27'),
                        dict(name='Philadelphia Eagles',price='4.0')])])])
                event['bookmakers']=[b for b in event['bookmakers'] if b['key']=='pinnacle']
                for b in event['bookmakers']:
                    b['last_update']=at;b['markets']=[m for m in b['markets'] if m['key']=='h2h']
                    for m in b['markets']:m['last_update']=at
                service.sink.commit(dict(type='current_aggregate',sport='NFL',body=json.dumps([event]).encode(),received_at=at),service.states)
            snapshot=store.snapshot();qs=[q for e in snapshot['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o) if q['venue']=='polymarket_us']
            long=next(q for q in qs if q['source']['native_side']=='Long');short=next(q for q in qs if q['source']['native_side']=='Short')
            self.assertTrue(long['sharp_reference'])
            self.assertEqual(long['sharp_reference']['version'],'pinnacle-proportional-no-vig-1')
            self.assertIsNotNone(long['comparison_input_refs']['refs']['reference'])
            self.assertIsNone(short.get('sharp_reference'))
            disclosure=long['comparison_input_status']['reference']['prospective_review']
            self.assertEqual(disclosure['effective_from'],self.proof['applicability']['start'])
            self.assertFalse(disclosure['historical_applicability'])
            self.assertNotIn('prospective_review',short['comparison_input_status']['reference'])
            from app.collection.current_comparison_inputs import prospective_reference_review
            historical_check=deepcopy(long);historical_check['times']['source_at']='2026-10-09T03:55:16.261974Z'
            self.assertIsNone(prospective_reference_review(historical_check))
            wrong_side=deepcopy(long);wrong_side['source']['native_outcome_id']='2165647'
            self.assertIsNone(prospective_reference_review(wrong_side))
            self.assertNotIn('native_predicate',short)
            self.assertEqual(short['source']['native_side'],'Short')
            self.assertEqual(short['original']['transformation'],'one_minus_native_bid')
            self.assertFalse(long['calculations']['net_ev']['eligible']);self.assertFalse(long['calculations']['conservative']['eligible'])
            self.assertTrue(long['calculations']['ev']['eligible'],long['calculations']['ev'])
            # An immutable ref profile is shared by that exact same revision.
            profile=snapshot['comparison_profiles'][long['comparison_input_refs']['refs']['reference']]
            self.assertEqual(profile['kind'],'reference')
            historical=selected(raw());self.assertEqual(historical['original']['value'],'0.2350');self.assertEqual(historical['revision'],9)
            self.assertIsNone(historical.get('sharp_reference'))
            from aiohttp.test_utils import TestClient, TestServer
            from app.dashboard.multi_game_server import create_app
            from app.dashboard.current_state import CURRENT_KEY
            from tests.test_current_state import owner
            class Frozen(CurrentStateProvider):
                def initial_state(self):return snapshot_inputs(snapshot)
            application=create_app(owner=owner(),sessions={},current_provider=Frozen())
            application[CURRENT_KEY].monotonic=lambda:0
            application[CURRENT_KEY]._age_origin=0
            async with TestClient(TestServer(application)) as client:
                current=await (await client.get('/api/current')).json()
                comparison=await (await client.get('/api/comparison?league=NFL')).json()
            self.assertEqual(current['runtime_id'],comparison['runtime_id'])
            self.assertEqual(current['state_revision'],comparison['state_revision'])
            self.proof_snapshot=current
            self.proof_comparison=comparison
        finally:
            service.dispatch=False;await store.close()


class QuotaFreeReader(unittest.TestCase):
    def read(self,body=b'[]',cost='0',status=200):
        response=type('Response',(),{})();response.status=status;response.headers=Message()
        response.headers['Content-Type']='application/json';response.headers['Content-Length']=str(len(body))
        response.headers['x-requests-last']=cost
        stream=io.BytesIO(body);response.read=stream.read;response.isclosed=lambda:stream.tell()==len(body)
        connection=type('Connection',(),{})();connection.request=lambda *a,**k:None;connection.getresponse=lambda:response;connection.close=lambda:None
        with tempfile.TemporaryDirectory() as directory,patch('app.comparison.event_evidence.http.client.HTTPSConnection',return_value=connection):
            record,graph=fetch_nfl_events(Path(directory)/'one','dummy-local-key')
            files={p.name:p.read_bytes() for p in (Path(directory)/'one').iterdir()}
            self.assertNotIn(b'dummy-local-key',b''.join(files.values()))
            return record,graph,files

    def test_fixed_documented_route_and_zero_cost(self):
        r,g,_=self.read();self.assertEqual(g,[]);self.assertEqual(r['credits'],0)
        self.assertNotIn('apiKey',r['url']);self.assertIn('/americanfootball_nfl/events?',r['url'])
        self.assertEqual(r['requests'],1);self.assertEqual(r['redirects'],0)

    def test_cost_redirect_and_credential_echo_refuse(self):
        for options in (dict(cost='1'),dict(cost='invalid'),dict(status=302),dict(body=b'{"key":"dummy-local-key"}')):
            r,g,files=self.read(**options);self.assertIsNone(g)
            if 'body' in options:self.assertNotIn('decoded.json',files);self.assertEqual(r['reason'],'credential_echo_suppressed')
