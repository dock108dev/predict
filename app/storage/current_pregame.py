"""Affected-game calculation owner and small SQL-only dashboard reads."""

from datetime import datetime, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
from time import monotonic

from psycopg.types.json import Jsonb

from app.comparison import current_pregame as math
from app.comparison.game_phase import scheduled_phase, sgo_event_status, sporting_phase
from app.comparison.public_sportsbook_estimate import signature
from app.comparison.snapshot_fee_outcome import outcome as fee_outcome, reviews
from app.comparison.snapshot_fee_scope import applicability
from app.fees import product_schedules, schedule_lifecycle
from .current_rows import CurrentRowStore, LOCK, contract_id
from .sportsgameodds_reference import EventInputs, read_event
from .store import hashed, stamp
from .sgo_schedule_review import canonical_roles


UPSERT = "INSERT INTO current_pregame_calculation\n            (contract_id,game_key,bet_id,league,family,venue,start_at,main,input_revision,version,valid_until,\n             net_ev,opportunity_score,reason,payload)\n            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)\n            ON CONFLICT(contract_id) DO UPDATE SET game_key=excluded.game_key,bet_id=excluded.bet_id,\n              league=excluded.league,family=excluded.family,venue=excluded.venue,start_at=excluded.start_at,\n              main=excluded.main,input_revision=excluded.input_revision,version=excluded.version,\n              calculated_at=clock_timestamp(),valid_until=excluded.valid_until,net_ev=excluded.net_ev,\n              opportunity_score=excluded.opportunity_score,reason=excluded.reason,payload=excluded.payload\n            WHERE current_pregame_calculation.input_revision<>excluded.input_revision\n                OR current_pregame_calculation.reason IS DISTINCT FROM excluded.reason"


def utc():
    return datetime.now(timezone.utc)


def numeric(value):
    f = Fraction(value)
    with localcontext() as ctx:
        ctx.prec = 80
        return Decimal(f.numerator) / Decimal(f.denominator)


def account_identity():
    """Fingerprint private account facts and their proof without exposing either."""
    import json
    from pathlib import Path
    from hashlib import sha256
    from app.comparison.snapshot_fee_scope import ACCOUNT_PATH, ROOT

    if not ACCOUNT_PATH.exists():
        return None
    try:
        body = ACCOUNT_PATH.read_bytes()
        fact = json.loads(body).get("kalshi") or {}
        path = Path(fact["evidence"]["path"])
        if not path.is_absolute():
            path = ROOT / path
        proof = sha256(path.read_bytes()).hexdigest()
        return hashed([sha256(body).hexdigest(), proof])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return hashed(["account_fact_unavailable", type(exc).__name__])


def configured_routes(db):
    from app.collection.current_policy import DEFAULT, price_routes

    owner = db.execute(
        "SELECT config FROM data_runtime WHERE singleton=true"
    ).fetchone()
    return price_routes(owner["config"] if owner else DEFAULT)


