"""Vendor fair odds are display-only, with no inferred clock or settlement."""
from fractions import Fraction


def comparison(record, rows):
    """Find an exact captured SGO observation; do not splice receipt frames."""
    try:
        q=record['quote'];source=q['source'];original=q['original']
        if source['provider'] != 'sportsgameodds':
            return None
        def line(value):
            return None if value is None else Fraction(value)
        candidates=[]
        for item in rows:
            f=item['facts'];fair=f.get('fair') or {}
            if (f.get('event_id') != source['native_event_id'] or f.get('odd_id') != source['native_outcome_id']
                    or f.get('venue') != q['venue'] or line(f.get('line')) != line(source.get('native_line'))
                    or f.get('price_american') != original.get('value')
                    or f.get('receipt_sha256') != q.get('provenance',{}).get('sha256')
                    or f.get('received_at') != q['times'].get('received_at')):
                continue
            if fair.get('available') is not True or fair.get('price_american') is None:
                continue
            candidates.append({'provider':'sportsgameodds', 'price_american':fair['price_american'],
                'line':fair.get('line'), 'source_at':None, 'received_at':f['received_at'],
                'available':True, 'meaning':'Vendor comparison; original source time and contributors unknown'})
        return candidates[0] if len(candidates)==1 else None
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None
