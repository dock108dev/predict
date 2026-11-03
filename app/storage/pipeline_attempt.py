"""Replaceable publication attempt summaries owned by the background worker."""
from psycopg.types.json import Jsonb
from .current_games import engine_binding


def scheduled(db,events,*,observations_only):
    """Persist selection before capture so killed children cannot monopolize it."""
    if not events:return
    db.execute("""UPDATE current_pipeline_attempt SET last_attempt=clock_timestamp(),
        disposition='waiting',reason='scheduled',facts=facts || jsonb_build_object(
            'stage','scheduled','scheduled_attempts',COALESCE((facts->>'scheduled_attempts')::bigint,0)+1)
        WHERE event_id=ANY(%s) AND branch=%s""",(events,'raw_grid' if observations_only else 'metrics'))


def record(db, events, *, observations_only, elapsed, result):
    if not events:return
    from .pipeline_generation import completed
    for gid in set(result.get('reused_generations',[])):
        completed(db,gid,reused=True)
    disposition='passed' if result.get('published') or result.get('unchanged') else 'waiting'
    reason=('published' if result.get('published') else 'dependencies_unchanged' if result.get('unchanged')
        else result.get('reason') or 'publication_not_accepted')
    if not observations_only and not result.get('inventory_complete',False):
        disposition='waiting'
        if result.get('published') or result.get('unchanged') or not result.get('reason'):
            reason='result_inventory_incomplete_or_unknown'
    errors=[{k:r[k] for k in ('game_key','reason') if k in r} for r in result.get('errors',[])[:8]]
    facts=dict(timings=result.get('timings',{}),publication_trace=result.get('publication_trace',{}),computed=result.get('computed',0),reused=result.get('reused',0),errors=errors,
        owner='app.storage.latest_board.reconcile',stage='published' if disposition=='passed' else 'retry',
        next_action='Validate API selection and browser rendering' if disposition=='passed' else 'Inspect publication dependency and admission evidence')
    db.execute('''INSERT INTO current_pipeline_attempt
        SELECT id,%s,clock_timestamp(),clock_timestamp(),1,%s,%s,%s,%s,%s FROM current_event WHERE id=ANY(%s)
        ON CONFLICT(event_id,branch) DO UPDATE SET last_attempt=EXCLUDED.last_attempt,
        attempts=current_pipeline_attempt.attempts+1,disposition=EXCLUDED.disposition,
        reason=EXCLUDED.reason,elapsed_ms=EXCLUDED.elapsed_ms,engine=EXCLUDED.engine,
        facts=EXCLUDED.facts || jsonb_build_object(
            'scheduled_attempts',COALESCE((current_pipeline_attempt.facts->>'scheduled_attempts')::bigint,0),
            'completed_calculations',COALESCE((current_pipeline_attempt.facts->>'completed_calculations')::bigint,0)+COALESCE((EXCLUDED.facts->>'computed')::bigint,0),
            'reused_calculations',COALESCE((current_pipeline_attempt.facts->>'reused_calculations')::bigint,0)+COALESCE((EXCLUDED.facts->>'reused')::bigint,0),
            'accepted_publications',COALESCE((current_pipeline_attempt.facts->>'accepted_publications')::bigint,0)+CASE WHEN EXCLUDED.reason='published' THEN 1 ELSE 0 END)''',
        ('raw_grid' if observations_only else 'metrics',disposition,reason,round(elapsed*1000,3),engine_binding(),Jsonb(facts),events))

def enqueue(db,events,*,observations_only):
    """First observed queue time for this engine, never a fabricated receipt age."""
    if not events:return
    db.execute('''INSERT INTO current_pipeline_attempt
        SELECT id,%s,clock_timestamp(),clock_timestamp(),0,'waiting','queued',0,%s,
            '{"stage":"queued","queue_time_basis":"first_scheduler_observation"}'::jsonb
        FROM current_event WHERE id=ANY(%s)
        ON CONFLICT(event_id,branch) DO UPDATE SET first_attempt=EXCLUDED.first_attempt,
            last_attempt=EXCLUDED.last_attempt,attempts=0,disposition='waiting',reason='queued',
            elapsed_ms=0,engine=EXCLUDED.engine,facts=EXCLUDED.facts
        WHERE current_pipeline_attempt.engine<>EXCLUDED.engine''',
        ('raw_grid' if observations_only else 'metrics',engine_binding(),events))
