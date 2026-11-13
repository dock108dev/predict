"""One bounded repeatable-read readiness capture; no durable derived state.

Caller supplies the operational config/authority. This module neither initializes
collection nor loads credentials, quota owners, settings writers or recovery.
"""
from copy import deepcopy
from itertools import product
from app.comparison.sporting_scope import sport as league_sport, supported as predicate_supported

from app.comparison.current_dependencies import digest, instant, encoded, encoded_size
from app.comparison.scanner_readiness import Selection, assemble, check, MAX_INSTRUMENTS, POLICY_REVISION, _count
from app.comparison.readiness_inputs import instrument
from app.collection.current_policy import GRANT, aggregate_scope, native_scope, native_markets
from app.storage.store import Store, hashed
from app.storage.current_rows import CurrentRowStore, contract_id, native_offer_ask_counts
from app.storage.comparison_board import ReadContext


def capture_reservation(db):
    from .board_capture import capture_batches
    from app.comparison.scanner_readiness import MAX_BYTES
    groups=capture_batches(db)
    # Measure each event once, then sum complete peer components. The previous
    # three queries per component repeatedly scanned the same source tables
    # even when admission would subsequently defer the scanner.
    sizes={r['event_id']:int(r['n']) for r in db.execute('''WITH offers AS MATERIALIZED (
            SELECT c.event_id,count(*) rows,sum(octet_length(c.facts::text)+octet_length(o.facts::text)) bytes
            FROM current_contract c JOIN current_offer o ON o.contract_id=c.id GROUP BY c.event_id)
            SELECT e.id event_id,offers.bytes+offers.rows*octet_length(e.facts::text) n
            FROM offers JOIN current_event e ON e.id=offers.event_id''')}
    depths={r['event_id']:int(r['n']) for r in native_offer_ask_counts(db)}
    for row in db.execute('''SELECT c.event_id,count(*) n FROM current_depth d JOIN current_contract c ON c.id=d.contract_id
        WHERE side='asks' GROUP BY c.event_id'''):
        event_id=row['event_id']
        depths[event_id]=depths.get(event_id,0)+row['n']
    maximum=max((sum(sizes.get(eid,0)*8+depths.get(eid,0)*2048 for eid in ids) for ids in groups),default=0)
    # Whole readiness output stays bounded; expensive source/finance preparation
    # owns only one complete possible-peer component at a time.
    return maximum+MAX_BYTES*8+16*1024*1024


def read(db, **kwargs):
    return capture(db, **kwargs)[0]


def _selected_components(db, planned, selection, scopes, wanted):
    """Keep complete possible-peer components for selected execution and references."""
    offered = db.execute('''SELECT DISTINCT c.event_id, c.venue, e.competition AS league,
        c.facts#>>'{market_identity,family}' AS family, c.facts#>>'{market_identity,period}' AS period
        FROM current_contract c JOIN current_event e ON e.id=c.event_id
        JOIN current_offer o ON o.contract_id=c.id
        WHERE c.venue=ANY(%s) AND e.competition=ANY(%s)''',
        ([*selection.venues, 'pinnacle'], list(selection.leagues))).fetchall()
    exact = {(s['venue'], s['league'], s['market'], s['period']) for s in scopes}
    execution = {row['event_id'] for row in offered if
        (row['venue'], row['league'],
         'winner' if row['family'] in ('moneyline', 'team_binary') else row['family'], row['period']) in exact}
    reference = {row['event_id'] for row in offered if row['venue'] == 'pinnacle' and
        league_sport(row['league']) in selection.sports and 'winner' in selection.markets and
        row['period'] in selection.periods}
    member_ids = {hashed(member) for member in wanted} if wanted is not None else None
    for ids in planned:
        include_execution = execution.intersection(ids) and (member_ids is None or member_ids.intersection(ids))
        if include_execution or reference.intersection(ids):
            yield ids, bool(include_execution)


