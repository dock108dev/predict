"""Runtime owner for bounded SGO discovery and current-row ingestion.

Paid dispatch requires explicit fresh provider account limits and reset. This
worker does not infer absent events from pagination and never withdraws rows
from an incomplete, moving, or successful-but-not-snapshot traversal.
"""
import asyncio
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re

from .current_ingress import call, operation
from .current_policy import ROOT, aggregate_scope
from .sportsgameodds_adapter import PROPHETX_BOOKMAKER_ID, Traversal, clock_sample
from .sportsgameodds_collector import DailyObjectPacing, GuardedPageCollector, RejectedCursor
from .sportsgameodds_current_rows import current_rows
from .sportsgameodds_ledger import ObjectLedger
from .sportsgameodds_schedule import (
    PLANNED_FRACTION, REFRESH_TARGET, EventDue, SchedulePolicy, budgeted_policy, daily_allowance,
    discovery_interval, due_events, poll_slot, response_object_charge,
)
from .sportsgameodds_transport import ODD_IDS, SportsgameoddsTransport
from .sportsgameodds_transport import TransportFailure
from .sportsgameodds_usage import read_usage
from app.comparison.sgo_reference import BEST_BOOKS

ALTERNATE_REFRESH_BOOKS = ('kalshi', 'novig', PROPHETX_BOOKMAKER_ID, *BEST_BOOKS)
ALTERNATE_REFRESH_WINDOW = timedelta(hours=2)


