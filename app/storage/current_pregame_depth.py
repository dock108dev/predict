"""Collector-owned current depth and passive Dashboard size calculations."""

from collections import Counter
from fractions import Fraction

from psycopg.types.json import Jsonb

from app.comparison import current_pregame as math, execution_contract
from .database_roles import COHORTS
from .store import encoded, hashed, stamp


MAX_RECEIPT_BYTES = 512 * 1024
BOARD_STAKE = str(math.COMPARISON_USD)
PRESENT_FIELDS = (
    "fee_is_upper_bound", "fee_lower_bound_usd", "limit_price", "price_limit_policy", "requested_stake_usd",
    "intended_stake_usd", "available_purchase_usd", "available_native_quantity",
    "availability_is_lower_bound", "modeled_purchase_usd", "modeled_stake_usd",
    "modeled_win_profit_usd", "modeled_loss_usd", "modeled_average_price",
    "modeled_fee_usd", "modeled_net_ev", "status", "size_status", "reason", "eligible",
    "supported_eligible", "as_of", "book_received_at", "book_source_at", "receipt_id", "source_health",
)


def unknown(reason, *, stake=BOARD_STAKE):
    return dict(status="unknown", size_status="unknown", reason=reason, eligible=False,
                supported_eligible=False, intended_stake_usd=str(stake))


def _clocks(receipt, known):
    for field in ("receipts", "identity_receipts"):
        for proof in receipt.get(field, ()):
            observed_at = proof.get("received_at") or proof.get("observed_at")
            if not observed_at:
                raise ValueError("dashboard_depth_receipt_clock_unverified")
            received = stamp(observed_at)
            if received > known or (proof.get("requested_at") and stamp(proof["requested_at"]) > received):
                raise ValueError("dashboard_depth_receipt_clock_unverified")


def _value(payload, record, receipt, *, at, stake):
    from app.comparison.experiment_depth_execution import evaluate_at_stake

    reference = payload.get("reference") or {}
    probability = reference.get('probability')
    from datetime import timedelta
    for quote in reference.get('required_input_prices') or reference.get('prices') or ():
        if (not quote.get('source_at') or not quote.get('received_at') or
                not stamp(quote['source_at']) <= stamp(quote['received_at']) <= at <
                stamp(quote['source_at'])+timedelta(seconds=900)):
            probability = None
            break
    return evaluate_at_stake(receipt, at=at, stake=stake, probability=probability,
                             minimum="0", expected=execution_contract.expected(record))


def _present(result):
    return {key: result[key] for key in PRESENT_FIELDS if key in result}


def _projection(payload, record, receipt, *, at):
    from .current_pregame import numeric

    result = _value(payload, record, receipt, at=at, stake=BOARD_STAKE)
    valuation = {"result": _present(result)}
    if result.get('size_status') == 'full_size' and result.get('modeled_net_ev') is not None:
        valuation['effective_ev'] = format(numeric(result['modeled_net_ev']), 'f')
    if not result.get("eligible"):
        return valuation
    states = result["modeled_cashflows"]
    valuation["rank_payload"] = dict(reference=payload["reference"],
        raw=dict(net_ev=result["modeled_net_ev"], opportunity_score=result["modeled_score"]),
        fee=dict(committed_usd=result["modeled_stake_usd"], cashflows=states))
    valuation["effective_ev"] = format(numeric(result["modeled_net_ev"]), "f")
    return valuation


