"""Bounded source identity diagnostics over an ordinary discovery's own bytes.

This module cannot collect, enrich, admit, or change source records. Unknown and
absent source fields remain distinct from normalized admission requirements.
"""
from copy import deepcopy
from hashlib import sha256
import json

VERSION = 'native-identity-trace-1'
MAX_BYTES = 12 * 1024
LEAGUES = ('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL')
EVENT_FIELDS = ('id', 'event_ticker', 'series_ticker', 'title', 'season', 'stage',
    'startDate', 'startTime', 'gameStartTime', 'gameId', 'sportradarGameId',
    'gameNumber', 'originalStartTime', 'rescheduledFromGameId', 'seriesSlug',
    'period', 'active', 'closed', 'live', 'ended', 'teams', 'participants')
MARKET_FIELDS = ('id', 'ticker', 'event_ticker', 'gameId', 'sportsMarketType',
    'sportsMarketTypeV2', 'marketType', 'gameStartTime', 'season', 'stage',
    'gameNumber', 'originalStartTime', 'rescheduledFromGameId', 'line',
    'yes_sub_title', 'no_sub_title', 'custom_strike', 'strike_type',
    'floor_strike', 'cap_strike', 'marketSides')
TEAM_FIELDS = ('id', 'name', 'safeName', 'league', 'ordering', 'homeAway',
               'role', 'side', 'position', 'home', 'away', 'isHome', 'isAway',
               'home_away', 'providerId', 'providerIds')
SIDE_FIELDS = ('id', 'marketId', 'long', 'teamId', 'description', 'team')
MILESTONE_FIELDS = ('id', 'category', 'type', 'source_id', 'source_provider',
    'source_ids', 'start_date', 'related_event_tickers')
DETAIL_FIELDS = ('source_id', 'source_provider', 'source_ids', 'source', 'season',
    'season_type', 'season_year', 'league',
    'home_team_id', 'away_team_id', 'main_game_event_ticker', 'game_number',
    'playoff_game_number', 'original_start', 'schedule_status', 'status')


