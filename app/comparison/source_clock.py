"""Source book currentness, independent of price changes and local activity."""
from datetime import timedelta
from app.storage.store import stamp


def evidence(quote):
    """An already content-bound ingress proof can date an unchanged book.

    Validate its seal and exact native instrument again on every projection.
    Invalid evidence refuses currentness; it never falls back to a price clock.
    """
    proof=quote.get('book_confirmation')
    if proof is None:return quote.get('times',{}).get('source_at'),'original_source',[]
    try:
        from app.collection.current_confirmation import validate
        source=quote['source']
        validate(proof,dict(venue=quote['venue'],event_id=source['native_event_id'],market_id=source['native_market_id']))
        original=quote.get('times',{}).get('source_at')
        if original is not None and stamp(original)>stamp(proof['confirmed_at']):
            return original,'original_source',[]
        return proof['confirmed_at'],proof['basis'],[]
    except (ValueError,KeyError,TypeError,AttributeError):
        return None,'invalid_confirmation',['book_confirmation_invalid']


def assess(quote, at):
    times=quote.get('times',{});source=times.get('source_at');receipt=times.get('received_at')
    clock,basis,reasons=evidence(quote);reasons=list(reasons)
    deadline=None
    try:
        if receipt is None:reasons.append('source_unknown')
        elif stamp(receipt)>at:reasons.append('source_future')
        if source is not None:
            if receipt is not None and stamp(source)>stamp(receipt):reasons.append('source_future_at_receipt')
            if stamp(source)>at:reasons.append('source_future')
        proof=quote.get('book_confirmation')
        if proof and stamp(proof['received_at'])>at:reasons.append('source_future')
        if clock is None:reasons.append('source_unknown')
        else:
            start=stamp(clock)
            deadline=start+timedelta(seconds=quote.get('freshness_policy',{}).get('maximum_age_seconds',900))
            if start>at:reasons.append('source_future')
            elif at>deadline:reasons.append('source_expired')
    except (ValueError,TypeError,KeyError,AttributeError):
        reasons.append('source_unknown');deadline=None
    return dict(clock_at=clock,basis=basis,current_until=None if deadline is None else deadline.isoformat(),
        reasons=sorted(set(reasons)))
