"""Project SGO prices and explicit sporting state into current-row storage."""
from copy import deepcopy
from decimal import Decimal
import re

from app.comparison.event_links import provider_key
from app.comparison.game_phase import sgo_event_status
from app.dashboard.session_projection import stable
from app.normalization.college_registry import aggregate_registry
from app.storage.schedule_metadata import VERSION as SCHEDULE_VERSION
from app.storage.store import hashed
from .sportsgameodds_adapter import PROPHETX_BOOKMAKER_ID

SPORTS = {'NFL': 'american_football', 'NCAAF': 'american_football', 'NBA': 'basketball',
          'NCAAB': 'basketball', 'MLB': 'baseball', 'NHL': 'ice_hockey'}
# Map bookmaker display names while retaining the original SGO quote identity.
# The provider's 'polymarket' is not established as Polymarket US.
CURRENT_VENUES = frozenset(('novig', PROPHETX_BOOKMAKER_ID, 'prophetx', 'pinnacle', 'kalshi'))


def display_venue(bookmaker_id):
    return 'prophetx' if bookmaker_id == PROPHETX_BOOKMAKER_ID else bookmaker_id


def source_bookmaker(record):
    return (record.get('comparison_source_metadata') or {}).get('provider_bookmaker_id', record['quote']['venue'])


def linked_event_ids(links):
    ids = {}
    novig = links.get('novig', {})
    event = re.fullmatch(
        r'/event-markets/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/sportsgameodds',
        novig.get('path', ''),
    )
    if novig.get('host') == 'novig.com' and event:
        ids['novig_event'] = event[1]
    kalshi = links.get('kalshi', {})
    event = re.fullmatch(r'/markets/(kx[a-z0-9]+)/[a-z0-9-]+/(\1-[a-z0-9-]+)', kalshi.get('path', ''))
    if kalshi.get('host') == 'kalshi.com' and event:
        ids['kalshi_event'] = event[2].upper()
    return ids


def _event_record(event, receipt_sha256, received_at, registry):
    event_id = event['event_id']
    league = event['league']
    home_name, away_name = (event['teams'][role]['name'] for role in ('home', 'away'))

    def participant(name, role):
        resolved = registry.resolve('team', name, league=league, venue='sportsgameodds')
        return resolved.canonical_id if resolved.status == 'resolved' else f'sportsgameodds:{league}:{event_id}:{role}'

    home, away = participant(home_name, 'home'), participant(away_name, 'away')
    row = dict(id=event_id, sport=SPORTS[league], competition=league, season='unverified', stage='unverified',
               scheduled_start=event['starts_at'], home=home, away=away,
               participants={home_name: home, away_name: away}, title=away_name + ' at ' + home_name,
               status=sgo_event_status(event['status']))
    linked = linked_event_ids(event.get('bookmaker_event_links', {}))
    if linked:
        row['shared_provider_ids'] = linked
    witness = dict(version=SCHEDULE_VERSION, native_event_id=event_id,
                   authority=['sportsgameodds', 'event', event_id], start=event['starts_at'], received_at=received_at,
                   proofs=[dict(path='sportsgameodds/receipt/' + receipt_sha256,
                                body_sha256=receipt_sha256, received_at=received_at)])
    row['schedule_metadata'] = dict(witness, revision=hashed(witness))
    return row


