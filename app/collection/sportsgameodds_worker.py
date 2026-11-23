"""Runtime owner for bounded SGO discovery and current-row ingestion.

Paid dispatch requires explicit fresh provider account limits and reset. This
worker does not infer absent events from pagination and never withdraws rows
from an incomplete, moving, or successful-but-not-snapshot traversal.
"""
import asyncio
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re

from .current_ingress import call, operation
from .current_policy import ROOT, PregameWindowClosed, aggregate_scope, live_enabled
from .sportsgameodds_adapter import PROPHETX_BOOKMAKER_ID, Traversal, clock_sample
from .sportsgameodds_collector import (
    DailyObjectPacing, DiscoveryScopeMismatch, GuardedPageCollector, InvalidProviderPage, RejectedCursor,
)
from .sportsgameodds_current_rows import current_rows
from .sportsgameodds_ledger import ObjectLedger
from . import sportsgameodds_schedule as scheduling
from .sportsgameodds_schedule import (
    PLANNED_FRACTION, REFRESH_TARGET, EventDue, budgeted_policy, daily_allowance,
    discovery_interval, due_events, poll_slot, response_object_charge,
)
from .sportsgameodds_transport import ODD_IDS, SportsgameoddsTransport
from .sportsgameodds_transport import TransportFailure
from .sportsgameodds_usage import read_usage
from app.comparison.reference_scope import REQUEST_BOOKS
from app.diagnostics import failure

ALTERNATE_REFRESH_BOOKS = REQUEST_BOOKS
ALTERNATE_REFRESH_WINDOW = timedelta(hours=2)
SCAN_INTERVAL = timedelta(minutes=1)


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


def retained_schedule(scope, now, limit, *, include_live=False):
    """Seed polling from retained receipts; never restore quote authority.

    The event frame's receipt is used only to order future polling. No
    missing event is treated as absent.
    """
    from app.storage.store import connect
    with connect() as db:
        rows = db.execute('''WITH schedule AS (
                SELECT f.event_id,
                    COALESCE(f.facts#>>'{event_context,league}',e.competition) AS league,
                    COALESCE(f.facts->>'starts_at',e.scheduled_start) AS starts_at,
                    f.facts->>'received_at' AS received_at,
                    f.facts#>>'{event_context,phase}' AS phase,
                    f.facts#>'{event_context,status}' AS status
                FROM current_sgo_event_frame f
                LEFT JOIN current_event e ON e.native_event_id=f.event_id AND e.provider='sportsgameodds'
            )
            SELECT * FROM schedule WHERE league=ANY(%s)
              AND starts_at::timestamptz >= %s
              AND (%s OR (phase='pregame' AND starts_at::timestamptz > %s))
              AND status->'ended' IS DISTINCT FROM 'true'::jsonb
              AND status->'completed' IS DISTINCT FROM 'true'::jsonb
              AND status->'cancelled' IS DISTINCT FROM 'true'::jsonb
            ORDER BY starts_at::timestamptz,event_id LIMIT %s''',
            (list(scope), now-timedelta(hours=12) if include_live else now, include_live, now, limit+1)).fetchall()
    result = {row['event_id']: dict(row, phase=row['phase'] or 'unknown', status=row['status'] or {})
              for row in rows[:limit]}
    return result, len(rows) > limit


