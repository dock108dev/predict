"""Read-only Polymarket US catalog bindings for exact Dashboard contracts."""

import asyncio
import json
import re
from collections import defaultdict
from datetime import timedelta
from email.utils import parsedate_to_datetime
from fractions import Fraction as F
from urllib.parse import urlsplit

from app.adapters import polymarket_us as pmus
from app.comparison import execution_contract, scanner_polymarket
from app.comparison.native_scoring_scope import source_rules
from app.dashboard.session_projection import stable
from app.storage.store import stamp

from .admission_enrichment import resolve_team, source_team_label, us_score
from .native_experiment_depth import ERRORS, _pmus_fee
from .native_selectors import LEAGUES
from .public_fee_refresh import REVIEW_WINDOW

IDENTITY_AGE = timedelta(seconds=60)
DOCUMENT_BYTES = 3 * 1024 * 1024
PAGE_SIZE = 20
MAX_PAGES = 3
MAX_BOOKS = 4
MAX_TRACKED_SLOTS = 128
WINNER = re.compile(r'^This market will settle to the winner of the (.+?) vs\.? (.+?) game\b')


class BookSelector:
    """Rotate a small REST book allowance across main and alternate strikes."""

    def __init__(self):
        self.offsets = {}

    def select(self, scope, bindings, events):
        slated = {cid: b for cid, b in bindings.items() if b['venue'] == 'polymarket_us' and not b['reason']}
        if not slated:
            return bindings
        main = {slated[cid]['market_id'] for rows in events.values() for cid, _, record in rows
                if cid in slated and (record.get('comparison_source_metadata') or {}).get('alternate') is False}
        alternate = {b['market_id'] for b in slated.values()} - main
        main_count = min(len(main), MAX_BOOKS - int(bool(alternate)))
        alternate_count = min(len(alternate), MAX_BOOKS - main_count)
        main_count = min(len(main), MAX_BOOKS - alternate_count)
        main_offset, alternate_offset = self.offsets.pop(scope, (0, 0))

        def rotate(values, offset, count):
            ordered = sorted(values)
            return {ordered[(offset+position) % len(ordered)] for position in range(count)}

        selected = rotate(main, main_offset, main_count) | rotate(alternate, alternate_offset, alternate_count)
        self.offsets[scope] = main_offset+main_count, alternate_offset+alternate_count
        if len(self.offsets) > MAX_TRACKED_SLOTS:
            self.offsets.pop(next(iter(self.offsets)))
        return {cid: dict(b, reason='native_book_capacity') if cid in slated and b['market_id'] not in selected else b
                for cid, b in bindings.items()}


def _open(row):
    return (row.get('active') is True and row.get('closed') is False
            and row.get('archived') is False and row.get('live') is not True)


def _role_binding(event, league, slug):
    binding = pmus.event_game_binding(event, slug, live_bindings=True)
    teams = binding['teams']
    if (binding['basis'] != 'embedded_full_game_side_team_ids'
            or {team['ordering'] for team in teams} != {'home', 'away'}):
        raise ValueError('polymarket_us_event_roles_unverified')
    roles = {team['ordering']: resolve_team(team, league, 'polymarket_us') for team in teams}
    ids = {team['ordering']: str(team['id']) for team in teams}
    if not all(roles.values()) or len(set(roles.values())) != 2:
        raise ValueError('polymarket_us_event_roles_unverified')
    return roles, ids, teams


def _compatible_group(event, winner, start):
    return (event.get('period') == 'NS' and _open(event)
            and execution_contract.clock(event['startTime']) == start
            and event.get('gameId') == winner.get('gameId')
            and event.get('sportradarGameId') == winner.get('sportradarGameId'))


def _proof_clock(evidence, cutoff):
    received = stamp(evidence['received_at'])
    headers = evidence['headers']
    date = parsedate_to_datetime(headers['date'])
    age = int(headers.get('age', '0'))
    publisher = min(received-timedelta(seconds=age), date)
    if age < 0 or date > received or not received <= cutoff < publisher+IDENTITY_AGE:
        raise ValueError('polymarket_us_catalog_stale')
    return publisher+IDENTITY_AGE