def capture(db, *, config, at, selection=None, authority=None, evaluations=(), source_status=None, cache=None, members=None,
            _shared_facts=False, resource_guard=None, retain_capacity_gaps=False, component_proofs=False):
    """Existing authority is required explicitly; config vocabulary is not support.

    Do not pass an owner connection without a READ ONLY transaction. All selected
    scopes, including empty/unsupported ones, survive filtering in the response.
    """
    from app.collection.current_policy import validate
    if type(_shared_facts) is not bool:
        raise ValueError('readiness_shared_facts_invalid')
    config = validate(config)
    default_selection = Selection()
    selection = selection or default_selection
    instant(at)
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        # One shared MVCC capture includes bounded ladders. Reusing it avoids a
        # second full-table capture and one depth roundtrip for every event.
        from .scanner_publication import current_revision
        from .board_capture import capture_batches
        from .current_games import engine_binding
        proof=current_revision(db)
        reserve=capture_reservation(db) if resource_guard is not None else 0
        if resource_guard is not None:resource_guard(reserve)
        frame=dict(epoch=proof['epoch'],revision=proof['current_rows_revision'],records=[],
            source_status={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()})
        engine=engine_binding()
        # Count exact discovered contracts independently of offered-price rows.
        discovered = db.execute('''SELECT c.id, c.venue, e.facts->>'competition' league,
            c.facts->'market_identity'->>'family' family,
            c.facts->'market_identity'->>'period' period, (o.contract_id IS NOT NULL) offered
            FROM current_contract c JOIN current_event e ON e.id=c.event_id
            LEFT JOIN current_offer o ON o.contract_id=c.id WHERE e.scheduled_start::timestamptz>%s::timestamptz ORDER BY c.id''',(at,)).fetchall()
        if len(discovered) > MAX_INSTRUMENTS:
            raise ValueError('readiness_contract_capacity')
        books = CurrentRowStore(db).native_offer_books()
        from app.fees.product_schedules import read_all, revision as fee_revision
        fee_states = read_all(db)
        fee_revisions = {key:fee_revision(state,publication=True) for key,state in sorted(fee_states.items())}
        statuses = deepcopy(frame['source_status'] if source_status is None else source_status)
        # ReadContext uses precisely this MVCC snapshot. It does no acquisition.
        scopes = scope_inventory(selection, config, authority)
        lookup = {s['key']: s for s in scopes}
        instruments, failures, shared_references, financial_inputs = [], [], {}, {}
        retained_input_bytes = 0
        # Resolve current membership globally before selecting any expensive
        # preparation. A new conflicting peer can invalidate an unchanged leg.
        wanted=None
        if members is not None:
            if not isinstance(members,tuple) or not 1<=len(members)<=32 or any(
                    not isinstance(m,tuple) or len(m)!=2 or any(not isinstance(v,str) or not v or len(v)>256 for v in m) for m in members):
                raise ValueError('readiness_selected_members_invalid')
            wanted=set(members)
        planned=capture_batches(db)
        selected = (_selected_components(db, planned, selection, scopes, wanted)
                    if wanted is not None or selection != default_selection else ((ids, True) for ids in planned))
        def components():
            for ids, include_execution in selected:
                part=CurrentRowStore(db).capture(include_depth=False,event_ids=ids)
                frame['records'].extend(r for r in part['records'] if r['quote']['venue']=='pinnacle')
                if not include_execution:
                    continue
                context=ReadContext(Store(db),at=at,frame=part)
                for rows in context.prepared['groups']:
                    if not any(r['quote']['venue']!='pinnacle' for r in rows):continue
                    if wanted is not None and not wanted.intersection((r['quote']['source']['provider'],r['quote']['source']['native_event_id']) for r in rows):continue
                    yield context,rows,ids
        groups=components() if any(s['supported'] for s in scopes) else ()
        from app.storage.scanner_preparation import PreparationCache, boundaries, _freeze_fact
        registry_owner = cache if cache is not None else PreparationCache(max_entries=1)
        registry, registry_boundary = registry_owner.registry(at=at)
        revalidation = [registry_boundary] if registry_boundary else []
        used_keys = set()
        financial_events = {}
        for context,rows,ids in groups:
            if not any(r['quote']['venue'] in selection.venues for r in rows):
                continue
            from app.comparison.calculation_control import checkpoint
            checkpoint()
            venues = {v for r in rows for v in (r['quote']['venue'], r['quote']['source']['provider'])}
            selected_books = [books[id_] for id_ in sorted({contract_id(r) for r in rows}) if id_ in books]
            key = digest(dict(epoch=context.epoch, engine=context.engine, registry=registry,
                readiness_policy=POLICY_REVISION,
                rows=rows, books=selected_books, fees=fee_revisions, selection=selection.to_dict(), config=config, authority=authority,
                statuses={venue:{k:statuses.get(venue, {}).get(k) for k in ('state','reason_code')} for venue in sorted(venues)}))
            used_keys.add(key)
            prepared = None if cache is None else (
                cache.get_shared(key, at=at) if _shared_facts else cache.get(key, at=at))
            if prepared is None:
                prepared = _prepare_group(context, rows, lookup, statuses, books, at, fee_states=fee_states)
                until = None
                if not prepared['failures']:
                    # Include clocks which were future/conflicting at admission,
                    # plus inactive registry starts absent from attached models.
                    future = [i['expires_at'] for i in prepared['instruments']]
                    future.extend([registry_boundary] if registry_boundary else [])
                    future.extend(value.isoformat() for value in boundaries(rows))
                    future.extend(value.isoformat() for value in boundaries(prepared['financial_inputs']))
                    for row in rows:
                        future.append(row['event']['scheduled_start'])
                        future.extend(row['quote']['times'][k] for k in ('source_at','received_at','projected_at')
                            if row['quote']['times'].get(k))
                        future.extend(row['quote']['provider_clocks'][k] for k in ('book','market')
                            if row['quote'].get('provider_clocks', {}).get(k))
                    for book in selected_books:
                        future.extend(book[k] for k in ('source_at','received_at') if book.get(k))
                    future = [value for value in future if instant(value) > instant(at)]
                    if future:
                        prepared['revalidate_at'] = min(future, key=instant)
                        for value in prepared['instruments']:
                            value['expires_at'] = min(value['expires_at'], prepared['revalidate_at'], key=instant)
                        until = prepared['revalidate_at']
                if _shared_facts:
                    prepared = _freeze_fact(prepared)
                if cache is not None and until is not None:
                    cache.put(key, prepared, at=at, until=until)
            if prepared.get('revalidate_at'):
                revalidation.append(prepared['revalidate_at'])
            instruments.extend(prepared['instruments'])
            failures.extend(prepared['failures'])
            financial_inputs.update(prepared['financial_inputs'])
            shared_references.update(prepared['references'])
            if component_proofs and prepared['financial_inputs']:
                financial_events.update(dict.fromkeys(prepared['financial_inputs'],tuple(sorted(ids))))
            retained_input_bytes += prepared['input_bytes']
            if resource_guard is not None:resource_guard(reserve+retained_input_bytes*8)
            if retained_input_bytes > 64 * 1024 * 1024:
                raise RuntimeError('scanner_financial_capture_capacity')
        if cache is not None and members is None:
            cache.prune(used_keys)
        for scope in scopes:
            contracts = [d for d in discovered if scope['sport']==league_sport(d['league']) and d['venue'] == scope['venue'] and d['league'] == scope['league'] and
                         d['family'] in (('moneyline', 'team_binary') if scope['market'] == 'winner' else (scope['market'],)) and d['period'] == scope['period']]
            scope['discovery'] = dict(contracts=_count(len(contracts), len(contracts), 'contracts', scope['key']),
                offered_contracts=_count(sum(d['offered'] for d in contracts), len(contracts), 'contracts', scope['key']),
                provenance='current_contract LEFT JOIN current_offer')
            scope['source_status'] = deepcopy(statuses.get(scope['venue'], {}))
            code = scope['source_status'].get('reason_code')
            if code in ('aggregate_transport_uncertain', 'ambiguous_dispatch_unresolved'):
                scope['check'] = check([*scope['check']['reason_codes'], code])
            if scope['source_status'].get('state') in ('failed', 'error'):
                scope['check'] = check([*scope['check']['reason_codes'], 'source_failed'])
            if any(scope['key'] in f['scopes'] for f in failures):
                # Explicit failed occurrence identities accompany a conservative
                # scope gap. Never silently claim a complete checked universe.
                scope['check'] = check([*scope['check']['reason_codes'], 'readiness_check_failed'])
        revision = digest(dict(rows=str(frame['revision']), config=config, engine=engine,
                               source_status=statuses, headers=list(books.values()), fees=fee_revisions))
        from app.comparison.scanner_projection import MAX_OCCURRENCES, MAX_PAIRS as MAX_SCANNER_PAIRS
        options = (dict(pair_limit=MAX_SCANNER_PAIRS, occurrence_limit=MAX_OCCURRENCES,
                        retain_capacity_gaps=True, transport_limit=None)
                   if retain_capacity_gaps else {})
        result = assemble(instruments, selection=selection, at=at, epoch=str(frame['epoch']),
                          input_revision=revision, scopes=scopes, evaluations=evaluations, **options)
        witnesses, instrument_witnesses = {}, {}
        if component_proofs:
            from .scanner_component import capture as component_revision, identity_index, native_witnesses
            by_events = {}
            for pair in result['pairs']:
                if pair['input_check']['state']=='ready':
                    for leg in pair['legs']:
                        if leg in financial_events:
                            by_events.setdefault(financial_events[leg],set()).add(leg)
            if by_events:
                index = identity_index(db)
                for ids, legs in by_events.items():
                    direct = {leg:contract_id(financial_inputs[leg]) for leg in legs if financial_inputs[leg].get('native_execution')}
                    if direct:
                        revisions = native_witnesses(db, ids, sorted(set(direct.values())), index=index)
                        for leg, contract in sorted(direct.items()):
                            key = hashed([ids,[contract]])
                            witnesses[key] = dict(events=list(ids),contracts=[contract],revision=revisions[contract])
                            instrument_witnesses[leg] = key
                    others = legs.difference(direct)
                    if others:
                        key = hashed([ids,None])
                        witnesses[key] = dict(events=list(ids),revision=component_revision(db,ids,index=index))
                        instrument_witnesses.update(dict.fromkeys(others,key))
        result['failed_occurrences'] = sorted({f['occurrence'] for f in failures} | set(result.get('failed_occurrences', ())))
        result['engine_binding'] = engine
        from app.comparison.scanner_readiness import clock_reasons
        selected_reference_rows = [r for r in frame['records'] if r['quote']['venue']=='pinnacle' and
            r['event']['competition'] in selection.leagues and league_sport(r['event']['competition']) in selection.sports and
            'winner' in selection.markets and r['market_identity']['period'] in selection.periods]
        n = len(selected_reference_rows)
        result['reference_sources'] = [dict(venue='pinnacle', role='reference_only',
            source_status=deepcopy(statuses.get('pinnacle', dict(state='unknown',reason_code='reference_transport_status_unknown'))),
            observed_originals=_count(n, n, 'originals', 'selected_reference_only'),
            fresh_originals=_count(sum(not clock_reasons(r['quote']['times'].get('source_at'), r['quote']['times'].get('received_at'), instant(at), 1800, 'reference') for r in selected_reference_rows), n, 'originals', 'selected_reference_only'))]
        result['references'] = shared_references
        from app.comparison.scanner_readiness import MAX_BYTES
        if not retain_capacity_gaps:
            from app.comparison.readiness_encoding import transport_size
            if transport_size(result)>MAX_BYTES:
                raise ValueError('readiness_response_capacity')
        # Transport sharing does not discount the expanded in-memory frame.
        if resource_guard is not None:
            resource_guard(reserve+retained_input_bytes*8+max(0,encoded_size(result)*8-MAX_BYTES*8))
        # Values were individually encoded before entering detached preparation
        # storage. Include every escaped key, colon, comma and the outer braces;
        # the extra final comma makes this conservative without serializing
        # the full input map again. assemble has already refused duplicate IDs.
        input_bytes_bound = 2 + retained_input_bytes + sum(len(encoded(key)) + 2 for key in financial_inputs)
        if input_bytes_bound > 64 * 1024 * 1024:
            raise RuntimeError('scanner_financial_capture_capacity')
        return result, financial_inputs, dict(current_rows_revision=frame['revision'],
            publication_proof=proof,
            component_witnesses=witnesses, instrument_witnesses=instrument_witnesses,
            input_bytes_bound=input_bytes_bound,
            revalidate_at=min(revalidation,key=instant,default=None),
            preparation_cache=None if cache is None else cache.stats())


