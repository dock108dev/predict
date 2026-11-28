"""Native book identity and ordering, independent of calculation and receipt clocks."""

from email.utils import parsedate_to_datetime

from app.storage.store import exact_time, hashed, stamp


IDENTITY = (
    "venue",
    "event_id",
    "market_id",
    "outcome_id",
    "opposite_outcome_id",
    "native_side",
)
MATERIAL = (
    *IDENTITY,
    "contract",
    "levels",
    "complete",
    "sequence",
    "source_at",
    "reason",
    "market_revision",
    "payout_usd",
    "currency",
    "quantity_increment",
    "quantity_minimum",
    "price_bands",
    "legal_prices",
    "fee",
)
WITHDRAWALS = frozenset(
    ("native_market_withdrawn", "native_market_halted", "native_identity_changed")
)


def identity(receipt):
    own = tuple(receipt.get(key) for key in IDENTITY)
    if receipt.get("venue") == "prophetx":
        # A strike ID must continue to identify the same provider outcome,
        # side and line across reads and restarts.
        contract = receipt.get("contract") or {}
        return (
            *own,
            str(receipt.get("native_outcome_id")),
            contract.get("selected_side"),
            contract.get("signed_line"),
        )
    return own


def revision(receipt):
    """Local retries and valuation times are not native market revisions."""
    return hashed({key: receipt[key] for key in MATERIAL if key in receipt})


def clock(receipt):
    """Use the source clock, otherwise the oldest HTTP cache-origin witness."""
    if receipt.get("source_at"):
        return exact_time(receipt["source_at"])
    clocks = []
    for proof in receipt.get("receipts", ()):
        headers = proof.get("headers") or proof
        date = headers.get("date")
        received = proof.get("received_at")
        if date and received:
            age = int(headers.get("age", "0"))
            if age < 0:
                raise ValueError("native_book_cache_age_invalid")
            origin = exact_time(parsedate_to_datetime(date).isoformat())
            arrival = exact_time(received)
            if origin > arrival:
                raise ValueError("native_book_source_clock_invalid")
            clocks.append(min(origin, arrival - age))
    return min(clocks) if clocks else None


def adopt(previous, incoming):
    """Return an admitted image or preserve the prior image with its original expiry.

    The publisher calls this under its transaction lock. Consequently the same
    rule applies to overlapping readers and to a new process after a restart.
    Failed reads never become book observations. Authoritative lifecycle changes
    must carry an exact identity and an ordered native witness.
    """
    if not previous:
        return incoming
    if incoming.get("reason") and incoming["reason"] not in WITHDRAWALS:
        return previous
    if identity(previous) != identity(incoming):
        return previous
    if previous.get("reason") and previous["reason"] not in WITHDRAWALS:
        return incoming
    if revision(previous) == revision(incoming):
        return previous
    before, after = clock(previous), clock(incoming)
    old_sequence, new_sequence = previous.get("sequence"), incoming.get("sequence")
    if (
        old_sequence is not None
        and new_sequence is not None
        and new_sequence < old_sequence
    ):
        return previous
    if incoming.get("reason") in WITHDRAWALS:
        # Exact lifecycle witnesses can revoke the same publication clock; a
        # dated older lifecycle response can never revoke a newer book.
        return (
            incoming
            if after is not None and (before is None or after >= before)
            else previous
        )
    if before is not None and (after is None or after < before):
        return previous
    if old_sequence is not None and old_sequence == new_sequence:
        return previous
    if before is not None and after == before:
        if old_sequence is None or new_sequence is None or old_sequence == new_sequence:
            return previous
    if stamp(incoming.get("received_at", incoming["valid_until"])) < stamp(
        previous.get("received_at", previous["valid_until"])
    ):
        return previous
    return incoming
