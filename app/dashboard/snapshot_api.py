"""Ordinary immutable comparison snapshots; browsing never dispatches providers."""

import asyncio
from time import monotonic
from threading import RLock
from datetime import datetime
from aiohttp import web
from app.storage.store import connect
from app.storage import comparison_snapshot as snapshots
from app.comparison.snapshot_math import assumptions
from app.comparison.snapshot_named_benchmark import selected_references
from .local_security import read_json, PublicRequestError
from .snapshot_display import presented, search_index, comparison_groups, ranking_value


def page_options(query):
    view = query.get("view", "ev")
    if view not in ("ev", "odds", "arbs"):
        raise PublicRequestError("Unknown snapshot view")
    metric = query.get("metric", "gross_return_percent")
    if metric not in (
        "gross_return_percent",
        "conditional_return_percent",
        "conservative_return_percent",
        "net_return_percent",
        "price_difference_cents",
        "minimum_return_percent",
    ):
        raise PublicRequestError("Unknown metric")
    try:
        offset = int(query.get("offset", "0"))
        limit = int(query.get("limit", "25"))
    except ValueError:
        raise PublicRequestError("Invalid page bounds") from None
    if offset < 0 or not 1 <= limit <= 100:
        raise PublicRequestError("Invalid page bounds")
    return view, metric, offset, limit


def page(result, query, *, options=None):
    from app.comparison.snapshot_fee_scope import RANKING_BASIS
    view, metric, offset, limit = options or page_options(query)
    if result is None:
        return dict(state="empty", defaults=assumptions()[0], provider_requests=0)
    out = {k: v for k, v in result.items() if k not in ("rows", "pairs", "references", "component_slices")}
    out['defaults'] = assumptions()[0]
    rows = result["pairs"] if view == "arbs" else result["rows"]

    names = search_index(result)

    def selected(row):
        return (
            all(
                not query.get(k) or str(row.get(field, "")) == query[k]
                for k, field in (("league", "league"), ("game", "game_key"))
            )
            and (
                not query.get("venue")
                or query["venue"] == row.get("venue")
                or query["venue"] in row.get("venues", [])
            )
            and (not query.get("family") or query["family"] == row["market"]["market"])
            and (all(term in (row["game_title"].casefold() + " " + names.get(row.get("game_key"), "")) for term in query.get("search", "").casefold().split()))
        )

    rows = [r for r in rows if selected(r)]
    position_count = len(rows)
    grouped = query.get("group") == "outcome"
    current = 'publication' in result
    by_id = {r["id"]: r for r in result["rows"]}
    if grouped:
        rows = comparison_groups(rows, by_id, metric, pairs=view == "arbs", current=current)
        if view == "odds":
            rows.sort(key=lambda r: (r["start_at"], r["game_title"], r["id"]))
    elif view == "odds":
        from .grouped_odds import group_prices

        bygame = {}
        for r in rows:
            bygame.setdefault(r["game_key"], []).append(r)
        odds_groups = []
        for prices in bygame.values():
            byid = {r["quote_id"]: r for r in prices}
            odds_groups.extend(
                dict(g, quotes=[byid[q] for ids in g["cells"].values() for q in ids])
                for g in group_prices(prices)["rows"]
            )
        rows = odds_groups
        rows.sort(
            key=lambda r: (
                r["quotes"][0]["start_at"],
                r["quotes"][0]["game_title"],
                r["id"],
            )
        )
    else:
        values = {r['id']: ranking_value(r, metric, current=current) for r in rows}
        rows = sorted(
            rows,
            key=lambda r: (
                values[r['id']] is None,
                -values[r['id']] if values[r['id']] is not None else 0,
                r["start_at"],
                r["id"],
            ),
        )
    out.update(
        state="ready",
        view=view,
        metric=metric,
        total=len(rows),
        grouping="outcome" if grouped else None,
        position_count=position_count,
        outcome_count=len(rows) if grouped else None,
        source_price_count=len({leg for r in rows for q in (r['quotes'] if grouped else [r])
                               for leg in q.get('legs', [])}) if view == 'arbs' else position_count,
        unranked_count=sum(r['score'] is None for r in rows) if grouped else
            sum(ranking_value(r, metric, current=current) is None for r in rows),
        ranking=dict(metric=metric, basis=(
            'conservative_public_schedule_estimate' if metric == 'conservative_return_percent' else
            'reviewed_trade_fees' if metric == 'conditional_return_percent' else metric),
            risk_basis=RANKING_BASIS if metric in ('conditional_return_percent','conservative_return_percent') else None,
            current_only=current, score_rule='maximum_eligible_exact_value'),
        offset=offset,
        limit=limit,
        rows=rows[offset : offset + limit],
    )
    by_id = {r["id"]: r for r in result["rows"]}
    def display(row):
        quote = presented(row, by_id)
        value = ranking_value(row, metric, current=current)
        quote['ranking'] = dict(eligible=value is not None, value=None if value is None else str(value),
            metric=metric, reason=None if value is not None else
            'metric_unavailable' if row.get(metric) is None else
            'current_authority_withdrawn' if not row.get('price_current') or row.get('current_reasons') else
            'metric_status_or_comparison_basis_unsupported')
        return quote
    out["rows"] = [dict(r, quotes=[display(q) for q in r["quotes"]]) if grouped or view == "odds" else display(r) for r in out["rows"]]
    out["reference_count"] = len(result["references"])
    coverage = {}
    for quote in (*result["rows"], *result["references"]):
        venue = quote.get("venue")
        if not venue:
            continue
        entry = coverage.setdefault(
            venue, dict(count=0, unknown_clock=0, newest=None, oldest=None)
        )
        entry["count"] += 1
        at = (quote.get("times") or {}).get("source_at")
        if not at:
            entry["unknown_clock"] += 1
            continue
        instant = datetime.fromisoformat(at)
        for key, choose in (("newest", max), ("oldest", min)):
            entry[key] = choose(entry[key], instant) if entry[key] else instant
    for entry in coverage.values():
        for key in ("newest", "oldest"):
            if entry[key]:
                entry[key] = entry[key].isoformat()
    out["coverage"] = coverage
    return out


