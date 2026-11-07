"""Exact line-group materialization; changed groups use the complete validator.

The complete current normalized group and event context form the proof. Cached
values never lend a price, quantity, binding or reference to changed input. Only
evaluation time is external: the shared clock/link owner runs again on every hit.
Financial calculation is not memoized here. No detached quote can bypass the
complete envelope, capacity or cross-group native-selection constraints.
"""
from collections import OrderedDict
import base64
import gzip
import io
import json
from time import time
from .store import encoded,hashed

MAX_BYTES=8*1024*1024
MAX_ENTRY=8*1024*1024
MAX_ENTRIES=8192
FILE_BYTES=12*1024*1024
TTL=7200
_cache=OrderedDict()
_metrics={}


def clear():
    _cache.clear();_metrics.clear()


def metrics():
    return dict(_metrics,entries=len(_cache),bytes=sum(len(v[2]) for v in _cache.values()))


def materialize(raw,*,binding):
    from app.dashboard.current_contract import drain,serialize_steps,stamp,price_clock_status,quotes_of,identity,byte_count_steps
    from app.comparison.estimated_policy import DEFAULT_POLICY
    # Validate the envelope even when every group is reused. Global constraints
    # below still see all groups, including cache hits and cross-group conflicts.
    result=drain(serialize_steps(dict(raw,events=[]),prices_only=True,estimate_policy=DEFAULT_POLICY))
    if not isinstance(raw['events'],list) or len(raw['events'])>200:raise ValueError('Event capacity exceeded')
    drain(byte_count_steps(raw))
    events={};native={};count_groups=count_quotes=0
    for event in raw['events']:
        context={k:v for k,v in event.items() if k!='groups'}
        groups=[];seen=set();staged=[];missing=[]
        for group in event['groups']:
            proof=hashed([binding,context,group,raw['mode']])
            slot=hashed([binding,context,group['id']])
            cached=_cache.get(slot);part=None
            if cached and cached[1]==proof and 0<=time()-cached[0]<TTL:
                try:
                    with gzip.GzipFile(fileobj=io.BytesIO(cached[2])) as stream:body=stream.read(MAX_ENTRY+1)
                    if len(body)>MAX_ENTRY:raise ValueError('materialization_capacity')
                    part=json.loads(body)
                except (OSError,ValueError,EOFError):_cache.pop(slot,None)
                else:
                    _cache.move_to_end(slot);_metrics['hits']=_metrics.get('hits',0)+1
                    for outcome in part['groups'][0]['outcomes']:
                        for quote in quotes_of(outcome):price_clock_status(quote,stamp(raw['clock_at']))
            staged.append([slot,proof,part])
            if part is None:missing.append(group)
        validated=iter(())
        if missing:
            all_new=drain(serialize_steps(dict(raw,events=[dict(event,groups=missing)]),prices_only=True,estimate_policy=DEFAULT_POLICY))['events'][0]
            validated=iter(dict(all_new,groups=[group]) for group in all_new['groups'])
        for slot,proof,part in staged:
            if part is None:
                part=next(validated);_metrics['misses']=_metrics.get('misses',0)+1
                body=encoded(part)
                if len(body)<=MAX_ENTRY:
                    packed=gzip.compress(body,compresslevel=3,mtime=0)
                    if len(packed)<=MAX_BYTES:
                        _cache[slot]=(time(),proof,packed);_cache.move_to_end(slot)
                        while len(_cache)>MAX_ENTRIES or sum(len(v[2]) for v in _cache.values())>MAX_BYTES:_cache.popitem(last=False)
            g=part['groups'][0]
            if g['id'] in seen:raise ValueError('Duplicate exact group; merge normalized inputs before commit')
            seen.add(g['id']);count_groups+=1
            for outcome in g['outcomes']:
                for quote in quotes_of(outcome):
                    source=quote['source'];key=identity('instrument',[quote['venue'],*[source[k] for k in ('provider','native_event_id','native_market_id','native_outcome_id','native_side','quote_side')]])
                    if key in native and native[key]!=outcome['id']:raise ValueError('Native instrument bound to conflicting selections')
                    native[key]=outcome['id'];count_quotes+=1
            groups.append(g)
        if not groups:
            part=drain(serialize_steps(dict(raw,events=[event]),prices_only=True,estimate_policy=DEFAULT_POLICY))['events'][0]
        eid=part['id']
        if eid in events:raise ValueError('Duplicate exact event')
        events[eid]=dict(part,groups=groups)
    if count_groups>2000 or count_quotes>16000:raise ValueError('Catalog capacity exceeded')
    result['events']=sorted(events.values(),key=lambda e:(e['start_at'],e['id']))
    drain(byte_count_steps(result))
    return result


def load(path):
    clear()
    try:
        with path.open('rb')as f:raw=f.read(FILE_BYTES+1)
        if len(raw)>FILE_BYTES:return
        value=json.loads(raw)
        if value['version']!=1 or len(value['entries'])>MAX_ENTRIES:return
        for key,at,proof,body in value['entries']:
            if 0<=time()-at<TTL:_cache[key]=(at,proof,base64.b64decode(body,validate=True))
        if sum(len(v[2]) for v in _cache.values())>MAX_BYTES:clear()
    except (OSError,ValueError,KeyError,TypeError):clear()


def save(path):
    import os
    raw=encoded(dict(version=1,entries=[[k,at,proof,base64.b64encode(body).decode()] for k,(at,proof,body) in _cache.items() if 0<=time()-at<TTL]))
    if len(raw)>FILE_BYTES:return False
    temporary=path.with_suffix('.tmp')
    try:
        with temporary.open('wb')as f:f.write(raw);f.flush();os.fsync(f.fileno())
        temporary.replace(path)
    except OSError:return False
    finally:temporary.unlink(missing_ok=True)
    return True
