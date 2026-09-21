"""All functions here run on workers, never the web/stream event loop."""
import json
from datetime import datetime,timezone
from app.storage import Store,connect,CapturePolicy
from app.dashboard.views import candidate_view,depth_view,side_labels
from app.dashboard.session_status import interpret_session


def list_sessions():
    with connect() as db:
        sessions=db.execute('SELECT id,environment,evidence_class,started_at,state FROM capture_session ORDER BY started_at DESC LIMIT 100').fetchall()
        for session in sessions:
            session['saved_status']=interpret_session(session,coverage_events(db,session['id']))
        return sessions


def coverage_events(db,sid):
    # Summary uses every event; only the visible evidence list is truncated.
    return db.execute('SELECT original_time,kind,detail FROM coverage_event WHERE session_id=%s ORDER BY observed_at DESC,id DESC',(sid,)).fetchall()


def saved_view(sid):
    with connect() as db:
        s=Store(db)
        session=db.execute('SELECT id,environment,evidence_class,started_at,state FROM capture_session WHERE id=%s',(sid,)).fetchone()
        if not session: raise LookupError('Session not found')
        row=db.execute("SELECT hash FROM metadata_version WHERE session_id=%s AND kind='dashboard-view' ORDER BY native_key DESC LIMIT 1",(sid,)).fetchone()
        if row: view=s.get(row['hash'])
        else:
            c=db.execute("SELECT audit_hash,observed_text FROM calculation WHERE session_id=%s AND engine='detector-capture-1' ORDER BY observed_at DESC LIMIT 1",(sid,)).fetchone()
            view=dict(markets=[],candidates=[],sequence=0,at=c['observed_text'] if c else None)
            if c:
                a=s.get(c['audit_hash']); report=a['result']; rows=a['input']['markets']['data']['observations']
                titles={r['key']:r.get('native',{}).get('title','Market') for r in rows.values()}
                view['candidates']=[candidate_view(x,titles,side_labels(rows.values())) for x in report['candidates']]
                for r in rows.values():
                    quotes=[leg['observation'] for x in report['candidates'] for leg in x['legs'] if leg['native_market_key']==r['key'] and leg['observation']]
                    unique={q['side']:q for q in quotes}
                    view['markets'].append(dict(key=r['key'],venue_key=r['venue'],venue=r['venue'],title=titles[r['key']],event_id=r['native_event_id'],market_id=r['native_market_id'],event_title=titles[r['key']],quotes=list(unique.values()),reasons=r.get('reasons',[])))
        view['session']=session
        events=coverage_events(db,sid)
        session['saved_status']=interpret_session(session,events)
        view['coverage']=events[:100]
        view['coverage_total']=len(events)
        view['receipts']=db.execute('SELECT count(*) AS n FROM receipt WHERE session_id=%s',(sid,)).fetchone()['n']
        view['messages']=session['saved_status']['messages']
        return view


def history(sid,cid):
    with connect() as db:
        rows=db.execute('SELECT observed_at,engine,state,reasons FROM candidate_observation WHERE session_id=%s AND candidate_id=%s ORDER BY observed_at LIMIT 100',(sid,cid)).fetchall()
        bounds=db.execute('SELECT min(observed_at) AS first, max(observed_at) AS last, count(*) AS count FROM candidate_observation WHERE session_id=%s AND candidate_id=%s',(sid,cid)).fetchone()
        return dict(samples=rows,first_observed=bounds['first'],last_observed=bounds['last'],total_observations=bounds['count'],
            note='Discrete observations only. Showing the first 100 samples at most; first/last span all retained samples. Time between samples is not proven opportunity survival.')


def saved_depth(sid,cid):
    with connect() as db:
        s=Store(db)
        row=db.execute("SELECT c.audit_hash FROM calculation c JOIN candidate_observation o ON c.session_id=o.session_id AND c.id=o.calculation_id WHERE c.session_id=%s AND o.candidate_id=%s AND c.engine='depth-1' ORDER BY c.observed_at DESC LIMIT 1",(sid,cid)).fetchone()
        if not row: raise LookupError('No saved depth result for this candidate')
        return depth_view(s.get(row['audit_hash']))
