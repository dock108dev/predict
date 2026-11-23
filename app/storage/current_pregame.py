"""Affected-game calculation owner and small SQL-only dashboard reads."""

from datetime import datetime, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
from time import monotonic

from psycopg.types.json import Jsonb

from app.comparison import current_pregame as math
from app.comparison import fee_mode
from app.comparison.game_phase import scheduled_phase, sgo_event_status, sporting_phase
from app.comparison.public_sportsbook_estimate import signature
from app.comparison.snapshot_fee_outcome import outcome as fee_outcome, reviews
from app.comparison.snapshot_fee_scope import applicability, provider_venue_fee_reason
from app.fees import product_schedules, schedule_lifecycle
from .current_rows import CurrentRowStore, LOCK, contract_id
from .sportsgameodds_reference import EventInputs, read_event
from .store import hashed, stamp
from .sgo_schedule_review import canonical_roles


UPSERT = """INSERT INTO current_pregame_calculation
    (contract_id,game_key,bet_id,league,family,venue,start_at,main,input_revision,version,valid_until,
     net_ev,opportunity_score,reason,payload)
    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT(contract_id) DO UPDATE SET game_key=excluded.game_key,bet_id=excluded.bet_id,
      league=excluded.league,family=excluded.family,venue=excluded.venue,start_at=excluded.start_at,
      main=excluded.main,input_revision=excluded.input_revision,version=excluded.version,
      calculated_at=clock_timestamp(),valid_until=excluded.valid_until,net_ev=excluded.net_ev,
      opportunity_score=excluded.opportunity_score,reason=excluded.reason,payload=excluded.payload
    WHERE current_pregame_calculation.input_revision<>excluded.input_revision
       OR current_pregame_calculation.reason IS DISTINCT FROM excluded.reason
       OR current_pregame_calculation.version<>excluded.version
       OR current_pregame_calculation.payload#>>'{reference,selection_policy}'
            IS DISTINCT FROM excluded.payload#>>'{reference,selection_policy}'
       OR current_pregame_calculation.payload#>>'{coherent_probability,policy_version}'
            IS DISTINCT FROM excluded.payload#>>'{coherent_probability,policy_version}'"""


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
        self.fee_mode = fee_mode.read(db)
        self.price_routes = configured_routes(db)
        self.reviews, self.products, self.fee_rules = {}, {}, {}
        self.prophetx = None
        self.account = self.account_error = self.account_revision = None
        if not self.fee_mode['enabled']:
            return
        self.reviews = reviews(at)
        self.products = product_schedules.read_all(db)
        self.prophetx = schedule_lifecycle.read(db)
        from app.fees import pricing

        self.fee_rules = pricing.read(db)
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
        if not self.fee_mode['enabled']:
            return fee_mode.zero_fee(record, self.fee_mode)
        value = self._included_fee(record, at)
        return dict(value, fee_mode=self.fee_mode,
            evidence=dict(value.get('evidence') or {}, fee_mode=self.fee_mode))

    def _included_fee(self, record, at):
        q, market = record["quote"], record["market_identity"]
        if reason := provider_venue_fee_reason(record):
            return dict(available=False, reason=reason, evidence=dict(
                provider=q["source"]["provider"], represented_venue=q["venue"],
                provider_bookmaker_id=(record.get("comparison_source_metadata") or {}).get("provider_bookmaker_id"),
                venue_equivalence="unestablished",
            ))
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
            context.fee_mode,
        ]
    )


def preserve_previous_conditional(db, cid, reason):
    old = db.execute("""SELECT c.payload,p.record,p.fee_input
        FROM current_pregame_calculation c LEFT JOIN current_pregame_price p
        USING(contract_id) WHERE c.contract_id=%s AND c.payload IS NOT NULL""", (cid,)).fetchone()
    if old:
        from app.research.records import preserve_conditional

        try:
            preserve_conditional(db, old["payload"], record=old["record"],
                                 fee_input=old["fee_input"], reason=reason)
        except Exception as exc:
            # Guarded reads withhold current applicability while rollback keeps
            # an original that cannot yet be safely retained in history.
            raise RuntimeError("conditional_calculation_retention_unavailable") from exc


