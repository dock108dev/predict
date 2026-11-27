import asyncio
from datetime import timedelta
from email.utils import format_datetime
from fractions import Fraction
import json
from unittest import skipUnless

import httpx
import pytest

from app.collection.native_experiment_depth import (
    NativeExperimentDepth, PMUS_CURRENT_HASH, PMUS_TERMS, _pmus_fee, native_bindings,
)
from app.collection.native_trading_pmus_stream import DashboardMarketStream
from app.storage.store import stamp
from tests.latest_board_fixture import SOCKET
from tests.test_paper_experiments_sql import ResearchWorkspaceFixture
from tests.test_paper_experiments import frozen_priced


AT = stamp('2026-11-27T15:26:00Z')


def binding(venue, market, selected, opposite):
    return dict(venue=venue, event_id='event', market_id=market, outcome_id=selected,
                opposite_outcome_id=opposite, native_side=selected, route=market, reason=None,
                levels=[], complete=False, receipts=[])


def test_kalshi_deduplicates_side_reads_and_complements_opposite_bids():
    calls = []

    def serve(request):
        calls.append(request.url.path)
        return httpx.Response(200, headers={'Date': format_datetime(AT)}, json={'orderbook_fp': {
            'yes_dollars': [['0.41', '1.23'], ['0.55', '100']],
            'no_dollars': [['0.24', '16'], ['0.40', '3.12']],
        }})

    async def read():
        async with NativeExperimentDepth(client=httpx.AsyncClient(transport=httpx.MockTransport(serve)), now=lambda: AT) as venue:
            return await venue.read_native({'one': binding('kalshi', 'market', 'yes', 'no'),
                                            'two': binding('kalshi', 'market', 'no', 'yes')}, AT + timedelta(seconds=1))

    books = asyncio.run(read())
    assert len(calls) == 1
    assert books['one']['complete'] and books['two']['complete']
    assert books['one']['levels'][0] == dict(price='3/5', quantity='3.12')
    assert books['two']['levels'][0] == dict(price='9/20', quantity='100')
    assert books['one']['receipts'] == books['two']['receipts']


def test_kalshi_empty_book_first_confirms_exact_open_market():
    routes = []

    def serve(request):
        routes.append(request.url.path)
        value = {'orderbook_fp': {'yes_dollars': [], 'no_dollars': []}} if request.url.path.endswith('/orderbook') else {
            'market': {'ticker': 'other', 'event_ticker': 'event', 'status': 'active'}}
        return httpx.Response(200, headers={'Date': format_datetime(AT)}, json=value)

    async def read():
        async with NativeExperimentDepth(client=httpx.AsyncClient(transport=httpx.MockTransport(serve)), now=lambda: AT) as venue:
            return await venue.read_native({'one': binding('kalshi', 'market', 'yes', 'no')}, AT + timedelta(seconds=1))

    books = asyncio.run(read())
    assert len(routes) == 2 and books['one']['reason'] == 'native_market_open_unverified'


def test_public_kalshi_batch_does_not_treat_a_missing_ticker_as_empty():
    calls = []

    def serve(request):
        calls.append(request.url.params.get_list('tickers'))
        body = {'orderbooks': [{'ticker': 'one', 'orderbook_fp': {
            'yes_dollars': [['0.47', '250']], 'no_dollars': [['0.50', '300']],
        }}]}
        return httpx.Response(200, headers={'Date': format_datetime(AT)}, json=body)

    async def read():
        async with NativeExperimentDepth(client=httpx.AsyncClient(transport=httpx.MockTransport(serve)), now=lambda: AT) as venue:
            return await venue.read_native({'one': binding('kalshi', 'one', 'yes', 'no'),
                                            'two': binding('kalshi', 'two', 'yes', 'no')},
                                           AT + timedelta(seconds=1), batch=True)

    books = asyncio.run(read())
    assert calls == [['one', 'two']]
    assert books['one']['levels'] == [dict(price='1/2', quantity='300')]
    assert books['two']['reason'] == 'native_book_unobserved'


def test_polymarket_short_sizes_come_from_long_bids_and_clock_is_source_bound():
    def serve(request):
        data = dict(marketSlug='slug', state='MARKET_STATE_OPEN', transactTime=AT.isoformat(),
            bids=[dict(px=dict(value='0.77', currency='USD'), qty='12.01')],
            offers=[dict(px=dict(value='0.79', currency='USD'), qty='119.02')])
        return httpx.Response(200, headers={'Date': format_datetime(AT), 'Age': '1'}, json={'marketData': data})

    selected = binding('polymarket_us', 'slug', 'Short', 'Long')
    cutoff = AT + timedelta(seconds=2)
    async def read():
        async with NativeExperimentDepth(client=httpx.AsyncClient(transport=httpx.MockTransport(serve)), now=lambda: AT) as venue:
            result = (await venue.read_native({'one': selected}, cutoff))['one']
            stale = (await venue.read_native({'one': selected}, cutoff + timedelta(seconds=30)))['one']
            return result, stale

    result, stale = asyncio.run(read())
    assert not result['complete'] and result['reason'] is None
    assert Fraction(result['levels'][0]['price']) == Fraction('.23')
    assert Fraction(result['levels'][0]['quantity']) == Fraction('12.01')
    assert result['source_at'] == AT.isoformat()
    assert stale['reason'] == 'stale'


