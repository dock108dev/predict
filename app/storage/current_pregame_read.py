"""Pure SQL reads of committed pregame rows; no acquisition or recovery work.

The public storage facade supplies its clock and route resolver. Resolving routes
stays after the cheap update-cursor path and inside the caller's transaction.
"""

from app.comparison import current_pregame as math
from .store import hashed, stamp
from .pregame_known_withdrawals import ROW_GUARDS
from datetime import timedelta


def read(db, query, *, at=None, clock, configured_routes):
    packet = _read(db, query, at=at, clock=clock, configured_routes=configured_routes)
    if query.get("max_age_minutes") and query.get("updates") != "1":
        age = timedelta(minutes=int(query["max_age_minutes"]))
        rows = list(packet.get("rows", []))
        for game in packet.get("games", []):
            rows.extend(game.get("rows", []))
        deadlines = [
            stamp(row["times"]["source_at"]) + age
            for row in rows
            if row.get("times", {}).get("source_at")
        ]
        if packet.get("refresh_at"):
            deadlines.append(stamp(packet["refresh_at"]))
        if deadlines:
            packet = dict(packet, refresh_at=min(deadlines).isoformat())
    return packet


def _read(db, query, *, at=None, clock, configured_routes):
    """Read committed complete rows; grouping and exact values precede pagination."""
    from . import pregame_ranking as ranking

    selected_sort = ranking.method(query.get("sort"))
    at = at or clock()
    limit = max(1, min(100, int(query.get("limit", "30"))))
    offset = max(0, int(query.get("offset", "0")))
    revision = db.execute(
        "SELECT revision,committed_at FROM current_pregame_revision WHERE singleton"
    ).fetchone()
    # Time is part of the cheap cursor only at a real eligibility deadline.
    deadlines = db.execute(
        """SELECT min(valid_until) FILTER (WHERE valid_until>%s) AS next,
                  max(valid_until) FILTER (WHERE valid_until<=%s) AS previous
        FROM (SELECT valid_until FROM current_pregame_calculation WHERE reason IS NULL
              UNION ALL SELECT valid_until FROM current_pregame_price
              UNION ALL SELECT start_at-(%s::int*interval '1 second')
                FROM current_pregame_price WHERE %s::int IS NOT NULL) eligible""",
        (at, at, query.get("_scope_seconds"), query.get("_scope_seconds")),
    ).fetchone()
    deadline, boundary = deadlines["next"], deadlines["previous"]
    public_revision = db.execute(
        "SELECT revision,current_schema() AS cohort_schema FROM public.current_pregame_revision WHERE singleton"
    ).fetchone()
    cursor = hashed(
        [
            public_revision["cohort_schema"],
            revision["revision"],
            public_revision["revision"],
            str(boundary),
        ]
    )
    base = dict(
        schema="predict-current-pregame-1",
        state="ready",
        generation=revision["revision"],
        cursor=cursor,
        update_cursor=cursor,
        provider_requests=0,
        scheduled_calculations=0,
        refresh_at=deadline.isoformat() if deadline else None,
        notice="Odds may be delayed.",
        sort=selected_sort,
    )
    if query.get("updates") == "1":
        return dict(base, changed=query.get("after") != cursor, poll_after_ms=500)
    compare = bool(query.get("bet_id") or query.get("id"))
    include_unavailable = (
        compare or query.get("browse") == "1" or query.get("view") in ("games", "game")
    )
    relation = "current_pregame_calculation"
    if include_unavailable:
        # Price-qualified rows survive a missing probability reference. Keep the
        # actual refusal reason and null EV; never turn missing EV into zero.
        relation = """(SELECT contract_id,game_key,bet_id,league,family,venue,start_at,main,
            valid_until,net_ev,opportunity_score,reason,payload FROM current_pregame_calculation
          UNION ALL SELECT price.contract_id,price.game_key,price.payload->>'bet_id',
            price.payload->>'league',price.payload->>'family',price.payload->>'venue',
            price.start_at,(price.payload->>'main')::boolean,price.valid_until,
            NULL::numeric,NULL::numeric,NULL::text,
            price.payload || jsonb_build_object('ev_unavailable_reason',
                COALESCE(calc.reason,'reference_unavailable'))
          FROM current_pregame_price price
          LEFT JOIN current_pregame_calculation calc ON calc.contract_id=price.contract_id
          WHERE calc.contract_id IS NULL OR calc.reason IS NOT NULL)"""
    clauses = [
        "p.reason IS NULL",
        "p.valid_until>%s",
        "p.start_at>%s",
        "e.scheduled_start::timestamptz>%s",
    ]
    params = [at, at, at]
    if query.get("_scope_seconds"):
        clauses.append("p.start_at<=%s")
        params.append(at + timedelta(seconds=int(query["_scope_seconds"])))
    order_by = query.get("order", "rank")
    if order_by not in ("rank", "newest", "oldest", "start"):
        raise ValueError("Unknown row order")
    if query.get("max_age_minutes"):
        age = int(query["max_age_minutes"])
        if not 1 <= age <= 525600:
            raise ValueError("Invalid maximum age")
        clauses.append("(p.payload#>>'{times,source_at}')::timestamptz>=%s")
        params.append(at - timedelta(minutes=age))
    # A bet with no positive stored venue cannot produce a positive result.
    # Keep every alias/venue inside admitted bets so newest-alias selection and
    # exact eligibility remain unchanged; do not filter individual rows by EV.
    if (
        not compare
        and query.get("browse") != "1"
        and query.get("view") not in ("games", "game")
    ):
        clauses.append(
            "p.bet_id IN (SELECT bet_id FROM current_pregame_calculation WHERE reason IS NULL AND net_ev>0)"
        )
    # A stored row from an older writer must not bypass the current owner rule.
    clauses.append("""(p.payload ? 'ev_unavailable_reason' OR (SELECT count(*) FROM jsonb_object_keys(
        COALESCE(p.payload#>'{reference,candidate_probabilities}','{}'::jsonb)) AS book
        WHERE book=ANY(%s))>=2)""")
    params.append(list(math.BEST_BOOKS))
    routes = configured_routes(db)
    clauses.append(
        "("
        + " OR ".join(
            "(p.venue=%s AND p.payload#>>'{source,provider}'=%s)" for _ in routes
        )
        + ")"
    )
    for venue, provider in routes.items():
        params.extend((venue, provider))
    if (
        not query.get("id")
        and not query.get("bet_id")
        and (
            query.get("view") == "games"
            or (query.get("view") != "game" and query.get("lines") != "all")
        )
    ):
        clauses.append("p.main")
    for key, column in (("league", "league"), ("family", "family"), ("venue", "venue")):
        if query.get(key):
            clauses.append(f"p.{column}=ANY(%s)")
            params.append(query[key].split(","))
    for key, column in (
        ("game_key", "game_key"),
        ("bet_id", "bet_id"),
        ("id", "contract_id"),
    ):
        if query.get(key):
            clauses.append(f"p.{column}=%s")
            params.append(query[key])
    if query.get("search"):
        clauses.append("p.payload->>'game' ILIKE %s")
        params.append("%" + query["search"][:150] + "%")
    # Explicit withdrawal is authoritative even before recovery handles the job.
    clauses.extend(
        [
            "o.facts->>'state' IS DISTINCT FROM 'unavailable'",
            "NOT COALESCE((SELECT lp.expired FROM sgo_line_presence lp WHERE lp.quote_id=o.sgo_quote_id LIMIT 1),false)",
            "NOT (COALESCE(e.facts->'status','{}'::jsonb) @> '{\"live\":true}'::jsonb)",
            "NOT (COALESCE(e.facts->'status','{}'::jsonb) @> '{\"ended\":true}'::jsonb)",
            "COALESCE(e.facts#>>'{status,status}','') NOT IN ('cancelled','final','suspended','started','delayed')",
            """NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload#>'{reference,prices}') r
           LEFT JOIN current_sgo_reference s ON s.id=r->>'input_id'
           WHERE s.id IS NULL OR s.facts->'available' IS DISTINCT FROM 'true'::jsonb)""",
        ]
    )
    clauses.extend(ROW_GUARDS)
    params.append(at)
    where = " AND ".join(clauses)
    source = (
        " FROM "
        + relation
        + """ p JOIN current_contract c ON c.id=p.contract_id
        JOIN current_offer_storage o ON o.contract_id=c.id JOIN LATERAL (SELECT * FROM current_event WHERE id=c.event_id LIMIT 1) e ON true WHERE """
        + where
    )
    # Multiple native aliases can describe one venue's same logical offer.
    # Source evidence order chooses its observation before EV chooses a venue.
    recency = "(payload#>>'{times,source_at}' IS NOT NULL) DESC,(payload#>>'{times,source_at}')::timestamptz DESC NULLS LAST,(payload#>>'{times,received_at}')::timestamptz DESC,contract_id"
    logical = (
        "WITH available AS (SELECT p.*"
        + source
        + "), logical AS (SELECT DISTINCT ON (bet_id,venue) * FROM available ORDER BY bet_id,venue,"
        + recency
        + ") "
    )
    if compare:
        entries = db.execute(
            logical
            + "SELECT payload,"
            + ranking.expression(selected_sort)
            + " AS ranking_value FROM logical ORDER BY net_ev DESC NULLS LAST,contract_id",
            params,
        ).fetchall()
        from .pregame_sportsbooks import read_prices

        rows = [
            ranking.present(r["payload"], r["ranking_value"], selected_sort)
            for r in entries
        ]
        return dict(
            base,
            sportsbooks=read_prices(db, rows, at=at),
            rows=rows,
            total=len(entries),
            offset=0,
            limit=limit,
        )
    positive = query.get("browse") != "1" and query.get("view") not in ("games", "game")
    grouped = (
        logical.rstrip()
        + ", qualified AS (SELECT *,row_number() OVER (PARTITION BY bet_id ORDER BY net_ev DESC NULLS LAST,contract_id) AS venue_order FROM logical), best AS (SELECT * FROM qualified WHERE venue_order=1"
        + (" AND net_ev>0" if positive else "")
        + ") "
    )
    if query.get("view") == "game":
        if not query.get("game_key"):
            raise ValueError("A game key is required")
        rows = [
            r["payload"]
            for r in db.execute(
                grouped + "SELECT payload FROM best ORDER BY main DESC,family,bet_id",
                params,
            )
        ]
        return dict(base, rows=rows, total=len(rows), offset=0, limit=len(rows))
    if query.get("view") == "games":
        page = db.execute(
            grouped
            + """, games AS (
            SELECT game_key,min(start_at) AS kickoff FROM best GROUP BY game_key),
            page AS (SELECT * FROM games ORDER BY kickoff,game_key LIMIT %s OFFSET %s),
            page_games AS (
            SELECT b.game_key,p.kickoff,
                jsonb_build_object('game_key',b.game_key,'game',min(b.payload->>'game'),
                  'league',min(b.league),'kickoff',p.kickoff,
                  'rows',jsonb_agg(b.payload ORDER BY b.family,b.bet_id)) AS game
            FROM best b JOIN page p USING(game_key) GROUP BY b.game_key,p.kickoff)
            SELECT count(*) AS total,
              (SELECT jsonb_agg(game ORDER BY kickoff,game_key) FROM page_games) AS games
            FROM games""",
            (*params, limit, offset),
        ).fetchone()
        return dict(
            base,
            games=page["games"] or [],
            rows=[],
            total=page["total"],
            offset=offset,
            limit=limit,
        )
    order = "ranking_value DESC NULLS LAST,net_ev DESC,bet_id"
    if order_by in ("newest", "oldest"):
        direction = "DESC" if order_by == "newest" else "ASC"
        order = (
            "(payload#>>'{times,source_at}')::timestamptz "
            + direction
            + " NULLS LAST,bet_id"
        )
    elif order_by == "start":
        order = "start_at,bet_id"
    page = db.execute(
        grouped
        + ", ranked AS (SELECT *,"
        + ranking.expression(selected_sort)
        + " AS ranking_value FROM best) SELECT count(*) AS total,"
        + "(SELECT jsonb_agg(jsonb_build_array(payload,ranking_value::text) ORDER BY "
        + order
        + ") FROM (SELECT * FROM ranked ORDER BY "
        + order
        + " LIMIT %s OFFSET %s) page) AS entries FROM ranked",
        (*params, limit, offset),
    ).fetchone()
    return dict(
        base,
        rows=[
            ranking.present(payload, value, selected_sort)
            for payload, value in page["entries"] or []
        ],
        total=page["total"],
        offset=offset,
        limit=limit,
    )
