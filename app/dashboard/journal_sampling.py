"""One sampler per durable journal, with the existing revision/15-second gate."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path

from app.storage.store import hashed, stamp


@contextmanager
def sampling_lease(journal):
    path = getattr(journal, "path", None)
    if path is None:
        yield None  # In-memory/custom adapters retain their local gate.
        return
    path = Path(path)
    if not path.is_absolute():
        raise ValueError("Absolute journal path required")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(str(path) + ".sampling.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+b") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


def shared_decision(state, identity, revision, at):
    gate = state.get("sampling_gate") if isinstance(state, dict) else None
    try:
        valid = (
            isinstance(gate, dict)
            and type(gate.get("schema")) is int
            and gate["schema"] == 1
            and gate.get("source") == hashed(identity)
            and type(gate.get("revision")) is int
        )
        if not valid:
            return True, True
        age = (at - stamp(gate["arb_at"])).total_seconds()
        if not 0 <= age < 15:
            return True, True
        return gate["revision"] != revision, False
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return True, True


def successful_gate(state, identity, revision, at, include_arbs):
    return dict(
        schema=1,
        source=hashed(identity),
        revision=revision,
        arb_at=at.isoformat() if include_arbs else state["sampling_gate"]["arb_at"],
    )
