"""Read committed, fee-qualified market prices and exact opposing book quotes."""

from collections import defaultdict, OrderedDict
from threading import Lock
from fractions import Fraction as F
from datetime import timedelta
from itertools import product
from psycopg.types.json import Jsonb
from app.comparison import pregame_arbs as math
from app.comparison.current_pregame import reference_key
from app.comparison.sgo_reference import american_probability
from app.comparison.sportsbooks import SPORTSBOOKS
from app.comparison.reference_scope import PROVIDER, REFERENCE_BOOKS
from .current_pregame import configured_routes, utc, read as pregame_read
from .store import hashed, stamp
from .pregame_known_withdrawals import ROW_GUARDS, BOOK_GUARD

_CACHE = OrderedDict()
_CACHE_LOCK = Lock()
_PAIR_CACHE = OrderedDict()
_PAIR_CACHE_LIMIT = 4096
_SCAN_CACHE = OrderedDict()
_SCAN_CACHE_LIMIT = 4
_VIEW_FIELDS = frozenset(("sort", "league", "family", "venue", "category", "book"))


def cached_pair(left, right, *, at):
    """Reuse exact immutable source/fee inputs across unrelated game revisions.

    SQL eligibility still runs on every miss of the query cache. Expired fees,
    withdrawal, route changes and kickoff exclude entries before this lookup;
    original quote clocks and the original calculation timestamp stay intact.
    """
    key = (left["cache_identity"], right["cache_identity"])
    with _CACHE_LOCK:
        if key in _PAIR_CACHE:
            _PAIR_CACHE.move_to_end(key)
            return _PAIR_CACHE[key]
        # Concurrent visits share the same immutable calculation rather than
        # multiplying CPU work after a client retries.
        result = math.evaluate(left, right, at=at)
        _PAIR_CACHE[key] = result
        while len(_PAIR_CACHE) > _PAIR_CACHE_LIMIT:
            _PAIR_CACHE.popitem(last=False)
    return result


def hydrate_prices(db, entries):
    """Load exact financial inputs only when needed, bound to the frozen price.

    All alias/price witnesses remain in the initial scan. Templates need their
    original record for exact line/role checks; modeled legs additionally need
    the unchanged fee input. A concurrent replacement fails rather than mixing
    its financial evidence with an older price outside a repeatable-read caller.
    """
    pending = {
        e["contract_id"]: e
        for e in entries
        if not e.get("sportsbook") and "fee_input" not in e
    }
    if not pending:
        return
    rows = list(
        db.execute(
            """SELECT contract_id,game_key,valid_until,payload,record,fee_input
        FROM current_pregame_price WHERE contract_id=ANY(%s)""",
            (list(pending),),
        )
    )
    if len(rows) != len(pending):
        raise TimeoutError("arbitrage_source_changed")
    for row in rows:
        entry = pending[row["contract_id"]]
        if (
            row["payload"] != entry["payload"]
            or row["valid_until"] != entry["valid_until"]
            or row["game_key"] != entry["game_key"]
        ):
            raise TimeoutError("arbitrage_source_changed")
        entry.update(record=row["record"], fee_input=row["fee_input"])


def book_query(db, query, parameters):
    """Avoid measured multi-second compilation for this one short-lived query.

    A nested transaction restores the prior setting on query failure; success
    restores it explicitly. The same scope works for standalone autocommit
    callers, without changing the connection or any other reader's policy.
    """
    with db.transaction():
        previous = db.execute("SHOW jit").fetchone()["jit"]
        if previous != "off":
            db.execute("SELECT set_config('jit','off',true)")
        result = db.execute(query, parameters)
        if previous != "off":
            db.execute("SELECT set_config('jit',%s,true)", (previous,))
        return result


