"""Bounded, process-local reuse of exact readiness preparation; no authority owner.

Current SQL and occurrence resolution precede lookup. Entries are immutable JSON
facts valid on one half-open temporal interval, never financial results or prices
whose original clocks have been renewed by a read.
"""

from bisect import bisect_right
from collections import OrderedDict
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock

from app.comparison.current_dependencies import digest, encoded, instant

INTERVAL_KEYS = frozenset(
    ("effective_from", "model_effective_from", "effective_to", "effective_until", "expires_at", "scheduled_ts")
)
MAX_REGISTRY_FILES = 256
MAX_REGISTRY_BYTES = 16 * 1024 * 1024
MAX_REGISTRY_BOUNDARIES = 65536


def _immutable(*args, **kwargs):
    raise TypeError("immutable_readiness_fact")


class _FrozenDict(dict):
    """Private JSON-compatible facts; ordinary copies deliberately thaw."""
    __slots__ = ()
    __init__ = __setitem__ = __delitem__ = __ior__ = _immutable
    clear = pop = popitem = setdefault = update = _immutable

    def __deepcopy__(self, memo):
        return _mutable_fact(self, memo)

    def __copy__(self):
        return _mutable_fact(self, {})

    def copy(self):
        return _mutable_fact(self, {})

    @classmethod
    def fromkeys(cls, keys, value=None):
        return _freeze_fact(dict.fromkeys(keys, value))


class _FrozenList(list):
    __slots__ = ()
    __init__ = __setitem__ = __delitem__ = __iadd__ = __imul__ = _immutable
    append = clear = extend = insert = pop = remove = reverse = sort = _immutable

    def __deepcopy__(self, memo):
        return _mutable_fact(self, memo)

    def __copy__(self):
        return _mutable_fact(self, {})

    def copy(self):
        return _mutable_fact(self, {})


def is_immutable_fact(value):
    """Recognize only this private cache's recursively frozen JSON containers."""
    return type(value) in (_FrozenDict, _FrozenList)


def _freeze_fact(value, memo=None):
    if is_immutable_fact(value):
        return value
    memo = {} if memo is None else memo
    identity = id(value)
    if identity in memo:
        return memo[identity]
    if isinstance(value, dict):
        # Public put historically follows JSON object-key normalization. Normal
        # readiness facts already have string keys, without this rare fallback.
        if any(type(key) is not str for key in value):
            result = _freeze_fact(json.loads(encoded(value)))
            memo[identity] = result
            return result
        result = dict.__new__(_FrozenDict)
        memo[identity] = result
        for key, child in value.items():
            dict.__setitem__(result, key, _freeze_fact(child, memo))
        return result
    if isinstance(value, (list, tuple)):
        result = list.__new__(_FrozenList)
        memo[identity] = result
        for child in value:
            list.append(result, _freeze_fact(child, memo))
        return result
    if value is None or type(value) in (str, int, float, bool):
        return value
    # JSON-compatible scalar subclasses must not retain mutable attributes.
    return json.loads(encoded(value))


def _mutable_fact(value, memo):
    identity = id(value)
    if identity in memo:
        return memo[identity]
    if isinstance(value, dict):
        result = {}
        memo[identity] = result
        result.update((key, _mutable_fact(child, memo)) for key, child in value.items())
        return result
    if isinstance(value, list):
        result = []
        memo[identity] = result
        result.extend(_mutable_fact(child, memo) for child in value)
        return result
    return value


def boundaries(value):
    """Include inactive applicability records, not only attached current models."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in INTERVAL_KEYS and isinstance(child, str):
                try:
                    yield instant(child)
                except ValueError:
                    # Fixture schemas and refusal examples also name these
                    # fields. They grant no temporal authority; real input
                    # validation remains the unchanged model owner's job.
                    pass
            if isinstance(child, (dict, list)):
                yield from boundaries(child)
    elif isinstance(value, list):
        for child in value:
            yield from boundaries(child)


class PreparationCache:
    def __init__(self, *, max_entries=500, max_bytes=32 * 1024 * 1024):
        if type(max_entries) is not int or not 1 <= max_entries <= 500:
            raise ValueError("readiness_cache_entry_capacity")
        if type(max_bytes) is not int or not 1 <= max_bytes <= 64 * 1024 * 1024:
            raise ValueError("readiness_cache_byte_capacity")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries = OrderedDict()
        self._bytes = self.hits = self.misses = self.evictions = 0
        self._registry = {}
        self._lock = RLock()

    def get(self, key, *, at):
        """Ordinary callers receive fully mutable detached JSON containers."""
        from copy import deepcopy
        value = self.get_shared(key, at=at)
        return deepcopy(value)

    def get_shared(self, key, *, at):
        """Private capture reuse only; fresh SQL and exact key still precede it."""
        moment = instant(at)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or not entry[0] <= moment < entry[1]:
                self.misses += 1
                if entry is not None:
                    self._bytes -= self._entries.pop(key)[3]
                return None
            self.hits += 1
            self._entries.move_to_end(key)
            return entry[2]

    def put(self, key, value, *, at, until):
        start, end = instant(at), instant(until)
        if not isinstance(key, str) or not key or len(key) > 256:
            raise ValueError("readiness_cache_key_invalid")
        # Charge the exact previous JSON envelope representation, then retain
        # only one frozen tree. This is an encoded-size cap, not a heap claim.
        size = len(encoded(dict(at=at, until=until, value=value))) + len(key.encode())
        with self._lock:
            previous = self._entries.pop(key, None)
            if previous is not None:
                self._bytes -= previous[3]
            if end <= start or size > self.max_bytes:
                return False
            self._entries[key] = (start, end, _freeze_fact(value), size)
            self._bytes += size
            while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
                self._bytes -= self._entries.popitem(last=False)[1][3]
                self.evictions += 1
        return True

    def prune(self, keys):
        keys = set(keys)
        with self._lock:
            for key in tuple(self._entries):
                if key not in keys:
                    self._bytes -= self._entries.pop(key)[3]

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            self._registry.clear()

    def stats(self):
        with self._lock:
            return dict(entries=len(self._entries), bytes=self._bytes, hits=self.hits,
                        misses=self.misses, evictions=self.evictions)

    def registry(self, *, at):
        """Bind all shipped fact registries and their upcoming temporal boundary.

        Contents are freshly hashed; parsed metadata is retained only while its
        exact bytes match. No source acquisition, mutable file stat shortcut or
        readiness grant is involved.
        """
        moment = instant(at)
        root = Path(__file__).resolve().parents[1] / "fixtures"
        paths = sorted(root.rglob("*.json"))
        if len(paths) > MAX_REGISTRY_FILES:
            raise ValueError("readiness_registry_file_capacity")
        versions, dates, total = {}, set(), 0
        with self._lock:
            for path in paths:
                raw = path.read_bytes()
                total += len(raw)
                if total > MAX_REGISTRY_BYTES:
                    raise ValueError("readiness_registry_byte_capacity")
                name = str(path.relative_to(root))
                version = sha256(raw).hexdigest()
                prior = self._registry.get(name)
                if prior is None or prior[0] != version:
                    prior = version, tuple(boundaries(json.loads(raw)))
                    self._registry[name] = prior
                versions[name] = version
                dates.update(prior[1])
                if len(dates) > MAX_REGISTRY_BOUNDARIES:
                    raise ValueError("readiness_registry_boundary_capacity")
            self._registry = {name: self._registry[name] for name in versions}
        dates = sorted(dates)
        offset = bisect_right(dates, moment)
        return digest(versions), dates[offset].isoformat() if offset < len(dates) else None