def test_throttle_and_cutoff_prevent_a_second_native_request():
    calls = []

    def serve(request):
        calls.append(request.url.path)
        return httpx.Response(429, headers={'Date': format_datetime(AT), 'Retry-After': '60'})

    selected = binding('kalshi', 'market', 'yes', 'no')
    async def read():
        async with NativeExperimentDepth(client=httpx.AsyncClient(transport=httpx.MockTransport(serve)), now=lambda: AT) as venue:
            for _ in range(2):
                result = (await venue.read_native({'one': selected}, AT + timedelta(seconds=1)))['one']
                assert result['reason'] == 'throttled'
            result = (await venue.read_native({'one': selected}, AT))['one']
            assert result['reason'] == 'cutoff_passed'

    asyncio.run(read())
    assert len(calls) == 1


def test_dashboard_hourly_allowance_defers_optional_read_without_blocking_checkpoint():
    calls = []

    def serve(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={'active': True})

    async def run():
        cutoff = AT + timedelta(seconds=2)
        async with NativeExperimentDepth(
            client=httpx.AsyncClient(transport=httpx.MockTransport(serve)), now=lambda: AT,
        ) as client:
            async def read(suffix):
                return await client._read('kalshi', 'https://example.test/' + suffix, cutoff, body_limit=100)

            async def optional():
                assert (await read('first'))[2] is None
                assert (await read('deferred'))[2] == 'native_dashboard_source_budget'

            await client.dashboard_call(optional(), {'requests_per_source': 10, 'source_bytes': 105})
            assert (await read('checkpoint'))[2] is None

    asyncio.run(run())
    assert calls == ['/first', '/checkpoint']


def test_polymarket_dashboard_stream_shares_exact_snapshot_and_rejects_stale_updates():
    calls = []
    clock = [AT]

    class Socket:
        def __init__(self):
            self.frames = asyncio.Queue()

        async def send(self, raw):
            command = json.loads(raw)['subscribe']
            calls.append(command['marketSlugs'])
            for when, state in ((AT, 'MARKET_STATE_OPEN'),
                                (AT-timedelta(seconds=1), 'MARKET_STATE_HALTED')):
                data = dict(requestId=command['requestId'], subscriptionType='SUBSCRIPTION_TYPE_MARKET_DATA',
                    marketData=dict(marketSlug='slug', state=state, transactTime=when.isoformat(),
                        bids=[dict(px=dict(value='0.77', currency='USD'), qty='12.01')],
                        offers=[dict(px=dict(value='0.79', currency='USD'), qty='119.02')]))
                self.frames.put_nowait(json.dumps(data))

        async def recv(self):
            return await self.frames.get()

        async def close(self):
            calls.append('closed')

    class Credential:
        def check(self, _raw):
            pass

    async def run():
        async def connect(_credential):
            return Socket()

        stream = DashboardMarketStream(now=lambda: clock[0], allowed=lambda: True,
                                       credentials=Credential, transport=connect)
        ends = dict(scheduled_start=(AT+timedelta(minutes=10)).isoformat(),
                    terms_valid_until=(AT+timedelta(minutes=1)).isoformat())
        selections = {side: dict(binding('polymarket_us', 'slug', side, other), **ends)
                      for side, other in (('Long', 'Short'), ('Short', 'Long'))}
        initial = await stream.read(selections, AT+timedelta(seconds=1))
        assert initial['Long']['receipts'] == initial['Short']['receipts']
        assert initial['Short']['levels'] == [dict(price='23/100', quantity='1201/100')]
        assert initial['Short']['reason'] is None
        clock[0] += timedelta(seconds=31)
        assert await stream.read(selections, clock[0]+timedelta(seconds=1)) == {}
        await stream.close()

    asyncio.run(run())
    assert calls == [['slug'], 'closed']


def test_sgo_polymarket_label_alone_does_not_map_to_polymarket_us():
    sgo = frozen_priced('+300', venue='polymarket_us')
    future = (AT + timedelta(minutes=10)).isoformat()
    task = dict(event=dict(starts_at=future, league='NBA', home='home', away='away'))
    result, = native_bindings(None, task, AT, [sgo]).values()
    assert result['reason'] == 'provider_venue_fee_applicability_unestablished'