def read_book_quotes(db, request_lines, *, include_groups=False, books=None):
    """Fetch supported books on represented lines before decoding quote bodies.

    The spread bound deliberately includes both signs; final canonical side,
    line and reversed-role checks retain their ordinary authority. Cross-products
    compare decimal and rational lines exactly, without float conversion.
    Profit bounds admit whole book/outcome witness groups across attached events;
    newest unprofitable quotes and conflicting ties must survive that admission.
    Unparsed price formats stay optimistic; only the ordinary model validates them.
    Materialize compact quote fields once: a parameterized event scan per requested
    alternate otherwise repeats JSON parsing and authority checks for every line.
    """
    if not request_lines:
        return []
    rows = list(
        book_query(
            db,
            """WITH requested AS (
                  SELECT * FROM jsonb_to_recordset(%s)
                    r(event_id text,family text,numerator numeric,denominator numeric,side text,
                      group_key text,canonical_side text,cost_numerator numeric,cost_denominator numeric)),
                quotes AS MATERIALIZED (
                SELECT q.id AS quote_id,
                  q.event_id,fields.market AS family,fields.side AS side,
                  fields.venue AS venue,fields.price_american#>>'{}' AS price_american,
                  jsonb_typeof(fields.price_american)='string' AS price_is_string,
                  CASE WHEN normalized.line ~
                    '^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?(/[0-9]+)?$'
                    AND pg_input_is_valid(split_part(normalized.line,'/',1),'numeric')
                    AND pg_input_is_valid(COALESCE(NULLIF(split_part(normalized.line,'/',2),''),'1'),'numeric')
                    THEN split_part(normalized.line,'/',1)::numeric END AS numerator,
                  CASE WHEN normalized.line ~
                    '^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?(/[0-9]+)?$'
                    AND pg_input_is_valid(split_part(normalized.line,'/',1),'numeric')
                    AND pg_input_is_valid(COALESCE(NULLIF(split_part(normalized.line,'/',2),''),'1'),'numeric')
                    THEN COALESCE(NULLIF(split_part(normalized.line,'/',2),''),'1')::numeric END AS denominator
                FROM current_sgo_reference q CROSS JOIN LATERAL jsonb_to_record(
                  CASE WHEN jsonb_typeof(q.facts)='object' THEN q.facts ELSE '{}'::jsonb END)
                  AS fields(market text,side text,venue text,line text,price_american jsonb,
                    available jsonb,provider_available jsonb,phase text,period text,partition text)
                CROSS JOIN LATERAL (
                  SELECT replace(trim(fields.line),'_','') AS line) normalized
                WHERE q.event_id=ANY(%s) AND fields.venue=ANY(%s)
                  AND fields.available='true'::jsonb
                  AND (NOT (q.facts ? 'provider_available') OR fields.provider_available='true'::jsonb)
                  AND (fields.phase)='pregame' AND (fields.period)='game'
                  AND (fields.partition) IS DISTINCT FROM 'three_way'
                  AND """
            + BOOK_GUARD
            + """
                  ), scoped AS MATERIALIZED (
                  SELECT q.quote_id,q.venue,q.price_american,q.price_is_string,
                    COALESCE(r.group_key,'') AS group_key,COALESCE(r.canonical_side,q.side) AS canonical_side,
                    r.cost_numerator,r.cost_denominator
                  FROM quotes q JOIN requested r ON q.event_id=r.event_id AND q.family=r.family
                  WHERE (r.side IS NULL OR q.side=r.side)
                    AND (r.family='moneyline' OR CASE WHEN r.family='spread' THEN
                      abs(q.numerator)*r.denominator=abs(r.numerator)*q.denominator
                    ELSE q.numerator*r.denominator=r.numerator*q.denominator END)),
                admitted AS (
                  SELECT quote_id,group_key,bool_or(cost_numerator IS NULL OR CASE
                    WHEN price_is_string AND price_american ~ '^[+-]?[0-9]{1,12}([.][0-9]{1,12})?$' THEN
                      CASE WHEN price_american::numeric>=100 THEN
                        price_american::numeric*(cost_denominator-cost_numerator)>100*cost_numerator
                      WHEN price_american::numeric<=-100 THEN
                        -price_american::numeric*cost_numerator<100*(cost_denominator-cost_numerator)
                      ELSE false END
                    ELSE true END) OVER(PARTITION BY group_key,canonical_side,venue) AS potential
                  FROM scoped)
                SELECT q.facts"""
            + (",chosen.group_keys" if include_groups else "")
            + " FROM current_sgo_reference q JOIN ("
            + (
                "SELECT quote_id,array_agg(DISTINCT group_key) AS group_keys FROM admitted WHERE potential GROUP BY quote_id"
                if include_groups
                else "SELECT DISTINCT quote_id FROM admitted WHERE potential"
            )
            + ") chosen ON q.id=chosen.quote_id",
            (
                Jsonb(request_lines),
                sorted({r["event_id"] for r in request_lines}),
                sorted(SPORTSBOOKS if books is None else books),
            ),
        )
    )
    return [
        dict(row["facts"], _arb_groups=row["group_keys"])
        if include_groups
        else row["facts"]
        for row in rows
    ]


