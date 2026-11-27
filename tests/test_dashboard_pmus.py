import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from app.collection import dashboard_pmus
from app.collection.native_experiment_depth import NativeExperimentDepth, PMUS_CURRENT_HASH, PMUS_TERMS
from app.comparison import execution_contract, scanner_polymarket
from app.comparison.experiment_depth_execution import evaluate_at_stake

AT = datetime(2026, 11, 27, 23, 50, tzinfo=timezone.utc)
KICKOFF = '2026-11-28T00:00:00Z'
HEADERS = {'Date': format_datetime(AT, usegmt=True), 'Age': '0'}

AWAY = dict(id=14, name='Miami Heat', league='nba', ordering='away')
HOME = dict(id=43, name='New York Knicks', league='nba', ordering='home')
KINDS = {'moneyline': 'basketball_team_full_game_winner', 'spread': 'basketball_team_full_game_spread',
         'total': 'basketball_team_full_game_total'}


def market(family, *, line=None):
    mid = str({'moneyline': 1, 'spread': 2, 'total': 3}[family])
    descriptions = {
        'moneyline': 'This market will settle to the winner of the Miami Heat vs New York Knicks basketball game.',
        'spread': 'This market will settle to Yes if Miami Heat covers a +31.5 point spread in the Miami Heat vs New York Knicks basketball game.',
        'total': 'This market will settle to Yes if Miami Heat and New York Knicks combine for over 221.5 points in the game.',
    }
    labels = {'moneyline': ('Heat', 'Knicks'), 'spread': ('+31.50', '-31.50'), 'total': ('Over', 'Under')}
    sides = [dict(id=mid+'L', long=True, marketId=mid, description=labels[family][0]),
             dict(id=mid+'S', long=False, marketId=mid, description=labels[family][1])]
    if family != 'total':
        for side, team in zip(sides, (AWAY, HOME), strict=True):
            side.update(team=team, teamId=team['id'])
    return dict(id=mid, slug='observed-native-'+mid, active=True, closed=False, archived=False,
                gameStartTime=KICKOFF, orderPriceMinTickSize=.01, minimumTradeQty=.01,
                sportsMarketType=KINDS[family], line=line, marketSides=sides,
                description=descriptions[family]+' Overtime is included if played.')


def event(selected):
    return dict(id='pmus-native-event', gameId=20, sportradarGameId='stable-utc-source',
                startTime=KICKOFF, period='NS', active=True, closed=False, archived=False,
                teams=[HOME, AWAY], markets=[selected])


def record(family, side, line, *, home='NBA:NYK', away='NBA:MIA'):
    participant = {'home': home, 'away': away}.get(side, 'combined')
    predicate = {'moneyline': 'win', 'spread': 'cover', 'total': side}[family]
    source = dict(provider='sportsgameodds', native_event_id='sgo-event', native_market_id=family,
                  native_outcome_id=side+str(line), deep_link='https://polymarket.com/event/wrong-jurisdiction')
    row = dict(event=dict(competition='NBA', home=home, away=away, scheduled_start=KICKOFF),
               quote=dict(venue='polymarket_us', source=source),
               market_identity=dict(family=family, period='full_game'),
               selection=dict(participant=participant, predicate=predicate, signed_line=line))
    return execution_contract.expected(row)['contract_id'], 'revision', row


def response(body):
    return httpx.Response(200, json=body, headers=HEADERS)


def fee_metadata():
    return {scanner_polymarket.PRODUCT: dict(last_attempt=dict(retrieval=dict(
        normalized_sha256=PMUS_CURRENT_HASH, document=dict(url=PMUS_TERMS, http_status=200,
                                                         retrieved_at='2026-11-27T20:00:00Z'))))}


