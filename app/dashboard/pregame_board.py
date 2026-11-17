"""Ordinary selected-unit list and inspection reads over committed projections."""
from collections import Counter
from datetime import time
from fractions import Fraction

from app.comparison.cashflows import exact_wire
from app.comparison.game_phase import scheduled_phase, sporting_clock
from app.fees import product_schedules, schedule_lifecycle
from app.storage import comparison_snapshot as snapshots, pregame_unit_board as units
from app.storage.ordinary_projection import event_owners, event_signature, publication_runtime, withdrawn_events
from app.storage.store import hashed, stamp

from .product_finance import visible_publication
from .snapshot_display import matchup_search, odds, participant_search, search_parts
from .trade_desk import EV_METRIC, filters, offer

BASIS = 'selected_unit'


def states_at(db, events, at):
    rows = [dict(source=dict(provider=provider, native_event_id=native))
            for provider, native in events if provider and native]
    witnessed = event_owners(db, rows, at=at)
    closed = withdrawn_events(db, at=at) if rows else {}
    return {key: (closed.get(event_signature(e)) or scheduled_phase(e, at), stamp(e['scheduled_start']),
                  sporting_clock(e)) for key, e in witnessed.items()}


def game_status(sources, witnessed, at):
    """A proven kickoff correction can withdraw the old economic occurrence."""
    schedule = [(phase, start, clock, stamp(original))
                for provider, native, original in sources
                if (info := witnessed.get((provider, native)))
                for phase, start, clock in [info]]
    cancelled = any(phase['state'] in ('cancelled', 'final', 'suspended', 'live') for phase, _, _, _ in schedule)
    corrections = [(stamp(clock), start) for _, start, clock, original in schedule if clock and start != original]
    corrected = max(corrections)[1] if corrections else None
    times = [start for _, start, _, _ in schedule] or [stamp(original) for _, _, original in sources]
    if cancelled or not times or min(times) <= at or corrected and corrected <= at:
        return 'pregame_closed', None
    if corrected:
        return 'reference_occurrence_schedule_changed', corrected
    return None, min(times)


def authority(db, guards, owner, at):
    contracts = {g['contract'] for g in guards if g['contract']}
    refs = {ref for g in guards for ref in g['references']}
    catalogs = {g['catalog']['dependency'].removeprefix('sgo-native-catalog:novig:') for g in guards if g['catalog']}
    stored = {r['id']: r for r in db.execute('''
        SELECT c.id,c.facts#>>'{market_identity,rules}' AS settlement_rules,
          c.facts#>'{comparison_source_metadata,scoring_scope}' AS scoring_scope,
          (NOT c.active OR o.contract_id IS NOT NULL AND o.facts->>'state' IS DISTINCT FROM 'unavailable')
          AND NOT EXISTS (
            SELECT 1 FROM native_book_revision observed JOIN native_book_revision current
              ON (current.venue,current.event_id,current.native_market_id) =
                 (observed.venue,observed.event_id,observed.native_market_id)
            WHERE observed.id=o.native_book_id AND current.is_current
              AND current.state IN ('closed','settled')
          ) AS posted
        FROM current_contract_storage c LEFT JOIN current_offer_storage o ON o.contract_id=c.id
        WHERE c.id=ANY(%s)
        ''', (sorted(contracts),))} if contracts else {}
    reference = {r['id']: r['available'] for r in db.execute('''
        SELECT id, facts->'available'='true'::jsonb AS available
        FROM sgo_quote_revision WHERE is_current AND id=ANY(%s)''', (sorted(refs),))} if refs else {}
    catalog = {r['event_id']: r['revision'] for r in db.execute('''
        SELECT event_id,revision FROM current_sgo_native_catalog WHERE event_id=ANY(%s)''',
        (sorted(catalogs),))} if catalogs else {}
    fee_policy = schedule_lifecycle.revision(owner.get('fee_lifecycle'))
    products = {k: product_schedules.revision(v) for k, v in (owner.get('fee_products') or {}).items()}
    result = {}
    for g in guards:
        reason = None
        price = stored.get(g['contract'])
        if not price or not price['posted']:
            reason = 'phase_price_unavailable'
        elif any(value != price[key] for key, value in (g['contract_terms'] or {}).items()):
            reason = 'venue_settlement_rules_unverified'
        elif not all(reference.get(ref) for ref in g['references']):
            reason = 'reference_quote_withdrawn'
        elif ((c := g['catalog']) and catalog.get(c['dependency'].removeprefix('sgo-native-catalog:novig:'))
                != c['expected'][0]):
            reason = 'sgo_native_catalog_replaced_or_expired'
        elif any(g[k] and stamp(g[k]) <= at for k in ('settlement_deadline', 'fallback_deadline')):
            reason = 'venue_settlement_rules_unverified'
        elif g['fee_deadline'] and stamp(g['fee_deadline']) <= at:
            reason = 'unit_fee_schedule_unverified'
        elif (g['fee_product'] and g['fee_revision'] != products.get(g['fee_product'],
                product_schedules.revision(None)) or g.get('venue') == 'prophetx'
                and g['fee_revision'] != fee_policy):
            reason = 'public_fee_schedule_refresh_pending'
        if reason:
            result[g['id']] = reason
    return result


