"""Read-only sportsbook price enrichment for exact desk outcomes."""
from datetime import timedelta
from fractions import Fraction

from app.comparison.game_phase import PREGAME_SPORTSBOOK_SECONDS
from app.comparison.public_sportsbook_estimate import outcome
from app.comparison.sgo_reference import BEST_BOOKS
from app.storage.store import stamp


def sportsbook_selection(offer, roles):
    """Map a browsable outcome to a sportsbook side without inferring settlement."""
    market, selection = offer['market'], offer.get('selection') or {}
    if market['period'] != 'full_game':
        return None
    family = 'moneyline' if market['market'] == 'winner' else market['market']
    if family != 'total' and not selection.get('participant'):
        return None
    teams = {role: team for team, role in roles.items()}
    return outcome(family, selection, teams.get('home'), teams.get('away'))


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
    inputs = sgo_inputs if sgo_inputs is not None else EventInputs(db)
    occurrences = {}
    group_games = {group['game_key'] for group in groups}
    for key, game in games.items():
        if key not in group_games:
            continue
        ids = {role: team for team, role in roles[key].items()}
        if len(roles[key]) == 2 and ids.keys() == {'home', 'away'} and game.get('start_at'):
            occurrences[key] = (game['league'], stamp(game['start_at']), ids['home'], ids['away'])
    retained_starts = {item[1] for item in occurrences.values()} if include_retained or mark_retained else ()
    schedule = inputs.occurrences(at, starts=retained_starts) if occurrences else {}
    matches = {}
    sportsbook_occurrences = {}
    for game, occurrence in occurrences.items():
        candidates = schedule.get(occurrence, {})
        if len(candidates) == 1:
            event, row = next(iter(candidates.items()))
            if row['valid']:
                matches[game] = event
                sportsbook_occurrences[event] = row['occurrence'] or occurrence

    visible_ids = {offer['id'] for group in groups for offer in group['offers']}
    local = {row['id']: row['source'] for row in rows if row['id'] in visible_ids
             and (row.get('source') or {}).get('provider') == 'sportsgameodds'}
    wanted = {}
    for group in groups:
        sources = [local[offer['id']] for offer in group['offers'] if offer['id'] in local]
        ids = {source['native_event_id'] for source in sources}
        game_key = group['game_key']
        event = matches.get(game_key)
        key = sportsbook_selection(group['offers'][0], roles.get(game_key, {}))
        if key is not None and event is not None and (not ids or ids == {event}):
            # A featured odd and a book's alternate can have distinct provider
            # IDs, even when their canonical side and signed line are equal.
            wanted.setdefault(event, {}).setdefault(key, {})[group['id']] = group
        if len(ids) == 1:
            for source in sources:
                line = source.get('native_line')
                key = (source['native_outcome_id'], None if line is None else Fraction(line))
                wanted.setdefault(source['native_event_id'], {}).setdefault(key, {})[group['id']] = group

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
                    if key and matches.get(group['game_key']) == event:
                        collect_pairs(group.setdefault('_sportsbook_pairs', {}), (observation,), key,
                                      at=at, start=scheduled)
        for row in observations:
            fact = row['facts']
            if (fact['period'] != 'game' or fact.get('price_american') is None
                    or fact['venue'] not in BEST_BOOKS or members.get(row['id']) != row['revision']):
                continue
            line = None if fact['line'] is None else Fraction(fact['line'])
            exact = {group_id: group for group_id, group in targets.get((fact['odd_id'], line), {}).items()
                     if group['league'] == fact['league'] and stamp(group['start_at']) == scheduled}
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