class SportsGameOddsWorker:
    ingress_source = 'sportsgameodds'
    # Free capture was >10 MB for five events; paid breadth is unmeasured.
    page_limit = 2
    max_pages = 10
    max_events = 2000
    # One discovery walk can cover the 2,000-event schedule in two-event pages.
    max_discovery_pages = 1000

    def __init__(self, service, *, key_loader=credential, usage_reader=read_usage,
                 transport=None, ledger_path=None, study_path=None, now=clock, activity_reader=None):
        self.service = service
        self.key_loader = key_loader
        self.usage_reader = usage_reader
        self.transport = transport or SportsgameoddsTransport()
        self.ledger_path = Path(ledger_path or ROOT / '.local/predict-odds/sportsgameodds-ledger.sqlite3')
        # Evidence follows the injected ledger namespace. Disposable workers
        # cannot accidentally retain synthetic responses in the owner's store.
        self.original_response_root = self.ledger_path.parent / 'original-responses'
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
        self.page_in_progress = False
        self.storage_interval_requested = False
        self.ledger = None
        self.window_id = None
        self.study_path = Path(study_path or ROOT / '.local/predict-odds/diagnostics/sgo-refresh-study.sqlite3')
        self.collector = None
        self.events = {}
        self.discovery_at = {}
        self.discovery_progress = {}
        self.discovery_next_league = None
        self.key = None
        self.account_id = None
        self.request_limit = 1
        self.collection_run = None
        self.activity_status = None
        self.activity_reader = activity_reader
        # Ordinary collection and the scheduled experiment share one paid
        # request slot. Upcoming checkpoint credit reservations are admission
        # headroom only; financial ledger exposure remains the actual request.
        self.request_lock = asyncio.Lock()
        self.experiment_late_waiting = False
        self.experiment_reserved_objects = 0
        self.experiment_reserved_requests = 0

    def controls(self):
        return {'stopped': self.closed or not self.service.dispatch or self.service.globally_stopped
                or (self.storage_interval_requested and not self.page_in_progress),
                'source_paused': 'sportsgameodds' in self.service.paused_sources}

    def event_in_scope(self, event, at):
        if getattr(self.service, 'activity_mode_enabled', False):
            return event['phase'] == 'pregame' and at < datetime.fromisoformat(event['starts_at'])
        return live_enabled(self.service.config) or (
            event['phase'] == 'pregame' and at < datetime.fromisoformat(event['starts_at']))

    def request_in_scope(self, params):
        if getattr(self.service, 'activity_mode_enabled', False):
            from .activity_mode import eligible, read_control
            try:
                status = (self.activity_reader or read_control)(at=self.now())
            except Exception:
                raise RuntimeError('activity control unavailable') from None
            if status.get('staged_bytes',0) >= 32*1024*1024:
                from .activity_collector import ActivityBudgetDelayed
                raise ActivityBudgetDelayed('archive_backlog', self.now()+timedelta(seconds=30))
            if 'leagueID' in params:
                return params.get('started') is False and params.get('live') is False and 'startsAfter' in params
            if self.collection_run and self.collection_run['kind'] == 'live':
                events = [self.events[eid] for eid in params['eventIDs'].split(',') if eid in self.events]
                return len(events) == len(params['eventIDs'].split(',')) and len(eligible(events,status,at=self.now())) == len(events)
            return all(eid in self.events and self.event_in_scope(self.events[eid], self.now()) for eid in params['eventIDs'].split(','))
        if live_enabled(self.service.config):
            return True
        if 'leagueID' in params:
            return params.get('started') is False and params.get('live') is False and 'startsAfter' in params
        # The provider ignores phase and start filters on exact event-ID requests.
        at = self.now()
        return all(event_id in self.events and self.event_in_scope(self.events[event_id], at)
                   for event_id in params['eventIDs'].split(','))

    async def request_in_scope_async(self, params):
        if getattr(self.service, 'activity_mode_enabled', False):
            from .bulk_checkpoint import owned_thread
            return await owned_thread(self.request_in_scope, params)
        return self.request_in_scope(params)

    def request_storage_interval(self):
        """Let the owned page settle and publish, then prevent another dispatch."""
        self.storage_interval_requested = True
        return not self.page_in_progress

    async def usage(self):
        if self.controls()['stopped'] or self.controls()['source_paused']:
            raise RuntimeError('collection stopped or source paused')
        # /account/usage is exempt from provider rate limits. Paid event
        # requests still reserve their own durable rate slot in the ledger.
        return await self.usage_reader(self.key)

    async def retain_original(self, params, response):
        from .bulk_checkpoint import owned_thread
        from .original_receipts import capture
        self.metrics['original_receipt'] = await owned_thread(
            capture, params, response, root=self.original_response_root)

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
                                              controls=self.controls, account_usage=pacing_usage,
                                              eligible=self.request_in_scope_async,
                                              receipt_retainer=self.retain_original)
        self.metrics.update(state='waiting', account_tier=observed.get('tier'), reset_basis=reset_basis)
        self._account_status()
        await self.update_study()

    async def update_study(self, page=None, admitted_at=None):
        from .bulk_checkpoint import owned_thread
        from .sportsgameodds_study import observe, report

        try:
            self.metrics['late_pregame_study'] = (
                await owned_thread(observe,self.study_path,page,admitted_at) if page is not None
                else await owned_thread(report,self.study_path))
        except Exception as exc:
            failure(__name__, 'sgo_refresh_study', exc)
            self.metrics['late_pregame_study'] = dict(state='measurement_unavailable')

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
    def admit(self, sport, records, reference_rows, event_frames, received_at, receipt_sha256, event_scopes, include_alternates=False, collection_run=None):
        if self.controls()['stopped'] or self.controls()['source_paused']:
            raise asyncio.CancelledError()
        states = deepcopy(self.service.states)
        yield (dict(type='current_aggregate_records', source='sportsgameodds', sport=sport,
                    records=records, sgo_reference_rows=reference_rows, sgo_event_frames=event_frames,
                    receipt_sha256=receipt_sha256, event_scopes=event_scopes, sgo_include_alt_lines=include_alternates,
                    collection_mode=(collection_run or {}).get('kind','monitor'), collection_run=collection_run,
                    complete_venues=[], received_at=received_at), states)

    @staticmethod
    def _prepare_page(page, ingress_bytes, collection_run=None):
        from app.dashboard.current_contract import packed
        from app.storage.sportsgameodds_reference import prepare_page, prepare_frames
        records, exclusions = current_rows(page, page.receipt_sha256)
        reference_rows = prepare_page(page)
        event_frames = prepare_frames(page, reference_rows)
        event_scopes = {event['event_id']: event['league'] for event in page.events}
        if not event_scopes:
            return None, len(exclusions)
        sport = page.events[0]['league']
        received_at = page.events[0]['received_at']
        envelope = dict(type='current_aggregate_records',source='sportsgameodds',sport=sport,
                        records=records,sgo_reference_rows=reference_rows,sgo_event_frames=event_frames,
                        receipt_sha256=page.receipt_sha256,event_scopes=event_scopes,complete_venues=[],received_at=received_at,
                        collection_mode=(collection_run or {}).get('kind','monitor'), collection_run=collection_run)
        if len(packed(envelope)) > ingress_bytes:
            raise ValueError('SGO current page exceeds ingress bound')
        prepared = dict(sport=sport, records=records, reference_rows=reference_rows, event_frames=event_frames,
                        received_at=received_at, receipt_sha256=page.receipt_sha256, event_scopes=event_scopes, collection_run=collection_run)
        return prepared, len(exclusions)

    async def _publish(self, page, *, include_alternates=False):
        from .bulk_checkpoint import owned_thread

        # Large alternate pages used to prepare and serialize on the same
        # event loop that receives both dedicated book streams.
        prepared, excluded = await owned_thread(self._prepare_page, page, self.service.config['ingress_bytes'], *([self.collection_run] if self.collection_run is not None else []))
        self.metrics['excluded'] += excluded
        if prepared is None:
            return
        # The entire page is one source-revocable transaction: prices and
        # reference evidence cannot become visible at different revisions.
        await call(self.service, self.admit, **prepared, include_alternates=include_alternates)
        admitted_at = self.now()
        self.metrics['records'] += len(prepared['records'])
        self.metrics['reference_rows'] = self.metrics.get('reference_rows', 0) + len(prepared['reference_rows'])
        cohorts = self.metrics.setdefault('admitted_quote_clock_samples', {})
        self.metrics['last_clock_sample_admitted_at'] = admitted_at.isoformat()
        clock_tallies = await owned_thread(clock_sample, page, admitted_at=admitted_at)
        for (league, phase, family, venue), tally in clock_tallies.items():
            key = ':'.join((league, phase, family, venue))
            totals = cohorts.setdefault(key, dict.fromkeys(tally, 0))
            for field, count in tally.items():
                totals[field] += count

        # A study failure cannot revoke prices already committed above.
        if include_alternates and any(timedelta(0) < datetime.fromisoformat(e['starts_at'])-admitted_at <= timedelta(minutes=30)
               for e in page.events):
            await self.update_study(page,admitted_at)

    async def _fetch(self, params):
        while True:
            while self.experiment_late_waiting:
                await asyncio.sleep(0.01)
            async with self.request_lock:
                if self.experiment_late_waiting:
                    continue
                return await self._fetch_owned(params)

    async def _fetch_owned(self, params):
        if not await self.request_in_scope_async(params):
            raise PregameWindowClosed()
        self.page_in_progress = True
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
            observed_at = self.now()
            next_events = {event_id: event for event_id, event in self.events.items()
                           if self.event_in_scope(event, observed_at)}
            for event in page.events:
                if event['league'] not in aggregate_scope(self.service.config):
                    raise ValueError('provider returned outside configured scope')
                if (not self.event_in_scope(event, observed_at) or event['status'].get('ended')
                        or event['status'].get('completed') or event['status'].get('cancelled')):
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
            admitted_page = page
            if getattr(self.service, 'activity_mode_enabled', False) or not live_enabled(self.service.config):
                pregame = {event['event_id'] for event in page.events
                           if self.event_in_scope(event, datetime.fromisoformat(event['received_at']))}
                # A provider may report an explicit closure with started=true.
                # Admit its lifecycle evidence without admitting post-start odds.
                events = tuple(event for event in page.events if event['event_id'] in pregame or
                               any(event['status'].get(key) is True for key in
                                   ('started', 'live', 'cancelled', 'completed', 'ended', 'delayed', 'suspended')))
                if len(pregame) != len(page.events):
                    admitted_page = replace(page, events=events,
                                            quotes=tuple(quote for quote in page.quotes
                                                         if quote['event_id'] in pregame))
            try:
                if params.get('includeAltLines') is True:
                    await self._publish(admitted_page, include_alternates=True)
                else:
                    await self._publish(admitted_page)
            except (ValueError, OperationalError, QueryCanceled) as exc:
                failure(__name__, 'sgo_page_admission_interrupted', exc)
                raise RuntimeError('provider page admission interrupted') from exc
            # A final sporting score is a separate research observation. It
            # cannot grant authority to post-start odds or venue settlement.
            if any(event.get('game_results') or event.get('scores') or
                   event['status'].get('completed') is True or event['status'].get('finalized') is True
                   for event in page.events):
                from .bulk_checkpoint import owned_thread
                from .sgo_game_results import ingest
                try:
                    self.metrics['sporting_results'] = await owned_thread(
                        ingest, page, known_at=self.now().isoformat())
                except Exception as exc:
                    failure(__name__, 'sgo_sporting_result_ingestion', exc)
                    self.metrics['sporting_results'] = dict(state='unavailable', reason='sporting_result_ingestion_failed')
            if alternate is not None:
                admitted = [quote for quote in admitted_page.quotes if quote.get('alternate')]
                alternate['admitted_alternate_rows'] += len(admitted)
                alternate['admitted_available_alternate_rows'] += sum(quote.get('available') is True for quote in admitted)
            self.events = next_events
            if page.events:
                await self.state('available', 'sgo_page_received',
                                 'SportsGameOdds page received; individual source clocks and availability apply.')
            return page
        finally:
            self.page_in_progress = False
            self._account_status()

    def params(self, *, league=None, event_ids=None, starts_after=None, cursor=None, include_alternates=False):
        result = {'oddID': ','.join(sorted(ODD_IDS)), 'limit': self.page_limit,
                  'includeOpposingOdds': True, 'bookmakerID': ','.join(REQUEST_BOOKS)}
        if league is not None:
            if starts_after is None:
                raise ValueError('league discovery requires a fixed start cutoff')
            result.update(leagueID=league, startsAfter=starts_after)
            if not live_enabled(self.service.config):
                result.update(started=False, live=False)
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
            'params': self.params(league=league, starts_after=traversal.starts_after),
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
                expected = self.params(league=league, starts_after=params['startsAfter'])
                if params != expected:
                    continue
                if not isinstance(value['next_cursor'], str) or not value['next_cursor']:
                    continue
                validate_params(dict(params, cursor=value['next_cursor']))
                pages, cursors, events = value['pages'], value['seen_cursors'], value['seen_events']
                if (type(pages) is not int or not 1 <= pages < self.max_discovery_pages
                        or not isinstance(cursors, list) or len(cursors) != pages - 1
                        or not isinstance(events, list) or len(events) > pages * self.page_limit
                        or any(not isinstance(x, str) or not x or len(x) > 2048 for x in cursors + events)
                        or len(set(cursors)) != len(cursors) or len(set(events)) != len(events)
                        or value['next_cursor'] in cursors):
                    continue
                objects = value.get('charged_objects', max(pages, len(events)))
                if type(objects) is not int or not max(pages, len(events)) <= objects <= pages * self.page_limit:
                    continue
                traversal = Traversal(max_pages=self.max_discovery_pages)
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

    def scheduled_events(self, *, at):
        return [EventDue(e['event_id'], datetime.fromisoformat(e['starts_at']),
                         datetime.fromisoformat(e.get('last_polled_at', e['received_at'])),
                         live=e['phase']=='live', started=e['phase']=='started') for e in self.events.values()
                if self.event_in_scope(e, at)]

    async def refresh(self, due, policy, *, between_discovery_pages=False):
        def needs_alternates(event, at):
            return event.active or event.starts_at - at <= ALTERNATE_REFRESH_WINDOW

        start = 0
        while start < len(due) and not self.storage_interval_requested:
            attempted_at = self.now()
            include_alternates = needs_alternates(due[start], attempted_at)
            batch = [due[start]]
            if not include_alternates:
                for event in due[start+1:start+self.page_limit]:
                    if needs_alternates(event, attempted_at):
                        break
                    batch.append(event)
            slots = [poll_slot(event, attempted_at, policy) for event in batch]
            event_ids = [event.event_id for event in batch]
            start += len(batch)
            try:
                try:
                    await self._fetch(self.params(event_ids=event_ids, include_alternates=include_alternates))
                except InvalidProviderPage as exc:
                    if not include_alternates:
                        raise
                    failure(__name__, 'sgo_alternate_refresh_parse', exc.__cause__ or exc)
                    self.metrics['alternate_parse_fallbacks'] = self.metrics.get('alternate_parse_fallbacks', 0) + 1
                    await self._fetch(self.params(event_ids=event_ids))
            except PregameWindowClosed:
                continue
            except InvalidProviderPage as exc:
                failure(__name__, 'sgo_refresh_parse', exc.__cause__ or exc)
                # Leave the previous prices and source clocks as recorded. Only
                # defer the next attempt so this event cannot starve the slate.
                attempted_at = self.now().isoformat()
                for event_id in event_ids:
                    if event_id in self.events:
                        self.events[event_id]['last_polled_at'] = attempted_at
                self.metrics['unreadable_refresh_events'] = self.metrics.get('unreadable_refresh_events', 0) + len(event_ids)
                continue
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
        candidates = self.scheduled_events(at=now)
        policy = scheduling.PREGAME_TARGET
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
                                                include_kickoff=live_enabled(self.service.config))
            discovery_cadence = discovery_interval(retained_events=walk_objects, daily_budget=allowance,
                                                   projected_refresh_objects=projected)
            discovery_per_day = walk_objects * timedelta(days=1) / discovery_cadence
            combined = projected + discovery_per_day
            target = scheduling.PREGAME_TARGET
            self.metrics['schedule_budget'] = dict(daily_allowance=allowance,
                projected_refresh_objects=projected, refresh_fraction=REFRESH_TARGET,
                discovery_hours=discovery_cadence.total_seconds()/3600,
                discovery_walk_objects=walk_objects, last_completed_walk_objects=prior_cost,
                projected_discovery_objects=discovery_per_day, projected_total_objects=combined,
                planned_fraction=PLANNED_FRACTION, projected_headroom_objects=round(allowance-combined, 3),
                projection='next_24_hours_through_kickoff', replan_seconds=SCAN_INTERVAL.total_seconds(),
                advertised_feed_seconds=600 if self.metrics.get('account_tier') == 'amateur' else 180,
                requested_late_refresh_seconds=int(target.approaching.total_seconds()),
                requested_early_refresh_seconds=int(target.imminent.total_seconds()),
                trial='one_minute_final_30_minutes',
                budget_stretched=policy.approaching!=target.approaching or policy.imminent!=target.imminent,
                live_minutes=policy.live.total_seconds()/60, approaching_minutes=policy.approaching.total_seconds()/60,
                approaching_hours=policy.approaching_window.total_seconds()/3600,
                hourly_window_hours=policy.imminent_window.total_seconds()/3600,
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
            due = due_events(self.scheduled_events(at=at), at, policy=policy, **self.controls_to_schedule())
            urgent, scheduled = [], []
            for event in due:
                (urgent if event.active or event.starts_at-at <= policy.imminent_window else scheduled).append(event)
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
            traversal = self.discovery_progress.setdefault(league, Traversal(max_pages=self.max_discovery_pages))
            # Keep the filter stable across cursor pages.
            if not hasattr(traversal, 'starts_after'):
                traversal.starts_after = (now-timedelta(hours=12) if live_enabled(self.service.config) else now).isoformat()
            for _ in range(self.max_pages):
                # A live update or kickoff can become due during a multi-page
                # walk. Give it the next guarded request before spending on
                # another discovery page, keeping the cursor and filter intact.
                urgent, _ = due_now()
                await self.refresh(urgent, policy, between_discovery_pages=in_traversal())
                if self.controls()['stopped'] or self.controls()['source_paused']:
                    return
                cursor = traversal.next_cursor
                params = self.params(league=league, starts_after=traversal.starts_after, cursor=cursor)
                try:
                    page = await self._fetch(params)
                except DiscoveryScopeMismatch:
                    self.metrics.setdefault('discovery_complete', {})[league] = False
                    raise
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
        return policy

    def approaching_events(self, at, policy):
        return [event for event in self.scheduled_events(at=at)
                if not event.active and at < event.starts_at <= at + policy.approaching_window]

    def next_pregame_refresh(self, at, policy, next_scan):
        # Wake at every selected event deadline or a faster-band boundary. This
        # also covers games outside the final two hours without new discovery.
        if policy is None:
            return next_scan
        deadlines = [next_scan]
        for event in self.scheduled_events(at=at):
            deadlines.append(max(at, poll_slot(event, at, policy)[1]))
            for window in (policy.approaching_window, policy.imminent_window, policy.near_window):
                boundary = event.starts_at-window
                if at < boundary:
                    deadlines.append(boundary)
        return min(deadlines)

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
                        retained_schedule, aggregate_scope(self.service.config), self.now(), self.max_events,
                        include_live=live_enabled(self.service.config))
                    self.events.update(retained)
                    self.metrics.update(retained_schedule_events=len(retained), retained_schedule_truncated=truncated)
                    if self.ledger is not None:
                        self.discovery_at.update(self.ledger.discovery_schedule(now=self.now()))
                        self.restore_discovery()
                    break
                except RuntimeError as exc:
                    if not await self.wait_for_dispatch(exc, retry_at=self.now()+timedelta(minutes=1)):
                        raise
                    await asyncio.sleep(60)
            if getattr(self.service, 'activity_mode_enabled', False):
                from .activity_collector import ActivityCollector
                await ActivityCollector(self).run()
                return
            next_scan = self.now()
            policy = None
            while not self.controls()['stopped'] and not self.controls()['source_paused']:
                now = self.now()
                scanning = policy is None or now >= next_scan
                if scanning:
                    next_scan = now + SCAN_INTERVAL
                try:
                    if self.ledger is not None and self.now() >= self.ledger.status(self.window_id)['reset_at']:
                        # Start each pacing window from fresh provider usage.
                        await self.initialize()
                    if scanning:
                        policy = await self.cycle()
                    else:
                        due = due_events(self.scheduled_events(at=now), now, policy=policy,
                                         **self.controls_to_schedule())
                        await self.refresh(due, policy)
                except RuntimeError as exc:
                    policy = None
                    if str(exc) == 'daily object pacing limit':
                        self.phase = 'waiting_for_budget'
                        delay, code = 60*60, 'sgo_daily_pacing'
                        if isinstance(exc, DailyObjectPacing):
                            delay = min(delay, max(1, (exc.retry_at-self.now()).total_seconds()))
                            self.metrics['daily_pacing'] = dict(eligible_retry_at=exc.retry_at.isoformat(),
                                requested=exc.requested, rolling=exc.rolling, allowance=exc.allowance)
                        reason = 'SportsGameOdds is waiting for its daily object budget; prices retain their original source times.'
                        next_scan = max(next_scan, self.now()+timedelta(seconds=delay))
                        await self.state('budget_delayed', code, reason)
                    elif not await self.wait_for_dispatch(exc, retry_at=next_scan):
                        raise
                else:
                    self.metrics.pop('daily_pacing', None)
                    if self.metrics['state'] != 'available':
                        await self.state('available', 'sgo_cycle_complete',
                                         'SportsGameOdds scans are scheduled. Individual source clocks and availability apply.')
                at = self.now()
                wake_at = min(next_scan, self.next_pregame_refresh(at, policy, next_scan))
                self.metrics['next_refresh_at'] = wake_at.isoformat()
                await asyncio.sleep(max(0, (wake_at-at).total_seconds()))
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

    async def wait_for_dispatch(self, exc, *, retry_at):
        # Retry read-only balance checks. Paid dispatch still requires a fresh
        # agreeing balance, with every unresolved reservation left in place.
        if str(exc) == 'request rate limit':
            self.phase, code = 'waiting_for_rate', 'sgo_request_rate'
            reason = 'SportsGameOdds is waiting for its request limit to reset.'
        elif isinstance(exc, DiscoveryScopeMismatch):
            self.phase, code = 'waiting_for_retry', 'sgo_discovery_league_mismatch'
            reason = 'SportsGameOdds returned events outside the requested league. Discovery did not advance.'
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
        self.metrics['next_refresh_at'] = retry_at.isoformat()
        await self.state('budget_delayed', code, reason)
        return True

    async def close(self):
        self.closed = True
        try:
            await self.transport.close()
        finally:
            self.key = None