async def _family(client, slug, kind, start, end, cutoff):
    matched = {}
    evidence = None
    try:
        for page in range(MAX_PAGES):
            # The public gateway currently applies only the first repeated
            # sportsMarketTypes field. Each request supplies one exact type.
            params = dict(tagSlug=slug, active='true', closed='false', period='NS',
                startTimeMin=(start-timedelta(seconds=1)).isoformat(),
                startTimeMax=(end+timedelta(seconds=1)).isoformat(), orderBy='startTime',
                limit=PAGE_SIZE, offset=PAGE_SIZE*page, sportsMarketTypes=kind)
            body, evidence, reason = await client._read('polymarket_us', pmus.GATEWAY+'/v1/events', cutoff,
                params=params, body_limit=DOCUMENT_BYTES)
            if reason:
                return {}, evidence, reason
            expiration = _proof_clock(evidence, cutoff)
            # Transport uses Decimal for exact JSON numerics. Admit exact
            # number text before reusing the shared stable market witness.
            events = json.loads(json.dumps(body['events'], default=str))
            if not isinstance(events, list) or len(events) > PAGE_SIZE:
                return {}, evidence, 'native_catalog_invalid'
            for event in events:
                eid = pmus.identifier(event['id'])
                if eid in matched:
                    return {}, evidence, 'native_catalog_invalid'
                matched[eid] = event, evidence, expiration
            if len(events) < PAGE_SIZE:
                return matched, evidence, None
    except ERRORS as error:
        return {}, evidence, 'stale' if str(error) == 'polymarket_us_catalog_stale' else 'native_catalog_invalid'
    return {}, evidence, 'native_book_capacity'


def _outcomes(market, family, event, roles, ids, start):
    mid = pmus.identifier(market['id'])
    if (not _open(market) or market.get('isCombo') is True
            or execution_contract.clock(market['gameStartTime']) != start):
        return []
    sides = {side['long']: side for side in market['marketSides']}
    if (set(pmus.side_ids(market)) != {True, False}
            or any(pmus.identifier(side['marketId']) != mid for side in sides.values())):
        return []
    role_by_id = {identity: role for role, identity in ids.items()}
    long_role, short_role = (role_by_id.get(str(sides[long].get('teamId'))) for long in (True, False))
    if family != 'total':
        if {long_role, short_role} != {'home', 'away'} or any(
            pmus.identifier(side['team']['id']) != str(side['teamId'])
            or side['team'].get('ordering') not in (None, role_by_id[str(side['teamId'])])
            or resolve_team(side['team'], event['competition'], 'polymarket_us') != roles[role_by_id[str(side['teamId'])]]
            for side in sides.values()):
            return []
    if family == 'moneyline':
        wording = market['description']
        match = WINNER.match(wording)
        if not match or any(fragment in wording.casefold() for fragment in
              ('first half', 'second half', 'end of regulation', 'first 5 innings')):
            return []
        first = source_team_label(match[1], event)
        words = match[2].split()
        second = {team for i in range(1, len(words)+1)
                  if (team := source_team_label(' '.join(words[:i]), event))}
        if len(second) != 1 or second | {first} != set(roles.values()):
            return []
        return [(long_role, None, True, 'winner'), (short_role, None, False, 'winner')]
    fact = us_score(market, dict(family=family, period='full_game', total_scope='combined'), event)
    if not fact:
        return []
    line = F(fact['line'])
    equality = fact['equality_treatment']
    if family == 'spread':
        return [(long_role, line, True, equality), (short_role, -line, False, equality)]
    if any(side.get('teamId') is not None for side in sides.values()):
        return []
    return [('over', line, True, equality), ('under', line, False, equality)]


def _settlement(market, rule, predicate):
    text = market['description']
    wording = text.casefold()
    league, family = rule['league'], rule['family']
    settlement = dict(available=rule.get('evidence_available') is True, rule_id=rule['source_sha256'],
        evidence=rule.get('evidence'), overtime='unknown', extra_innings='unknown',
        shootout='unknown', equality='unknown', native_rules=text)
    if 'overtime is included if played.' in wording or 'overtime and any shootout are included if played.' in wording:
        settlement['overtime'] = 'included'
    if 'extra innings are included if played.' in wording or 'extra innings are included.' in wording:
        settlement.update(overtime='not_applicable', extra_innings='included')
    if league == 'NHL':
        if family == 'moneyline' and 'overtime and any shootout are included if played.' in wording:
            settlement['shootout'] = 'official_final_score'
        elif 'if a shootout determines the winner, the shootout will count as one goal for the winning team.' in wording:
            settlement.update(shootout='official_final_score', shootout_count='one_goal_to_winning_team')
    if any(fragment in wording for fragment in ('regulation only', 'overtime is excluded',
           'overtime is not included', 'extra innings are not included', 'shootout does not count')):
        settlement.update(available=False, reason='native_settlement_equivalence_unverified')
    if predicate == 'winner':
        if 'if the game ends in a tie, the market will settle to $0.50.' in wording:
            settlement['equality'] = 'half_face'
        elif league != 'NFL' and 'tie' not in wording:
            settlement['equality'] = 'not_feasible'
    elif predicate == 'unreachable':
        settlement['equality'] = 'not_possible'
    elif predicate == 'refund':
        # The literal establishes a push. It does not identify, by itself,
        # which entry fees would be returned under this account's schedule.
        settlement['equality'] = 'push_refund'
    elif predicate == 'predicate':
        settlement['equality'] = 'predicate'
    return settlement


