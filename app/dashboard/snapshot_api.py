"""Ordinary immutable comparison snapshots; browsing never dispatches providers."""

import asyncio
from time import monotonic
from threading import RLock
from datetime import datetime
from aiohttp import web
from app.owned_work import joined_thread
from app.storage.store import connect, stamp
from app.storage import comparison_snapshot as snapshots
from app.comparison.snapshot_math import assumptions
from .local_security import read_json, PublicRequestError
from .snapshot_display import (
    comparison_groups, pregame_at, presented, ranking_value, retained_pregame, saved_pregame, scoped_result, search_index,
)


def runtime_allows_live(db):
    from app.collection.current_policy import live_enabled
    from app.collection.runtime_status import read_runtime

    return live_enabled(read_runtime(db, ordinary_authority=True)['config'])


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
    from .product_finance import visible_assumptions, visible_publication

    view, metric, offset, limit = options or page_options(query)
    if result is None:
        return dict(state="empty", defaults=visible_assumptions(assumptions()[0]), provider_requests=0)
    out = {k: v for k, v in result.items()
           if k not in ("rows", "pairs", "references", "component_slices", "benchmark_diagnostics")}
    out['defaults'] = visible_assumptions(assumptions()[0])
    if out.get('assumptions'):
        out['assumptions'] = visible_assumptions(out['assumptions'])
    if out.get('publication'):
        out['publication'] = visible_publication(out['publication'])
    if out.get('sources'):
        out['sources'] = visible_publication(out)['sources']
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

    rows = [r for r in rows if r.get('venue') != 'pinnacle' and selected(r)]
    position_count = len(rows)
    grouped = query.get("group") == "outcome"
    current = 'publication' in result
    by_id = {r["id"]: r for r in result["rows"]}
    if grouped:
        rows = comparison_groups(rows, by_id, metric, pairs=view == "arbs", current=current, qualified=view == 'ev')
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
        values = {r['id']: ranking_value(r, metric, current=current, qualified=view == 'ev') for r in rows}
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
            sum(ranking_value(r, metric, current=current, qualified=view == 'ev') is None for r in rows),
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
        value = ranking_value(row, metric, current=current, qualified=view == 'ev')
        quote['ranking'] = dict(eligible=value is not None, value=None if value is None else str(value),
            metric=metric, reason=None if value is not None else
            'metric_unavailable' if row.get(metric) is None else
            'current_authority_withdrawn' if not row.get('price_current') or row.get('current_reasons') else
            'metric_status_or_comparison_basis_unsupported')
        return quote
    out["rows"] = [dict(r, quotes=[display(q) for q in r["quotes"]]) if grouped or view == "odds" else display(r) for r in out["rows"]]
    references = [r for r in result['references'] if r.get('venue') != 'pinnacle']
    out["reference_count"] = len(references)
    coverage = {}
    for quote in (*result["rows"], *references):
        venue = quote.get("venue")
        if not venue or venue == 'pinnacle':
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
    def decoded(result_id, db, *, ordinary=False):
        nonlocal decoded_cache
        # Concurrent viewer/inspection reads share one cold decode. Otherwise
        # each can allocate the same large root and contend in Python's GC.
        with decode_lock:
            cached_id,cached_result=decoded_cache
            if cached_id==result_id:return cached_result
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
            return decoded(result_id,db,ordinary=cache)
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
        return decoded(row["id"],db,ordinary=cache)

    def saved_page(db, result, query, options):
        if result and not runtime_allows_live(db):
            result = retained_pregame(result)
        return history(db, page(result, query, options=options))

    async def read(req):
        options = page_options(req.query)

        def work():
            with connect() as db:
                result = leased_result(db, req.query.get("result_id"),cache=True)
                if req.query.get("result_id") and result is None:
                    raise PublicRequestError("Selected snapshot expired")
                return saved_page(db, result, req.query, options)

        return web.json_response(await asyncio.to_thread(work))

    from .browse_sessions import BrowseSessions
    from .desk_delivery import ReadBurst
    browsing=BrowseSessions()
    desk_reads = ReadBurst()
    app.on_cleanup.append(desk_reads.close)

    async def current_read(req):
        timings = {}
        submitted = monotonic()
        is_fee_census = req.path.endswith('/fee-coverage')
        is_updates = req.path.endswith('/updates')
        is_selection = req.path.endswith('/selection')
        query = dict(req.query)
        query.setdefault('metric', 'minimum_return_percent' if query.get('view') == 'arbs' else 'conditional_return_percent')
        query.setdefault('group', 'outcome')
        is_desk = query.get('layout') == 'desk'
        if is_desk:
            from .trade_desk import desk_phase
            query['phase'] = desk_phase(query, current=True)
        options = None if is_fee_census else page_options(query)
        current_desk = (options is not None and options[0] != 'arbs' and query.get('layout') == 'desk'
                        and (query.get('browse_odds') == '1' or query.get('ranked') == '1')
                        and query.get('last_known') != '1' and not req.path.endswith('/selection'))
        from app.storage import ordinary_publication as live
        from app.storage import current_aggregate_desk
        from app.fees.schedule_lifecycle import revision as fee_revision
        from app.storage.store import hashed
        from app.storage.current_games import utc

        def exact_selection(result, selected, native_contract, aggregate_contract):
            pairs = [row for row in result['pairs'] if row['id'] == selected]
            ids = {selected, *(leg for pair in pairs for leg in pair['legs'])}
            contracts = {contract for contract in (native_contract, aggregate_contract) if contract}
            rows = [row for row in result['rows'] if row['id'] in ids
                    or contracts and row['current_authority']['price'].get('dependency') in contracts]
            if is_desk and rows:
                occurrences = {(row['game_key'], row['start_at']) for row in rows}
                rows = [row for row in result['rows'] if (row['game_key'], row['start_at']) in occurrences]
            return dict(result, rows=rows, pairs=pairs)

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
            started = monotonic()
            timings['queue'] = (started - submitted) * 1000
            from app.collection.current_policy import live_enabled
            with connect() as db, db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                db.execute('SET LOCAL jit=off')
                head = live.status(db)
                at = stamp(utc())
                owner, states = live.authority(db, at=at,
                    include_diagnostics=is_fee_census and query.get('funnel') == '1')
                provider = live.aggregate_provider(owner=owner)
                settings = live.current_settings(db)
                epoch = str(db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch'])
                live_available = live_enabled(owner.get('config', {}))
                if not live_available:
                    query['phase'] = 'pregame'
                if is_desk:
                    features = dict(features=dict(live_enabled=live_available), phase=query['phase'])
                else:
                    features = {}
                timings['authority']=(monotonic()-started)*1000
                update_cursor = None
                selected = query.get('id') if is_selection else None
                if is_selection and (not selected or len(selected) > 128):
                    raise PublicRequestError('Exact selection required')
                live_contract = (selected.removeprefix('native-current:')
                                 if selected and selected.startswith('native-current:') else None)
                aggregate_contract = (selected.removeprefix(current_aggregate_desk.PREFIX)
                    if selected and selected.startswith(current_aggregate_desk.PREFIX) else None)
                if is_desk and not is_fee_census and not is_selection:
                    from .desk_updates import cursor as desk_cursor
                    stage = monotonic()
                    update_cursor = desk_cursor(db, at=at, phase=query['phase'], head=head, owner=owner,
                        states=states, settings=settings, epoch=epoch, live_enabled=live_available)
                    timings['desk_revision'] = (monotonic()-stage)*1000
                    if is_updates:
                        return dict(changed=query.get('after') != update_cursor, cursor=update_cursor,
                                    poll_after_ms=6500, generation=head['generation'], provider_requests=0,
                                    **features)
                    features['update_cursor'] = update_cursor
                policy = live.policy_identity(provider)
                stage = monotonic()
                cold = decoded_cache[0] != head['result_id']
                result = decoded(head['result_id'], db, ordinary=True) if head['result_id'] else None
                if head['result_id'] and result is None:
                    raise web.HTTPServiceUnavailable(reason='Published prices unavailable')
                timings['cold_decode' if cold else 'cached_decode'] = (monotonic()-stage)*1000
                stage = monotonic()
                if result is not None and not is_fee_census and not live_available:
                    result = scoped_result(result, [row for row in result['rows'] if pregame_at(row, at)])
                if result is not None and is_selection and is_desk:
                    result = exact_selection(result, selected, live_contract, aggregate_contract)
                overlay_events = None
                public_summary = query.get('summary') == '1'
                if current_desk and public_summary and query.get('phase') == 'pregame':
                    from .desk_scope import pregame_search
                    games, overlay_events = pregame_search(db, result, query, at)
                    if result is not None and games is not None:
                        result = scoped_result(result, [row for row in result['rows'] if row['game_key'] in games])
                lifecycle_rows = result['rows'] if result else ()
                dependency_result = result
                # Held pregame prices still have their lifecycle and original
                # evidence. They cannot rank, so omit calculation dependencies.
                if result is not None and current_desk and public_summary:
                    if query['phase'] == 'pregame' and (
                            not owner.get('healthy') or not owner.get('active') or owner.get('global_stopped')):
                        dependency_result = None
                    elif owner.get('active') and not owner.get('global_stopped'):
                        relevant = [row for row in result['rows']
                                    if (deadline := row['current_authority']['price'].get('current_until'))
                                    and stamp(deadline) >= at]
                        dependency_result = scoped_result(result, relevant)
                        if query.get('phase') != 'pregame':
                            result = dependency_result
                            relevant_games = {row['game_key'] for row in relevant}
                            lifecycle_rows = [row for row in lifecycle_rows if row['game_key'] in relevant_games]
                timings['scope'] = (monotonic()-stage)*1000
                stage = monotonic()
                deps, dependency_revision = (live.published_dependencies(db, dependency_result, provider=provider, at=at)
                                             if dependency_result else ({}, None))
                timings['dependencies'] = (monotonic()-stage)*1000
                # Legacy pagination still binds published dependencies.
                cursor = update_cursor or hashed([head['generation'], dependency_revision, epoch, policy, settings['revision'],
                    fee_revision(owner.get('fee_lifecycle')),
                    owner.get('fee_products'),
                    owner.get('active'), owner.get('healthy'), owner.get('global_stopped'), owner.get('paused_sources'),
                    owner.get('calculations', {}).get('board'),
                    {k: [s.get('state'), s.get('reason_code'), s.get('observed_sports')] for k,s in states.items()},
                    int(at.timestamp())//2 if head['facts'].get('next_boundary') and at >= stamp(head['facts']['next_boundary']) else None,
                    live_available])
                if is_updates:
                    return dict(schema=live.VERSION, cursor=cursor,
                        changed=req.query.get('after') != cursor,
                        generation=head['generation'], result_id=head['result_id'],
                        publication=head['facts'], poll_after_ms=2000, provider_requests=0)
                direct_desk = provider == 'sportsgameodds' and options is not None and options[0] != 'arbs' and query.get('layout') == 'desk'
                native_desk = direct_desk and (current_desk or live_contract)
                aggregate_desk = direct_desk and (current_desk or aggregate_contract)
                if not head['result_id']:
                    if is_fee_census:
                        empty = dict(rows=[], publication=dict(sources=states, read_at=at.isoformat()))
                        inventory_deps = live.dependencies(db, provider=provider)
                        return dict(fee_census(db, empty, inventory_deps, owner, states, at, policy=policy, epoch=epoch, settings=settings),
                            state='initializing', cursor=cursor,
                            generation=head['generation'], result_id=None, provider_requests=0)
                    from app.storage.ordinary_projection import publication_runtime
                    initializing = dict(state='initializing', sources=states, read_at=at.isoformat(),
                                        current_prices=0, retained_prices=0, data_runtime=publication_runtime(owner))
                    result = dict(id=None, rows=[], pairs=[], games=[], publication=initializing,
                                  captured_at=at.isoformat(), assumptions=settings)
                    if not (native_desk or aggregate_desk or is_selection and is_desk):
                        fallback = game_capture_link(db, query, allow_live=live_available)
                        return dict(state='initializing', publication=initializing, **features,
                            cursor=cursor, generation=head['generation'], rows=[], total=0, provider_requests=0,
                            **({'retained_game': fallback} if fallback else {}))
                if not is_fee_census and query.get('layout')!='desk' and not req.path.endswith('/selection') and (
                        query.get('expected_cursor') and query['expected_cursor'] != cursor or
                        options[2] and not query.get('expected_cursor')):
                    return dict(state='page_changed', reason='comparison_changed_restart_pagination',
                        cursor=cursor, generation=head['generation'], result_id=head['result_id'],
                        restart_offset=0, rows=[], provider_requests=0)
                stage=monotonic()
                if is_selection and not is_desk:
                    result = exact_selection(result, selected, live_contract, aggregate_contract)
                captured_pairs = ([pair for pair in result['pairs'] if snapshots.exact_arb_pair(pair)]
                                  if is_fee_census or options[0] == 'arbs' else ())
                frames = (live.sportsbook_frames(db, at) if dependency_result and any(
                    (r.get('sportsbook_baseline') or {}).get('indicative') for r in dependency_result['rows'])
                    and owner.get('config', {}).get('aggregate_provider') == 'sportsgameodds' else ())
                from app.storage.ordinary_projection import event_owners, publication_runtime
                from .trade_desk import browse_retained
                browsing_odds = query.get('browse_odds') == '1'
                retained_fallback = (browsing_odds and not public_summary
                                     and browse_retained(publication_runtime(owner)))
                retain_sportsbook_ev = (browsing_odds and not public_summary
                                        and query.get('layout') == 'desk' and options is not None
                                        and options[0] != 'arbs' and query.get('basis', 'sportsbooks') == 'sportsbooks')
                event_facts = event_owners(db, lifecycle_rows, at=at) if is_desk else None
                if head['result_id']:
                    result = live.project(result, deps, owner, states, at=at, policy=policy, epoch=epoch,
                                          settings=settings, sportsbook_frames=frames,
                                          current_desk=current_desk and not retained_fallback,
                                          retain_sportsbook_ev=retain_sportsbook_ev,
                                          event_facts=event_facts,
                                          lifecycle_rows=lifecycle_rows if is_desk else None)
                timings['projection']=(monotonic()-stage)*1000
                from app.storage.sportsgameodds_reference import EventInputs
                sgo_inputs = EventInputs(db)
                if native_desk:
                    from app.storage.current_native_desk import overlay
                    stage=monotonic()
                    from .trade_desk import desk_phase
                    result = overlay(db, result, owner, states, at=at, contract=live_contract,
                                     phase=desk_phase(query) or 'pregame', sgo_inputs=sgo_inputs,
                                     event_ids=overlay_events)
                    timings['native_desk']=(monotonic()-stage)*1000
                if aggregate_desk:
                    stage = monotonic()
                    result = current_aggregate_desk.overlay(db, result, owner, states, at=at, phase=query['phase'],
                                                            contract=aggregate_contract, sgo_inputs=sgo_inputs,
                                                            event_ids=overlay_events)
                    timings['aggregate_desk'] = (monotonic()-stage)*1000
                if not head['result_id'] and not result['rows'] and not is_selection:
                    fallback = game_capture_link(db, query, allow_live=live_available)
                    return dict(state='initializing', publication=result['publication'], cursor=cursor, **features,
                                generation=head['generation'], rows=[], total=0, provider_requests=0,
                                **({'retained_game': fallback} if fallback else {}))
                if is_fee_census:
                    inventory_deps = live.dependencies(db, provider=provider)
                    return dict(fee_census(db, result, inventory_deps, owner, states, at, pairs=captured_pairs,
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
                        basis = query.get('basis', 'reviewed')
                        value = (offer(row, METRICS.get(basis,EV_METRIC), sportsbook_updates_paused=paused)
                                 if row and row['kind'] == 'single' and direct_venue_offer(row) else None)
                        if value and not phase_matches(row, phase, at):
                            return dict(row=None, withdrawn_from_phase=True,
                                        reason=row.get('game_state_reason') or 'phase_price_unavailable', provider_requests=0)
                        inspection = (row.get('native_inspection') or row.get('aggregate_inspection')) if value else None
                        evidence = dict(captured_at=row['captured_at'], inspection=inspection) if inspection else None
                        return dict(row=value, evidence=evidence, provider_requests=0, **features)
                    return dict(result_id=result['id'],generation=head['generation'],cursor=cursor,
                        state='removed' if row is None else 'ready' if row.get('price_current',True) else 'unavailable',
                        publication=result['publication'],assumptions=result['assumptions'],provider_requests=0,
                        captured_at=row.get('captured_at', result['captured_at']) if row else None,
                        row=None if row is None else presented(row,{r['id']:r for r in result['rows']}))
                stage=monotonic()
                if query.get('layout') == 'desk':
                    from .trade_desk import add_public_prices, add_sgo_prices, desk_phase, page as desk_page
                    def enrich(out, *, include_retained, mark_retained=False):
                        if owner.get('config', {}).get('aggregate_provider') != 'sportsgameodds' or 'sportsgameodds' not in states:
                            return
                        quote_states = states
                        if retained_fallback:
                            aggregate = dict(states['sportsgameodds'], state='unavailable')
                            quote_states = dict(states, sportsgameodds=aggregate)
                        add_sgo_prices(db, out, result['rows'], quote_states, at=at,
                                       include_retained=include_retained, mark_retained=mark_retained, sgo_inputs=sgo_inputs)
                        if desk_phase(query) != 'live':
                            add_public_prices(out, owner, at=at, include_retained=include_retained,
                                              mark_retained=mark_retained,
                                              include_history=not public_summary or bool(query.get('game_key')))
                    out = desk_page(result, query, options, captured_pairs=captured_pairs, policy=policy,
                                    browsing=browsing, enrich=enrich, published_only=True, event_facts=event_facts)
                    if not out.get('rows') and not out.get('retained_game'):
                        fallback = game_capture_link(db, query, allow_live=live_available)
                        if fallback:
                            out['retained_game'] = fallback
                else:
                    out = page(result, query, options=options)
                out.update(features)
                if out.get('state')=='page_changed':return out
                timings['page']=(monotonic()-stage)*1000
                stage = monotonic()
                if is_desk:
                    from .desk_updates import refresh_at
                    out['refresh_at'] = refresh_at(out, at)
                from app.storage.delivery_clocks import recent
                if not (is_desk and public_summary):
                    out['delivery_clocks'] = recent(db)
                timings['metadata'] = (monotonic()-stage)*1000
                out.update(cursor=cursor, generation=head['generation'], publication=dict(
                    out['publication'], **{k:v for k,v in head['facts'].items() if k in (
                        'published_at','price_seconds','total_seconds','error')}))
                return out

        from .desk_delivery import common_page, encode, packet_response, timing_header

        async def read_work():
            value = await joined_thread(__name__, 'desk_read_after_cancellation', work)
            return (value, dict(timings)), float('inf'), 0

        if is_updates and is_desk and set(req.query) <= {'layout', 'phase', 'after'}:
            (result, saved_timings), shared = await desk_reads.read(('updates', query['phase']), read_work, reuse=0)
            result = dict(result, changed=query.get('after') != result['cursor'])
            headers = {'Server-Timing': 'desk_shared;dur=0' if shared else timing_header(saved_timings)}
            return web.json_response(result, headers=headers)

        if (is_desk and query.get('summary') == '1' and not
                (is_updates or is_selection or is_fee_census)):
            def public_packet():
                started = monotonic()
                result = work()
                observed = (result.get('publication') or {}).get('read_at') or utc()
                stage = monotonic()
                packet, expires, size = encode(result, at=stamp(observed), started=started)
                timings['encode'] = (monotonic() - stage) * 1000
                return (packet, dict(timings)), expires, size

            async def produce():
                return await joined_thread(__name__, 'desk_read_after_cancellation', public_packet)

            key = common_page(query, options)
            (packet, saved_timings), shared = await desk_reads.read(key, produce)
            return packet_response(req, packet, saved_timings, shared=shared)

        (result, saved_timings), _ = await desk_reads.read(None, read_work)
        return web.json_response(result, headers={'Server-Timing': timing_header(saved_timings)})

    def game_capture_link(db, query, *, allow_live):
        if query.get('layout') != 'desk' or query.get('browse_odds') != '1' or not query.get('game_capture'):
            return None
        from .replay_api import retained_capture

        result_id, game_key = query['game_capture'], query.get('game_key')
        result = retained_capture(db, result_id, game_key)
        if not result or not (allow_live or retained_pregame(result)['rows']):
            return None
        return dict(game_key=game_key, result_id=result_id, captured_at=result['captured_at'])

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
        from .product_finance import visible_assumptions
        body=await read_json(req)
        if not isinstance(body,dict) or set(body)!={'assumptions','expected'}:
            raise PublicRequestError('Exact settings and prior revision required')
        try:value=assumptions(body['assumptions'])[0]
        except (ValueError,TypeError,ArithmeticError) as exc:raise PublicRequestError(str(exc)) from None
        def work():
            with connect() as db:
                selected = activate(db, value, expected=body['expected'])
            return dict(state='pending',assumptions=visible_assumptions(selected),provider_requests=0)
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
                result = snapshots.replace(
                    db,
                    action=body.get("action"),
                    value=body.get("assumptions"),
                    expected=body.get("expected"),
                    product=True,
                )
                return saved_page(db, result, req.query, options)

        try:
            return web.json_response(await asyncio.to_thread(work))
        except snapshots.SnapshotOperationError as exc:
            raise PublicRequestError(str(exc)) from None

    async def details(req):
        if not req.query.get("result_id") or not req.query.get("id"):
            raise PublicRequestError("Exact result revision and selection required")
        stake = None
        if 'stake' in req.query:
            from .trade_desk import funding
            try:
                stake = funding(req.query['stake'])
            except (ValueError, ZeroDivisionError):
                raise PublicRequestError('Enter a stake between $0.01 and $1,000,000') from None

        def work():
            with connect() as db:
                if req.query.get('lease_id'):
                    from app.storage.ordinary_publication import retain
                    retain(db, req.query['result_id'], req.query['lease_id'])
                    result=decoded(req.query['result_id'], db)
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
                    evidence_result = decoded(row['evidence_result_id'], db)
                    if evidence_result is None:
                        raise PublicRequestError('Selected evidence expired')
                    row=next(r for r in [*evidence_result['rows'],*evidence_result['pairs']] if r['id']==row['id'])
                capture_at = row.get('captured_at') or evidence_result.get('captured_at')
                legs = set(row['legs']) if row.get('kind') == 'pair' else None
                entries = ([leg for leg in evidence_result['rows'] if leg['id'] in legs]
                           if legs is not None else [row])
                if not entries or not all(saved_pregame(leg, capture_at) for leg in entries):
                    if not runtime_allows_live(db):
                        raise PublicRequestError('Selection is not in this result revision')
                pair_details = req.query.get('layout') == 'desk' and snapshots.exact_arb_pair(row)
                if stake is not None or pair_details:
                    if not snapshots.exact_arb_pair(row) or 'default_funding_result' not in row:
                        raise PublicRequestError('Exact saved arbitrage pair required')
                    from app.comparison.ordinary_arb import current_payoff
                    by_id = {leg['id']:leg for leg in evidence_result['rows'] if leg['id'] in row['legs']}
                    legs = [dict(by_id[leg], captured_at=evidence_result['captured_at'],
                                 game_state=by_id[leg]['current_authority']['price']['lifecycle']['state'])
                            for leg in row['legs']]
                    payoff = row['default_funding_result'] if stake is None else current_payoff(row, legs, stake)
                    out = dict(id=row['id'], evidence_result_id=evidence_result['id'], **payoff, provider_requests=0)
                    if pair_details:
                        from .trade_desk import offer
                        out['settlement_payouts'] = row['before_fees'].get('settlement_payouts')
                        out['offers'] = [offer(dict(leg, price_current=True, evidence_result_id=evidence_result['id']))
                                         for leg in legs]
                    return out
                inputs = snapshots.unpack(
                    db.execute(
                        "SELECT inputs FROM comparison_snapshot WHERE id=%s",
                        (evidence_result["snapshot_id"],),
                    ).fetchone()["inputs"]
                )
                ids = row.get("legs", [row["id"]])
                from .product_finance import visible_assumptions, visible_original, visible_row

                originals = [visible_original(q) for q in inputs["quotes"]
                             if q["id"] in ids and q["venue"] != 'pinnacle']
                from app.comparison.inspection_math import offer_math, offer_disclosures
                inspection = None
                desk = {}
                if row['kind'] == 'single':
                    row = visible_row(row)
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
                    assumptions=visible_assumptions(evidence_result["assumptions"]),
                    row=presented(row, {r["id"]: r for r in result["rows"]}),
                    originals=originals,
                    references=[],
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
