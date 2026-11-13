"""Vendor fair odds are display-only, with no inferred clock or settlement."""
from fractions import Fraction


def comparison(record, rows, frame=None, *, index=None):
    """Find an exact captured SGO observation; do not splice receipt frames."""
    try:
        q=record['quote'];source=q['source'];original=q['original']
        if source['provider'] != 'sportsgameodds':
            return None
        def line(value):
            return None if value is None else Fraction(value)
        facts = (frame or {}).get('facts') or {}
        members = {}
        if facts.get('provider') == 'sportsgameodds' and facts.get('event_id') == source['native_event_id']:
            members = index.members if index is not None else dict(facts.get('members', ()))
        if index is not None:
            rows = index.selection(source['native_outcome_id'], source.get('native_line'))
        candidates = []
        for item in rows:
            f=item['facts'];fair=f.get('fair') or {}
            if (f.get('event_id') != source['native_event_id'] or f.get('odd_id') != source['native_outcome_id']
                    or f.get('venue') != q['venue'] or line(f.get('line')) != line(source.get('native_line'))
                    or f.get('price_american') != original.get('value')):
                continue
            original_receipt = (f.get('receipt_sha256') == q.get('provenance',{}).get('sha256')
                                and f.get('received_at') == q['times'].get('received_at'))
            metadata = record.get('comparison_source_metadata') or {}
            same_observation = (item.get('id') in members and members[item['id']] == item.get('revision')
                                and f.get('source_at') == q['times'].get('source_at')
                                and f.get('phase') == metadata.get('provider_phase')
                                and f.get('opposing_odd_id') == metadata.get('provider_opposing_odd_id')
                                and f.get('available') is (q.get('state') == 'available'))
            if not original_receipt and not same_observation:
                continue
            if not fair:
                continue
            # Keep the vendor's line distinct from the offer's line. This is
            # display context only and is never an input to offer-specific EV.
            same_line = line(fair.get('line')) == line(f.get('line'))
            candidate = {'provider':'sportsgameodds', 'price_american':fair['price_american'],
                'line':fair.get('line'), 'source_at':None, 'received_at':f['received_at'],
                'same_line':same_line, 'available':fair.get('available') is True,
                'meaning':'SportsGameOdds fair odds; original source time and contributors unknown'}
            consensus = f.get('consensus')
            if isinstance(consensus, dict):
                candidate['consensus'] = dict(consensus, received_at=f['received_at'],
                    same_line=line(consensus.get('line')) == line(f.get('line')))
            candidates.append(candidate)
        return candidates[0] if len(candidates)==1 else None
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None