def observation_clock(entry):
    """Compare instants, not ISO strings with potentially different UTC offsets."""
    times = entry["payload"]["times"]
    return (
        times.get("source_at") is not None,
        stamp(times.get("source_at") or times["received_at"]),
        stamp(times["received_at"]),
        entry["contract_id"],
    )


def book_entry(quote, template, *, at):
    p = template["payload"]
    try:
        if (
            quote.get("event_id") not in p.get("sportsbook_event_ids", [])
            or quote.get("available") is not True
            or quote.get("provider_available", True) is not True
            or quote.get("venue") not in SPORTSBOOKS
            or quote.get("partition") == "three_way"
            or quote.get("phase") != "pregame"
            or quote.get("period") != "game"
            or quote.get("league") != p["league"]
            or quote.get("market") != p["family"]
            or stamp(quote["starts_at"]) != stamp(p["kickoff"])
            or not quote.get("source_at")
            or not stamp(quote["source_at"])
            <= stamp(quote["received_at"])
            <= at
            < stamp(p["kickoff"])
        ):
            return None
        if any(
            quote.get("event_status", {}).get(k)
            for k in (
                "live",
                "started",
                "ended",
                "finalized",
                "cancelled",
                "suspended",
                "delayed",
            )
        ):
            return None
        family, _, line = reference_key(template["record"])
        side = quote["side"]
        if p.get("sportsbook_sides_reversed", {}).get(quote["event_id"]) and side in (
            "home",
            "away",
        ):
            side = {"home": "away", "away": "home"}[side]
        qline = None if family == "moneyline" else F(quote["line"])
        if family == "spread" and side == "away":
            qline = -qline
        if qline != line:
            return None
        decimal = 1 / american_probability(quote["price_american"])
        selection = dict(template["record"]["selection"])
        if family == "total":
            selection.update(predicate=side, signed_line=quote["line"])
        else:
            event = template["record"]["event"]
            selection["participant"] = event[side]
            if family == "spread":
                selection["signed_line"] = quote["line"]
        label = next(
            (
                name
                for name, team in template["record"]["event"]
                .get("participants", {})
                .items()
                if team == selection.get("participant")
            ),
            selection.get("participant"),
        )
        payload = dict(
            p,
            id="book:"
            + hashed(
                [quote["event_id"], quote["venue"], quote["odd_id"], quote["line"]]
            ),
            venue=quote["venue"],
            side=side,
            selection=selection,
            selection_label=label,
            reference=None,
            posted=dict(value=quote["price_american"], units="american_odds"),
            source=dict(provider="sportsgameodds", native_event_id=quote["event_id"]),
            times=dict(source_at=quote["source_at"], received_at=quote["received_at"]),
            raw=dict(posted_decimal=str(decimal), after_fee_decimal=str(decimal)),
            display=dict(
                posted_odds=quote["price_american"], after_fees=quote["price_american"]
            ),
            fee=dict(
                entry_usd="0",
                committed_usd="100",
                classification="sportsbook_no_placement_fee",
                evidence={},
                cashflows={},
            ),
        )
        from .pregame_quote_evidence import market_link

        if link := market_link(quote["venue"], quote.get("bookmaker_market_link")):
            payload["verification_link"] = dict(
                url=link,
                scope="market",
                basis="Retained provider market link; verify venue identity and terms",
            )
        return dict(payload=payload, sportsbook=True)
    except (KeyError, ValueError, TypeError, ArithmeticError):
        return None


