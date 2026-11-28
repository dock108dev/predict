"""Native Dashboard publication; SGO references and frozen experiments stay separate."""

from collections import Counter
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction as F

from psycopg.types.json import Jsonb

from app.collection.native_trading_identity import link, expected
from app.comparison import current_pregame as math
from app.comparison.cashflows import exact_wire as wire
from app.comparison.experiment_depth_execution import evaluate_at_stake
from app.comparison.native_observation import WITHDRAWALS, adopt, clock, revision
from app.comparison.pregame_valuation import american, decimal_display
from app.comparison.sgo_native_binding import pregame_subject_roles
from . import sgo_native_catalog
from .current_pregame_depth import _present, unknown
from .current_rows import contract_id
from .pregame_known_withdrawals import phase_closed, reference_known_unavailable
from .sportsgameodds_reference import read_event
from .store import encoded, hashed, stamp

VERSION = "native-trading-offers-1"
PUBLICATION_LOCK = 901128
DASHBOARD_UPDATES_CHANNEL = "predict_novig_dashboard"
HORIZON = timedelta(hours=24)
REFERENCE_AGE = timedelta(seconds=900)
MAX_SNAPSHOT_BYTES = 512 * 1024
SNAPSHOT_BUDGET = 384 * 1024 * 1024
SUPERSEDED_EVIDENCE_AGE = timedelta(minutes=5)
SUPERSEDED_PRESSURE_AGE = timedelta(minutes=2)
PAST_OFFER_AGE = timedelta(hours=2)
PRIORITY_WINDOW = timedelta(hours=2)


# The same negative authority applies to the board, the detail/amount route,
# and the coverage report. The historical evidence stays replayable as saved.
def _reference_current(game_link):
    return (
        "NOT COALESCE(" + phase_closed("source_event") + ",false)"
        " AND (source_event.scheduled_start IS NULL OR source_event.scheduled_start::timestamptz"
        f" = ({game_link}->>'sgo_start')::timestamptz)"
        " AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE("
        " s.payload#>'{reference,required_input_prices}',s.payload#>'{reference,prices}',"
        " '[]'::jsonb)) witness WHERE "
        + reference_known_unavailable("witness->>'input_id'")
        + ")"
    )


def _source_event(game_link):
    return (
        " LEFT JOIN public.current_event source_event ON source_event.provider='sportsgameodds'"
        f" AND source_event.native_event_id={game_link}->>'sgo_event_id' "
    )


def _game_closed(game_link, clock_parameter="%s"):
    return (
        "COALESCE(" + phase_closed("source_event") + " OR "
        f"COALESCE(source_event.scheduled_start,{game_link}->>'sgo_start')::timestamptz"
        f"<={clock_parameter},false)"
    )


REFERENCE_CURRENT = _reference_current("(s.payload->'game_link')")
SOURCE_EVENT = _source_event("(s.payload->'game_link')")
GAME_CLOSED = _game_closed("(s.payload->'game_link')")


def _current_reference(row, at):
    if not row["reference_current"]:
        return "reference_withdrawn"
    until = row["reference_valid_until"]
    if until and stamp(until) <= at:
        return "reference_stale"
    return None


def anchors(db, at, *, novig_events=()):
    rows = db.execute(
        f"""WITH upcoming AS MATERIALIZED (
            SELECT e.native_event_id, e.facts, e.scheduled_start FROM public.current_event e
            WHERE e.provider='sportsgameodds'
            AND e.scheduled_start::timestamptz>%s AND e.scheduled_start::timestamptz<%s
            AND e.expires_order>extract(epoch FROM %s::timestamptz)
            AND NOT COALESCE({phase_closed("e")},false)
            ORDER BY e.scheduled_start,e.native_event_id LIMIT 4096
        ), proposals AS (
            SELECT e.*, accepted.canonical_game_id accepted, legacy.canonical_game_id legacy
            FROM upcoming e
            LEFT JOIN public.native_trading_sgo_game accepted ON accepted.sgo_event_id=e.native_event_id
            LEFT JOIN LATERAL (
                SELECT s.snapshot->>'canonical_game_id' canonical_game_id
                FROM public.market_pull_scope s JOIN public.market_pull p USING(pull_id)
                WHERE s.event_id=e.native_event_id AND left(s.snapshot->>'canonical_game_id',10)='canonical:'
                AND s.state IN ('complete','partial') AND p.state IN ('complete','partial')
                ORDER BY p.started_order,s.family LIMIT 1
            ) legacy ON accepted.sgo_event_id IS NULL
        )
        SELECT candidate.facts event, COALESCE(candidate.accepted,
            CASE WHEN count(*) OVER(PARTITION BY candidate.legacy)=1 AND owner.sgo_event_id IS NULL
            THEN candidate.legacy END, 'source:sportsgameodds:'||candidate.native_event_id) canonical_game_id,
            candidate.accepted IS NOT NULL registered
        FROM proposals candidate LEFT JOIN public.native_trading_sgo_game owner
        ON owner.canonical_game_id=candidate.legacy
        ORDER BY candidate.scheduled_start,candidate.native_event_id""",
        (at, at + HORIZON, at),
    ).fetchall()
    # Apply only the existing authoritative, role-scoped schedule review.
    from .sgo_schedule_review import canonical_roles

    witnesses = sgo_native_catalog.read(
        db,
        [
            row["event"]["id"]
            for row in rows
            if (row["event"].get("shared_provider_ids") or {}).get("novig_event")
            in novig_events
        ],
        include_markets=False,
    )

    for row in rows:
        event = dict(row["event"])
        _, _, event["home"], event["away"] = canonical_roles(
            event["id"],
            (
                event["competition"],
                stamp(event["scheduled_start"]),
                event["home"],
                event["away"],
            ),
            at=at,
        )
        row["event"] = event
        proof = pregame_subject_roles(event, witnesses.get(event["id"]), at=at)
        if proof:
            row["novig_subject_roles"] = proof
    return rows


