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
        clocks = [row.get("times", {}).get("source_at") for row in rows]
        clocks.extend(
            price.get("source_at")
            for row in rows
            for price in (row.get("reference") or {}).get("prices", [])
        )
        deadlines = [stamp(value) + age for value in clocks if value]
        if packet.get("refresh_at"):
            deadlines.append(stamp(packet["refresh_at"]))
        if deadlines:
            packet = dict(packet, refresh_at=min(deadlines).isoformat())
    return packet


def _read(db, query, *, at=None, clock, configured_routes):
    """Read committed complete rows; grouping and exact values precede pagination."""
    from . import pregame_ranking as ranking
    from .current_pregame_depth import BOARD_STAKE

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
    depth_revision = db.execute("""
        SELECT (SELECT published_at FROM public.current_pregame_depth ORDER BY published_at DESC LIMIT 1) AS publication,
               (SELECT valid_until FROM public.current_pregame_depth WHERE valid_until>%s ORDER BY valid_until LIMIT 1) AS next,
               (SELECT valid_until FROM public.current_pregame_depth WHERE valid_until<=%s ORDER BY valid_until DESC LIMIT 1) AS previous
        """, (at, at)).fetchone()
    if depth_revision["next"] is not None:
        deadline = min(deadline, depth_revision["next"]) if deadline else depth_revision["next"]
    public_revision = db.execute(
        "SELECT revision,current_schema() AS cohort_schema FROM public.current_pregame_revision WHERE singleton"
    ).fetchone()
    authority = public_revision["revision"]
    if public_revision["cohort_schema"] != "public":
        from .pregame_cohort_authority import authority_state

        state = authority_state(db, at)
        public_start = state["next"]
        if public_start is not None:
            deadline = min(deadline, public_start) if deadline else public_start
        authority = [state["fingerprint"], configured_routes(db), str(public_start)]
    cursor = hashed(
        [
            public_revision["cohort_schema"],
            revision["revision"],
            authority,
            str(boundary),
            str(depth_revision["publication"]),
            str(depth_revision["previous"]),
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
        liquidity_stake_usd=BOARD_STAKE,
    )
    if query.get("updates") == "1":
        return dict(base, changed=query.get("after") != cursor, poll_after_ms=500)
    compare = bool(query.get("bet_id") or query.get("id"))
    coverage = query.get("liquidity_coverage") == "1"
    include_unavailable = (
        compare or coverage or query.get("browse") == "1" or query.get("view") in ("games", "game")
    )
    relation = "eligible_calculations"
    if include_unavailable:
        # Price-qualified rows survive a missing probability reference. Keep the
        # actual refusal reason and null EV; never turn missing EV into zero.
        relation = """(SELECT contract_id,game_key,bet_id,league,family,venue,start_at,main,
            valid_until,net_ev,opportunity_score,reason,payload FROM eligible_calculations
          UNION ALL SELECT price.contract_id,price.game_key,price.payload->>'bet_id',
            price.payload->>'league',price.payload->>'family',price.payload->>'venue',
            price.start_at,(price.payload->>'main')::boolean,price.valid_until,
            NULL::numeric,NULL::numeric,NULL::text,
            price.payload || jsonb_build_object('ev_unavailable_reason',
                COALESCE(calc.reason,stored.reason,'acquisition_or_reference_unavailable'))
          FROM current_pregame_price price
          LEFT JOIN eligible_calculations calc ON calc.contract_id=price.contract_id
          LEFT JOIN current_pregame_calculation stored ON stored.contract_id=price.contract_id
          WHERE calc.contract_id IS NULL OR calc.reason IS NOT NULL)"""
    clauses = [
        "p.reason IS NULL",
        "p.valid_until>%s",
        "p.start_at>%s",
        "e.scheduled_start::timestamptz>%s",
        # Refuse an older writer's native-US fee assumption immediately, before
        # collector recovery replaces the generated row. Raw catalog stays open.
        "(NOT (e.provider='sportsgameodds' AND p.venue='polymarket_us') OR p.payload#>>'{fee_mode,enabled}'='false')",
        """CASE WHEN e.provider='sportsgameodds'
            AND o.price_units IN ('american_odds','decimal_odds')
            AND c.facts#>>'{market_identity,family}' IN ('spread','total')
          THEN mod((c.facts#>>'{market_identity,line}')::numeric*2,1)=0 ELSE true END""",
    ]
    params = [at, at, at, at]
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
        cutoff = at - timedelta(minutes=age)
        clauses.append(
            "(p.payload#>>'{times,source_at}')::timestamptz BETWEEN %s AND %s"
        )
        params.extend([cutoff, at])
        # A fresh market price cannot renew an older or unknown probability
        # reference. Browse prices without a reference remain inspectable.
        clauses.append("""(p.payload->'reference' IS NULL OR p.payload->'reference'='null'::jsonb OR (
            jsonb_array_length(COALESCE(p.payload#>'{reference,prices}','[]'::jsonb))>0
            AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(
                COALESCE(p.payload#>'{reference,prices}','[]'::jsonb)) ref
                WHERE ref->>'source_at' IS NULL
                   OR NOT ((ref->>'source_at')::timestamptz BETWEEN %s AND %s))))""")
        params.extend([cutoff, at])
    positive = (
        not compare
        and not coverage
        and query.get("browse") != "1"
        and query.get("view") not in ("games", "game")
    )
    prefix = """WITH read_clock AS (SELECT %s::timestamptz AS at),
        eligible_calculations AS MATERIALIZED (
        SELECT calc.* FROM current_pregame_calculation calc
        WHERE calc.payload#>>'{acquisition,eligible}'='true'
          AND calc.payload#>>'{acquisition,pull_id}' IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM (SELECT scope.pull_id,scope.state
              FROM public.market_pull_scope scope JOIN public.market_pull pull USING(pull_id)
              WHERE scope.event_id=calc.payload#>>'{source,native_event_id}'
                AND scope.family=calc.family AND scope.period='full_game'
                AND scope.coverage->>'covers_board'='true'
              ORDER BY pull.started_order DESC LIMIT 1) latest
            WHERE latest.state<>'complete' OR latest.pull_id<>calc.payload#>>'{acquisition,pull_id}')
    ), """
    # Keep every alias/venue inside a bet with a positive stored witness. Make
    # this cheap scalar selection a real boundary: otherwise the planner can
    # apply JSON/reference/withdrawal guards to the whole slate before the
    # positive-bet semijoin. Newest observation still wins before EV ranking.
    if positive:
        relation = "candidate_prices"
        prefix += (
            """candidate_prices AS MATERIALIZED (SELECT * FROM eligible_calculations
            WHERE bet_id IN (
              SELECT bet_id FROM eligible_calculations WHERE reason IS NULL AND net_ev>0
              UNION
              SELECT c.bet_id FROM public.current_pregame_depth d JOIN eligible_calculations c USING(contract_id)
              WHERE c.reason IS NULL AND d.valid_until>(SELECT at FROM read_clock)
                AND d.published_at<=(SELECT at FROM read_clock)
                AND (d.valuations->c.input_revision->>'effective_ev')::numeric>0)), """
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
        and not coverage
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
        JOIN current_offer_storage o ON o.contract_id=c.id
        JOIN LATERAL (SELECT * FROM current_event WHERE id=c.event_id LIMIT 1) e ON true
        LEFT JOIN public.current_pregame_depth d ON d.contract_id=p.contract_id
          AND d.published_at<=(SELECT at FROM read_clock)
        LEFT JOIN LATERAL (
          SELECT d.valuations->(p.payload->>'input_revision') AS value
          WHERE d.contract_revision=c.revision AND d.valid_until>(SELECT at FROM read_clock)
        ) depth ON true WHERE """
        + where
    )
    # Multiple native aliases can describe one venue's same logical offer.
    # Source evidence order chooses its observation before EV chooses a venue.
    recency = "(payload#>>'{times,source_at}' IS NOT NULL) DESC,(payload#>>'{times,source_at}')::timestamptz DESC NULLS LAST,(payload#>>'{times,received_at}')::timestamptz DESC,contract_id"
    participation = """
        SELECT p.*, depth.value->'rank_payload' AS native_rank,
          (depth.value->>'effective_ev')::numeric AS native_ev,
          COALESCE(depth.value->'result', jsonb_build_object(
            'status','unknown','size_status','unknown','intended_stake_usd',%s::text,
            'reason', CASE WHEN d.contract_id IS NULL THEN 'book_unobserved'
                WHEN d.contract_revision<>c.revision THEN 'identity_revision_changed'
                WHEN d.valid_until<=(SELECT at FROM read_clock) THEN 'stale_book'
                ELSE 'reference_revision_changed' END))
          || jsonb_strip_nulls(jsonb_build_object('receipt_id',d.receipt_id,'book_known_at',d.known_at,
                'valid_until',d.valid_until,'published_at',d.published_at)) AS liquidity
        """
    if compare:
        participation += """, CASE WHEN depth.value IS NOT NULL THEN
          jsonb_strip_nulls(jsonb_build_object(
            'event_id',d.receipt->'event_id','market_id',d.receipt->'market_id',
            'outcome_id',d.receipt->'outcome_id','opposite_outcome_id',d.receipt->'opposite_outcome_id',
            'sequence',d.receipt->'sequence','market_revision',d.receipt->'market_revision',
            'binding_revision',d.receipt->'binding_revision','contract',d.receipt->'contract',
            'fee',jsonb_strip_nulls(jsonb_build_object(
                'version',d.receipt#>'{fee,version}','schedule_revision',d.receipt#>'{fee,schedule_revision}')),
            'levels',(SELECT jsonb_agg(jsonb_build_object('price',level->'price','quantity',level->'quantity') ORDER BY n)
                FROM jsonb_array_elements(CASE WHEN jsonb_typeof(d.receipt->'levels')='array'
                    THEN d.receipt->'levels' ELSE '[]'::jsonb END) WITH ORDINALITY AS level(level,n)),
            'receipts',(SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                'sha256',proof->'sha256','status',proof->'status','requested_at',proof->'requested_at',
                'received_at',proof->'received_at','observed_at',proof->'observed_at',
                'date',proof->'date','age',proof->'age','etag',proof->'etag',
                'cache_control',COALESCE(proof->'cache-control',proof->'cache_control'),
                'sequence',proof->'sequence')) ORDER BY n)
                FROM jsonb_array_elements(CASE WHEN jsonb_typeof(d.receipt->'receipts')='array'
                    THEN d.receipt->'receipts' ELSE '[]'::jsonb END) WITH ORDINALITY AS proof(proof,n))))
          END AS liquidity_evidence"""
    else:
        participation += ", NULL::jsonb AS liquidity_evidence"
    # The single projection parameter follows the clock parameter and precedes the
    # established candidate guards that already use the same read timestamp.
    params.insert(1, BOARD_STAKE)
    logical = (
        prefix
        + "available AS ("
        + participation
        + source
        + """), projected AS (
            SELECT *, COALESCE(native_rank,payload) AS ranking_payload,
                COALESCE(native_ev,CASE WHEN liquidity->>'status'='unknown' THEN net_ev END) AS effective_ev,
                native_ev IS NOT NULL AS depth_supported,
                payload || jsonb_build_object('liquidity',liquidity)
                  || CASE WHEN liquidity_evidence IS NOT NULL THEN jsonb_build_object('liquidity_evidence',liquidity_evidence)
                    ELSE '{}'::jsonb END AS display_payload
            FROM available), logical AS (
            SELECT DISTINCT ON (bet_id,venue) * FROM projected ORDER BY bet_id,venue,"""
        + recency
        + ") "
    )
    if coverage:
        rows = db.execute(logical + """, sizes AS (
          SELECT league,venue,family,main,liquidity->>'status' AS status,
            liquidity->>'size_status' AS size_status,liquidity->>'reason' AS reason,
            liquidity->>'modeled_net_ev' AS modeled_ev,
            CASE WHEN liquidity->>'size_status' IS DISTINCT FROM 'unknown'
                OR liquidity->>'availability_is_lower_bound'='true' THEN
                split_part(liquidity->>'modeled_stake_usd','/',1)::numeric
                / COALESCE(NULLIF(split_part(liquidity->>'modeled_stake_usd','/',2),''),'1')::numeric END AS stake
          FROM logical), reasons AS (
            SELECT league,venue,family,main,reason,count(*) AS rows FROM sizes
            WHERE reason IS NOT NULL GROUP BY league,venue,family,main,reason
          ) SELECT league,venue,family,main,count(*) AS opportunities,
            count(*) FILTER (WHERE size_status<>'unknown') AS assessable,
            count(*) FILTER (WHERE size_status='full_size') AS full_size,
            count(*) FILTER (WHERE status<>'unknown' AND modeled_ev IS NOT NULL) AS ev_assessable,
            (count(*)*%s::numeric)::text AS intended_stake_usd,
            COALESCE(sum(stake),0)::text AS observed_supported_stake_usd,
            COALESCE((SELECT jsonb_object_agg(reason,rs.rows) FROM reasons rs
              WHERE (rs.league,rs.venue,rs.family,rs.main)=(s.league,s.venue,s.family,s.main)),
              '{}'::jsonb) AS reasons
          FROM sizes s GROUP BY league,venue,family,main ORDER BY league,venue,family,main DESC""",
          (*params, BOARD_STAKE)).fetchall()
        return dict(base, coverage=rows, total=sum(row["opportunities"] for row in rows))
    if compare:
        entries = db.execute(
            logical
            + "SELECT display_payload AS payload,"
            + ranking.expression(selected_sort, payload="ranking_payload")
            + " AS ranking_value FROM logical ORDER BY depth_supported DESC,effective_ev DESC NULLS LAST,net_ev DESC NULLS LAST,contract_id",
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
    grouped = (
        logical.rstrip()
        + """, qualified AS (SELECT *,row_number() OVER (PARTITION BY bet_id ORDER BY
          (effective_ev>0) DESC NULLS LAST,depth_supported DESC,effective_ev DESC NULLS LAST,
          net_ev DESC NULLS LAST,contract_id
          ) AS venue_order FROM logical), best AS (SELECT * FROM qualified WHERE venue_order=1"""
        + (" AND effective_ev>0" if positive else "")
        + ") "
    )
    if query.get("view") == "game":
        if not query.get("game_key"):
            raise ValueError("A game key is required")
        rows = [
            r["payload"]
            for r in db.execute(
                grouped + "SELECT display_payload AS payload FROM best ORDER BY main DESC,family,bet_id",
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
                  'rows',jsonb_agg(b.display_payload ORDER BY b.family,b.bet_id)) AS game
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
    order = "depth_supported DESC,ranking_value DESC NULLS LAST,effective_ev DESC,bet_id"
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
        + ranking.expression(selected_sort, payload="ranking_payload")
        + " AS ranking_value FROM best) SELECT count(*) AS total,"
        + "(SELECT jsonb_agg(jsonb_build_array(display_payload,ranking_value::text) ORDER BY "
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
