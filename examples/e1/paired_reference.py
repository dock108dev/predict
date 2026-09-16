"""SDA parser traversal adaptation, local synthetic extraction probe only.

Source: sda b63ad4d985ab9e8d007767e2b97c78b4783d7c65
scraper/sports_scraper/odds/parser.py: parse_odds_events.
Rewritten here around one complete pair; no adapter, requests, registry or DB.
No upstream license found; no vendored source or redistribution clearance.
"""
from decimal import Decimal
from app.models.core import parse_decimal


def paired_rows(event, outcomes):
    """Keep both slots and stable book/market keys, reject ambiguous outcomes.

    Demonstrates the useful event -> book -> market -> outcome traversal only.
    E2 must provide source identity, exact rules, receipt time and mapping.
    """
    result = []
    for book in event.get('bookmakers', ()):
        for market in book.get('markets', ()):
            if market['key'] != 'h2h':
                continue
            sides = {}
            for row in market.get('outcomes', ()):
                name = row['name']
                if name not in outcomes or name in sides:
                    raise ValueError('third or duplicate outcome needs separate market assessment')
                price = None if row.get('price') is None else parse_decimal(row['price'])
                if price is not None and price <= 1:
                    raise ValueError('probe uses decimal odds, never inferred odds format')
                sides[name] = price
            result.append((event['id'], book['key'], market['key'],
                           tuple(sides.get(name) for name in outcomes)))
    return tuple(result)


def example():
    payload = {'id':'synthetic-atl-pit', 'bookmakers':[{'key':'invented-book-A',
        'markets':[{'key':'h2h','outcomes':[{'name':'PIT','price':'2.1000'},
                                         {'name':'ATL','price':'1.90000000000000000001'}]}]}]}
    result = paired_rows(payload, ('ATL','PIT'))
    assert result[0][3] == (Decimal('1.90000000000000000001'), Decimal('2.1000'))
    payload['bookmakers'][0]['markets'][0]['outcomes'].pop()
    assert paired_rows(payload, ('ATL','PIT'))[0][3][0] is None
    print('PASS: paired order, native keys, exact decimals and missing-side preservation')


if __name__ == '__main__':
    example()
