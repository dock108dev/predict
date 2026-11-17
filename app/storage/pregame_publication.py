"""Read the committed economics against the current sporting schedule."""

from datetime import timedelta

from app.comparison.game_phase import scheduled_phase, sporting_clock
from app.comparison.source_clock import CURRENT_DESK_MAX_AGE_SECONDS
from app.fees import product_schedules, schedule_lifecycle
from app.fees.evidence import applies
from app.storage.store import hashed, stamp
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


def project(db, result, owner, states, *, at, epoch, withdrawn, families=()):
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
    start_clocks = {}
    schedule_witnesses = {}
    withdrawals = {}
    for original in candidates:
        if families and original['market']['market'] not in families:
            continue
        authority = original['current_authority']
        price = authority['price']
        source = original.get('source') or {}
        key = source.get('provider'), source.get('native_event_id')
        lifecycle = price.get('lifecycle', {})
        witness = (key, authority.get('occurrence_id'), original['start_at'],
                   lifecycle.get('state'), lifecycle.get('reason'), lifecycle.get('basis'))
        if witness not in schedule_witnesses:
            phase, start = schedules.get(key, (lifecycle, original['start_at']))
            correction = corrections.get(authority.get('occurrence_id'))
            if correction and not phase.get('reason') and phase.get('state') != 'live':
                phase, start = correction[1]
            if start not in start_clocks:
                start_clocks[start] = stamp(start)
            start_clock = start_clocks[start]
            schedule_witnesses[witness] = phase, start_clock, start_clock.isoformat()
        phase, start_clock, start = schedule_witnesses[witness]
        if phase.get('state') in ('cancelled', 'final', 'suspended') and phase.get('reason'):
            withdrawals[original['game_key']] = phase['reason']
        if (start_clock <= at or phase.get('state') != 'scheduled' or phase.get('reason')
                or set(price.get('reasons', ())) - {'source_expired'} or not price.get('expected')):
            continue
        row = dict(original, start_at=start, price_current=True, posted_price=True, game_state='scheduled',
                   game_state_reason=None, game_state_basis=phase.get('basis'), current_reasons=[],
                   quote_freshness=quote_freshness(original, price, owner, states, key[0], at))
        row['current_authority'] = dict(authority, start_at=start,
            price=dict(price, current_until=start, lifecycle=phase),
            references=[dict(ref, current_until=start) for ref in authority['references']])
        if original['start_at'] not in start_clocks:
            start_clocks[original['start_at']] = stamp(original['start_at'])
        if start_clock != start_clocks[original['start_at']] and (
                'pregame_reference' in row or (events.get(key, {}).get('schedule_metadata') or {}).get('reviewed_correction')):
            reason = 'reference_occurrence_schedule_changed'
            row.update(pregame_reference=dict(available=False, reason=reason),
                       settlement_assessment=dict(available=False, reason=reason),
                       sportsbook_reference_reason=reason, sportsbook_baseline=None, sportsbook_return_percent=None,
                       sportsbook_after_fee_percent=None, trade_fee=dict(available=False, reason=reason))
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


def arb_contracts(db, contracts):
    """Read posted membership and the contract fields that govern settlement."""
    if not contracts:
        return {}
    return {row['id']: (row['revision'], hashed([row['selection'], row['market'], row['scoring_scope']]))
            for row in db.execute("""
        SELECT c.id, c.revision, c.facts->'selection' AS selection, c.facts->'market_identity' AS market,
            c.facts#>'{comparison_source_metadata,scoring_scope}' AS scoring_scope
        FROM current_contract c
        JOIN current_offer_storage o ON o.contract_id=c.id
        WHERE c.id=ANY(%s) AND o.facts->>'state' IS DISTINCT FROM 'unavailable'
            AND NOT EXISTS (
                SELECT 1 FROM native_book_revision observed
                JOIN native_book_revision latest ON (latest.venue,latest.event_id,latest.native_market_id) =
                    (observed.venue,observed.event_id,observed.native_market_id)
                WHERE observed.id=o.native_book_id AND latest.is_current AND latest.state IN ('closed','settled'))
        """, (sorted(contracts),))}


def arb_authority(db, result, owner, at):
    """Validate membership and fees while the old publication supplies prices."""
    legs = {leg for pair in result['pairs'] for leg in pair['legs']}
    if not legs:
        return result
    rows = {row['id']: row for row in result['rows'] if row['id'] in legs}
    witnesses = {id_: row['current_authority']['price'] for id_, row in rows.items()}
    current = arb_contracts(db, {w['dependency'] for w in witnesses.values() if w.get('dependency')})
    eligible = set()
    for id_, witness in witnesses.items():
        live = current.get(witness.get('dependency'))
        if not live or not witness.get('expected'):
            continue
        semantic = rows[id_]['current_authority'].get('arb_contract')
        if live[0] == witness['expected'][1] or live[1] == semantic:
            eligible.add(id_)
    for id_ in eligible:
        row = rows[id_]
        fee = row.get('trade_fee') or {}
        if not fee.get('available') or fee.get('classification') == 'synthetic':
            continue
        product = product_schedules.key_for(row)
        expected = row['current_authority'].get('public_fee_revision')
        governing = (owner.get('fee_products', {}).get(product) if product else
                     owner.get('fee_lifecycle') if row['venue'] == 'prophetx' else None)
        revision = product_schedules.revision(governing) if product else schedule_lifecycle.revision(governing)
        evidence = fee.get('evidence') or {}
        if (product or row['venue'] == 'prophetx') and revision != expected:
            reason = (schedule_lifecycle.REVIEW_REQUIRED if (governing or {}).get('review_required')
                      else 'public_fee_schedule_refresh_pending')
        elif not evidence.get('reviewed_at') or not applies(evidence, at):
            reason = 'conditional_fee_review_expired_or_not_effective'
        else:
            continue
        rows[id_] = dict(row, trade_fee=dict(available=False, reason=reason))
    return dict(result, pairs=[pair for pair in result['pairs'] if eligible.issuperset(pair['legs'])],
                rows=[rows.get(row['id'], row) for row in result['rows']])
