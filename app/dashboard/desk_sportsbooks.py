"""Read-only sportsbook price enrichment for exact desk outcomes."""
from datetime import timedelta
from fractions import Fraction

from app.comparison.game_phase import PREGAME_SPORTSBOOK_SECONDS
from app.comparison.sgo_reference import BEST_BOOKS
from app.storage.store import stamp


def sportsbook_selection(offer, roles):
    """Map a browsable outcome to a sportsbook side without inferring settlement."""
    market, selection = offer['market'], offer.get('selection') or {}
    family = market['market']
    if market['period'] != 'full_game':
        return None
    predicate = selection.get('predicate')
    if family == 'winner' and predicate == 'win':
        side = roles.get(selection.get('participant'))
        return ('moneyline', side, None) if side else None
    if family == 'spread' and predicate == 'cover':
        side = roles.get(selection.get('participant'))
    elif family == 'total' and predicate in ('over', 'under'):
        side = predicate
    else:
        return None
    line = selection.get('signed_line')
    return (family, side, Fraction(line)) if side and line is not None else None


def add_sgo_prices(db, out, rows, states, *, at, include_retained, mark_retained=False, sgo_inputs=None):
    """Join stored same-line book quotes for display, including native-only groups."""
    from app.comparison.game_phase import LIVE_SECONDS, sgo_event_status, sporting_phase
    from app.comparison.public_sportsbook_estimate import collect_pairs, sgo_observation
    from app.storage.ordinary_projection import source_allowed
    from app.storage.sportsgameodds_reference import EventInputs

    groups = [group for group in out['rows'] if group.get('offers')]
    if not groups:
        return
    state = states['sportsgameodds']
    if state.get('reason_code') == 'sgo_charge_unresolved':
        for group in groups:
            group['sportsbook_source_reason'] = 'sgo_charge_unresolved'
        if not (include_retained or mark_retained):
            return
    games = {game['game_key']: game for game in out['games']}
    roles = {key: {p['id']: p['role'] for p in game['participants']
                   if p.get('id') and p.get('role') in ('home', 'away')}
             for key, game in games.items()}
    signatures = {}
    group_games = {group['game_key'] for group in groups}
    for key, game in games.items():
        if key not in group_games:
            continue
        ids = {role: team for team, role in roles[key].items()}
        if ids.keys() == {'home', 'away'} and game.get('start_at'):
            signature = (game['league'], stamp(game['start_at']), ids['home'], ids['away'])
            signatures.setdefault(signature, []).append(key)
    candidates = {}
    sportsbook_occurrences = {}
    if signatures:
        starts = [signature[1] for signature in signatures]
        events = db.execute("""SELECT native_event_id, competition, scheduled_start,
                                      facts->>'home' AS home, facts->>'away' AS away
                               FROM current_event
                               WHERE provider='sportsgameodds' AND competition=ANY(%s)
                                 AND scheduled_start::timestamptz BETWEEN %s AND %s""",
                            (sorted({signature[0] for signature in signatures}), min(starts), max(starts))).fetchall()
        for event in events:
            signature = (event['competition'], stamp(event['scheduled_start']), event['home'], event['away'])
            for key in signatures.get(signature, ()):
                candidates.setdefault(key, set()).add(event['native_event_id'])
                sportsbook_occurrences[event['native_event_id']] = signature

    visible_ids = {offer['id'] for group in groups for offer in group['offers']}
    local = {row['id']: row['source'] for row in rows if row['id'] in visible_ids
             and (row.get('source') or {}).get('provider') == 'sportsgameodds'}
    wanted = {}
    for group in groups:
        sources = [local[offer['id']] for offer in group['offers'] if offer['id'] in local]
        ids = {source['native_event_id'] for source in sources}
        game_key = group['game_key']
        scheduled_ids = candidates.get(game_key, set())
        key = sportsbook_selection(group['offers'][0], roles.get(game_key, {}))
        if key is not None and len(scheduled_ids) == 1 and (not ids or scheduled_ids == ids):
            # A featured odd and a book's alternate can have distinct provider
            # IDs, even when their canonical side and signed line are equal.
            wanted.setdefault(next(iter(scheduled_ids)), {}).setdefault(key, {})[group['id']] = group
        if len(ids) == 1:
            for source in sources:
                line = source.get('native_line')
                key = (source['native_outcome_id'], None if line is None else Fraction(line))
                wanted.setdefault(source['native_event_id'], {}).setdefault(key, {})[group['id']] = group

    inputs = sgo_inputs if sgo_inputs is not None else EventInputs(db)
    windows = {}
    selected_frames = {}
    for event, frame in inputs.frames(wanted).items():
        facts = frame['facts']
        members = dict(facts['members'])
        context = facts.get('event_context') or {}
        phase = sporting_phase({'status': sgo_event_status(context.get('status') or {})})
        frame_at = stamp(facts['received_at'])
        scheduled = stamp(facts['starts_at'])
        live = at >= scheduled
        deadline = timedelta(seconds=LIVE_SECONDS if live else PREGAME_SPORTSBOOK_SECONDS)
        frame_current = (at - deadline <= frame_at <= at and phase['reason'] is None
                         and (phase['state'] == 'live') == live)
        if not frame_current and not (include_retained or mark_retained):
            continue
        source_since = None if include_retained or mark_retained else at - deadline
        windows.setdefault(source_since, []).append(event)
        selected_frames[event] = frame, members, context, frame_at, scheduled, live, deadline, frame_current
    event_quotes = {}
    for source_since, events_in_window in windows.items():
        event_quotes.update(inputs.quotes(events_in_window, bookmakers=BEST_BOOKS, source_since=source_since,
                                         game_markets=True))
    for event, observations in event_quotes.items():
        targets = wanted[event]
        frame, members, context, frame_at, scheduled, live, deadline, frame_current = selected_frames[event]
        if (not live and frame_current and not mark_retained and event in sportsbook_occurrences
                and source_allowed(state, context.get('league'))):
            event_groups = {gid: group for matches in targets.values() for gid, group in matches.items()}
            observation = sgo_observation(frame, observations, at=at,
                                         occurrence=sportsbook_occurrences[event])
            if observation:
                for group in event_groups.values():
                    key = sportsbook_selection(group['offers'][0], roles.get(group['game_key'], {}))
                    if key and candidates.get(group['game_key']) == {event}:
                        collect_pairs(group.setdefault('_sportsbook_pairs', {}), (observation,), key,
                                      at=at, start=scheduled)
        for row in observations:
            fact = row['facts']
            if (fact['period'] != 'game' or fact.get('price_american') is None
                    or fact['venue'] not in BEST_BOOKS or members.get(row['id']) != row['revision']):
                continue
            line = None if fact['line'] is None else Fraction(fact['line'])
            exact = targets.get((fact['odd_id'], line), {})
            by_schedule = targets.get((fact['market'], fact['side'], line), {})
            if not exact and not by_schedule:
                continue
            starts = stamp(fact['starts_at'])
            if starts != scheduled:
                continue
            source_at = stamp(fact['source_at']) if fact.get('source_at') else None
            received_at = stamp(fact['received_at'])
            if (not fact['available'] or fact['phase'] != ('live' if live else 'pregame')
                    or not source_at or not source_at <= received_at <= frame_at <= at
                    or (source_at >= starts) != live):
                continue
            current = bool(frame_current and at <= source_at + deadline and source_allowed(state, fact['league']))
            if mark_retained:
                if not current:
                    for group in (by_schedule | exact).values():
                        hidden = group.setdefault('retained_sportsbooks', [])
                        if fact['venue'] not in hidden:
                            hidden.append(fact['venue'])
            elif current or include_retained:
                for group_id, group in (by_schedule | exact).items():
                    book = group['sportsbook_quotes'].setdefault(fact['venue'], [])
                    prior = next((price for price in book if price.get('price_american') == fact['price_american']
                                  and price.get('source_at') == fact['source_at']), None)
                    if prior is not None:
                        prior['alternate'] = fact.get('alternate')
                    else:
                        book.append(dict(price_american=fact['price_american'], source_at=fact['source_at'],
                                         current=current, side=fact['side'], line=fact['line'],
                                         alternate=fact.get('alternate'),
                                         match='source_event' if group_id in exact else 'schedule_and_teams'))


