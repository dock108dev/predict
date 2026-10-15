"""Sequential native HTTP admission, pacing and retry policy.

The session owns budgets and Stop; the caller supplies its observation clock.
This adapter never starts discovery or acquires credentials.
"""

import asyncio
import fnmatch
import time

from app.collection import coverage, native_payload
from app.collection.acquisition_policy import isolated_native
from app.collection.odds_http import BudgetStop
from app.collection.prediction_producer import MockREST


class SequentialREST(MockREST):
    """Sequential per-venue requests; retries are charged by the same client."""

    def __init__(self, *args, clock, **kwargs):
        super().__init__(*args, **kwargs)
        self.clock = clock
        self.request_interval = 1.0  # conservative bootstrap until account lookup
        self.rate = None
        self.costs = None
        self.lock = asyncio.Lock()

    async def bounded_wait(self, delay):
        session = getattr(self, "session", None)
        if not getattr(session, "profile", None):
            await asyncio.sleep(delay)
            return
        remaining = (
            session.started_monotonic + session.spec["duration"] - time.monotonic()
        )
        if session.stop_event.is_set():
            raise asyncio.CancelledError()
        if remaining <= 0:
            raise BudgetStop("prediction_rest_deadline")
        try:
            await asyncio.wait_for(session.stop_event.wait(), min(delay, remaining))
        except TimeoutError:
            if time.monotonic() >= session.started_monotonic + session.spec["duration"]:
                raise BudgetStop("prediction_rest_deadline")
            return
        raise asyncio.CancelledError()

    async def pace(self):
        if getattr(self, "pacing_venue", self.venue):
            await self.bounded_wait(self.request_interval)

    def account_limits(self, limits, costs):
        read = limits["read"]
        self.rate = float(read["refill_rate"])
        self.capacity = float(read["bucket_capacity"])
        self.costs = costs
        if self.rate <= 0 or self.capacity <= 0 or float(costs["default_cost"]) <= 0:
            raise BudgetStop("unusable_account_budget")

    def fail_budget(self, reason):
        session = getattr(self, "session", None)
        if session is None:
            return
        from .native_selectors import gap_enabled

        if (
            gap_enabled(session.spec)
            or getattr(self, "native_scope_request_context", False)
        ) and reason in native_payload.query_cap_reasons(session.spec):
            # This family cannot fit; the fair selector records that terminal
            # operation without removing independent sport opportunities.
            return
        if reason == "native_response_byte_cap" and getattr(
            self, "gap_envelope", False
        ):
            session.discovery.stop_source(self.source_venue, reason)
            return
        if getattr(self, "transport_policy", None) and reason.startswith("native_"):
            session.discovery.stop_source(self.source_venue, reason)
            return
        local = {
            "prediction_discovery_byte_cap",
            "prediction_discovery_request_cap",
            "prediction_session_byte_cap",
            "discovery_generation_request_cap",
            "native_compression_refused",
            "native_parse_rejected",
            "native_incomplete_json",
            "native_malformed_data",
        }
        if isolated_native(session.spec) and reason in local:
            session.discovery.stop_source(self.source_venue, reason)
        else:
            session.request_stop("prediction_rest_resource_cap")

    async def get(self, url, params=None, **kwargs):
        from urllib.parse import urlsplit
        from email.utils import parsedate_to_datetime

        async with self.lock:
            from .us_metadata_diagnostic import enabled as us_diagnostic

            metadata_diagnostic = bool(
                getattr(self, "session", None) and us_diagnostic(self.session.spec)
            )
            if metadata_diagnostic and (
                getattr(self, "source_venue", None) != "polymarket_us"
                or url != self.endpoint + "/v1/events/127804"
                or params not in (None, {})
                or kwargs
            ):
                raise BudgetStop("us_metadata_request_outside_sealed_scope")
            if getattr(self, "session", None) and native_payload.enabled(
                self.session.spec
            ):
                self.native_payload_policy = True
                self.response_cap = native_payload.BODY_LIMITS[
                    native_payload.category(urlsplit(url).path)
                ]
                from .native_selectors import gap_enabled
                from .native_books import enabled as book_slice

                self.gap_envelope = gap_enabled(self.session.spec) or book_slice(
                    self.session.spec
                )
                if self.gap_envelope:
                    self.response_cap = (
                        512 * 1024
                        if coverage.event_path(urlsplit(url).path)
                        else 256 * 1024
                    )
                native_payload.configure_transport(self, self.session.spec)
            elif getattr(self, "session", None):
                # Validate an explicit new contract even outside a named probe.
                # An absent contract continues to select the historical reader.
                native_payload.configure_transport(self, self.session.spec)
            scope_ceiling = getattr(self, "native_scope_generation_ceiling", None)
            if scope_ceiling is not None and self.budget.requests >= scope_ceiling:
                raise BudgetStop("native_scope_generation_request_cap")
            if self.budget.requests >= min(
                self.limits["discovery_requests"],
                getattr(self, "request_ceiling", self.limits["discovery_requests"]),
            ):
                self.fail_budget("prediction_discovery_request_cap")
                raise BudgetStop("prediction_discovery_request_cap")
            if self.rate:
                cost = max(
                    [
                        float(self.costs["default_cost"]),
                        *[
                            float(e["cost"])
                            for e in self.costs["endpoint_costs"]
                            if e["method"] == "GET"
                            and fnmatch.fnmatch(urlsplit(url).path, e["path"])
                        ],
                    ]
                )
                if cost > self.capacity:
                    raise BudgetStop("request_cost_exceeds_account_bucket")
                self.request_interval = max(0.5, cost / self.rate)
            elif getattr(self, "pacing_venue", self.venue) == "polymarket_us":
                self.request_interval = 0.5  # below documented retail 20/s
            from .v1_coverage import enabled as v1_coverage

            attempts = (
                1
                if metadata_diagnostic
                or getattr(self, "gap_envelope", False)
                or getattr(self, "native_scope_request_context", False)
                or v1_coverage(
                    getattr(self, "session", None).spec
                    if getattr(self, "session", None)
                    else {}
                )
                else 2
            )
            for attempt in range(attempts):
                if self.budget.requests >= getattr(
                    self, "request_ceiling", self.limits["discovery_requests"]
                ):
                    raise BudgetStop("discovery_generation_request_cap")
                try:
                    response = await super().get(url, params, **kwargs)
                except BudgetStop as exc:
                    self.fail_budget(str(exc))
                    raise
                except (TimeoutError, __import__("aiohttp").ClientError):
                    if attempt == attempts - 1:
                        raise
                    await self.bounded_wait(1)
                    continue
                if (
                    not metadata_diagnostic
                    and getattr(self, "gap_envelope", False)
                    and response.status_code in (429, 500, 502, 503, 504)
                ):
                    delay = 1.0
                    value = response.headers.get("Retry-After")
                    if value:
                        try:
                            delay = max(delay, float(value))
                        except ValueError:
                            delay = max(
                                delay,
                                (
                                    parsedate_to_datetime(value) - self.clock()
                                ).total_seconds(),
                            )
                    if not 0 <= delay <= 180:
                        raise ValueError("gap_recovery_retry_after_outside_bound")
                    self.gap_retry_at = time.monotonic() + delay
                if (
                    response.status_code not in (429, 500, 502, 503, 504)
                    or attempt == attempts - 1
                ):
                    return response
                delay = 1.0
                retry = response.headers.get("Retry-After")
                if retry:
                    try:
                        delay = max(delay, float(retry))
                    except ValueError:
                        delay = max(
                            delay,
                            (
                                parsedate_to_datetime(retry) - self.clock()
                            ).total_seconds(),
                        )
                if not 0 <= delay <= 180:
                    raise BudgetStop("retry_after_exceeds_deadline")
                await self.bounded_wait(delay)