def _prepare_group(context, rows, lookup, statuses, books, at, *, fee_states=None):
    """One occurrence through the existing producer/model owners exactly once."""
    from app.dashboard.current_contract import quotes_of
    from app.comparison.current_dependencies import references
    from app.comparison.scanner_native import NativeEvidenceError, VENUES, model
    from app.fees.product_schedules import for_offer
    occurrence = 'current-occurrence:' + digest(rows[0]['market_identity']['event'])
    instruments, failures, shared, inputs, size = [], [], {}, {}, 0
    by_contract = {contract_id(row):row for row in rows}
    fee_reviews = {venue:for_offer(fee_states, dict(venue=venue), instant(at)) for venue in VENUES}
    try:
        # No second catalog-only normalization. The supplied group belongs to
        # this fresh ReadContext, and the ordinary bundles adapter remains owner.
        for bundle in context.bundles(occurrence_rows=rows, cache=False, _readiness_only=True):
            state = bundle['state_inputs']
            for event in state['events']:
                for group in event['groups']:
                    for outcome in group['outcomes']:
                        for quote in quotes_of(outcome):
                            key = digest(dict(venue=quote['venue'], sport=league_sport(event['league']), league=event['league'],
                                market=group['market'], period=group['period']))
                            if key not in lookup:
                                continue
                            source = quote['source']
                            status = statuses.get(quote['venue'], statuses.get(source['provider'], {}))
                            try:
                                cid = contract_id(dict(quote=quote))
                                book, record = books.get(cid), by_contract.get(cid)
                                extra = {}
                                if (quote['venue'] in VENUES and quote['provenance']['real_source']
                                        and record and record.get('comparison_source_metadata',{}).get('native_key')):
                                    try:
                                        extra['native_execution'] = model(quote, record, event, group, book,
                                            fee_reviews[quote['venue']], at=instant(at))
                                    except NativeEvidenceError as exc:
                                        extra['native_error'] = str(exc)
                                    except (KeyError, ValueError, TypeError, ArithmeticError):
                                        extra['native_error'] = 'native_execution_evidence_unqualified'
                                value = instrument(quote, state['comparison_profiles'], event, group, at=at,
                                    source_status=status, authorized=lookup[key]['authorized'],
                                    book=book, **extra)
                            except (ValueError, KeyError, TypeError):
                                failures.append(dict(occurrence=occurrence, scopes=[key]))
                                continue
                            if status.get('reason_code') == 'aggregate_transport_uncertain':
                                value['checks']['execution'] = check([*value['checks']['execution']['reason_codes'],
                                    'ambiguous_dispatch_unresolved'])
                            instruments.append(value)
                            values = references(quote, state['comparison_profiles'])
                            # Every observation remains in readiness accounting. Only
                            # executable, contract-ready legs can enter financial work
                            # or a ticket, so do not duplicate their unusable profile
                            # graphs into the preparation cache and retained projection.
                            if all(value['checks'][purpose]['state']=='ready' for purpose in ('execution','contract')):
                                detached = dict(quote=deepcopy(quote),
                                    profiles={quote['comparison_input_refs']['refs'][kind]: item for kind, item in values.items()},
                                    event={k:deepcopy(v) for k,v in event.items() if k not in ('groups','funded_pairs')},
                                    group={k:deepcopy(v) for k,v in group.items() if k != 'outcomes'})
                                if 'native_execution' in extra:
                                    detached['native_execution'] = extra['native_execution']
                                size += len(encoded(detached))
                                inputs[value['id']] = detached
                            reference = quote['comparison_input_refs']['refs'].get('reference')
                            if reference and reference not in shared:
                                ref = values['reference']['payload']
                                shared[reference] = dict(venue=ref.get('venue','pinnacle'),
                                    originals=[{k:r.get(k) for k in ('book_at','market_at','received_at','revision')}
                                        for r in ref.get('outcomes',[])], receipt_sha256=ref.get('receipt_sha256'))
    except (ValueError, KeyError, TypeError):
        failures.append(dict(occurrence=occurrence, scopes=sorted({digest(dict(venue=r['quote']['venue'],
            sport=league_sport(r['event']['competition']), league=r['event']['competition'],
            market={'moneyline':'winner','team_binary':'winner'}.get(r['market_identity']['family'],r['market_identity']['family']), period=r['market_identity']['period'])) for r in rows})))
    return dict(instruments=instruments, failures=failures, references=shared, financial_inputs=inputs, input_bytes=size)


def scope_inventory(selection, config, authority):
    scopes = []
    for venue, sport, league, market, period in product(selection.venues, selection.sports, selection.leagues, selection.markets, selection.periods):
        if league_sport(league) is not None and sport != league_sport(league):
            continue
        native = venue in ('kalshi', 'polymarket_us')
        configured = bool(config['enabled'] and league in (native_scope(config) if native else aggregate_scope(config)) and
                          (native or config['aggregate_enabled']) and ('moneyline' if market == 'winner' else market) in
                          (native_markets(config) if native else config['families']))
        supported = sport == league_sport(league) and predicate_supported(league, 'moneyline' if market=='winner' else market, period)
        authorized = bool(authority == GRANT and configured and supported)
        scope = dict(venue=venue, sport=sport, league=league, market=market, period=period)
        reasons = []
        if not supported:
            reasons.append('scope_unsupported')
        elif not authorized:
            reasons.append('scope_not_authorized')
        scopes.append(dict(key=digest(scope), **scope, configured=configured, authorized=authorized,
                           supported=supported, check=check(reasons)))
    if len(scopes) > 256:
        raise ValueError('readiness_scope_capacity')
    return scopes
