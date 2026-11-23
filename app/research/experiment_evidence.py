"""Content-addressed shared JSON for complete immutable checkpoint witnesses.

Only required checkpoint evidence is stored. Exact nested objects (event identity,
reference pairs, fee rules and cashflow facts) are interned once, even when many
offers or both checkpoints use them. Reopening needs only the exported records.
"""
import base64
import gzip
from hashlib import sha256
import json
import zlib

from app.storage.store import encoded, hashed

VERSION = "ev-checkpoint-shared-json-1"
REFERENCE = "$ev_checkpoint_ref"
INTERN_BYTES = 256
MAX_DEPTH = 96
GAME_METADATA_BYTES = 16 * 1024
ACCOUNTING_METADATA_BYTES = 4096
CHECKPOINT_ENVELOPE = "$ev_checkpoint_envelope"
COMPRESSED_SNAPSHOT = "$ev_checkpoint_gzip"
GZIP_VERSION = "ev-checkpoint-canonical-gzip-chunks-1"
GZIP_CHUNK_VERSION = "ev-checkpoint-gzip-chunk-1"
GZIP_CHUNK_BYTES = 512 * 1024
# A measured nine-book checkpoint is 11.84 MB canonical JSON. This bounds the
# decoder's memory independently from its much smaller retained gzip payload.
MAX_DECODED_CHECKPOINT_BYTES = 32 * 1024 * 1024
MAX_COMPRESSED_CHECKPOINT_BYTES = MAX_DECODED_CHECKPOINT_BYTES + 1024 * 1024


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
            if any(key in item for key in (REFERENCE,CHECKPOINT_ENVELOPE,COMPRESSED_SNAPSHOT)):
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


def pack_checkpoint(value):
    """Losslessly compress the full witness rather than thousands of tiny refs.

    Metadata remains shared JSON. The actual snapshot is canonical JSON, gzip
    encoded deterministically, then split into immutable content-hashed chunks.
    Every quote, reference, fee input and cashflow is retained without polling
    revisions or changing the allocation. Old shared-JSON records remain valid.
    """
    snapshot = value["snapshot"]
    pending = [(snapshot,0)]
    while pending:
        item,depth = pending.pop()
        if depth > MAX_DEPTH:
            raise ValueError("experiment_blob_depth")
        if isinstance(item,dict):
            if any(key in item for key in (REFERENCE,CHECKPOINT_ENVELOPE,COMPRESSED_SNAPSHOT)):
                raise ValueError("experiment_reserved_source_key")
            pending.extend((child,depth+1) for child in item.values())
        elif isinstance(item,list):
            pending.extend((child,depth+1) for child in item)
    original = encoded(snapshot)
    if len(original) > MAX_DECODED_CHECKPOINT_BYTES:
        raise ValueError("research_record_capacity")
    metadata,blobs = pack({key:item for key,item in value.items() if key != "snapshot"})

    def shared(item):
        root,parts = pack(item)
        blobs.update(parts)
        if isinstance(root,dict) and set(root) == {REFERENCE}:
            return root
        body = dict(version=VERSION,kind="blob",value=root)
        identity = hashed(body)
        blobs.setdefault(identity,body)
        return {REFERENCE:identity}

    packed_snapshot = dict(snapshot)
    if isinstance(snapshot.get("event"),dict):
        packed_snapshot["event"] = shared(snapshot["event"])
    if isinstance(snapshot.get("offers"),list):
        offers = []
        for offer in snapshot["offers"]:
            packed_offer = dict(offer)
            if isinstance(offer.get("fee_input"),(dict,list)):
                packed_offer["fee_input"] = shared(offer["fee_input"])
            if isinstance(offer.get("record"),dict):
                record = dict(offer["record"])
                if isinstance(record.get("event"),dict):
                    record["event"] = shared(record["event"])
                packed_offer["record"] = record
            offers.append(packed_offer)
        packed_snapshot["offers"] = offers
    external_refs = sorted(references(packed_snapshot))
    raw = encoded(packed_snapshot)
    if len(raw) > MAX_DECODED_CHECKPOINT_BYTES:
        raise ValueError("research_record_capacity")
    compressed = gzip.compress(raw,compresslevel=6,mtime=0)
    if len(compressed) > MAX_COMPRESSED_CHECKPOINT_BYTES:
        raise ValueError("research_record_capacity")
    chunks = []
    for offset in range(0,len(compressed),GZIP_CHUNK_BYTES):
        body = dict(version=GZIP_CHUNK_VERSION,kind="blob",encoding="base64",
                    data=base64.b64encode(compressed[offset:offset+GZIP_CHUNK_BYTES]).decode("ascii"))
        identity = hashed(body)
        blobs.setdefault(identity,body)
        chunks.append({REFERENCE:identity})
    manifest = dict(version=GZIP_VERSION,encoding="canonical-json+gzip+base64-chunks",
        sha256=sha256(raw).hexdigest(),decoded_bytes=len(raw),compressed_bytes=len(compressed),chunks=chunks,
        original_sha256=sha256(original).hexdigest(),original_bytes=len(original),
        shared_inputs=[{REFERENCE:identity} for identity in external_refs])
    return {CHECKPOINT_ENVELOPE:dict(metadata=metadata,snapshot={COMPRESSED_SNAPSHOT:manifest})},blobs


