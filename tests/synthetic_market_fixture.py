"""Authored, finite test data. No saved observations, provider or credential I/O."""
import base64
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import json

from app.arbitrage import book_observations
from app.models.core import (BookLevel, BookSync, Depth, EvidenceKind, Ladder,
    MarketState, NativeRef, OrderBook, OutcomeBook, Probability, Quantity,
    RawPayload, ReceiptFreshness, SourceTimeProgress, Venue)
from app.storage.workflow import packet

AT = '2026-09-16T12:00:00+00:00'


def us_market_data():
    return dict(id='381958', slug='aec-nfl-tb-cin-2026-09-13',
        question='SYNTHETIC Tampa Bay vs Cincinnati winner', marketType='moneyline',
        sportsMarketType='football_team_full_game_winner', status='OPEN',
        description='SYNTHETIC full game including overtime; tied game settles one half.',
        feeCoefficient='0.06', marketSides=[
            dict(id='763430', long=True, description='Tampa Bay Buccaneers',
                 team=dict(name='Tampa Bay Buccaneers')),
            dict(id='763431', long=False, description='Cincinnati Bengals',
                 team=dict(name='Cincinnati Bengals'))])


def session_rows():
    rows = []
    def row(typ, source='session', **values):
        value = dict(type=typ, source=source, session_id='b2-fixture',
            observed_at=AT, ingress_id='fixture-'+str(len(rows)), **values)
        rows.append(value)
        return value
    row('session_started', spec=dict(mode='mock', stale_seconds=30,
        assessment_revisions=dict(pairing=None, lineage=None, fees=None, settlement=None)))
    inventory = {v: dict(events=[], markets=[], selection=dict(ids=[]))
                 for v in ('kalshi', 'polymarket_us', 'novig')}
    games = [
        ('Buffalo Bills', 'Detroit Lions', 'NFL:BUF', 'NFL:DET',
         '2026-09-18T00:15:00+00:00', ('1315440', '1315441'), ('.6700', '.3200', '.3250', '.3300')),
        ('Atlanta Falcons', 'Carolina Panthers', 'NFL:ATL', 'NFL:CAR',
         '2026-09-20T17:00:00+00:00', ('1315462', '1315463'), ('.4300', '.5600', '.5600', '.5650')),
    ]
    row('coverage_inventory', generation=1, previous_generation=None, inventory=inventory)
    for i, (home, away, home_id, away_id, start, ids, prices) in enumerate(games):
        for venue, cat in inventory.items():
            eid, mid = venue+'-e'+str(i), venue+'-m'+str(i)
            sides = [dict(native_id=n, participant=p, predicate=pred,
                          native_label=n.upper() if venue=='kalshi' else ('Long' if j==0 else 'Short'))
                for j, (n, p, pred) in enumerate(
                    [('no', home, 'not_win'), ('yes', home, 'win')] if venue=='kalshi'
                    else [(ids[0], away, 'win'), (ids[1], home, 'win')])]
            event = dict(id=eid, title='SYNTHETIC '+away+' vs '+home, scheduled_start=start,
                canonical_key=['fixture-event-'+str(i)], sport='american_football',
                competition='NFL', season='2026', participants={home:home_id, away:away_id},
                identity='resolved', exclusion=None)
            cat['events'].append(event)
            cat['markets'].append(dict(id=mid, event_id=eid, market_type='moneyline',
                period='full_game', status='active', exclusion=None, product_outcomes=sides))
            cat['selection']['ids'].append(mid)
            if venue=='kalshi':
                native = dict(markets=[dict(ticker=mid, event_ticker=eid, title=home+' wins',
                    yes_sub_title=home, no_sub_title=home, status='active',
                    rules_primary='SYNTHETIC full-game winner including overtime.',
                    rules_secondary='SYNTHETIC tie resolves to $0.50; postponed game must begin within 48 hours; otherwise fair value.')])
            else:
                native = dict(markets=[dict(id=mid, title=event['title'], marketType='moneyline',
                    feeCoefficient='0.06', description='SYNTHETIC tie settles $0.50; game rescheduled to a date within two days; otherwise fair value.', marketSides=[dict(id=s['native_id'], long=j==0,
                        team=dict(name=s['participant'])) for j,s in enumerate(sides)])])
            raw = RawPayload(ref=NativeRef(venue=Venue(venue), event_id=eid, market_id=mid),
                source='synthetic://session/'+venue, received_at=datetime.fromisoformat(AT),
                json_text=json.dumps(native), exchange_at=datetime.fromisoformat(AT), kind=EvidenceKind.SYNTHETIC)
            meta = dict(raw=asdict(raw), title=event['title'], market_type='moneyline',
                state='active', period=None, canonical_id=None,
                outcomes=[dict(native_id=s['native_id'], label=s['participant'], canonical_id=None) for s in sides])
            row('market_selected', venue, market=json.loads(json.dumps(meta, default=str)))
            row('source_health', venue, state='connected', market_ids=[mid], stream_group=venue+str(i))
            def ladder(price, bid=False):
                return Ladder(depth=Depth.PARTIAL, levels=(BookLevel(
                    price=Probability(value=Decimal(price)),
                    quantity=Quantity(value=Decimal('1000000'), unit='contracts')), BookLevel(
                    price=Probability(value=Decimal(price)+(Decimal('-.01') if bid else Decimal('.01'))),
                    quantity=Quantity(value=Decimal('1000000'), unit='contracts'))))
            outcomes = (OutcomeBook(outcome_id='yes', bids=ladder(prices[0],bid=True)),
                        OutcomeBook(outcome_id='no', bids=ladder(prices[1],bid=True))) if venue=='kalshi' else (
                OutcomeBook(outcome_id=ids[0], bids=ladder(prices[2],bid=True), asks=ladder(prices[3])),
                OutcomeBook(outcome_id=ids[1]))
            book = OrderBook(raw=raw, quantity_unit='contracts', outcomes=outcomes,
                state=MarketState.UNKNOWN if venue=='kalshi' else MarketState.ACTIVE,
                sync=BookSync.SYNCHRONIZED, receipt_freshness=ReceiptFreshness.RECENT,
                source_time_progress=SourceTimeProgress.ADVANCED, sequence='1')
            packets = []
            for observation in book_observations(book, environment='synthetic',
                    evidence_class='synthetic', source_time_semantics='unknown'):
                value = packet(observation)
                value['raw_b64'] = base64.b64encode(value.pop('raw')).decode()
                packets.append(value)
            row('prediction_book', venue, book=json.loads(json.dumps(asdict(book), default=str)),
                packets=packets, stream_group=venue+str(i))
    return rows
