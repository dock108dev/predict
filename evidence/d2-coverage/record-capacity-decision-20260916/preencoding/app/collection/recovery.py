"""Read-only stable-journal prefix inspection; indexes never modify source bytes."""
import base64
from contextlib import ExitStack
from datetime import datetime
import fcntl
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID
from app.reference.records import packed
from app.collection.run_spec import preflight,time_value

CAP=32*1024*1024
KINDS={'session_started','session_finished','source_health','prediction_discovery_http','discovery_validated','market_selected','prediction_command','prediction_frame','prediction_book','native_stream_finished','controlled_interruption'}
VENUES={'kalshi','polymarket_us'}

def strict_json(body):
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('duplicate JSON field')
            d[k]=v
        return d
    return json.loads(body,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))

def signature(st):
    return dict(device=st.st_dev,inode=st.st_ino,size=st.st_size,mtime_ns=st.st_mtime_ns,ctime_ns=st.st_ctime_ns)

def stable_read(path):
    path=Path(path).resolve(strict=True)
    with ExitStack() as stack:
        # Existing E6 owners lock the environment; new writers also lock the journal.
        owner=path.parent.parent/'owner.lock'
        if owner.exists():
            lock=stack.enter_context(owner.open('rb'));fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        f=stack.enter_context(path.open('rb'));fcntl.flock(f,fcntl.LOCK_SH|fcntl.LOCK_NB)
        import os
        before=signature(os.fstat(f.fileno()))
        if before['size']>CAP:raise ValueError('source byte cap')
        body=f.read(CAP+1)
        if len(body)>CAP or before!=signature(os.fstat(f.fileno())) or before!=signature(path.stat()):raise ValueError('source changed during read')
    return body,dict(path=str(path),**before,sha256=sha256(body).hexdigest())

