"""Read-only explanation of every observed source event's current membership."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,stamp
from app.storage.current_games import utc
from datetime import timedelta

def run(source,target):
 records=json.loads(Path(source).read_text())['records']
 observed={e['id']:e for sample in records for e in sample['events']}
 with connect() as db,db.transaction():
  db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
  at=utc();start=stamp(at);end=start+timedelta(hours=72)
  events={r['id']:r for r in db.execute('SELECT id,provider,native_event_id,competition,scheduled_start,revision,facts FROM current_event WHERE id=ANY(%s)',(list(observed),))}
  counts={r['event_id']:r for r in db.execute("""SELECT c.event_id,count(*) contracts,count(o.contract_id) offers,
   array_agg(DISTINCT c.facts#>>'{market_identity,family}') families
   FROM current_contract c LEFT JOIN current_offer o ON o.contract_id=c.id
   WHERE c.event_id=ANY(%s) GROUP BY c.event_id""",(list(observed),))}
  rows=[]
  for eid,initial in observed.items():
   event=events.get(eid);count=counts.get(eid,{})
   scheduled=stamp(event['scheduled_start']) if event and event.get('scheduled_start') else None
   reason=('normalized_event_absent' if event is None else 'scheduled_start_absent' if scheduled is None else
    'event_started_before_window' if scheduled<start else 'event_after_72_hour_window' if scheduled>=end else
    'current_offers_withdrawn_or_not_admitted' if not count.get('offers') else 'offered_in_window')
   rows.append(dict(source_event_id=eid,source=initial['provider'],native_event_id=initial['native_event_id'],
    membership_reason=reason,current_event=event,current_counts=count,
    next_action='Use complete current dependency validation and scheduler lineage' if reason=='offered_in_window' else
    'Retire obsolete work; follow source admission if the event is offered again' if reason=='current_offers_withdrawn_or_not_admitted' else
    'Respect the recorded schedule and source membership; do not count as unchanged eligible work'))
 Path(target).write_text(json.dumps(dict(at=at,rows=rows,limits=['An absent offer does not establish that the provider withdrew it; source receipt/admission evidence distinguishes those cases.']),indent=2,default=str))
 print('events',len(rows))

if __name__=='__main__':run(*sys.argv[1:])