def _binding(market, *, eid, cid, expected, is_long, predicate, rule, fee,
             role_proof, family_proof, expiry):
    sides = pmus.side_ids(market)
    mid = pmus.identifier(market['id'])
    slug = pmus.identifier(market['slug'])
    if len(slug) > 200 or urlsplit(slug).scheme or '/' in slug:
        raise ValueError('polymarket_us_market_locator_invalid')
    tick = F(market['orderPriceMinTickSize'])
    probe = scanner_polymarket.MINIMUM_PRICE
    if tick > probe:
        probe = tick
    # Share the scanner's validated fractional contract and fee price grid.
    original = dict(units='usd_per_contract', quantity_units='contracts', payout_units='USD',
        payout='1', value=str(probe), transformation='one_minus_native_bid',
        native_units='usd_per_contract', native_value=str(1-probe))
    grid = scanner_polymarket._grid(dict(original=original), dict(long=is_long, values=market))
    return dict(venue='polymarket_us', event_id=eid, market_id=mid, route=slug,
        outcome_id=sides[is_long], opposite_outcome_id=sides[not is_long], native_side='Long' if is_long else 'Short',
        market_revision=stable(market), binding_method='public_pmus_typed_event_and_selected_side',
        scheduled_start=expected['starts_at'], terms_valid_until=expiry.isoformat(),
        contract_id=cid, contract=dict(expected, phase='pregame', settlement=_settlement(market, rule, predicate)),
        fee=fee, currency='USD', payout_usd='1', quantity_increment=grid['increment'], quantity_minimum=grid['minimum'],
        price_bands=[[grid['minimum_price'], grid['maximum_price'], grid['tick']]],
        identity_receipts=[role_proof, family_proof], levels=[], receipts=[], reason=None, complete=False)


def _main_market(event, markets, family):
    """Verify the venue's own signed full-game line and its exact market ID."""
    groups = event.get('marketGroups') or []
    if family == 'moneyline':
        primary = [group for group in groups if isinstance(group, dict) and group.get('id') == 'PRIMARY']
        candidates = [m['id'] for m in markets if len(primary) == 1
                      and m['id'] in (primary[0].get('marketIds') or ()) and _open(m)]
        return candidates[0] if len(candidates) == 1 else None
    group_id = f"game-lines/{'spread' if family == 'spread' else 'totals'}/full-game"
    field = 'mainSpreadLine' if family == 'spread' else 'mainTotalLine'
    try:
        game_state = event['metadata']['gameState']
        if (str(game_state['gameId']) != str(event['gameId'])
                or game_state['sportradarGameId'] != event['sportradarGameId']):
            return None
        group, = [group for group in groups if group.get('id') == group_id and group.get('live') is False]
        stat, = [stat for stat in game_state['marketGroupStats'] if stat.get('marketGroupId') == group_id]
        line = F(game_state[field])
        if F(group['line']) != line or F(stat['line']) != line:
            return None
        (market_id,) = [m['id'] for m in markets if m['id'] in group['marketIds']
                        and _open(m) and m.get('line') is not None and F(m['line']) == line]
        return market_id
    except ERRORS:
        return None


