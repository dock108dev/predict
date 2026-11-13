"""ProphetX full-game prices from the already-polled OddsLink public board."""
from collections import Counter
from datetime import timedelta
from decimal import Decimal
import re
from urllib.parse import urlsplit

from app.comparison.event_links import provider_key
from app.comparison.game_phase import sporting_phase
from app.comparison.public_sportsbook_estimate import FAMILIES, SOURCE
from app.normalization.college_registry import occurrence_registry
from app.storage.schedule_metadata import VERSION as SCHEDULE_VERSION, core
from app.storage.store import hashed, stamp
from .sportsgameodds_current_rows import SPORTS

VERSION = 'oddslink-prophetx-full-game-1'
MAX_OFFERS = 60 * 6


def live_occurrences(db, league, at):
    """Use explicitly observed sporting state from the independent native feeds."""
    newest = {}
    for row in db.execute('''SELECT scheduled_start, facts FROM current_event
        WHERE competition=%s AND provider IN ('kalshi','polymarket_us')
          AND scheduled_start::timestamptz BETWEEN %s AND %s''', (league, at-timedelta(hours=4), at)):
        event = row['facts']
        if event.get('schedule_conflict') or event.get('occurrence_conflict') or event.get('neutral_venue'):
            continue
        state = sporting_phase(event)['state']
        if state not in ('live', 'final', 'suspended'):
            continue
        start = stamp(row['scheduled_start'])
        clock = (event.get('status') or {}).get('observed_at')
        if not clock or not start <= stamp(clock) <= at:
            continue
        key = (start, event['home'], event['away'])
        instant = stamp(clock)
        previous = newest.get(key)
        if previous is None or (instant, state != 'live') > (previous[0], previous[1] != 'live'):
            newest[key] = (instant, state)
    # The clock here is for event state. The shorter live price clock is
    # independently enforced by the ordinary publication at read time.
    return {key: instant for key, (instant, state) in newest.items()
            if state == 'live' and at - instant <= timedelta(minutes=30)}


def keep_unchanged_schedule(db, rows):
    """Reuse an existing exact schedule witness while its statement still agrees."""
    events = {row['event']['id']: row['event'] for row in rows}
    for row in db.execute('''SELECT native_event_id, facts FROM current_event
        WHERE provider=%s AND native_event_id=ANY(%s)''', (SOURCE, list(events))):
        previous = row['facts']
        event = events[row['native_event_id']]
        if (not previous.get('schedule_conflict') and previous.get('schedule_metadata')
                and previous['scheduled_start'] == event['scheduled_start'] and core(previous) == core(event)):
            event['schedule_metadata'] = previous['schedule_metadata']


def records(capture, *, live=None, families=FAMILIES.values()):
    league = capture['sport_key'].upper()
    received = capture['received_at']
    generated, at = stamp(capture['generated_at']), stamp(received)
    if league not in SPORTS or generated > at or at-generated > timedelta(minutes=2):
        return []
    fixtures = capture['fixtures']
    ids = Counter(fixture['id'] for fixture in fixtures)
    output = []
    for fixture in fixtures:
        if ids[fixture['id']] != 1:
            continue
        try:
            output.extend(fixture_records(fixture, capture, league, live or {}, families))
        except (AttributeError, KeyError, TypeError, ValueError, ArithmeticError):
            # Isolate one malformed fixture from the rest of the board.
            continue
    return output