def _bytes(value):
    # RuntimeState persists with JSON's default ASCII escaping. Budget that
    # exact representation too, including non-ASCII team names and source keys.
    return json.dumps(value, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def _bounded(value, *, depth=0):
    """Keep whole scalar values or an explicit hash/length truncation marker."""
    if depth > 5:
        return dict(truncated=True, reason='nesting_limit')
    if isinstance(value, str):
        if len(value.encode()) <= 320:
            return value
        return dict(truncated=True, type='string', bytes=len(value.encode()),
                    sha256=sha256(value.encode()).hexdigest())
    if value is None or type(value) in (bool, int, float):
        return value
    if isinstance(value, list):
        items = [_bounded(v, depth=depth+1) for v in value[:4]]
        return items if len(value) <= 4 else dict(items=items, truncated=True, omitted_items=len(value)-4)
    if isinstance(value, dict):
        # Input dictionaries are selected only through explicit field schemas.
        keys = sorted(value)[:12]
        result = {k: _bounded(value[k], depth=depth+1) for k in keys}
        if len(value) > 12:
            return dict(values=result, truncated=True, omitted_keys=len(value)-12)
        return result
    return dict(truncated=True, reason='non_json_value', type=type(value).__name__)


def _team(team):
    if not isinstance(team, dict):
        return _bounded(team)
    values = {k: team[k] for k in TEAM_FIELDS if k in team and k != 'providerIds'}
    if 'providerIds' in team:
        providers = team['providerIds']
        if isinstance(providers, list):
            values['providerIds'] = [{k: p[k] for k in ('provider', 'providerId') if k in p}
                if isinstance(p, dict) else p for p in providers[:4]]
            if len(providers) > 4:
                values['providerIds_omitted'] = len(providers)-4
        else:
            values['providerIds'] = dict(truncated=True, reason='unexpected_provider_ids_shape')
    return _bounded(values)


def _section(native, fields):
    native = native if isinstance(native, dict) else {}
    values = {}
    for key in fields:
        if key not in native:
            continue
        value = native[key]
        if key == 'teams' and isinstance(value, list):
            values[key] = [_team(t) for t in value[:4]]
            if len(value) > 4:
                values['teams_omitted'] = len(value)-4
        elif key == 'marketSides' and isinstance(value, list):
            values[key] = [{k: _team(s[k]) if k == 'team' else _bounded(s[k])
                for k in SIDE_FIELDS if k in s} if isinstance(s, dict) else _bounded(s)
                for s in value[:4]]
            if len(value) > 4:
                values['marketSides_omitted'] = len(value)-4
        elif key == 'participants':
            # This field may contain participant/team objects. Do not copy
            # ancillary attributes or arbitrary source metadata into metrics.
            values[key] = [_team(t) for t in value[:4]] if isinstance(value, list) else dict(truncated=True, reason='unexpected_participant_shape')
        elif key == 'custom_strike' and isinstance(value, dict):
            allowed = ('football_team', 'basketball_team', 'baseball_team', 'hockey_team')
            values[key] = _bounded({k: value[k] for k in allowed if k in value})
        elif key == 'season' and isinstance(value, dict):
            values[key] = _bounded({k: value[k] for k in ('id', 'name', 'year', 'type', 'week') if k in value})
        else:
            values[key] = _bounded(value)
    keys = sorted(native)
    return dict(values=values, missing_fields=[k for k in fields if k not in native],
                native_keys=[_bounded(k) for k in keys[:80]], native_keys_omitted=max(0, len(keys)-80))


def _proof(proof, row_path):
    result = {k: _bounded(proof[k]) for k in ('path', 'body_sha256', 'received_at', 'inventory_row') if k in proof}
    result['row_path'] = row_path
    return result


def _raw_rows(data, kind):
    plural = 'events' if kind == 'event' else 'markets'
    if isinstance(data.get(plural), list):
        for i, row in enumerate(data[plural]):
            yield row, '/'+plural+'/'+str(i)
    if isinstance(data.get(kind), dict):
        yield data[kind], '/'+kind
    if kind == 'market':
        for event, path in _raw_rows(data, 'event'):
            if isinstance(event, dict):
                for i, market in enumerate(event.get('markets') or []):
                    yield market, path+'/markets/'+str(i)


def _raw(record, kind, venue, decoded):
    key = 'event_ticker' if venue == 'kalshi' and kind == 'event' else 'ticker' if venue == 'kalshi' else 'id'
    proofs = record.get('provenance') or []
    for proof in reversed(proofs):
        data = decoded(proof.get('body_sha256'))
        if data is None:
            continue
        matches = [(r, path) for r, path in _raw_rows(data, kind)
                   if isinstance(r, dict) and str(r.get(key)) == record['id']]
        if len(matches) == 1:
            row, path = matches[0]
            return row, _proof(proof, path), data
    # Source metadata is still useful, but must not masquerade as a byte lookup.
    value = record.get('_native') or record.get('native_metadata') or {}
    return value, dict(lookup='catalog_native_metadata', raw_page_missing=True,
        references=[_proof(p, None) for p in proofs[:1]]), None


def _blocked(event, market):
    binding = market.get('v1_raw_binding') or {}
    return bool(event.get('exclusion') or market.get('exclusion')
        or market.get('subscription_evidence_exclusion') or binding.get('status') == 'IDENTITY_BLOCKED')


def _pool_lists(trace):
    """Repeated field-presence/key schemas occupy one source-local list pool."""
    pool = []
    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key, item in list(value.items()):
                if key in ('missing_fields', 'native_keys') and isinstance(item, list):
                    if item not in pool:
                        pool.append(item)
                    value[key+'_ref'] = pool.index(item)
                    value.pop(key)
                else:
                    visit(item)
    visit(trace['samples'])
    trace['field_sets'] = pool


def _pool_teams(trace):
    """Identical own team objects may occur in event and both market sides."""
    pool = []
    def team(value):
        if not isinstance(value, dict):
            return value
        if value not in pool:
            pool.append(value)
        return dict(trace_team_ref=pool.index(value))
    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key, item in list(value.items()):
                if key == 'teams' and isinstance(item, list):
                    value[key] = [team(t) for t in item]
                elif key == 'team' and isinstance(item, dict):
                    value[key] = team(item)
                else:
                    visit(item)
    visit(trace['samples'])
    trace['team_facts'] = pool


def _pool_proofs(trace):
    pool = []
    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key, item in list(value.items()):
                if key in ('event_proof', 'market_proof', 'proof') and isinstance(item, dict) and 'body_sha256' in item:
                    page = {k: v for k, v in item.items() if k != 'row_path'}
                    if page not in pool:
                        pool.append(page)
                    value[key] = dict(page_ref=pool.index(page), row_path=item['row_path'])
                else:
                    visit(item)
    visit(trace['samples'])
    trace['page_proofs'] = pool


def _trace_bytes(trace):
    """Discard unused pooled schemas after an explicit diagnostic omission."""
    tables = {'missing_fields_ref': 'field_sets', 'native_keys_ref': 'field_sets',
              'trace_team_ref': 'team_facts', 'page_ref': 'page_proofs'}
    used = {table: set() for table in tables.values()}
    def walk(value, remap=None):
        if isinstance(value, list):
            for item in value:
                walk(item, remap)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key in tables:
                    table = tables[key]
                    if remap is None:
                        used[table].add(item)
                    else:
                        value[key] = remap[table][item]
                else:
                    walk(item, remap)
    walk(trace['samples'])
    indexes = {table: sorted(values) for table, values in used.items()}
    walk(trace['samples'], {table: {old: new for new, old in enumerate(values)} for table, values in indexes.items()})
    for table, values in indexes.items():
        trace[table] = [trace[table][index] for index in values]
    return _bytes(trace)


def identity_trace(catalog, venue, *, pages=(), selected=(), selected_events=(), pass_number=0, byte_cap=MAX_BYTES):
    """One rotating sample per present league, within one fixed source budget.

    ``pages`` are already collected ordinary discovery receipts. Explicit field
    absence is reported only against the captured raw row, never guessed from a
    blocker. A missing receipt lookup is labeled as catalog metadata fallback.
    """
    if venue not in ('kalshi', 'polymarket_us'):
        raise ValueError('Native source required')
    if type(byte_cap) is not int or not 2048 <= byte_cap <= MAX_BYTES:
        raise ValueError('Identity trace byte bound must be 2048..12288')
    if type(pass_number) is not int or pass_number < 0:
        raise ValueError('Nonnegative discovery pass required')
    selected, selected_events = set(selected), set(selected_events)
    events = {e['id']: e for e in catalog.get('events', [])}
    groups = {league: [] for league in LEAGUES}
    for market in catalog.get('markets', []):
        event = events.get(market.get('event_id'))
        if event and event.get('competition') in groups:
            chosen = market['id'] in selected or event['id'] in selected_events
            blocked = _blocked(event, market)
            priority = 0 if blocked and chosen else 1 if blocked else 2 if chosen else 3
            groups[event['competition']].append((priority, event['id'], market['id'], event, market))
    chosen_rows = []
    for league in LEAGUES:
        rows = sorted(groups[league], key=lambda row: row[:3])
        if not rows:
            continue
        preferred = [r for r in rows if r[0] == rows[0][0]]
        chosen_rows.append((league, preferred[pass_number % len(preferred)], len(rows)))
    by_hash = {p.get('body_sha256'): p for p in pages if p.get('source') == venue}
    cache = {}
    def decoded(digest):
        if digest not in cache:
            page = by_hash.get(digest)
            try:
                from .coverage import decode_page
                # decode_page validates the original hash/envelope; parse its
                # original text again to keep raw JSON pointer paths exact even
                # for singular routes whose catalog reader adds plural aliases.
                cache[digest] = json.loads(decode_page(page)[0]) if page else None
            except (KeyError, ValueError, TypeError):
                cache[digest] = None
        return cache[digest]
    result = dict(version=VERSION, source=venue, discovery_pass=pass_number,
        meaning='Own source identity facts; no inferred season, stage, occurrence or admission',
        samples=[], omitted_samples=0, byte_cap=byte_cap, truncated=False)
    for league, (_, _, _, event, market), count in chosen_rows:
        eraw, eproof, data = _raw(event, 'event', venue, decoded)
        mraw, mproof, _ = _raw(market, 'market', venue, decoded)
        binding = market.get('v1_raw_binding') or {}
        sample = dict(league=league, event_id=_bounded(event['id']), market_id=_bounded(market['id']),
            selected=market['id'] in selected, event_selected=event['id'] in selected_events,
            blocked=_blocked(event, market), candidates=count, rotation=pass_number,
            binding=dict(status=binding.get('status'), blockers=_bounded(binding.get('blockers') or [])),
            normalized={k: _bounded(event.get(k)) for k in ('season', 'stage', 'scheduled_start',
                'game_id', 'game_number', 'original_start', 'schedule_status', 'source_participant_roles')},
            event=_section(eraw, EVENT_FIELDS), market=_section(mraw, MARKET_FIELDS),
            event_proof=eproof, market_proof=mproof, linked_milestones=[], omitted_fields=[])
        if venue == 'kalshi':
            milestone_pages = [(data, eproof)] if data is not None else []
            for page in pages:
                if page.get('source') == venue and page.get('path') == '/trade-api/v2/milestones':
                    extra = decoded(page.get('body_sha256'))
                    if extra is not None:
                        milestone_pages.append((extra, _proof(page, None)))
            linked = [(i, m, proof) for body, proof in milestone_pages
                for i, m in enumerate(body.get('milestones') or [])
                if isinstance(m, dict) and event['id'] in (m.get('related_event_tickers') or [])]
            for index, milestone, proof in linked[:2]:
                facts = _section(milestone, MILESTONE_FIELDS)
                facts['details'] = _section(milestone.get('details'), DETAIL_FIELDS)
                facts['proof'] = dict(proof, row_path='/milestones/'+str(index))
                sample['linked_milestones'].append(facts)
            sample['linked_milestones_omitted'] = max(0, len(linked)-2)
        result['samples'].append(sample)
    _pool_lists(result)
    _pool_teams(result)
    _pool_proofs(result)
    # Keep the six league identities visible even when their complete diagnostic
    # sections do not fit. Every removed section is explicit, never a prefix that
    # could be mistaken for a full source fact or contract clause.
    removable = [('normalized',), ('market', 'native_keys_ref'), ('event', 'native_keys_ref'),
                 ('market', 'missing_fields_ref'), ('event', 'missing_fields_ref'),
                 ('market',), ('linked_milestones',), ('event',)]
    for path in removable:
        if len(_trace_bytes(result)) <= byte_cap:
            break
        for sample in sorted(result['samples'], key=lambda s: len(_bytes(s)), reverse=True):
            if len(_trace_bytes(result)) <= byte_cap:
                break
            parent = sample
            for key in path[:-1]:
                parent = parent.get(key, {})
            if path[-1] in parent:
                parent.pop(path[-1])
                sample['omitted_fields'].append('.'.join(path))
    while len(_trace_bytes(result)) > byte_cap and result['samples']:
        result['samples'].pop()
        result['omitted_samples'] += 1
    result['truncated'] = bool(result['omitted_samples'] or any(s['omitted_fields'] for s in result['samples']))
    # The flag itself must also fit the advertised bound.
    while len(_trace_bytes(result)) > byte_cap and result['samples']:
        result['samples'].pop(); result['omitted_samples'] += 1; result['truncated'] = True
    return deepcopy(result)