def history(db, out):
    out["history"] = [
        dict(
            id=r["id"],
            snapshot_id=r["snapshot_id"],
            captured_at=r["captured_at"].isoformat(),
        )
        for r in db.execute(
            """SELECT r.id,r.snapshot_id,s.captured_at FROM comparison_snapshot_result r
           JOIN comparison_snapshot s ON s.id=r.snapshot_id ORDER BY r.calculated_at DESC LIMIT 12"""
        ).fetchall()
    ]
    return out


def mount(app):
    # Result IDs are immutable. Keep one list root, bounded to one revision.
    # Reading a small selected member must not evict the large rolling root.
    # Evidence retention/authority is still checked at its owning read boundary.
    decoded_cache=(None,None)
    decode_lock=RLock()
    def decoded(result_id, db=None, *, ordinary=False):
        nonlocal decoded_cache
        # Concurrent viewer/inspection reads share one cold decode. Otherwise
        # each can allocate the same large root and contend in Python's GC.
        with decode_lock:
            cached_id,cached_result=decoded_cache
            if cached_id==result_id:return cached_result
            if db is None:
                with connect() as connection:return decoded(result_id,connection,ordinary=ordinary)
            row=db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',
                (result_id,)).fetchone()
            result=snapshots.unpack(row['result'],lazy=ordinary,db=db,
                previous=cached_result if ordinary else None) if row else None
            # Lookup stays inside the caller's coherent MVCC frame.
            if ordinary:decoded_cache=(result_id,result)
            return result

    def leased_result(db, result_id, *, cache=False):
        if result_id:
            from app.storage.ordinary_publication import lease
            if not lease(db, result_id):
                return None
            return decoded(result_id,ordinary=cache)
        row = db.execute(
            """UPDATE comparison_snapshot_result SET lease_until=now()+interval '2 hours'
            WHERE id=COALESCE(%s,(SELECT result_id FROM comparison_publication WHERE kind='manual' AND id=''))
            RETURNING id,snapshot_id""",
            (result_id,),
        ).fetchone()
        if not row:
            return None
        db.execute(
            "UPDATE comparison_snapshot SET lease_until=now()+interval '2 hours' WHERE id=%s",
            (row["snapshot_id"],),
        )
        return decoded(row["id"],ordinary=cache)

    async def read(req):
        options = page_options(req.query)

        def work():
            with connect() as db:
                result = leased_result(db, req.query.get("result_id"),cache=True)
                if req.query.get("result_id") and result is None:
                    raise PublicRequestError("Selected snapshot expired")
                return history(db, page(result, req.query, options=options))

        return web.json_response(await asyncio.to_thread(work))

    from .browse_sessions import BrowseSessions
    browsing=BrowseSessions()

    async def current_read(req):
        timings = {}
        is_fee_census = req.path.endswith('/fee-coverage')
        query = dict(req.query)
        query.setdefault('metric', 'minimum_return_percent' if query.get('view') == 'arbs' else 'conditional_return_percent')
        query.setdefault('group', 'outcome')
        options = None if is_fee_census else page_options(query)
        current_desk = (options is not None and options[0] != 'arbs' and query.get('layout') == 'desk'
                        and (query.get('browse_odds') == '1' or query.get('ranked') == '1')
                        and query.get('last_known') != '1' and not req.path.endswith('/selection'))
        from app.storage import ordinary_publication as live
        from app.fees.schedule_lifecycle import revision as fee_revision
        from app.storage.store import hashed, stamp
        from app.storage.current_games import utc

        def fee_census(db, result, deps, owner, states, at, *, pairs=(), policy=None, epoch=None, settings=None):
            from .fee_coverage import census, source_inventory
            from .trade_desk import desk_phase, direct_venue_offer, phase_matches
            phase = desk_phase(query)
            if phase:
                result = dict(result, rows=[row for row in result['rows']
                    if direct_venue_offer(row) and phase_matches(row, phase, at)])
            counts = census(result, source_inventory(db, deps, phase=phase, at=at), pairs=pairs, policy=policy)
            counts['phase'] = phase
            if query.get('funnel') == '1':
                from .coverage_funnel import measure
                counts['synchronized_funnel'] = measure(db, result, deps, counts, owner, at=at, phase=phase)
                if query.get('independent') == '1':
                    from .coverage_finance_inputs import measure as audit_inputs
                    counts['synchronized_funnel']['independent_finance'] = audit_inputs(db, result, pairs, deps,
                        owner, states, settings=settings, policy=policy, epoch=epoch, at=at, phase=phase)
            return counts

        def work():
            started=monotonic()
            with connect() as db, db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                head = live.status(db)
                at = stamp(utc())
                owner, states = live.authority(db, at=at,
                    include_diagnostics=is_fee_census and query.get('funnel') == '1')
                provider = live.aggregate_provider(owner=owner)
                deps = live.dependencies(db, provider=provider)
                policy = live.policy_identity(provider)
                settings = live.current_settings(db)
                epoch = str(db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch'])
                timings['authority']=(monotonic()-started)*1000
                # No heartbeat/read timestamp in the change cursor.
                cursor = hashed([head['generation'], {k:v[:3] for k,v in deps.items()}, epoch, policy, settings['revision'],
                    fee_revision(owner.get('fee_lifecycle')),
                    owner.get('fee_products'),
                    owner.get('active'), owner.get('healthy'), owner.get('global_stopped'), owner.get('paused_sources'),
                    {k: [s.get('state'), s.get('reason_code'), s.get('observed_sports')] for k,s in states.items()},
                    int(at.timestamp())//2 if head['facts'].get('next_boundary') and at >= stamp(head['facts']['next_boundary']) else None])
                if req.path.endswith('/updates'):
                    return dict(schema=live.VERSION, cursor=cursor,
                        changed=req.query.get('after') != cursor,
                        generation=head['generation'], result_id=head['result_id'],
                        publication=head['facts'], poll_after_ms=2000, provider_requests=0)
                if not head['result_id']:
                    if is_fee_census:
                        empty = dict(rows=[], publication=dict(sources=states, read_at=at.isoformat()))
                        return dict(fee_census(db, empty, deps, owner, states, at, policy=policy, epoch=epoch, settings=settings),
                            state='initializing', cursor=cursor,
                            generation=head['generation'], result_id=None, provider_requests=0)
                    from app.storage.ordinary_projection import publication_runtime
                    return dict(state='initializing', publication=dict(state='initializing', sources=states,
                            data_runtime=publication_runtime(owner)),
                        cursor=cursor, generation=head['generation'], rows=[], total=0, provider_requests=0)
                if not is_fee_census and query.get('layout')!='desk' and not req.path.endswith('/selection') and (
                        query.get('expected_cursor') and query['expected_cursor'] != cursor or
                        options[2] and not query.get('expected_cursor')):
                    return dict(state='page_changed', reason='comparison_changed_restart_pagination',
                        cursor=cursor, generation=head['generation'], result_id=head['result_id'],
                        restart_offset=0, rows=[], provider_requests=0)
                stage=monotonic()
                cold=decoded_cache[0]!=head['result_id']
                result = decoded(head['result_id'],db,ordinary=True)
                timings['cold_decode' if cold else 'cached_decode']=(monotonic()-stage)*1000
                stage=monotonic()
                if req.path.endswith('/selection'):
                    selected=req.query.get('id')
                    if not selected or len(selected)>128:
                        raise PublicRequestError('Exact selection required')
                    pairs=[r for r in result['pairs'] if r['id']==selected]
                    ids={selected,*(leg for pair in pairs for leg in pair['legs'])}
                    result=dict(result,rows=[r for r in result['rows'] if r['id'] in ids],pairs=pairs)
                captured_pairs = [pair for pair in result['pairs'] if snapshots.exact_arb_pair(pair)]
                frames = (live.sportsbook_frames(db, at) if any(
                    (r.get('sportsbook_baseline') or {}).get('indicative') for r in result['rows'])
                    and owner.get('config', {}).get('aggregate_provider') == 'sportsgameodds' else ())
                result = live.project(result, deps, owner, states, at=at, policy=policy, epoch=epoch,
                                      settings=settings, sportsbook_frames=frames, current_desk=current_desk)
                timings['projection']=(monotonic()-stage)*1000
                if is_fee_census:
                    return dict(fee_census(db, result, deps, owner, states, at, pairs=captured_pairs,
                        policy=policy, epoch=epoch, settings=settings),
                        state=result['publication']['state'],
                        cursor=cursor, generation=head['generation'], result_id=head['result_id'], provider_requests=0)
                if req.path.endswith('/selection'):
                    result['publication']['count_scope']='selected_inputs'
                    row=next((r for r in [*result['rows'],*result['pairs']] if r['id']==selected),None)
                    if query.get('layout') == 'desk':
                        from .trade_desk import EV_METRIC, METRICS, desk_phase, direct_venue_offer, offer, phase_matches
                        paused = states.get('sportsgameodds', {}).get('reason_code') == 'sgo_charge_unresolved'
                        phase = desk_phase(query)
                        basis = query.get('basis', 'sportsbooks' if phase == 'pregame' else 'reviewed')
                        value = (offer(row, METRICS.get(basis,EV_METRIC), sportsbook_updates_paused=paused)
                                 if row and row['kind'] == 'single' and direct_venue_offer(row) else None)
                        if value and not phase_matches(row, phase, at):
                            value.update(current=False, value=None, withdrawn_from_phase=True)
                        return dict(row=value, provider_requests=0)
                    return dict(result_id=result['id'],generation=head['generation'],cursor=cursor,
                        state='removed' if row is None else 'ready' if row.get('price_current',True) else 'unavailable',
                        publication=result['publication'],assumptions=result['assumptions'],provider_requests=0,
                        captured_at=row.get('captured_at', result['captured_at']) if row else None,
                        row=None if row is None else presented(row,{r['id']:r for r in result['rows']}))
                stage=monotonic()
                if query.get('layout') == 'desk':
                    from .trade_desk import add_public_prices, add_sgo_prices, desk_phase, page as desk_page
                    def enrich(out, *, include_retained):
                        if owner.get('config', {}).get('aggregate_provider') != 'sportsgameodds' or 'sportsgameodds' not in states:
                            return
                        add_sgo_prices(db, out, result['rows'], states, at=at,
                                       include_retained=include_retained)
                        if desk_phase(query) != 'live':
                            add_public_prices(out, owner, at=at, include_retained=include_retained)
                    qualify = query.get('lines') in ('main', 'all') and (
                        query.get('browse_odds') == '1' or query.get('ranked') == '1') and options[0] != 'arbs'
                    out = desk_page(result, query, options, captured_pairs=captured_pairs, policy=policy,
                                    browsing=browsing, enrich=enrich if qualify else None)
                    if not qualify and out.get('state') == 'ready' and options[0] != 'arbs':
                        enrich(out, include_retained=query.get('last_known') == '1')
                else:
                    out = page(result, query, options=options)
                if out.get('state')=='page_changed':return out
                timings['page']=(monotonic()-stage)*1000
                from app.storage.delivery_clocks import recent
                out['delivery_clocks']=recent(db)
                out.update(cursor=cursor, generation=head['generation'], publication=dict(
                    out['publication'], **{k:v for k,v in head['facts'].items() if k in (
                        'published_at','price_seconds','total_seconds','error')}))
                return out

        result=await asyncio.to_thread(work)
        return web.json_response(result,headers={'Server-Timing': ', '.join(
            f'{name};dur={duration:.3f}' for name,duration in timings.items())})

    async def evidence_lease(req):
        from app.storage.ordinary_publication import retain
        if req.method == 'DELETE':
            lease_id=req.query.get('lease_id')
            if not lease_id or len(lease_id)>64:raise PublicRequestError('Exact lease required')
            def release():
                with connect() as db:
                    db.execute("DELETE FROM comparison_result_reference WHERE kind='lease' AND holder=%s",(lease_id,))
                return dict(released=True,provider_requests=0)
            return web.json_response(await asyncio.to_thread(release))
        body = await read_json(req)
        if not isinstance(body, dict) or set(body)-{'result_id','lease_id'} or not isinstance(body.get('result_id'), str):
            raise PublicRequestError('Exact evidence revision required')
        def work():
            with connect() as db:
                return retain(db, body['result_id'], body.get('lease_id'))
        try:
            return web.json_response(await asyncio.to_thread(work))
        except snapshots.SnapshotOperationError as exc:
            raise PublicRequestError(str(exc)) from None

    async def current_settings(req):
        from app.storage.comparison_policy import activate
        body=await read_json(req)
        if not isinstance(body,dict) or set(body)!={'assumptions','expected'}:
            raise PublicRequestError('Exact settings and prior revision required')
        try:value=assumptions(body['assumptions'])[0]
        except (ValueError,TypeError,ArithmeticError) as exc:raise PublicRequestError(str(exc)) from None
        def work():
            with connect() as db:
                selected = activate(db, value, expected=body['expected'])
            return dict(state='pending',assumptions=selected,provider_requests=0)
        try:
            return web.json_response(await asyncio.to_thread(work))
        except snapshots.SnapshotOperationError as exc:
            raise PublicRequestError(str(exc)) from None

    async def operate(req):
        options = page_options(req.query)
        body = await read_json(req)
        if not isinstance(body, dict) or set(body) - {
            "action",
            "assumptions",
            "expected",
        }:
            raise PublicRequestError("Exact snapshot operation required")
        if "assumptions" in body:
            try:
                assumptions(body["assumptions"])
            except (ValueError, TypeError, ArithmeticError) as exc:
                raise PublicRequestError(str(exc)) from None

        def work():
            with connect() as db:
                return history(
                    db,
                    page(
                        snapshots.replace(
                            db,
                            action=body.get("action"),
                            value=body.get("assumptions"),
                            expected=body.get("expected"),
                        ),
                        req.query,
                        options=options,
                    ),
                )

        try:
            return web.json_response(await asyncio.to_thread(work))
        except snapshots.SnapshotOperationError as exc:
            raise PublicRequestError(str(exc)) from None

    async def details(req):
        if not req.query.get("result_id") or not req.query.get("id"):
            raise PublicRequestError("Exact result revision and selection required")

        def work():
            with connect() as db:
                if req.query.get('lease_id'):
                    from app.storage.ordinary_publication import retain
                    retain(db, req.query['result_id'], req.query['lease_id'])
                    result=decoded(req.query['result_id'])
                else:
                    result = leased_result(db, req.query.get("result_id"))
                if result is None:
                    raise PublicRequestError("Selected snapshot expired")
                row = next(
                    (
                        r
                        for r in [*result["rows"], *result["pairs"]]
                        if r["id"] == req.query.get("id")
                    ),
                    None,
                )
                if row is None:
                    raise PublicRequestError("Selection is not in this result revision")
                # The ordinary head is an immutable union of disjoint matching
                # components. Bind inspection to that exact member's inputs.
                evidence_result = result
                if row.get('evidence_result_id'):
                    evidence_result = decoded(row['evidence_result_id'])
                    if evidence_result is None:
                        raise PublicRequestError('Selected evidence expired')
                    row=next(r for r in [*evidence_result['rows'],*evidence_result['pairs']] if r['id']==row['id'])
                inputs = snapshots.unpack(
                    db.execute(
                        "SELECT inputs FROM comparison_snapshot WHERE id=%s",
                        (evidence_result["snapshot_id"],),
                    ).fetchone()["inputs"]
                )
                ids = row.get("legs", [row["id"]])
                originals = [q for q in inputs["quotes"] if q["id"] in ids]
                by_id = {q["id"]: q for q in originals}
                refs = {}
                from app.comparison.snapshot_named_benchmark import references
                benchmark_refs=references(inputs['quotes'],inputs['references'],evidence_result['assumptions'])
                for leg in evidence_result["rows"]:
                    if leg["id"] in by_id:
                        for ref in selected_references(
                            leg, by_id[leg["id"]], benchmark_refs
                        ):
                            refs[ref["id"]] = ref
                from app.comparison.inspection_math import offer_math, offer_disclosures
                inspection = None
                desk = {}
                if row['kind'] == 'single':
                    inspection = offer_math(row)
                    inspection.update(offer_disclosures(row, evidence_result['captured_at'], originals))
                    if req.query.get('layout') == 'desk':
                        from app.storage.store import stamp
                        from .trade_desk import EV_METRIC, METRICS, offer
                        authority = (row.get('current_authority') or {}).get('price') or {}
                        reasons = authority.get('reasons', [])
                        captured_at = evidence_result['captured_at']
                        current_until = authority.get('current_until')
                        captured_current = bool(current_until and stamp(captured_at) <= stamp(current_until) and not reasons)
                        desk['desk_offer'] = offer(dict(row, price_current=captured_current,
                            current_reasons=reasons, captured_at=captured_at, evidence_result_id=evidence_result['id']),
                            METRICS.get(req.query.get('basis'), EV_METRIC))
                return dict(
                    **desk,
                    inspection=inspection,
                    result_id=result["id"],
                    evidence_result_id=evidence_result['id'],
                    snapshot_id=evidence_result["snapshot_id"],
                    captured_at=evidence_result["captured_at"],
                    assumptions=evidence_result["assumptions"],
                    row=presented(row, {r["id"]: r for r in result["rows"]}),
                    benchmark_diagnostics=evidence_result.get("benchmark_diagnostics", {}),
                    originals=originals,
                    references=list(refs.values()),
                    provider_requests=0,
                )

        return web.json_response(await asyncio.to_thread(work))

    app.router.add_get("/api/comparison-snapshot", read)
    app.router.add_get("/api/comparison-current", current_read)
    app.router.add_get("/api/comparison-current/updates", current_read)
    app.router.add_get("/api/comparison-current/fee-coverage", current_read)
    app.router.add_get("/api/comparison-current/selection", current_read)
    app.router.add_post("/api/comparison-current/lease", evidence_lease)
    app.router.add_delete("/api/comparison-current/lease", evidence_lease)
    app.router.add_post("/api/comparison-current/settings", current_settings)
    app.router.add_post("/api/comparison-snapshot", operate)
    app.router.add_get("/api/comparison-snapshot/details", details)
