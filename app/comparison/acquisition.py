"""Acquisition membership and the owner's whole-input receipt-span rule.

Source clocks are deliberately not acquisition clocks. Historical arithmetic
can still be reproduced without this contract; current promotion requires it.
"""
from app.storage.store import stamp

MAX_RECEIPT_SPAN_SECONDS = 600


def provenance(page):
    if not getattr(page, 'pull_id', None) or not getattr(page, 'attempt_id', None):
        return None
    return dict(pull_id=page.pull_id, attempt_id=page.attempt_id,
                receipt_sha256=page.receipt_sha256, received_at=page.received_at)


def offer_input(record):
    value = (record.get('comparison_source_metadata') or {}).get('acquisition')
    return dict(value or {}, received_at=record['quote']['times'].get('received_at'))


def validate(inputs):
    """Return an exportable witness, or refuse missing/mixed/too-wide inputs."""
    inputs = list(inputs)
    if not inputs or any(not item or not item.get('pull_id') or not item.get('attempt_id')
                         or not item.get('receipt_sha256') or not item.get('received_at') for item in inputs):
        raise ValueError('acquisition_membership_unverified')
    pulls = {item['pull_id'] for item in inputs}
    if len(pulls) != 1:
        raise ValueError('acquisition_pull_mismatch')
    clocks = [stamp(item['received_at']) for item in inputs]
    span = (max(clocks)-min(clocks)).total_seconds()
    if span > MAX_RECEIPT_SPAN_SECONDS:
        raise ValueError('acquisition_receipt_span_exceeded')
    return dict(pull_id=next(iter(pulls)), eligible=True,
                received_from=min(clocks).isoformat(), received_until=max(clocks).isoformat(),
                receipt_span_seconds=span, required_inputs=inputs)


def calculation(record, reference):
    prices = reference.get('required_input_prices', reference.get('prices', []))
    return validate([offer_input(record), *[dict(price.get('acquisition') or {},
        received_at=price.get('received_at')) for price in prices]])