def validate_rows(rows):
    if not rows or rows[0].get('type')!='session_started':raise ValueError('initial session metadata missing')
    sid=rows[0]['session_id'];UUID(sid);spec=rows[0]['spec']
    if spec.get('reference_enabled',False) or not preflight(spec,now=time_value(rows[0]['observed_at']))['valid']:raise ValueError('unsupported or invalid saved specification')
    ids=set();last_time=None;markets={};validated=set();commands={};health={v:'idle' for v in VENUES};last_frame={};receipts={v:set() for v in VENUES};requests={v:set() for v in VENUES};subscribed=set()
    for i,r in enumerate(rows):
        kind=r['type'];venue=r.get('source');at=time_value(r['observed_at'])
        if kind not in KINDS or r['session_id']!=sid:raise ValueError('unsupported record or conflicting session')
        if last_time and at<last_time:raise ValueError('record time order changed')
        last_time=at
        if kind=='session_finished':
            if r.get('health')!=health or not isinstance(r.get('reason'),str):raise ValueError('invalid terminal context')
            if i!=len(rows)-1:raise ValueError('records after terminal record')
            if type(r['delivered']) is not int or type(r['persisted']) is not int or not 0<=r['persisted']<=r['delivered']==len(ids):raise ValueError('invalid terminal accounting')
            continue
        UUID(r['ingress_id'])
        if r['ingress_id'] in ids:raise ValueError('duplicate ingress identity')
        ids.add(r['ingress_id'])
        if not isinstance(r.get('health'),dict) or set(r['health'])!=VENUES or r.get('economics','missing') is not None:raise ValueError('missing record context')
        context=dict(health)
        if kind=='source_health':context[venue]=r.get('state')
        if r['health']!=context:raise ValueError('conflicting recorded health context')
        if kind=='session_started':
            if i!=0 or venue!='session' or not r.get('provenance'):raise ValueError('conflicting session metadata')
            continue
        if venue not in VENUES:raise ValueError('unsupported source')
        expected=spec['sources'][venue]
        if kind=='source_health':
            if r['state'] not in ('idle','awaiting_snapshot','connected','disconnected','ineligible'):raise ValueError('unsupported health')
            health[venue]=r['state']
            if r['state'] in ('disconnected','awaiting_snapshot'):subscribed.discard(venue)
        elif kind=='prediction_discovery_http':
            raw=base64.b64decode(r['body_b64'],validate=True)
            if sha256(raw).hexdigest()!=r['body_sha256']:raise ValueError('HTTP body digest changed')
            if type(r['complete']) is not bool or not isinstance(r['path'],str):raise ValueError('invalid discovery receipt')
            if r['complete'] and r['status']==200:receipts[venue].add(r['body_sha256'])
        elif kind=='discovery_validated':
            if (r['event_id'],r['market_id'],r['scheduled_start'],r['mapping_revision'])!=(expected['event_id'],expected['market_id'],spec['scheduled_start'],spec['mapping_revision']):raise ValueError('discovery identity conflict')
            validated.add(venue)
        elif kind=='market_selected':
            ref=r['market']['raw']['ref']
            if venue not in validated or (ref['event_id'],ref['market_id'])!=(expected['event_id'],expected['market_id']):raise ValueError('missing or conflicting selected metadata')
            if venue in markets and r['market']['outcomes']!=markets[venue]['outcomes']:raise ValueError('outcome identity changed')
            m=r['market'];raw=m['raw']
            if sha256(raw['json_text'].encode()).hexdigest() not in receipts[venue]:raise ValueError('metadata lacks complete HTTP dependency')
            from dataclasses import asdict
            from app.models.core import EvidenceKind
            from app.adapters.kalshi import Response as KR,parse_market as km
            from app.adapters.polymarket_us import Response as PR,parse_market as pm
            response=(KR if venue=='kalshi' else PR)(raw['json_text'],raw['source'],datetime.fromisoformat(raw['received_at']),EvidenceKind(raw['kind']))
            payload=strict_json(raw['json_text'])
            selected=(km(response,next(x for x in payload['markets'] if x['ticker']==expected['market_id']),expected['event_id'],'KXNFLGAME') if venue=='kalshi' else pm(response,next(x for e in payload['events'] for x in e['markets'] if str(x['id'])==expected['market_id']),expected['event_id']))
            if json.loads(json.dumps(asdict(selected),default=str))!=m:raise ValueError('selected metadata differs from native parser')
            markets[venue]=m
        elif kind=='prediction_command':
            if venue not in markets:raise ValueError('subscription lacks market metadata')
            if health.get(venue)!='awaiting_snapshot' or venue in subscribed:raise ValueError('subscription lacks connection boundary')
            command=strict_json(r['body']);previous=commands.get(venue)
            if type(r['connection']) is not int or r['connection']!=(1 if previous is None else previous+1):raise ValueError('subscription generation mismatch')
            if venue=='kalshi':
                if command['cmd']!='subscribe' or command['params']['market_tickers']!=[expected['market_id']] or command['params']['channels']!=['orderbook_delta']:raise ValueError('wrong subscription')
            else:
                subscription=command['subscribe'];rid=subscription['requestId']
                raw=strict_json(markets[venue]['raw']['json_text'])
                native=next(x for e in raw['events'] for x in e['markets'] if str(x['id'])==expected['market_id'])
                if not rid or rid in requests[venue] or subscription['marketSlugs']!=[native['slug']] or subscription['subscriptionType']!='SUBSCRIPTION_TYPE_MARKET_DATA':raise ValueError('invalid subscription identity')
                requests[venue].add(rid)
                # Native parser binds requestId and marketSlug on each image.
            commands[venue]=r['connection'];last_frame.pop(venue,None);subscribed.add(venue)
        elif kind=='prediction_frame':
            if venue not in subscribed or commands.get(venue)!=r['connection']:raise ValueError('frame lacks current subscription')
            raw=base64.b64decode(r['body_b64'],validate=True)
            if sha256(raw).hexdigest()!=r['body_sha256'] or time_value(r['received_at'])>at:raise ValueError('invalid native frame receipt')
            last_frame[venue]=r
        elif kind=='prediction_book':
            b=r['book'];ref=b['raw']['ref']
            if venue not in markets or venue not in last_frame or (ref['event_id'],ref['market_id'])!=(expected['event_id'],expected['market_id']):raise ValueError('book dependencies missing')
            if b['raw']['kind']!=('observation' if spec['mode']=='real' else 'synthetic'):raise ValueError('book provenance mismatch')
            if time_value(b['raw']['received_at'])>at:raise ValueError('book precedes receipt')
            if b['sync']=='synchronized' and b['receipt_freshness']=='recent' and (venue not in subscribed or health.get(venue) not in ('awaiting_snapshot','connected')):raise ValueError('book invalid for connection state')
            if b['receipt_freshness']=='stale' and (at-time_value(b['raw']['received_at'])).total_seconds()<spec['stale_seconds']:raise ValueError('unsupported stale state')
        elif kind=='controlled_interruption':
            if commands.get(venue)!=r['connection']:raise ValueError('interruption lacks connection')
        elif kind=='native_stream_finished':
            if type(r['closed']) is not bool or not isinstance(r['diagnostics'],list):raise ValueError('invalid close record')
    return spec

