"""Short lived detached ordinary-read frames; no database or provider ownership.

Only the selected compact view is retained, once, as immutable serialized game
records. Page envelopes are transient. The budget includes a conservative fixed
allowance for Python containers, tokens and per-page accounting.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
import json
from secrets import token_urlsafe
from threading import RLock
from time import monotonic

from app.collection.current_policy import DEFAULT
from .store import encoded

MAX_FRAMES = 4
MAX_RETAINED_BYTES = 64 * 1024 * 1024
MAX_READ_BYTES = 80 * 1024 * 1024
TTL_SECONDS = 30


def process_bytes():
    from app.collection.continuous import rss
    return rss()


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
        """Take immutable bytes, evicting oldest unfinished/abandoned reads."""
        with self.lock:
            self.cleanup()
            token = token_urlsafe(32)
            header = encoded(dict(header, read_token=token))
            records = tuple(records)
            size = len(header) + sum(map(len, records)) + 4096 + 256 * len(records)
            if size > self.maximum_bytes:
                raise ValueError('current_slate_read_capacity')
            self.guard(size)
            while self.frames and (len(self.frames) >= self.maximum_frames or
                                   self.retained_bytes + size > self.maximum_bytes):
                self.discard(next(iter(self.frames)))
            frame = CapturedRead(token, context, authority, self.clock() + self.ttl_seconds,
                                 header, records, size)
            self.frames[token] = frame
            self.retained_bytes += size
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
            if complete:
                self.discard(frame.token)

    @staticmethod
    def decode(value):
        return json.loads(value)