def _canonical_fingerprint(value):
    size = 0
    digest = sha256()
    encoder = json.JSONEncoder(sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
    for piece in encoder.iterencode(value):
        data = piece.encode()
        size += len(data)
        if size > MAX_DECODED_CHECKPOINT_BYTES:
            raise ValueError("experiment_checkpoint_decode_bound")
        digest.update(data)
    return size,digest.hexdigest()


def unpack(root, records):
    """Resolve one exact witness from a verified database/export record index."""
    active = set()
    cache = {}

    def visit(item, depth):
        if depth > MAX_DEPTH:
            raise ValueError("experiment_blob_depth")
        if isinstance(item,dict) and set(item) == {CHECKPOINT_ENVELOPE}:
            envelope = item[CHECKPOINT_ENVELOPE]
            metadata = visit(envelope["metadata"],depth+1)
            if not isinstance(metadata,dict) or "snapshot" in metadata:
                raise ValueError("experiment_checkpoint_envelope_invalid")
            return dict(metadata,snapshot=visit(envelope["snapshot"],depth+1))
        if isinstance(item,dict) and set(item) == {COMPRESSED_SNAPSHOT}:
            manifest = item[COMPRESSED_SNAPSHOT]
            decoded = manifest.get("decoded_bytes")
            original_bytes = manifest.get("original_bytes")
            compressed_size = manifest.get("compressed_bytes")
            chunks = manifest.get("chunks")
            if (manifest.get("version") != GZIP_VERSION or manifest.get("encoding") != "canonical-json+gzip+base64-chunks"
                    or type(decoded) is not int or not 0 < decoded <= MAX_DECODED_CHECKPOINT_BYTES
                    or type(compressed_size) is not int or not 0 < compressed_size <= MAX_COMPRESSED_CHECKPOINT_BYTES
                    or type(original_bytes) is not int or not 0 < original_bytes <= MAX_DECODED_CHECKPOINT_BYTES
                    or not isinstance(chunks,list) or not chunks
                    or len(chunks) > (MAX_COMPRESSED_CHECKPOINT_BYTES+GZIP_CHUNK_BYTES-1)//GZIP_CHUNK_BYTES):
                raise ValueError("experiment_checkpoint_decode_bound")
            pieces = [visit(chunk,depth+1) for chunk in chunks]
            if any(not isinstance(piece,bytes) or not 0 < len(piece) <= GZIP_CHUNK_BYTES for piece in pieces):
                raise ValueError("experiment_checkpoint_chunk_invalid")
            compressed = b"".join(pieces)
            if len(compressed) != compressed_size:
                raise ValueError("experiment_checkpoint_compressed_size")
            decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
            try:
                raw = decoder.decompress(compressed,decoded+1)
            except zlib.error as exc:
                raise ValueError("experiment_checkpoint_gzip_invalid") from exc
            if (len(raw) != decoded or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
                    or sha256(raw).hexdigest() != manifest.get("sha256")):
                raise ValueError("experiment_checkpoint_decoded_integrity")
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError,json.JSONDecodeError) as exc:
                raise ValueError("experiment_checkpoint_json_invalid") from exc
            if _canonical_fingerprint(value) != (len(raw),sha256(raw).hexdigest()):
                raise ValueError("experiment_checkpoint_json_not_canonical")
            if references(value) != references(manifest.get("shared_inputs")):
                raise ValueError("experiment_checkpoint_shared_dependencies")
            resolved = visit(value,depth+1)
            if _canonical_fingerprint(resolved) != (original_bytes,manifest.get("original_sha256")):
                raise ValueError("experiment_checkpoint_original_integrity")
            return resolved
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
            if hashed(body) != identity or body.get("kind") != "blob" or body.get("version") not in (VERSION,GZIP_CHUNK_VERSION):
                raise ValueError("experiment_blob_integrity")
            active.add(identity)
            if body["version"] == GZIP_CHUNK_VERSION:
                try:
                    value = base64.b64decode(body["data"],validate=True)
                except (ValueError,TypeError) as exc:
                    raise ValueError("experiment_checkpoint_chunk_invalid") from exc
                if body.get("encoding") != "base64" or not 0 < len(value) <= GZIP_CHUNK_BYTES:
                    raise ValueError("experiment_checkpoint_chunk_invalid")
            else:
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