def test_pmus_cutover_requires_new_public_document_receipt_before_the_decision():
    with pytest.raises(ValueError, match='polymarket_us_current_terms_unreviewed'):
        _pmus_fee({}, AT)
    evidence = dict(normalized_sha256=PMUS_CURRENT_HASH, document=dict(url=PMUS_TERMS, http_status=200,
        retrieved_at=(AT - timedelta(minutes=1)).isoformat()))
    terms = _pmus_fee({'polymarket_us:standard_sports': dict(last_attempt=dict(retrieval=evidence))}, AT)
    assert terms['coefficient'] == '0.11' and terms['api_coefficient'] == '0.0695'
    evidence['document']['retrieved_at'] = (AT + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match='polymarket_us_current_terms_unreviewed'):
        _pmus_fee({'polymarket_us:standard_sports': dict(last_attempt=dict(retrieval=evidence))}, AT)


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class NativeReplacementSQL(ResearchWorkspaceFixture):
    async def test_retained_native_book_replaces_partial_quoted_winner_in_replay(self):
        from app.comparison import scanner_kalshi
        from app.research import experiment, paper, paper_depth
        from app.storage import experiment_depth
        from tests.test_experiment_depth_execution import receipt
        from tests.test_paper_experiments import fixed_policy
        from tests.test_scanner_kalshi import inputs

        day = '2026-11-23'
        self.at = stamp(day + 'T17:00:00Z')
        game = self.game('cross-venue-depth', day + 'T18:00:00Z')
        # Same exact side and reference probability. Novig's frozen price has
        # higher EV, while only the observed Kalshi ask can support Win $25.
        novig = frozen_priced('+120', venue='novig', ev='.232', line='-10.5')
        candidate = frozen_priced('+100', venue='kalshi', ev='.12', line='-10.5')
        for offer in (novig, candidate):
            row = offer['record']
            row['event'].update(scheduled_start=game['starts_at'], competition='NCAAB')
            row['market_identity']['rules'] = 'sportsgameodds-unverified-1'
            row['result_policy'] = 'sportsgameodds-unverified-1:spread'
            row['quote']['source'].update(native_event_id=game['source_event_id'],
                                          native_outcome_id='points-home-game-sp-home', native_line='-10.5')
        assert novig['calculation_payload']['reference']['probability'] == candidate['calculation_payload']['reference']['probability']
        snapshot = dict(event=dict(home='home', away='away', competition='NCAAB', scheduled_start=game['starts_at']),
                        source_event=dict(event_id=game['source_event_id']), offers=[novig, candidate],
                        coverage=dict(incomplete=False))
        with self.connect() as db:
            experiment.discover(db, [game], at=self.at)
            for kind, target in (('early', self.at), ('late', stamp(day + 'T17:50:00Z'))):
                self.advance(db, target)
                task, = experiment.due(db, at=self.at)
                saved = experiment.capture(db, task['game_id'], kind, snapshot, token=task['token'],
                    requested_at=target, received_at=target, known_at=target)
                assert saved['state'] == 'captured'

            q, evidence = inputs()
            evidence['fee_review']['reviewed_at'] = '2026-11-23T15:00:00Z'
            resolved = scanner_kalshi.resolve(q, evidence, at=self.at)
            kalshi_receipt = dict(receipt(('.48', 100)), venue='kalshi', payout_usd='1', quantity_increment='1',
                price_bands=resolved['grid']['price_ranges'],
                fee=dict(model='kalshi_direct_taker_bound', terms=resolved['fee']))
            saved = experiment_depth.save(db, task, known_at=target, observations={
                experiment_depth.offer_key(novig['record']): receipt(('.45', 1000)),
                experiment_depth.offer_key(candidate['record']): kalshi_receipt,
            })
            policy = dict(fixed_policy(target='25'), league='NCAAB', defer_results=True,
                portfolio_rule=paper.MAIN_FIRST_ONE_PER_GAME, market_scope=paper.MAIN_SPREADS_TOTALS,
                depth_policy=paper_depth.VERSION, depth_receipts={task['game_id']: saved['id']})
            report = paper.report(db, day, policy=policy, as_of=self.at, evidence=True)

        selection, = report['portfolios']['best_venue']['tickets']
        comparison, = [row['depth_comparison'] for row in report['games']]
        assert selection['venue'] == 'kalshi'
        assert selection['depth']['modeled_native_quantity'] == '50'
        assert selection['depth']['modeled_fee_usd'] == '0.875'
        assert comparison['picks']['quoted']['venue'] == 'novig'
        assert comparison['picks']['quoted']['depth']['status'] == 'partial_size'
        assert report['depth_analysis']['scenarios']['depth']['replacements'] == 1