async def read(client, league, events, *, at, cutoff, products, discover_window=None):
    """Read only the scheduled candidate window and bind complete native sides."""
    slug = LEAGUES.get(league)
    if not slug:
        return {}
    keys = defaultdict(lambda: defaultdict(list))
    starts = set()
    for rows in events.values():
        for cid, _, record in rows:
            if record['quote']['venue'] != 'polymarket_us':
                continue
            try:
                event = record['event']
                expected = execution_contract.expected(record)
                start = stamp(event['scheduled_start'])
                if expected['league'] != league or expected['period'] != 'full_game' or start <= at:
                    continue
                signed = expected['signed_line']
                key = expected['family'], expected['selected_side'], F(signed) if signed is not None else None
                keys[(start, event['home'], event['away'])][key].append((cid, expected))
                starts.add(start)
            except ERRORS:
                continue
    if not starts and discover_window is None:
        return {}
    types = dict(zip(('moneyline', 'spread', 'total'), pmus.full_game_types(slug), strict=True))
    present = {key[0] for strikes in keys.values() for key in strikes}
    requested = {family: kind for family, kind in types.items()
                 if discover_window is not None or family in present or family == 'moneyline'}
    start_window, end_window = discover_window if discover_window else (min(starts), max(starts))
    scans = dict(zip(requested, await asyncio.gather(*(
        _family(client, slug, kind, start_window, end_window, cutoff) for kind in requested.values())), strict=True))
    catalog = {family: result[0] for family, result in scans.items()}
    now = client.now()
    try:
        fee = _pmus_fee(products, now)
    except ERRORS as error:
        reason = str(error) if isinstance(error, ValueError) and str(error).startswith('polymarket_') else 'polymarket_us_fee_unverified'
        fee = dict(model='polymarket_us_standard_taker_bound', reason=reason)
    fee_until = stamp(fee['observed_at'])+REVIEW_WINDOW if fee.get('observed_at') else cutoff+IDENTITY_AGE

    rules = {r['native_type']: r for r in source_rules(detached=False)
             if r['provider'] == 'polymarket_us' and r['league'] == league and r['period'] == 'full_game'}
    occurrences = defaultdict(list)
    for eid, (winner, witness, expires) in catalog['moneyline'].items():
        try:
            start = execution_contract.clock(winner['startTime'])
            if not _compatible_group(winner, winner, start):
                continue
            roles, ids, teams = _role_binding(winner, league, slug)
            occurrence = stamp(winner['startTime']), roles['home'], roles['away']
            in_window = start_window <= occurrence[0] < end_window or start_window == end_window == occurrence[0]
            if occurrence in keys or discover_window is not None and in_window:
                occurrences[occurrence].append((eid, winner, witness, expires, roles, ids, teams))
        except ERRORS:
            continue
    output = {}
    for strikes in keys.values():
        for (family, _, _), entries in strikes.items():
            _, proof, failure = scans['moneyline'] if scans['moneyline'][2] else scans[family]
            if failure:
                for cid, _ in entries:
                    output[cid] = dict(venue='polymarket_us', reason=failure, complete=False, levels=[],
                                       receipts=[proof] if proof else [])
    for occurrence, options in occurrences.items():
        if len(options) != 1:
            continue
        eid, winner, witness, expires, roles, ids, teams = options[0]
        start = execution_contract.clock(winner['startTime'])
        source_event = dict(competition=league, participants=roles, _native=dict(teams=teams))
        matches = defaultdict(list)
        for family, kind in requested.items():
            listing = catalog[family].get(eid)
            rule = rules.get(kind)
            if not listing or not rule:
                continue
            row, evidence, listing_expiry = listing
            try:
                if not _compatible_group(row, winner, start):
                    continue
                markets = [m for m in row.get('markets', ()) if m.get('sportsMarketType') == kind]
                if (len({str(m.get('id')) for m in markets}) != len(markets)
                        or len({m.get('slug') for m in markets}) != len(markets)):
                    continue
                main_market_id = _main_market(row, markets, family) if discover_window is not None else None
            except ERRORS:
                continue
            for market in markets:
                try:
                    for side, line, is_long, predicate in _outcomes(market, family, source_event, roles, ids, start):
                        selections = keys[occurrence].get((family, side, line), ())
                        discovered = None
                        if discover_window is not None:
                            from .native_trading_identity import native_event, record, expected as exact

                            labels = {team['ordering']: team['name'] for team in teams}
                            native = native_event('polymarket_us', eid, league, occurrence[0], roles, labels,
                                proof=dict(witness, native_team_ids=ids),
                                shared={'sportradar': str(winner['sportradarGameId'])}
                                if winner.get('sportradarGameId') else {})
                            discovered = record('polymarket_us', native, pmus.identifier(market['id']),
                                pmus.side_ids(market)[is_long], 'Long' if is_long else 'Short',
                                family, side, line, settlement=_settlement(market, rule, predicate),
                                main=market['id'] == main_market_id if main_market_id is not None else None)
                            if main_market_id is not None:
                                discovered['comparison_source_metadata']['main_line_witness'] = dict(
                                    native_market_id=str(main_market_id), source_sha256=evidence['sha256'],
                                    source_url=evidence['url'])
                            expectation = exact(discovered)
                            selections = [*selections, (expectation['contract_id'], expectation)]
                        for cid, expected in selections:
                            binding = _binding(market, eid=eid, cid=cid, expected=expected,
                                is_long=is_long, predicate=predicate, rule=rule, fee=fee,
                                role_proof=dict(witness, participants=roles, native_team_ids=ids),
                                family_proof=evidence, expiry=min(expires, listing_expiry, fee_until, occurrence[0]))
                            if discovered is not None and cid == expectation['contract_id']:
                                binding['_record'] = discovered
                            matches[cid].append(binding)
                except ERRORS:
                    continue
        output.update((cid, bindings[0]) for cid, bindings in matches.items() if len(bindings) == 1)
    return output
