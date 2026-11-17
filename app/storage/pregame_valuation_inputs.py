"""Snapshot exact-side executable book inputs for ordinary pregame members."""
from fractions import Fraction as F

from app.comparison.pregame_valuation import MAX_LEVELS
from app.comparison.snapshot_fee_scope import applicability
from app.dashboard.current_contract import price

from .current_rows import CurrentRowStore, contract_id
from .store import hashed, stamp


def freeze(db, inputs):
    at = stamp(inputs['captured_at'])
    selected = {contract_id(q['original_record']): q for q in inputs['quotes'] if q.get('original_record')
        and q['venue'] in ('kalshi', 'polymarket_us') and q['source']['provider'] == q['venue']
        and stamp(q['start_at']) > at}
    books = CurrentRowStore(db).native_valuation_asks(selected, cap=MAX_LEVELS)
    for cid, q in selected.items():
        # Incremental price captures can carry an earlier quote object.
        # No book from a different receipt can overwrite or extend that quote.
        q.pop('valuation_fill_terms', None)
        book = books.get(cid)
        try:
            if (not book or stamp(book['received_at']) != stamp(q['times']['received_at'])
                    or stamp(book['received_at']) > at or F(book['levels'][0][0]) != price(q)
                    or F(q['original']['payout']) != 1):
                continue
            # Use a conservative whole-contract retail grid for Kalshi. The
            # Polymarket fee adapter validates the exact published market grid.
            values = (applicability(q['original_record']).get('retail') or {}).get('values') or {}
            step = '1' if q['venue'] == 'kalshi' else values['minimumTradeQty']
            if F(step) <= 0:
                continue
        except (ArithmeticError, KeyError, TypeError, ValueError):
            continue
        evidence = {key: book[key] for key in ('book_id', 'revision', 'depth_revision', 'source_at', 'received_at')}
        asks = [dict(price=level[0], quantity=level[2]) for level in book['levels']]
        terms = dict(kind='exchange', venue_type='marketplace', order_type='taker', increment=step, minimum=step,
                     evidence=evidence, asks=asks)
        q['valuation_fill_terms'] = dict(terms, revision=hashed(terms))