def ordered_pairs(rows, selected):
    rows = sorted(rows, key=lambda p: (-F(p["return_rate"]), p["kickoff"], p["id"]))
    if selected == "start":
        return sorted(rows, key=lambda p: (p["kickoff"], p["id"]))
    if selected in ("newest", "oldest"):

        def clock(pair):
            times = [
                stamp(leg["times"]["source_at"])
                for leg in pair["legs"]
                if leg.get("times", {}).get("source_at")
            ]
            return min(times) if len(times) == len(pair["legs"]) else None

        known = [p for p in rows if clock(p) is not None]
        unknown = [p for p in rows if clock(p) is None]
        return sorted(known, key=clock, reverse=selected == "newest") + unknown
    return rows


def pair_matches(venues, category, book, query):
    return not (
        query.get("venue")
        and query["venue"] not in venues
        or query.get("category")
        and query["category"] != category
        or query.get("book")
        and query["book"] != book
    )


def scan_view(scan, query, selected, offset, limit):
    """Project a completed scan; never treat a narrowed scan as a superset."""
    if (query.get("league") or query.get("family")) and not scan["uniform_groups"]:
        return None
    groups = {
        key: value
        for key, value in scan["groups"].items()
        if (not query.get("league") or query["league"] == value["league"])
        and (not query.get("family") or query["family"] == value["family"])
    }
    rows = []
    for pair in scan["packet"]["rows"]:
        if scan["row_groups"][pair["id"]] not in groups:
            continue
        venues = tuple(leg["venue"] for leg in pair["legs"])
        book = next((v for v in venues if v in SPORTSBOOKS), None)
        if pair_matches(venues, pair["category"], book, query):
            rows.append(pair)
    evaluated, excluded = 0, 0
    for (group, venues, category, book), counts in scan["counts"].items():
        if group in groups and pair_matches(venues, category, book, query):
            evaluated += counts[0]
            excluded += counts[1]
    deadlines = [g["deadline"] for g in groups.values() if g["deadline"]]
    if scan["cursor_deadline"]:
        deadlines.append(scan["cursor_deadline"])
    deadline = min(deadlines, default=None)
    books = sorted({book for g in groups.values() for book in g["books"]})
    rows = ordered_pairs(rows, selected)
    return dict(
        scan["packet"],
        rows=rows[offset : offset + limit],
        total=len(rows),
        offset=offset,
        limit=limit,
        evaluated_pairs=evaluated,
        excluded_pairs=excluded,
        sportsbooks=books,
        refresh_at=deadline.isoformat() if deadline else None,
    )