class CalculationContext:
    def __init__(self, db, at):
        self.reviews = reviews(at)
        self.products = product_schedules.read_all(db)
        self.prophetx = schedule_lifecycle.read(db)
        from app.fees import pricing

        self.fee_rules = pricing.read(db)
        self.price_routes = configured_routes(db)
        from app.comparison.snapshot_fee_scope import ACCOUNT_PATH, kalshi_account

        self.account = None
        self.account_error = None
        self.account_revision = None
        if ACCOUNT_PATH.exists():
            self.account_revision = account_identity()
            try:
                fact = kalshi_account(at)
                precision = fact.get("balance_precision", "0.0001")
                if precision not in ("0.0001", "0.01"):
                    raise ValueError("kalshi_account_precision_unbound")
                self.account = dict(
                    membership=fact["membership"],
                    channel=fact["channel"],
                    balance_precision=precision,
                    revision=self.account_revision,
                    review_before=fact["review_before"],
                    effective_from=fact["effective_from"],
                )
            except (ValueError, KeyError, OSError, TypeError) as exc:
                self.account_error = str(exc)

    def fee(self, record, at):
        q, market = record["quote"], record["market_identity"]
        row = dict(
            venue=q["venue"],
            source=q["source"],
            original=q["original"],
            times=q["times"],
            league=record["event"]["competition"],
            start_at=record["event"]["scheduled_start"],
            captured_at=at.isoformat(),
            game_state="scheduled",
            market=dict(
                market="winner"
                if market["family"] == "moneyline"
                else market["family"],
                period=market["period"],
            ),
            fee_applicability=applicability(record),
        )
        from app.fees import pricing

        if q["venue"] == "kalshi" and self.account_error:
            return dict(available=False, reason=self.account_error)
        review = (
            schedule_lifecycle.for_offer(
                self.prophetx, row, at, fallback=self.reviews[q["venue"]]
            )
            if q["venue"] == "prophetx"
            else product_schedules.for_offer(
                self.products, row, at, fallback=self.reviews[q["venue"]]
            )
        )
        if q["venue"] in self.fee_rules:
            future = pricing.next_change(self.fee_rules, q["venue"], row["league"], at)
            configured = pricing.select(self.fee_rules, q["venue"], row["league"], at)
            if configured is None:
                return dict(
                    available=False,
                    reason="fee_rule_no_current_schedule",
                    evidence=dict(next_change_at=future),
                )
            if q["venue"] == "kalshi" and self.account:
                configured = dict(
                    configured, balance_precision=self.account["balance_precision"]
                )
            value = pricing.outcome(row, configured, review=review)
            deadlines = [
                v for v in (future, value["evidence"].get("next_change_at")) if v
            ]
            value["evidence"]["next_change_at"] = min(
                deadlines, key=stamp, default=None
            )
            if q["venue"] == "kalshi" and self.account:
                value["evidence"]["account_profile"] = self.account
            return value
        if q["venue"] == "novig" and q["source"]["provider"] == "sportsgameodds":
            from app.comparison.sgo_native_binding import bind, published_pregame_fee
            from .sgo_native_catalog import read

            catalog = read(self.db, {record["event"]["id"]})
            binding = bind(record, catalog.get(record["event"]["id"]), at=at)
            return published_pregame_fee(record, binding, at=at, review=review)
        from app.comparison.trade_preview import order_step

        step = order_step(row) if q["venue"] == "polymarket_us" else None
        quantity = step if step and step > 0 and 1 % step else "1"
        fee = fee_outcome(
            row, at=at, phase="scheduled", review=review, quantity=quantity
        )
        if fee.get("available") and q["venue"] == "kalshi" and self.account:
            fee = dict(
                fee,
                classification="account_reviewed",
                evidence=dict(fee["evidence"], account_profile=self.account),
            )
        return fee


def affected(db, job, at):
    """Resolve only the changed source occurrence, including book-only SGO frames."""
    event = db.execute(
        "SELECT id,facts FROM current_event WHERE provider=%s AND native_event_id=%s",
        (job["provider"], job["native_event_id"]),
    ).fetchone()
    if event:
        start = stamp(event["facts"]["scheduled_start"])
    else:
        frame = (
            db.execute(
                "SELECT facts->>'starts_at' AS start FROM current_sgo_event_frame WHERE event_id=%s",
                (job["native_event_id"],),
            ).fetchone()
            if job["provider"] == "sportsgameodds"
            else None
        )
        if not frame or not frame["start"]:
            return [], {}, None
        start = stamp(frame["start"])
    inputs = EventInputs(db)
    schedules = inputs.occurrences(at, starts=[start])

    def canonical(key, provider, native):
        return (
            canonical_roles(native, key, at=at) if provider == "sportsgameodds" else key
        )

    schedules = {
        canonical(key, "sportsgameodds", native): values
        for key, values in schedules.items()
        for native in values
    }
    occurrence = (
        canonical(
            signature(event["facts"], event["facts"]["competition"]),
            job["provider"],
            job["native_event_id"],
        )
        if event
        else next(
            (
                key
                for key, values in schedules.items()
                if job["native_event_id"] in values
            ),
            None,
        )
    )
    if occurrence is None:
        return [], {}, None
    league, start, home, away = occurrence
    events = list(
        db.execute(
            """SELECT id,provider,native_event_id,facts FROM current_event
        WHERE competition=%s AND scheduled_start::timestamptz=%s
          AND ((facts->>'home'=%s AND facts->>'away'=%s) OR (facts->>'home'=%s AND facts->>'away'=%s))""",
            (league, start, home, away, away, home),
        )
    )
    events = [
        e
        for e in events
        if canonical(signature(e["facts"], league), e["provider"], e["native_event_id"])
        == occurrence
    ]
    observations = {}
    candidates = schedules.get(occurrence, {})
    if len(candidates) == 1:
        native, schedule = next(iter(candidates.items()))
        status = sporting_phase(
            {"status": sgo_event_status(schedule.get("status") or {})}
        )
        if (
            schedule["valid"]
            and schedule["phase"] == "pregame"
            and status["reason"] is None
            and status["state"] != "live"
        ):
            observations[native] = read_event(db, native, bookmakers=math.BEST_BOOKS)
            original_occurrence = (
                signature(event["facts"], league)
                if event and job["provider"] == "sportsgameodds"
                else schedule.get("occurrence")
            )
            if original_occurrence and original_occurrence[2:] != occurrence[2:]:
                for entry in observations[native]:
                    q = entry["facts"]
                    if q.get("side") in ("home", "away"):
                        q["canonical_side"] = "away" if q["side"] == "home" else "home"
    return events, observations, occurrence


