"""Read the committed economics against the current sporting schedule."""

from datetime import timedelta

from app.comparison.game_phase import scheduled_phase, sporting_clock
from app.comparison.source_clock import CURRENT_DESK_MAX_AGE_SECONDS
from app.storage.store import stamp
from .ordinary_projection import event_owners, event_signature, publication_runtime, source_allowed


def occurrence_rows(rows, selected, *, possible_peers=False):
    """Keep schedule witnesses from every source in a verified occurrence."""
    ids = {row['id'] for row in selected}
    occurrences = {occurrence for row in selected
                   if (occurrence := row['current_authority'].get('occurrence_id'))}
    # The display can reconcile separate published occurrence keys using
    # independent source facts. Supply the same-start candidates on Open Game.
    slots = {(row['league'], stamp(row['start_at'])) for row in selected} if possible_peers else set()
    if not occurrences and not slots:
        return selected
    return [row for row in rows if row['id'] in ids
            or row['current_authority'].get('occurrence_id') in occurrences
            or (row['league'], stamp(row['start_at'])) in slots]


def feed_available(owner, states, provider, venue, league):
    return (owner.get('healthy') and owner.get('active') and not owner.get('global_stopped')
            and not {provider, venue}.intersection(owner.get('paused_sources', ()))
            and source_allowed(states.get(provider, states.get(venue, {})), league))


def quote_freshness(row, price, owner, states, provider, at):
    times = row.get('times') or {}
    clock = price.get('clock_at') or times.get('source_at')
    if not clock:
        return 'retained' if not feed_available(owner, states, provider, row['venue'], row['league']) else 'unknown'
    fresh = at - timedelta(seconds=CURRENT_DESK_MAX_AGE_SECONDS) <= stamp(clock) <= at
    return 'fresh' if fresh and feed_available(owner, states, provider, row['venue'], row['league']) else 'retained'


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
    withdrawals = {}
    for original in candidates:
        price = original['current_authority']['price']
        source = original.get('source') or {}
        key = source.get('provider'), source.get('native_event_id')
        phase, start = schedules.get(key, (price.get('lifecycle', {}), original['start_at']))
        correction = corrections.get(original['current_authority'].get('occurrence_id'))
        if correction and not phase.get('reason') and phase.get('state') != 'live':
            phase, start = correction[1]
        start = stamp(start).isoformat()
        if phase.get('state') in ('cancelled', 'final', 'suspended') and phase.get('reason'):
            withdrawals[original['game_key']] = phase['reason']
        if (stamp(start) <= at or phase.get('state') != 'scheduled' or phase.get('reason')
                or set(price.get('reasons', ())) - {'source_expired'} or not price.get('expected')):
            continue
        row = dict(original, start_at=start, price_current=True, posted_price=True, game_state='scheduled',
                   game_state_reason=None, game_state_basis=phase.get('basis'), current_reasons=[],
                   quote_freshness=quote_freshness(original, price, owner, states, key[0], at))
        authority = original['current_authority']
        row['current_authority'] = dict(authority, start_at=start,
            price=dict(price, current_until=start, lifecycle=phase),
            references=[dict(ref, current_until=start) for ref in authority['references']])
        baseline = row.get('sportsbook_baseline')
        if baseline:
            provider = baseline.get('source') or 'sportsgameodds'
            row['reference_feed_available'] = bool(feed_available(owner, states, provider, provider, row['league']))
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
    fresh_count = sum(row['quote_freshness'] == 'fresh' for row in rows)
    publication = dict(result['publication'], read_at=at.isoformat(), sources=states,
        data_runtime=runtime, current_prices=fresh_count,
        retained_prices=sum(row['quote_freshness'] == 'retained' for row in rows),
        posted_prices=len(rows),
        state='held' if runtime['stopped'] or runtime['paused_sources'] else
        'ready' if result['publication']['finance'] == 'ready' else 'partial')
    return dict(result, rows=rows, pairs=pairs, games=games, publication=publication,
                desk_event_facts=events,
                pregame_withdrawals={key: reason for key, reason in withdrawals.items() if key not in starts})
