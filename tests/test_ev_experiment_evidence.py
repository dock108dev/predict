"""Shared immutable inputs and offline integrity, independent of PostgreSQL."""
from copy import deepcopy
import base64
import random
from unittest.mock import patch

import pytest

from app.research import experiment_evidence as evidence
from app.research.experiment_evidence import pack, pack_checkpoint, unpack
from app.storage.store import encoded, hashed


def test_shared_inputs_are_stored_once_and_reopen_without_source_reads():
    pair = dict(prices=[dict(book="reference", price="-110", facts="retained" * 100)])
    source = dict(offers=[dict(identity=index, pair=deepcopy(pair)) for index in range(30)])
    root, blobs = pack(source)
    assert unpack(root, blobs) == source
    assert sum(len(encoded(value)) for value in blobs.values()) < len(encoded(source))


def test_missing_or_changed_dependency_cannot_reproduce():
    root, blobs = pack(dict(source="immutable" * 100))
    with pytest.raises(ValueError, match="blob_missing"):
        unpack(root, {})
    changed = deepcopy(blobs)
    next(iter(changed.values()))["value"] = dict(source="changed")
    with pytest.raises(ValueError, match="blob_integrity"):
        unpack(root, changed)


def test_source_cannot_impersonate_an_internal_dependency_reference():
    with pytest.raises(ValueError, match="reserved_source_key"):
        pack({"$ev_checkpoint_ref": "0" * 64})


def compressed_example():
    event=dict(home="home",away="away",scheduled_start="2026-11-23T01:00:00Z")
    return dict(status="captured",known_at="2026-11-23T00:00:00Z",snapshot=dict(event=event,
        offers=[dict(record=dict(event=deepcopy(event)),fee_input=dict(rule="frozen",facts="shared"*100))],
        source_noise=random.Random(73).randbytes(800*1024).hex()))


def compressed_manifest(root):
    return root[evidence.CHECKPOINT_ENVELOPE]["snapshot"][evidence.COMPRESSED_SNAPSHOT]


def test_checkpoint_chunks_are_lossless_bounded_and_keep_shared_fee_identity():
    value=compressed_example()
    root,blobs=pack_checkpoint(value)
    manifest=compressed_manifest(root)
    assert len(manifest["chunks"])>=2
    assert max(len(encoded(row)) for row in blobs.values())<1024*1024
    assert unpack(root,blobs)==value
    changed=deepcopy(value);changed["known_at"]="2026-11-23T00:00:01Z"
    changed["snapshot"]["received_at"]="2026-11-23T00:00:01Z"
    second,other=pack_checkpoint(changed)
    assert evidence.references(manifest["shared_inputs"]) & evidence.references(compressed_manifest(second)["shared_inputs"])
    assert unpack(second,dict(blobs,**other))==changed
    # A pre-compression v1 witness remains readable by the same decoder.
    legacy,legacy_blobs=pack(value)
    assert unpack(legacy,legacy_blobs)==value


def test_checkpoint_digest_and_original_canonical_size_are_verified():
    value=compressed_example();root,blobs=pack_checkpoint(value)
    changed=deepcopy(root);compressed_manifest(changed)["original_sha256"]="0"*64
    with pytest.raises(ValueError,match="original_integrity"):
        unpack(changed,blobs)
    changed=deepcopy(root);compressed_manifest(changed)["decoded_bytes"]-=1
    with pytest.raises(ValueError,match="decoded_integrity"):
        unpack(changed,blobs)
    changed=deepcopy(root)
    identity=compressed_manifest(changed)["chunks"][0][evidence.REFERENCE]
    bad=deepcopy(blobs[identity]);raw=bytearray(base64.b64decode(bad["data"]));raw[len(raw)//2]^=1
    bad["data"]=base64.b64encode(raw).decode()
    bad_id=hashed(bad);bad_blobs=dict(blobs);bad_blobs[bad_id]=bad
    compressed_manifest(changed)["chunks"][0][evidence.REFERENCE]=bad_id
    with pytest.raises(ValueError,match="checkpoint_(gzip_invalid|decoded_integrity)"):
        unpack(changed,bad_blobs)


def test_checkpoint_decode_bound_is_checked_before_allocating_decoder():
    root,blobs=pack_checkpoint(compressed_example())
    compressed_manifest(root)["decoded_bytes"]=evidence.MAX_DECODED_CHECKPOINT_BYTES+1
    with patch.object(evidence.zlib,"decompressobj",side_effect=AssertionError("must_not_decode")):
        with pytest.raises(ValueError,match="decode_bound"):
            unpack(root,blobs)
