"""Finite offline adapter with injected transport/clock and durable ingress.

There is deliberately no HTTP transport, key loading, or default database here.
Synchronous sink writes provide backpressure without an unbounded queue.
"""
import asyncio
import base64
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from typing import AsyncIterator, Protocol
from uuid import uuid4

from app.edge_contracts import ReferenceQuote
from app.storage.store import exact_time
from .records import (EVENT, HEADER_ALLOWLIST, Receipt, ReferenceGap, request_metadata, packed, wire)
from .enrichment import enrich, parse_body


class ReferenceAdapter(Protocol):
    def observe(self, native_event_id: str) -> AsyncIterator[ReferenceQuote | ReferenceGap]: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Bounds:
    max_requests: int = 12
    max_retries: int = 2
    max_seconds: float = 120
    request_timeout: float = 5
    poll_seconds: float = 1
    backoff_seconds: float = 1
    max_backoff_seconds: float = 10
    max_response_bytes: int = 1024 * 1024
    max_total_bytes: int = 12 * 1024 * 1024

    def __post_init__(self):
        if any(not math.isfinite(v) or v <= 0 for k, v in asdict(self).items() if k != 'max_retries') or type(self.max_retries) is not int or self.max_retries < 0:
            raise ValueError('finite positive work bounds required')
        if any(type(getattr(self, k)) is not int for k in ('max_requests', 'max_response_bytes', 'max_total_bytes')):
            raise ValueError('integer work bounds required')


class Clock:
    def now(self): return datetime.now(timezone.utc).isoformat()
    async def sleep(self, seconds): await asyncio.sleep(seconds)


class PersistenceFailure(RuntimeError):
    pass


