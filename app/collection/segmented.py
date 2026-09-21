"""D3a offline-only bounded history, using the existing lossless hash-chain journal.

Production has no transport integration. Explicit mock integration uses this same writer.
A restart always creates a new directory/run ID.
Replay is sequential from segment zero; checkpoints are deliberately not used.
"""
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from app.reference.records import packed
from .journal_encoding import VERSION as ENCODING, decode, encode
from .odds_http import BudgetStop
from .recovery import signature, strict_json
from .transport_session import ObservationJournal
from .continuous import rss

MIB = 1024 * 1024
VERSION = 'd3a-offline-segments-1'
POLICY = dict(logical=4096, segments=4, encoded_ingress=16*MIB,
              segment_logical=1024, segment_encoded=4*MIB, segment_expanded=8*MIB,
              reserve_bytes=65536, reserve_records=64, rss=256*MIB,
              queue_objects=48, queue_expanded=4*MIB, output=128*MIB, disk_floor=1024*MIB)
ZERO = '0'*64


def digest_file(path):
    h = sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(65536), b''): h.update(block)
    return h.hexdigest()


def iter_journal(path, *, tail=False):
    """Bounded physical line/expanded payload reading, including old encodings.

    A torn final line can be excluded only for explicit interrupted inspection;
    a complete corrupt line always fails. Yield one row and its verified offset.
    """
    chain = ZERO; offset = 0; expanded = 0; count = 0
    with Path(path).open('rb') as f:
        if os.fstat(f.fileno()).st_size > 32*MIB: raise ValueError('journal byte cap')
        while True:
            line = f.readline(32*MIB+1)
            if not line: break
            if len(line) > 32*MIB: raise ValueError('line byte cap')
            if not line.endswith(b'\n'):
                if tail: break
                raise ValueError('torn journal tail')
            value = strict_json(line)
            if set(value) != {'previous', 'sha256', 'row'}: raise ValueError('invalid envelope')
            expected = sha256((chain+packed(value['row'])).encode()).hexdigest()
            if value['previous'] != chain or value['sha256'] != expected: raise ValueError('journal chain mismatch')
            row = decode(value['row']); expanded += len(packed(row).encode()); count += 1
            if expanded > 32*MIB or count > 4096: raise ValueError('journal expanded/record cap')
            chain = expected; offset += len(line)
            yield row, dict(chain=chain, offset=offset, physical=count, expanded=expanded)


