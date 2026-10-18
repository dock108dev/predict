"""Versioned, volatile publication observations consumed by episode summaries.

No consumers, SQL, providers or financial calculations. Not an episode archive.
A complete supplied-universe observation is required at both ends; pending
finance coalesces, uncertainty censors, and first observations are silent.
"""
from collections import deque
from copy import deepcopy
from fractions import Fraction as F
from .current_dependencies import digest, encoded

VERSION = 'predict-scanner-transitions-1'
MAX_EVENTS = 256
MAX_BYTES = 512 * 1024
MAX_RETAINED_BYTES = 2 * 1024 * 1024
MAX_BATCHES = 128
MAX_BASELINE_BYTES = 8 * 1024 * 1024
COOLDOWN_SECONDS = 30
EDGE_POINTS = F('0.25')
SIZE_RATIO = F('1.10')
SIZE_DOLLARS = F(10)


def matches(r, filters):
    if r is None or r['category'] != filters.category or not r['current']:
        return False
    if filters.venues and not set(r['venues']).issubset(filters.venues):
        return False
    for plural, singular in (('sports', 'sport'), ('leagues', 'league'), ('markets', 'market'), ('periods', 'period')):
        if getattr(filters, plural) and r[singular] not in getattr(filters, plural):
            return False
    return (filters.minimum_edge is None or F(r['edge']) >= F(filters.minimum_edge)) and (
        filters.minimum_size is None or r['size'] is not None and F(r['size']) >= F(filters.minimum_size))


def fact(row):
    return {**{k:deepcopy(row[k]) for k in ('id','opportunity_id','pair_id','category','current','sport','league','market','period','venues','dependency_revision','economic_revision','expires_at','source_clocks')},
            'edge':row['metric']['value'], 'size':row['supported_capital_usd']}


