from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch
import json
import time

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.collection.current_database import DatabaseIngressSink
from app.collection.current_aggregate_admission import admit
from app.collection.current_policy import DEFAULT
from app.collection.current_service import CurrentService
from app.collection.novig_v3_current import NovigCurrentWorker
from app.collection.novig_v3_stream import read_only_stream
from app.dashboard.current_state import CurrentStore
from app.dashboard.replay_api import load
from app.storage import comparison_snapshot as snapshots, odds_replay, ordinary_publication as publication
from app.storage.current_rows import CurrentRowStore
from app.storage.ordinary_scheduling import receipt_watermarks
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_novig_v3_stream import delta, life, snapshot


@skipUnless(SOCKET, 'Explicit disposable PostgreSQL lane required')
class NovigCurrentAdmission(LatestBoardFixture):
    async def test_signed_source_ingress_ordinary_math_and_archive_survive_disconnect(self):
        self.at = datetime.now(timezone.utc)
        self.state.write(self.service)
        start = int((self.at - timedelta(minutes=2)).timestamp() * 1000)
        event = dict(eventId='event', league='NCAAB', status='OPEN_INGAME', startsTs=start)
        market = dict(marketId='market', eventId='event', marketType='TOTAL', startsTs=start, status='OPEN',
                      strike='141.5', voids='FMV', fee=dict(coefficient='0.06', makerCredit='0.25', charged='WHEN_LIVE'),
                      outcomes=[dict(outcomeId=oid, name=label, status='TBD')
                                for oid, label in [('outcome', 'Over 141.5'), ('other', 'Under 141.5')]])
        people = dict(eventId='event', homeCompetitorId='mia', awayCompetitorId='unf',
                      competitors=[dict(competitorId='mia', name='Miami Hurricanes', marketIds=['market']),
                                   dict(competitorId='unf', name='Alabama Crimson Tide', marketIds=['market'])])
        paths = {
            '/v3/catalog/events': dict(items=[dict(event, status='OPEN_PREGAME')]),
            '/v3/catalog/markets': dict(items=[market]),
            '/v3/catalog/events/event': event,
            '/v3/catalog/markets/market': market,
            '/v3/catalog/participants': dict(items=[people]),
        }

        def rest(request):
            assert request.method == 'GET' and request.headers['Novig-Key-Id'] == 'fixture'
            return httpx.Response(200, json=paths[request.url.path])

        service = CurrentService(dict(DEFAULT, aggregate_sports=['NCAAB']), database_mode=True)
        service.runtime_id = self.service.runtime_id
        service.dispatch = True
        service.store = CurrentStore(service)
        service.sink = DatabaseIngressSink(service.store, service.config)
        with self.connect() as db:
            db.execute('TRUNCATE current_event CASCADE')
        messages = [snapshot(), delta(life=life(5, 'GOLIVE')), snapshot(seq=11, life=5, nonce=2)]
        observed = {}

        class Socket:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def send(self, raw):
                assert set(json.loads(raw)) in ({'nonce', 'subscribe'}, {'nonce', 'snapshot'})

            def __aiter__(self):
                return self

            async def __anext__(self):
                if messages:
                    return json.dumps(dict(messages.pop(0), ts=time.time_ns() // 1_000_000))
                inspect()
                raise StopAsyncIteration

        def inspect():
            self.at = datetime.now(timezone.utc)
            held = dict(state='held', reason_code='fixture_quota_hold')
            with self.connect() as db:
                # An empty authoritative aggregate refresh and aggregate health
                # loss must leave the independently signed Novig offer alone.
                rows = CurrentRowStore(db)
                rows.upsert_records([], scopes=[dict(venue='novig', competition='NCAAB',
                    received_at=self.at.isoformat(), aggregate_route='featured')],
                    authoritative=True, source_status={'novig': held}, now=self.at.isoformat())
                aggregate, native = receipt_watermarks(db)
                assert not aggregate
                assert [row['venue'] for row in native] == ['novig']
                owner, states = publication.authority(db, at=self.at)
                inputs = snapshots.capture(db, at=self.at.isoformat(), ordinary=True)
                settings = publication.current_settings(db)
            states['novig'] = held
            states['pinnacle'] = dict(state='available')
            assert len(inputs['quotes']) == 1, inputs['issues']
            result = publication.bind(snapshots.calculate(inputs, settings), inputs, 'ready')
            def project(authority):
                return publication.project(result, inputs['dependencies'], authority, states,
                                           at=self.at, policy=inputs['policy_identity'], epoch=inputs['epoch'])
            row = project(owner)['rows'][0]
            assert row['price_current'] and row['trade_fee']['trade_fee_usd'] == '0.01500', (row['price_reasons'], row['current_authority']['price'], owner['active'], owner['runtime_id'])
            assert row['exact_pinnacle_reference_current'] is False
            assert not project(dict(owner, runtime_id='new-owner'))['rows'][0]['price_current']
            assert not project(dict(owner, paused_sources=['the_odds_api']))['rows'][0]['price_current']
            at = self.at.isoformat()
            reference = [dict(id='aggregate-event', sport_key='basketball_ncaab',
                commence_time=datetime.fromtimestamp(start / 1000, timezone.utc).isoformat(),
                home_team='Miami Hurricanes', away_team='Alabama Crimson Tide',
                bookmakers=[dict(key='pinnacle', last_update=at, markets=[
                    dict(key='totals', last_update=at, outcomes=[
                        dict(name='Over', price=2, point=141.5), dict(name='Under', price=3, point=141.5)])])])]
            with self.connect() as db:
                CurrentRowStore(db).upsert_records(admit(json.dumps(reference).encode(), 'NCAAB', at), now=at)
                inputs = snapshots.capture(db, at=at, ordinary=True)
            # Deliberately select the existing NCAAB overtime scenario in the
            # disposable fixture. The producer never infers it from a price.
            settings, _ = snapshots.assumptions(dict(scoring='ncaab_full_game_overtime', scenario='decisive_only'))
            result = publication.bind(snapshots.calculate(inputs, settings), inputs, 'ready')
            matched = project(owner)['rows'][0]
            assert matched['exact_pinnacle_reference_current'], (result['benchmark_diagnostics'], matched.get('snapshot_identity'), matched['current_reasons'])
            assert matched['conditional_return_percent'] == '1700/103'
            observed['id'] = matched['id']
            observed['capture'] = (inputs, settings, owner, states)

        async def stream(markets, update, **kwargs):
            await read_only_stream(markets, update, connect_factory=lambda *a, **kw: Socket(), **kwargs)

        key = ('fixture', Ed25519PrivateKey.generate())
        worker = NovigCurrentWorker(service, stream=stream)
        with patch('app.collection.current_database.connect', self.connect):
            async with httpx.AsyncClient(transport=httpx.MockTransport(rest)) as client:
                assert await worker.batch(client, key)
        with self.connect() as db:
            assert {r['quote']['venue'] for r in CurrentRowStore(db).capture()['records']} == {'pinnacle'}
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            archive = odds_replay.compile_archive('frozen', observed['capture'], directory)
            with patch.object(odds_replay, 'DIRECTORY', directory):
                detail = load(dict(dataset='frozen', result_id=archive['id'], id=observed['id']), details=True)
            assert detail['row']['price_current']
            assert detail['inspection']['trade_fee']['trade_fee_usd'] == '0.01500'
            assert detail['row']['conditional_return_percent'] == '1700/103'
            assert detail['provider_requests'] == 0
