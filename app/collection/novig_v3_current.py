"""Read-only signed Novig producer for the ordinary current-row owner."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
import re
import time
from urllib.parse import quote, urlencode

import httpx
from websockets.exceptions import WebSocketException

from app.comparison.event_links import provider_key
from app.comparison.snapshot_novig_live import live_fee
from app.storage.store import hashed, stamp
from .current_ingress import call
from .current_policy import aggregate_scope
from .novig_v3_public import HOST, MAX_BODY
from .novig_v3_stream import load_read_key, read_only_stream, signed_headers

MARKETS = {'MONEY': 'moneyline', 'SPREAD': 'spread', 'TOTAL': 'total'}
MAX_MARKETS = 12
VERSION = 'novig-v3-current-1'
SPORT = dict(NFL='american_football', NCAAF='american_football', NBA='basketball',
             NCAAB='basketball', MLB='baseball', NHL='ice_hockey')


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,80}', value):
        raise ValueError('novig_catalog_identity')
    return value


def selections(market, competitors, roles):
    family = MARKETS[market['marketType']]
    line = market.get('strike')
    if family == 'moneyline':
        if line is not None:
            raise ValueError('novig_moneyline_strike')
    elif not isinstance(line, str) or not Decimal(line).is_finite():
        raise ValueError('novig_line_invalid')
    outcomes = market['outcomes']
    if len(outcomes) != 2 or len({identity(o['outcomeId']) for o in outcomes}) != 2:
        raise ValueError('novig_outcomes_invalid')
    result = {}
    for outcome in outcomes:
        label = outcome['name']
        if not isinstance(label, str) or not 0 < len(label) <= 180 or outcome['status'] != 'TBD':
            raise ValueError('novig_outcome_unavailable')
        if family == 'total':
            side, mark = label.rsplit(' ', 1)
            if side not in ('Over', 'Under') or Decimal(mark) != Decimal(line):
                raise ValueError('novig_total_side')
            participant, predicate, signed = None, side.lower(), line
        else:
            name, signed = label.rsplit(' ', 1) if family == 'spread' else (label, None)
            matches = [cid for cid, team in competitors.items()
                       if market['marketId'] in team['marketIds']
                       and name in (team['name'], team.get('shortName'), team.get('symbol'))]
            if len(matches) != 1 or matches[0] not in roles.values():
                raise ValueError('novig_team_side')
            participant, predicate = matches[0], 'cover' if signed is not None else 'win'
            if signed is not None and (not Decimal(signed).is_finite() or abs(Decimal(signed)) != abs(Decimal(line))):
                raise ValueError('novig_spread_side')
        result[outcome['outcomeId']] = dict(label=label, participant=participant, predicate=predicate, signed_line=signed)
    sides = list(result.values())
    if family == 'total' and {s['predicate'] for s in sides} != {'over', 'under'}:
        raise ValueError('novig_total_pair')
    if family != 'total' and {s['participant'] for s in sides} != set(roles.values()):
        raise ValueError('novig_team_pair')
    anchor = None
    if family == 'spread':
        if sum(Decimal(s['signed_line']) for s in sides):
            raise ValueError('novig_spread_pair')
        # At pick'em either anchor has the same threshold; home is canonical.
        anchor = roles['home'] if Decimal(line) == 0 else next(
            s['participant'] for s in sides if Decimal(s['signed_line']) == Decimal(line))
    return result, anchor


def records_for_book(owner, event, market, participants, *, terms_at, at, runtime_id):
    """Normalize only directly bound full-game sides and a signed post-reset image."""
    eid, mid = identity(event['eventId']), identity(market['marketId'])
    league = event['league']
    starts = event['startsTs']
    if (event['status'] != 'OPEN_INGAME' or market['status'] != 'OPEN'
            or type(starts) is not int or market['startsTs'] != starts
            or market['eventId'] != eid or participants['eventId'] != eid
            or (eid, mid) != (owner.event_id, owner.market_id) or not owner.book_source_at):
        return []
    start = datetime.fromtimestamp(starts / 1000, timezone.utc).isoformat()
    if not stamp(start) <= stamp(owner.book_source_at) <= stamp(owner.book_at):
        return []
    sides = participants['competitors']
    teams = {identity(v['competitorId']): v for v in sides}
    roles = {r: identity(participants[r + 'CompetitorId']) for r in ('home', 'away')}
    if len(sides) != 2 or set(teams) != set(roles.values()):
        return []
    names = {v['name']: k for k, v in teams.items()}
    if len(names) != 2 or any(not isinstance(n, str) or not 0 < len(n) <= 180 for n in names):
        return []
    choices, anchor = selections(market, teams, roles)
    facts = dict(id=eid, sport=SPORT[league], competition=league, season=None, stage=None,
                 scheduled_start=start, participants=names, **roles,
                 title=teams[roles['away']]['name'] + ' at ' + teams[roles['home']]['name'],
                 source_participant_roles=roles, status={'live': True})
    family, line = MARKETS[market['marketType']], market.get('strike')
    sides = list(choices.values())
    market_identity = dict(event=provider_key('novig', facts), sport=facts['sport'], competition=league,
                           season=None, stage=None, scheduled_start=start, family=family, period='full_game',
                           line=line, outcome_set=hashed(choices), rules=VERSION)
    result = []
    for oid, selection in choices.items():
        evidence = owner.evidence(event, market, oid, at=owner.book_at)
        if evidence is None:
            continue
        evidence['terms_at'] = terms_at
        source = dict(provider='novig', native_event_id=eid, native_market_id=mid, native_outcome_id=oid,
                      native_side='buy', quote_side='buy', native_line=line, binding_version=VERSION,
                      binding_id=hashed([eid, mid, oid, selection]))
        original = dict(value=evidence['price'], units='usd_per_contract', payout='1',
                        payout_units='USD', quantity_units='novig_v3_cent_contracts', role='comparison')
        check = dict(source=source, original=original, market=dict(market='winner' if family == 'moneyline' else family,
                                                                  period='full_game', line=line))
        if not live_fee(check, stamp(at), evidence)['available']:
            continue
        q = dict(id='', revision=1, venue='novig', source=source, original=original,
                 times=dict(source_at=owner.book_source_at, received_at=owner.book_at, projected_at=None,
                            source_time_kind='provider_book'), state='available',
                 rule_note='Signed full-game book. Exceptional settlement requires separate evidence.',
                 cost_note='One immediate fill of 100 native one-cent contracts.',
                 freshness_policy=dict(version=VERSION, maximum_age_seconds=15),
                 provenance=dict(mode='current', real_source=True, sha256=hashed(evidence)),
                 novig_v3_evidence=evidence, novig_runtime_id=runtime_id)
        result.append(dict(event=deepcopy(facts), market_identity=market_identity, selection=selection,
                           period_boundary='Native full-game market', anchor_participant=anchor,
                           outcome_cardinality=2, outcome_selections=sides, verified=False, quote=q,
                           event_scope=dict(policy='native-event-unverified-2', source='novig', native_event_id=eid),
                           orientation_evidence=[VERSION+':'+hashed(participants)], result_policy=VERSION,
                           comparison_source_metadata=dict(phase='live', native_terms={'voids': market.get('voids')},
                               comparison_admission=dict(supported=False, reason='comparison_context_missing',
                                                         missing_fields=['season', 'stage']))))
    return result


class NovigCurrentWorker:
    def __init__(self, service, *, transport=None, stream=read_only_stream, key_loader=load_read_key):
        self.service = service
        self.transport, self.stream, self.key_loader = transport, stream, key_loader
        self.closed = False
        self.metrics = dict(state='initializing', subscriptions=0, live_qualified=0)

    def allowed(self):
        return (not self.closed and self.service.dispatch
                and not {'novig', 'the_odds_api'} & self.service.paused_sources)

    async def read(self, client, key, path, **params):
        if not self.allowed():
            raise asyncio.CancelledError()
        query = urlencode(sorted(params.items()), quote_via=quote)
        headers = signed_headers(*key, 'GET', path, query, timestamp_ms=time.time_ns() // 1_000_000)
        async with client.stream('GET', HOST + path + ('?' + query if query else ''), headers=headers) as response:
            response.raise_for_status()
            if response.headers.get('age', '0') != '0':
                raise ValueError('novig_signed_catalog_cached')
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BODY:
                    raise ValueError('novig_signed_catalog_body_bound')
        return json.loads(body)

    async def batch(self, client, key):
        leagues = ','.join(aggregate_scope(self.service.config))
        families = ','.join(t for t, f in MARKETS.items() if f in self.service.config['families'])
        # Subscribe before go-live. A late connection must wait for a new
        # observed reset instead of dating its initial in-game snapshot.
        now = time.time_ns() // 1_000_000
        events = await self.read(client, key, '/v3/catalog/events', league=leagues,
                                 status='OPEN_PREGAME,OPEN_INGAME,DELAYED', limit=100,
                                 startsAfter=now-3*3600_000, startsBefore=now+15*60_000)
        event_limit = min(4, self.service.config['events_per_source'])
        market_limit = min(MAX_MARKETS, self.service.config['markets_per_source'])
        nearby = sorted(events['items'], key=lambda e: (e['status']=='OPEN_INGAME', abs(e['startsTs']-now)))[:event_limit]
        self.metrics['discovery_partial'] = bool(events.get('next') or len(events['items']) > len(nearby))
        subjects = {}
        for event in nearby:
            eid = identity(event['eventId'])
            if event['league'] not in leagues.split(','):
                continue
            page = await self.read(client, key, '/v3/catalog/markets', event=eid, marketType=families, limit=20)
            self.metrics['discovery_partial'] |= bool(page.get('next'))
            for market in page['items']:
                if (market['eventId'] == eid and market['status'] == 'OPEN'
                        and market['startsTs'] == event['startsTs'] and market['marketType'] in families.split(',')):
                    mid = identity(market['marketId'])
                    if mid in subjects:
                        raise ValueError('novig_duplicate_market')
                    if len(subjects) < market_limit:
                        subjects[mid] = eid
                    else:
                        self.metrics['discovery_partial'] = True
        self.metrics.update(subscriptions=len(subjects), state='subscribed' if subjects else 'waiting', gap=None)
        if not subjects:
            return False

        active = {}
        metadata = {}
        async def update(session, frame, at):
            if not self.allowed():
                raise asyncio.CancelledError()
            affected = set(frame.get('snapshot', frame.get('delta', {}))) if frame is not None else set(active)
            previous = affected & active.keys()
            if previous:
                await call(self.service, self.service.novig_quotes, 'novig', [],
                           [(session.markets[mid].event_id, mid) for mid in sorted(previous)])
                for mid in previous:
                    active.pop(mid)
            admitted = {}
            for mid in sorted(affected):
                owner = session.markets[mid]
                have_image = owner.connected and owner.frames and 'book' in owner.frames[-1]
                if not have_image:
                    continue
                # Record actual metadata observation clocks independently of the
                # book. Refresh bounded exact metadata when the prior read ages.
                cached = metadata.get(mid)
                if cached is None or stamp(cached[3]) < stamp(owner.reset_at) or (stamp(at)-stamp(cached[3])).total_seconds() >= 8:
                    observed = datetime.now(timezone.utc).isoformat()
                    eid = owner.event_id
                    event, market, people = await asyncio.gather(
                        self.read(client, key, '/v3/catalog/events/'+eid),
                        self.read(client, key, '/v3/catalog/markets/'+mid),
                        self.read(client, key, '/v3/catalog/participants', event=eid, limit=2))
                    if people.get('next') or len(people['items']) != 1:
                        raise ValueError('novig_participant_scope_incomplete')
                    cached = event, market, people['items'][0], observed
                    metadata[mid] = cached
                try:
                    rows = records_for_book(owner, *cached[:3], terms_at=cached[3],
                                            at=datetime.now(timezone.utc).isoformat(), runtime_id=self.service.runtime_id)
                except (ValueError, KeyError, TypeError, ArithmeticError):
                    rows = []
                if rows:
                    admitted[mid] = rows
            if admitted:
                await call(self.service, self.service.novig_quotes, 'novig',
                           [row for rows in admitted.values() for row in rows], [])
                active.update((mid,len(rows)) for mid,rows in admitted.items())
            self.metrics['live_qualified'] = sum(active.values())

        await self.stream(subjects, update, key=key, duration=1800, require_provider_clock=True)
        self.metrics.update(state='waiting', gap='novig_waiting_for_observed_reset')
        return True

    async def run(self):
        async with httpx.AsyncClient(transport=self.transport, timeout=5, follow_redirects=False, trust_env=False) as client:
            while self.allowed():
                delay = 60
                try:
                    key = await asyncio.to_thread(self.key_loader)
                    if await self.batch(client, key):
                        delay = 15
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    retry = exc.response.headers.get('Retry-After', '')
                    if status == 429:
                        delay = max(60, min(int(retry), 3600)) if retry.isdigit() else 300
                    self.metrics.update(state='unavailable', gap='novig_signed_http_'+str(status))
                except (ValueError, KeyError, TypeError, OSError, httpx.HTTPError, WebSocketException, TimeoutError) as exc:
                    gap = ('novig_v3_read_key_unavailable' if str(exc) == 'novig_v3_read_key_unavailable'
                           else 'novig_signed_feed_unavailable')
                    self.metrics.update(state='unavailable', gap=gap)
                    delay = 300 if gap == 'novig_v3_read_key_unavailable' else 60
                finally:
                    self.metrics.update(subscriptions=0, live_qualified=0)
                await asyncio.sleep(delay)

    async def close(self):
        self.closed = True