def _dashboard_inputs(db, event_ids, contract_ids):
    """Match the home Dashboard's latest complete acquisition and exact quote."""
    query = """WITH latest AS MATERIALIZED (
        SELECT DISTINCT ON (s.event_id,s.family,s.period) s.pull_id,s.state,s.snapshot
        FROM public.market_pull_scope s JOIN public.market_pull p USING(pull_id)
        WHERE s.event_id=ANY(%s) AND s.coverage->>'covers_board'='true' AND s.period='full_game'
        ORDER BY s.event_id,s.family,s.period,p.started_order DESC
    ) SELECT v#>>'{calculation_payload,id}' AS contract_id,
      'dashboard:'||s.pull_id||':'||(v#>>'{display_offer,revision}') AS key,
      v->'calculation_payload' AS payload
    FROM latest s CROSS JOIN LATERAL jsonb_array_elements(COALESCE(s.snapshot->'offers','[]'::jsonb)) v
    WHERE s.state='complete' AND v#>>'{calculation_payload,id}'=ANY(%s)
      AND v#>>'{calculation_payload,acquisition,pull_id}'=s.pull_id
      AND v#>>'{calculation_payload,acquisition,eligible}'='true'
      AND v#>>'{calculation_payload,reference,probability}' IS NOT NULL
      AND v#>>'{display_offer,revision}' IS NOT NULL AND v->>'reason' IS NULL"""
    return db.execute(query, (list(event_ids), list(contract_ids)))


def publish(db, items, *, at):
    """Replace current observations only for the same active contract revision."""
    # One transaction serializes concurrent readers and makes ordering survive
    # restarts. Revaluation may change without receiving another native book.
    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(901127)')
        return _publish(db, items, at=at)


def _publish(db, items, *, at):
    from app.comparison.native_observation import adopt

    at = stamp(at)
    items = list(items)
    if not items:
        return 0
    contracts = {item["contract_id"] for item in items}
    rows = db.execute("""SELECT c.id,c.revision,e.native_event_id,p.record,p.payload AS price
        FROM public.current_contract_storage c
        JOIN public.current_event e ON e.id=c.event_id
        JOIN public.current_pregame_price p ON p.contract_id=c.id
        WHERE c.active AND c.id=ANY(%s) AND p.start_at>%s""", (list(contracts), at)).fetchall()
    exact = {row["id"]:row for row in rows}
    previous = {row['contract_id']: row for row in db.execute(
        'SELECT * FROM public.current_pregame_depth WHERE contract_id=ANY(%s) FOR UPDATE',
        (list(contracts),))}
    valuation_inputs = {}
    selection = "SELECT contract_id,input_revision,payload FROM {}.current_pregame_calculation WHERE contract_id=ANY(%s) AND reason IS NULL AND valid_until>%s"
    for schema in ("public", *COHORTS):
        for row in db.execute(selection.format(schema), (list(contracts), at)):
            valuation_inputs.setdefault(row["contract_id"], {})[row["input_revision"]] = row["payload"]
    for row in _dashboard_inputs(db, {row['native_event_id'] for row in rows}, exact):
        valuation_inputs.setdefault(row['contract_id'], {})[row['key']] = row['payload']
    output = []
    for item in items:
        cid = item["contract_id"]
        row = exact.get(cid)
        if not row or row["revision"] != item["contract_revision"]:
            continue
        receipt = item["receipt"]
        if not isinstance(receipt, dict) or len(encoded(receipt)) > MAX_RECEIPT_BYTES:
            continue
        if receipt.get("venue") != row["price"]["venue"] or receipt.get("contract_id") not in (None, cid):
            continue
        known, expires = (stamp(item[field]) for field in ("known_at", "valid_until"))
        prior = previous.get(cid)
        if prior and prior['contract_revision'] == row['revision']:
            selected = adopt(prior['receipt'], receipt)
            if selected is prior['receipt']:
                receipt, known, expires = selected, prior['known_at'], prior['valid_until']
        expires = min(expires, stamp(row["price"]["kickoff"]))
        if not known <= at < expires:
            continue
        observed_at = receipt.get("received_at")
        if observed_at and stamp(observed_at) > known:
            continue
        _clocks(receipt, known)
        receipt_id = receipt.get('receipt_id') or hashed(receipt)
        receipt = dict(receipt, receipt_id=receipt_id, contract_id=cid)
        current = valuation_inputs.get(cid, {})
        valuations = {key:_projection(payload, row["record"], receipt, at=at)
                      for key, payload in current.items()}
        # A missing probability witness still permits inspection of depth.
        if row["price"]["input_revision"] not in valuations:
            valuations[row["price"]["input_revision"]] = {
                "result": _present(_value(row["price"], row["record"], receipt, at=at, stake=BOARD_STAKE))
            }
        output.append((cid, row["revision"], receipt_id, known, expires, at, Jsonb(receipt), Jsonb(valuations)))
        previous[cid] = dict(contract_id=cid, contract_revision=row['revision'], receipt=receipt,
                             known_at=known, valid_until=expires)
    if not output:
        return 0
    with db.cursor() as cursor:
        cursor.executemany("""INSERT INTO public.current_pregame_depth AS existing
            (contract_id,contract_revision,receipt_id,known_at,valid_until,published_at,receipt,valuations)
            SELECT %s,%s,%s,%s,%s,%s,%s,%s
            WHERE EXISTS (SELECT 1 FROM public.current_contract_storage c
                WHERE c.id=%s AND c.revision=%s AND c.active)
            ON CONFLICT(contract_id) DO UPDATE SET contract_revision=excluded.contract_revision,
                receipt_id=excluded.receipt_id,known_at=excluded.known_at,valid_until=excluded.valid_until,
                published_at=excluded.published_at,receipt=excluded.receipt,valuations=excluded.valuations
            WHERE existing.known_at<=excluded.known_at AND
              (existing.contract_revision,existing.receipt_id,existing.valid_until,existing.valuations)
              IS DISTINCT FROM
              (excluded.contract_revision,excluded.receipt_id,excluded.valid_until,excluded.valuations)
            """, [entry + entry[:2] for entry in output])
        return cursor.rowcount


