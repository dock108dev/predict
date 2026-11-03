"""Reconcile every frozen native identity without treating gaps as retirement."""
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,stamp


def run(cohort,path):
    original=json.loads(Path(cohort).read_text());ids=[r['source_event_id'] for r in original['rows']]
    with connect() as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        at=db.execute('SELECT transaction_timestamp() at').fetchone()['at'];end=at+timedelta(hours=72)
        events={r['id']:r for r in db.execute('''SELECT e.id,e.provider,e.native_event_id,e.scheduled_start,
            (SELECT count(*) FROM current_contract c JOIN current_offer o ON o.contract_id=c.id WHERE c.event_id=e.id) offers,
            (SELECT count(*) FROM current_native_book b WHERE b.event_id=e.id) books FROM current_event e WHERE e.id=ANY(%s)''',(ids,))}
        rows=[]
        for old in original['rows']:
            eid=old['source_event_id'];e=events.get(eid);scheduled=e and e['scheduled_start']
            raw=db.execute('''SELECT disposition,withdrawn,count(*) markets,min(observed_at) oldest_observation,
                max(observed_at) newest_observation,min(absent_since) absent_since,max(missing_passes) missing_passes
                FROM current_acquisition_market WHERE source=%s AND event_id=%s GROUP BY disposition,withdrawn''',
                (old['source'],old['native_event_id'])).fetchall()
            if scheduled and not at<=stamp(scheduled)<end:state='outside_current_window'
            elif e and e['offers']:state='still_offered_and_eligible'
            elif raw and all(r['withdrawn'] for r in raw):state='authoritatively_withdrawn'
            else:state='temporarily_absent_or_admission_blocked'
            rows.append(dict(source_event_id=eid,source=old['source'],native_event_id=old['native_event_id'],
                disposition=state,current=e,source_catalog=raw,
                evidence='Current normalized membership and retained source census; absence alone is not withdrawal.'))
    Path(path).write_text(json.dumps(dict(at=at,window_end=end,counts=dict(Counter(r['disposition'] for r in rows)),rows=rows),default=str,indent=2))
    print(Counter(r['disposition'] for r in rows))


if __name__=='__main__':run(*sys.argv[1:])