def input_identity(record, reference, context, fee=None):
    """Economic inputs exclude receipt-envelope changes for an unchanged price."""
    q = record["quote"]
    event = record["event"]
    meta = record.get("comparison_source_metadata") or {}
    venue = q["venue"]
    product = product_schedules.key_for(dict(venue=venue, game_state="scheduled"))
    fee_policy = (
        context.prophetx if venue == "prophetx" else context.products.get(product)
    )
    return hashed(
        [
            math.VERSION,
            q["original"],
            q["source"],
            q["times"].get("source_at"),
            record["market_identity"],
            record["selection"],
            {
                key: event.get(key)
                for key in (
                    "competition",
                    "scheduled_start",
                    "home",
                    "away",
                    "participants",
                    "title",
                    "status",
                    "state",
                    "game_number",
                    "shared_provider_ids",
                    "occurrence_conflict",
                    "schedule_conflict",
                )
            },
            {
                key: meta.get(key)
                for key in (
                    "alternate",
                    "scoring_scope",
                    "series_id",
                    "native_market_type",
                    "native_key",
                    "phase",
                    "public_retail_observation",
                    "source_predicate",
                )
            },
            reference,
            context.reviews.get(venue),
            context.fee_rules.get(venue),
            context.price_routes.get(venue),
            fee,
            fee_policy,
            context.account_revision if venue == "kalshi" else None,
        ]
    )


