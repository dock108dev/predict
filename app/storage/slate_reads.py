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
    record_keys: tuple = ()
    packet_store: object = None
    packet_ids: tuple = ()
    blob_ids: tuple = ()
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
        self.blobs = {}
        self.blob_refs = {}

    def guard(self, additional_bytes=0):
        # This is the existing process guard, never an expanded read allowance.
        if self.resource_bytes() + additional_bytes >= DEFAULT['rss_bytes']:
            raise ValueError('current_slate_read_capacity')

    def discard(self, token):
        with self.lock:
            old = self.frames.pop(token, None)
            if old is not None:
                self.retained_bytes -= old.size
                for key in old.blob_ids:
                    self.blob_refs[key]-=1
                    if not self.blob_refs[key]:
                        self.retained_bytes-=len(self.blobs.pop(key))+256
                        self.blob_refs.pop(key)
                if old.packet_store:old.packet_store.release(old.token)

    def cleanup(self):
        with self.lock:
            now = self.clock()
            for token, frame in list(self.frames.items()):
                if now >= frame.deadline:
                    self.discard(token)

    def clear(self):
        with self.lock:
            for token in list(self.frames):self.discard(token)
            self.retained_bytes = 0

    def capture(self, header, records, *, context, authority, packet_store=None, display_token=None):
        """Take immutable bytes without evicting active pagination or Details."""
        with self.lock:
            self.cleanup()
            token = token_urlsafe(32)
            record_keys=tuple(g['game_key'] for g in header.get('games',[]))
            header = self.freeze(encoded(dict(header, read_token=token)))
            records,blobs,blob_ids=self.share_records(records)
            shared_size=sum(len(blobs[k])+256 for k in blob_ids if k not in self.blobs)
            size = len(header) + sum(map(len, records)) + 4096 + 256 * len(records)
            if size + shared_size > self.maximum_bytes:
                raise ValueError('current_slate_read_capacity')
            self.guard(size+shared_size)
            # Preflight eviction: a refused newcomer must leave all existing
            # evidence intact. Selected Details and active pages are protected.
            candidates = [key for key,value in self.frames.items() if value.context == 'completed']
            # A Details handoff may replace its own display lease at capacity.
            if display_token in self.frames and self.frames[display_token].context == 'displayed':
                candidates.append(display_token)
            victims=[];remaining_bytes=self.retained_bytes;remaining_count=len(self.frames)
            while remaining_count >= self.maximum_frames or remaining_bytes + size + shared_size > self.maximum_bytes:
                if not candidates:
                    raise ValueError('current_slate_read_capacity')
                victim=candidates.pop(0);victims.append(victim)
                remaining_count-=1;remaining_bytes-=self.frames[victim].size
            frame = CapturedRead(token, context, authority, self.clock() + self.ttl_seconds,
                                 header, records, size, record_keys=record_keys)
            frame.packet_ids=tuple(self.packet_ids(records))
            if frame.packet_ids:
                if packet_store is None:raise ValueError('current_slate_read_expired')
                packet_store.pin(token,frame.packet_ids,self.ttl_seconds)
                frame.packet_store=packet_store
            for victim in victims:self.discard(victim)
            frame.blob_ids=tuple(blob_ids)
            for key in blob_ids:
                if key not in self.blobs:
                    self.blobs[key]=blobs[key];self.retained_bytes+=len(blobs[key])+256
                self.blob_refs[key]=self.blob_refs.get(key,0)+1
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
                if frame.packet_store:frame.packet_store.renew(frame.token,self.ttl_seconds)
                frame.progress_offset = offset
                frame.deadline = self.clock() + self.ttl_seconds
                if frame.token in self.frames:
                    self.frames.move_to_end(frame.token)
            # Completed pages can still open an exact selected result. They
            # remain within the same four-frame/byte/TTL eviction budget.
            if complete:
                records=[]
                for index,record in enumerate(frame.records):
                    if record.startswith(b'PR1') and record[7:10] in (b'PB1',b'PV1') and index<len(frame.record_keys):
                        # The publication packet already holds exact Originals.
                        # Drop the detached validation proof without expanding
                        # and recompressing every game's captured evidence.
                        size=int.from_bytes(record[3:7],'big')
                        if not 0<size<len(record)-7:raise ValueError('current_slate_read_capacity')
                        tail=encoded(dict(game_key=frame.record_keys[index],dependencies=None))
                        packet=record[7:7+size]
                        if packet.startswith(b'PV1'):
                            value=self.decode(packet[3:]);value.pop('_board_text',None)
                            packet=b'PV1'+self.freeze(encoded(value))
                        records.append(b'PR1'+len(packet).to_bytes(4,'big')+packet+tail)
                        continue
                    self.guard(len(record)*8)
                    value=self.decode(record)
                    value.pop('_proof',None)
                    if value.get('row'):
                        value['row'].pop('_board_text',None)
                        if '_facts_text' in value['row']:
                            value['row']['facts']=json.loads(value['row'].pop('_facts_text'))
                        facts=value['row'].get('facts',{})
                        facts.pop('boards',None)
                        for unit in facts.get('result_units',{}).values():
                            unit.get('facts',{}).pop('boards',None)
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
            if frame.context not in ('completed','displayed','selected'):
                raise ValueError('current_slate_read_context_changed')
            self.guard()
            if frame.packet_store:frame.packet_store.renew(frame.token,self.ttl_seconds)
            if frame.context != 'selected':frame.context='displayed'
            frame.deadline=self.clock()+self.ttl_seconds
            self.frames.move_to_end(token)

    def selection(self, token, game):
        with self.lock:
            self.cleanup()
            frame = self.frames.get(token)
            if frame is None:raise ValueError('current_slate_read_expired')
            records=(frame.records[frame.record_keys.index(game)],) if game in frame.record_keys else frame.records
            for record in records:
                self.guard(len(record)*8)
                value = self.decode(record,packet_store=frame.packet_store)
                if value['game_key'] == game:
                    if value.get('row') and '_facts_text' in value['row']:
                        value['row']['facts']=json.loads(value['row'].pop('_facts_text'))
                    if frame.context != 'selected':
                        # Retain only the opened game. A selected modal must
                        # not pin a 500-game pagination frame between polls.
                        selected=self.capture({},[record],context='selected',authority=frame.authority,packet_store=frame.packet_store,display_token=frame.token)
                        return value['row'],selected.token
                    # Reading renews only this bounded UI cache lease, never
                    # any source, confirmation or calculation clock.
                    if frame.packet_store:frame.packet_store.renew(frame.token,self.ttl_seconds)
                    frame.deadline = self.clock() + self.ttl_seconds
                    self.frames.move_to_end(token)
                    return value['row'],frame.token
            raise ValueError('current_selection_removed')

    @staticmethod
    def freeze(value):
        if value.startswith((b'PZ1',b'PR1')) or len(value)<32768:return value
        return b'PZ1'+len(value).to_bytes(4,'big')+zlib.compress(value,3)

    @classmethod
    def join_record(cls, key, packet, proof):
        tail=cls.freeze(encoded(dict(game_key=key,dependencies=None,_proof=proof)))
        return b'PR1'+len(packet).to_bytes(4,'big')+packet+tail

    def packet_ids(self,records):
        for record in records:
            if record.startswith(b'PR1'):
                size=int.from_bytes(record[3:7],'big');packet=record[7:7+size]
                if packet.startswith(b'PB1'):yield packet[3:].decode('ascii')
                else:
                    value=self.decode(packet[3:] if packet.startswith(b'PV1') else packet)
                    yield from value.get('_original_packets',[])

    def share_records(self, records):
        """Intern exact immutable facts across replacing lists under one byte cap.

        Prices and proof contexts are never merged. Only byte-identical fact
        strings share storage; each frame owns explicit references until expiry.
        Pending admission has no effect on existing readers or the shared pool.
        """
        from hashlib import sha256
        prepared=[];blobs={};keys=set()
        for record in records:
            if record.startswith(b'PR1'):
                size=int.from_bytes(record[3:7],'big');packet=record[7:7+size]
                if packet.startswith(b'PV1'):
                    key=self.decode(packet[3:])['_facts_blob'];keys.add(key)
                    blobs[key]=self.blobs[key]
                elif not packet.startswith(b'PB1'):
                    value=self.decode(packet)
                    if '_facts_text' in value:
                        raw=self.freeze(encoded(value.pop('_facts_text')))
                        key=sha256(raw).hexdigest();keys.add(key);blobs[key]=raw
                        value['_facts_blob']=key
                        packet=b'PV1'+self.freeze(encoded(value))
                        record=b'PR1'+len(packet).to_bytes(4,'big')+packet+record[7+size:]
            prepared.append(self.freeze(record))
        return tuple(prepared),blobs,keys

    def decode(self,value,*,packet_store=None):
        if value.startswith(b'PV1'):
            result=self.decode(value[3:]);key=result.pop('_facts_blob')
            if key not in self.blobs:raise ValueError('current_slate_read_expired')
            result['_facts_text']=self.decode(self.blobs[key])
            return result
        if value.startswith(b'PB1'):
            if packet_store is None:raise ValueError('current_slate_read_expired')
            value=packet_store.load(value[3:].decode('ascii'))
        if value.startswith(b'PR1'):
            size=int.from_bytes(value[3:7],'big')
            if not 0<size<len(value)-7:raise ValueError('current_slate_read_capacity')
            result=self.decode(value[7+size:],packet_store=packet_store)
            result['row']=self.decode(value[7:7+size],packet_store=packet_store)
            return result
        if value.startswith(b'PZ1'):
            size=int.from_bytes(value[3:7],'big')
            if not 0<size<=MAX_READ_BYTES:raise ValueError('current_slate_read_capacity')
            self.guard(size*8)
            stream=zlib.decompressobj();body=stream.decompress(value[7:],size+1)
            if len(body)!=size or not stream.eof or stream.unused_data:raise ValueError('current_slate_read_capacity')
            value=body
        return json.loads(value)
