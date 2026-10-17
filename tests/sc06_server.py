"""SC06 test-owned full SQL → financial projection → HTTP browser server.

Requires a verified disposable socket. Authoring adapters do not exist in the
ordinary app. All clocks advance; unchanged source clocks are never renewed.
"""

import asyncio
from collections import deque
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import tempfile
from time import perf_counter, process_time, thread_time
from threading import Event, Lock, local, Thread
from queue import Queue, Full

from aiohttp import web
from app.comparison.current_dependencies import digest, instant
from app.comparison.scanner_destinations import Destinations
from app.dashboard.scanner_api import mount
from app.dashboard.scanner_client_api import mount as mount_client
from app.storage.current_rows import CurrentRowStore, contract_id
from app.storage.scanner_publication import transaction, subscribe
from tests import test_sc02_sql as sql
from tests.sc06_fixture import (
    records,
    native_books,
    AuthoredAdapters,
    Clock,
    assert_authored_originals,
)
from tests.test_sc03_tickets import catalog

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "app/dashboard/opportunity_static/current"


class AdmissionDBObserver:
    """Opt-in diagnostic only; never retains SQL text or parameter values."""

    def __init__(self, db, connector, phase):
        self.db = db
        self.connector = connector
        self.phase = phase
        self.backend_pid = db.info.backend_pid
        self.aggregates = {}
        self.aggregate_overflow = 0
        self.slowest = []
        self.wait_samples = []
        self.wait_sample_overflow = 0
        self.sampler_error = None
        self.sampler_done = Event()
        self.sampler = Thread(target=self._sample, daemon=True)
        self.sampler.start()

    def __getattr__(self, name):
        return getattr(self.db, name)

    def _timed(self, signature, operation, callback):
        start, cpu, process = perf_counter(), thread_time(), process_time()
        phase = self.phase()
        error = None
        try:
            return callback()
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            end = perf_counter()
            item = dict(
                signature=signature,
                operation=operation,
                phase=phase,
                start=start,
                end=end,
                wall_ms=(end - start) * 1000,
                thread_cpu_ms=(thread_time() - cpu) * 1000,
                process_cpu_ms=(process_time() - process) * 1000,
                error=error,
            )
            key = (signature, operation, phase)
            aggregate = self.aggregates.get(key)
            if aggregate is None and len(self.aggregates) < 64:
                aggregate = self.aggregates[key] = dict(
                    signature=signature,
                    operation=operation,
                    phase=phase,
                    calls=0,
                    wall_ms=0,
                    thread_cpu_ms=0,
                    process_cpu_ms=0,
                    max_wall_ms=0,
                    errors=0,
                )
            if aggregate is None:
                self.aggregate_overflow += 1
            else:
                aggregate["calls"] += 1
                for k in ("wall_ms", "thread_cpu_ms", "process_cpu_ms"):
                    aggregate[k] += item[k]
                aggregate["max_wall_ms"] = max(
                    aggregate["max_wall_ms"], item["wall_ms"]
                )
                aggregate["errors"] += int(error is not None)
            self.slowest.append(item)
            self.slowest.sort(key=lambda x: -x["wall_ms"])
            del self.slowest[20:]

    def execute(self, statement, *args, **kwargs):
        # Hash only the caller's SQL template; parameter values never enter it.
        template = statement if isinstance(statement, str) else type(statement).__name__
        signature = hashlib.sha256(template.encode()).hexdigest()
        cursor = self._timed(
            signature,
            "execute",
            lambda: self.db.execute(statement, *args, **kwargs),
        )
        return AdmissionCursorObserver(cursor, self, signature)

    def _sample(self):
        previous = None
        try:
            with self.connector() as observer:
                observer.autocommit = True
                while not self.sampler_done.is_set():
                    start = perf_counter()
                    row = observer.execute(
                        "SELECT pid,state,wait_event_type,wait_event FROM pg_stat_activity WHERE pid=%s",
                        (self.backend_pid,),
                    ).fetchone()
                    sample = dict(
                        start=start,
                        end=perf_counter(),
                        scheduling_lag_ms=None
                        if previous is None
                        else max(0, (start - previous) * 1000 - 50),
                        backend=None if row is None else dict(row),
                    )
                    if len(self.wait_samples) < 512:
                        self.wait_samples.append(sample)
                    else:
                        self.wait_sample_overflow += 1
                    previous = start
                    if self.sampler_done.wait(0.05):
                        break
        except BaseException as exc:
            self.sampler_error = type(exc).__name__

    def finish(self):
        self.sampler_done.set()
        self.sampler.join(timeout=2)
        return dict(
            backend_pid=self.backend_pid,
            aggregates=list(self.aggregates.values()),
            aggregate_bound=64,
            aggregate_overflow_calls=self.aggregate_overflow,
            slowest_calls=self.slowest,
            slowest_bound=20,
            pg_stat_activity=self.wait_samples,
            wait_sample_bound=512,
            wait_sample_overflow=self.wait_sample_overflow,
            sampler_error=self.sampler_error,
            sampler_still_running=self.sampler.is_alive(),
            sampler_interval_ms=50,
            interpretation="Diagnostic overhead included; execute/fetch wall time includes Python scheduling and server/client waits. Process CPU includes other threads. Wait-event samples are observations, not complete CPU attribution.",
        )


