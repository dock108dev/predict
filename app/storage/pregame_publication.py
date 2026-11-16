"""Read the committed economics against the current sporting schedule."""

from app.comparison.game_phase import scheduled_phase, sporting_clock
from app.storage.store import stamp
from .ordinary_projection import event_owners, event_signature, publication_runtime


def occurrence_rows(rows, selected):
    """Keep schedule witnesses from every source in a verified occurrence."""
    ids = {row['id'] for row in selected}
    occurrences = {occurrence for row in selected
                   if (occurrence := row['current_authority'].get('occurrence_id'))}
    if not occurrences:
        return selected
    return [row for row in rows if row['id'] in ids
            or row['current_authority'].get('occurrence_id') in occurrences]


def project(db, result, owner, states, *, at, epoch, withdrawn):
    """Apply sporting changes without comparing the publication to newer prices.

    A published member owns its price, reference, fee and pair results together.
    The schedule is an independent authority and must take effect before another
    collector turn, including when acquisition is stopped.
    """
    candidates = [row for row in result['rows']
                  if row.get('publication_epoch', result['publication']['epoch']) == epoch
                  and row['current_authority']['price'].get('lifecycle', {}).get('state') != 'live']
    events = event_owners(db, candidates, at=at)
    # Check each source event only once, even with many alternate lines.
    schedules = {}
    for key, event in events.items():
        phase = withdrawn.get(event_signature(event)) or scheduled_phase(event, at)
        schedules[key] = (phase, event['scheduled_start'])
    corrections = {}
    for row in candidates:
        if not (occurrence := row['current_authority'].get('occurrence_id')):
            continue
        source = row.get('source') or {}
        key = source.get('provider'), source.get('native_event_id')
        event = events.get(key)
        if not event or stamp(event['scheduled_start']) == stamp(row['start_at']):
            continue
        if clock := sporting_clock(event):
            revision = stamp(clock)
            if occurrence not in corrections or revision > corrections[occurrence][0]:
                corrections[occurrence] = (revision, schedules[key])
    rows = []
    starts = {}
    for original in candidates:
        price = original['current_authority']['price']
        source = original.get('source') or {}
        key = source.get('provider'), source.get('native_event_id')
        phase, start = schedules.get(key, (price.get('lifecycle', {}), original['start_at']))
        correction = corrections.get(original['current_authority'].get('occurrence_id'))
        if correction and not phase.get('reason') and phase.get('state') != 'live':
            phase, start = correction[1]
        start = stamp(start).isoformat()
        if (stamp(start) <= at or phase.get('state') != 'scheduled' or phase.get('reason')
                or set(price.get('reasons', ())) - {'source_expired'} or not price.get('expected')):
            continue
        row = dict(original, start_at=start, price_current=True, posted_price=True, game_state='scheduled',
                   game_state_reason=None, game_state_basis=phase.get('basis'), current_reasons=[])
        authority = original['current_authority']
        row['current_authority'] = dict(authority, start_at=start,
            price=dict(price, current_until=start, lifecycle=phase),
            references=[dict(ref, current_until=start) for ref in authority['references']])
        baseline = row.get('sportsbook_baseline')
        if baseline:
            row['sportsbook_baseline'] = dict(baseline, current_until=start)
            row['sportsbook_return_percent'] = baseline['return_percent']
        starts.setdefault(row['game_key'], set()).add(start)
        rows.append(row)
    by_id = {row['id']: row for row in rows}
    pairs = []
    for pair in result['pairs']:
        if all(leg in by_id for leg in pair['legs']):
            first, second = (by_id[leg] for leg in pair['legs'])
            if stamp(first['start_at']) == stamp(second['start_at']):
                pairs.append(dict(pair, start_at=first['start_at']))
    games = [dict(game, start_at=next(iter(times))) if len(times) == 1 else game
             for game in result['games'] if (times := starts.get(game['game_key']))]
    runtime = publication_runtime(owner)
    publication = dict(result['publication'], read_at=at.isoformat(), sources=states,
        data_runtime=runtime, current_prices=len(rows), retained_prices=0,
        state='held' if runtime['stopped'] or runtime['paused_sources'] else
        'ready' if result['publication']['finance'] == 'ready' else 'partial')
    return dict(result, rows=rows, pairs=pairs, games=games, publication=publication)
