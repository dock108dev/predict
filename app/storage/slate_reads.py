"""Short lived detached ordinary-read frames; no database or provider ownership.

Only the selected compact view is retained, once, as immutable serialized game
records. Page envelopes are transient. The budget includes a conservative fixed
allowance for Python containers, tokens and per-page accounting.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
import json
import zlib
from secrets import token_urlsafe
from threading import RLock
from time import monotonic

from app.collection.current_policy import DEFAULT
from .store import encoded

MAX_FRAMES = 4
MAX_RETAINED_BYTES = 64 * 1024 * 1024
MAX_READ_BYTES = 80 * 1024 * 1024
TTL_SECONDS = 120


def process_bytes():
    # Admission measures live allocations. A prior, released capture's peak is
    # not resident memory and must not permanently deny subsequent refreshes.
    from app.collection.background_work import resident_bytes
    return resident_bytes()


@dataclass
class CapturedRead:
    token: str
    context: str
    authority: str
    deadline: float
    header: bytes
    records: tuple[bytes, ...]
    size: int
    page_bytes: dict = field(default_factory=dict)
    progress_offset: int = -1


class CapturedReads:
    def __init__(self, *, clock=monotonic, ttl_seconds=TTL_SECONDS,
                 maximum_frames=MAX_FRAMES, maximum_bytes=MAX_RETAINED_BYTES,
                 maximum_read_bytes=MAX_READ_BYTES, resource_bytes=process_bytes):
        if not 0 < ttl_seconds <= TTL_SECONDS or not 0 < maximum_frames <= MAX_FRAMES:
            raise ValueError('current_slate_read_capacity')
        if not 0 < maximum_bytes <= MAX_RETAINED_BYTES or not 0 < maximum_read_bytes <= MAX_READ_BYTES:
            raise ValueError('current_slate_read_capacity')
        self.clock = clock
        self.ttl_seconds = ttl_seconds
        self.maximum_frames = maximum_frames
        self.maximum_bytes = maximum_bytes
        self.maximum_read_bytes = maximum_read_bytes
        self.resource_bytes = resource_bytes
        self.frames = OrderedDict()
        self.retained_bytes = 0
        self.lock = RLock()
        self.on_capture = None

    def guard(self, additional_bytes=0):
        # This is the existing process guard, never an expanded read allowance.
        if self.resource_bytes() + additional_bytes >= DEFAULT['rss_bytes']:
            raise ValueError('current_slate_read_capacity')

    def discard(self, token):
        with self.lock:
            old = self.frames.pop(token, None)
            if old is not None:
                self.retained_bytes -= old.size

    def cleanup(self):
        with self.lock:
            now = self.clock()
            for token, frame in list(self.frames.items()):
                if now >= frame.deadline:
                    self.discard(token)

    def clear(self):
        with self.lock:
            self.frames.clear()
            self.retained_bytes = 0

    def capture(self, header, records, *, context, authority):
        """Take immutable bytes without evicting active pagination or Details."""
        with self.lock:
            self.cleanup()
            token = token_urlsafe(32)
            header = self.freeze(encoded(dict(header, read_token=token)))
            records = tuple(self.freeze(record) for record in records)
            size = len(header) + sum(map(len, records)) + 4096 + 256 * len(records)
            if size > self.maximum_bytes:
                raise ValueError('current_slate_read_capacity')
            self.guard(size)
            # Preflight eviction: a refused newcomer must leave all existing
            # evidence intact. Selected Details and active pages are protected.
            candidates = sorted((key for key,value in self.frames.items()
                                 if value.context in ('completed','displayed')),
                                key=lambda key: self.frames[key].context == 'displayed')
            victims=[];remaining_bytes=self.retained_bytes;remaining_count=len(self.frames)
            while remaining_count >= self.maximum_frames or remaining_bytes + size > self.maximum_bytes:
                if not candidates:
                    raise ValueError('current_slate_read_capacity')
                victim=candidates.pop(0);victims.append(victim)
                remaining_count-=1;remaining_bytes-=self.frames[victim].size
            for victim in victims:self.discard(victim)
            frame = CapturedRead(token, context, authority, self.clock() + self.ttl_seconds,
                                 header, records, size)
            self.frames[token] = frame
            self.retained_bytes += size
            if self.on_capture:self.on_capture(frame.token)
            return frame

    def get(self, token, *, context):
        with self.lock:
            self.cleanup()
            frame = self.frames.get(token)
            if frame is None:
                raise ValueError('current_slate_read_expired')
            if frame.context != context:
                raise ValueError('current_slate_read_context_changed')
            self.guard()
            return frame

    def authorize(self, frame, authority):
        with self.lock:
            if self.clock() >= frame.deadline:
                self.discard(frame.token)
                raise ValueError('current_slate_read_expired')
            if authority != frame.authority:
                self.discard(frame.token)
                raise ValueError('current_slate_read_authority_changed')

    def account(self, frame, *, offset, limit, size, complete):
        with self.lock:
            if size > self.maximum_read_bytes - sum(frame.page_bytes.values()) + frame.page_bytes.get((offset, limit), 0):
                self.discard(frame.token)
                raise ValueError('current_slate_read_capacity')
            frame.page_bytes[(offset, limit)] = size
            # Successful forward progress renews inactivity, not source clocks.
            # Replaying a page cannot keep an abandoned traversal alive forever.
            if offset > frame.progress_offset:
                frame.progress_offset = offset
                frame.deadline = self.clock() + self.ttl_seconds
                if frame.token in self.frames:
                    self.frames.move_to_end(frame.token)
            # Completed pages can still open an exact selected result. They
            # remain within the same four-frame/byte/TTL eviction budget.
            if complete:
                records=[]
                for record in frame.records:
                    self.guard(len(record)*8)
                    value=self.decode(record)
                    value.pop('_proof',None)
                    if value.get('row'):
                        value['row'].pop('_board_text',None)
                        value['row'].get('facts',{}).pop('boards',None)
                    records.append(self.freeze(encoded(value)))
                old_size=frame.size
                frame.records=tuple(records);frame.header=b'{}';frame.context='completed'
                frame.size=2+sum(map(len,records))+4096+256*len(records)
                self.retained_bytes+=frame.size-old_size

    def lease(self, token):
        """Keep a currently displayed completed frame selectable, within bounds."""
        with self.lock:
            self.cleanup()
            frame=self.frames.get(token)
            if frame is None:raise ValueError('current_slate_read_expired')
            if frame.context not in ('completed','displayed'):
                raise ValueError('current_slate_read_context_changed')
            self.guard()
            frame.context='displayed'
            frame.deadline=self.clock()+self.ttl_seconds
            self.frames.move_to_end(token)

    def selection(self, token, game):
        with self.lock:
            self.cleanup()
            frame = self.frames.get(token)
            if frame is None:raise ValueError('current_slate_read_expired')
            for record in frame.records:
                self.guard(len(record)*8)
                value = self.decode(record)
                if value['game_key'] == game:
                    if value.get('row') and '_facts_text' in value['row']:
                        value['row']['facts']=json.loads(value['row'].pop('_facts_text'))
                    if frame.context != 'selected':
                        # Retain only the opened game. A selected modal must
                        # not pin a 500-game pagination frame between polls.
                        selected=self.capture({},[record],context='selected',authority=frame.authority)
                        return value['row'],selected.token
                    # Reading renews only this bounded UI cache lease, never
                    # any source, confirmation or calculation clock.
                    frame.deadline = self.clock() + self.ttl_seconds
                    self.frames.move_to_end(token)
                    return value['row'],frame.token
            raise ValueError('current_selection_removed')

    @staticmethod
    def freeze(value):
        if value.startswith(b'PZ1') or len(value)<32768:return value
        return b'PZ1'+len(value).to_bytes(4,'big')+zlib.compress(value,1)

    def decode(self,value):
        if value.startswith(b'PZ1'):
            size=int.from_bytes(value[3:7],'big')
            if not 0<size<=MAX_READ_BYTES:raise ValueError('current_slate_read_capacity')
            self.guard(size*8)
            stream=zlib.decompressobj();body=stream.decompress(value[7:],size+1)
            if len(body)!=size or not stream.eof or stream.unused_data:raise ValueError('current_slate_read_capacity')
            value=body
        return json.loads(value)
