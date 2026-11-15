"""Narrow targeted desk reads before offer validation or archive enrichment."""
from collections import defaultdict
from datetime import timedelta

from app.collection.current_policy import SPORTS
from app.normalization.registry import Registry
from app.storage.store import stamp

from .snapshot_display import search_index, search_parts


def occurrence(league, start, home, away):
    if league and start and home and away and home != away:
        return league, stamp(start), home, away
    return None


def pregame_search(db, result, query, at):
    """Find a conservative occurrence envelope. The page still checks exact terms.

    A search must keep every venue for a possible matchup. Snapshot titles and
    source-event titles can differ, so pool their searchable names by exact
    league, kickoff and home/away identity before excluding any candidates.
    """
    terms = tuple(term for part in search_parts(query.get('search', '')) for term in part)
    leagues = set(query.get('league', '').split(',')) - {''}
    leagues = leagues & set(SPORTS) if leagues else set(SPORTS)
    if not terms and leagues == set(SPORTS):
        return None, None
    if not leagues:
        return set(), []

    texts = defaultdict(set)
    groups = {}
    if result:
        names = search_index(result) if terms else {}
        for game in result['games']:
            if game['league'] not in leagues:
                continue
            teams = {item['role']: item['id'] for item in game['participants']
                     if item.get('id') and item.get('role') in ('home', 'away')}
            key = occurrence(game['league'], game['start_at'], teams.get('home'), teams.get('away'))
            group = groups[game['game_key']] = key or game['game_key']
            if terms:
                texts[group].add(names.get(game['game_key'], ''))
        for row in result['rows']:
            if row['league'] in leagues:
                group = groups.setdefault(row['game_key'], row['game_key'])
                if terms:
                    texts[group].add(row['game_title'].casefold())

    entities = Registry.current().entities if terms else {}
    events = {}
    for row in db.execute("""SELECT id,competition,scheduled_start,
                    facts->>'home' home,facts->>'away' away,
                    facts->>'title' title,facts->'participants' participants
                FROM current_event
                WHERE competition=ANY(%s) AND scheduled_start::timestamptz>%s
                  AND scheduled_start::timestamptz<=%s""",
            (sorted(leagues), at, at + timedelta(hours=72))):
        group = occurrence(row['competition'], row['scheduled_start'], row['home'], row['away']) or row['id']
        events[row['id']] = group
        if terms:
            participants = row['participants'] if isinstance(row['participants'], dict) else {}
            teams = set(participants.values()) | {row['home'], row['away']}
            pieces = [row['title'], *participants, *teams,
                      *(entities.get(team, {}).get('name') for team in teams)]
            texts[group].add(' '.join(str(piece) for piece in pieces if piece).casefold())

    if not terms:
        return set(groups), sorted(events)
    matches = set()
    for group, names in texts.items():
        text = ' '.join(names)
        if all(term in text for term in terms):
            matches.add(group)
    return ({game_key for game_key, group in groups.items() if group in matches},
            sorted(event_id for event_id, group in events.items() if group in matches))