def reference_inputs(eid, observations, at):
    return math.ReferenceInputs(
        {
            eid: [
                entry
                for entry in observations
                if entry["facts"].get("source_at")
                and at - REFERENCE_AGE
                <= stamp(entry["facts"]["source_at"])
                <= stamp(entry["facts"]["received_at"])
                <= at
            ]
        }
    )


def reference(record, game_link, observations, *, at):
    if game_link["status"] != "matched":
        return None, None, game_link["reason"]
    if not isinstance(observations, math.ReferenceInputs):
        observations = reference_inputs(game_link["sgo_event_id"], observations, at)
    try:
        result = math.reference(record, observations, at=at)
    except ValueError as exc:
        return None, None, str(exc)
    prices = result.get("required_input_prices") or result["prices"]
    expires = min(stamp(row["source_at"]) + REFERENCE_AGE for row in prices)
    return result, expires, None


def audit(record, book, observations):
    """Compare exact sides/lines while reporting observation skew separately."""
    from app.comparison.sgo_reference import american_probability
    from app.comparison.sgo_native_binding import outcome_link_id
    from app.collection.sgo_capabilities import DISPLAY_NAMES

    contract = expected(record)
    native_clock = clock(book)
    levels = book.get("levels") or []
    output = []
    for row in observations:
        q = row["facts"]
        line = q.get("line")
        venue = DISPLAY_NAMES.get(q.get("venue"), q.get("venue"))
        if (
            venue != book["venue"]
            or q.get("market") != contract["family"]
            or q.get("period") != "game"
            or q.get("side") != contract["selected_side"]
            or (None if line is None else F(line))
            != (None if contract["signed_line"] is None else F(contract["signed_line"]))
        ):
            continue
        counterpart = q.get("bookmaker_market_link")
        exact_outcome = outcome_link_id(counterpart) if venue == "novig" else None
        if exact_outcome and exact_outcome != book["outcome_id"]:
            continue
        source_at = q.get("source_at")
        from .store import exact_time

        skew = (
            None
            if not source_at or native_clock is None
            else native_clock - exact_time(source_at)
        )
        original = q.get("price_american")
        diff = (
            None
            if not levels or original is None
            else F(levels[0]["price"]) - F(american_probability(original))
        )
        output.append(
            dict(
                sgo_id=row["id"],
                sgo_revision=row["revision"],
                sgo_bookmaker=q.get("venue"),
                sgo_link=counterpart,
                instrument_match="exact_outcome_link"
                if exact_outcome
                else "selection_signature",
                sgo_price_american=original,
                native_price=None if not levels else levels[0]["price"],
                native_source_at=book.get("source_at"),
                native_observation_clock=None
                if native_clock is None
                else str(native_clock),
                native_received_at=book.get("received_at"),
                sgo_source_at=source_at,
                sgo_received_at=q.get("received_at"),
                time_skew_seconds=None if skew is None else str(skew),
                price_difference=wire(diff) if diff is not None else None,
                comparison="venue_equivalence_unverified"
                if q.get("venue") == "polymarket"
                else "clock_unavailable"
                if skew is None
                else "comparable_window"
                if abs(skew) <= 30
                else "time_skew",
            )
        )
    return output