def fixture_records(fixture, capture, league, live, families):
    event_id = fixture['id']
    if (fixture['sport_key'].upper() != league or not isinstance(event_id, str)
            or not re.fullmatch(r'[A-Za-z0-9:_-]{1,160}', event_id)):
        return []
    books = [book for book in fixture['bookmakers'] if book['key'] == 'prophetx']
    if len(books) != 1 or books[0]['kind'] != 'exchange':
        return []
    book, = books
    source_at = book['last_update']
    start, observed = stamp(fixture['commence_time']), stamp(source_at)
    received, digest = capture['received_at'], capture['sha256']
    if observed > stamp(capture['generated_at']):
        return []
    names = {role: fixture[role+'_team'] for role in ('home', 'away')}
    registry = occurrence_registry()
    teams = {}
    for role, name in names.items():
        resolved = registry.resolve('team', name, league=league)
        teams[role] = resolved.canonical_id or SOURCE+':'+event_id+':'+role
    if len(set(teams.values())) != 2 or len(set(names.values())) != 2:
        return []
    started = start <= stamp(received)
    live_at = live.get((start, teams['home'], teams['away']))
    if started:
        if fixture['in_play'] is not True or not live_at or observed < start:
            return []
    elif fixture['in_play'] is not False or observed >= start:
        return []
    event = dict(id=event_id, competition=league, sport=SPORTS[league], season=None, stage=None,
                 scheduled_start=fixture['commence_time'], **teams,
                 participants={name: teams[role] for role, name in names.items()},
                 title=names['away']+' at '+names['home'], status=dict(live=started))
    if started:
        event['status']['observed_at'] = live_at.isoformat()
    witness = dict(version=SCHEDULE_VERSION, native_event_id=event_id, authority=[SOURCE, 'event', event_id],
                   start=event['scheduled_start'], received_at=received, proofs=[dict(
                       path='oddslink/public/board/'+league.lower(), body_sha256=digest, received_at=received)])
    event['schedule_metadata'] = dict(witness, revision=hashed(witness))
    link = urlsplit(book.get('link', ''))
    market_link = (dict(host=link.hostname, path=link.path) if link.scheme == 'https'
                   and link.netloc in ('prophetx.co', 'www.prophetx.co') and len(link.path) <= 256 else None)
    output = []
    for market, family in FAMILIES.items():
        outcomes = book['markets'].get(market, [])
        if family not in families or len(outcomes) != 2:
            continue
        sides = {}
        for outcome in outcomes:
            label = outcome['name']
            role = (label.casefold() if family == 'total' else
                    next((role for role, team in names.items() if team == label), None))
            price = outcome['price']
            point = outcome.get('point')
            if role is None or type(price) is not int or not 100 <= abs(price) <= 100000:
                break
            if (family == 'moneyline') != (point is None):
                break
            if point is not None:
                point = Decimal(str(point))
                if not point.is_finite() or abs(point) > 1000:
                    break
            sides[role] = (label, price, point)
        roles = ('over', 'under') if family == 'total' else ('home', 'away')
        if set(sides) != set(roles):
            continue
        line, opposite = (sides[role][2] for role in roles)
        if (family == 'spread' and line != -opposite) or (family == 'total' and line != opposite):
            continue
        selections = [dict(label=sides[role][0], participant=teams.get(role),
                           predicate={'spread':'cover', 'moneyline':'win'}.get(family, role),
                           signed_line=line_text(sides[role][2])) for role in roles]
        identity = dict(event=provider_key(SOURCE, event), sport=event['sport'], competition=league,
                        season=None, stage=None, scheduled_start=event['scheduled_start'], family=family,
                        period='full_game', line=line_text(line), outcome_set=hashed(selections), rules=VERSION)
        mid = hashed([event_id, family, identity['line']])
        for role, selection in zip(roles, selections, strict=True):
            source = dict(provider=SOURCE, native_event_id=event_id, native_market_id=mid, native_outcome_id=role,
                          native_side='bookmaker_outcome', native_line=selection['signed_line'], quote_side='buy',
                          binding_version=VERSION, binding_id=hashed([mid, role]))
            quote = dict(id='', revision=1, venue='prophetx', source=source, state='available',
                         original=dict(value=f"{sides[role][1]:+d}", units='american_odds', payout='1',
                                       payout_units='USD', quantity_units='unknown', role='comparison'),
                         times=dict(source_at=source_at, received_at=received, projected_at=None,
                                    source_time_kind='provider_book'),
                         provider_clocks=dict(book=source_at, market=None, selected_basis='book'),
                         freshness_policy=dict(version=VERSION, maximum_age_seconds=900),
                         rule_note='Full-game price from the OddsLink public board. Exact settlement rules are unverified.',
                         observation_time_evidence='OddsLink bookmaker last update.',
                         provenance=dict(mode='current', real_source=True, sha256=digest))
            output.append(dict(event=event, market_identity=identity, quote=quote, selection=selection,
                               outcome_cardinality=2, outcome_selections=selections, verified=False,
                               period_boundary='OddsLink full-game main line', orientation_evidence=[VERSION],
                               result_policy=VERSION+':'+family,
                               anchor_participant=teams['home'] if family == 'spread' else None,
                               comparison_source_metadata=dict(provider_event_link=market_link),
                               event_scope=dict(policy='oddslink-provider-event-unverified-1', source=SOURCE,
                                                native_event_id=event_id)))
    return output


def line_text(value):
    return None if value is None else format(value.normalize() if value else Decimal(0), 'f')