class AdmissionCursorObserver:
    def __init__(self, cursor, observer, signature):
        self.cursor, self.observer, self.signature = cursor, observer, signature

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def fetchone(self):
        return self.observer._timed(self.signature, "fetchone", self.cursor.fetchone)

    def fetchall(self):
        return self.observer._timed(self.signature, "fetchall", self.cursor.fetchall)


def product_http_path(path):
    return path == "/api/scanner" or path.startswith("/api/scanner/")


def product_http_entry(req, response, before, completed, error=None):
    entry = dict(
        path=req.path,
        method=req.method,
        started=before,
        completed=completed,
        status=getattr(response, "status", None),
    )
    if error is not None:
        entry["error"] = error
    if (
        req.path == "/api/scanner/ticket"
        and req.method == "POST"
        and getattr(response, "body", None)
    ):
        try:
            value = json.loads(response.body)
            if not isinstance(value, dict):
                raise ValueError("non-object product ticket response")
            entry["ticket"] = {
                k: value.get(k)
                for k in (
                    "state",
                    "ready_for_manual_action",
                    "selection",
                    "timing",
                    "error",
                )
            }
            selected = value.get("selected_frame")
            entry["ticket"]["selected_frame"] = (
                None
                if not isinstance(selected, dict)
                else {
                    k: selected.get(k)
                    for k in ("id", "dependency_revision", "expires_at")
                }
            )
        except (ValueError, TypeError, UnicodeError) as exc:
            entry["ticket_decode_error"] = type(exc).__name__
    return entry


