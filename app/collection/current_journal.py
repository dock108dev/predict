"""Append-only observation segments; reading never grants acquisition authority.

The original observations.jsonl is a permanent cursor identity. Segmented
writers seal it in place and continue in numbered files. No observation file is
renamed, truncated, overwritten or pruned by this implementation.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .odds_http import BudgetStop
from .current_storage_policy import (
    JOURNAL_BYTE_CAP, JOURNAL_RECORD_BYTE_CAP, JOURNAL_SEGMENT_BYTE_CAP,
    require_disk_space,
)


MANIFEST_VERSION = 'predict-current-journal-segments-1'
MANIFEST_BYTE_CAP = 256 * 1024
SEGMENT_COUNT_CAP = 1024
SEGMENT_PATTERN = re.compile(r'observations-([0-9]{6})\.jsonl\Z')


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _json(raw):
    def reject_constant(_):
        raise ValueError('nonfinite JSON')
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate JSON key')
            value[key] = item
        return value
    return json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_object)


class CurrentJournal:
    def __init__(self, directory, *, byte_cap=JOURNAL_SEGMENT_BYTE_CAP,
                 record_cap=JOURNAL_RECORD_BYTE_CAP, total_byte_cap=None,
                 compact_history=None):
        if not _integer(byte_cap) or byte_cap <= 0:
            raise ValueError('current_observation_storage_cap')
        if not _integer(record_cap) or record_cap <= 0:
            raise ValueError('current_observation_record_cap')
        # Existing small-cap fixtures keep their original single-file meaning.
        # Supplying total_byte_cap explicitly enables small segmented fixtures.
        if total_byte_cap is None:
            total_byte_cap = JOURNAL_BYTE_CAP if byte_cap == JOURNAL_SEGMENT_BYTE_CAP else byte_cap
        if not _integer(total_byte_cap) or total_byte_cap <= 0:
            raise ValueError('current_observation_storage_cap')
        self.path = Path(directory) / 'observations.jsonl'
        self.byte_cap = byte_cap
        self.total_byte_cap = total_byte_cap
        self.record_cap = record_cap
        self.records = 0
        self.manifest_path = self.path.parent / 'observations.manifest.json'
        self.temporary_path = self.path.parent / 'observations.manifest.tmp'
        self.lock_path = self.path.parent / 'observations.lock'
        self.segmented = total_byte_cap > byte_cap
        self.compact_history = (byte_cap == JOURNAL_SEGMENT_BYTE_CAP
            and record_cap == JOURNAL_RECORD_BYTE_CAP
            and total_byte_cap == JOURNAL_BYTE_CAP) if compact_history is None else bool(compact_history)
        self._verified = {}

    def _directory_sync(self):
        fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextmanager
    def _lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent.is_symlink():
            raise BudgetStop('current_observation_integrity_failed')
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'r+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            from .current_journal_domains import recover_domains
            try:
                recover_domains(self.path.parent,
                    lambda extra: self._check_budget(append_bytes=extra))
            except ValueError as exc:
                raise BudgetStop('current_observation_integrity_failed') from exc
            yield

    def _stat(self, path):
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise BudgetStop('current_observation_integrity_failed') from exc
        if not stat.S_ISREG(info.st_mode):
            raise BudgetStop('current_observation_integrity_failed')
        return info

    def _signature(self, path):
        info = self._stat(path)
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _digest_file(self, path, *, validate=False):
        digest = hashlib.sha256()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            if validate:
                while True:
                    raw = stream.readline(self.record_cap + 1)
                    if not raw:
                        break
                    if not raw.endswith(b'\n'):
                        if len(raw) > self.record_cap:
                            raise BudgetStop('current_observation_record_cap')
                        raise BudgetStop('current_observation_incomplete_tail')
                    if len(raw) > self.record_cap:
                        raise BudgetStop('current_observation_record_cap')
                    try:
                        self.read_record(_json(raw), path.parent)
                    except (ValueError, UnicodeError) as exc:
                        raise BudgetStop('current_observation_integrity_failed') from exc
                    digest.update(raw)
            else:
                for raw in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(raw)
        return digest.hexdigest()

    def _verify_file(self, path, *, sealed=None, need_digest=False):
        signature = self._signature(path)
        if sealed is not None and signature[2] != sealed['bytes']:
            raise BudgetStop('current_observation_integrity_failed')
        cached = self._verified.get(path.name)
        if cached is None or cached[0] != signature or ((sealed is not None or need_digest) and cached[1] is None):
            digest = self._digest_file(path, validate=sealed is None)
            # Detect replacement/modification during verification as well.
            if self._signature(path) != signature:
                raise BudgetStop('current_observation_integrity_failed')
            self._verified[path.name] = (signature, digest)
        else:
            digest = cached[1]
        if sealed is not None and digest != sealed['sha256']:
            raise BudgetStop('current_observation_integrity_failed')
        return signature[2], digest

    def _segment_path(self, index):
        return self.path.parent / f'observations-{index:06d}.jsonl'

    def _create_empty(self, path):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            if self._stat(path).st_size:
                raise BudgetStop('current_observation_integrity_failed')
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        self._directory_sync()

    def _manifest_raw(self, manifest):
        raw = json.dumps(manifest, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
        if len(raw) > MANIFEST_BYTE_CAP:
            raise BudgetStop('current_observation_segment_cap')
        return raw

    def _metadata_bytes(self):
        return sum(self._stat(path).st_size for path in (
            self.manifest_path, self.temporary_path, self.lock_path,
        ) if path.exists() or path.is_symlink())

    def _data_paths(self):
        paths = [self.path] if self.path.exists() or self.path.is_symlink() else []
        for path in self.path.parent.glob('observations-*.jsonl'):
            if SEGMENT_PATTERN.fullmatch(path.name) is None:
                raise BudgetStop('current_observation_manifest_corrupt')
            paths.append(path)
        return paths

    def _check_budget(self, *, append_bytes=0, new_manifest=None):
        from .current_journal_domains import artifact_usage
        data = sum((max(self._stat(path).st_size, self._stat(path).st_blocks * 512)
                    if self.compact_history else self._stat(path).st_size)
                   for path in self._data_paths())
        metadata = self._metadata_bytes()
        # Legacy tiny-cap fixtures retain their byte-exact single-file contract.
        # Ordinary journals charge actual allocated storage for every artifact.
        if self.compact_history:
            metadata = sum(max(self._stat(path).st_size, self._stat(path).st_blocks * 512)
                for path in (self.manifest_path, self.temporary_path, self.lock_path)
                if path.exists() or path.is_symlink())
        data += artifact_usage(self.path.parent)
        # The old manifest and complete replacement coexist until os.replace.
        # The fixed temporary file is overwritten rather than multiplied.
        if new_manifest is not None:
            temporary = self._stat(self.temporary_path).st_size if self.temporary_path.exists() else 0
            replacement = len(new_manifest)
            if self.compact_history:
                replacement = (replacement + 4095) // 4096 * 4096
                temporary = max(temporary, self._stat(self.temporary_path).st_blocks * 512) if temporary else 0
            metadata += max(0, replacement - temporary)
        if self.compact_history:
            append_bytes = (append_bytes + 4095) // 4096 * 4096
        if data + metadata + append_bytes > self.total_byte_cap:
            raise BudgetStop('current_observation_storage_cap')
        require_disk_space(self.path.parent, append_bytes + (len(new_manifest) if new_manifest else 0))

    def _publish_manifest(self, manifest, *, append_bytes=0):
        raw = self._manifest_raw(manifest)
        self._check_budget(append_bytes=append_bytes, new_manifest=raw)
        fd = os.open(self.temporary_path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(self.temporary_path, self.manifest_path)
        self._directory_sync()

    def _bootstrap(self, *, append_bytes=0):
        # Bootstrap and rotation may have crashed after creating an empty file.
        # Empty orphans are safe to adopt; unmanifested records are never inferred.
        extras = [p for p in self._data_paths() if p != self.path]
        next_path = self._segment_path(1)
        if extras and (extras != [next_path] or self._stat(next_path).st_size):
            raise BudgetStop('current_observation_manifest_corrupt')
        require_disk_space(self.path.parent, append_bytes + MANIFEST_BYTE_CAP)
        if not self.path.exists():
            self._create_empty(self.path)
        length, digest = self._verify_file(self.path, need_digest=True)
        manifest = dict(schema=MANIFEST_VERSION,
            sealed=[dict(name=self.path.name, index=0, bytes=length, sha256=digest)],
            active=dict(name=next_path.name, index=1))
        self._check_budget(append_bytes=append_bytes, new_manifest=self._manifest_raw(manifest))
        self._create_empty(next_path)
        self._publish_manifest(manifest, append_bytes=append_bytes)
        return manifest

    def _load_manifest(self):
        if self._stat(self.manifest_path).st_size > MANIFEST_BYTE_CAP:
            raise BudgetStop('current_observation_manifest_corrupt')
        fd = os.open(self.manifest_path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            raw = stream.read(MANIFEST_BYTE_CAP + 1)
        try:
            manifest = _json(raw)
            if set(manifest) != {'schema', 'sealed', 'active'} or manifest['schema'] != MANIFEST_VERSION:
                raise ValueError('manifest shape')
            sealed = manifest['sealed']
            if not isinstance(sealed, list) or not 1 <= len(sealed) < SEGMENT_COUNT_CAP:
                raise ValueError('segment count')
            for index, entry in enumerate(sealed):
                name = self.path.name if index == 0 else self._segment_path(index).name
                if (not isinstance(entry, dict) or set(entry) != {'name', 'index', 'bytes', 'sha256'}
                        or entry['name'] != name or not _integer(entry['index']) or entry['index'] != index
                        or not _integer(entry['bytes']) or entry['bytes'] < 0
                        or not isinstance(entry['sha256'], str)
                        or re.fullmatch(r'[0-9a-f]{64}', entry['sha256']) is None):
                    raise ValueError('sealed identity')
                if index and entry['bytes'] > self.byte_cap:
                    raise ValueError('sealed size')
            active = manifest['active']
            if (not isinstance(active, dict) or set(active) != {'name', 'index'}
                    or not _integer(active['index']) or active['index'] != len(sealed)
                    or active['name'] != self._segment_path(len(sealed)).name):
                raise ValueError('active identity')
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise BudgetStop('current_observation_manifest_corrupt') from exc
        expected = {entry['name'] for entry in sealed} | {active['name']}
        extras = [path for path in self._data_paths() if path.name not in expected]
        orphan = self._segment_path(active['index'] + 1)
        if extras and (extras != [orphan] or self._stat(orphan).st_size):
            raise BudgetStop('current_observation_manifest_corrupt')
        if self.temporary_path.exists() and self._stat(self.temporary_path).st_size > MANIFEST_BYTE_CAP:
            raise BudgetStop('current_observation_manifest_corrupt')
        for entry in sealed:
            self._verify_file(self.path.parent / entry['name'], sealed=entry)
        length, _ = self._verify_file(self.path.parent / active['name'])
        if length > self.byte_cap:
            raise BudgetStop('current_observation_storage_cap')
        return manifest, bool(extras)

    def _rotate(self, manifest, *, append_bytes=0):
        active = manifest['active']
        if active['index'] + 1 >= SEGMENT_COUNT_CAP:
            raise BudgetStop('current_observation_segment_cap')
        length, digest = self._verify_file(self.path.parent / active['name'], need_digest=True)
        next_path = self._segment_path(active['index'] + 1)
        updated = dict(schema=MANIFEST_VERSION, sealed=manifest['sealed'] + [
            dict(name=active['name'], index=active['index'], bytes=length, sha256=digest)
        ], active=dict(name=next_path.name, index=active['index'] + 1))
        self._check_budget(append_bytes=append_bytes, new_manifest=self._manifest_raw(updated))
        self._create_empty(next_path)
        self._publish_manifest(updated, append_bytes=append_bytes)
        return updated

    def _append_raw(self, path, raw):
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'r+b') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        self._directory_sync()
        # Prior bytes were verified under the same interprocess lock; this
        # successful write consists of one fully serialized valid record.
        self._verified[path.name] = (self._signature(path), None)

    def append(self, record):
        raw = json.dumps(record, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode() + b'\n'
        if len(raw) > self.record_cap:
            raise BudgetStop('current_observation_record_cap')
        if self.segmented and len(raw) > self.byte_cap:
            raise BudgetStop('current_observation_record_cap')
        require_disk_space(self.path.parent, len(raw))
        with self._lock():
            if self.compact_history:
                from .current_journal_domains import pack_record
                packed = pack_record(record, self.path.parent,
                    lambda extra: self._check_budget(append_bytes=extra))
                raw = json.dumps(packed, sort_keys=True, separators=(',', ':'),
                    ensure_ascii=False, allow_nan=False).encode() + b'\n'
                if len(raw) > self.record_cap or (self.segmented and len(raw) > self.byte_cap):
                    raise BudgetStop('current_observation_record_cap')
            if not self.segmented:
                if self.manifest_path.exists():
                    raise BudgetStop('current_observation_manifest_corrupt')
                if self.path.exists():
                    length, _ = self._verify_file(self.path)
                else:
                    length = 0
                if length + len(raw) > self.byte_cap:
                    raise BudgetStop('current_observation_storage_cap')
                self._check_budget(append_bytes=len(raw))
                self._append_raw(self.path, raw)
            else:
                if not self.manifest_path.exists():
                    manifest = self._bootstrap(append_bytes=len(raw))
                    orphan = False
                else:
                    manifest, orphan = self._load_manifest()
                path = self.path.parent / manifest['active']['name']
                if orphan or self._stat(path).st_size + len(raw) > self.byte_cap:
                    manifest = self._rotate(manifest, append_bytes=len(raw))
                    path = self.path.parent / manifest['active']['name']
                elif self.temporary_path.exists():
                    # Complete a stale metadata write from the validated state.
                    self._publish_manifest(manifest, append_bytes=len(raw))
                self._check_budget(append_bytes=len(raw))
                self._append_raw(path, raw)
            self.records += 1

    @staticmethod
    def read_record(record, directory):
        from .current_journal_domains import unpack_record
        return unpack_record(record, directory)

    def prepare(self):
        """Seal preserved history for an owned handover, without a fake record.

        The caller owns acquisition/lifecycle authority. This operation only
        prepares durable storage and never resumes dispatch or renews clocks.
        """
        with self._lock():
            if not self.segmented:
                if self.manifest_path.exists():
                    raise BudgetStop('current_observation_manifest_corrupt')
                if self.path.exists():
                    self._verify_file(self.path)
                    return [self.path]
                return []
            if not self.manifest_path.exists():
                manifest = self._bootstrap()
            else:
                manifest, orphan = self._load_manifest()
                if orphan:
                    manifest = self._rotate(manifest)
                elif self.temporary_path.exists():
                    self._publish_manifest(manifest)
                self._check_budget()
            return [self.path.parent / entry['name'] for entry in manifest['sealed']] + [
                self.path.parent / manifest['active']['name']
            ]

    def paths(self):
        """Ordered original and manifested segments; importer cursor paths stay fixed."""
        if not self.path.parent.exists():
            return []
        with self._lock():
            if not self.manifest_path.exists():
                if self.path.exists():
                    self._verify_file(self.path)
                    return [self.path]
                return []
            manifest, _ = self._load_manifest()
            return [self.path.parent / entry['name'] for entry in manifest['sealed']] + [
                self.path.parent / manifest['active']['name']
            ]

    segment_paths = paths

    def snapshot(self):
        if not self.path.parent.exists():
            return dict(path=str(self.path), bytes=0, total_bytes=0,
                byte_cap=self.byte_cap, total_byte_cap=self.total_byte_cap,
                active_path=str(self.path), active_bytes=0, segment_count=0,
                sealed_count=0, allocation_bytes=0, manifest_path=str(self.manifest_path),
                records_this_runtime=self.records, append_only=True, segmented=self.segmented)
        with self._lock():
            manifest = None
            if self.manifest_path.exists():
                manifest, orphan = self._load_manifest()
                paths = [self.path.parent / entry['name'] for entry in manifest['sealed']] + [
                    self.path.parent / manifest['active']['name']
                ]
                active = paths[-1]
            else:
                paths = [self.path] if self.path.exists() else []
                if paths:
                    self._verify_file(self.path)
                active = self.path
                orphan = False
            journal_bytes = sum(self._stat(path).st_size for path in paths)
            from .current_journal_domains import artifact_paths, artifact_usage
            domain_bytes = artifact_usage(self.path.parent)
            total = sum(self._stat(path).st_size for path in self._data_paths()) + self._metadata_bytes() + domain_bytes
            all_files = self._data_paths() + [p for p in (
                self.manifest_path, self.temporary_path, self.lock_path,
            ) if p.exists()] + artifact_paths(self.path.parent)
            allocation = sum(max(self._stat(p).st_size, self._stat(p).st_blocks * 512) for p in all_files)
            return dict(path=str(self.path), bytes=journal_bytes, total_bytes=total,
                byte_cap=self.byte_cap, total_byte_cap=self.total_byte_cap,
                active_path=str(active), active_bytes=self._stat(active).st_size if active.exists() else 0,
                segment_count=len(paths), sealed_count=len(manifest['sealed']) if manifest else 0,
                allocation_bytes=allocation, manifest_path=str(self.manifest_path),
                pending_rotation=orphan, records_this_runtime=self.records,
                append_only=True, segmented=self.segmented, domain_bytes=domain_bytes,
                compact_history=self.compact_history)
