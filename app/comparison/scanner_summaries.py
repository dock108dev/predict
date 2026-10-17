"""One bounded publication observer; compact facts, never financial reports.

The dedicated fixed-slot file has no index, journal, WAL or auxiliary files.
Checksums make torn writes unavailable rather than inventing continuity. All
filesystem work belongs to the single worker, outside projection/ingress locks.
"""
from collections import deque
from copy import deepcopy
from fractions import Fraction as F
from hashlib import sha256
import json
import os
import fcntl
from pathlib import Path
from struct import pack, unpack, error as StructError
from threading import Condition, RLock, Thread
from time import monotonic

from .current_dependencies import digest, encoded, instant
from .scanner_projection import Filters

VERSION = 'predict-opportunity-summaries-1'
HEADER_BYTES = 4096
MAX_BYTES = 10 * 1024 * 1024
MAX_EPISODES = 10000
RETENTION_SECONDS = 7 * 86400
MAX_OBSERVATION_BYTES = 4 * 1024 * 1024
MAX_QUEUE = 4
MAX_RESPONSE_BYTES = 65536
MAX_JOINT = 4
MAX_COUNTER = 2**53 - 1
GAPS = {'stopped', 'expired', 'capture_failed', 'epoch_changed', 'restart'}


def _seconds(value):
    return instant(value).timestamp()


def _increment(value, count=1):
    return min(MAX_COUNTER, value + count)


def _dimensions(row, filters):
    return (not filters.venues or set(row['venues']).issubset(filters.venues)) and all(
        not getattr(filters, plural) or row[singular] in getattr(filters, plural)
        for plural, singular in (('sports','sport'), ('leagues','league'), ('markets','market'), ('periods','period')))


def _category_complete(pair, category, rows):
    if category == 'ev':
        # A cashflow receipt proves nothing about an optional EV reference.
        # The evaluator emits signed EV research rows whenever numeric EV is
        # supported; its absence is unknown coverage, not a negative EV result.
        return any(r['pair_id']==pair['id'] and r['category']=='ev' for r in rows)
    return pair['complete']


def observation(projection, reason):
    """Detached allowlisted capture, invoked only at actual publication."""
    from .scanner_transitions import fact
    frame = projection.frame or {}
    instruments = {i['id']: i for i in frame.get('instruments', [])}
    pairs = []
    for pair in frame.get('pairs', []):
        legs = [instruments[k] for k in pair['legs']]
        pairs.append(dict(id=pair['id'], venues=sorted(i['venue'] for i in legs),
            **{k: legs[0][k] for k in ('sport','league','market','period')},
            complete=pair['id'] in projection.receipts, expires_at=pair['expires_at'],
            pending=pair['id'] in projection.pending or pair['id'] in projection.targets and pair['id'] not in projection.cache))
    return dict(server_id=projection.server_id, epoch=projection.epoch,
        publication=projection.publication, observed_at=projection.published_at,
        reason=reason, state=projection.state, pending=bool(projection.pending),
        errors=bool(projection.errors), rows=[fact(r) for r in projection.rows.values() if r['current']],
        pairs=pairs, scopes=[{k:s.get(k) for k in ('venue','sport','league','market','period','state')}
            for s in frame.get('scopes', [])], options=projection._options())