def current_rows(page, receipt_sha256):
    """Return (rows, exclusions); never declares a scope authoritative."""
    if not isinstance(receipt_sha256, str) or not re.fullmatch('[0-9a-f]{64}', receipt_sha256):
        raise ValueError('original receipt digest required')
    if page.receipt_sha256 != receipt_sha256:
        raise ValueError('receipt digest mismatch')
    events = {event['event_id']: event for event in page.events}
    groups, excluded = {}, []
    for quote in page.quotes:
        if quote['venue'] not in CURRENT_VENUES:
            excluded.append((quote['event_id'], quote['venue'], 'unsupported current-row venue'))
            continue
        if quote['price_american'] is None:
            excluded.append((quote['event_id'], quote['venue'], 'no retained price'))
            continue
        line = quote['line']
        if line is not None:
            value = Decimal(line)
            if quote['market'] == 'spread' and quote['side'] == 'away':
                value = -value
            line = '0' if value == 0 else str(value.normalize())
        venue = display_venue(quote['venue'])
        key = (quote['event_id'], venue, quote['market'], line)
        side = quote['side']
        sides = groups.setdefault(key, {})
        source_side = (quote['venue'], side)
        if source_side in sides:
            raise ValueError('duplicate same-side price at line')
        sides[source_side] = quote
    batches = []
    for (event_id, venue, family, _line), source_sides in groups.items():
        # Prefer one feed for the whole line when both spellings are present.
        bookmaker = PROPHETX_BOOKMAKER_ID if any(k[0] == PROPHETX_BOOKMAKER_ID for k in source_sides) else venue
        by_side = {side: quote for (book, side), quote in source_sides.items() if book == bookmaker}
        sides = ('over', 'under') if family == 'total' else ('home', 'away')
        pair = set(by_side) == set(sides)
        if pair:
            a, b = (by_side[side] for side in sides)
            pair = a['odd_id'] == b['opposing_odd_id'] and b['odd_id'] == a['opposing_odd_id']
            if pair and family != 'moneyline':
                pair = (a['line'] is not None and b['line'] is not None and
                        (Decimal(a['line']) == -Decimal(b['line']) if family == 'spread'
                         else Decimal(a['line']) == Decimal(b['line'])))
        # A missing, ambiguous, or conflicting opposing observation does not
        # erase a displayed source price. Each unmatched side gets its own
        # unverified group and an empty opposite-outcome descriptor.
        batches.extend([(event_id, venue, family, list(by_side.values()), True)] if pair else
                       [(event_id, venue, family, [q], False) for q in by_side.values()])
    result = []
    registry = aggregate_registry() if batches else None
    event_records = {}
    for event_id, venue, family, quotes, paired in batches:
        event = events[event_id]
        sides = ('over', 'under') if family == 'total' else ('home', 'away')
        first = quotes[0]
        if family != 'moneyline' and first['line'] is None:
            excluded.append((event_id, venue, 'missing line'))
            continue
        by_side = {q['side']: q for q in quotes}
        received_at = first['received_at']
        event_key = (event_id, received_at)
        if event_key not in event_records:
            row_event = _event_record(event, receipt_sha256, received_at, registry)
            event_records[event_key] = (row_event, provider_key('sportsgameodds', row_event))
        row_event, occurrence = event_records[event_key]
        home, away = row_event['home'], row_event['away']
        canonical = first['line']
        if family == 'spread' and first['side'] == 'away':
            canonical = str(-Decimal(canonical))
        selections = []
        for side in sides:
            if family == 'moneyline':
                line = None
            elif family == 'total' or side == 'home':
                line = canonical
            else:
                line = str(-Decimal(canonical))
            if side in by_side:
                line = by_side[side]['line']
            selections.append(dict(participant=None if family == 'total' else home if side == 'home' else away,
                                   predicate=side if family == 'total' else 'cover' if family == 'spread' else 'win',
                                   signed_line=line,
                                   label=side.title() if family == 'total' else event['teams'][side]['name']))
        identity = dict(event=occurrence, sport=row_event['sport'],
                        competition=event['league'], season='unverified', stage='unverified',
                        scheduled_start=event['starts_at'], family=family, period='full_game',
                        line=canonical, outcome_set=stable(selections), rules='sportsgameodds-unverified-1')
        policy = 'sportsgameodds-unverified-1:' + family
        if not paired:
            policy += ':single:' + stable([venue, first['odd_id'], first['line']])
        for side, selection in zip(sides, selections):
            if side not in by_side:
                continue
            quote = by_side[side]
            instrument = stable(['sportsgameodds', venue, event_id, quote['odd_id'], quote['line']])
            source = dict(provider='sportsgameodds', native_event_id=event_id,
                          native_market_id=stable([event_id, family, quote['line'], side]),
                          native_outcome_id=quote['odd_id'], native_side='bookmaker_outcome',
                          binding_id=instrument, binding_version='sgo-current-unverified-1',
                          native_line=quote['line'], quote_side='buy')
            original = dict(value=quote['price_american'], units='american_odds', payout='1', payout_units='USD',
                            quantity_units='unknown', role='comparison')
            at = quote['source_at']
            q = dict(id='', revision=1, venue=venue, source=source, original=original,
                     times=dict(source_at=at, received_at=quote['received_at'], projected_at=None,
                                source_time_kind='provider_book' if at else 'unknown'),
                     state='available' if quote['available'] else 'unavailable',
                     rule_note='SportsGameOdds aggregate full-game outcome; settlement and native occurrence association unverified.',
                     cost_note='American odds retained exactly; fees, execution and depth are unverified.',
                     observation_time_evidence='SportsGameOdds bookmaker clock; upstream delay unknown.',
                     provider_clocks=dict(book=at, market=None, selected_basis='book' if at else 'unknown'),
                     provenance=dict(mode='current', real_source=True, sha256=receipt_sha256))
            row = dict(event=deepcopy(row_event), market_identity=deepcopy(identity),
                       period_boundary='Provider full-game market; exceptional settlement unverified',
                       anchor_participant=home if family == 'spread' else None, selection=selection, quote=q,
                       orientation_evidence=['sgo-current-unverified-1', receipt_sha256], verified=False,
                       outcome_cardinality=2, outcome_selections=deepcopy(selections),
                       result_policy=policy,
                       comparison_source_metadata=dict(provider_event_aliases=list(event['aliases']),
                           provider_event_status=deepcopy(event['status']), provider_phase=event['phase'],
                           provider_source_clock_original=quote['source_at_original'],
                           provider_opposing_odd_id=quote['opposing_odd_id']),
                       event_scope=dict(policy='sgo-provider-event-unverified-1', source='sportsgameodds', native_event_id=event_id))
            if venue != quote['venue']:
                row['comparison_source_metadata']['provider_bookmaker_id'] = quote['venue']
            if market_link := quote.get('bookmaker_market_link'):
                row['comparison_source_metadata']['bookmaker_market_link'] = market_link.copy()
            if quote.get('alternate') is True:
                row['comparison_source_metadata']['alternate'] = True
            row['_instrument'] = instrument
            fingerprint = [source, original, q['state'], identity, at, quote['source_at_original'],
                           quote['opposing_odd_id'], policy, event['aliases'], event['status'], event['phase']]
            if market_link:
                fingerprint.append(market_link)
            if venue != quote['venue']:
                fingerprint.append(quote['venue'])
            if quote.get('alternate') is True:
                fingerprint.append('alternate')
            row['_fingerprint'] = stable(fingerprint)
            result.append(row)
    return result, excluded