class Transitions:
    def __init__(self):
        self.sequence = 0
        self.floor = 0
        self.history = deque()
        self.bytes = 0
        self.previous = None
        self.pairs = set()
        self.episodes = {}
        self.last_improvement = {}
        self.context = None
        self.censored = 'initial_baseline'

    def censor(self, reason):
        self.sequence += 1
        self.floor = self.sequence
        self.history.clear()
        self.bytes = 0
        self.previous = None
        self.pairs.clear()
        self.episodes.clear()
        self.last_improvement.clear()
        self.censored = reason

    def observe(self, p, reason):
        context = (p.server_id, p.epoch)
        if self.context != context:
            self.context = context
            self.censor('server_or_epoch_changed')
        if reason in ('stopped','expired','capture_failed') or p.errors:
            self.censor(reason if not p.errors else 'coverage_gap')
            return
        # Input reconciliation removes pending rows before finance has completed.
        # This intermediate state proves neither withdrawal nor episode birth.
        if p.pending:
            return
        if p.state not in ('evaluated_positive','evaluated_zero'):
            self.censor('coverage_incomplete')
            return
        rows = {k:fact(r) for k,r in p.rows.items() if r['current']}
        if len(rows)>4096 or len(encoded(rows))>MAX_BASELINE_BYTES:
            self.censor('baseline_capacity')
            return
        pairs = set(p.receipts)
        if self.previous is None:
            self.previous = rows
            self.pairs = pairs
            self.episodes = {k:digest((context,k,self.sequence)) for k in rows}
            self.censored = 'initial_baseline'
            return
        self.sequence += 1
        events = []
        now = __import__('datetime').datetime.fromisoformat(p.clock().replace('Z','+00:00')).timestamp()
        for key in sorted(set(self.previous)|set(rows)):
            before, after = self.previous.get(key), rows.get(key)
            episode = self.episodes.get(key)
            if before is None:
                # First observation of an added pair has no observed earlier zero.
                episode = digest((context,key,self.sequence))
                self.episodes[key] = episode
                kind = 'new' if after['pair_id'] in self.pairs else 'first_observation'
            elif after is None:
                # Removed pairs / unknown coverage do not prove market withdrawal.
                kind = 'withdrawn' if before['pair_id'] in pairs else 'unavailable'
            elif before['dependency_revision'] == after['dependency_revision'] and before['economic_revision'] == after['economic_revision']:
                continue
            else:
                edge = F(after['edge'])-F(before['edge'])
                size = after['size'] is not None and before['size'] is not None and F(after['size']) >= max(F(before['size'])*SIZE_RATIO,F(before['size'])+SIZE_DOLLARS)
                improved = edge >= EDGE_POINTS or (size and F(after['edge']) >= F(before['edge']))
                cooled = now-self.last_improvement.get(key,float('-inf')) >= COOLDOWN_SECONDS
                kind = 'improved' if improved and cooled else 'changed'
                if kind == 'improved':self.last_improvement[key] = now
            events.append(dict(id=digest((context,self.sequence,key)),cursor=self.sequence,episode_id=episode,
                               kind=kind,observed_at=p.clock(),before=before,after=after))
            if after is None:
                self.episodes.pop(key,None)
                self.last_improvement.pop(key,None)
        self.previous = rows
        self.pairs = pairs
        batch = dict(cursor=self.sequence,events=events)
        size = len(encoded(batch))
        if len(events)>MAX_EVENTS or size>MAX_BYTES:
            self.censor('overflow')
            return
        self.history.append(batch)
        self.bytes += size
        while len(self.history)>MAX_BATCHES or self.bytes>MAX_RETAINED_BYTES:
            old = self.history.popleft()
            self.bytes -= len(encoded(old))
            self.floor = old['cursor']

    def read(self, p, filters, *, cursor=None, server_id=None, epoch=None, scope=None):
        canonical = filters.to_dict()
        for name in ('venues','sports','leagues','markets','periods'):
            canonical[name] = sorted(canonical[name])
        identity = digest(dict(filters=canonical,version=VERSION,server_id=p.server_id,epoch=p.epoch))
        unsupported = [f'{name}:{value}' for name,values in p._options().items() for value in getattr(filters,name) if value not in values]
        valid = (not unsupported and type(cursor) is int and self.floor <= cursor <= self.sequence and
                 server_id == p.server_id and epoch == p.epoch and scope == identity and self.previous is not None)
        events = []
        if valid:
            for batch in self.history:
                if batch['cursor'] <= cursor:continue
                for event in batch['events']:
                    a,b = matches(event['before'],filters),matches(event['after'],filters)
                    if not (a or b):continue
                    e = deepcopy(event)
                    # Scope crossings describe an existing episode, never its birth.
                    if not a and b and e['kind'] not in ('new','first_observation'):e['kind']='matching'
                    elif a and not b and e['kind'] not in ('withdrawn','unavailable'):e['kind']='no_longer_matching'
                    if e['kind']=='changed':continue
                    e['audible'] = e['kind'] in ('new','improved','matching','withdrawn')
                    events.append(e)
        overflow = len(events)>MAX_EVENTS or len(encoded(events))>MAX_BYTES
        silent = not valid or overflow
        return dict(version=VERSION,server_id=p.server_id,epoch=p.epoch,scope=identity,cursor=self.sequence,
                    continuity='censored' if silent else 'continuous',
                    reason=('unsupported_scope' if unsupported else 'overflow' if overflow else self.censored if self.previous is None else 'baseline_or_cursor_resync') if silent else None,
                    events=[] if silent else events,unsupported_filters=unsupported,coverage_complete=not unsupported and self.previous is not None and not p.pending and not p.errors and p.state in ('evaluated_positive','evaluated_zero'),
                    provider_requests=0,financial_evaluations=0,
                    bounds=dict(events=MAX_EVENTS,response_bytes=MAX_BYTES+4096,retained_bytes=MAX_RETAINED_BYTES,batches=MAX_BATCHES,consumer_state=0,baseline_rows=4096,baseline_bytes=MAX_BASELINE_BYTES),
                    material_improvement=dict(edge_percentage_points=str(EDGE_POINTS),size_ratio=str(SIZE_RATIO),minimum_size_increase_usd=str(SIZE_DOLLARS),cooldown_seconds=COOLDOWN_SECONDS))