def read(db, query, *, at=None, can_continue=None):
    at = at or utc()
    query = dict(query)
    query.setdefault('reference_scope', 'selected')
    query.setdefault('provider', PROVIDER)
    if query['reference_scope'] not in ('selected', 'all'):
        raise ValueError('Unknown reference scope')
    if query['provider'] != PROVIDER and query['reference_scope'] != 'all':
        raise ValueError('Other providers require historical selection')

    def checkpoint():
        if can_continue is not None and not can_continue():
            raise TimeoutError("arbitrage_read_cancelled")

    checkpoint()
    limit = max(1, min(100, int(query.get("limit", "30"))))
    offset = max(0, int(query.get("offset", "0")))
    selected_sort = query.get("sort", "return")
    if selected_sort not in ("return", "newest", "oldest", "start"):
        raise ValueError("Unknown arbitrage order")
    age = None
    if query.get("max_age_minutes"):
        age = int(query["max_age_minutes"])
        if not 1 <= age <= 525600:
            raise ValueError("Invalid maximum age")
    cursor_packet = pregame_read(
        db, {"updates": "1", "_scope_seconds": query.get("_scope_seconds")}, at=at
    )
    cursor = cursor_packet["cursor"]
    identity = (
        db.info.host,
        db.info.port,
        db.info.dbname,
        cursor,
        tuple(sorted((k, v) for k, v in query.items() if k not in ("limit", "offset"))),
    )
    scan_identity = identity[:-1] + (
        tuple(
            sorted(
                (k, v)
                for k, v in query.items()
                if k not in _VIEW_FIELDS | {"limit", "offset"}
            )
        ),
    )
    with _CACHE_LOCK:
        cached = _CACHE.get(identity)
        if cached is not None and (
            cached["refresh_at"] is None or at < stamp(cached["refresh_at"])
        ):
            _CACHE.move_to_end(identity)
            return dict(
                cached,
                rows=cached["rows"][offset : offset + limit],
                offset=offset,
                limit=limit,
            )
        scan = _SCAN_CACHE.get(scan_identity)
        if scan is not None and (
            scan["packet"]["refresh_at"] is None
            or at < stamp(scan["packet"]["refresh_at"])
        ):
            _SCAN_CACHE.move_to_end(scan_identity)
        else:
            scan = None
    if scan is not None:
        projected = scan_view(scan, query, selected_sort, offset, limit)
        if projected is not None:
            checkpoint()
            return projected
    complete_scan = not any(query.get(k) for k in _VIEW_FIELDS - {"sort"})
    routes = configured_routes(db)
    checkpoint()
    # A queued source/fee change suppresses stale calculations before rebuilding.
    late_inputs = not any(query.get(k) for k in ("league", "family", "search"))
    filters, parameters = list(ROW_GUARDS), [at, at, at, at]
    filters.append('e.provider=%s')
    parameters.append(query['provider'])
    if query.get("_scope_seconds"):
        filters.append("p.start_at<=%s")
        parameters.append(at + timedelta(seconds=int(query["_scope_seconds"])))
    if age is not None:
        filters.append("(p.payload#>>'{times,source_at}')::timestamptz>=%s")
        parameters.append(at - timedelta(minutes=age))
    for name in ("league", "family"):
        if query.get(name):
            filters.append("p.payload->>'" + name + "'=%s")
            parameters.append(query[name])
    if query.get("search"):
        filters.append("p.payload->>'game' ILIKE %s")
        parameters.append("%" + query["search"][:150] + "%")
    entries = list(
        db.execute(
            "SELECT "
            + (
                "p.contract_id,p.game_key,p.valid_until,p.payload"
                if late_inputs
                else "p.*"
            )
            + """ FROM current_pregame_price p
        JOIN current_contract c ON c.id=p.contract_id
        JOIN current_offer_storage o ON o.contract_id=c.id JOIN LATERAL (SELECT * FROM current_event WHERE id=c.event_id LIMIT 1) e ON true
        WHERE p.start_at>%s AND p.valid_until>%s AND e.scheduled_start::timestamptz>%s
          AND o.facts->>'state' IS DISTINCT FROM 'unavailable'
          AND NOT EXISTS(SELECT 1 FROM sgo_line_presence lp WHERE lp.quote_id=o.sgo_quote_id AND lp.expired)
          AND NOT EXISTS(SELECT 1 FROM current_pregame_work w WHERE w.provider=e.provider AND w.native_event_id=e.native_event_id)
          AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(p.payload->'sportsbook_event_ids') ref(event_id)
            JOIN current_pregame_work w ON w.provider='sportsgameodds' AND w.native_event_id=ref.event_id)
          AND NOT (COALESCE(e.facts->'status','{}'::jsonb) @> '{"live":true}'::jsonb)
          AND NOT (COALESCE(e.facts->'status','{}'::jsonb) @> '{"ended":true}'::jsonb)
          AND COALESCE(e.facts#>>'{status,status}','') NOT IN ('cancelled','final','suspended','started','delayed')
        """
            + (" AND " + " AND ".join(filters) if filters else "")
            + " ORDER BY p.game_key,p.contract_id",
            parameters,
        )
    )
    entries = [
        e
        for e in entries
        if e["payload"]["source"]["provider"] == routes.get(e["payload"]["venue"])
    ]
    labels = {}
    uniform_groups = True
    for entry in entries:
        p = entry["payload"]
        label = (p["league"], p["family"])
        if labels.setdefault(p["arb_key"], label) != label:
            uniform_groups = False
    # Prefer newest native alias, never whichever stale alias yields more profit.
    unique = {}
    for entry in entries:
        checkpoint()
        p = entry["payload"]
        key = (p["game_key"], p["arb_key"], p["side"], p["venue"])
        if query.get("league") and p["league"] != query["league"]:
            continue
        if query.get("family") and p["family"] != query["family"]:
            continue
        if query.get("search", "").casefold() not in p["game"].casefold():
            continue
        previous = unique.get(key)
        if previous is None or observation_clock(entry) > observation_clock(previous):
            unique[key] = entry
    entries = list(unique.values())
    # Only exact lines represented by retained market legs can form a pair.
    # Fetching every alternate from each event previously decoded tens of
    # thousands of irrelevant JSON bodies before the first pair was modeled.
    grouped = defaultdict(lambda: defaultdict(list))
    for entry in entries:
        grouped[entry["payload"]["arb_key"]][entry["payload"]["side"]].append(entry)
    hydrate_prices(db, [next(iter(sides.values()))[0] for sides in grouped.values()])
    requested = {}
    for group_key, sides in grouped.items():
        markets = [e for side in sides.values() for e in side]
        template = markets[0]
        p = template["payload"]
        family, _, line = reference_key(template["record"])
        actual = abs(line) if family == "spread" else line
        events = {
            eid for e in markets for eid in e["payload"].get("sportsbook_event_ids", [])
        }
        for entry in markets:
            canonical_side = {
                "home": "away",
                "away": "home",
                "over": "under",
                "under": "over",
            }.get(entry["payload"]["side"])
            if canonical_side is None:
                continue
            probability = 1 / F(entry["payload"]["raw"]["posted_decimal"])
            for eid in events:
                side = canonical_side
                if p.get("sportsbook_sides_reversed", {}).get(eid) and side in (
                    "home",
                    "away",
                ):
                    side = {"home": "away", "away": "home"}[side]
                key = (
                    group_key,
                    canonical_side,
                    eid,
                    family,
                    None if actual is None else actual.numerator,
                    1 if actual is None else actual.denominator,
                    side,
                )
                requested[key] = min(probability, requested.get(key, probability))
    request_lines = [
        dict(
            group_key=group_key,
            canonical_side=canonical,
            event_id=eid,
            family=family,
            numerator=n,
            denominator=d,
            side=side,
            cost_numerator=cost.numerator,
            cost_denominator=cost.denominator,
        )
        for (group_key, canonical, eid, family, n, d, side), cost in sorted(
            requested.items()
        )
    ]
    quotes = read_book_quotes(db, request_lines, include_groups=complete_scan,
        books=REFERENCE_BOOKS if query['reference_scope'] == 'selected' else None)
    if query.get("max_age_minutes"):
        cutoff = at - timedelta(minutes=int(query["max_age_minutes"]))
        quotes = [
            q for q in quotes if q.get("source_at") and stamp(q["source_at"]) >= cutoff
        ]
    by_event = defaultdict(list)
    for q in quotes:
        try:
            line = None if q["market"] == "moneyline" else F(q["line"])
            if q["market"] == "spread" and q["side"] == "away":
                line = -line
            by_event[(q["event_id"], q["market"], line)].append(q)
        except (KeyError, ValueError, TypeError, ArithmeticError):
            continue
    results = []
    evaluated = 0
    excluded = 0
    counts = defaultdict(lambda: [0, 0])
    group_metadata = {}
    row_groups = {}
    prepared_groups = []
    financial_inputs = {}
    for group_key, sides in grouped.items():
        checkpoint()
        all_markets = [e for side in sides.values() for e in side]
        if complete_scan:
            deadlines = [e["valid_until"] for e in all_markets]
            if age is not None:
                deadlines.extend(
                    stamp(e["payload"]["times"]["source_at"]) + timedelta(minutes=age)
                    for e in all_markets
                    if e["payload"].get("times", {}).get("source_at")
                )
            group_metadata[group_key] = dict(
                league=all_markets[0]["payload"]["league"],
                family=all_markets[0]["payload"]["family"],
                deadline=min(deadlines, default=None),
                books=set(),
            )
        books = {}
        ambiguous = set()
        entry = all_markets[0]
        family, _, line = reference_key(entry["record"])
        for eid in {
            eid
            for e in all_markets
            for eid in e["payload"].get("sportsbook_event_ids", [])
        }:
            lookup_line = (
                -line
                if family == "spread"
                and entry["payload"].get("sportsbook_sides_reversed", {}).get(eid)
                else line
            )
            for quote in by_event[(eid, family, lookup_line)]:
                book = book_entry(quote, entry, at=at)
                if not book:
                    continue
                key = (book["payload"]["venue"], book["payload"]["side"])
                prior = books.get(key)
                clock = lambda b: stamp(b["payload"]["times"]["source_at"])
                if prior and clock(book) < clock(prior):
                    continue
                if (
                    prior
                    and clock(book) == clock(prior)
                    and prior["payload"]["posted"] != book["payload"]["posted"]
                ):
                    ambiguous.add(key)
                elif prior is None or clock(book) > clock(prior):
                    ambiguous.discard(key)
                books[key] = book
        candidates = list(all_markets) + [
            v for k, v in books.items() if k not in ambiguous
        ]
        first = [e for e in candidates if e["payload"]["side"] in ("home", "over")]
        second = [e for e in candidates if e["payload"]["side"] in ("away", "under")]
        for candidate in candidates:
            candidate["acquisition_probability"] = 1 / F(
                candidate["payload"]["raw"]["posted_decimal"]
            )
        # Alias and conflicting-book selection is already complete. Preserve all
        # price witnesses; full financial inputs are needed only where the same
        # existing pre-fee necessary test can proceed to fee-qualified math.
        for a, b in product(first, second):
            checkpoint()
            if (
                a.get("sportsbook")
                and b.get("sportsbook")
                or a["payload"]["venue"] == b["payload"]["venue"]
                or a["acquisition_probability"] + b["acquisition_probability"] >= 1
            ):
                continue
            for candidate in (a, b):
                if not candidate.get("sportsbook"):
                    financial_inputs[candidate["contract_id"]] = candidate
        prepared_groups.append((group_key, candidates, first, second))
    hydrate_prices(db, financial_inputs.values())
    for group_key, candidates, first, second in prepared_groups:
        checkpoint()
        for candidate in candidates:
            payload = candidate["payload"]
            candidate["cache_identity"] = hashed(
                [
                    payload["id"],
                    payload.get("input_revision"),
                    payload["raw"],
                    payload.get("times"),
                    payload.get("collection"),
                    payload.get("scoring_scope"),
                    candidate.get("fee_input"),
                    None if payload.get("input_revision") else candidate.get("record"),
                ]
            )
        for a, b in product(first, second):
            checkpoint()
            if a.get("sportsbook") and b.get("sportsbook"):
                continue
            if query.get("book") and not any(
                e.get("sportsbook") and e["payload"]["venue"] == query["book"]
                for e in (a, b)
            ):
                continue
            if query.get("venue") and query["venue"] not in (
                a["payload"]["venue"],
                b["payload"]["venue"],
            ):
                continue
            category = (
                "market_book"
                if a.get("sportsbook") or b.get("sportsbook")
                else "market_market"
            )
            if query.get("category") and query["category"] != category:
                continue
            evaluated += 1
            if complete_scan:
                count_key = (
                    group_key,
                    tuple(sorted((a["payload"]["venue"], b["payload"]["venue"]))),
                    category,
                    next(
                        (e["payload"]["venue"] for e in (a, b) if e.get("sportsbook")),
                        None,
                    ),
                )
                counts[count_key][0] += 1
            # Most pairs cannot beat even the pre-fee price. Do not repeatedly
            # decode fractions or rebuild fee orders for those combinations.
            if (
                a["payload"]["venue"] == b["payload"]["venue"]
                or a["acquisition_probability"] + b["acquisition_probability"] >= 1
            ):
                continue
            try:
                pair = cached_pair(a, b, at=at)
            except (ValueError, KeyError, TypeError, ArithmeticError):
                excluded += 1
                if complete_scan:
                    counts[count_key][1] += 1
                continue
            if pair:
                results.append(pair)
                row_groups[pair["id"]] = group_key
        # Each entry belongs to this exact arb group. Its cent-allocation memo
        # has no use after the group and must not accumulate across the slate.
        for candidate in candidates:
            candidate.pop("_reprice_cache", None)
    results = ordered_pairs(results, selected_sort)
    deadline = min((e["valid_until"] for e in entries), default=None)
    if cursor_packet.get("refresh_at"):
        boundary = stamp(cursor_packet["refresh_at"])
        deadline = min(deadline, boundary) if deadline else boundary
    if query.get("max_age_minutes"):
        age = timedelta(minutes=int(query["max_age_minutes"]))
        age_deadlines = [
            stamp(e["payload"]["times"]["source_at"]) + age
            for e in entries
            if e["payload"].get("times", {}).get("source_at")
        ]
        age_deadlines.extend(
            stamp(q["source_at"]) + age for q in quotes if q.get("source_at")
        )
        if deadline:
            age_deadlines.append(deadline)
        deadline = min(age_deadlines, default=None)
    packet = dict(
        schema="predict-pregame-arbs-1",
        rows=results,
        total=len(results),
        offset=offset,
        limit=limit,
        cursor=cursor,
        provider_requests=0,
        scheduled_calculations=0,
        sportsbook_prefilter="opposite_market_positive_before_fees",
        evaluated_pairs=evaluated,
        excluded_pairs=excluded,
        refresh_at=deadline.isoformat() if deadline else None,
        conditioning="decisive_completed_game",
        instant_fill_max_usd=None,
        sportsbooks=sorted(
            {
                q["venue"]
                for q in quotes
                if q.get("venue") in SPORTSBOOKS and q.get("available") is True
            }
        ),
    )

    if complete_scan:
        for quote in quotes:
            for group in quote.get("_arb_groups", []):
                if group not in group_metadata:
                    continue
                metadata = group_metadata[group]
                if quote.get("venue") in SPORTSBOOKS and quote.get("available") is True:
                    metadata["books"].add(quote["venue"])
                if query.get("max_age_minutes") and quote.get("source_at"):
                    boundary = stamp(quote["source_at"]) + age
                    metadata["deadline"] = min(metadata["deadline"], boundary)
        scan = dict(
            packet=packet,
            groups=group_metadata,
            row_groups=row_groups,
            counts=dict(counts),
            uniform_groups=uniform_groups,
            cursor_deadline=stamp(cursor_packet["refresh_at"])
            if cursor_packet.get("refresh_at")
            else None,
        )
    with _CACHE_LOCK:
        if complete_scan:
            _SCAN_CACHE[scan_identity] = scan
            while len(_SCAN_CACHE) > _SCAN_CACHE_LIMIT:
                _SCAN_CACHE.popitem(last=False)
        _CACHE[identity] = packet
        while len(_CACHE) > 8:
            _CACHE.popitem(last=False)
    return dict(packet, rows=results[offset : offset + limit])