class SummaryStore:
    """Synchronous owner used only by SummaryWorker or disposable tests."""
    def __init__(self, path, *, max_bytes=MAX_BYTES, max_episodes=MAX_EPISODES,
                 retention_seconds=RETENTION_SECONDS, slot_bytes=4096):
        if (not HEADER_BYTES + slot_bytes <= max_bytes <= MAX_BYTES or
            not 1 <= max_episodes <= MAX_EPISODES or not 1 <= retention_seconds <= RETENTION_SECONDS or
            slot_bytes < 1024 or slot_bytes % 512):
            raise ValueError('summary_bounds_invalid')
        self.path = Path(path)
        self.max_bytes = max_bytes; self.max_episodes = max_episodes
        self.retention_seconds = retention_seconds; self.slot_bytes = slot_bytes
        # APFS reports allocated extents beyond logical length (including
        # preallocation/COW high water). Reserve space within the same10MiB
        # budget; never treat payload/file length alone as physical storage.
        self.allocation_reserve = min(2*1024*1024,max_bytes//4) if max_bytes>=1024*1024 else 0
        self.capacity = min(max_episodes, (max_bytes - HEADER_BYTES - self.allocation_reserve) // slot_bytes)
        self.records = {}; self.slots = {}; self.active = {}; self.present = set(); self.pairs = set();self.row_pairs={};self.category_pairs=set()
        self.context = None; self.latest = None; self.previous_complete = False
        self.lock = RLock(); self.closed = False; self.fd = None; self.failed = None
        self.meta = dict(version=VERSION, slot_bytes=slot_bytes, first=None, last=None,
                         evicted=0, gaps=0, lost=False, complete_publications=0,
                         sequence=0, high_water=0)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
            self.fd = os.open(self.path, flags, 0o600)
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.fchmod(self.fd, 0o600)
            size = os.fstat(self.fd).st_size
            if size > max_bytes:
                raise ValueError('summary_file_capacity')
            if size:
                head = self._decode(os.pread(self.fd, HEADER_BYTES, 0))
                if not head or head.get('version') != VERSION or head.get('slot_bytes') != slot_bytes:
                    self.meta.update(lost=True, gaps=1)
                    os.ftruncate(self.fd, HEADER_BYTES)
                else:
                    self.meta = {k: head.get(k, v) for k,v in self.meta.items()}
                    for slot in range(min(self.capacity, max(0, (size-HEADER_BYTES)//slot_bytes))):
                        raw = os.pread(self.fd, slot_bytes, HEADER_BYTES+slot*slot_bytes)
                        if not raw.strip(b'\0'):continue
                        record = self._decode(raw)
                        if not record or not self._valid_record(record) or record['episode_id'] in self.records:
                            self.meta.update(lost=True, gaps=_increment(self.meta['gaps']))
                            self._clear(slot); continue
                        key = record['episode_id']; self.records[key] = record; self.slots[key] = slot
                        if record['termination'] is None:
                            record.update(termination='restart', ended_at=record['last_observed'], right_censored=True)
                            self._write(slot, record)
                            self.meta.update(lost=True)
                    if self.meta['first'] is not None:
                        self.meta.update(lost=True,gaps=_increment(self.meta['gaps']))
            self._header()
        except Exception:
            if self.fd is not None:os.close(self.fd)
            self.fd = None
            raise

    @staticmethod
    def _decode(raw):
        try:
            size = unpack('>I', raw[:4])[0]
            if not 0 < size <= len(raw)-36:return None
            body = raw[36:36+size]
            if sha256(body).digest() != raw[4:36]:return None
            return json.loads(body)
        except (ValueError, TypeError, StructError):return None

    @staticmethod
    def _valid_record(record):
        try:
            return (isinstance(record, dict) and len(record['episode_id']) == 64 and
                    len(encoded(record)) < 65536 and record['category'] in (
                    'covered_outcome_arb','conditional_hedge','ev') and
                    _seconds(record['first_observed']) <= _seconds(record['last_observed']) and
                    all(len(str(record[k])) <= 256 for k in ('id','pair_id','opportunity_id')))
        except (KeyError, ValueError, TypeError):return False

    def _write_raw(self, offset, value, bound):
        body = encoded(value)
        if len(body)+36 > bound:raise ValueError('summary_record_capacity')
        data = pack('>I', len(body)) + sha256(body).digest() + body
        data += b'\0' * (bound-len(data))
        if self.allocation_reserve and self._physical()>self.max_bytes-self.allocation_reserve//2:
            raise OSError('summary_allocation_headroom')
        if os.pwrite(self.fd, data, offset) != len(data):raise OSError('summary_short_write')

    def _write(self, slot, value):
        self._write_raw(HEADER_BYTES + slot*self.slot_bytes, value, self.slot_bytes)

    def _clear(self, slot):
        if os.pwrite(self.fd, b'\0'*self.slot_bytes, HEADER_BYTES+slot*self.slot_bytes) != self.slot_bytes:
            raise OSError('summary_short_write')

    def _physical(self):
        if self.fd is None:return 0
        stat = os.fstat(self.fd)
        return max(stat.st_size, stat.st_blocks*512)

    def _header(self):
        self.meta['high_water'] = max(self.meta['high_water'], self._physical(), HEADER_BYTES)
        if self.meta['high_water'] > self.max_bytes:raise OSError('summary_physical_capacity')
        self._write_raw(0, self.meta, HEADER_BYTES)

    def _evict(self, at, *, need=False):
        cutoff = _seconds(at)-self.retention_seconds
        ordered = sorted(self.records, key=lambda key:(self.records[key]['first_observed'], key))
        for key in ordered:
            if _seconds(self.records[key]['first_observed']) > cutoff and not (need and len(self.records) >= self.capacity):break
            record = self.records.pop(key); slot = self.slots.pop(key); self._clear(slot)
            if self.active.get(record['id']) == key:self.active.pop(record['id'], None)
            self.meta.update(evicted=_increment(self.meta['evicted']), lost=True)

    def gap(self, reason, at=None):
        with self.lock:
            at = at or self.meta['last']
            for key in list(self.active.values()):
                record = self.records[key]
                record.update(termination=reason, ended_at=at, right_censored=True)
                self._write(self.slots[key], record)
            self.active.clear(); self.present.clear(); self.pairs.clear();self.row_pairs.clear();self.category_pairs.clear(); self.previous_complete=False
            self.meta.update(gaps=_increment(self.meta['gaps']), lost=True)
            self._header()

    def _new(self, row, obs):
        self._evict(obs['observed_at'], need=True)
        self.meta['sequence'] = _increment(self.meta['sequence'])
        key = digest((obs['server_id'],obs['epoch'],row['id'],self.meta['sequence']))
        new = (row['pair_id'],row['category']) in self.category_pairs and row['id'] not in self.present
        clocks = deepcopy(row['source_clocks'])
        record = {k:deepcopy(row[k]) for k in ('id','opportunity_id','pair_id','category','sport','league','market','period','venues')}
        record.update(episode_id=key, server_id=obs['server_id'], epoch=obs['epoch'],
            first_observed=obs['observed_at'], last_observed=obs['observed_at'],
            first_publication=obs['publication'], last_publication=obs['publication'],
            first_dependency=row['dependency_revision'], dependency_revision=row['dependency_revision'],
            first_economic=row['economic_revision'], economic_revision=row['economic_revision'],
            first_source_clocks=clocks, source_clocks=clocks, expires_at=row['expires_at'],
            left_censored=not new, right_censored=False, termination=None, ended_at=None,
            edge_min=row['edge'], edge_max=row['edge'], size_min=row['size'], size_max=row['size'],
            joint=[[row['edge'],row['size']]], joint_complete=True, meaningful_changes=0)
        used=set(self.slots.values())
        slot = next(i for i in range(self.capacity) if i not in used)
        self._write(slot, record)
        self.records[key]=record; self.slots[key]=slot; self.active[row['id']]=key

    def _update(self, record, row, obs):
        if record['dependency_revision'] != row['dependency_revision'] or record['economic_revision'] != row['economic_revision']:
            record['meaningful_changes'] = _increment(record['meaningful_changes'])
        record.update(last_observed=obs['observed_at'],last_publication=obs['publication'],
            dependency_revision=row['dependency_revision'],economic_revision=row['economic_revision'],
            source_clocks=deepcopy(row['source_clocks']),expires_at=row['expires_at'])
        record['edge_min']=str(min(F(record['edge_min']),F(row['edge'])))
        record['edge_max']=str(max(F(record['edge_max']),F(row['edge'])))
        if row['size'] is not None:
            for name,fn in (('size_min',min),('size_max',max)):
                record[name]=str(fn(F(record[name]),F(row['size']))) if record[name] is not None else row['size']
        witness=[row['edge'],row['size']]
        if witness not in record['joint']:
            # Keep a Pareto frontier, not independent maxima as a joint claim.
            def dominates(a,b):return F(a[0])>=F(b[0]) and a[1] is not None and b[1] is not None and F(a[1])>=F(b[1])
            if not any(dominates(a,witness) for a in record['joint']):
                joint=[a for a in record['joint'] if not dominates(witness,a)]+[witness]
                if len(joint)>MAX_JOINT:record['joint_complete']=False
                record['joint']=joint[-MAX_JOINT:]
        self._write(self.slots[record['episode_id']], record)

    def observe(self, obs):
        with self.lock:
            if self.closed or self.failed:return
            try:
                self._evict(obs['observed_at'])
                context=(obs['server_id'],obs['epoch'])
                if context != self.context:
                    if self.context is not None:self.gap('server_or_epoch_changed',obs['observed_at'])
                    self.context=context
                self.latest=deepcopy(obs)
                self.meta['first']=self.meta['first'] or obs['observed_at'];self.meta['last']=obs['observed_at']
                if obs['reason'] in GAPS-{'expired'}:
                    self.gap(obs['reason'],obs['observed_at'])
                else:
                    rows={row['id']:row for row in obs['rows']}
                    pairs={p['id'] for p in obs['pairs'] if p['complete']}
                    category_pairs={(p['id'],category) for p in obs['pairs'] for category in
                        ('covered_outcome_arb','conditional_hedge','ev') if _category_complete(p,category,obs['rows'])}
                    # A pair can finish while the rest of the scope is pending.
                    # Observe its qualified rows immediately. Pending work cannot
                    # prove absence, nor erase the last complete negative proof.
                    pending={p['id'] for p in obs['pairs'] if p.get('pending',obs['pending'])}
                    if obs['reason']=='expired':pending={p['id'] for p in obs['pairs'] if p['id'] in pending and _seconds(obs['observed_at'])<_seconds(p.get('expires_at',obs['observed_at']))}
                    if self.pairs-pairs-pending:
                        self.meta.update(lost=True,gaps=_increment(self.meta['gaps']))
                    for row_id,key in list(self.active.items()):
                        if row_id not in rows:
                            record=self.records[key]
                            if record['pair_id'] in pending:continue
                            withdrawn=(record['pair_id'],record['category']) in category_pairs
                            record.update(termination='withdrawn' if withdrawn else 'coverage_gap',
                                ended_at=obs['observed_at'],right_censored=not withdrawn)
                            self._write(self.slots[key],record);self.active.pop(row_id)
                            if not withdrawn:self.meta.update(lost=True,gaps=_increment(self.meta['gaps']))
                    for row_id,row in rows.items():
                        if row_id in self.active:self._update(self.records[self.active[row_id]],row,obs)
                        else:self._new(row,obs)
                    retained={key:value for key,value in self.row_pairs.items() if value in pending}
                    retained.update({key:row['pair_id'] for key,row in rows.items()})
                    self.row_pairs=retained;self.present=set(retained)
                    self.pairs=pairs | (self.pairs & pending);self.previous_complete=bool(pairs)
                    self.category_pairs=category_pairs | {proof for proof in self.category_pairs if proof[0] in pending}
                    if obs['state'] in ('evaluated_positive','evaluated_zero') and not obs['errors'] and not obs['pending']:
                        self.meta['complete_publications']=_increment(self.meta['complete_publications'])
                self._header();os.fsync(self.fd)
            except Exception:
                self.failed='summary_write_failed';self.previous_complete=False
                self.meta.update(lost=True,gaps=_increment(self.meta['gaps']))

    def read(self, *, filters=None, at=None):
        from app.storage.current_games import utc
        filters=filters or Filters();at=at or utc()
        with self.lock:
            obs=self.latest or {};options=obs.get('options',{})
            unsupported=[f'{name}:{v}' for name in ('venues','sports','leagues','markets','periods')
                         for v in getattr(filters,name) if v not in options.get(name,[])]
            records=[];threshold_complete=True
            cutoff=_seconds(at)-self.retention_seconds
            expired_history=any(_seconds(r['first_observed'])<=cutoff for r in self.records.values())
            for record in self.records.values():
                if _seconds(record['first_observed'])<=cutoff or record['category']!=filters.category or not _dimensions(record,filters):continue
                edge=filters.minimum_edge;size=filters.minimum_size
                def qualifies(e,s):return (edge is None or F(e)>=F(edge)) and (size is None or s is not None and F(s)>=F(size))
                if edge is not None and size is not None:
                    witnessed=any(qualifies(e,s) for e,s in record['joint'])
                    if not witnessed and qualifies(record['edge_max'],record['size_max']) and not record['joint_complete']:
                        threshold_complete=False
                    if not witnessed:continue
                elif not qualifies(record['edge_max'],record['size_max']):continue
                records.append(record)
            pairs=[p for p in obs.get('pairs',[]) if _dimensions(p,filters)]
            scopes=[s for s in obs.get('scopes',[]) if all(not getattr(filters,plural) or s[singular] in getattr(filters,plural)
                    for plural,singular in (('venues','venue'),('sports','sport'),('leagues','league'),('markets','market'),('periods','period')))]
            fresh=bool(obs) and all(_seconds(at)<_seconds(r['expires_at']) for r in obs.get('rows',[])) and all(
                not p.get('expires_at') or _seconds(at)<_seconds(p['expires_at']) for p in pairs)
            evaluated=sum(_category_complete(p,filters.category,obs.get('rows',[])) for p in pairs)
            complete=bool(pairs) and evaluated==len(pairs) and not unsupported and not obs.get('errors',True) and obs.get('state') in ('evaluated_positive','evaluated_zero','partial','not_evaluated') and all(s['state']=='ready' for s in scopes) and fresh and not self.failed
            checked_zero=not any(r['category']==filters.category and _dimensions(r,filters) and
                (filters.minimum_edge is None or F(r['edge'])>=F(filters.minimum_edge)) and
                (filters.minimum_size is None or r['size'] is not None and F(r['size'])>=F(filters.minimum_size)) for r in obs.get('rows',[])) if complete else None
            def extrema(name):
                values=[F(r[name]) for r in records if r[name] is not None]
                return str((min if name.endswith('min') else max)(values)) if values else None
            spans=[max(0,_seconds(r['last_observed'])-_seconds(r['first_observed'])) for r in records]
            ended=sum(r['termination'] is not None for r in records)
            canonical=filters.to_dict()
            for name in ('venues','sports','leagues','markets','periods'):
                canonical[name]=sorted(canonical[name])
            out=dict(version=VERSION,server_id=obs.get('server_id'),epoch=obs.get('epoch'),
                scope=digest(canonical),observed_at=obs.get('observed_at'),filters=filters.to_dict(),
                state='stopped' if obs.get('reason')=='stopped' else 'available' if complete else 'unavailable',
                observation_window=dict(**{'from':self.meta['first'],'to':self.meta['last']}),
                counts=dict(observed_episodes=len(records),observed_new=sum(not r['left_censored'] for r in records),
                    left_censored=sum(r['left_censored'] for r in records),ended=ended,open=len(records)-ended,
                    gap_censored=sum(r['right_censored'] for r in records)),
                edge_percent=dict(minimum=extrema('edge_min'),maximum=extrema('edge_max')),
                supported_capital_usd=dict(minimum=extrema('size_min'),maximum=extrema('size_max')),
                duration_seconds=dict(minimum_observed=min(spans,default=None),maximum_observed=max(spans,default=None),
                    complete_episodes=sum(not r['left_censored'] and r['termination']=='withdrawn' for r in records)),
                coverage=dict(state=obs.get('state','unavailable'),complete=complete,
                    observed_complete_publications=self.meta['complete_publications'],gaps=self.meta['gaps'],checked_zero=checked_zero,
                    compatible_pairs=len(pairs) if obs else None,evaluated_pairs=evaluated if obs else None),
                history=dict(complete=complete and not self.meta['lost'] and not expired_history and not any(r['left_censored'] for r in records) and threshold_complete,
                    evicted_episodes=self.meta['evicted'],continuity_lost=self.meta['lost'] or expired_history,threshold_history_complete=threshold_complete),
                bounds=dict(retention_seconds=self.retention_seconds,episode_limit=self.max_episodes,storage_limit_bytes=self.max_bytes,
                    physical_bytes=self._physical(),physical_high_water_bytes=self.meta['high_water'],queue_observations=MAX_QUEUE,response_bytes=MAX_RESPONSE_BYTES),
                notes=['observed_spans_not_market_lifetimes','independent_extrema_not_joint']+([self.failed] if self.failed else []),
                unsupported_filters=unsupported,provider_requests=0,financial_evaluations=0)
            if len(encoded(out))>MAX_RESPONSE_BYTES:raise ValueError('summary_response_capacity')
            return out

    def maintain(self, at):
        with self.lock:
            if self.failed or self.closed:return
            try:
                before=len(self.records);self._evict(at)
                if len(self.records)!=before:self._header();os.fsync(self.fd)
            except Exception:self.failed='summary_write_failed'

    def close(self):
        with self.lock:
            if self.closed:return
            self.closed=True
            if self.fd is not None:
                try:os.fsync(self.fd)
                finally:os.close(self.fd);self.fd=None


class SummaryWorker:
    """One task, four bounded detached snapshots, no persistence on offer."""
    def __init__(self, path, **caps):
        self.condition=Condition();self.queue=deque();self.closed=False;self.busy=False
        self.lost=0;self.store=None;self.error=None;self.path=path;self.caps=caps
        self.thread=Thread(target=self._run,name='predict-summary',daemon=True);self.thread.start()

    def offer(self, snapshot):
        try:
            if len(encoded(snapshot))>MAX_OBSERVATION_BYTES:raise ValueError('summary_observation_capacity')
            with self.condition:
                if self.closed:return
                if len(self.queue)>=MAX_QUEUE:
                    self.queue.clear();self.lost=_increment(self.lost)
                self.queue.append(snapshot);self.condition.notify()
        except Exception:
            with self.condition:self.lost=_increment(self.lost);self.condition.notify()

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.queue or self.closed or self.lost,timeout=60)
                if not self.queue and self.closed:break
                lost=self.lost;self.lost=0
                obs=self.queue.popleft() if self.queue else None;self.busy=True
            if self.store is None and self.error is None and (obs is not None or lost):
                try:self.store=SummaryStore(self.path,**self.caps)
                except Exception:self.error='summary_store_unavailable'
            if self.store:
                try:
                    if lost:self.store.gap('queue_overflow',obs['observed_at'] if obs else None)
                    if obs:self.store.observe(obs)
                    else:
                        from app.storage.current_games import utc
                        self.store.maintain(utc())
                except Exception:self.error='summary_write_failed'
            with self.condition:self.busy=False;self.condition.notify_all()
        if self.store:
            try:self.store.close()
            except Exception:self.error='summary_close_failed'

    def flush(self, timeout=5):
        end=monotonic()+timeout
        with self.condition:
            while self.queue or self.busy or self.lost:
                remaining=end-monotonic()
                if remaining<=0:return False
                self.condition.wait(remaining)
        return True

    def read(self, **kwargs):
        if self.store:
            value=self.store.read(**kwargs)
            with self.condition:
                delayed=bool(self.queue or self.busy or self.lost)
                lost=bool(self.lost)
            if delayed:
                value['state']='unavailable';value['coverage'].update(complete=False,checked_zero=None)
                value['notes'].append('summary_publication_waiting')
            if lost:value['history'].update(complete=False,continuity_lost=True)
            if self.error:
                value['state']='unavailable';value['coverage'].update(complete=False,checked_zero=None)
                value['history'].update(complete=False,continuity_lost=True);value['notes'].append(self.error)
            return value
        # The store can fail independently; a disposable in-memory unavailable
        # response uses the same shape without opening another file or task.
        blank=object.__new__(SummaryStore)
        blank.lock=RLock();blank.latest=None;blank.records={};blank.fd=None
        blank.max_bytes=self.caps.get('max_bytes',MAX_BYTES);blank.max_episodes=self.caps.get('max_episodes',MAX_EPISODES)
        blank.retention_seconds=self.caps.get('retention_seconds',RETENTION_SECONDS)
        blank.meta=dict(first=None,last=None,lost=True,complete_publications=0,gaps=1,evicted=0,high_water=0)
        blank.failed=self.error or 'summary_initializing'
        return blank.read(**kwargs)

    def close(self):
        with self.condition:self.closed=True;self.condition.notify_all()
        self.thread.join(timeout=5)
        if self.thread.is_alive():self.error='summary_close_timeout'