def preview(db, payload, record, *, at, stake, evidence=False):
    """Revalue a requested size from the retained current book, without acquisition."""
    found = db.execute("""SELECT d.receipt,d.published_at,d.valid_until
        FROM public.current_pregame_depth d JOIN current_contract c ON c.id=d.contract_id
        JOIN public.current_offer o ON o.contract_id=c.id
        WHERE d.contract_id=%s AND d.contract_revision=c.revision AND d.published_at<=%s
          AND o.facts->>'state'='available'""",
        (payload["id"], at)).fetchone()
    if not found or found["valid_until"] <= at:
        result = unknown("stale_book" if found else "book_unobserved", stake=stake)
        return (result, None) if evidence else result
    result = _value(payload, record, found["receipt"], at=at, stake=stake)
    summary = dict(_present(result), modeled_fills=result.get("modeled_fills"),
                   published_at=found["published_at"].isoformat(), valid_until=found["valid_until"].isoformat())
    return (summary, found['receipt']) if evidence else summary


def coverage(db, *, at, sport=None, family=None, venue=None):
    """Count the current price catalog without materializing the ranked board."""
    from app.comparison.cashflows import exact_wire
    from app.comparison.snapshot_fee_outcome import VENUES

    sql = """WITH clock AS (SELECT %s::timestamptz AS at), base AS MATERIALIZED (
      SELECT DISTINCT ON (p.payload->>'bet_id',c.venue) c.id,c.revision,c.venue,
         p.payload->>'league' league,p.payload->>'family' family,
         COALESCE((p.payload->>'main')::boolean,false) main,e.provider,e.native_event_id,
         p.payload->>'input_revision' input_revision,p.valid_until,o.facts->>'state' quote_state
      FROM public.current_pregame_price p JOIN public.current_contract_storage c ON c.id=p.contract_id
      JOIN public.current_event e ON e.id=c.event_id
      LEFT JOIN public.current_offer_storage o ON o.contract_id=c.id
      WHERE c.active AND p.start_at>(SELECT at FROM clock) AND c.venue=ANY(%s)
        AND p.payload->>'family' IN ('moneyline','spread','total')
        AND p.payload->>'period'='full_game'
        AND (%s::text IS NULL OR p.payload->>'league'=%s)
        AND (%s::text IS NULL OR p.payload->>'family'=%s)
      ORDER BY p.payload->>'bet_id',c.venue,o.received_order DESC NULLS LAST,c.id
    ) SELECT b.venue,b.league,b.family,b.main,
        CASE WHEN b.quote_state IS DISTINCT FROM 'available' THEN 'price_withdrawn'
          WHEN b.valid_until<=(SELECT at FROM clock) THEN 'stale_quote'
          WHEN d.receipt_id IS NULL THEN 'book_unobserved'
          WHEN d.contract_revision<>b.revision THEN 'identity_revision_changed'
          WHEN d.valid_until<=(SELECT at FROM clock) THEN 'stale_book' ELSE NULL END reason,
        d.receipt->>'reason' raw_reason,
        COALESCE(w.projection, d.valuations->b.input_revision)->'result' result,
        w.projection IS NOT NULL exact_reference
      FROM base b
      LEFT JOIN public.current_pregame_depth d ON d.contract_id=b.id AND d.published_at<=(SELECT at FROM clock)
      LEFT JOIN LATERAL (
        SELECT s.pull_id,s.state FROM public.market_pull_scope s JOIN public.market_pull p USING(pull_id)
        WHERE d.valid_until>(SELECT at FROM clock) AND d.receipt->>'reason' IS NULL
          AND b.provider='sportsgameodds' AND s.event_id=b.native_event_id AND s.family=b.family
          AND s.period='full_game' AND s.coverage->>'covers_board'='true'
        ORDER BY p.started_order DESC LIMIT 1
      ) latest ON true
      LEFT JOIN LATERAL (
        SELECT hit.value projection FROM jsonb_each(d.valuations) hit
        WHERE latest.state='complete' AND split_part(hit.key,':',1)='dashboard'
          AND split_part(hit.key,':',2)=latest.pull_id LIMIT 1
      ) w ON true"""
    rows = db.execute(sql, (at,[venue] if venue else list(VENUES),sport,sport,family,family)).fetchall()
    groups = {}
    for row in rows:
        group = tuple(row[key] for key in ('venue','league','family','main'))
        totals = groups.setdefault(group, dict(opportunities=0, assessable=0, full_size=0, ev_assessable=0,
                                               stake=Fraction(0), reasons=Counter()))
        totals['opportunities'] += 1
        result = row['result'] or {}
        if row['reason']:
            totals['reasons'][row['reason']] += 1
            continue
        size = result.get('size_status','unknown')
        totals['assessable'] += size != 'unknown'
        totals['full_size'] += size == 'full_size'
        totals['ev_assessable'] += bool(row['exact_reference'] and result.get('modeled_net_ev') is not None)
        if result.get('modeled_stake_usd') is not None and (size != 'unknown' or result.get('availability_is_lower_bound')):
            totals['stake'] += Fraction(result['modeled_stake_usd'])
        reason = result.get('reason') or row['raw_reason']
        if not row['exact_reference'] and result.get('modeled_net_ev') is not None:
            reason = reason or 'reference_revision_changed'
        if reason or size == 'unknown':
            totals['reasons'][reason or 'book_unobserved'] += 1
    output = []
    for (venue,league,family,main), totals in sorted(groups.items()):
        supported = exact_wire(totals.pop('stake'))
        output.append(dict(venue=venue, league=league, family=family, main=main, **totals,
            intended_stake_usd=str(int(BOARD_STAKE)*totals['opportunities']), observed_supported_stake_usd=supported))
    return dict(coverage=output,total=len(rows),provider_requests=0,scheduled_calculations=0,
                read_at=at.isoformat(),liquidity_stake_usd=BOARD_STAKE)
