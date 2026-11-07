"""Bounded non-executable catalog plans; every quote and validator runs afresh.

Plans contain event/group/outcome structure and immutable contract rules, never price, clock,
depth, reference probability or financial results. Exact complete input structure
and caller policy/epoch/control/settings bind each lookup. Persistence is owned
by the existing ordinary advisory lock, not another worker or publisher.
"""
from collections import OrderedDict
from copy import deepcopy
import base64
import gzip
import io
import json
from time import time, perf_counter
from .store import encoded, hashed

MAX_BYTES=4*1024*1024
MAX_ENTRY=8*1024*1024
MAX_ENTRIES=512
FILE_BYTES=6*1024*1024
TTL=7200
_plans=OrderedDict()
_metrics={}


def clear():
    _plans.clear();_metrics.clear()


def metrics():
    return dict(_metrics,entries=len(_plans),bytes=sum(len(v[1]) for v in _plans.values()))


def structure(record):
    # These fields are copied from the NEW captured record when instantiating a
    # plan. They do not select event/group/outcome structure. Unknown fields stay
    # in the proof, so additions cannot silently take an older shortcut.
    r={k:v for k,v in record.items() if k!='orientation_evidence'}
    r['comparison_source_metadata']={k:v for k,v in record.get('comparison_source_metadata',{}).items() if k!='observed_at'}
    q={k:v for k,v in record['quote'].items() if k not in
       ('revision','times','depth','book_confirmation','observed_book','provider_clocks','observation_time_evidence')}
    q['original']={k:v for k,v in q['original'].items() if k not in ('value','native_value')}
    q['provenance']={k:v for k,v in q['provenance'].items() if k not in ('sha256','receipt_sha256')}
    if 'occurrence_match' in q:
        audit={k:v for k,v in q['occurrence_match'].items() if k!='revision'}
        audit['members']=[{k:v for k,v in m.items() if k!='evidence_sha256'} for m in audit['members']]
        q['occurrence_match']=audit
    r['quote']=q
    return r


def slots(events):
    for event in events:
        for group in event['groups']:
            for outcome in group['outcomes']:
                for venue in outcome['quotes']:yield event,group,outcome,outcome['quotes'],venue
                for values in outcome.get('alternatives',{}).values():
                    for i in range(len(values)):yield event,group,outcome,values,i


def topology(events,by_source):
    """Encode private structural shells without copying discarded quote trees."""
    def plan(q):
        source=hashed(q['source'])
        return dict(source=source,contract=q.get('native_contract'),
            material_from_quote='material_sha256' not in by_source[source].get('comparison_source_metadata',{}))
    return [dict(event,groups=[dict(group,outcomes=[dict(outcome,
        quotes={v:plan(q) for v,q in outcome['quotes'].items()},
        alternatives={v:[plan(q) for q in values] for v,values in outcome.get('alternatives',{}).items()})
        for outcome in group['outcomes']]) for group in event['groups']]) for event in events]


def restore(saved,by_source):
    with gzip.GzipFile(fileobj=io.BytesIO(saved)) as stream:raw=stream.read(MAX_ENTRY+1)
    if len(raw)>MAX_ENTRY:raise ValueError('capture_plan_capacity')
    return restore_events(json.loads(raw),by_source)


def restore_events(events,by_source):
    from app.dashboard.current_contract import binding_context
    from app.comparison.event_links import digest
    for event,group,outcome,owner,index in slots(events):
        plan=owner[index];record=by_source[plan['source']]
        # Prices, clocks, depth and binding witnesses are always newly captured.
        # Only exact unchanged rules/contract evidence survives the proof lookup.
        q=dict(record['quote'])
        q['binding']=dict(verified=record['verified'],evidence=record['orientation_evidence'],
            selection=binding_context(event,group,outcome))
        if plan['contract'] is not None:
            contract=plan['contract']
            if plan['material_from_quote']:
                contract['material_sha256']=q['provenance'].get('sha256')
                contract['id']='native-contract:'+digest({k:v for k,v in contract.items() if k!='id'})
            q['native_contract']=contract
        owner[index]=q
    return events


