"""Content-addressed shared JSON for complete immutable checkpoint witnesses.

Only required checkpoint evidence is stored. Exact nested objects (event identity,
reference pairs, fee rules and cashflow facts) are interned once, even when many
offers or both checkpoints use them. Reopening needs only the exported records.
"""
from app.storage.store import encoded, hashed

VERSION = "ev-checkpoint-shared-json-1"
REFERENCE = "$ev_checkpoint_ref"
INTERN_BYTES = 256
MAX_DEPTH = 96
GAME_METADATA_BYTES = 16 * 1024
ACCOUNTING_METADATA_BYTES = 4096


def references(value):
    if isinstance(value, dict):
        if set(value) == {REFERENCE}:
            identity = value[REFERENCE]
            if not isinstance(identity, str) or len(identity) != 64:
                raise ValueError("experiment_blob_reference_invalid")
            return {identity}
        return set().union(*(references(child) for child in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(references(child) for child in value)) if value else set()
    return set()


def pack(value):
    """Return a packed root and dependency records without touching a database."""
    blobs = {}

    def visit(item, depth):
        if depth > MAX_DEPTH:
            raise ValueError("experiment_blob_depth")
        if isinstance(item, dict):
            if REFERENCE in item:
                raise ValueError("experiment_reserved_source_key")
            node = {key: visit(child, depth + 1) for key, child in item.items()}
        elif isinstance(item, list):
            node = [visit(child, depth + 1) for child in item]
        else:
            return item
        if len(encoded(node)) < INTERN_BYTES:
            return node
        body = dict(version=VERSION, kind="blob", value=node)
        identity = hashed(body)
        blobs.setdefault(identity, body)
        return {REFERENCE: identity}

    return visit(value, 0), blobs


def unpack(root, records):
    """Resolve one exact witness from a verified database/export record index."""
    active = set()
    cache = {}

    def visit(item, depth):
        if depth > MAX_DEPTH:
            raise ValueError("experiment_blob_depth")
        if isinstance(item, dict) and set(item) == {REFERENCE}:
            identity = item[REFERENCE]
            if identity in active:
                raise ValueError("experiment_blob_cycle")
            if identity in cache:
                return cache[identity]
            row = records.get(identity)
            if row is None:
                raise ValueError("experiment_blob_missing")
            body = row.get("payload", row)
            if hashed(body) != identity or body.get("kind") != "blob" or body.get("version") != VERSION:
                raise ValueError("experiment_blob_integrity")
            active.add(identity)
            value = visit(body["value"], depth + 1)
            active.remove(identity)
            cache[identity] = value
            return value
        if isinstance(item, dict):
            return {key: visit(child, depth + 1) for key, child in item.items()}
        if isinstance(item, list):
            return [visit(child, depth + 1) for child in item]
        return item

    return visit(root, 0)