def add_public_prices(out, owner, *, at, include_retained, mark_retained=False, include_history=True):
    from app.comparison.public_sportsbook_estimate import LIFETIME, allowed, collect_pairs, index, read_captures, retained_prices
    from app.storage.store import ROOT

    if not out['rows'] or not (include_retained or mark_retained or allowed(owner)):
        return
    captures = read_captures(ROOT, at=at)
    current = index(captures, at=at) if allowed(owner) else {}
    retained = {}
    if include_retained or mark_retained:
        retained = (retained_prices(ROOT, captures, at=at, leagues={group.get('league') for group in out['rows']})
                    if include_history else index(captures, at=at, retained=True))
    games = {game['game_key']: game for game in out['games']}
    for group in out['rows']:
        game = games.get(group['game_key'])
        if not game or not group.get('offers'):
            continue
        roles = {p['id']: p['role'] for p in game['participants'] if p.get('id') and p.get('role') in ('home', 'away')}
        teams = {role: team for team, role in roles.items()}
        key = sportsbook_selection(group['offers'][0], roles)
        if not key or teams.keys() != {'home', 'away'}:
            continue
        occurrence = (game['league'], stamp(group['start_at']), teams['home'], teams['away'])
        if not mark_retained and (observation := current.get(occurrence)):
            collect_pairs(group.setdefault('_sportsbook_pairs', {}), (observation,), key,
                          at=at, start=occurrence[1])
        for entries, fresh in ((retained, False),) if mark_retained else ((current, True), (retained, False)):
            observation = entries.get(occurrence)
            if (not observation or not observation['scheduled']
                    or stamp(observation['frame_received_at']) >= occurrence[1]):
                continue
            for book, prices in observation['quotes'].get(key, {}).items():
                if mark_retained:
                    if prices and not group['sportsbook_quotes'].get(book):
                        hidden = group.setdefault('retained_sportsbooks', [])
                        if book not in hidden:
                            hidden.append(book)
                    continue
                display = group['sportsbook_quotes'].setdefault(book, [])
                for price in prices:
                    source = stamp(price['source_at'])
                    if source >= occurrence[1] or fresh and not source <= at <= source + LIFETIME:
                        continue
                    if not any(old['price_american'] == price['price_american']
                               and old.get('source_at') == price['source_at'] for old in display):
                        display.append(dict(price, current=fresh))