def normalized(envelope,records,*,binding):
    start=perf_counter()
    try:return _normalized(envelope,records,binding=binding)
    finally:_metrics['seconds']=round(_metrics.get('seconds',0)+perf_counter()-start,6)


def _normalized(envelope,records,*,binding):
    from app.dashboard.current_normalized import catalog_from_normalized
    from app.comparison.native_scoring_scope import attach, source_rules
    # Rule loading checks current governing evidence. Its exact content plus
    # complete record structure proves the unchanged attach/descriptor result.
    # That owner only validates the evaluation clock; it has no clock-age cache.
    from app.comparison.current_dependencies import instant
    instant(envelope['clock_at'])
    by_source={hashed(r['quote']['source']):r for r in records}
    key=hashed([binding,source_rules(detached=False),[structure(r) for r in records]])
    # One latest proof per complete source-event neighborhood. Retaining every
    # superseded topology would evict quiet neighborhoods during material churn.
    namespace=hashed(sorted({(r['quote']['source']['provider'],r['quote']['source']['native_event_id']) for r in records}))
    saved=_plans.get(namespace) if len(by_source)==len(records) else None
    if saved and saved[2]==key and 0<=time()-saved[0]<TTL:
        try:events=restore(saved[1],by_source)
        except (OSError,EOFError,ValueError,KeyError,TypeError,IndexError):
            _plans.pop(namespace,None)
            _metrics['invalid']=_metrics.get('invalid',0)+1
        else:
            _plans.move_to_end(namespace)
            _metrics['hits']=_metrics.get('hits',0)+1
            _metrics['quotes_rebound']=_metrics.get('quotes_rebound',0)+len(records)
            return dict(deepcopy(envelope),events=events,comparison_profiles={})
    _metrics['misses']=_metrics.get('misses',0)+1
    attached=[attach(r,at=envelope['clock_at']) for r in records]
    result=catalog_from_normalized(envelope,attached,include_profiles=False,source_rules={},selected_applicability={},_scoring_attached=True)
    if len(by_source)!=len(attached):return result
    raw=encoded(topology(result['events'],by_source))
    if len(raw)<=MAX_ENTRY:
        # Measured ~1.2 ms/entry buys 23% more complete neighborhoods within the
        # same byte bound, preventing a fair rotation from evicting its own plans.
        packed=gzip.compress(raw,compresslevel=6,mtime=0)
        if len(packed)<=MAX_BYTES:
            _plans[namespace]=(time(),packed,key)
            _plans.move_to_end(namespace)
            while len(_plans)>MAX_ENTRIES or sum(len(v[1]) for v in _plans.values())>MAX_BYTES:_plans.popitem(last=False)
    return result


def load(path):
    clear()
    try:
        with path.open('rb') as f:raw=f.read(FILE_BYTES+1)
        if len(raw)>FILE_BYTES:return
        value=json.loads(raw)
        if value['version']!=3 or len(value['plans'])>MAX_ENTRIES:return
        for namespace,at,body,key in value['plans']:
            if 0<=time()-at<TTL:_plans[namespace]=(at,base64.b64decode(body,validate=True),key)
        if sum(len(v[1]) for v in _plans.values())>MAX_BYTES:clear()
    except (OSError,ValueError,KeyError,TypeError):clear()


def save(path):
    import os
    raw=encoded(dict(version=3,plans=[[k,at,base64.b64encode(body).decode(),proof] for k,(at,body,proof) in _plans.items() if 0<=time()-at<TTL]))
    if len(raw)>FILE_BYTES:return
    temporary=path.with_suffix('.tmp')
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        with temporary.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        temporary.replace(path)
    except OSError:return False
    finally:
        try:temporary.unlink(missing_ok=True)
        except OSError:pass
    return True
