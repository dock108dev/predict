"""Isolated delivery diagnostic limits. Does not alter any existing profile."""
import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import time
from types import MappingProxyType
from uuid import uuid4

from app.dashboard.bounds import CaptureQueue, retained_bytes
from app.reference.records import packed
from .continuous import rss
from .journal_encoding import encode
from .odds_http import BudgetStop
from .segmented import SegmentedJournal, fsync_dir
from .supervised import NAME, PROFILE, RateBudget

MIB = 1024**2
CAP = MappingProxyType(dict(logical=20000, physical=20257, encoded_ingress=64*MIB,
    expanded_ingress=192*MIB, journal_bytes=72*MIB, expanded_physical=200*MIB,
    output=120*MIB, write_bytes=160*MIB, frames=4096, body=256*1024,
    primary_bytes=8*MIB, http_bytes=24*MIB, helper_bytes=8*MIB,
    metadata_bytes=8*MIB, finalization_bytes=32*MIB))


class Clock:
    def monotonic(self): return time.monotonic()
    def utc(self): return datetime.now(timezone.utc)
    def anchor(self):
        before = self.monotonic(); utc = self.utc(); after = self.monotonic()
        return dict(utc=utc.isoformat(), mono=(before+after)/2,
                    uncertainty=(after-before)/2,
                    resolution=time.get_clock_info('monotonic').resolution,
                    utc_offset=utc.timestamp()-(before+after)/2)


def raw_fields(raw):
    return dict(body_b64=base64.b64encode(raw).decode(), body_sha256=sha256(raw).hexdigest(),
                body_bytes=len(raw))


class Bodies:
    """One outstanding HTTP and one recv allocation. Failed partial bytes count."""
    def __init__(self):
        self.used = dict(http=0, primary=0); self.pending = {}; self.peak = 0

    def reserve(self, kind):
        if kind not in self.used or kind in self.pending: raise BudgetStop('pending_body_conflict')
        if self.used[kind]+CAP['body'] > CAP[kind+'_bytes']:
            raise BudgetStop(kind+'_body_cap')
        if sum(self.used.values())+sum(self.pending.values())+CAP['body'] > PROFILE['body_bytes']:
            raise BudgetStop('shared_body_cap')
        self.pending[kind] = CAP['body']
        self.peak = max(self.peak, sum(self.used.values())+sum(self.pending.values()))

    def finish(self, kind, size):
        if kind not in self.pending or not 0 <= size <= self.pending[kind]:
            raise BudgetStop('body_reservation_violation')
        self.pending.pop(kind); self.used[kind] += size


class Requests:
    def __init__(self):
        self.counts = dict(initial=0, refresh=0, reference=0)
        self.generations = [0, 0]; self.slots = set()

    def charge(self, kind, slot=None):
        if kind not in self.counts: raise ValueError('request kind')
        if kind == 'reference' and (slot not in range(60, 300, 15) or slot in self.slots):
            raise BudgetStop('reference_slot')
        generation = 0 if kind == 'initial' or (kind == 'reference' and slot < 120) else 1
        if (self.counts[kind] >= (16 if kind == 'reference' else 40) or
            sum(self.counts.values()) >= 96 or self.generations[generation] >= (44, 52)[generation]):
            raise BudgetStop('shared_request_cap')
        self.counts[kind] += 1; self.generations[generation] += 1
        if kind == 'reference': self.slots.add(slot)