def settlement_key(book):
    """Group only verified equivalent score and exceptional payoff rules."""
    contract = book["contract"]
    rules = contract["settlement"]
    if not rules.get("available"):
        return book["venue"], rules.get("rule_id") or book["market_id"]
    family = contract["family"]
    league = contract["league"]
    equality = rules.get("equality")
    if family != "moneyline" and F(contract["signed_line"]).denominator == 2:
        if equality in ("not_feasible", "not_possible", "predicate"):
            equality = "unreachable"
    elif (
        family == "moneyline"
        and league != "NFL"
        and equality
        in ("not_feasible", "not_possible", "half_face", "void_without_official_winner")
    ):
        equality = "unreachable"
    # Unreviewed exceptional terms retain venue ownership. Evidence URLs and
    # IDs can change without changing a fully qualified settlement.
    exceptions = tuple(
        rules.get(key) for key in ("shortened_game", "forfeit", "void", "void_payout")
    )
    if not all(exceptions[:3]):
        exceptions = (book["venue"], rules.get("rule_id"))
    return dict(
        equality=equality,
        equality_cashflow=None
        if equality == "unreachable"
        else rules.get("equality_cashflow"),
        overtime=rules.get("overtime"),
        extra_innings=rules.get("extra_innings") if league == "MLB" else None,
        shootout=rules.get("shootout") if league == "NHL" else None,
        shootout_count=rules.get("shootout_count")
        if league == "NHL" and family != "moneyline"
        else None,
        normal_win=wire(F(rules.get("normal_win", "1"))),
        normal_loss=wire(F(rules.get("normal_loss", "0"))),
        exceptions=exceptions,
    )


def projection(
    record,
    book,
    game_link,
    ref,
    reference_until,
    reference_reason,
    *,
    at,
    stake="100",
    fee_mode=None,
):
    """Reuse the exact native sizing/fee model even without a fair reference."""
    result = evaluate_at_stake(
        book,
        at=at,
        stake=stake,
        probability=(ref or {}).get("probability"),
        minimum="0",
        expected=expected(record),
        fees_enabled=True if fee_mode is None else fee_mode["enabled"],
    )
    if fee_mode is not None:
        result["fee_mode"] = fee_mode
    result.update(
        _present(result),
        valid_until=book.get("valid_until"),
        published_at=at.isoformat(),
        reference_valid_until=None
        if reference_until is None
        else reference_until.isoformat(),
    )
    if ref is None:
        result["modeled_net_ev"] = None
        result["reference_reason"] = reference_reason
    levels = book.get("levels") or []
    price = F(levels[0]["price"]) if levels else None
    ev = result.get("modeled_net_ev") if result.get("status") != "unknown" else None
    contract = expected(record)
    event = record["event"]
    native = record["quote"]["source"]
    identity = dict(
        game=game_link["canonical_game_id"],
        family=contract["family"],
        period=contract["period"],
        side=contract["selected_side"],
        line=contract["signed_line"],
        settlement=settlement_key(book),
    )
    # Venue-specific rule IDs remain separate until equivalent semantics are
    # established. Never merge two unknown settlements on labels alone.
    bet_id = hashed(identity)
    selection = record["selection"]
    label = next(
        (
            name
            for name, cid in event["participants"].items()
            if cid == selection.get("participant")
        ),
        contract["selected_side"].title(),
    )
    row = dict(
        id=contract_id(record),
        venue=book["venue"],
        game=event["title"],
        league=event["competition"],
        kickoff=event["scheduled_start"],
        family=contract["family"],
        period=contract["period"],
        bet_id=bet_id,
        selection_label=label,
        line=contract["signed_line"],
        side=contract["selected_side"],
        line_role="unknown"
        if record["comparison_source_metadata"].get("alternate") is None
        else "alternate"
        if record["comparison_source_metadata"]["alternate"]
        else "main",
        posted=dict(
            value=wire(price * F(book.get("payout_usd", "1")))
            if price is not None
            else None,
            units="usd_per_contract",
            payout_usd=book.get("payout_usd"),
            native_price_probability=None if price is None else wire(price),
        ),
        times=dict(
            source_at=book.get("source_at"),
            received_at=book.get("received_at"),
            calculated_at=at.isoformat(),
        ),
        display=dict(
            posted_odds=None if price is None else american(1 / price),
            fair_odds=(ref or {}).get("fair_odds"),
            net_ev=None if ev is None else decimal_display(F(ev) * 100) + "%",
        ),
        calculation=dict(
            status="unavailable"
            if ev is None
            else "positive"
            if F(ev) > 0
            else "negative"
            if F(ev) < 0
            else "zero",
            net_ev_ratio=ev,
            net_ev_percent=None if ev is None else wire(F(ev) * 100),
        ),
        eligible_until=book.get("valid_until"),
        liquidity=result,
        native_source=native,
        canonical_game_id=game_link["canonical_game_id"],
        other_quotes=[],
    )
    return dict(
        version=VERSION,
        row=row,
        record=record,
        book=book,
        reference=ref,
        reference_reason=reference_reason,
        game_link=game_link,
        calculated_at=at.isoformat(),
        fee_mode=fee_mode,
    )