def create_app(count=500):
    if (
        os.environ.get("SC06_TRACE_DIR")
        and (Path(os.environ["SC06_TRACE_DIR"]) / "sql-traces.jsonl").exists()
    ):
        raise ValueError(
            "SC06 trace destination already exists; choose a fresh evidence directory"
        )
    if not sql.SOCKET:
        raise ValueError("SC06 requires a verified disposable PostgreSQL socket")
    sql.SQL.setUpClass()
    temp = tempfile.TemporaryDirectory(prefix="sc06-summary-")
    # Runtime-only worker store is redirected before Scanner construction.
    from unittest.mock import patch

    root_patch = patch("app.storage.store.ROOT", Path(temp.name))
    root_patch.start()
    from app.comparison.estimated_policy import RequestedTradePolicy

    policy_patch = patch(
        "app.dashboard.scanner_api.load",
        return_value=RequestedTradePolicy(capital_ceiling_usd="1000"),
    )
    policy_patch.start()
    adapters = AuthoredAdapters()
    adapters.__enter__()
    import socket

    network_attempts = []
    real_connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in (
            "127.0.0.1",
            "::1",
            "localhost",
        ):
            network_attempts.append(dict(host=str(address[0]), port=address[1]))
            raise AssertionError("SC06 forbids provider requests")
        return real_connect(sock, address)

    network_patch = patch.object(socket.socket, "connect", local_only)
    network_patch.start()
    app = web.Application()
    clock = Clock()
    provider = sql.SQL.provider(None)
    provider.states = {
        v: dict(state="available", reason_code="sc06_explicit_authored_source")
        for v in ("kalshi", "polymarket_us", "novig", "prophetx")
    }
    scanner = mount(app, provider)
    scanner.connector = sql.SQL.connect
    scanner.clock = clock
    scanner.projection.clock = clock
    scanner.tickets.clock = clock
    scanner.tickets.allow_authored = True
    from app.collection.current_policy import candidate
    from app.storage.current_games import engine_binding
    from app.comparison.scanner_readiness import POLICY_REVISION

    application, inventory = candidate()
    binding = dict(
        application=application,
        engine=engine_binding(),
        readiness_policy=POLICY_REVISION,
        application_files=len(inventory),
        assets=json.loads((ASSETS / "scanner-runtime.json").read_text()),
        schema="012_current_rows.sql",
        python=sys.version,
        sql_database=sql.SQL.name,
    )
    rows = records(count, at=clock())
    update_counts = [0] * count
    traces = deque()
    samples = []
    commits = deque(maxlen=512)
    trace_bytes = 0
    trace_dropped = 0
    trace_lock = Lock()
    admission_local = local()
    trace_directory = Path(os.environ.get("SC06_TRACE_DIR", temp.name + "/traces"))
    trace_directory.mkdir(parents=True, exist_ok=True)
    trace_path = trace_directory / "sql-traces.jsonl"
    trace_queue = Queue(maxsize=64)
    stream = dict(
        path=str(trace_path),
        written_entries=0,
        written_bytes=0,
        physical_bytes=0,
        queued_bytes=0,
        queue_peak_bytes=0,
        dropped=0,
        error=None,
        bound_bytes=64 * 1024**2,
        queue_bound_entries=64,
        queue_bound_bytes=4 * 1024**2,
    )

    trace_handle = trace_path.open("xb", buffering=0)

    def persist_traces():
        with trace_handle as handle:
            while True:
                payload = trace_queue.get()
                if payload is None:
                    trace_queue.task_done()
                    return
                try:
                    if stream["error"] is not None:
                        raise RuntimeError("trace worker already failed")
                    if (
                        stream["written_bytes"] + len(payload) + 128 * 1024
                        >= stream["bound_bytes"]
                        or shutil.disk_usage(trace_directory).free < 1024**3
                    ):
                        raise RuntimeError("trace physical storage/free disk guard")
                    handle.write(payload)
                    physical = (
                        os.fstat(handle.fileno()).st_blocks * 512
                        + trace_directory.stat().st_blocks * 512
                    )
                    if physical > stream["bound_bytes"]:
                        raise RuntimeError("trace physical storage guard")
                    with trace_lock:
                        stream["written_entries"] += 1
                        stream["written_bytes"] += len(payload)
                        stream["physical_bytes"] = physical
                except Exception as exc:
                    with trace_lock:
                        stream["error"] = str(exc)
                        stream["dropped"] += 1
                finally:
                    with trace_lock:
                        stream["queued_bytes"] -= len(payload)
                    trace_queue.task_done()

    trace_worker = Thread(
        target=persist_traces, name="sc06-test-trace-writer", daemon=True
    )
    trace_worker.start()

    def trace(value):
        # Test observations are bounded by bytes as well as count. A dropped
        # causal observation is explicit and disqualifies a campaign.
        nonlocal trace_bytes, trace_dropped
        payload = json.dumps(value, separators=(",", ":")).encode() + b"\n"
        size = len(payload)
        enqueued = False
        with trace_lock:
            if stream["queued_bytes"] + size > stream["queue_bound_bytes"]:
                stream["dropped"] += 1
            else:
                try:
                    trace_queue.put_nowait(payload)
                    enqueued = True
                    stream["queued_bytes"] += size
                    stream["queue_peak_bytes"] = max(
                        stream["queue_peak_bytes"], stream["queued_bytes"]
                    )
                except Full:
                    stream["dropped"] += 1
            traces.append((value, size))
            trace_bytes += size
            while len(traces) > 8192 or trace_bytes > 16 * 1024**2:
                _, removed = traces.popleft()
                trace_bytes -= removed
                trace_dropped += 1
        return enqueued

    def committed(value):
        commits.append(value)
        admission_local.observation = value

    trace_close = subscribe(committed)
    started = perf_counter()

    def guard():
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
            1 if sys.platform == "darwin" else 1024
        )
        with sql.SQL.connect() as db:
            size = db.execute(
                "select pg_database_size(current_database()) n"
            ).fetchone()["n"]
        free = shutil.disk_usage(temp.name).free
        if stream["error"] is not None or stream["dropped"]:
            raise RuntimeError("SC06 trace persistence guard")
        if rss > 768 * 1024**2 or size > 2 * 1024**3 or free < 1024**3:
            raise RuntimeError("SC06 resource guard")
        return dict(peak_rss_bytes=rss, sql_bytes=size, free_disk_bytes=free)

    def ingest(changed, sample=None, receipt=None):
        receipt = perf_counter() if receipt is None else receipt
        admission = perf_counter()
        phases = dict(admission_started=admission)
        assert_authored_originals(changed)
        phases["originals_checked"] = perf_counter()
        admission_local.observation = None
        diagnostic = None
        with sql.SQL.connect() as raw_db:
            db = raw_db
            if (
                os.environ.get("SC06_ADMISSION_DIAGNOSTICS") == "1"
                and sample != "initial"
            ):
                diagnostic = AdmissionDBObserver(
                    raw_db, sql.SQL.connect, lambda: next(reversed(phases))
                )
            phases["connection_ready"] = perf_counter()
            if diagnostic is not None:
                db = diagnostic
            try:
                with transaction(db):
                    s = CurrentRowStore(db)
                    s.upsert_records(changed)
                    phases["offers_upserted"] = perf_counter()
                    books = native_books(changed)
                    phases["native_books_authored"] = perf_counter()
                    s.replace_native_books(books)
                    phases["native_books_replaced"] = perf_counter()
                    decoded = db.execute(
                        "SELECT facts,price_value,price_units FROM current_offer WHERE contract_id=ANY(%s)",
                        ([contract_id(r) for r in changed],),
                    ).fetchall()
                    if len(decoded) != len(changed):
                        raise AssertionError("SC06 SQL original count mismatch")
                    assert_authored_originals([dict(quote=r["facts"]) for r in decoded])
                    if any(
                        r["facts"]["original"]["value"] != r["price_value"]
                        or r["facts"]["original"]["units"] != r["price_units"]
                        for r in decoded
                    ):
                        raise AssertionError("SC06 SQL original column/fact mismatch")
                    phases["decoded_originals_checked"] = perf_counter()
                phases["transaction_committed"] = perf_counter()
            finally:
                if diagnostic is not None:
                    trace(
                        dict(
                            stage="admission_db_diagnostic",
                            sample=sample,
                            **diagnostic.finish(),
                        )
                    )
        done = perf_counter()
        proof = deepcopy(admission_local.observation)
        result = dict(
            sample=sample,
            receipt_monotonic=receipt,
            admission_monotonic=admission,
            admission_ms=(done - admission) * 1000,
            admission_phases=phases,
            commit_observation=proof,
            original_consistency=dict(
                authored_checked=len(changed),
                sql_decoded_checked=len(decoded),
                rule="current-contract identity native_value=value and native_units=units; SQL price columns equal quote facts",
            ),
            source=[
                dict(
                    contract_id=contract_id(r),
                    event=r["event"]["id"],
                    source=r["quote"]["source"],
                    source_at=r["quote"]["times"]["source_at"],
                    price=r["quote"]["original"]["value"],
                )
                for r in changed
            ],
        )
        trace(
            dict(
                stage="admission",
                **result,
                source_count=len(result["source"]),
                source_identity_sha256=digest(result["source"]),
            )
        )
        result.update(guard())
        samples.append(result)
        return result

    with sql.SQL.connect() as db:
        db.execute("TRUNCATE current_event CASCADE")
    ingest(rows, sample="initial")
    capture = scanner._capture

    def measured_capture(*args, **kwargs):
        start = perf_counter()
        try:
            f, x, m, ms = capture(*args, **kwargs)
            trace(
                dict(
                    stage="capture",
                    start=start,
                    end=perf_counter(),
                    input_revision=f["input_revision"],
                    readiness_revision=f["revision"],
                    current_rows_revision=m["current_rows_revision"],
                    instruments=len(f["instruments"]),
                    pairs=len(f["pairs"]),
                    preparation_cache=m.get("preparation_cache"),
                    ms=ms,
                )
            )
            return f, x, m, ms
        except Exception as exc:
            trace(
                dict(
                    stage="capture_failed",
                    start=start,
                    end=perf_counter(),
                    error=str(exc),
                )
            )
            raise

    scanner._capture = measured_capture
    probe = scanner._probe

    def measured_probe(*args, **kwargs):
        before = perf_counter()
        try:
            value = probe(*args, **kwargs)
            trace(
                dict(stage="probe", start=before, end=perf_counter(), marker=value[0])
            )
            return value
        except Exception as exc:
            trace(
                dict(
                    stage="probe_failed",
                    start=before,
                    end=perf_counter(),
                    error=type(exc).__name__,
                )
            )
            raise

    scanner._probe = measured_probe
    materialize = scanner.projection._materialize

    def measured_materialize(reason):
        before = perf_counter()
        try:
            return materialize(reason)
        finally:
            trace(
                dict(
                    stage="materialize",
                    start=before,
                    end=perf_counter(),
                    reason=reason,
                    pending=len(scanner.projection.pending),
                    cached_pairs=len(scanner.projection.cache),
                    receipts=len(scanner.projection.receipts),
                    publication=scanner.projection.publication,
                )
            )

    scanner.projection._materialize = measured_materialize
    evaluator = scanner.projection.evaluator

    def measured_finance(pair, instruments, inputs, **kwargs):
        start = perf_counter()
        value = evaluator(pair, instruments, inputs, **kwargs)
        trace(
            dict(
                stage="finance",
                start=start,
                end=perf_counter(),
                pair_id=pair["id"],
                event=pair["occurrence_id"],
                source=[
                    dict(
                        id=k,
                        source=instruments[k]["native_key"],
                        clocks=instruments[k]["clocks"],
                    )
                    for k in pair["legs"]
                ],
                search=value["search"],
                qualifying=value["qualifying"],
                rows=len(value["rows"]),
            )
        )
        return value

    scanner.projection.evaluator = measured_finance
    # The selected callback executes a genuinely fresh SQL proof; record the
    # production path without replacing its inputs, clock or deadline.
    for callback_name in ("fresh", "fresh_selected"):
        callback = getattr(scanner.tickets, callback_name, None)
        if callback:

            def measured_fresh(
                *args, _callback=callback, _name=callback_name, **kwargs
            ):
                before = perf_counter()
                try:
                    value = _callback(*args, **kwargs)
                    frame = value[0]
                    trace(
                        dict(
                            stage="ticket_" + _name,
                            start=before,
                            end=perf_counter(),
                            outcome="returned",
                            input_revision=frame["input_revision"],
                            readiness_revision=frame["revision"],
                            instruments=len(frame["instruments"]),
                            pairs=len(frame["pairs"]),
                            source=[
                                dict(native_key=i["native_key"], clocks=i["clocks"])
                                for i in frame["instruments"]
                            ],
                        )
                    )
                    return value
                except Exception as exc:
                    trace(
                        dict(
                            stage="ticket_" + _name,
                            start=before,
                            end=perf_counter(),
                            outcome=type(exc).__name__,
                        )
                    )
                    raise

            setattr(scanner.tickets, callback_name, measured_fresh)
    publish = scanner.projection._publish
    previous_bindings = {}

    def measured_publish(result, reason):
        nonlocal previous_bindings
        start = perf_counter()
        publish(result, reason)
        bindings = {
            r["id"]: dict(
                row_id=r["id"],
                pair_id=r["pair_id"],
                dependency_revision=r["dependency_revision"],
                economic_revision=r["economic_revision"],
                evaluated_at=r["evaluated_at"],
                source_clocks=deepcopy(r["source_clocks"]),
            )
            for r in result.values()
        }
        trace(
            dict(
                stage="publication",
                start=start,
                end=perf_counter(),
                revision=scanner.projection.publication,
                reason=reason,
                pending=len(scanner.projection.pending),
                row_count=len(result),
                coverage=scanner.projection.state,
                input_revision=scanner.projection.capture_revision,
                bindings=[
                    v for k, v in bindings.items() if previous_bindings.get(k) != v
                ],
                removed=sorted(set(previous_bindings) - set(bindings)),
                bindings_meaning="changed bindings only; unchanged rows retain prior exact facts",
            )
        )
        previous_bindings = bindings

    scanner.projection._publish = measured_publish
    requests = deque(maxlen=2048)
    http_recorder = dict(
        product_entries=0,
        ring_evictions=0,
        durable_enqueued=0,
        durable_enqueue_failed=0,
    )

    @web.middleware
    async def observe(req, handler):
        # Test-state/clock/control polling never decodes or consumes product proof.
        if not product_http_path(req.path):
            return await handler(req)
        before = perf_counter()
        response = None
        error = None
        try:
            response = await handler(req)
            return response
        except BaseException as exc:
            error = type(exc).__name__
            if isinstance(exc, web.HTTPException):
                response = exc
            raise
        finally:
            entry = product_http_entry(req, response, before, perf_counter(), error)
            if len(requests) == requests.maxlen:
                http_recorder["ring_evictions"] += 1
            requests.append(entry)
            http_recorder["product_entries"] += 1
            if trace(dict(stage="product_http", **entry)):
                http_recorder["durable_enqueued"] += 1
            else:
                http_recorder["durable_enqueue_failed"] += 1

    app.middlewares.append(observe)

    async def state(req):
        p = scanner.projection
        full = req.query.get("full") == "1"
        for attempt in range(8):
            if full:
                await asyncio.wait_for(asyncio.to_thread(trace_queue.join), timeout=5)
            # Same lock order as measured publication; counts/revision/coverage form
            # one coherent test witness rather than a mixture of adjacent states.
            with p.lock:
                with trace_lock:
                    if full and stream["queued_bytes"] != 0:
                        continue
                    observations = (
                        dict(
                            traces=[v for v, _ in traces],
                            samples=list(samples),
                            requests=list(requests),
                        )
                        if full
                        else {}
                    )
                    recorder = dict(
                        trace_entries=len(traces),
                        trace_bytes=trace_bytes,
                        trace_dropped=trace_dropped,
                        trace_bound_bytes=16 * 1024**2,
                        admissions=len(samples),
                        product_http=deepcopy(http_recorder),
                        stream=deepcopy(stream),
                    )
                scopes = (p.frame or {}).get("scopes", [])
                now = instant(clock())
                fresh_pairs = sum(
                    instant(pair["expires_at"]) > now
                    for pair in (p.frame or {}).get("pairs", [])
                )
                coverage = dict(
                    compatible_pairs=len((p.frame or {}).get("pairs", [])),
                    evaluated_pairs=len(p.receipts),
                    original_clock_current_pairs=fresh_pairs,
                    original_clock_earliest_expiry=min(
                        (
                            pair["expires_at"]
                            for pair in (p.frame or {}).get("pairs", [])
                        ),
                        key=instant,
                        default=None,
                    ),
                    scopes_ready=bool(scopes)
                    and all(s["state"] == "ready" for s in scopes),
                    complete=bool(p.frame)
                    and len(p.receipts) == count
                    and fresh_pairs == count
                    and not p.pending
                    and not p.errors
                    and bool(scopes)
                    and all(s["state"] == "ready" for s in scopes)
                    and p.state in ("evaluated_positive", "evaluated_zero"),
                )
                current = dict(
                    frame=None
                    if p.frame is None
                    else dict(
                        instruments=len(p.frame["instruments"]),
                        pairs=len(p.frame["pairs"]),
                        events=len(
                            {i["occurrence_id"] for i in p.frame["instruments"]}
                        ),
                    ),
                    pending=len(p.pending),
                    evaluations=p.evaluations,
                    reuses=p.reuses,
                    errors=list(p.errors),
                    coverage=p.state,
                    global_coverage=coverage,
                    rows=len(p.rows),
                    publication=p.publication,
                    sql_post_commit_observation=deepcopy(p.sql_observation),
                    initial_admission=(
                        None
                        if not samples
                        else {
                            k: deepcopy(v)
                            for k, v in samples[0].items()
                            if k != "source"
                        }
                    ),
                )
            break
        else:
            raise RuntimeError("SC06 durable checkpoint refill retry bound")
        return web.json_response(
            dict(
                clock=clock(),
                server_monotonic=perf_counter(),
                started=started,
                binding=binding,
                **current,
                recorder=recorder,
                **observations,
                provider_requests=len(network_attempts),
                blocked_network_attempts=list(network_attempts),
                **guard(),
            )
        )

    async def update(req):
        receipt = perf_counter()
        value = await req.json()
        index = value.get("index", 0)
        sample = value.get("sample")
        if type(index) is not int or not 0 <= index < count:
            raise web.HTTPBadRequest(text="authored index invalid")
        previous = previous_sources([index])
        changed = material(index)
        result = await asyncio.to_thread(ingest, changed, sample, receipt)
        result["previous_source"] = previous
        return web.json_response(result)

    def previous_sources(indices):
        return [
            dict(
                source=deepcopy(row["quote"]["source"]),
                source_at=row["quote"]["times"]["source_at"],
                price=row["quote"]["original"]["value"],
            )
            for index in indices
            for row in rows[index * 2 : index * 2 + 2]
        ]

    def material(index, *, oscillate=False):
        changed = deepcopy(rows[index * 2 : index * 2 + 2])
        at = clock()
        for leg, r in enumerate(changed):
            q = r["quote"]
            q["times"].update(source_at=at, received_at=at, projected_at=at)
            # Every renewed original is a real material observation: both prices
            # and first depth prices change. Controlled prices improve monotonically;
            # the separately declared finite feed alternates within legal bounds.
            delta = Decimal("0.001") if leg == 0 else Decimal("0.002")
            original = Decimal(q["original"]["value"])
            q["original"]["value"] = str(
                original - delta
                if not oscillate or update_counts[index] % 2 == 0
                else original + delta
            )
            q["depth"][0]["price"] = q["original"]["value"]
            q["original"].update(
                native_value=q["original"]["value"],
                native_units=q["original"]["units"],
                transformation="identity",
            )
        rows[index * 2 : index * 2 + 2] = changed
        update_counts[index] += 1
        return changed

    async def feed(req):
        receipt = perf_counter()
        value = await req.json()
        indices = value.get("indices")
        if (
            not isinstance(indices, list)
            or not 1 <= len(indices) <= 84
            or len(set(indices)) != len(indices)
            or any(type(i) is not int or not 0 <= i < count for i in indices)
        ):
            raise web.HTTPBadRequest(text="authored feed indices invalid")
        previous = previous_sources(indices)
        changed = [row for index in indices for row in material(index, oscillate=True)]
        result = await asyncio.to_thread(ingest, changed, value.get("sample"), receipt)
        result["previous_source"] = previous
        return web.json_response(result)

    async def destinations(req):
        p = scanner.projection
        with p.lock:
            instruments = (p.frame or {}).get("instruments", [])
            # Only the selected first page receives test-owned route evidence.
            row = p.rows.get(req.query.get("row_id", ""))
            keys = (
                {tuple(position["native_key"]) for position in row["positions"]}
                if row
                else set()
            )
            wanted = [i for i in instruments if tuple(i["native_key"]) in keys]
            scanner.tickets.destinations = Destinations(catalog(wanted))
        return web.json_response(dict(instruments=len(wanted)))

    async def clock_read(req):
        return web.json_response(dict(server_monotonic=perf_counter(), clock=clock()))

    async def stop(req):
        provider.dispatch = False
        scanner.projection.stop()
        return web.json_response(dict(stopped=True))

    async def asset(req):
        name = req.match_info["name"]
        if name not in ("scanner.js", "scanner.css", "board-client.js"):
            raise web.HTTPNotFound()
        return web.FileResponse(ASSETS / name)

    async def shell(req):
        return web.Response(
            text=(ASSETS / "scanner.html")
            .read_text()
            .replace(
                "<body>",
                '<body><p style="padding:4px 12px;background:#fff0cc">SC06 authored 500-event workload · disposable SQL · zero provider traffic · source qualification remains open</p>',
            ),
            content_type="text/html",
        )

    async def cleanup(app):
        trace_close()
        trace_queue.put(None)
        await asyncio.to_thread(trace_worker.join, 5)
        adapters.__exit__()
        network_patch.stop()
        policy_patch.stop()
        root_patch.stop()
        sql.SQL.tearDownClass()
        temp.cleanup()

    app.on_cleanup.append(cleanup)
    mount_client(app)
    app.router.add_get("/__test/state", state)
    app.router.add_get("/__test/clock", clock_read)
    app.router.add_post("/__test/update", update)
    app.router.add_post("/__test/destinations", destinations)
    app.router.add_post("/__test/feed", feed)
    app.router.add_post("/api/admin/current", stop)
    app.router.add_get("/current/assets/{name}", asset)
    app.router.add_get("/{tail:.*}", shell)
    return app


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--events", type=int, default=500)
    args = p.parse_args()
    web.run_app(create_app(args.events), host="127.0.0.1", port=args.port, print=None)