def fsync_dir(folder):
    fd = os.open(folder, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


class SegmentedJournal:
    def __init__(self, folder, *, label, fault=None, output_root=None, profile_name=None):
        from .supervised import profile
        self.policy = dict(profile(profile_name)) if profile_name else POLICY
        self.finalizing = False
        self.folder = Path(folder)
        self.output_root = Path(output_root) if output_root is not None else self.folder
        if not self.folder.resolve().is_relative_to(self.output_root.resolve()):
            raise ValueError("history must be inside output accounting root")
        self.folder.mkdir()  # Never resume, truncate or overwrite an existing run.
        self.lock = (self.folder/'writer.lock').open('xb')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.run = str(uuid4()); self.label = label; self.fault = fault or (lambda stage: None)
        self.segments = []; self.active = None; self.failed = False; self.closed = False
        self.logical = self.encoded = self.expanded = self.observations = 0
        self.control_writes = self.manifest_writes = self.manifest_write_bytes = 0
        self.admission_attempts = self.manifest_publications = 0
        self.local = None; self.terminal = False
        try:
            self._guard(); self._publish(False); self._open()
        except BaseException:
            self.abort(); raise

    def disk_bytes(self):
        return sum(p.stat().st_size for p in self.output_root.rglob('*') if p.is_file())

    def _guard(self, additional=0):
        if rss() >= self.policy['rss']: raise BudgetStop('offline_rss_cap')
        used = self.disk_bytes()
        reserve = max(0,self.policy['output']-used) if self.policy.get('name') else self.policy['output']
        if shutil.disk_usage(self.folder).free < self.policy['disk_floor']+reserve:
            raise BudgetStop('offline_disk_reservation')
        headroom = self.policy.get('finalization_reserve', self.policy['reserve_bytes']) if not self.finalizing else self.policy['reserve_bytes']
        if used+additional+headroom > self.policy['output']:
            raise BudgetStop('offline_output_reservation')

    def _open(self):
        if len(self.segments) >= self.policy['segments']: raise BudgetStop('offline_segment_cap')
        self.active = ObservationJournal(self.folder/f'segment-{len(self.segments):04d}.jsonl', encoding=ENCODING)
        self.local = dict(logical=0, observations=0, encoded=0, expanded=0)
        self.active.save(dict(type='d3_segment_start', format=VERSION, run=self.run,
            index=len(self.segments), previous=self.segments[-1]['chain'] if self.segments else ZERO,
            first_ordinal=self.observations, dependency='sequential-from-zero'))
        self.control_writes += 1
        self.fault('header_fsynced'); fsync_dir(self.folder); self.fault('segment_directory_fsynced')

    def _publish(self, complete):
        value = dict(format=VERSION, run=self.run, label=self.label, policy=self.policy,
            complete=complete, segments=self.segments, checkpoint_bytes=0,
            totals=dict(logical=self.logical, observations=self.observations,
                        encoded=self.encoded, expanded=self.expanded))
        body = (packed(value)+'\n').encode()
        if len(body) > self.policy.get('manifest_bytes',self.policy['reserve_bytes']): raise BudgetStop('manifest_cap')
        self._guard(len(body))
        with (self.folder/'manifest.pending').open('xb', buffering=0) as f:
            if f.write(body) != len(body): raise OSError('short manifest write')
            self.fault('manifest_written'); os.fsync(f.fileno()); self.fault('manifest_fsynced')
        self.manifest_writes += 1; self.manifest_write_bytes += len(body)
        os.replace(self.folder/'manifest.pending', self.folder/'manifest.json')
        self.fault('manifest_replaced'); fsync_dir(self.folder); self.fault('manifest_directory_fsynced')
        self.manifest_publications += 1

    def _seal(self, complete=False):
        self.active.save(dict(type='d3_segment_seal', run=self.run, index=len(self.segments),
                              totals=self.local, end_ordinal=self.observations))
        self.control_writes += 1; self.fault('seal_fsynced')
        self.active.close(); self.fault('segment_closed')
        self.segments.append(dict(name=self.active.path.name, chain=self.active.previous,
            sha256=digest_file(self.active.path), bytes=self.active.bytes,
            physical=self.active.count, expanded_physical=self.active.expanded_bytes, **self.local))
        self._publish(complete)

    def rotate(self):
        if self.failed or self.closed or self.terminal: raise ValueError('journal closed')
        if not self.local['observations']: return
        if len(self.segments)+1 >= self.policy['segments']: raise BudgetStop('offline_segment_cap')
        try: self._seal(); self._open()
        except BaseException:
            self.failed = True; raise

    def save(self, row):
        if self.failed or self.closed or self.terminal: raise ValueError('journal closed')
        if row['type'].startswith('d3_'): raise ValueError('reserved control type')
        terminal = row['type'] == 'session_finished'
        logical = 0 if terminal else 1
        encoded = len(packed(encode(row)).encode()); expanded = len(packed(row).encode())
        if self.logical+logical > self.policy['logical'] or self.encoded+(encoded if logical else 0) > self.policy['encoded_ingress']:
            raise BudgetStop('offline_run_ingress_cap')
        if terminal and (encoded > self.policy['reserve_bytes']//2 or expanded > self.policy['reserve_bytes']//2):
            raise BudgetStop('offline_terminal_cap')
        if logical and (encoded >= self.policy['segment_encoded']-self.policy['reserve_bytes']-1024 or expanded >= self.policy['segment_expanded']-self.policy['reserve_bytes']-1024):
            raise BudgetStop('offline_row_exceeds_segment')
        if self.policy.get('name'):
            totals=self.accounting()
            if (expanded>self.policy['row_bytes'] or encoded>self.policy['row_bytes'] or
                self.expanded+(expanded if logical else 0)>self.policy['expanded_ingress'] or
                totals['physical_records']+3>self.policy['physical'] or
                totals['journal_encoded_bytes']+encoded+65536>self.policy['journal_bytes'] or
                totals['journal_expanded_payload_bytes']+expanded+65536>self.policy['expanded_physical'] or
                totals['journal_encoded_bytes']+self.manifest_write_bytes+encoded+65536>
                    self.policy['write_bytes']-self.policy['finalization_reserve']):
                raise BudgetStop('supervised_history_budget')
        self._guard(encoded+512)
        if logical and (self.local['logical']+1 >= self.policy['segment_logical'] or
                self.active.bytes+encoded+512+self.policy['reserve_bytes'] >= self.policy['segment_encoded'] or
                self.active.expanded_bytes+expanded+self.policy['reserve_bytes'] >= self.policy['segment_expanded']):
            self.rotate()
        if self.active.count >= 4096-self.policy['reserve_records'] or self.active.bytes+encoded+512 >= 32*MIB-self.policy['reserve_bytes']:
            raise BudgetStop('offline_physical_reserve')
        self.admission_attempts += 1
        try: self.active.save(row)
        except BaseException:
            self.failed = True; raise
        self.observations += 1; self.local['observations'] += 1
        self.logical += logical; self.local['logical'] += logical
        self.encoded += encoded if logical else 0; self.local['encoded'] += encoded if logical else 0
        self.expanded += expanded if logical else 0; self.local['expanded'] += expanded if logical else 0
        self.terminal = terminal

    def finish(self, *, cleanup_complete):
        if self.failed or self.closed: raise ValueError('journal closed')
        try:
            self._seal(complete=bool(cleanup_complete and self.terminal))
            self.closed = True
        except BaseException:
            self.failed = True; raise
        finally:
            self.abort()

    def abort(self):
        try:
            if self.active and not self.active.file.closed: self.active.close()
        finally:
            if not self.lock.closed: self.lock.close()
            self.closed = True

    def accounting(self):
        sealed_names = {s['name'] for s in self.segments}
        active = self.active if self.active and self.active.path.name not in sealed_names else None
        def total(key, attribute):
            return sum(s[key] for s in self.segments)+(getattr(active, attribute) if active else 0)
        return dict(logical=self.logical, observations=self.observations,
            original_terminal_records=self.observations-self.logical,
            observation_write_attempts=self.admission_attempts,
            encoded_ingress=self.encoded, expanded_ingress=self.expanded,
            physical_records=total('physical', 'count'), control_records=self.control_writes,
            physical_write_attempts=sum(s['physical'] for s in self.segments)+(active.attempted if active else 0),
            journal_encoded_bytes=total('bytes', 'bytes'),
            journal_expanded_payload_bytes=total('expanded_physical', 'expanded_bytes'),
            manifest_records=1 if (self.folder/'manifest.json').exists() else 0,
            manifest_bytes=(self.folder/'manifest.json').stat().st_size if (self.folder/'manifest.json').exists() else 0,
            manifest_writes=self.manifest_writes, manifest_publications=self.manifest_publications,
            manifest_write_bytes=self.manifest_write_bytes, checkpoint_records=0, checkpoint_bytes=0,
            disk_bytes=self.disk_bytes())


class SegmentedReader:
    """Verified sequential iterator. No list of run rows, even during recovery.

    Holding a shared writer lock and binding signatures prevents reopening mutated
    originals. Recovery never promotes an unpublished tail to a completed run.
    """
    def __init__(self, folder):
        self.folder = Path(folder)
        self.policy = POLICY

    def _manifest(self):
        p = self.folder/'manifest.json'
        if p.stat().st_size > 256*1024: raise ValueError('manifest cap')
        m = strict_json(p.read_bytes())
        from .supervised import profile
        self.policy = dict(profile(m['policy']['name'])) if m['policy'].get('name') else POLICY
        if p.stat().st_size > self.policy.get('manifest_bytes',self.policy['reserve_bytes']): raise ValueError('manifest cap')
        if m['format'] != VERSION or m['policy'] != self.policy or m['checkpoint_bytes'] != 0:
            raise ValueError('unsupported history policy')
        if len(m['segments']) > self.policy['segments']: raise ValueError('segment cap')
        return m

    def _scan(self, m, *, recovery=False):
        previous = ZERO; ordinal = 0; logical = encoded = expanded = 0; terminal = False
        names = []
        for index, s in enumerate(m['segments']):
            name = f'segment-{index:04d}.jsonl'; names.append(name)
            if s['name'] != name: raise ValueError('segment order mismatch')
            path = self.folder/name
            if path.is_symlink() or path.stat().st_size != s['bytes'] or digest_file(path) != s['sha256']:
                raise ValueError('segment identity mismatch')
            local = dict(logical=0, observations=0, encoded=0, expanded=0); sealed = False
            for pos, (row, info) in enumerate(iter_journal(path)):
                if pos == 0:
                    if row != dict(type='d3_segment_start', format=VERSION, run=m['run'], index=index,
                        previous=previous, first_ordinal=ordinal, dependency='sequential-from-zero'):
                        raise ValueError('unresolved segment dependency')
                elif row['type'] == 'd3_segment_seal':
                    if sealed or row != dict(type='d3_segment_seal', run=m['run'], index=index,
                                            totals=local, end_ordinal=ordinal): raise ValueError('invalid seal')
                    sealed = True
                else:
                    if sealed or terminal or row['type'].startswith('d3_'): raise ValueError('record after terminal/seal')
                    terminal = row['type'] == 'session_finished'
                    ordinal += 1; local['observations'] += 1
                    if not terminal:
                        logical += 1; local['logical'] += 1
                        n = len(packed(encode(row)).encode()); e = len(packed(row).encode())
                        encoded += n; expanded += e; local['encoded'] += n; local['expanded'] += e
                    yield row
            if not sealed or any(s[k] != v for k, v in local.items()) or info != dict(
                    chain=s['chain'], offset=s['bytes'], physical=s['physical'], expanded=s['expanded_physical']):
                raise ValueError('segment accounting mismatch')
            if local['logical'] >= self.policy['segment_logical'] or s['bytes'] >= self.policy['segment_encoded'] or s['expanded_physical'] >= self.policy['segment_expanded']:
                raise ValueError('segment policy exceeded')
            previous = s['chain']
        if m['totals'] != dict(logical=logical, observations=ordinal, encoded=encoded, expanded=expanded):
            raise ValueError('run accounting mismatch')
        if logical > self.policy['logical'] or encoded > self.policy['encoded_ingress'] or expanded > self.policy.get('expanded_ingress',float('inf')): raise ValueError('run policy exceeded')
        if m['complete'] and not terminal: raise ValueError('complete manifest lacks source terminal')
        extras = sorted(p.name for p in self.folder.glob('segment-*.jsonl') if p.name not in names)
        if not recovery and (extras or not m['complete'] or not terminal): raise ValueError('incomplete run')
        if recovery:
            if len(extras) > 1 or (extras and extras != [f'segment-{len(names):04d}.jsonl']):
                raise ValueError('unexpected interrupted segments')
        self.summary = dict(manifest=m, unpublished=extras, verified_observations=ordinal)

    def rows(self, *, allow_interrupted=False):
        with (self.folder/'writer.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            m = self._manifest(); before = self.identities()
            # Verify the whole dependency chain before exposing usable books.
            for _ in self._scan(m, recovery=allow_interrupted): pass
            for row in self._scan(m, recovery=allow_interrupted):
                if rss() >= self.policy['rss']: raise BudgetStop('offline_replay_rss_cap')
                yield row
            if before != self.identities(): raise ValueError('history changed during replay')

    def identities(self):
        files = sorted(self.folder.iterdir())
        if len(files) > (self.policy['segments']+3 if self.policy.get('name') else 8): raise ValueError('unexpected history files')
        result = {}
        for p in files:
            if not p.is_file() or p.is_symlink(): raise ValueError('unexpected history entry')
            if p.stat().st_size > 32*MIB: raise ValueError('history file cap')
            result[p.name] = dict(signature(p.stat()), sha256=digest_file(p))
        if sum(x['size'] for x in result.values()) > self.policy['output']: raise ValueError('history output cap')
        return result

    def inspect(self):
        with (self.folder/'writer.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            m = self._manifest(); before = self.identities()
            for _ in self._scan(m, recovery=True): pass
            tail = None
            for name in self.summary['unpublished']:
                offset = 0; count = 0; sealed = False
                for row, info in iter_journal(self.folder/name, tail=True):
                    if count == 0:
                        expected = dict(type='d3_segment_start', format=VERSION, run=m['run'], index=len(m['segments']),
                            previous=m['segments'][-1]['chain'] if m['segments'] else ZERO,
                            first_ordinal=m['totals']['observations'], dependency='sequential-from-zero')
                        if row != expected: raise ValueError('interrupted dependency mismatch')
                    elif sealed: raise ValueError('record after unpublished seal')
                    sealed = row['type'] == 'd3_segment_seal'; offset = info['offset']; count += 1
                tail = dict(name=name, verified_physical=count, verified_offset=offset,
                    excluded_trailing_bytes=(self.folder/name).stat().st_size-offset,
                    qualification='unpublished physical prefix only; no durable acknowledgement inferred')
            if before != self.identities(): raise ValueError('history changed during inspection')
            return dict(format=VERSION, folder=str(self.folder.resolve()), sources=before,
                state='complete' if m['complete'] and not tail else 'interrupted',
                published=self.summary['verified_observations'], tail=tail,
                restart='new run directory and explicit source session boundary required')


def recovery_index(folder, destination):
    report = SegmentedReader(folder).inspect()
    body = dict(report, recovery_identity=sha256(packed(report).encode()).hexdigest())
    destination = Path(destination)
    if destination.resolve().is_relative_to(Path(folder).resolve()): raise ValueError('index must be separate')
    with destination.open('x') as f:
        f.write(packed(body)+'\n'); f.flush(); os.fsync(f.fileno())
    fsync_dir(destination.parent)
    return body


def reopen_recovery_index(path):
    body = strict_json(Path(path).read_bytes()); identity = body.pop('recovery_identity')
    if sha256(packed(body).encode()).hexdigest() != identity or SegmentedReader(body['folder']).inspect() != body:
        raise ValueError('indexed source or device changed')
    return dict(body, recovery_identity=identity)
