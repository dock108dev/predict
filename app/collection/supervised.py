"""Explicit offline five-minute policy; never selected by the production factory."""
from collections import deque
import heapq
from pathlib import Path
import time
from types import MappingProxyType
from uuid import UUID
from app.dashboard.bounds import retained_bytes
from .odds_http import BudgetStop

NAME = 'predict-supervised-segmented-5m-v1'
MIB = 1024**2
PROFILE = MappingProxyType(dict(name=NAME, duration=300, refresh_seconds=120, generations=2,
    logical=65536, physical=65793, encoded_ingress=160*MIB, expanded_ingress=512*MIB,
    journal_bytes=176*MIB, expanded_physical=520*MIB, segments=128,
    segment_logical=1024, segment_encoded=4*MIB, segment_expanded=8*MIB,
    reserve_bytes=65536, reserve_records=64, rss=256*MIB, soft_rss=224*MIB,
    queue_objects=48, queue_expanded=4*MIB, output=224*MIB, disk_floor=1024*MIB,
    finalization_reserve=32*MIB, write_bytes=256*MIB, manifest_bytes=256*1024,
    row_bytes=MIB, frames=24000, group_messages=20000, body_bytes=64*MIB,
    requests=128, generation_requests=64, groups=12, connections=24, sockets=6,
    state_bytes=64*MIB, diagnostic_bytes=MIB, finalization_seconds=300))

def profile(name):
    if name != NAME: raise ValueError('unknown supervised profile')
    return PROFILE

class Samples(list):
    """Bounded non-authoritative diagnostics; raw evidence lives in the journal."""
    def __init__(self, limit=128): super().__init__(); self.limit=limit; self.total=0
    def append(self, value):
        self.total += 1
        if self.limit:
            super().append(value)
            if len(self)>self.limit: del self[0]

def bound_native(obj):
    for key in ('frames','responses'):
        if hasattr(obj,key): setattr(obj,key,Samples(0))
    for key in ('events','diagnostics'):
        if hasattr(obj,key): setattr(obj,key,Samples())
    if hasattr(obj,'engine'): bound_native(obj.engine)

def native_state(obj):
    keys=('markets','last','sides','native_ids','source_highwater','source_time_high_water',
          'frames','responses','events','diagnostics','gaps','previous_books','counts')
    state={k:getattr(obj,k) for k in keys if hasattr(obj,k)}
    if hasattr(obj,'engine'): state['engine']=native_state(obj.engine)
    if hasattr(obj,'engines'): state['engines']={k:native_state(v) for k,v in obj.engines.items()}
    return state

class RateBudget:
    def __init__(self): self.rows=deque(); self.frames=deque(); self.peak={}; self.frame_count=0
    def admit(self, encoded, expanded, frame=False):
        now=time.monotonic()
        while self.rows and now-self.rows[0][0]>=1: self.rows.popleft()
        while self.frames and now-self.frames[0]>=1: self.frames.popleft()
        values=(len(self.rows)+1, sum(r[1] for r in self.rows)+encoded,
                sum(r[2] for r in self.rows)+expanded)
        if any(v>cap for v,cap in zip(values,(1024,8*MIB,32*MIB))): raise BudgetStop('supervised_ingress_rate')
        if frame and (self.frame_count>=PROFILE['frames'] or len(self.frames)>=256):
            raise BudgetStop('supervised_frame_budget')
        self.rows.append((now,encoded,expanded))
        if frame: self.frames.append(now); self.frame_count+=1
        for key,v in zip(('rows','encoded','expanded','frames'),(*values,len(self.frames))):
            self.peak[key]=max(self.peak.get(key,0),v)

class ExactIdentities:
    """Exact external merge of bounded sorted UUID chunks; no run-sized set."""
    def __init__(self, folder):
        self.folder=Path(folder); self.folder.mkdir(); self.chunk=[]; self.paths=[]; self.count=0
    def add(self, value):
        uid=UUID(value)
        if str(uid)!=value: raise ValueError('noncanonical ingress identity')
        if self.count>=PROFILE['logical']: raise BudgetStop('identity_count_cap')
        self.chunk.append(uid.bytes); self.count+=1
        if len(self.chunk)==4096: self.flush()
    def flush(self):
        if not self.chunk:return
        path=self.folder/f'{len(self.paths):02d}.uuid'
        with path.open('xb') as f:
            for uid in sorted(self.chunk): f.write(uid)
        self.paths.append(path); self.chunk.clear()
    def finish(self):
        self.flush()
        def entries(path):
            with path.open('rb') as f:
                while value:=f.read(16):
                    if len(value)!=16: raise ValueError('torn identity spool')
                    yield value
        previous=None
        for value in heapq.merge(*(entries(p) for p in self.paths)):
            if value==previous: raise ValueError('duplicate observation identity')
            previous=value
        return self.count