def credential():
    key_format = r'[A-Za-z0-9_-]{1,1024}'
    from .service_secrets import read_file
    value = read_file('sportsgameodds')
    if value is not None or (value := os.environ.get('SPORTSGAMEODDS_API_KEY')):
        value = value.strip()
        if not re.fullmatch(key_format, value):
            raise ValueError('SportsGameOdds credential unavailable')
        return value
    from .credential_handoff import git_executable
    import stat
    import subprocess
    path = ROOT / '.env'
    try:
        git = git_executable()
        ignored = subprocess.run([git, 'check-ignore', '--quiet', '--no-index', '.env'], cwd=ROOT,
                                 stderr=subprocess.DEVNULL)
        tracked = subprocess.run([git, 'ls-files', '--error-unmatch', '.env'], cwd=ROOT,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ignored.returncode or tracked.returncode != 1:
            raise ValueError('SportsGameOdds credential unavailable')
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as secret:
            info = os.fstat(secret.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > 65536):
                raise ValueError('SportsGameOdds credential unavailable')
            raw = secret.read(65537)
        if len(raw) > 65536:
            raise ValueError('SportsGameOdds credential unavailable')
        lines = raw.decode('utf-8').splitlines()
    except (OSError, UnicodeError):
        raise ValueError('SportsGameOdds credential unavailable') from None
    entries = [line.split('=', 1)[1].strip().strip("\"'") for line in lines
               if re.match(r'^\s*(?:export\s+)?SPORTSGAMEODDS_API_KEY\s*=', line)]
    if len(entries) != 1 or not re.fullmatch(key_format, entries[0]):
        raise ValueError('SportsGameOdds credential unavailable')
    return entries[0]


def clock():
    return datetime.now(timezone.utc)


def pacing_reset(observed, now):
    """Use provider evidence when present; otherwise use the owner's pacing assumption."""
    if observed.get('reset_at') is not None:
        return observed['reset_at'], 'provider_reported'
    now = now.astimezone(timezone.utc)
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return datetime(year, month, 1, tzinfo=timezone.utc), 'assumed_calendar_month'


def retained_schedule(scope, now, limit):
    """Seed polling from retained receipts; never restore quote authority.

    The event frame's receipt is used only to order future polling. No
    missing event is treated as absent.
    """
    from app.storage.store import connect
    with connect() as db:
        rows = db.execute('''SELECT f.event_id AS native_event_id,
                COALESCE(f.facts->'event_context'->>'league',e.competition) AS competition,
                COALESCE(f.facts->>'starts_at',e.scheduled_start) AS scheduled_start, f.facts
            FROM current_sgo_event_frame f
            LEFT JOIN current_event e ON e.native_event_id=f.event_id AND e.provider='sportsgameodds'
            WHERE COALESCE(f.facts->'event_context'->>'league',e.competition)=ANY(%s)
              AND COALESCE(f.facts->>'starts_at',e.scheduled_start)::timestamptz >= %s
            ORDER BY COALESCE(f.facts->>'starts_at',e.scheduled_start)::timestamptz,f.event_id LIMIT %s''',
            (list(scope), now-timedelta(hours=12), limit+1)).fetchall()
    result = {}
    for row in rows[:limit]:
        facts = row['facts']; context = facts.get('event_context') or {}
        status = context.get('status') or {}
        if any(status.get(k) is True for k in ('ended', 'completed', 'cancelled')):
            continue
        event_id = row['native_event_id']
        result[event_id] = dict(event_id=event_id, league=row['competition'], starts_at=row['scheduled_start'],
                                received_at=facts['received_at'], phase=context.get('phase', 'unknown'), status=status)
    return result, len(rows) > limit


class SportsGameOddsWorker:
    ingress_source = 'sportsgameodds'
    # Free capture was >10 MB for five events; paid breadth is unmeasured.
    page_limit = 2
    max_pages = 10
    max_events = 2000

    def __init__(self, service, *, key_loader=credential, usage_reader=read_usage,
                 transport=None, ledger_path=None, now=clock):
        self.service = service
        self.key_loader = key_loader
        self.usage_reader = usage_reader
        self.transport = transport or SportsgameoddsTransport()
        self.ledger_path = Path(ledger_path or ROOT / '.local/predict-odds/sportsgameodds-ledger.sqlite3')
        self.now = now
        self.closed = False
        self.metrics = {'state':'connecting', 'requests':0, 'pages':0, 'events':0,
                        'records':0, 'excluded':0, 'next_refresh_at':None,
                        'alternate_refresh': dict(resolved_requests=0, returned_events=0,
                            received_alternate_rows=0, admitted_alternate_rows=0, admitted_available_alternate_rows=0,
                            duplicate_alternate_rows=0, conflicting_alternate_lines=0, ignored_bookmaker_groups=0,
                            largest_page_bytes=0, bookmaker_filter=list(ALTERNATE_REFRESH_BOOKS),
                            vendor_consensus_contributors='unspecified_for_filtered_response')}
        self.phase = 'initializing'
        self.ledger = None
        self.window_id = None
        self.collector = None
        self.events = {}
        self.discovery_at = {}
        self.discovery_progress = {}
        self.discovery_next_league = None
        self.schedule_policy = None
        self.key = None
        self.account_id = None
        self.request_limit = 1

    def controls(self):
        return {'stopped': self.closed or not self.service.dispatch or self.service.globally_stopped,
                'source_paused': 'sportsgameodds' in self.service.paused_sources}

    async def usage(self):
        if self.controls()['stopped'] or self.controls()['source_paused']:
            raise RuntimeError('collection stopped or source paused')
        self.ledger.reserve_request(self.account_id, requests_per_minute=self.request_limit, now=self.now())
        if self.controls()['stopped'] or self.controls()['source_paused']:
            raise RuntimeError('collection stopped or source paused')
        return await self.usage_reader(self.key)

    async def initialize(self):
        self.key = self.key_loader()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ledger = ObjectLedger(self.ledger_path)
        self.account_id = self.ledger.account_identity()
        observed = await self.usage()
        self._usage_status(observed)
        self.request_limit = observed['requests_per_minute']
        reset, reset_basis = pacing_reset(observed, self.now())
        if reset <= self.now():
            raise RuntimeError('account reset evidence expired')
        # A credential change cannot create a new accounting partition.
        self.window_id = self.account_id + ':' + reset.isoformat()
        try:
            self.ledger.status(self.window_id)
        except KeyError:
            self.ledger.create_window(self.window_id, limit=observed['limit'], initial_used=observed['used'],
                reserve=max(1, observed['limit']//10), reset_at=reset,
                requests_per_minute=observed['requests_per_minute'])
        async def pacing_usage():
            current = await self.usage()
            self._usage_status(current)
            current_reset, basis = pacing_reset(current, self.now())
            if basis != reset_basis:
                raise RuntimeError('current account usage evidence unavailable or changed')
            return dict(current, reset_at=current_reset)
        self.collector = GuardedPageCollector(self.ledger, self.window_id, self.transport,
                                              controls=self.controls, account_usage=pacing_usage)
        self.metrics.update(state='waiting', account_tier=observed.get('tier'), reset_basis=reset_basis)
        self._account_status()

    def _usage_status(self, observed):
        # Nonsecret, point-in-time provider facts; a calendar boundary remains
        # separately labeled as an assumption rather than a provider reset.
        self.metrics['provider_usage'] = {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in observed.items() if key in ('tier', 'limit', 'used', 'requests_per_minute', 'reset_at', 'at')
        }

    def _account_status(self):
        if self.ledger is None or self.window_id is None:
            return
        value = self.ledger.status(self.window_id)
        self.metrics['objects'] = {k: v.isoformat() if isinstance(v, datetime) else v for k,v in value.items()}
        self.metrics['object_holds'] = self.ledger.holds(self.window_id)
        self.metrics['object_interruptions'] = self.ledger.interruptions(self.window_id)

    @operation
    def admit(self, sport, records, reference_rows, event_frames, received_at, receipt_sha256, event_scopes):
        if self.controls()['stopped'] or self.controls()['source_paused']:
            raise asyncio.CancelledError()
        states = deepcopy(self.service.states)
        yield (dict(type='current_aggregate_records', source='sportsgameodds', sport=sport,
                    records=records, sgo_reference_rows=reference_rows, sgo_event_frames=event_frames,
                    receipt_sha256=receipt_sha256, event_scopes=event_scopes,
                    complete_venues=[], received_at=received_at), states)

    async def _publish(self, page):
        from app.dashboard.current_contract import packed
        from app.storage.sportsgameodds_reference import prepare_page, prepare_frames
        records, exclusions = current_rows(page, page.receipt_sha256)
        reference_rows = prepare_page(page)
        event_frames = prepare_frames(page, reference_rows)
        self.metrics['excluded'] += len(exclusions)
        if not records and not reference_rows and not event_frames:
            return
        # The entire page is one source-revocable transaction: prices and
        # reference evidence cannot become visible at different revisions.
        sport = page.events[0]['league']
        received_at = page.events[0]['received_at']
        event_scopes = {event['event_id']: event['league'] for event in page.events}
        envelope = dict(type='current_aggregate_records',source='sportsgameodds',sport=sport,
                        records=records,sgo_reference_rows=reference_rows,sgo_event_frames=event_frames,
                        receipt_sha256=page.receipt_sha256,event_scopes=event_scopes,complete_venues=[],received_at=received_at)
        if len(packed(envelope)) > self.service.config['ingress_bytes']:
            raise ValueError('SGO current page exceeds ingress bound')
        await call(self.service, self.admit, sport, records, reference_rows, event_frames, received_at, page.receipt_sha256, event_scopes)
        admitted_at = self.now()
        self.metrics['records'] += len(records)
        self.metrics['reference_rows'] = self.metrics.get('reference_rows', 0) + len(reference_rows)
        cohorts = self.metrics.setdefault('admitted_quote_clock_samples', {})
        self.metrics['last_clock_sample_admitted_at'] = admitted_at.isoformat()
        for (league, phase, family, venue), tally in clock_sample(page, admitted_at=admitted_at).items():
            key = ':'.join((league, phase, family, venue))
            totals = cohorts.setdefault(key, dict.fromkeys(tally, 0))
            for field, count in tally.items():
                totals[field] += count

    async def _fetch(self, params):
        self.phase = 'collecting'
        try:
            page = await self.collector.fetch(params, self.key)
            self.metrics['requests'] += 1
            self.metrics['pages'] += 1
            self.metrics['events'] += len(page.events)
            self.metrics['payload_bytes'] = self.metrics.get('payload_bytes', 0) + page.payload_bytes
            self.metrics['largest_page_bytes'] = max(self.metrics.get('largest_page_bytes', 0), page.payload_bytes)
            alternate = None
            if params.get('includeAltLines') is True:
                alternate = self.metrics['alternate_refresh']
                alternate['resolved_requests'] += 1
                alternate['returned_events'] += len(page.events)
                for target, field in (('received_alternate_rows', 'alternate_rows'),
                        ('duplicate_alternate_rows', 'duplicate_alternate_rows'),
                        ('conflicting_alternate_lines', 'conflicting_alternate_lines'),
                        ('ignored_bookmaker_groups', 'ignored_bookmaker_groups')):
                    alternate[target] += getattr(page, field)
                alternate['largest_page_bytes'] = max(alternate['largest_page_bytes'], page.payload_bytes)
            requested = set(params.get('eventIDs', '').split(',')) - {''}
            returned = {event['event_id'] for event in page.events}
            aliases = {}
            for event in page.events:
                for alias in event.get('aliases', ()):
                    if alias in requested and alias not in returned:
                        aliases.setdefault(alias, set()).add(event['event_id'])
            # A paid response is not a successfully admitted observation until
            # the source-revocable ingress transaction succeeds. Stage schedule
            # changes so a failed admission cannot postpone retry or discard an
            # older event/alias from the in-memory schedule.
            next_events = dict(self.events)
            for event in page.events:
                if event['league'] not in aggregate_scope(self.service.config):
                    raise ValueError('provider returned outside configured scope')
                if event['status'].get('ended') or event['status'].get('completed') or event['status'].get('cancelled'):
                    next_events.pop(event['event_id'], None)
                else:
                    next_events[event['event_id']] = event
            # SGO can return a replacement event for a requested old ID. Its
            # explicit alias updates scheduling only; it is not cross-provider
            # identity or authority to withdraw the old source observation.
            for alias, replacements in aliases.items():
                if len(replacements) == 1:
                    next_events.pop(alias, None)
            if len(next_events) > self.max_events:
                raise ValueError('event scheduling capacity exceeded')
            # An empty or partial ID response is not evidence of closure.
            # Remember the local attempt solely to avoid repeatedly spending on
            # an omitted ID; never change its provider or receipt clocks.
            if 'eventIDs' in params:
                seen = {event['event_id'] for event in page.events}
                resolved_aliases = {alias for alias, replacements in aliases.items() if len(replacements) == 1}
                for event_id in requested - seen - resolved_aliases:
                    if event_id in next_events:
                        next_events[event_id] = dict(next_events[event_id], last_polled_at=self.now().isoformat())
            from psycopg import OperationalError
            from psycopg.errors import QueryCanceled
            try:
                await self._publish(page)
            except (ValueError, OperationalError, QueryCanceled) as exc:
                from app.diagnostics import failure
                failure(__name__, 'sgo_page_admission_interrupted', exc)
                raise RuntimeError('provider page admission interrupted') from exc
            if alternate is not None:
                admitted = [quote for quote in page.quotes if quote.get('alternate')]
                alternate['admitted_alternate_rows'] += len(admitted)
                alternate['admitted_available_alternate_rows'] += sum(quote.get('available') is True for quote in admitted)
            self.events = next_events
            if page.events:
                await self.state('available', 'sgo_page_received',
                                 'SportsGameOdds page received; individual source clocks and availability apply.')
            return page
        finally:
            self._account_status()

    def params(self, *, league=None, event_ids=None, cursor=None, include_alternates=False):
        result = {'oddID': ','.join(sorted(ODD_IDS)), 'limit': self.page_limit,
                  'includeOpposingOdds': True}
        if league is not None:
            result['leagueID'] = league
        else:
            result['eventIDs'] = ','.join(event_ids)
            result['limit'] = len(event_ids)
        if include_alternates:
            if league is not None or cursor is not None or len(event_ids) != 1:
                raise ValueError('alternate refresh requires one explicit event')
            result.update(includeAltLines=True, bookmakerID=','.join(ALTERNATE_REFRESH_BOOKS))
        if cursor is not None:
            result['cursor'] = cursor
        return result

    def checkpoint_discovery(self, league, traversal):
        if self.ledger is None:
            return
        self.ledger.save_discovery_progress(league, {
            'params': dict(self.params(league=league), startsAfter=traversal.starts_after),
            'next_cursor': traversal.next_cursor,
            'pages': len(traversal.pages),
            'charged_objects': traversal.charged_objects,
            'seen_cursors': sorted(traversal._seen_cursors),
            'seen_events': sorted(traversal._seen_events),
        }, now=self.now())

    def restore_discovery(self):
        if self.ledger is None:
            return
        from .sportsgameodds_transport import validate_params
        for league, value in self.ledger.load_discovery_progress(now=self.now()).items():
            try:
                if league not in aggregate_scope(self.service.config) or not isinstance(value, dict):
                    continue
                params = value['params']
                expected = dict(self.params(league=league), startsAfter=params['startsAfter'])
                if params != expected:
                    continue
                if not isinstance(value['next_cursor'], str) or not value['next_cursor']:
                    continue
                validate_params(dict(params, cursor=value['next_cursor']))
                pages, cursors, events = value['pages'], value['seen_cursors'], value['seen_events']
                if (type(pages) is not int or not 1 <= pages < 1000
                        or not isinstance(cursors, list) or len(cursors) != pages - 1
                        or not isinstance(events, list) or len(events) > pages * self.page_limit
                        or any(not isinstance(x, str) or not x or len(x) > 2048 for x in cursors + events)
                        or len(set(cursors)) != len(cursors) or len(set(events)) != len(events)
                        or value['next_cursor'] in cursors):
                    continue
                objects = value.get('charged_objects', max(pages, len(events)))
                if type(objects) is not int or not max(pages, len(events)) <= objects <= pages * self.page_limit:
                    continue
                traversal = Traversal(max_pages=1000)
                traversal.charged_objects = objects
                traversal.starts_after = params['startsAfter']
                traversal.next_cursor = value['next_cursor']
                traversal.pages = [None] * pages
                traversal._seen_cursors = set(cursors)
                traversal._seen_events = set(events)
                self.discovery_progress[league] = traversal
            except (KeyError, TypeError, ValueError):
                continue
        self.metrics['discovery_restored'] = len(self.discovery_progress)

    def scheduled_events(self):
        return [EventDue(e['event_id'], datetime.fromisoformat(e['starts_at']),
                         datetime.fromisoformat(e.get('last_polled_at', e['received_at'])),
                         live=e['phase']=='live', started=e['phase']=='started') for e in self.events.values()]

    async def refresh(self, due, policy, *, between_discovery_pages=False):
        def needs_alternates(event, at):
            return event.active or event.starts_at - at <= ALTERNATE_REFRESH_WINDOW

        start = 0
        while start < len(due):
            attempted_at = self.now()
            include_alternates = needs_alternates(due[start], attempted_at)
            batch = [due[start]]
            if not include_alternates:
                for event in due[start+1:start+self.page_limit]:
                    if needs_alternates(event, attempted_at):
                        break
                    batch.append(event)
            slots = [poll_slot(event, attempted_at, policy) for event in batch]
            await self._fetch(self.params(event_ids=[event.event_id for event in batch],
                                          include_alternates=include_alternates))
            start += len(batch)
            metrics = self.metrics.setdefault('completed_refresh_polls', {})
            for rank, deadline in slots:
                tier = ('active', 'kickoff', 'started')[rank] if rank <= 2 else 'scheduled'
                tally = metrics.setdefault(tier, dict(events=0, between_discovery_pages=0,
                                                       max_schedule_delay_seconds=0))
                tally['events'] += 1
                tally['between_discovery_pages'] += int(between_discovery_pages)
                delay = round(max(0, (attempted_at-deadline).total_seconds()), 3)
                tally['max_schedule_delay_seconds'] = max(tally['max_schedule_delay_seconds'], delay)

    async def cycle(self):
        now = self.now()
        # Receipt time schedules polling and carries no source-price authority.
        candidates = self.scheduled_events()
        policy = SchedulePolicy()
        discovery_cadence = timedelta(hours=12)
        leagues = list(aggregate_scope(self.service.config))
        if self.ledger is not None and self.window_id is not None:
            # The worker serializes requests. A prior process's transport may
            # still finish before its timeout, so wait out that interval.
            if self.account_id is not None and self.ledger.recover_interrupted(
                self.account_id, now=now, minimum_age=getattr(self.transport, 'timeout_seconds', 30)
            ):
                self._account_status()
            account = self.ledger.status(self.window_id)
            rolling = self.ledger.rolling_objects(self.window_id, since=now-timedelta(days=1))
            allowance = daily_allowance(available=account['available'] + rolling, now=now, reset_at=account['reset_at'])
            by_league = Counter(event['league'] for event in self.events.values())
            prior_cost = self.ledger.discovery_cost(now=now)
            walk_objects = sum(max(1, by_league[league], prior_cost.get(league, 0)) for league in leagues)
            policy, projected = budgeted_policy(candidates, now, allowance, discovery_walk_objects=walk_objects,
                                                priority_pregame=True)
            self.schedule_policy = policy
            discovery_cadence = discovery_interval(retained_events=walk_objects, daily_budget=allowance,
                                                   projected_refresh_objects=projected)
            discovery_per_day = walk_objects * timedelta(days=1) / discovery_cadence
            combined = projected + discovery_per_day
            self.metrics['schedule_budget'] = dict(daily_allowance=allowance,
                projected_refresh_objects=projected, refresh_fraction=REFRESH_TARGET,
                discovery_hours=discovery_cadence.total_seconds()/3600,
                discovery_walk_objects=walk_objects, last_completed_walk_objects=prior_cost,
                projected_discovery_objects=discovery_per_day, projected_total_objects=combined,
                planned_fraction=PLANNED_FRACTION, projected_headroom_objects=round(allowance-combined, 3),
                live_minutes=policy.live.total_seconds()/60, approaching_minutes=policy.approaching.total_seconds()/60,
                approaching_hours=policy.approaching_window.total_seconds()/3600,
                imminent_minutes=policy.imminent.total_seconds()/60,
                near_minutes=policy.near.total_seconds()/60, distant_minutes=policy.distant.total_seconds()/60)
            self.metrics['resolved_objects_last_hour'] = self.ledger.charge_breakdown(self.window_id, since=now-timedelta(hours=1))
            self.metrics['resolved_objects_hour_ended_at'] = now.isoformat()
        def discovery_due(league):
            if league in self.discovery_progress or league not in self.discovery_at:
                return True
            interval = (timedelta(minutes=15) if league in self.metrics.get('discovery_unstable', {})
                        else discovery_cadence)
            return now - self.discovery_at[league] >= interval

        def due_now():
            at = self.now()
            due = due_events(self.scheduled_events(), at, policy=policy, **self.controls_to_schedule())
            urgent, scheduled = [], []
            for event in due:
                (urgent if event.active or event.starts_at <= at else scheduled).append(event)
            return urgent, scheduled

        def in_traversal():
            return any(walk.next_cursor is not None for walk in self.discovery_progress.values())

        urgent, scheduled = due_now()
        await self.refresh(urgent, policy, between_discovery_pages=in_traversal())
        walking = any(map(discovery_due, leagues))
        await self.refresh(scheduled[:self.page_limit] if walking else scheduled, policy)
        if self.discovery_next_league in leagues:
            offset = leagues.index(self.discovery_next_league)
            leagues = leagues[offset:] + leagues[:offset]
        for index, league in enumerate(leagues):
            if self.controls()['stopped'] or self.controls()['source_paused']:
                return
            if not discovery_due(league):
                continue
            # Advance before dispatch: a local rate or budget interruption must
            # not repeatedly favor the first leagues on the next cycle. Cursors
            # remain attached to their own league and retain their query filter.
            self.discovery_next_league = leagues[(index + 1) % len(leagues)]
            # The 2,000-event schedule bound permits up to 1,000 two-event
            # pages. A smaller traversal cap silently abandoned large slates.
            traversal = self.discovery_progress.setdefault(league, Traversal(max_pages=1000))
            # Keep the filter stable across cursor pages; include recently
            # started games so live events are not discarded by discovery.
            if not hasattr(traversal, 'starts_after'):
                traversal.starts_after = (now - timedelta(hours=12)).isoformat()
            for _ in range(self.max_pages):
                # A live update or kickoff can become due during a multi-page
                # walk. Give it the next guarded request before spending on
                # another discovery page, keeping the cursor and filter intact.
                urgent, _ = due_now()
                await self.refresh(urgent, policy, between_discovery_pages=in_traversal())
                if self.controls()['stopped'] or self.controls()['source_paused']:
                    return
                cursor = traversal.next_cursor
                params = self.params(league=league, cursor=cursor)
                params['startsAfter'] = traversal.starts_after
                try:
                    page = await self._fetch(params)
                except RejectedCursor:
                    # Abandon only this incomplete walk. Keep its reserved cost.
                    self.discovery_progress.pop(league, None)
                    if self.ledger is not None:
                        self.ledger.clear_discovery_progress(league)
                    self.discovery_at.pop(league, None)
                    self.metrics.setdefault('discovery_complete', {})[league] = False
                    self.metrics.setdefault('discovery_unstable', {})[league] = self.now().isoformat()
                    raise
                try:
                    traversal.add(cursor, page)
                except ValueError:
                    # Moving pages cannot prove absence. Keep observations
                    # already admitted and retry discovery on its normal cadence.
                    self.discovery_progress.pop(league, None)
                    if self.ledger is not None:
                        self.ledger.clear_discovery_progress(league)
                    self.discovery_at[league] = now
                    self.metrics.setdefault('discovery_complete', {})[league] = False
                    self.metrics.setdefault('discovery_unstable', {})[league] = self.now().isoformat()
                    break
                # Keep bounded cursor and event identities, not entire payloads.
                traversal.charged_objects += response_object_charge(len(page.events))
                traversal.pages[-1] = None
                if traversal.complete:
                    self.discovery_progress.pop(league, None)
                    completed_at = self.now()
                    self.discovery_at[league] = completed_at
                    if self.ledger is not None:
                        self.ledger.record_discovery(league, completed_at=completed_at, objects=traversal.charged_objects)
                    self.metrics.get('discovery_unstable', {}).pop(league, None)
                    break
                if len(traversal.pages) >= traversal.max_pages:
                    self.discovery_progress.pop(league, None)
                    if self.ledger is not None:
                        self.ledger.clear_discovery_progress(league)
                    self.discovery_at[league] = now
                    self.metrics.setdefault('discovery_unstable', {})[league] = self.now().isoformat()
                    break
                self.checkpoint_discovery(league, traversal)
                # Give overdue pregame work a bounded share of the turn.
                # A large refresh backlog cannot take every discovery slot.
                urgent, scheduled = due_now()
                await self.refresh(urgent, policy, between_discovery_pages=True)
                await self.refresh(scheduled[:self.page_limit], policy)
            self.metrics.setdefault('discovery_complete', {})[league] = traversal.complete
        self.phase = 'waiting_for_cycle'
        self.metrics['next_refresh_at'] = (self.now()+timedelta(seconds=self.next_cycle_delay())).isoformat()

    def next_cycle_delay(self):
        # Continue a bounded traversal promptly, while respecting the same
        # per-page usage reconciliation, local rate guard and daily budget.
        if self.discovery_progress:
            return 60
        policy = self.schedule_policy
        if policy is None:
            return 15 * 60
        now = self.now()
        delay = 15 * 60
        for event in self.scheduled_events():
            _, due = poll_slot(event, now, policy)
            delay = min(delay, max(0, (due - now).total_seconds()))
            if not event.active:
                for window in (policy.approaching_window, policy.imminent_window, policy.near_window):
                    boundary = (event.starts_at - window - now).total_seconds()
                    if boundary > 0:
                        delay = min(delay, boundary)
        # Avoid a busy loop for due requests interrupted by controls or rate.
        return max(60, int(delay))

    def controls_to_schedule(self):
        c = self.controls()
        return dict(stopped=c['stopped'], paused=c['source_paused'])

    @operation
    def provider_status(self, state, code, reason):
        yield (dict(type='sgo_status', source='sportsgameodds', state=state, reason_code=code, reason=reason), deepcopy(self.service.states))

    async def state(self, state, code, reason):
        self.metrics.update(state=state, reason_code=code)
        if self.service.database_mode:
            await call(self.service, self.provider_status, state, code, reason)
        await call(self.service, self.service.source_state, 'novig', state, reason)
        await call(self.service, self.service.source_state, 'prophetx', state, reason)

    async def run(self):
        if not self.service.database_mode:
            await self.state('unavailable', 'sgo_database_required', 'SportsGameOdds requires current-row storage.')
            return
        try:
            await self.state('connecting', 'sgo_connecting', 'Connecting to SportsGameOdds account usage.')
            while not self.controls()['stopped'] and not self.controls()['source_paused']:
                try:
                    await self.initialize()
                    retained, truncated = await asyncio.to_thread(
                        retained_schedule, aggregate_scope(self.service.config), self.now(), self.max_events)
                    self.events.update(retained)
                    self.metrics.update(retained_schedule_events=len(retained), retained_schedule_truncated=truncated)
                    if self.ledger is not None:
                        self.discovery_at.update(self.ledger.discovery_schedule(now=self.now()))
                        self.restore_discovery()
                    break
                except RuntimeError as exc:
                    if not await self.wait_for_dispatch(exc):
                        raise
                    await asyncio.sleep(60)
            while not self.controls()['stopped'] and not self.controls()['source_paused']:
                try:
                    if self.ledger is not None and self.now() >= self.ledger.status(self.window_id)['reset_at']:
                        # Start each pacing window from fresh provider usage.
                        await self.initialize()
                    await self.cycle()
                except RuntimeError as exc:
                    if str(exc) == 'daily object pacing limit':
                        self.phase = 'waiting_for_budget'
                        delay, code = 60*60, 'sgo_daily_pacing'
                        if isinstance(exc, DailyObjectPacing):
                            delay = min(delay, max(1, (exc.retry_at-self.now()).total_seconds()))
                            self.metrics['daily_pacing'] = dict(eligible_retry_at=exc.retry_at.isoformat(),
                                requested=exc.requested, rolling=exc.rolling, allowance=exc.allowance)
                        reason = 'SportsGameOdds is waiting for its daily object budget; prices retain their original source times.'
                    else:
                        if not await self.wait_for_dispatch(exc):
                            raise
                        await asyncio.sleep(60)
                        continue
                    self.metrics['next_refresh_at'] = (self.now()+timedelta(seconds=delay)).isoformat()
                    await self.state('budget_delayed', code, reason)
                    await asyncio.sleep(delay)
                    continue
                self.metrics.pop('daily_pacing', None)
                if self.metrics['state'] != 'available':
                    await self.state('available', 'sgo_cycle_complete',
                                     'SportsGameOdds scans are scheduled. Individual source clocks and availability apply.')
                await asyncio.sleep(self.next_cycle_delay())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reasons = {'account reset evidence unavailable':'The provider did not report an account reset time.',
                       'account reset evidence expired':'The account reset evidence has expired.',
                       'current account usage evidence unavailable or changed':'Current account usage could not be safely reconciled.',
                       'unresolved provider object reservation':'An earlier provider request has an unresolved object charge.',
                       'provider rate limited':'The provider rate limit was reached.',
                       'provider rejected cursor':'The provider rejected a discovery cursor and the incomplete walk was discarded.',
                       'daily object pacing limit':'The daily object pacing limit has been reached.'}
            reason = reasons.get(str(exc), 'SportsGameOdds collection is unavailable; check account and source status.')
            self.metrics['state']='unavailable'
            self.metrics['reason_code']='sgo_account_or_collection_unavailable'
            self.metrics['limitation']=reason
            if not self.closed and self.service.dispatch:
                await self.state('unavailable', 'sgo_account_or_collection_unavailable',
                    reason)
        finally:
            await self.close()

    async def wait_for_dispatch(self, exc):
        # Retry read-only balance checks. Paid dispatch still requires a fresh
        # agreeing balance, with every unresolved reservation left in place.
        if str(exc) == 'request rate limit':
            self.phase, code = 'waiting_for_rate', 'sgo_request_rate'
            reason = 'SportsGameOdds is waiting for its request limit to reset.'
        elif isinstance(exc, (TransportFailure, RejectedCursor)) or str(exc) in (
                'provider rate limited', 'provider response unsuccessful', 'provider page admission interrupted'):
            self.phase, code = 'waiting_for_retry', 'sgo_scan_interrupted'
            reason = 'SportsGameOdds will retry on the next scan. Any uncertain cost remains reserved.'
        elif str(exc) in ('unresolved provider object reservation',
                'unresolved object reservation', 'collection paused or rate limited'):
            self.phase, code = 'waiting_for_reconciliation', 'sgo_charge_unresolved'
            reason = 'SportsGameOdds is waiting for accounting or provider controls to allow dispatch.'
        elif str(exc) in ('account usage unavailable', 'account usage request failed',
                          'current account usage evidence unavailable or changed'):
            self.phase, code = 'waiting_for_usage', 'sgo_usage_unreconciled'
            reason = 'SportsGameOdds is waiting for a fresh provider balance that agrees with the ledger.'
        else:
            return False
        self.metrics['next_refresh_at'] = (self.now()+timedelta(seconds=60)).isoformat()
        await self.state('budget_delayed', code, reason)
        return True

    async def close(self):
        self.closed = True
        try:
            await self.transport.close()
        finally:
            self.key = None