def test_exact_family_catalog_binding_feeds_us_short_depth_and_size():
    winner = event(market('moneyline'))
    spread = event(market('spread', line=31.5))
    total = event(market('total', line=221.5))
    wrong_side = record('spread', 'away', '-31.5')
    selected = record('spread', 'home', '-31.5')
    home_win = record('moneyline', 'home', None)
    under = record('total', 'under', '221.5')
    calls = []

    def request(req):
        assert req.method == 'GET' and req.url.host == 'gateway.polymarket.us'
        calls.append(req.url.path)
        if req.url.path == '/v1/events':
            params = req.url.params
            assert params['tagSlug'] == 'nba' and params['period'] == 'NS' and params['offset'] == '0'
            assert params['startTimeMin'] == '2026-11-27T23:59:59+00:00'
            assert params['startTimeMax'] == '2026-11-28T00:00:01+00:00'
            return response({'events': [{KINDS['moneyline']: winner, KINDS['spread']: spread,
                                        KINDS['total']: total}[params['sportsMarketTypes']]]})
        assert req.url.path == '/v1/markets/observed-native-2/book'
        return response(dict(marketData=dict(marketSlug='observed-native-2', state='OPEN',
            transactTime='2026-11-27T23:49:59Z',
            bids=[dict(px=dict(currency='USD', value='.7'), qty='100')],
            offers=[dict(px=dict(currency='USD', value='.71'), qty='100')])))

    async def run():
        async with NativeExperimentDepth(client=httpx.AsyncClient(transport=httpx.MockTransport(request)),
                                         now=lambda: AT) as client:
            bindings = await dashboard_pmus.read(client, 'NBA',
                {'sgo-event': [wrong_side, selected, home_win, under]},
                at=AT, cutoff=AT+timedelta(seconds=3), products=fee_metadata())
            assert set(bindings) == {row[0] for row in (selected, home_win, under)}
            book = (await client.read_native({selected[0]: bindings[selected[0]]}, AT+timedelta(seconds=3)))[selected[0]]
            return bindings, book

    bindings, book = asyncio.run(run())
    assert calls.count('/v1/events') == 3
    assert bindings[home_win[0]]['outcome_id'] == '1S'
    assert bindings[under[0]]['outcome_id'] == '3S'
    assert book['event_id'] == 'pmus-native-event'
    assert book['market_id'] == '2' and book['outcome_id'] == '2S' and book['opposite_outcome_id'] == '2L'
    assert book['contract']['signed_line'] == '-63/2'
    assert book['levels'] == [dict(price='3/10', quantity='100')]
    assert book['quantity_minimum'] == book['quantity_increment'] == '0.01'
    assert book['fee']['coefficient'] == '0.11' and book['fee']['api_coefficient'] == '0.0695'
    result = evaluate_at_stake(book, at=AT, stake='25', probability='.45', minimum='.04',
                               expected=execution_contract.expected(selected[2]))
    assert result['status'] == 'full_size' and result['eligible']
    assert result['modeled_fee_usd'] != '0'


@pytest.mark.parametrize('conflict', ['swapped_teams', 'rescheduled', 'duplicate_occurrence', 'duplicate_strike'])
def test_conflicting_polymarket_occurrences_and_strikes_are_unmatched(conflict):
    selected = record('spread', 'home', '-31.5')
    winner = event(market('moneyline'))
    spread = event(market('spread', line=31.5))
    winners = [winner]
    if conflict == 'swapped_teams':
        selected = record('spread', 'home', '-31.5', home='NBA:MIA', away='NBA:NYK')
    elif conflict == 'rescheduled':
        spread['startTime'] = '2026-11-28T00:00:01Z'
    elif conflict == 'duplicate_occurrence':
        winners.append(dict(winner, id='different-event-same-names'))
    else:
        extra = deepcopy(spread['markets'][0])
        extra.update(id='8', slug='ambiguous-same-terms')
        for side in extra['marketSides']:
            side['marketId'] = '8'
            side['id'] = '8'+side['id'][-1]
        spread['markets'].append(extra)

    def request(req):
        assert req.url.path == '/v1/events'
        rows = winners if req.url.params['sportsMarketTypes'] == KINDS['moneyline'] else [spread]
        return response({'events': rows})

    async def run():
        async with NativeExperimentDepth(client=httpx.AsyncClient(transport=httpx.MockTransport(request)),
                                         now=lambda: AT) as client:
            return await dashboard_pmus.read(client, 'NBA', {'sgo-event': [selected]},
                at=AT, cutoff=AT+timedelta(seconds=3), products={})

    assert asyncio.run(run()) == {}


def test_slot_selector_rotates_unique_markets_and_keeps_both_sides():
    selector = dashboard_pmus.BookSelector()
    markets = {f'{market}-{side}': dict(venue='polymarket_us', market_id=str(market), reason=None)
        for market in range(8) for side in ('long', 'short')}
    markets['other'] = dict(venue='kalshi', market_id='2', reason=None)
    markets['unknown'] = dict(venue='polymarket_us', market_id='bad', reason='fee_unverified')
    events = {'sgo': [(cid, 'current', dict(comparison_source_metadata=dict(alternate=int(cid[0]) >= 4)))
                      for cid in markets if cid[0].isdigit()]}

    def selected(scope):
        result = selector.select(scope, markets, events)
        assert result['other'] is markets['other'] and result['unknown'] is markets['unknown']
        picks = {b['market_id'] for cid, b in result.items() if cid[0].isdigit() and b['reason'] is None}
        assert len(picks) == 4 and sum(int(m) >= 4 for m in picks) == 1
        for market in range(8):
            expected = None if str(market) in picks else 'native_book_capacity'
            assert result[f'{market}-long']['reason'] == result[f'{market}-short']['reason'] == expected
        return picks

    first = selected(('NBA', 'slot-1'))
    assert selected(('NBA', 'slot-2')) == first
    assert first == {'0', '1', '2', '4'}
    assert selected(('NBA', 'slot-1')) == {'0', '1', '3', '5'}
