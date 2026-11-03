"""Small background projection and globally ranked, evidence-bound dashboard reads.

No financial calculation or provider acquisition occurs here. Missing metrics
remain missing; full-state and conditional metrics are never interchangeable.
"""
from collections import Counter
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction

from .store import encoded, hashed, stamp
from app.dashboard.comparison_board import expand_price_fields, expand_financial

METRICS = {
    'ev': ('buffered_ev_usd', 'buffered_return_percent'),
    'arbs': ('buffered_complete_modeled_minimum_usd', 'buffered_complete_minimum_return_percent'),
}


def project(facts):
    out = {k: deepcopy(v) for k, v in facts.items() if k not in ('boards', 'selected_frame', 'result_units', 'dashboard_boards')}
    out['boards'] = {}
    for kind, (field, percentage) in METRICS.items():
        b = expand_financial(deepcopy(facts['boards'][kind]))
        candidates = []; blocked = Counter(); total = len(b['rows'])
        for row in b['rows']:
            metrics = row.get('financial_metrics', {})
            # Hypothetical scenarios are not calibrated full-state EV.
            supported = metrics.get(field) is not None and metrics.get(percentage) is not None and not row.get('modeled_basis')
            if kind == 'arbs':
                supported = supported and len(row.get('legs', [])) == 2 and len({l['venue'] for l in row['legs']}) == 2
            if supported:
                candidates.append(row)
            else:
                reasons = row.get('availability', {}).get('metrics', {}).get(field, {}).get('reason_codes', [])
                blocked.update(reasons or ['full_state_metric_unsupported'])
        ids = {leg.get('price_ref') or leg.get('quote_id') for row in candidates for leg in row.get('legs', [row])}
        b['prices'] = [p for p in b['prices'] if p['quote_id'] in ids]
        b['rows'] = candidates
        # Pair-search refusals are diagnostic units, not manufactured pair rows.
        refusals = max(0, b['availability']['total_results'] - total)
        if refusals:
            for cause in b['availability'].get('causes', []):
                blocked[cause['code']] += cause.get('affected_results', 0)
        b['dashboard_counts'] = dict(total=total, supported=len(candidates), blocked=total-len(candidates),
            refused_units=refusals, reasons=dict(blocked))
        out['boards'][kind] = b
    return out


def in_window(game, now, end):
    try:
        start = stamp(game['start_at'])
        return now <= start < end
    except (KeyError, ValueError, TypeError):
        return False


def rank(entries, kind):
    percentage = METRICS[kind][1]
    return sorted(entries, key=lambda e: (-Fraction(e[1]['financial_metrics'][percentage]),
        e[0].get('start_at') or '', e[0]['game_key'], e[1].get('quote_id') or e[1].get('pair_id')))