class OddsAPIReferenceAdapter:
    def __init__(self, *, transport, clock, sink, source, assessment, session_id, failure_journal, bounds=Bounds()):
        self.transport, self.clock, self.sink = transport, clock, sink
        self.source, self.assessment, self.session_id = source, assessment, session_id
        self.failure_journal, self.bounds = Path(failure_journal), bounds
        self._closed = False
        self._owner_task = None
        self._last_success = None
        self._pending_gap = None
        self._started = False

    def _save(self, record):
        try:
            self.sink(record)
        except Exception as exc:
            # A failed DB/queue cannot honestly claim its own failure was saved there.
            # Retain the unsaved record (including raw bytes) and failure outside it.
            failure = {'format': 'reference-failure-journal-1', 'record': wire(record),
                       'detected_at': self.clock.now(), 'failure': type(exc).__name__,
                       'reason': 'queue_failure' if isinstance(exc, asyncio.QueueFull) else 'storage_failure',
                       'durability': 'fallback journal only; primary persistence failed'}
            self.failure_journal.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self.failure_journal.open('a') as f:
                    f.write(packed(failure) + '\n'); f.flush(); os.fsync(f.fileno())
            except Exception as journal_error:
                raise PersistenceFailure('primary storage and fallback journal both failed; durability unknown') from journal_error
            raise PersistenceFailure('primary persistence failed; unsaved evidence retained in fallback journal') from exc

    def _gap(self, reason, receipt=None, recovery=False):
        now = self.clock.now()
        gap = ReferenceGap(id=str(uuid4()), session_id=self.session_id, detected_at=now,
            reason=reason, receipt_id=receipt.id if receipt else None,
            last_success_at=self._last_success,
            prior_gap_id=self._pending_gap if recovery else None,
            end_at=now if recovery else None, recovery='fresh_snapshot' if recovery else 'unresolved')
        self._save(gap)
        self._pending_gap = None if recovery else (self._pending_gap or gap.id)
        return gap

    async def _sleep(self, seconds, deadline):
        # Clock is injected for fixtures; real-loop timeout independently bounds a bad clock.
        remaining = min(deadline - exact_time(self.clock.now()),
                        exact_time(self.assessment.target.scheduled_start.isoformat()) - exact_time(self.clock.now()))
        if remaining <= 0: return
        await self.clock.sleep(min(seconds, float(remaining)))

    async def aclose(self):
        if self._closed: return
        self._closed = True
        task = self._owner_task
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
        await asyncio.wait_for(self.transport.aclose(), timeout=self.bounds.request_timeout)

    async def observe(self, native_event_id):
        if native_event_id != EVENT: raise ValueError('one explicit synthetic event only')
        if self._closed or self._started: raise ValueError('adapter is closed or already consumed')
        self._started = True
        self._owner_task = asyncio.current_task()
        deadline = exact_time(self.clock.now()) + Decimal(str(self.bounds.max_seconds))
        retries, total = 0, 0
        try:
            async with asyncio.timeout(self.bounds.max_seconds):
                for _ in range(self.bounds.max_requests):
                    now = self.clock.now()
                    if self._closed: break
                    if exact_time(now) >= deadline:
                        yield self._gap('work_deadline'); break
                    if exact_time(now) >= exact_time(self.assessment.target.scheduled_start.isoformat()):
                        yield self._gap('kickoff_reached'); break
                    started = now
                    try:
                        request_seconds = min(self.bounds.request_timeout, float(deadline - exact_time(now)),
                            float(exact_time(self.assessment.target.scheduled_start.isoformat()) - exact_time(now)))
                        async with asyncio.timeout(request_seconds):
                            response = await self.transport.request(request_metadata())
                    except (TimeoutError, OSError):
                        yield self._gap('transport_failure')
                        retries += 1
                        if retries > self.bounds.max_retries: break
                        await self._sleep(min(self.bounds.backoff_seconds * 2 ** (retries - 1), self.bounds.max_backoff_seconds), deadline)
                        continue
                    # Assign arrival before parsing or saving, including rejected/error bodies.
                    receipt = Receipt(id=str(uuid4()), session_id=self.session_id, received_at=self.clock.now(),
                        request_started_at=started, body_b64=base64.b64encode(response.body).decode(),
                        body_sha256=sha256(response.body).hexdigest(), status=response.status,
                        request_json=packed(request_metadata()),
                        headers=tuple((k.lower(), str(v)) for k, v in response.headers if k.lower() in HEADER_ALLOWLIST))
                    self._save(receipt)
                    total += len(response.body)
                    if len(response.body) > self.bounds.max_response_bytes or total > self.bounds.max_total_bytes:
                        yield self._gap('payload_work_limit', receipt); break
                    try: error_code = parse_body(receipt).get('error_code')
                    except (ValueError, UnicodeError): error_code = None
                    headers = dict(receipt.headers)
                    try:
                        exhausted = any(int(v) <= 0 for k, v in receipt.headers if k == 'x-requests-remaining')
                    except ValueError:
                        exhausted = True
                    quota = error_code == 'OUT_OF_USAGE_CREDITS' or exhausted
                    entitlement = response.status in (401, 403)
                    # Even last-credit successful responses retain their enrichment.
                    revision = enrich(receipt, self.source, self.assessment)
                    self._save(revision)
                    if revision.quote is not None:
                        yield revision.quote
                    if quota or entitlement:
                        yield self._gap('quota_exhausted' if quota else 'entitlement_stop', receipt); break
                    if response.status == 429 or response.status >= 500:
                        yield self._gap('http_429' if response.status == 429 else 'http_server_failure', receipt)
                        retries += 1
                        if retries > self.bounds.max_retries: break
                        wait = min(self.bounds.backoff_seconds * 2 ** (retries - 1), self.bounds.max_backoff_seconds)
                        if 'retry-after' in headers:
                            try: wait = max(wait, float(headers['retry-after']))
                            except ValueError:
                                try: wait = max(wait, parsedate_to_datetime(headers['retry-after']).timestamp() - datetime.fromisoformat(self.clock.now()).timestamp())
                                except (ValueError, TypeError):
                                    yield self._gap('invalid_retry_guidance_stop', receipt); break
                        if not math.isfinite(wait) or wait > self.bounds.max_backoff_seconds or wait > float(deadline - exact_time(self.clock.now())):
                            yield self._gap('retry_guidance_exceeds_budget', receipt); break
                        await self._sleep(wait, deadline)
                        continue
                    if response.status != 200:
                        yield self._gap('http_rejected', receipt); break
                    stop_reasons = ('schedule_or_identity_unresolved', 'phase_unresolved', 'kickoff_reached',
                                    'schedule_unresolved', 'missing_or_wrong_event_identity', 'ambiguous_or_missing_participants', 'missing_participant_identity')
                    if any(reason in revision.reasons for reason in stop_reasons):
                        yield self._gap('phase_schedule_identity_stop', receipt); break
                    complete = revision.quote is not None and None not in revision.quote.decimal_odds
                    if not complete:
                        yield self._gap('rejected_or_incomplete_snapshot', receipt)
                        retries += 1
                        if retries > self.bounds.max_retries: break
                    else:
                        if self._pending_gap:
                            yield self._gap('observed_recovery', receipt, recovery=True)
                        self._last_success = receipt.received_at
                        retries = 0
                    await self._sleep(self.bounds.poll_seconds, deadline)
                else:
                    yield self._gap('request_bound_reached')
        except asyncio.CancelledError:
            self._gap('cancelled')
            raise
        except TimeoutError:
            yield self._gap('work_deadline')
        except PersistenceFailure:
            raise
        except Exception as exc:
            self._gap('unexpected_failure:' + type(exc).__name__)
            raise
        except GeneratorExit:
            self._gap('consumer_closed')
            raise
        finally:
            await self.aclose()
