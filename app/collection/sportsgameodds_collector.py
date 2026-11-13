"""Guarded single-page SGO acquisition primitive; no autonomous dispatch.

The owning runtime must bind a fresh account observation, controls and a durable
consumer. It must not start this component merely because a key exists.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from collections import Counter

from .sportsgameodds_adapter import parse_page
from .sportsgameodds_schedule import daily_allowance, daily_retry_at, response_object_charge
from .sportsgameodds_transport import validate_params


class RejectedCursor(RuntimeError):
    """The cursor was rejected; its request remains an uncertain charge."""


class DailyObjectPacing(RuntimeError):
    def __init__(self, *, retry_at, requested, rolling, allowance):
        super().__init__('daily object pacing limit')
        self.retry_at = retry_at
        self.requested = requested
        self.rolling = rolling
        self.allowance = allowance


class GuardedPageCollector:
    def __init__(self, ledger, window_id, transport, *, controls, account_usage):
        self.ledger = ledger
        self.window_id = window_id
        self.transport = transport
        self.controls = controls
        self.account_usage = account_usage

    async def fetch(self, params, api_key, *, now=None):
        params = validate_params(params)
        state = self.ledger.status(self.window_id)
        if state['reset_at'] is None:
            raise RuntimeError('account reset evidence unavailable')
        # Do not dispatch around a charge whose amount is still uncertain.
        if state['held']:
            raise RuntimeError('unresolved provider object reservation')
        observed = await self.account_usage()
        now = now or datetime.now(timezone.utc)
        # A higher provider count is conservatively recorded as external usage.
        # A lower count may be lag or an actual reset; neither releases exposure.
        if (not isinstance(observed, dict) or type(observed.get('used')) is not int
                or observed.get('limit') != state['limit'] or observed.get('reset_at') != state['reset_at']
                or type(observed.get('requests_per_minute')) is not int
                or observed['requests_per_minute'] < state['requests_per_minute']
                or not isinstance(observed.get('at'), datetime)
                or observed['at'].tzinfo is None or observed['at'].utcoffset() is None
                or not timedelta(0) <= now - observed['at'] <= timedelta(seconds=60)):
            raise RuntimeError('current account usage evidence unavailable or changed')
        self.ledger.reconcile_increase(self.window_id, used=observed['used'], now=now)
        state = self.ledger.status(self.window_id)
        rolling = self.ledger.rolling_objects(self.window_id, since=now-timedelta(days=1))
        per_day = daily_allowance(available=state['available'] + rolling, now=now, reset_at=state['reset_at'])
        if rolling + params['limit'] > per_day:
            retry = daily_retry_at(available=state['available'], requested=params['limit'], now=now,
                reset_at=state['reset_at'], expirations=self.ledger.rolling_expirations(self.window_id, now=now))
            raise DailyObjectPacing(retry_at=retry, requested=params['limit'], rolling=rolling, allowance=per_day)
        control = self.controls()
        attempt = str(uuid4())
        self.ledger.reserve(self.window_id, attempt, objects=params['limit'], now=now,
                            stopped=control['stopped'], source_paused=control['source_paused'],
                            category='discovery' if 'leagueID' in params else 'event_refresh',
                            league=params.get('leagueID'), request=params, usage=observed)
        # Recheck after reservation and immediately before dispatch. An unused
        # reservation is released only with a locally certain no-dispatch receipt.
        control = self.controls()
        if control['stopped'] or control['source_paused']:
            self.ledger.resolve(attempt, charged=0, evidence='control revoked before dispatch', now=now)
            raise RuntimeError('collection stopped or source paused')
        response = await self.transport.fetch(params, api_key)
        self.ledger.record_response(attempt, response)
        if response.status == 429:
            if response.retry_after_seconds:
                received = datetime.fromisoformat(response.received_at.replace('Z','+00:00'))
                self.ledger.note_rate_limit(self.window_id,
                    retry_after=received + timedelta(seconds=response.retry_after_seconds), now=received)
            else:
                self.ledger.set_paused(self.window_id, True)
            raise RuntimeError('provider rate limited; charge remains held')
        if response.status == 400 and response.invalid_cursor and 'cursor' in params:
            raise RejectedCursor('provider rejected cursor; charge remains held')
        if response.status != 200:
            raise RuntimeError('provider response unsuccessful; charge remains held')
        venues = set(params['bookmakerID'].split(',')) if 'bookmakerID' in params else None
        page = parse_page(response.body, response.received_at, venues=venues)
        charged = response_object_charge(len(page.events))
        # One object per returned event; the minimum charge on an empty page
        # has no observed event phase. Never infer phase from a request.
        leagues = {'NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL'}
        phases = {'pregame', 'live', 'started'}
        breakdown = Counter((event.get('league') if event.get('league') in leagues else 'unknown',
                             event.get('phase') if event.get('phase') in phases else 'unknown')
                            for event in page.events)
        if not page.events:
            breakdown[(params.get('leagueID', 'unknown'), 'unknown')] = 1
        self.ledger.resolve(attempt, charged=charged, evidence='parsed provider response', now=now,
                            breakdown=dict(breakdown))
        return page