def read(db, policy, *, reads, stopped=False):
    from .latest_board import snapshot, board, slate_authority
    from .selected_frame import bind_token
    # Keep evidence selection and projected results in the same MVCC snapshot.
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        frame = snapshot(db, resource_guard=reads.guard, game='__catalog_only__')
        now = stamp(frame['at']); end = now + timedelta(hours=72)
        games = [g for g in frame['status']['games'] if in_window(g, now, end)]
        # Unsupported classes need counts and reasons, not a full contract graph.
        from .current_games import engine_binding
        current_engine=engine_binding()
        projections = {r['game_key']: r for r in db.execute(
            """SELECT game_key,CASE WHEN facts#>>'{context,engine_binding}'=%s
                AND facts#>>'{context,policy_revision}'=%s
                AND facts#>>'{estimate_availability,state}' IS DISTINCT FROM 'pending'
                THEN facts->'boards' ELSE NULL END boards,
                facts->'context' context,facts->'estimate_availability' estimate
                FROM latest_dashboard WHERE game_key=ANY(%s)""",
            (current_engine,policy.revision,[g['game_key'] for g in games])).fetchall()}
        # Small supported-row projections are committed with each unit. A slow
        # parent assembly must not hide a completed sibling from the Dashboard.
        unit_projections = db.execute("""SELECT u.game_key,u.unit_id,u.captured_at,
            u.facts->'dashboard_boards' boards,COALESCE(i.units,u.facts->'unit_inventory') inventory
            FROM current_result_unit u LEFT JOIN current_result_inventory i USING(game_key)
            WHERE u.game_key=ANY(%s)
            AND u.facts#>>'{context,engine_binding}'=%s
            AND u.facts#>>'{context,policy_revision}'=%s
            AND u.facts ? 'dashboard_boards'""",
            ([g['game_key'] for g in games],current_engine,policy.revision)).fetchall()
        by_game = {}
        for unit in unit_projections:by_game.setdefault(unit['game_key'],[]).append(unit)
        for key, units in by_game.items():
            inventory=max(units,key=lambda u:u['captured_at'])['inventory']
            if inventory is None:continue  # No complete membership proof; retain the ordinary pending projection.
            wanted={u['id'] for u in inventory}
            units=[u for u in units if u['unit_id'] in wanted]
            if not units:continue
            merged={}
            for kind in METRICS:
                b=deepcopy(units[0]['boards'][kind]);counts=Counter();reasons=Counter()
                b['rows']=[];b['prices']=[]
                for unit in units:
                    source=unit['boards'][kind];b['rows'].extend(source['rows']);b['prices'].extend(source['prices'])
                    c=source['dashboard_counts'];counts.update({k:c.get(k,0) for k in ('total','supported','blocked','refused_units')});reasons.update(c['reasons'])
                from app.comparison.calculation_availability import combine
                b['availability']=combine([u['boards'][kind]['availability'] for u in units],games=1,evaluated=True)
                b['dashboard_counts']=dict(counts,reasons=dict(reasons))
                b['result_unit_coverage']=dict(total=len(wanted),published=len(units),pending=len(wanted)-len(units))
                merged[kind]=b
            projections[key]=dict(boards=merged,context=dict(engine_binding=current_engine,policy_revision=policy.revision),estimate=dict(state='partial'))
        for game in games:
            game.pop('matches', None)
        selected_frames = {}
        slates = {}; selected = set()
        for kind, (field, percentage) in METRICS.items():
            entries = []; boards = []; errors = []; counts = Counter(); reasons = Counter()
            for game in games:
                key = game['game_key']
                saved = projections.get(key)
                if (saved is None or (saved.get('context') or {}).get('engine_binding')!=current_engine
                        or (saved.get('context') or {}).get('policy_revision')!=policy.revision
                        or (saved.get('estimate') or {}).get('state')=='pending'):
                    errors.append(dict(game_key=key, reason='background_dashboard_pending'))
                    continue
                projection=saved['boards']
                count = projection[kind]['dashboard_counts']
                counts.update({k: count.get(k, 0) for k in ('total', 'supported', 'blocked', 'refused_units')})
                reasons.update(count['reasons'])
                if projection[kind]['rows']:
                    if key not in selected_frames:
                        selected_frames[key] = snapshot(db, resource_guard=reads.guard, game=key, dashboard=True)
                    value = expand_price_fields(board(selected_frames[key], key, view=kind, filter='all'))
                    # Counts describe supported/unsupported inputs, independent
                    # of the currentness validation applied to each result.
                    value['dashboard_counts'] = count
                else:
                    value = deepcopy(projection[kind])
                    value['background_reasons'] = frame['reasons']
                boards.append(value)
                for row in value['rows']:
                    state = row['availability']['metrics'][field]['state']
                    if not stopped and state == 'numeric_current' and row.get('freshness', {}).get('status') == 'current':
                        entries.append((game, row))
                    else:
                        counts['stale'] += 1
                        reasons.update(row['availability']['metrics'][field]['reason_codes'])
            ordered = rank(entries, kind)
            counts['evaluated'] = len(ordered)
            # Return all supported rows, globally ordered; UI filters cannot hide
            # a better result on another game page. Unsupported bodies stay in SQL.
            order = {id(row): index for index, (_, row) in enumerate(ordered)}
            for b in boards:
                b['rows'] = [r for r in b['rows'] if id(r) in order]
                b['rows'].sort(key=lambda r: order[id(r)])
                if b['rows']: selected.add(b['game_key'])
                b['availability']['evaluation_complete'] = not (b['dashboard_counts']['blocked'] or b['dashboard_counts'].get('refused_units') or b['background_reasons'])
                b['availability']['causes'] = [dict(code=k) for k in b['dashboard_counts']['reasons']]
            slates[kind] = dict(version='predict-dashboard-1', games=games, boards=boards, errors=errors,
                policy=frame['status']['policy'], stopped=stopped or not frame['owner'].get('active'),
                as_of=frame['status'].get('as_of'), read_at=frame['at'], read_revision=frame['read_revision'],
                window=dict(start=now.isoformat(), end=end.isoformat()), counts=dict(counts), blocked_reasons=dict(reasons),
                ranking_basis=dict(metric=percentage, direction='descending', ties=['start_at','game_key','result_id'], includes_nonpositive=True),
                ranking=[dict(game_key=g['game_key'], result_id=r.get('quote_id') or r.get('pair_id'), value=r['financial_metrics'][percentage]) for g,r in ordered])
        records = []
        for key in sorted(selected):
            saved = db.execute("SELECT game_key,calculated_at,facts-'boards' facts FROM latest_board WHERE game_key=%s", (key,)).fetchone()
            if saved is None: raise ValueError('current_inputs_changed_or_removed')
            from .result_publication import attach as attach_units
            attach_units(db,saved,guard=reads.guard)
            records.append(reads.freeze(encoded(dict(game_key=key, row=saved))))
        captured = reads.capture({}, records, context='completed', authority=hashed([frame['read_authority'], bool(stopped)]))
        revision = hashed({k: dict(rows=[r for b in s['boards'] for r in b['rows']], games=[(g['game_key'],g.get('start_at')) for g in s['games']], counts=s['counts'], reasons=s['blocked_reasons']) for k, s in slates.items()})
        for slate in slates.values():
            slate['read_token'] = captured.token
            for b in slate['boards']:
                bind_token(b, captured.token)
                expand_financial(b)
    reads.authorize(captured, slate_authority(db, stopped=stopped))
    return dict(version='predict-dashboard-1', slates=slates, revision=revision, read_at=frame['at'], provider_requests=0)
