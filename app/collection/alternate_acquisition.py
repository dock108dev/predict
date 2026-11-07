"""Complete event-odds route with explicit owner authority and durable raw values."""
from datetime import datetime, timedelta
import json
from .current_policy import ROOT
from .current_quota import QuotaStop
from .current_aggregate_policy import POLICY
from app.reference.product import SPORT_KEYS

AUTHORITY_PATH=ROOT/'.local/predict-alternate-authority.json'
# Leave room for the 20s transport bound, 30s local-write retry bound and
# accounting before the next featured slot. Never cancel a paid request.
FEATURED_HANDOFF_SECONDS=60


def authority(at):
    if not AUTHORITY_PATH.exists():return None
    value=json.loads(AUTHORITY_PATH.read_text())
    cycle,day=value.get('credits_per_cycle'),value.get('credits_per_day')
    # This owner-maintained authorization is configuration, not a market-count
    # constant. Account availability and the exact request manifest remain
    # independently enforced by the ledger at every reservation.
    if (value.get('schema') not in ('predict-alternate-authority-1','predict-alternate-authority-2')
            or type(cycle) is not int or type(day) is not int or cycle<18
            or cycle>300 or (cycle-18)%2 or day!=56*cycle
            or (value.get('expires_at') is None and value.get('schema')!='predict-alternate-authority-2')
            or value.get('interval_seconds')!=900 or value.get('enabled') is not True):
        raise QuotaStop('alternate_authority_invalid')
    clock=datetime.fromisoformat(at.replace('Z','+00:00'))
    if clock<datetime.fromisoformat(value['approved_at']):return None
    if value.get('expires_at') is not None and clock>=datetime.fromisoformat(value['expires_at']):return None
    return value


def check_expiry(at):
    if AUTHORITY_PATH.exists():
        value=json.loads(AUTHORITY_PATH.read_text())
        if value.get('expires_at') is not None and datetime.fromisoformat(at.replace('Z','+00:00'))>=datetime.fromisoformat(value['expires_at']):
            raise QuotaStop('aggregate_owner_authority_expired')


def event_request(sport):
    return dict(path='/v4/sports/'+SPORT_KEYS[sport]+'/events',params={})


def validate_request(request, cost):
    if cost==0 and request in [event_request(s) for s in SPORT_KEYS]:return
    path=request.get('path','').split('/')
    if (cost!=2 or len(path)!=7 or path[:3]!=['','v4','sports'] or path[3] not in SPORT_KEYS.values()
            or path[4]!='events' or path[6]!='odds' or not path[5].isalnum()
            or request.get('params')!=dict(bookmakers=','.join(POLICY.bookmakers),
                markets='alternate_spreads,alternate_totals',oddsFormat='decimal',dateFormat='iso')):
        raise QuotaStop('alternate_request_scope_invalid')


def save_response(sport,event_id,response,cycle_id):
    """Retry only the already-paid local write; preserve its original receipt."""
    from time import monotonic, sleep
    from psycopg.errors import LockNotAvailable, DeadlockDetected, SerializationFailure
    deadline=monotonic()+30
    while True:
        try:
            return _save_response(sport,event_id,response,cycle_id)
        except (LockNotAvailable,DeadlockDetected,SerializationFailure):
            if monotonic()>=deadline:raise
            # Every retry rechecks persisted Stop before admitting the exact
            # retained response. No dispatch or quota transaction occurs here.
            sleep(.1)


def _save_response(sport,event_id,response,cycle_id):
    from app.storage.store import connect
    from psycopg.types.json import Jsonb
    from .current_aggregate_admission import parse_frame
    frame=response.get('parsed_frame') or parse_frame(response['body'])
    payload=frame.payload
    disposition='received_pending_qualification'
    if not isinstance(payload,dict) or payload.get('id')!=event_id:
        disposition='rejected_event_identity'
    with connect() as db:
        from .runtime_status import AUTHORITY_LOCK
        db.execute('SELECT pg_advisory_xact_lock_shared(%s)',(AUTHORITY_LOCK,))
        owner=db.execute('SELECT global_stopped,paused_sources FROM data_runtime WHERE singleton').fetchone()
        if owner and (owner['global_stopped'] or any(v in owner['paused_sources'] for v in ('the_odds_api','novig','prophetx'))):
            raise QuotaStop('aggregate_owner_stopped')
        db.execute('INSERT INTO current_acquisition_alternate VALUES (%s,%s,%s,%s,%s,%s,%s) '
            'ON CONFLICT(sport,event_id) DO UPDATE SET received_at=EXCLUDED.received_at,'
            'cycle_id=EXCLUDED.cycle_id,receipt_sha256=EXCLUDED.receipt_sha256,'
            'disposition=EXCLUDED.disposition,payload=EXCLUDED.payload '
            'WHERE current_acquisition_alternate.received_at<=EXCLUDED.received_at',
            (sport,event_id,response['received_at'],cycle_id,frame.receipt_sha256,disposition,Jsonb(payload)))
        if disposition=='received_pending_qualification':
            from .current_aggregate_admission import admit_alternate
            from app.storage.current_rows import CurrentRowStore
            records,complete,errors=admit_alternate(response['body'],sport,response['received_at'],frame=frame)
            CurrentRowStore(db).upsert_records(records,authoritative=True,
                scopes=[dict(venue=v,competition=sport,native_event_id=event_id,
                    aggregate_route='alternate',received_at=response['received_at']) for v in complete])
            db.execute('UPDATE current_acquisition_alternate SET disposition=%s WHERE sport=%s AND event_id=%s AND receipt_sha256=%s',
                ('partial_admission' if errors else 'admitted_exact_lines',sport,event_id,frame.receipt_sha256))


