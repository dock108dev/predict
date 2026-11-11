"""Runtime owner for bounded SGO discovery and current-row ingestion.

Paid dispatch requires explicit fresh provider account limits and reset. This
worker does not infer absent events from pagination and never withdraws rows
from an incomplete, moving, or successful-but-not-snapshot traversal.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from .current_ingress import call, operation
from .current_policy import ROOT, aggregate_scope
from .sportsgameodds_adapter import Traversal
from .sportsgameodds_collector import GuardedPageCollector
from .sportsgameodds_current_rows import current_rows
from .sportsgameodds_ledger import ObjectLedger
from .sportsgameodds_schedule import EventDue, due_events
from .sportsgameodds_transport import ODD_IDS, SportsgameoddsTransport
from .sportsgameodds_usage import read_usage


def credential():
    value = os.environ.get('SPORTSGAMEODDS_API_KEY')
    if value:
        return value.strip()
    path = ROOT / '.local/sportsgameodds-evaluation.env'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise ValueError('SportsGameOdds credential unavailable')
    entries = [line.split('=', 1)[1].strip().strip("\"'") for line in path.read_text().splitlines()
               if line.startswith('SPORTSGAMEODDS_API_KEY=')]
    if len(entries) != 1 or not entries[0]:
        raise ValueError('SportsGameOdds credential unavailable')
    return entries[0]


def clock():
    return datetime.now(timezone.utc)


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
                        'records':0, 'excluded':0, 'next_refresh_at':None}
        self.phase = 'initializing'
        self.ledger = None
        self.window_id = None
        self.collector = None
        self.events = {}
        self.discovery_at = {}
        self.discovery_progress = {}
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
        self.request_limit = observed['requests_per_minute']
        if observed.get('reset_at') is None:
            raise RuntimeError('account reset evidence unavailable')
        reset = observed['reset_at']
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
        self.collector = GuardedPageCollector(self.ledger, self.window_id, self.transport,
                                              controls=self.controls, account_usage=self.usage)
        self.metrics.update(state='waiting', account_tier=observed.get('tier'))
        self._account_status()

    def _account_status(self):
        if self.ledger is None or self.window_id is None:
            return
        value = self.ledger.status(self.window_id)
        self.metrics['objects'] = {k: v.isoformat() if isinstance(v, datetime) else v for k,v in value.items()}

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
        self.metrics['records'] += len(records)
        self.metrics['reference_rows'] = self.metrics.get('reference_rows', 0) + len(reference_rows)

    async def _fetch(self, params):
        self.phase = 'collecting'
        try:
            page = await self.collector.fetch(params, self.key)
            self.metrics['requests'] += 1
            self.metrics['pages'] += 1
            self.metrics['events'] += len(page.events)
            for event in page.events:
                if event['league'] not in aggregate_scope(self.service.config):
                    raise ValueError('provider returned outside configured scope')
                if event['status'].get('ended') or event['status'].get('completed') or event['status'].get('cancelled'):
                    self.events.pop(event['event_id'], None)
                else:
                    self.events[event['event_id']] = event
                if len(self.events) > self.max_events:
                    raise ValueError('event scheduling capacity exceeded')
            await self._publish(page)
            return page
        finally:
            self._account_status()

    def params(self, *, league=None, event_ids=None, cursor=None):
        result = {'oddID': ','.join(sorted(ODD_IDS)), 'limit': self.page_limit,
                  'includeOpposingOdds': True}
        if league is not None:
            result['leagueID'] = league
        else:
            result['eventIDs'] = ','.join(event_ids)
        if cursor is not None:
            result['cursor'] = cursor
        return result

    async def cycle(self):
        now = self.now()
        # Previously discovered live and imminent events take priority over a
        # potentially broad discovery walk. Receipt time is scheduling only.
        candidates = [EventDue(e['event_id'], datetime.fromisoformat(e['starts_at'].replace('Z','+00:00')),
                     datetime.fromisoformat(e['received_at'].replace('Z','+00:00')), e['phase']=='live')
                      for e in self.events.values()]
        due = due_events(candidates, now, **self.controls_to_schedule())
        for start in range(0, len(due), self.page_limit):
            batch = due[start:start+self.page_limit]
            await self._fetch(self.params(event_ids=[event.event_id for event in batch]))
        for league in aggregate_scope(self.service.config):
            if self.controls()['stopped'] or self.controls()['source_paused']:
                return
            if league not in self.discovery_progress and league in self.discovery_at and now-self.discovery_at[league] < timedelta(hours=12):
                continue
            traversal = self.discovery_progress.setdefault(league, Traversal(max_pages=100))
            for _ in range(self.max_pages):
                cursor = traversal.next_cursor
                page = await self._fetch(self.params(league=league, cursor=cursor))
                traversal.add(cursor, page)
                # Keep bounded cursor and event identities, not entire payloads.
                traversal.pages[-1] = None
                if traversal.complete:
                    self.discovery_progress.pop(league, None)
                    self.discovery_at[league] = now
                    break
                if len(traversal.pages) >= traversal.max_pages:
                    self.discovery_progress.pop(league, None)
                    self.discovery_at[league] = now
                    break
            self.metrics.setdefault('discovery_complete', {})[league] = traversal.complete
        self.phase = 'waiting_for_cycle'
        self.metrics['next_refresh_at'] = (self.now()+timedelta(minutes=15)).isoformat()

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
        for venue in ('novig','prophetx'):
            await call(self.service, self.service.source_state, venue, state, reason)

    async def run(self):
        if not self.service.database_mode:
            await self.state('unavailable', 'sgo_database_required', 'SportsGameOdds requires current-row storage.')
            return
        try:
            await self.state('connecting', 'sgo_connecting', 'Connecting to SportsGameOdds account usage.')
            await self.initialize()
            while not self.controls()['stopped'] and not self.controls()['source_paused']:
                try:
                    await self.cycle()
                except RuntimeError as exc:
                    if str(exc) == 'daily object pacing limit':
                        self.phase = 'waiting_for_budget'
                        delay, code = 60*60, 'sgo_daily_pacing'
                        reason = 'SportsGameOdds is waiting for its daily object budget; prices retain their original source times.'
                    elif str(exc) == 'request rate limit':
                        self.phase = 'waiting_for_rate'
                        delay, code = 60, 'sgo_request_rate'
                        reason = 'SportsGameOdds is waiting for its request limit to reset.'
                    else:
                        raise
                    self.metrics['next_refresh_at'] = (self.now()+timedelta(seconds=delay)).isoformat()
                    await self.state('budget_delayed', code, reason)
                    await asyncio.sleep(delay)
                    continue
                await self.state('budget_delayed', 'sgo_cycle_complete', 'SportsGameOdds prices are attributed aggregate observations; source freshness is checked separately.')
                await asyncio.sleep(15*60)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reasons = {'account reset evidence unavailable':'The provider did not report an account reset time.',
                       'account reset evidence expired':'The account reset evidence has expired.',
                       'current account usage evidence unavailable or changed':'Current account usage could not be safely reconciled.',
                       'unresolved provider object reservation':'An earlier provider request has an unresolved object charge.',
                       'provider rate limited; charge remains held':'The provider rate limit was reached; the request charge remains held.',
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

    async def close(self):
        if not self.closed:
            self.closed = True
            await self.transport.close()
        self.key = None