def calculate_game(db, job, context, *, at):
    events, observations, occurrence = affected(db, job, at)
    ids = [e["id"] for e in events]
    if not ids:
        return dict(offers=0, complete=0)
    capture_ids = [
        e["id"] for e in events if e["provider"] in set(context.price_routes.values())
    ]
    if not capture_ids:
        db.execute(
            "DELETE FROM current_pregame_calculation WHERE contract_id IN (SELECT id FROM current_contract_storage WHERE event_id=ANY(%s))",
            (ids,),
        )
        return dict(offers=0, complete=0)
    records = CurrentRowStore(db).capture(include_depth=False, event_ids=capture_ids)[
        "records"
    ]
    records = [
        r
        for r in records
        if r["quote"]["venue"] not in context.price_routes
        or r["quote"]["source"]["provider"] == context.price_routes[r["quote"]["venue"]]
    ]
    from app.comparison.occurrence_matching import OccurrenceResolver

    resolver = OccurrenceResolver()
    facts = {}
    for record in records:
        source = record["quote"]["source"]
        if source["provider"] == "sportsgameodds":
            record["event"] = dict(
                record["event"], home=occurrence[2], away=occurrence[3]
            )
        key = (source["provider"], source["native_event_id"])
        if key not in facts:
            facts[key] = resolver._facts(record)
    conflicts = {
        key
        for key, f in facts.items()
        if f["conflict"]
        or any(not resolver._consistent(f, other) for other in facts.values())
    }
    game_key = "pregame:" + hashed(
        [occurrence[0], occurrence[1].isoformat(), *occurrence[2:]]
    )
    previous = {
        r["contract_id"]: r
        for r in db.execute(
            "SELECT contract_id,input_revision,reason,valid_until FROM current_pregame_calculation WHERE contract_id=ANY(%s)",
            ([contract_id(r) for r in records],),
        )
    }
    references = {}
    reference_errors = {}
    reference_inputs = math.ReferenceInputs(observations)
    updates = []
    complete = 0
    context.db = db
    accepted = set()
    for record in records:
        cid = contract_id(record)
        accepted.add(cid)
        q, market, event = record["quote"], record["market_identity"], record["event"]
        family = market["family"]
        reason = None
        payload = None
        fee = None
        revision = None
        try:
            if (q["source"]["provider"], q["source"]["native_event_id"]) in conflicts:
                raise ValueError("occurrence_identity_conflict")
            if q["source"]["provider"] != context.price_routes.get(q["venue"]):
                raise ValueError("acquisition_route_outside_primary_venue_scope")
            if q["venue"] not in ("kalshi", "polymarket_us", "novig", "prophetx"):
                raise ValueError("venue_outside_pregame_scope")
            if q["source"]["provider"] not in (
                "sportsgameodds",
                "kalshi",
                "polymarket_us",
            ):
                raise ValueError("acquisition_route_outside_pregame_scope")
            if market["period"] != "full_game" or family not in (
                "moneyline",
                "spread",
                "total",
            ):
                raise ValueError("market_outside_pregame_scope")
            if scheduled_phase(event, at)["state"] != "scheduled":
                raise ValueError("pregame_closed")
            if q["state"] == "unavailable":
                raise ValueError("price_withdrawn")
            if (
                event.get("occurrence_conflict")
                or event.get("conflicting_duplicate")
                or event.get("schedule_conflict")
            ):
                raise ValueError("occurrence_conflict")
            if stamp(market["scheduled_start"]) != stamp(event["scheduled_start"]):
                # The existing schedule owner validates ordered reschedules.
                from .schedule_metadata import project

                if (
                    project(event, record)["market_identity"]["scheduled_start"]
                    != event["scheduled_start"]
                ):
                    raise ValueError("occurrence_schedule_conflict")
            key = math.reference_key(record)
            if key in reference_errors:
                raise ValueError(reference_errors[key])
            if key not in references:
                try:
                    references[key] = math.reference(record, reference_inputs, at=at)
                except ValueError as exc:
                    reference_errors[key] = str(exc)
                    raise
            fee = context.fee(record, at)
            revision = input_identity(record, references[key], context, fee)
            prior = previous.get(cid)
            if (
                prior
                and prior["input_revision"] == revision
                and prior["reason"] is None
                and stamp(prior["valid_until"]) > at
            ):
                complete += 1
                continue
            if not fee.get("available"):
                raise ValueError(fee.get("reason") or "fee_schedule_unavailable")
            payload = math.calculate(
                record, references[key], fee, at=at, game_key=game_key
            )
        except (KeyError, TypeError, ValueError, ArithmeticError, OSError) as exc:
            reason = str(exc)[:160] or type(exc).__name__
        revision = revision or input_identity(record, dict(reason=reason), context)
        deadline = event["scheduled_start"]
        if payload or fee:
            evidence = dict(
                payload["fee"]["evidence"] if payload else fee.get("evidence") or {}
            )
            if evidence.get("account_profile"):
                evidence["account_review_before"] = evidence["account_profile"][
                    "review_before"
                ]
            deadline = min(
                [
                    stamp(deadline),
                    *(
                        stamp(evidence[k])
                        for k in (
                            "review_before",
                            "next_change_at",
                            "account_review_before",
                        )
                        if evidence.get(k)
                    ),
                ]
            ).isoformat()
        if payload:
            payload["input_revision"] = revision
        prior = previous.get(cid)
        if (
            reason
            and prior
            and prior["reason"] == reason
            and prior["input_revision"] == revision
        ):
            continue
        updates.append(
            (
                cid,
                game_key,
                payload["bet_id"] if payload else None,
                event["competition"],
                family,
                q["venue"],
                event["scheduled_start"],
                payload["main"] if payload else False,
                revision,
                math.VERSION,
                deadline,
                numeric(payload["raw"]["net_ev"]) if payload else None,
                numeric(payload["raw"]["opportunity_score"]) if payload else None,
                reason,
                Jsonb(payload) if payload else None,
            )
        )
        complete += payload is not None
    if updates:
        with db.cursor() as cursor:
            cursor.executemany(UPSERT, updates)
    db.execute(
        "DELETE FROM current_pregame_calculation WHERE game_key=%s AND NOT(contract_id=ANY(%s))",
        (game_key, sorted(accepted)),
    )
    return dict(offers=len(records), complete=complete)


