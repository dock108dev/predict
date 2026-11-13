"""Exact semantic game-comparison bundle generations, distinct from source events.

A generation covers the complete game calculation's dependency graph, including
its candidate and reference rosters. It is not an individual EV/pair result row.
"""
from psycopg.types.json import Jsonb
from .store import hashed


def identity(game_key, dependencies, engine, policy, applicability):
    revision=hashed([dependencies,applicability])
    return hashed([game_key,revision,engine,policy]),revision


def admit(db, game_key, dependencies, engine, policy, applicability, *, trace=None):
    gid,revision=identity(game_key,dependencies,engine,policy,applicability)
    with db.transaction():
        if trace is not None:
            from .pipeline_delivery import difference
            previous=db.execute('SELECT trace FROM pipeline_generation WHERE game_key=%s ORDER BY last_attempt DESC LIMIT 1',(game_key,)).fetchone()
            trace=dict(trace,changes=difference(previous['trace'] if previous else {},trace))
        db.execute("""UPDATE pipeline_generation SET disposition='superseded',reason='new_semantic_generation'
            WHERE game_key=%s AND id<>%s AND disposition IN ('eligible_pending','failed','deferred')""",(game_key,gid))
        db.execute("""INSERT INTO pipeline_generation(id,game_key,engine,policy,dependency_revision,events,trace)
            VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET
            last_attempt=clock_timestamp(),attempts=pipeline_generation.attempts+1,
            disposition=CASE WHEN pipeline_generation.published_at IS NULL THEN 'eligible_pending' ELSE pipeline_generation.disposition END""",
            (gid,game_key,engine,policy,revision,Jsonb(dependencies['selector']['events']),Jsonb(trace or {})))
    return gid


def completed(db,gid,*,reused=False):
    db.execute("""UPDATE pipeline_generation SET completed_at=COALESCE(completed_at,clock_timestamp()),
        calculations=calculations+%s,reuses=reuses+%s WHERE id=%s""",(int(not reused),int(reused),gid))


def outcome(db,gid,*,published,reason=None,facts=None):
    disposition='published' if published else 'deferred'
    if not published and reason=='membership_changed':disposition='superseded'
    if published and (facts or {}).get('retained_financial_only'):
        disposition='superseded';reason='inputs_changed_during_calculation'
    db.execute("""UPDATE pipeline_generation SET disposition=%s,reason=%s,facts=%s,
        commits=commits+%s,published_at=CASE WHEN %s THEN COALESCE(published_at,clock_timestamp()) ELSE published_at END
        WHERE id=%s""",(disposition,reason,Jsonb(facts or {}),int(published),published,gid))


def retire_obsolete(db,game_keys,covered,active,captured_at):
    """Retire old keys only with the same committed proof as publication removal.

    A partial component cannot retire an uncovered peer, nor can an older capture
    retire a generation admitted later. The caller owns the publication transaction.
    """
    if captured_at is None:return
    db.execute("""UPDATE pipeline_generation g SET disposition='superseded',
        reason='publication_membership_replaced'
        WHERE disposition IN ('eligible_pending','failed','deferred')
        AND admitted_at<=%s AND NOT(split_part(game_key,'#result:',1)=ANY(%s)) AND jsonb_array_length(events)>0
        AND (NOT(events ?| %s) OR NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(g.events) e(value)
            WHERE NOT(e.value=ANY(%s))))""",(captured_at,list(game_keys),list(active),list(covered)))


def prune(db):
    if db.execute("""SELECT EXISTS(SELECT 1 FROM pg_attribute
        WHERE attrelid=to_regclass('pipeline_generation') AND attname='trace' AND NOT attisdropped) present""").fetchone()['present']:
        db.execute("""UPDATE pipeline_generation SET trace='{}'::jsonb WHERE trace<>'{}'::jsonb
        AND disposition IN ('published','superseded') AND id IN
        (SELECT id FROM pipeline_generation WHERE trace<>'{}'::jsonb ORDER BY last_attempt DESC,id OFFSET 2000)""")
    # Retain unfinished work. Terminal history is exported by cohort monitors.
    db.execute("""DELETE FROM pipeline_generation WHERE disposition IN ('published','superseded')
        AND last_attempt<clock_timestamp()-interval '2 hours'""")
    db.execute("""DELETE FROM pipeline_generation WHERE id IN (
        SELECT id FROM pipeline_generation WHERE disposition IN ('published','superseded')
        ORDER BY last_attempt DESC,id OFFSET 50000)""")


def recover_interrupted(db):
    """Only the exclusive financial owner can declare its predecessor gone."""
    from .current_games import engine_binding
    db.execute("""UPDATE pipeline_generation SET disposition='superseded',reason='engine_replaced'
        WHERE engine<>%s AND disposition IN ('eligible_pending','deferred','failed')""",(engine_binding(),))
    db.execute("""UPDATE pipeline_generation SET disposition='deferred',
        reason='previous_worker_exited_before_commit'
        WHERE disposition='eligible_pending'""")