def calculate_game(db, job, context, *, at):
    if job["provider"] not in {"sportsgameodds", *context.price_routes.values()}:
        db.execute(
            "DELETE FROM current_pregame_price WHERE contract_id IN (SELECT c.id FROM current_contract_storage c JOIN current_event e ON e.id=c.event_id WHERE e.provider=%s AND e.native_event_id=%s)",
            (job["provider"], job["native_event_id"]),
        )
        db.execute(
            """DELETE FROM current_pregame_calculation WHERE contract_id IN
            (SELECT c.id FROM current_contract_storage c JOIN current_event e ON e.id=c.event_id
             WHERE e.provider=%s AND e.native_event_id=%s)""",
            (job["provider"], job["native_event_id"]),
        )
        return dict(offers=0, complete=0)
    events, observations, occurrence = affected(db, job, at)
    ids = [e["id"] for e in events]
    if not ids:
        return dict(offers=0, complete=0)
    capture_ids = [
        e["id"] for e in events if e["provider"] in set(context.price_routes.values())
    ]
    if not capture_ids:
        db.execute(
            "DELETE FROM current_pregame_price WHERE contract_id IN (SELECT id FROM current_contract_storage WHERE event_id=ANY(%s))",
            (ids,),
        )
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
            """SELECT contract_id,input_revision,reason,valid_until,version,
                payload#>>'{reference,selection_policy}' AS reference_policy,
                payload#>>'{coherent_probability,policy_version}' AS coherent_policy
                FROM current_pregame_calculation WHERE contract_id=ANY(%s)""",
            ([contract_id(r) for r in records],),
        )
    }
    references = {}
    reference_errors = {}
    coherent = {}
    reference_inputs = math.ReferenceInputs(
        observations, books=math.COHERENT_POLICIES[math.EXPANSION_POLICY]
    )
    updates = []
    price_updates = []
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
        price_payload = None
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
            if settlement_reason := math.posted_settlement_reason(record):
                preserve_previous_conditional(db, cid, settlement_reason)
                raise ValueError(settlement_reason)
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
            fee = context.fee(record, at)
            if not fee.get("available"):
                if fee.get("reason") == "provider_venue_fee_applicability_unestablished":
                    preserve_previous_conditional(db, cid, fee["reason"])
                raise ValueError(fee.get("reason") or "fee_schedule_unavailable")
            price_payload = math.calculate(record, None, fee, at=at, game_key=game_key)
            key = math.reference_key(record)
            if key not in coherent:
                try:
                    coherent[key] = math.qualified_coherent_reference(record, reference_inputs, at=at)
                except ValueError as exc:
                    coherent[key] = dict(
                        available=False, reason=str(exc),
                        policy_version=math.COHERENT_POLICY,
                        probability=None, probabilities=None,
                    )
            price_payload["coherent_probability"] = coherent[key]
            from app.collection.sportsgameodds_current_rows import source_bookmaker

            try:
                price_payload["alternative_probabilities"] = {
                    math.EXPANSION_POLICY: math.qualified_coherent_reference(
                        record, reference_inputs, at=at, policy=math.EXPANSION_POLICY,
                        evaluated_book=source_bookmaker(record),
                    )
                }
            except ValueError as exc:
                price_payload["alternative_probabilities"] = {
                    math.EXPANSION_POLICY: dict(
                        policy_version=math.EXPANSION_POLICY, probability=None,
                        probabilities=None, reason=str(exc),
                    )
                }
            price_payload["sportsbook_event_ids"] = list(observations)
            price_payload["sportsbook_sides_reversed"] = {
                eid: any(
                    q["facts"].get("canonical_side")
                    and q["facts"]["canonical_side"] != q["facts"]["side"]
                    for q in quotes
                )
                for eid, quotes in observations.items()
            }
            # Book event/role attachment can change without changing this price.
            price_payload["input_revision"] = hashed(
                [
                    input_identity(record, None, context, fee),
                    price_payload["sportsbook_event_ids"],
                    price_payload["sportsbook_sides_reversed"],
                    math.probability_inputs(coherent[key]),
                    {p: math.probability_inputs(r) for p, r in price_payload["alternative_probabilities"].items()},
                ]
            )
            if key in reference_errors:
                raise ValueError(reference_errors[key])
            if key not in references:
                try:
                    references[key] = math.reference(record, reference_inputs, at=at)
                except ValueError as exc:
                    reference_errors[key] = str(exc)
                    raise
            revision = hashed([input_identity(record, references[key], context, fee),
                               math.probability_inputs(coherent[key]),
                               {p: math.probability_inputs(r) for p, r in price_payload["alternative_probabilities"].items()}])
            prior = previous.get(cid)
            if (
                prior
                and prior["input_revision"] == revision
                and prior["reason"] is None
                and prior["version"] == math.VERSION
                and prior["reference_policy"] == math.REFERENCE_POLICY
                and prior["coherent_policy"] == math.COHERENT_POLICY
                and stamp(prior["valid_until"]) > at
            ):
                complete += 1
                price_updates.append(
                    (
                        cid,
                        game_key,
                        event["scheduled_start"],
                        prior["valid_until"],
                        Jsonb(price_payload),
                        Jsonb(record),
                        Jsonb(fee),
                    )
                )
                continue
            payload = math.calculate(
                record, references[key], fee, at=at, game_key=game_key
            )
            payload["coherent_probability"] = coherent[key]
            payload["alternative_probabilities"] = price_payload["alternative_probabilities"]
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
        if price_payload:
            price_updates.append(
                (
                    cid,
                    game_key,
                    event["scheduled_start"],
                    deadline,
                    Jsonb(price_payload),
                    Jsonb(record),
                    Jsonb(fee),
                )
            )
        else:
            db.execute("DELETE FROM current_pregame_price WHERE contract_id=%s", (cid,))
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
    if price_updates:
        with db.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO current_pregame_price
                (contract_id,game_key,start_at,valid_until,payload,record,fee_input) VALUES(%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(contract_id) DO UPDATE SET game_key=excluded.game_key,start_at=excluded.start_at,
                  valid_until=excluded.valid_until,payload=excluded.payload,record=excluded.record,fee_input=excluded.fee_input
                WHERE current_pregame_price.payload->>'input_revision' IS DISTINCT FROM excluded.payload->>'input_revision'""",
                price_updates,
            )
    db.execute(
        "DELETE FROM current_pregame_price WHERE game_key=%s AND NOT(contract_id=ANY(%s))",
        (game_key, sorted(accepted)),
    )
    if updates:
        with db.cursor() as cursor:
            cursor.executemany(UPSERT, updates)
    db.execute(
        "DELETE FROM current_pregame_calculation WHERE game_key=%s AND NOT(contract_id=ANY(%s))",
        (game_key, sorted(accepted)),
    )
    return dict(offers=len(records), complete=complete)


def process(db, *, limit=32, keys=None, at=None, can_continue=None):
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
        if can_continue is not None and not can_continue():
            break
        started = monotonic()
        with db.transaction():
            db.execute("SET LOCAL max_parallel_workers_per_gather=0")
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
                    captured_mode = fee_mode.read(db)
                    registry = tuple(
                        (r["venue"], r["state"])
                        for r in db.execute(
                            "SELECT venue,state FROM public_fee_schedule ORDER BY venue"
                        )
                    ) if captured_mode['enabled'] else None
                    current_identity = hashed([registry,
                        account_identity() if captured_mode['enabled'] else None, captured_mode])
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


def enqueue_due(db, *, at=None):
    """Recover expired fee inputs even when an EV reference is unavailable."""
    at = at or utc()
    db.execute(
        """INSERT INTO current_pregame_work(provider,native_event_id)
        SELECT DISTINCT e.provider,e.native_event_id FROM (
            SELECT contract_id FROM current_pregame_calculation
            WHERE valid_until<=%s AND start_at>%s
              AND (reason IS NULL OR reason='fee_rule_no_current_schedule')
            UNION
            SELECT contract_id FROM current_pregame_price
            WHERE valid_until<=%s AND start_at>%s
        ) due JOIN current_contract c ON c.id=due.contract_id
        JOIN current_event e ON e.id=c.event_id
        ON CONFLICT DO NOTHING""",
        (at, at, at, at),
    )


def read(db, query, *, at=None):
    """Keep the public read entry point and its injected clock/route policy."""
    from .current_pregame_read import read as read_current

    return read_current(db, query, at=at, clock=utc, configured_routes=configured_routes)


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