def process(db, *, limit=32, keys=None, at=None):
    """Recover durable admissions, atomically replacing each game's complete rows.

    Admission and final calculation use the existing writer lock in the same
    order. A failure rolls back only this game; other jobs and source facts stay.
    No browser caller invokes this function.
    """
    context = None
    registry_identity = None
    results = []
    attempted = set()
    for _ in range(limit):
        started = monotonic()
        with db.transaction():
            # Every writer takes this lock before touching the coalesced queue.
            db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
            job = db.execute(
                """SELECT * FROM current_pregame_work
                WHERE NOT((provider||':'||native_event_id)=ANY(%s))
                  AND (%s::text[] IS NULL OR (provider||':'||native_event_id)=ANY(%s))
                  AND (attempted_at IS NULL OR error IS NULL OR attempted_at<clock_timestamp()-interval '2 seconds')
                ORDER BY admitted_at,provider,native_event_id LIMIT 1 FOR UPDATE SKIP LOCKED""",
                (sorted(attempted), keys, keys),
            ).fetchone()
            if not job:
                break
            key = job["provider"] + ":" + job["native_event_id"]
            attempted.add(key)
            try:
                with db.transaction():
                    effective_at = at or utc()
                    registry = tuple(
                        (r["venue"], r["state"])
                        for r in db.execute(
                            "SELECT venue,state FROM public_fee_schedule ORDER BY venue"
                        )
                    )
                    current_identity = hashed([registry, account_identity()])
                    if context is None or current_identity != registry_identity:
                        context = CalculationContext(db, effective_at)
                        registry_identity = current_identity
                    result = calculate_game(db, job, context, at=effective_at)
                    db.execute(
                        "DELETE FROM current_pregame_work WHERE provider=%s AND native_event_id=%s AND revision=%s",
                        (job["provider"], job["native_event_id"], job["revision"]),
                    )
                    db.execute(
                        "UPDATE current_pregame_revision SET revision=revision+1,committed_at=clock_timestamp() WHERE singleton"
                    )
                    results.append(
                        dict(
                            key=key,
                            admitted_at=job["admitted_at"].isoformat(),
                            seconds=monotonic() - started,
                            **result,
                        )
                    )
            except Exception as exc:
                from app.diagnostics import failure

                failure(__name__, "affected_game_calculation", exc)
                db.execute(
                    "UPDATE current_pregame_work SET error=%s,attempted_at=clock_timestamp() WHERE provider=%s AND native_event_id=%s",
                    (type(exc).__name__, job["provider"], job["native_event_id"]),
                )
                results.append(dict(key=key, error=type(exc).__name__))
        if results and "error" not in results[-1]:
            finished = utc()
            results[-1].update(
                committed_at=finished.isoformat(),
                admission_to_commit_ms=round(
                    (finished - job["admitted_at"]).total_seconds() * 1000, 3
                ),
            )
    return results