def _inspect(path):
    body,identity=stable_read(path);offset=0;chain='0'*64;rows=[]
    for fragment in body.split(b'\n')[:-1]:
        line=fragment+b'\n'
        if len(rows)>=4096:raise ValueError('record cap')
        item=strict_json(line)
        if set(item)!={'row','previous','sha256'}:raise ValueError('invalid journal envelope')
        expected=sha256((chain+packed(item['row'])).encode()).hexdigest()
        if item['previous']!=chain or item['sha256']!=expected:raise ValueError('broken journal chain')
        chain=expected;rows.append(item['row']);offset+=len(line)
    spec=validate_rows(rows)
    terminal=rows[-1]['type']=='session_finished'
    if terminal and offset!=len(body):raise ValueError('bytes after terminal record')
    saved=dict(rows=rows,sha256=chain,state='complete' if terminal else 'interrupted')
    from app.dashboard.e6_live import verify_all_saved
    replay=verify_all_saved(saved)
    rejected={g['ingress_id'] for g in replay['gaps']};states={};frames={}
    for r in rows:
        v=r.get('source')
        if r['type']=='source_health':states[v]=r['state']
        if r['type']=='prediction_frame':frames[v]=r['ingress_id']
        if r['type']=='prediction_book' and r['book']['sync']=='unsynchronized' and states.get(v) not in ('disconnected','ineligible') and frames.get(v) not in rejected:
            raise ValueError('unsynchronized state lacks invalidation dependency')
    # Revalidation catches a noncooperating writer changing bytes during parsing/replay.
    _,after=stable_read(path)
    if identity!=after:raise ValueError('source changed during verification')
    return dict(format='e6-recovery-1',session=rows[0]['session_id'],source=identity,spec_sha256=sha256(packed(spec).encode()).hexdigest(),
        status='interrupted_finalization' if terminal else 'interrupted',verified_offset=offset,verified_chain=chain,excluded_trailing_bytes=len(body)-offset,
        last_verified_at=rows[-1]['observed_at'],terminal_record_present=terminal,
        counts=dict(frames=sum(r['type']=='prediction_frame' for r in rows),books=sum(r['type']=='prediction_book' for r in rows),packets=sum(len(r['packets']) for r in rows if r['type']=='prediction_book'),ingress=sum('ingress_id' in r for r in rows)),
        accounting=dict(delivered=rows[-1]['delivered'] if terminal else None,persisted=rows[-1]['persisted'] if terminal else None,lost=None,pending=None,crash_time=None),replay=replay),saved

def inspect(path):
    try:return _inspect(path)
    except (KeyError,TypeError,IndexError,AttributeError,StopIteration,UnicodeError) as exc:
        raise ValueError('invalid journal structure or missing native dependency') from None

def index(path,destination):
    if (Path(path).parent/'manifest.json').exists():raise ValueError('saved manifest exists; use completed-session validation, not recovery fallback')
    report,_=inspect(path);report['recovery_identity']=sha256(packed(report).encode()).hexdigest()
    destination=Path(destination)
    if destination.resolve()==Path(path).resolve():raise ValueError('index must be separate')
    destination.parent.mkdir(parents=True,exist_ok=True)
    from app.dashboard.e6_live import save_json
    save_json(destination,report)
    return report

def reopen_index(path,expected=None):
    report=strict_json(Path(path).read_bytes());identity=report.pop('recovery_identity')
    if sha256(packed(report).encode()).hexdigest()!=identity or (expected is not None and identity!=expected):raise ValueError('recovery index identity changed')
    fresh,saved=inspect(report['source']['path'])
    if fresh!=report:raise ValueError('indexed source or verified prefix changed')
    report['recovery_identity']=identity
    return report,saved

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('journal',type=Path);p.add_argument('--index',type=Path,required=True);a=p.parse_args()
    print(json.dumps(index(a.journal,a.index),indent=2))
if __name__=='__main__':main()