def save_event_census(sport,response,cycle_id):
    from app.storage.store import connect
    from psycopg.types.json import Jsonb
    frame=response['parsed_frame']
    with connect() as db:
        db.execute('INSERT INTO current_acquisition_event_census VALUES (%s,%s,%s,%s,%s) '
            'ON CONFLICT(sport) DO UPDATE SET cycle_id=EXCLUDED.cycle_id,received_at=EXCLUDED.received_at,'
            'receipt_sha256=EXCLUDED.receipt_sha256,payload=EXCLUDED.payload',
            (sport,cycle_id,response['received_at'],frame.receipt_sha256,Jsonb(frame.payload)))
        db.execute("DELETE FROM current_acquisition_alternate a WHERE sport=%s AND received_at<now()-interval '2 days' "
            "AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements(%s::jsonb) e WHERE e->>'id'=a.event_id)",
            (sport,Jsonb(frame.payload)))


def prioritize(requests, received):
    """Least recently collected first; stable league interleaving for ties/new events."""
    return sorted(requests,key=lambda r:received.get((r['sport'],r['event_id']),float('-inf')))


def priority_requests(requests, sports):
    from app.storage.store import connect
    with connect() as db:
        db.execute('SET TRANSACTION READ ONLY')
        rows=db.execute('SELECT sport,event_id,received_at FROM current_acquisition_alternate WHERE sport=ANY(%s)',
                        (list(sports),)).fetchall()
    return prioritize(requests,{(r['sport'],r['event_id']):r['received_at'].timestamp() for r in rows})


def handoff_due(scheduler, at, deadline, remaining):
    if deadline is None or datetime.fromisoformat(at.replace('Z','+00:00')) >= (
            datetime.fromisoformat(deadline.replace('Z','+00:00'))-timedelta(seconds=FEATURED_HANDOFF_SECONDS)):
        scheduler.metrics.update(alternate_state='deferred_for_scheduled_refresh',
            alternate_deferred=remaining,alternate_next_refresh=deadline)
        scheduler.next_check_at=deadline
        return True
    return False


async def acquire(scheduler,sports):
    from .alternate_plan import plan
    from .bulk_checkpoint import owned_thread
    from .current_quota import now
    grant=authority(now())
    if grant is None:return
    deadline=scheduler.quota_due()
    scheduler.metrics.update(alternate_completed=0,alternate_deferred=0,alternate_census_completed=0,
                             alternate_state='event_census')
    scheduler.metrics.pop('alternate_plan',None)
    if handoff_due(scheduler,now(),deadline,None):return
    free=[event_request(s) for s in sports]
    scheduler.ledger.extend_cycle(scheduler.service.ownership,scheduler.cycle_id,free,0)
    events={}
    for sport,request in zip(sports,free):
        if handoff_due(scheduler,now(),deadline,None):return
        response=await scheduler.dispatch(request,0)
        payload=response['parsed_frame'].payload
        if not isinstance(payload,list) or any(not isinstance(e,dict) or not isinstance(e.get('id'),str) for e in payload):
            raise QuotaStop('alternate_event_census_invalid')
        await owned_thread(save_event_census,sport,response,scheduler.cycle_id)
        scheduler.metrics['alternate_census_completed']+=1
        events[sport]=[e for e in payload if datetime.fromisoformat(e['commence_time'].replace('Z','+00:00'))>datetime.fromisoformat(now())]
    proposal=plan(events)
    proposal.update(authorized_cycle=grant['credits_per_cycle'],authorized_day=grant['credits_per_day'])
    scheduler.metrics['alternate_plan']={k:v for k,v in proposal.items() if k!='requests'}
    if proposal['total_maximum_credits_per_cycle']>grant['credits_per_cycle']:
        scheduler.metrics['alternate_state']='blocked_full_census_exceeds_authorized_cycle'
        return
    ordered=await owned_thread(priority_requests,proposal['requests'],sports)
    requests=[dict(path=r['path'],params=r['params']) for r in ordered]
    scheduler.ledger.extend_cycle(scheduler.service.ownership,scheduler.cycle_id,requests,2)
    scheduler.metrics['alternate_plan']['dispatch_enabled']=True
    scheduler.metrics['alternate_plan']['reason']=f"Explicit owner authority: {grant['credits_per_cycle']}/cycle and {grant['credits_per_day']}/day; expiry {grant.get('expires_at') or 'renewed by owner without a new cutoff'}"
    scheduler.metrics['alternate_state']='acquiring'
    scheduler.metrics['alternate_completed']=0
    for index,(item,request) in enumerate(zip(ordered,requests)):
        if handoff_due(scheduler,now(),deadline,len(requests)-index):return
        response=await scheduler.dispatch(request,2)
        scheduler.permitted()
        await owned_thread(save_response,item['sport'],item['event_id'],response,scheduler.cycle_id)
        scheduler.metrics['alternate_completed']+=1
    scheduler.metrics['alternate_state']='acquisition_and_exact_line_admission_complete'