def read_page(db, query, options, *, cents, head, owner, states, epoch, at):
    _, _, offset, limit = options
    base = dict(schema=units.SCHEMA, rows=[], total=0, offset=offset, limit=limit, page_count=0,
        basis=BASIS, row_kind='bets', valuation_version=units.pregame_valuation.VERSION, selected_usd=exact_wire(Fraction(cents, 100)) if cents else None,
        publication=visible_publication(dict(sources=states, read_at=at.isoformat())),
        matched_offer_count=0, offer_count=0, ranked_group_count=0, calculation_missing=[])
    if cents is None:
        return dict(base, state='unit_needed')
    stored = units.read(db, cents)
    if not stored or not stored['root_id'] or not stored['board_id']:
        return dict(base, state='read_failed' if stored and stored['error'] else 'valuation_pending',
                    reason=stored['error'] if stored else None)
    if stored['policy_id'] != units.policy_id():
        return dict(base, state='valuation_pending', reason='valuation_policy_changed')
    board_id = stored['board_id']
    projection = snapshots._decode(stored['projection'])
    if projection['publication']['epoch'] != epoch:
        return dict(base, state='valuation_pending', reason='valuation_evidence_epoch_changed')

    zone, day, minimum, profit, _ = filters(query)
    terms = search_parts(query.get('search', ''))
    leagues, families, venues = [set(query.get(key, '').split(',')) - {''} for key in ('league', 'family', 'venue')]
    venue_filter = venues.__contains__ if venues else lambda _: True
    games = projection['games']
    requested_game = query.get('game_key')
    requested_game = projection['aliases'].get(requested_game, requested_game)
    start_window = [time.fromisoformat(query[key]) if query.get(key) else None for key in ('time_from','time_to')]

    def in_scope(game, league, family, start):
        if (requested_game and requested_game != game or leagues and league not in leagues
                or families and family not in families):
            return False
        start_from, start_to = start_window
        if day or start_from or start_to:
            local = stamp(start).astimezone(zone)
            if (day and local.date() != day or start_from and local.time() < start_from
                    or start_to and local.time() >= start_to):
                return False
        return True

    def matches_search(key):
        game = games.get(key, {})
        title = ' '.join(p.get('name') or '' for p in game.get('participants', ()))
        if len(terms) == 2:
            return matchup_search(terms, game, title)
        if not terms[0]:
            return True
        haystack = title.casefold() + ' ' + participant_search(game)
        return all(term in haystack for term in terms[0])

    scope = [r for r in projection['reasons'] if venue_filter(r['venue'])
             and in_scope(r['game_key'], r['league'], r['family'], r['start_at'])]
    match_games = {key for r in scope if matches_search(key := r['game_key'])}
    sources = projection['events']
    witnessed = states_at(db, {(provider, native) for key in match_games for provider, native, _ in sources[key]}, at)
    sporting = {key: game_status(sources[key], witnessed, at) for key in match_games}
    counts = Counter()
    for record in scope:
        key = record['game_key']
        if key in sporting:
            reason, _ = sporting[key]
            if not reason:
                counts.update(record['counts'])
            elif reason != 'pregame_closed':
                counts.update({'offers': record['counts']['offers'], reason: record['counts']['offers']})
    candidates = []
    for item in projection['candidates']:
        row = item['row']
        key = row['game_key']
        if (key not in sporting or sporting[key][0]
                or not in_scope(key, row['league'], row['market']['market'], row['start_at'])
                or not venue_filter(row['offer']['venue'])
                or query.get('lines') != 'all' and not item['main']):
            continue
        candidates.append(item)
    invalid = authority(db, [i['guard'] for i in candidates], owner, at)
    counts.update(invalid.values())
    chosen = {}
    for entry in candidates:
        row = entry['row']
        if row['offer']['id'] in invalid:
            continue
        old = chosen.get(row['id'])
        if old is None or entry['priority'] < old['priority']:
            chosen[row['id']] = entry
    rows = []
    for entry in candidates:
        row = entry['row']
        if chosen.get(row['id']) is not entry:
            continue
        quote = row['offer']
        valuation = quote['valuation_summary']
        if (minimum is not None and Fraction(quote['value']) < minimum
                or profit is not None and Fraction(valuation['raw']['expected_net_profit_usd']) < profit):
            continue
        guard = entry['guard']
        deadlines = [guard[k] for k in ('fee_deadline', 'settlement_deadline', 'fallback_deadline') if guard[k]]
        inspected = dict(quote, board_id=board_id, unit_usd=base['selected_usd'],
                         calculation_current_until=min(deadlines, key=stamp, default=None))
        rows.append(dict(row, offers=[inspected], score_source=dict(id=quote['id'], venue=quote['venue']),
                         score=quote['value'], opportunity_score=row['score']))
        rows[-1].pop('offer')
    # Bind offset to the normalized unit, filtered order and authoritative
    # removals. A cursor never applies to a different result even at the same offset.
    filter_signature = {key: query[key] for key in ('league','family','venue','lines','game_key','search','day',
                        'timezone','time_from','time_to','minimum','profit') if query.get(key)}
    cursor = hashed([board_id, filter_signature, [(row['id'], row['score_source']['id']) for row in rows]])
    base.update(board_id=board_id, source_result_id=stored['root_id'], board_cursor=cursor,
        valuation_policy_revision=stored['policy_id'],
        replacement_pending=stored['root_id'] != head['result_id'],
        publication=visible_publication(dict(projection['publication'], read_at=at.isoformat(), sources=states,
            data_runtime=publication_runtime(owner))))
    if (query.get('board_cursor') and cursor != query['board_cursor'] or offset and not query.get('board_cursor')):
        return dict(base, state='page_changed', reason='The selected-unit board changed. Return to the first page.')
    total = len(rows)
    shown = rows[offset:offset+limit]
    deadlines = [start for reason, start in sporting.values() if not reason and start and start > at]
    for item in candidates:
        for key in ('fee_deadline', 'settlement_deadline', 'fallback_deadline'):
            if (deadline := item['guard'][key]) and stamp(deadline) > at:
                deadlines.append(stamp(deadline))
    qualified_without_positive = 0
    if not total:
        qualified_unranked = [entry['guard'] for entry in projection['unranked']
                              if entry['game_key'] in sporting and not sporting[entry['game_key']][0]
                              and in_scope(entry['game_key'], entry['league'], entry['family'], entry['start_at'])
                              and venue_filter(entry['guard']['venue']) and (entry['main'] or query.get('lines') == 'all')]
        invalid_unranked = authority(db, qualified_unranked, owner, at)
        counts.update(invalid_unranked.values())
        qualified_without_positive = len(qualified_unranked) - len(invalid_unranked)
    matched = counts.pop('offers', 0)
    qualified = counts.pop('qualified', 0)
    return dict(base, state='ready', rows=shown, total=total, page_count=len(shown),
                board_state='populated' if total else 'empty', ranked_group_count=total, matched_offer_count=matched, offer_count=matched,
                blocker_counts=dict(counts), calculation_missing=sorted(counts),
                qualified_offer_count=max(0, qualified - len(invalid)),
                qualified_board_offer_count=len(candidates) - len(invalid) + qualified_without_positive,
                calculation_reason=None if total else
                'No qualified offers have positive Net EV for this unit and filters.' if qualified > len(invalid)
                else 'No posted offers qualify for a selected-unit valuation.',
                games=[games[key] for key in dict.fromkeys(r['game_key'] for r in shown) if key in games],
                refresh_at=min(deadlines).isoformat() if deadlines else None)


