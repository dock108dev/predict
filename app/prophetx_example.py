"""Finite offline example using invented V4-shaped selections; no network."""
from datetime import datetime, timezone
from decimal import Decimal
from app.adapters.prophetx import Response, book, decode
from app.models.core import EvidenceKind

PAYLOAD = '''{"id":7,"name":"Invented example","type":"moneyline","selections":[
[{"outcome_id":1,"strike_id":"invented-a","name":"Invented A","price":-125.25,"quantity":12.345}],
[{"outcome_id":2,"strike_id":"invented-b","name":"Invented B","price":110,"quantity":5.25}]]}'''

def main():
    r = Response(PAYLOAD, 'synthetic:prophetx-example', datetime.now(timezone.utc), EvidenceKind.SYNTHETIC)
    b = book(r, '11', decode(PAYLOAD), streaming=True)
    print('SYNTHETIC ONLY: invented identities and numbers; not a venue capture.')
    for group in b.native_windows:
        for selection in group:
            print(selection.strike_id, 'native price:', selection.price,
                  'native quantity:', selection.quantity.value, 'unit:', selection.quantity.unit)
    print('Native window:', b.native_sync, 'advertised depth:', b.native_depth)
    for q in b.normalized_quotes:
        print('Normalized ask probability:', q.ask.price.value, '; sizing:', q.ask.quantity)
    print('Normalized sized book:', b.sync, '; market state:', b.state)
    print('American conversion is corroborated by separate sandbox evidence. This example is synthetic.')
    print('Quantity ownership, executable capacity and exchange timestamp scale remain unresolved.')

if __name__ == '__main__':
    main()