class Records:
    """Authoritative records use the existing fsynced hash-chain and bounded queue.

    Metadata is append-only. Only history manifests are replaced, so the existing
    finalization receipt can independently reconcile cumulative file writes.
    """
    def __init__(self, output, clock=None, *, external_reserve=0):
        self.output = Path(output); self.clock = clock or Clock()
        if not 0<=external_reserve<=CAP['helper_bytes']:raise ValueError('external_reserve')
        self.external_reserve=external_reserve
        self.history = SegmentedJournal(self.output/'history', output_root=self.output,
            label='isolated Kalshi delivery diagnosis', profile_name=NAME)
        self.queue = CaptureQueue(48, 4*MIB); self.rate = RateBudget()
        self.received = self.accepted = self.rejected = self.durable = self.drained = 0
        self.failed = False; self.frames = 0; self.state_peak = 0

    def guard(self, additional=0, state=None, finalizing=False):
        if rss() >= (PROFILE['rss'] if finalizing else PROFILE['soft_rss']):
            raise BudgetStop('diagnostic_rss')
        if state is not None:
            size = retained_bytes(state); self.state_peak = max(self.state_peak, size)
            if size > PROFILE['state_bytes']: raise BudgetStop('diagnostic_state')
        a = self.history.accounting(); used = a['disk_bytes']
        reserved = (65536 if finalizing else CAP['finalization_bytes'])+self.external_reserve
        if used+additional+reserved > CAP['output']: raise BudgetStop('diagnostic_output')
        manifest_size = a['manifest_bytes']
        writes = used+self.history.manifest_write_bytes-manifest_size
        if writes+additional+reserved > CAP['write_bytes']: raise BudgetStop('diagnostic_writes')
        if shutil.disk_usage(self.output).free < PROFILE['disk_floor']+max(0,PROFILE['output']-used):
            raise BudgetStop('diagnostic_disk')

    def save(self, record_type, *, frame=False, **fields):
        self.received += 1
        row = dict(type=record_type, ingress_id=str(uuid4()), clock=self.clock.anchor(), **fields)
        try:
            encoded = len(packed(encode(row)).encode()); expanded = len(packed(row).encode())
            a = self.history.accounting()
            for key, value in dict(logical=a['logical']+1,
                encoded_ingress=a['encoded_ingress']+encoded,
                expanded_ingress=a['expanded_ingress']+expanded,
                physical=a['physical_records']+3,
                journal_bytes=a['journal_encoded_bytes']+encoded+65536,
                expanded_physical=a['journal_expanded_payload_bytes']+expanded+65536).items():
                if value > CAP[key]: raise BudgetStop('diagnostic_'+key)
            if max(encoded,expanded) > MIB: raise BudgetStop('diagnostic_row')
            if frame and self.frames >= CAP['frames']: raise BudgetStop('diagnostic_frames')
            self.guard(encoded+512, state=(row,self.queue))
            self.rate.admit(encoded,expanded,frame)
            self.history.save(row)
        except BaseException:
            self.rejected += 1; self.failed = True
            raise
        self.accepted += 1; self.durable += 1
        if frame: self.frames += 1
        try:
            self.queue.put_nowait(row)
            # Serial processing is deliberate: never accumulate a second raw queue.
            self.queue.get_nowait(); self.queue.task_done(); self.drained += 1
        except BaseException:
            self.failed = True
            raise
        return row

    def metadata(self, name, value, *, helper=False, finalizing=False):
        if Path(name).name != name: raise ValueError('metadata filename')
        body = (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
        ceiling = CAP['finalization_bytes'] if finalizing else CAP['helper_bytes' if helper else 'metadata_bytes']
        # Conservative: count all nonjournal payload against each applicable limit.
        used = sum(p.stat().st_size for p in self.output.iterdir() if p.is_file())
        if used+len(body) > ceiling: raise BudgetStop('metadata_cap')
        if 'manifest' in name and len(body)>PROFILE['manifest_bytes']: raise BudgetStop('manifest_cap')
        self.guard(len(body),finalizing=finalizing)
        with (self.output/name).open('xb',buffering=0) as f:
            if f.write(body)!=len(body): raise OSError('short metadata write')
            os.fsync(f.fileno())
        fsync_dir(self.output)

    def accounting(self):
        return dict(received=self.received,accepted=self.accepted,rejected=self.rejected,
            durable=self.durable,drained=self.drained,pending=self.queue.qsize(),
            unresolved=self.accepted-self.durable,
            durable_not_queued=self.durable-self.drained-self.queue.qsize(),
            frames=self.frames,queue_peak_objects=self.queue.high_items,
            queue_peak_bytes=self.queue.high_bytes,state_peak=self.state_peak,
            rss=rss(),**self.history.accounting())