def publish(db, observations, *, at, prune=False):
    """One ordered current observation per exact native selection across restarts."""
    at = stamp(at)
    from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage
    from app.collection.sgo_capabilities import CURRENT_BOOKS
    from app.research.experiment import next_late_storage_reservation, sql_runway_bytes
    from app.research.records import LOCK as STORAGE_ADMISSION_LOCK
    from .sportsgameodds_reference import HISTORY_RUNWAY

    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(%s)", (PUBLICATION_LOCK,))
        if not db.execute(
            "SELECT pg_try_advisory_xact_lock(%s) acquired", (STORAGE_ADMISSION_LOCK,)
        ).fetchone()["acquired"]:
            return dict(
                state="deferred", reason="native_storage_admission_busy", published=0
            )
        if prune:
            db.execute(
                "DELETE FROM public.native_trading_offer WHERE starts_at<=%s",
                (at - PAST_OFFER_AGE,),
            )
            db.execute(
                """DELETE FROM public.native_trading_snapshot s
                WHERE created_at<=%s AND NOT EXISTS (SELECT 1 FROM public.native_trading_offer o
                    WHERE o.snapshot_id=s.id)""",
                (at - SUPERSEDED_EVIDENCE_AGE,),
            )
        if not observations:
            return dict(state="ready", published=0)
        # A checkpoint can enter its window after the collector's last
        # priority check. Leave room for its full reservation, including
        # any late-claim top-up, when optional native snapshots are admitted.
        protected = max(HISTORY_RUNWAY, sql_runway_bytes(next_late_storage_reservation(db, at=at)))
        runway = max(0, (SQL_BYTE_CAP - protected - sql_usage(db)) // 2)
        if runway < MAX_SNAPSHOT_BYTES:
            return dict(state="deferred", reason="native_storage_capacity", published=0)
        retained = db.execute(
            "SELECT COALESCE(sum(payload_bytes),0) n FROM public.native_trading_snapshot"
        ).fetchone()["n"]
        if SNAPSHOT_BUDGET - retained < len(observations) * MAX_SNAPSHOT_BYTES:
            expired = db.execute(
                """WITH evict AS (
                SELECT s.id FROM public.native_trading_snapshot s WHERE s.created_at<=%s
                AND NOT EXISTS (SELECT 1 FROM public.native_trading_offer o WHERE o.snapshot_id=s.id)
                ORDER BY s.created_at,s.id LIMIT 1024)
                DELETE FROM public.native_trading_snapshot s USING evict WHERE s.id=evict.id
                RETURNING s.payload_bytes""",
                (at - SUPERSEDED_PRESSURE_AGE,),
            ).fetchall()
            retained -= sum(row["payload_bytes"] for row in expired)
        available = min(runway, SNAPSHOT_BUDGET - retained)
        if available <= 0:
            return dict(
                state="deferred", reason="native_snapshot_capacity", published=0
            )
        novig_events = {
            item["event_id"]
            for item in observations.values()
            if item.get("venue") == "novig" and item.get("event_id")
        }
        games = anchors(db, at, novig_events=novig_events)
        from app.comparison.fee_mode import read as read_fee_mode

        mode = read_fee_mode(db)
        cached = {}
        registered = {game["event"]["id"] for game in games if game["registered"]}
        count = 0
        refs = {}
        for incoming in observations.values():
            record = incoming.get("_record")
            if not record or not incoming.get("contract"):
                continue
            cid = contract_id(record)
            prior = db.execute(
                "SELECT * FROM public.native_trading_offer WHERE id=%s FOR UPDATE",
                (cid,),
            ).fetchone()
            receipt = {
                key: value for key, value in incoming.items() if not key.startswith("_")
            }
            if not receipt.get("received_at") or not receipt.get("valid_until"):
                proofs = [
                    proof.get("received_at") or proof.get("observed_at")
                    for proof in receipt.get("identity_receipts", ())
                ]
                clocks = [stamp(value) for value in proofs if value]
                receipt = dict(
                    receipt,
                    received_at=(max(clocks) if clocks else at).isoformat(),
                    valid_until=at.isoformat(),
                    reason=receipt.get("reason") or "book_unobserved",
                )
            elif not receipt.get("reason") and stamp(receipt["valid_until"]) <= stamp(
                receipt["received_at"]
            ):
                receipt = dict(receipt, reason="native_identity_expired")
            if prior:
                reported = receipt
                receipt = adopt(prior["book"], receipt)
                if receipt is prior["book"]:
                    # Only the admitted receipt can be revalued against
                    # changed reference odds. A stale retry is read-only.
                    if revision(reported) != revision(receipt) or stamp(
                        reported["received_at"]
                    ) < stamp(receipt["received_at"]):
                        refs[cid] = prior["reference_valid_until"]
                        continue
                    record = prior["record"]
            game_link = link(
                record["event"], games, prior=prior["game_link"] if prior else None
            )
            eid = game_link.get("sgo_event_id")
            if eid not in cached:
                rows = (
                    read_event(db, eid, bookmakers=CURRENT_BOOKS.union(math.BEST_BOOKS))
                    if eid
                    else []
                )
                cached[eid] = reference_inputs(eid, rows, at), rows
            indexed, rows = cached[eid]
            ref, reference_until, reason = reference(record, game_link, indexed, at=at)
            payload = projection(
                record,
                receipt,
                game_link,
                ref,
                reference_until,
                reason,
                at=at,
                fee_mode=mode,
            )
            payload["sgo_comparison"] = audit(record, receipt, rows)
            snapshot = hashed(
                [
                    revision(receipt),
                    receipt["received_at"],
                    receipt["valid_until"],
                    record,
                    game_link,
                    ref,
                    reason,
                    payload["sgo_comparison"],
                    mode,
                ]
            )
            if prior and prior["snapshot_id"] == snapshot:
                refs[cid] = reference_until
                continue
            payload["row"].update(
                revision=snapshot,
                pull_id="native:" + snapshot,
                market_id=game_link["canonical_game_id"]
                + "|"
                + receipt["contract"]["family"]
                + "|full_game",
            )
            size = len(encoded(payload))
            if size > MAX_SNAPSHOT_BYTES:
                continue
            if size > available:
                return dict(
                    state="deferred",
                    reason="native_snapshot_capacity",
                    published=count,
                    references=refs,
                )
            if game_link["status"] == "matched" and eid not in registered:
                db.execute(
                    """INSERT INTO public.native_trading_sgo_game(sgo_event_id,canonical_game_id)
                    VALUES (%s,%s) ON CONFLICT (sgo_event_id) DO NOTHING""",
                    (eid, game_link["canonical_game_id"]),
                )
                registered.add(eid)
            changed = db.execute(
                """INSERT INTO public.native_trading_snapshot(id,offer_id,created_at,payload_bytes,payload)
                VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (snapshot, cid, at, size, Jsonb(payload)),
            ).rowcount
            available -= size * changed
            source = record["quote"]["source"]
            value = payload["row"]
            ev = value["calculation"]["net_ev_ratio"]
            db.execute(
                """INSERT INTO public.native_trading_offer AS old
                (id,venue,native_event_id,native_market_id,native_outcome_id,canonical_game_id,league,family,line_role,
                 starts_at,discovered_at,published_at,snapshot_id,book,record,game_link,book_valid_until,
                 reference_valid_until,net_ev,active)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id) DO UPDATE SET canonical_game_id=excluded.canonical_game_id,
                 starts_at=excluded.starts_at,published_at=excluded.published_at,snapshot_id=excluded.snapshot_id,
                 book=excluded.book,record=excluded.record,game_link=excluded.game_link,
                 book_valid_until=excluded.book_valid_until,reference_valid_until=excluded.reference_valid_until,
                 net_ev=excluded.net_ev,active=excluded.active,line_role=excluded.line_role""",
                (
                    cid,
                    receipt["venue"],
                    source["native_event_id"],
                    source["native_market_id"],
                    source["native_outcome_id"],
                    game_link["canonical_game_id"],
                    event_league(record),
                    value["family"],
                    value["line_role"],
                    value["kickoff"],
                    at,
                    at,
                    snapshot,
                    Jsonb(receipt),
                    Jsonb(record),
                    Jsonb(game_link),
                    stamp(receipt["valid_until"]),
                    reference_until,
                    None
                    if ev is None
                    else Decimal(F(ev).numerator) / Decimal(F(ev).denominator),
                    receipt.get("reason") not in WITHDRAWALS,
                ),
            )
            count += 1
            refs[cid] = reference_until
            if receipt["venue"] == "novig":
                notice = dict(sport=event_league(record), family=value["family"], revision=snapshot)
                db.execute(
                    "SELECT pg_notify(%s,%s)",
                    (DASHBOARD_UPDATES_CHANNEL, encoded(notice).decode()),
                )
        return dict(state="ready", published=count, references=refs)


def event_league(record):
    return record["event"]["competition"]


def dashboard(
    db,
    *,
    at,
    until,
    offset=0,
    limit=30,
    sport=None,
    family=None,
    venue=None,
    view=None,
    **_,
):
    """Passive reads over the same 24-hour native inventory; no provider I/O."""
    from app.comparison.fee_mode import read as read_fee_mode

    mode = read_fee_mode(db)
    rows = db.execute(
        """SELECT o.reference_valid_until,o.book_valid_until,o.active,
        CASE WHEN o.active AND (%(show_all)s OR o.book_valid_until>%(at)s)
            THEN s.payload->'row' END dashboard_row,
        CASE WHEN o.active AND o.book_valid_until>%(at)s THEN s.payload->'fee_mode' END fee_mode,
        CASE WHEN %(show_all)s AND COALESCE(o.book_valid_until<=%(at)s,true)
            THEN o.book->>'reason' END book_reason,
        CASE WHEN %(show_all)s AND COALESCE(o.book_valid_until<=%(at)s,true)
            THEN o.book->'levels' NOT IN ('[]'::jsonb,'null'::jsonb)
                OR o.book->'complete'='true'::jsonb END book_observed,
        CASE WHEN o.active AND o.book_valid_until>%(at)s AND o.reference_valid_until IS NOT NULL THEN
        """
        + _reference_current("o.game_link")
        + """ ELSE true END reference_current,
        """
        + _game_closed("o.game_link", "%(at)s")
        + """ game_closed
        FROM public.native_trading_offer o JOIN public.native_trading_snapshot s ON s.id=o.snapshot_id
        """
        + _source_event("o.game_link")
        + """
        WHERE o.starts_at>%(at)s AND o.starts_at<=%(until)s
          AND (%(sport)s::text IS NULL OR o.league=%(sport)s)
          AND (%(family)s::text IS NULL OR o.family=%(family)s)
          AND (%(venue)s::text IS NULL OR o.venue=%(venue)s)""",
        dict(
            at=at,
            until=min(until, at + HORIZON),
            show_all=view == "all",
            sport=sport or None,
            family=family or None,
            venue=venue or None,
        ),
    ).fetchall()
    grouped = {}
    current = []
    for found in rows:
        if found["dashboard_row"] is None or found["game_closed"]:
            continue
        row = found["dashboard_row"]
        if not found["book_valid_until"] or found["book_valid_until"] <= at:
            row["book_status"] = "stale" if found["book_observed"] else "unobserved"
            row["posted"] = dict(
                row["posted"], value=None, native_price_probability=None
            )
            row["display"]["posted_odds"] = None
            row["liquidity"] = unknown(found["book_reason"] or "stale_book")
        else:
            row["book_status"] = "fresh"
        invalid = _current_reference(found, at)
        if row["book_status"] != "fresh" or invalid or found["fee_mode"] != mode:
            row["display"].update(fair_odds=None, net_ev=None)
            row["calculation"].update(
                status="unavailable", net_ev_ratio=None, net_ev_percent=None
            )
            row["liquidity"].update(
                modeled_net_ev=None,
                eligible=False,
                supported_eligible=False,
                reason=row["liquidity"].get("reason")
                if row["book_status"] != "fresh"
                else invalid or "fee_mode_changed",
            )
        current.append(row)
    price_available = any(row["display"]["posted_odds"] is not None for row in current)
    expired = any(
        row["active"] and row["book_valid_until"] and row["book_valid_until"] <= at
        for row in rows
    )
    inputs_unavailable = any(
        row["calculation"]["status"] == "unavailable" for row in current
    )
    current = [
        row
        for row in current
        if view == "all"
        or (
            row["calculation"]["net_ev_ratio"] is None
            if view == "unavailable"
            else row["calculation"]["net_ev_ratio"] is not None
            and F(row["calculation"]["net_ev_ratio"]) > 0
        )
    ]
    current.sort(
        key=lambda r: (
            r["book_status"] != "fresh",
            r["calculation"]["net_ev_ratio"] is None,
            -F(r["calculation"]["net_ev_ratio"] or 0),
            r["kickoff"],
            r["id"],
        )
    )
    for row in current:
        if row["bet_id"] in grouped:
            grouped[row["bet_id"]]["other_quotes"].append(row)
        else:
            grouped[row["bet_id"]] = row
    values = list(grouped.values())
    return dict(
        rows=values[offset : offset + limit],
        total=len(values),
        offset=offset,
        stored_offers=len(rows),
        source_authority="official_venue_apis",
        availability=dict(
            price_available=price_available,
            inputs_unavailable=inputs_unavailable,
            pull_incomplete=False,
            expired_positive=expired,
        ),
    )


def _same_preview_instrument(saved, latest):
    old_book, new_book = saved["book"], latest["book"]
    fields = (
        "venue",
        "event_id",
        "market_id",
        "outcome_id",
        "opposite_outcome_id",
        "native_side",
    )
    return (
        saved["row"]["market_id"] == latest["row"]["market_id"]
        and expected(saved["record"]) == expected(latest["record"])
        and all(old_book.get(field) == new_book.get(field) for field in fields)
        and old_book["contract"].get("settlement")
        == new_book["contract"].get("settlement")
    )


def detail(db, query, *, at, stake="100", frozen=False):
    from app.dashboard.local_security import PublicRequestError
    from app.comparison.fee_mode import read as read_fee_mode

    snapshot = query["pull_id"].removeprefix("native:")
    columns = (
        "SELECT s.payload, s.created_at published_at, "
        + REFERENCE_CURRENT
        + " reference_current, "
        + GAME_CLOSED
        + " game_closed, "
        "source_event.scheduled_start IS NOT NULL AND source_event.scheduled_start::timestamptz "
        "IS DISTINCT FROM (s.payload#>>'{game_link,sgo_start}')::timestamptz schedule_changed, "
        "s.payload#>>'{row,liquidity,reference_valid_until}' reference_valid_until, "
        "COALESCE(o.active AND o.book=s.payload->'book', false) book_current "
    )
    join = " FROM public.native_trading_snapshot s LEFT JOIN public.native_trading_offer o ON o.id=s.offer_id "
    lookup = " WHERE s.id=%s AND s.offer_id=%s"
    keys = snapshot, query.get("offer_id")
    if frozen:
        row = db.execute(
            "SELECT s.payload FROM public.native_trading_snapshot s" + lookup, keys
        ).fetchone()
    else:
        row = db.execute(columns + join + SOURCE_EVENT + lookup, (at, *keys)).fetchone()
    if (
        not row
        or query.get("revision") != snapshot
        or row["payload"]["row"]["market_id"] != query["market_id"]
    ):
        raise PublicRequestError("Exact native offer revision unavailable.")
    payload = row["payload"]
    output = dict(
        native_offer=payload,
        liquidity_evidence=payload["book"],
        selected_offer=dict(
            normalized_record=payload["record"],
            calculation=payload["row"]["calculation"],
        ),
    )
    if frozen:
        return dict(output, liquidity=payload["row"]["liquidity"])
    preview_requested = "amount" in query
    if preview_requested:
        row = db.execute(
            columns + join + SOURCE_EVENT + " WHERE o.snapshot_id=s.id AND o.id=%s",
            (at, query["offer_id"]),
        ).fetchone()
        # A normal refresh can replace the receipt while the owner types an
        # amount. Keep the saved export fixed and price on the current image
        # only if its exact instrument and settlement are unchanged.
        if not row or not _same_preview_instrument(payload, row["payload"]):
            change = (
                "native_identity_changed" if row else "native_observation_superseded"
            )
            return dict(
                output, liquidity=unknown(change, stake=stake), liquidity_evidence=None
            )
        output["liquidity_evidence"] = row["payload"]["book"]
    value = row["payload"]
    book = value["book"]
    if row["game_closed"] or stamp(book["contract"]["starts_at"]) <= at:
        return dict(output, liquidity=unknown("native_game_started", stake=stake))
    if row["schedule_changed"]:
        return dict(output, liquidity=unknown("native_schedule_changed", stake=stake))
    if not row["book_current"] or stamp(book["valid_until"]) <= at:
        book_reason = (
            "native_observation_superseded" if not row["book_current"] else "stale_book"
        )
        return dict(
            output, liquidity=unknown(book.get("reason") or book_reason, stake=stake)
        )

    invalid = _current_reference(row, at)
    ref = None if invalid else value["reference"]
    reason = invalid or value.get("reference_reason")
    mode = read_fee_mode(db)
    if preview_requested:
        until = row["reference_valid_until"]
        updated = projection(
            value["record"],
            book,
            value["game_link"],
            ref,
            stamp(until) if until else None,
            reason,
            at=at,
            stake=stake,
            fee_mode=mode,
        )["row"]
        output["preview_offer"] = dict(
            revision=value["row"]["revision"],
            venue=updated["venue"],
            native_source=updated["native_source"],
            posted=updated["posted"],
            display=updated["display"],
        )
        preview = dict(updated["liquidity"], published_at=row["published_at"].isoformat())
    else:
        preview = deepcopy(payload["row"]["liquidity"])
        if ref is None or payload.get("fee_mode") != mode:
            preview.update(
                modeled_net_ev=None,
                eligible=False,
                supported_eligible=False,
                reason=reason or "fee_mode_changed",
            )
    return dict(output, liquidity=preview)


def coverage(db, *, at, sport=None, family=None, venue=None):
    from app.comparison.fee_mode import read as read_fee_mode

    mode = read_fee_mode(db)
    rows = db.execute(
        """SELECT o.venue,o.league,o.family,o.line_role,o.native_event_id,o.native_market_id,
        o.starts_at,o.active,o.book_valid_until,o.reference_valid_until,
        o.game_link->>'status' match_status,o.game_link->>'reason' match_reason,
        o.book->>'reason' book_reason,
        s.payload->>'reference_reason' reference_reason,
        CASE WHEN o.active AND o.book_valid_until>%(at)s
             THEN s.payload#>'{row,liquidity}' ELSE '{}'::jsonb END liquidity,
        CASE WHEN o.active AND o.book_valid_until>%(at)s THEN s.payload->'fee_mode' END fee_mode,
        CASE WHEN o.reference_valid_until IS NOT NULL THEN
        """
        + _reference_current("o.game_link")
        + """ ELSE true END reference_current,
        """
        + _game_closed("o.game_link", "%(at)s")
        + """ game_closed
        FROM public.native_trading_offer o JOIN public.native_trading_snapshot s ON s.id=o.snapshot_id
        """
        + _source_event("o.game_link")
        + """
        WHERE o.starts_at>%(at)s AND o.starts_at<=%(until)s
        AND (%(sport)s::text IS NULL OR o.league=%(sport)s)
        AND (%(family)s::text IS NULL OR o.family=%(family)s)
        AND (%(venue)s::text IS NULL OR o.venue=%(venue)s)""",
        dict(at=at, until=at + HORIZON, sport=sport, family=family, venue=venue),
    ).fetchall()
    groups = {}
    for row in rows:
        key = row["venue"], row["league"], row["family"], row["line_role"]
        (
            group,
            priority_group,
            reasons,
            priority_reasons,
            books,
            fresh_books,
            priority_books,
        ) = groups.setdefault(
            key, (Counter(), Counter(), Counter(), Counter(), set(), set(), set())
        )
        priority = row["starts_at"] <= at + PRIORITY_WINDOW
        book_key = row["native_event_id"], row["native_market_id"]
        books.add(book_key)
        value = row["liquidity"]
        fresh = bool(
            row["active"]
            and not row["game_closed"]
            and row["book_valid_until"]
            and row["book_valid_until"] > at
        )
        if fresh:
            fresh_books.add(book_key)
            if priority:
                priority_books.add(book_key)
        reference_gap = _current_reference(row, at)
        usable = bool(
            not row["game_closed"]
            and row["reference_valid_until"]
            and not reference_gap
        )
        size = value.get("size_status")
        counts = dict(
            offers=1,
            exact_matches=int(row["match_status"] == "matched"),
            fresh_books=int(fresh),
            usable_references=int(usable),
            fresh_books_with_usable_reference=int(fresh and usable),
            assessable=int(fresh and size != "unknown"),
            full_size=int(fresh and size == "full_size"),
            ev_assessable=int(
                fresh
                and usable
                and row["fee_mode"] == mode
                and value.get("modeled_net_ev") is not None
            ),
        )
        group.update(counts)
        if priority:
            priority_group.update(counts)
        else:
            priority_group.update(dict.fromkeys(counts, 0))
        states = set()
        if row["match_status"] != "matched":
            states.add(row["match_reason"] or "unmatched")
        elif not row["game_closed"] and not usable:
            states.add(
                reference_gap or row["reference_reason"] or "reference_unavailable"
            )
        if row["game_closed"]:
            states.add("game_no_longer_pregame")
        elif not row["active"]:
            states.add(row["book_reason"] or "withdrawn")
        elif not fresh:
            states.add(row["book_reason"] or "stale_book")
        else:
            if size in ("confirmed_empty", "below_floor"):
                states.add(size)
            if value.get("reason"):
                states.add(value["reason"])
        reasons.update(states)
        if priority:
            priority_reasons.update(states)
    output = []
    for (venue, league, family, role), values in sorted(groups.items()):
        (
            group,
            priority,
            reasons,
            priority_reasons,
            books,
            fresh_books,
            priority_books,
        ) = values
        output.append(
            dict(
                venue=venue,
                league=league,
                family=family,
                line_role=role,
                main=role == "main",
                opportunities=group["offers"],
                unique_books=len(books),
                unique_fresh_books=len(fresh_books),
                priority_unique_fresh_books=len(priority_books),
                reasons=dict(reasons),
                priority_reasons=dict(priority_reasons),
                **{f"priority_{key}": number for key, number in priority.items()},
                **group,
            )
        )
    return dict(
        coverage=output,
        total=len(rows),
        provider_requests=0,
        scheduled_calculations=0,
        read_at=at.isoformat(),
        liquidity_stake_usd="100",
        source_authority="official_venue_apis",
    )
