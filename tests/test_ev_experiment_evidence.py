"""Shared immutable inputs and offline integrity, independent of PostgreSQL."""
from copy import deepcopy

import pytest

from app.research.experiment_evidence import pack, unpack
from app.storage.store import encoded


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
