"""Pregame native prices and before-fee EV from one committed SQL read."""
from datetime import timedelta

from app.comparison.public_sportsbook_estimate import select, signature
from app.comparison.source_clock import NATIVE_BOOK_MAX_AGE_SECONDS
from app.comparison.sporting_scope import supported
from app.normalization.registry import Registry
from .current_rows import CurrentRowStore, contract_id
from .ordinary_projection import source_allowed
from .store import hashed, stamp


VENUES = ('kalshi', 'polymarket_us')


def active_records(db, *, at, venues, contract=None):
    # An admissible source or confirmation clock cannot exceed its receipt.
    # This bounds the SQL read before revalidating each exact book's clock.
    rows = db.execute("""SELECT c.id, c.event_id, o.price_dependency AS price,
                                c.revision AS contract, e.revision AS event
        FROM current_offer_storage o
        JOIN current_contract c ON c.id=o.contract_id
        JOIN current_event e ON e.id=c.event_id
        JOIN native_book_revision b ON b.id=o.native_book_id
        WHERE c.venue=ANY(%s) AND e.provider=c.venue
          AND (%s::text IS NULL OR c.id=%s)
          AND e.scheduled_start::timestamptz > %s AND e.scheduled_start::timestamptz <= %s
          AND o.received_order >= extract(epoch FROM %s::timestamptz)
          AND b.is_current AND b.state='active' AND b.sync='synchronized'""",
        (venues, contract, contract, at, at + timedelta(hours=72),
         at - timedelta(seconds=NATIVE_BOOK_MAX_AGE_SECONDS))).fetchall()
    if not rows:
        return [], {}
    frame = CurrentRowStore(db).capture(include_depth=False,
        event_ids=list({row['event_id'] for row in rows}), contract_ids=[row['id'] for row in rows])
    return frame['records'], {row['id']: [row[field] for field in ('price', 'contract', 'event')] for row in rows}


def scheduled_occurrence(record):
    event, quote = record['event'], record['quote']
    market = record['market_identity']
    league = event['competition']
    if (quote['state'] != 'available' or market['period'] != 'full_game'
            or market['family'] not in ('moneyline', 'spread', 'total')
            or not supported(league, market['family'], market['period'])
            or event.get('conflicting_duplicate') or event.get('occurrence_conflict')
            or event.get('schedule_conflict') or not event.get('home') or not event.get('away')
            or event['home'] == event['away']
            or event.get('source_participant_roles') != {role: event.get(role) for role in ('home', 'away')}):
        return None
    admission = (record.get('comparison_source_metadata') or {}).get('comparison_admission') or {}
    if admission.get('supported') is False and (
            admission.get('reason') != 'comparison_context_missing'
            or not set(admission.get('missing_fields', ())) <= {'season', 'stage'}):
        return None
    return signature(event, league)


def game_signature(game):
    roles = {p['role']: p['id'] for p in game['participants'] if p['role'] in ('away', 'home')}
    if roles.keys() == {'away', 'home'}:
        return game['league'], stamp(game['start_at']), roles['home'], roles['away']
    return None


def game_for(record, occurrence, published, prior, dependencies, registry, *, has_reference):
    # Carry an existing occurrence only when its exact contract and event
    # revisions still match. A separate source-local identity covers a new game.
    if prior:
        expected = prior['current_authority']['price'].get('expected') or ()
        game = published.get(prior['game_key'])
        if len(expected) >= 3 and expected[1:3] == dependencies[1:3] and game and game_signature(game) == occurrence:
            return game
    event, source = record['event'], record['quote']['source']
    league, start, home, away = occurrence
    participants = [dict(id=team, role=role, name=registry.entities.get(team, {}).get('name', team))
                    for role, team in (('away', away), ('home', home))]
    key = (hashed([league, start.isoformat(), home, away]) if has_reference and league != 'MLB'
           else hashed([source['provider'], source['native_event_id']]))
    return dict(game_key='native-current:' + key, title=event.get('title') or ' vs. '.join(p['name'] for p in participants),
                league=league, start_at=start.isoformat(), participants=participants)


def overlay(db, result, owner, states, *, at, contract=None):
    """Replace native rows for this view using exact original clocks and pairs.

    The ordinary capture still owns archived evidence, arb and reviewed fees.
    No provider request, captured row, or publication pointer is written here.
    """
    from .ordinary_publication import pregame_sportsbooks, quote_authority

    venues = [venue for venue in VENUES if source_allowed(states.get(venue, {}))
              and venue not in owner.get('paused_sources', ())]
    if not venues or not owner.get('healthy') or not owner.get('active') or owner.get('global_stopped'):
        return result
    records, dependencies = active_records(db, at=at, venues=venues, contract=contract)
    if not records:
        return result
    published = {game['game_key']: game for game in result['games']}
    prior_rows = {row['current_authority']['price']['dependency']: row for row in result['rows']
                  if (row.get('source') or {}).get('provider') in VENUES}
    captured = []
    for record in records:
        if (occurrence := scheduled_occurrence(record)) is None:
            continue
        q = record['quote']
        cid = contract_id(record)
        row = dict(original_record=record, original=q['original'], source=q['source'],
                   venue=q['venue'], league=occurrence[0], times=q['times'])
        authority = quote_authority(row, dict(captured_at=at, dependencies=dependencies))
        if authority['reasons'] or authority['lifecycle']['state'] != 'scheduled' or not authority['expected']:
            continue
        captured.append((cid, row, authority, occurrence))
    if not captured:
        return result
    observations = pregame_sportsbooks(db, owner, states, at,
                                      occurrences={occurrence for _, _, _, occurrence in captured})
    registry = Registry.current()
    rows = {}
    for cid, row, authority, occurrence in captured:
        q, record = row['original_record']['quote'], row['original_record']
        market = record['market_identity']
        prior = prior_rows.get(cid)
        game = game_for(record, occurrence, published, prior, dependencies[cid], registry,
                        has_reference=bool(observations.get(occurrence)))
        published[game['game_key']] = game
        baseline = select(row, authority, observations, at=at)
        row.update(id='native-current:' + cid, kind='single', game_key=game['game_key'],
            game_title=game['title'], start_at=game['start_at'], live_native_desk=True,
            market=dict(market='winner' if market['family'] == 'moneyline' else market['family'],
                        period=market['period'], line=market.get('line')),
            selection=dict({'result_interpretation': 'normal_win'}, **record['selection']),
            price_current=True, game_state='scheduled', current_reasons=[],
            current_authority=dict(price=authority, references=[]),
            book_confirmation=q.get('book_confirmation'), captured_at=at.isoformat(),
            price_revision=hashed([*dependencies[cid], authority['clock_at']]),
            economic_revision=hashed(baseline) if baseline else None,
            sportsbook_baseline=baseline, sportsbook_return_percent=baseline['return_percent'] if baseline else None,
            cost_per_normal_claim=baseline['cost'] if baseline else None,
            alternate=(record.get('comparison_source_metadata') or {}).get('alternate'))
        row.pop('original_record')
        rows[cid] = row
    retained = [row for row in result['rows'] if row['current_authority']['price'].get('dependency') not in rows]
    return dict(result, rows=retained + list(rows.values()), games=list(published.values()))