def read(db, query, *, at=None):
    """Read committed complete rows; grouping and exact values precede pagination."""
    at = at or utc()
    limit = max(1, min(100, int(query.get("limit", "30"))))
    offset = max(0, int(query.get("offset", "0")))
    revision = db.execute(
        "SELECT revision,committed_at FROM current_pregame_revision WHERE singleton"
    ).fetchone()
    # Time is part of the cheap cursor only at a real eligibility deadline.
    deadline = db.execute(
        "SELECT min(valid_until) AS at FROM current_pregame_calculation WHERE reason IS NULL AND valid_until>%s",
        (at,),
    ).fetchone()["at"]
    boundary = db.execute(
        "SELECT max(valid_until) AS at FROM current_pregame_calculation WHERE reason IS NULL AND valid_until<=%s",
        (at,),
    ).fetchone()["at"]
    cursor = hashed([revision["revision"], str(boundary)])
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
    )
    if query.get("updates") == "1":
        return dict(base, changed=query.get("after") != cursor, poll_after_ms=500)
    clauses = [
        "p.reason IS NULL",
        "p.valid_until>%s",
        "p.start_at>%s",
        "e.scheduled_start::timestamptz>%s",
    ]
    params = [at, at, at]
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
    if query.get("lines") != "all" and not query.get("id") and not query.get("bet_id"):
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
            "NOT (COALESCE(e.facts->'status','{}'::jsonb) @> '{\"live\":true}'::jsonb)",
            "NOT (COALESCE(e.facts->'status','{}'::jsonb) @> '{\"ended\":true}'::jsonb)",
            "COALESCE(e.facts#>>'{status,status}','') NOT IN ('cancelled','final','suspended','started','delayed')",
            """NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p.payload#>'{reference,prices}') r
           LEFT JOIN current_sgo_reference s ON s.id=r->>'input_id'
           WHERE s.id IS NULL OR s.facts->'available' IS DISTINCT FROM 'true'::jsonb)""",
        ]
    )
    where = " AND ".join(clauses)
    source = (
        """ FROM current_pregame_calculation p JOIN current_contract c ON c.id=p.contract_id
        JOIN current_offer o ON o.contract_id=c.id JOIN current_event e ON e.id=c.event_id WHERE """
        + where
    )
    compare = bool(query.get("bet_id") or query.get("id"))
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
            logical + "SELECT payload FROM logical ORDER BY net_ev DESC,contract_id",
            params,
        ).fetchall()
        return dict(
            base,
            rows=[r["payload"] for r in entries],
            total=len(entries),
            offset=0,
            limit=limit,
        )
    positive = query.get("browse") != "1"
    grouped = (
        logical.rstrip()
        + ", qualified AS (SELECT *,row_number() OVER (PARTITION BY bet_id ORDER BY net_ev DESC,contract_id) AS venue_order FROM logical), best AS (SELECT * FROM qualified WHERE venue_order=1"
        + (" AND net_ev>0" if positive else "")
        + ") "
    )
    total = db.execute(grouped + "SELECT count(*) AS n FROM best", params).fetchone()[
        "n"
    ]
    rows = db.execute(
        grouped
        + """SELECT payload FROM best
        ORDER BY opportunity_score DESC,net_ev DESC,bet_id LIMIT %s OFFSET %s""",
        (*params, limit, offset),
    ).fetchall()
    return dict(
        base, rows=[r["payload"] for r in rows], total=total, offset=offset, limit=limit
    )


def operational(db):
    state = dict(
        db.execute("""SELECT (SELECT count(*) FROM current_offer) AS stored_offers,
        (SELECT count(*) FROM current_pregame_calculation WHERE reason IS NULL AND valid_until>clock_timestamp()) AS complete_offers,
        (SELECT count(*) FROM current_pregame_work) AS awaiting_recovery,
        (SELECT max(calculated_at) FROM current_pregame_calculation WHERE reason IS NULL) AS latest_complete_calculation,
        (SELECT committed_at FROM current_pregame_revision WHERE singleton) AS last_successful_game_commit""").fetchone()
    )
    state["sources"] = [
        dict(
            provider=r["provider"],
            latest_receipt=stamp(r["received_at"]).isoformat()
            if r["received_at"]
            else None,
        )
        for r in db.execute("""
        SELECT DISTINCT ON(e.provider) e.provider,o.received_at FROM current_offer o
        JOIN current_contract c ON c.id=o.contract_id JOIN current_event e ON e.id=c.event_id
        ORDER BY e.provider,o.received_order DESC""")
    ]
    state["failures"] = list(
        db.execute("""SELECT provider,native_event_id,error FROM current_pregame_work
        WHERE error IS NOT NULL ORDER BY attempted_at DESC LIMIT 12""")
    )
    return state
