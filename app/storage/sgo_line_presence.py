"""Scoped omission evidence, separate from immutable provider quote facts."""

from psycopg.types.json import Jsonb

GRACE_SECONDS = 15 * 60


def observe(db, rows, *, include_alternates=False, events=(), received_at=None):
    if not rows and not (include_alternates and events and received_at):
        return 0
    incoming = [
        dict(
            id=r["id"],
            event=r["event_id"],
            book=r["bookmaker_id"],
            odd=r["facts"]["odd_id"],
            at=r["received_order"],
        )
        for r in rows
    ]
    # Older/duplicate pages cannot start, prolong, or reverse absence evidence.
    restored = db.execute(
        """WITH incoming AS (
      SELECT * FROM jsonb_to_recordset(%s) i(id text,event text,book text,odd text,at numeric)
    ), changed AS (
      SELECT p.quote_id FROM sgo_line_presence p JOIN incoming i ON i.id=p.quote_id
      WHERE p.expired AND i.at>p.scope_received
    ) SELECT quote_id FROM changed""",
        (Jsonb(incoming),),
    ).fetchall()
    db.execute(
        """INSERT INTO sgo_line_presence(quote_id,event_id,bookmaker_id,odd_id,last_seen,scope_received)
      SELECT id,event,book,odd,at,at FROM jsonb_to_recordset(%s) i(id text,event text,book text,odd text,at numeric)
      ON CONFLICT(quote_id) DO UPDATE SET last_seen=excluded.last_seen,
      scope_received=excluded.scope_received,missing_since=NULL,expired=false
      WHERE excluded.last_seen>sgo_line_presence.scope_received""",
        (Jsonb(incoming),),
    )
    scope_rows = []
    if include_alternates and events and received_at:
        from app.collection.sportsgameodds_transport import ODD_IDS
        from app.collection.sportsgameodds_worker import ALTERNATE_REFRESH_BOOKS
        from app.storage.store import exact_time

        by_scope = {}
        for r in incoming:
            by_scope.setdefault((r["event"], r["book"], r["odd"]), []).append(r["id"])
        for prior in db.execute(
            "SELECT DISTINCT event_id,bookmaker_id,odd_id FROM sgo_line_presence WHERE event_id=ANY(%s) AND bookmaker_id=ANY(%s) AND odd_id=ANY(%s)",
            (list(events), list(ALTERNATE_REFRESH_BOOKS), list(ODD_IDS)),
        ):
            key = (prior["event_id"], prior["bookmaker_id"], prior["odd_id"])
            scope_rows.append(
                dict(
                    event=key[0],
                    book=key[1],
                    odd=key[2],
                    at=str(exact_time(received_at)),
                    ids=by_scope.get(key, []),
                )
            )
    expired = []
    if include_alternates:
        expired = db.execute(
            """WITH scopes AS (
          SELECT event,book,odd,max(at) at,array_agg(id) ids FROM
          jsonb_to_recordset(%s) i(id text,event text,book text,odd text,at numeric)
          GROUP BY event,book,odd
          UNION ALL SELECT event,book,odd,at,ids FROM jsonb_to_recordset(%s)
          s(event text,book text,odd text,at numeric,ids text[])
        ) UPDATE sgo_line_presence p SET
          missing_since=COALESCE(p.missing_since,s.at),scope_received=s.at,
          expired=(s.at-COALESCE(p.missing_since,s.at)>=%s)
        FROM scopes s WHERE (p.event_id,p.bookmaker_id,p.odd_id)=(s.event,s.book,s.odd)
          AND NOT(p.quote_id=ANY(s.ids)) AND s.at>p.scope_received
        RETURNING p.quote_id,p.expired""",
            (Jsonb(incoming), Jsonb(scope_rows), GRACE_SECONDS),
        ).fetchall()
    changed = len(restored) + sum(r["expired"] for r in expired)
    if changed:
        for event in sorted({r["event"] for r in incoming} | set(events)):
            db.execute("SELECT pregame_enqueue('sportsgameodds',%s)", (event,))
    return changed