def selection(db, query, *, cents, head, owner, states, epoch, at, fragments):
    unavailable = dict(row=None, reason='unit_publication_changed')
    stored = units.read(db, cents)
    if (not stored or not stored['root_id'] or stored['board_id'] != query['board_id'] or stored['policy_id'] != units.policy_id()):
        return unavailable
    packet = snapshots._decode(stored['projection'])
    if packet['publication']['epoch'] != epoch:
        return unavailable
    exact_key = query.get('quote_key')
    refreshing = query.get('refresh') == '1' and not query.get('expected_member') and exact_key
    item = next((i for i in packet['candidates'] if (refreshing or i['row']['offer']['id'] == query['id'])
                 and (not exact_key or i['guard']['contract'] == exact_key)), None)
    if item:
        row = item['row']
        bet, game = row['id'], row['game_key']
        selected, expected = row['offer']['id'], row['offer']['evidence_result_id']
        start = row['start_at']
    else:
        replacement = next((entry for entry in packet['unranked'] if entry['guard']['contract'] == exact_key), None) if refreshing else None
        if replacement is None:
            return unavailable
        bet, game = replacement['bet_id'], replacement['game_key']
        selected, expected = replacement['guard']['id'], replacement['member']
        start = replacement['start_at']
    sources = packet['events'][game]
    witnessed = states_at(db, {(p, n) for p, n, _ in sources}, at)
    reason, _ = game_status(sources, witnessed, at)
    if reason:
        return dict(row=None, reason=reason, withdrawn_from_phase=reason == 'pregame_closed')
    drawer = packet['drawers'][bet]
    invalid = authority(db, [d['guard'] for d in drawer], owner, at)
    if reason := invalid.get(selected):
        return dict(row=None, reason=reason, withdrawn_from_phase=True)
    if query.get('expected_member') and query['expected_member'] != expected:
        return unavailable
    if head['result_id'] != stored['root_id']:
        latest = fragments.read(db, head['result_id'], leagues=set(), game_key=None, selected=selected,
                                quote_key=exact_key, browse=False) if head['result_id'] else None
        if latest is None and head['result_id']:
            rg = db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s', (head['result_id'],)).fetchone()
            latest = snapshots.unpack(rg['result'], lazy=True, db=db) if rg else None
        if not latest or not any(r['id'] == selected and r.get('evidence_result_id') == expected for r in latest['rows']):
            return unavailable
    parts = units.stored_parts(db, cents, stored['policy_id'], {d['member'] for d in drawer})
    if len(parts) != len({d['member'] for d in drawer}):
        return dict(row=None, reason='unit_board_evidence_unavailable')
    valuations = []
    for d in drawer:
        if d['id'] in invalid:
            continue
        model = parts[d['member']]['models'][d['id']]
        original = model['offer']
        reference = model['reference']
        display = model['display']
        raw = model['raw']
        if d['status'] != 'qualified':
            display = {k: v for k, v in display.items() if k not in ('net_ev', 'expected_net_profit_usd', 'opportunity_score')}
            raw = {k: v for k, v in raw.items() if k not in ('net_ev', 'expected_net_profit_usd', 'opportunity_score')}
        valuations.append(dict(model, publication_id=stored['root_id'], status=d['status'], reasons=d['reasons'],
            raw=raw, display=display, posted_odds=odds(original['value'], original['units'], original.get('payout', '1')),
            fair_odds=units.fair_odds(reference) if reference.get('available') else None))
    full = next(r for r in parts[expected]['rows'] if r['id'] == selected)
    model = next(m for m in valuations if m['offer_id'] == selected)
    price = full['current_authority']['price']
    from app.storage.pregame_publication import quote_freshness

    exact = offer(dict(full, price_current=True, posted_price=True, game_state='scheduled', current_reasons=[],
       quote_freshness=quote_freshness(full, price, owner, states, full['source']['provider'], at)), EV_METRIC)
    exact.update(start_at=start, source=full['source'], valuation=model, board_id=stored['board_id'],
                 unit_usd=model['selected_usd'])
    return dict(row=exact, reason=exact['reason'], result_id=stored['root_id'], board_id=stored['board_id'],
                comparison=valuations)
