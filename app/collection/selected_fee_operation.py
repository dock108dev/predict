"""Explicit once-only HOU-JAC public fee reads inside the existing data owner.

No timer, credentials, account state, model promotion or automatic resumption.
The source's existing allowance funds this smaller finite transport envelope.
"""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import time

from app.comparison.current_dependencies import digest, instant
from .current_policy import ROOT, GRANT, candidate, native_scope, native_markets
from .native_fee_metadata import context
from .native_payload import TRANSPORT_CONTRACT
from .odds_http import BudgetStop
from .prediction_producer import MockREST, PredictionBudget
from .venue_access import ENDPOINTS

SCOPE = 'sc07-hou-jac-fee-acquisition-scope-1'
AUTHORITY = 'owner-sc07-hou-jac-fees-20261017'
OPERATION = 'sc07-hou-jac-fees-20261017'
SERIES = 'KXNFLGAME'
EVENT = 'KXNFLGAME-26OCT18HOUJAC'
MARKET = EVENT + '-JAC'
START = '2026-10-18T13:30:00+00:00'
TERMS = 'b0137b5db2fb2ec32870890ba5b2bbf7926748c59ed83bf51407b62985a5f8bd'
ROUTES = (
    ('/trade-api/v2/series/KXNFLGAME', {}),
    ('/trade-api/v2/series/fee_changes', dict(series_ticker=SERIES, show_historical='true')),
    ('/trade-api/v2/events/fee_changes', dict(event_ticker=EVENT, limit=100, cursor='')),
)
CAP = 256 * 1024
TOTAL = 3 * CAP
REQUEST_SECONDS = 10
DEADLINE_SECONDS = 45
CLEANUP_SECONDS = 5
SPACING_SECONDS = 1
FEE_TYPES = {'quadratic', 'quadratic_with_maker_fees', 'quadratic_with_combo_maker_fees'}


def utc():return datetime.now(timezone.utc).isoformat()


def selected_identity(connector, at):
    """Read the exact existing target; never discover, admit or renew a quote."""
    with connector() as db:
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            rows = db.execute('''SELECT e.native_event_id,e.scheduled_start,e.facts event_facts,
                c.id contract_id,c.facts contract_facts FROM current_event e
                JOIN current_contract c ON c.event_id=e.id
                WHERE e.provider='kalshi' AND e.native_event_id=%s AND c.venue='kalshi'
                  AND c.native_market_id=%s AND c.native_outcome_id='yes' AND c.native_side='yes' ''',
                (EVENT, MARKET)).fetchall()
    if len(rows) != 1:raise ValueError('selected_fee_identity_unavailable')
    row = rows[0]; event = row['event_facts']; facts = row['contract_facts']
    meta = facts.get('comparison_source_metadata', {})
    original = meta.get('combined_native_binding', {}).get('original_terms')
    selection = facts.get('selection', {})
    if (instant(str(row['scheduled_start'])) != instant(START) or instant(START) <= instant(at)
            or event.get('competition') != 'NFL' or event.get('stage') != 'regular_season'
            or event.get('home') != 'NFL:JAX' or event.get('away') != 'NFL:HOU'
            or meta.get('series_id') != SERIES or meta.get('native_key') != ['kalshi', EVENT, MARKET, 'yes', 'yes']
            or selection.get('participant') != 'NFL:JAX' or selection.get('predicate') != 'win'
            or selection.get('signed_line') is not None or digest(original) != TERMS):
        raise ValueError('selected_fee_identity_conflict')
    return dict(native_key=meta['native_key'], scheduled_start=START,
                original_terms_sha256=TERMS, sql_contract_id=row['contract_id'])


def _number(value):
    if isinstance(value, bool) or value is None:raise ValueError('selected_fee_multiplier_invalid')
    n = Decimal(str(value))
    if not n.is_finite() or n < 0:raise ValueError('selected_fee_multiplier_invalid')


def validate_response(index, data):
    """Exact target and bounded complete history; no cursor traversal."""
    if not isinstance(data, dict):raise ValueError('selected_fee_schema_invalid')
    if index == 0:
        row = data.get('series')
        if not isinstance(row, dict) or row.get('ticker') != SERIES:
            raise ValueError('selected_fee_series_identity_conflict')
        if row.get('fee_type') not in FEE_TYPES:raise ValueError('selected_fee_type_unsupported')
        _number(row.get('fee_multiplier'))
        return
    name = 'series_fee_change_arr' if index == 1 else 'event_fee_changes'
    rows = data.get(name)
    if not isinstance(rows, list) or len(rows) > (1000 if index == 1 else 100) or any(not isinstance(r, dict) for r in rows):
        raise ValueError('selected_fee_schema_invalid')
    if index == 2 and data.get('cursor') != '':raise ValueError('selected_fee_history_incomplete')
    seen = set()
    for row in rows:
        if row.get('series_ticker') != SERIES or index == 2 and row.get('event_ticker') != EVENT:
            raise ValueError('selected_fee_history_identity_conflict')
        stamp = instant(row['scheduled_ts'])
        if stamp in seen:raise ValueError('selected_fee_history_ambiguous')
        seen.add(stamp)
        kind = row.get('fee_type' if index == 1 else 'fee_type_override')
        if kind not in FEE_TYPES and (index == 1 or kind is not None):
            raise ValueError('selected_fee_type_unsupported')
        value = row.get('fee_multiplier' if index == 1 else 'fee_multiplier_override')
        if index == 1 or value is not None:_number(value)
        if index == 2 and not {'fee_type_override', 'fee_multiplier_override'} <= row.keys():
            raise ValueError('selected_fee_schema_invalid')


class FeeREST(MockREST):
    """Existing bounded transport, anonymous and charged before each dispatch."""
    def __init__(self, operation):
        limits = dict(discovery_requests=3, session_bytes=TOTAL, frame_bytes=CAP,
            dollars_per_discovery_request='0', dollars_per_connection='0', dollar_cap_per_source='0')
        super().__init__(ENDPOINTS['kalshi']['rest'], limits, operation.receipt,
            REQUEST_SECONDS, PredictionBudget(limits), venue='kalshi', credential=None)
        self.operation = operation
        self.transport_policy = dict(TRANSPORT_CONTRACT, response_wire_bytes=CAP-4096,
            response_entity_bytes=CAP, response_decoded_bytes=CAP,
            discovery_wire_bytes=TOTAL, discovery_decoded_bytes=TOTAL,
            ingress_callback_bytes=4096, parse_expansion_bytes=2*1024*1024)
        self.revised_parse_accounting = True

    async def pace(self):
        op = self.operation
        if op.last_dispatch is not None:
            await asyncio.sleep(max(0, SPACING_SECONDS - (op.timer()-op.last_dispatch)))
        op.guard()
        worker = op.worker; budget = worker.client.budget
        if budget.requests >= worker.config['requests_per_source']:
            raise BudgetStop('selected_fee_source_request_cap')
        if worker.connection_allowance_used() >= worker.config['connections_per_source']:
            raise BudgetStop('selected_fee_source_connection_cap')
        budget.reserve('discovery_request')
        worker.supplemental_connections += 1
        worker.metrics['selected_fee_connections'] = worker.metrics.get('selected_fee_connections', 0) + 1
        worker.metrics['selected_fee_request_reservations'] = worker.metrics.get('selected_fee_request_reservations', 0) + 1
        worker.metrics['requests'] = worker.budget_totals['requests'] + budget.requests
        op.last_dispatch = op.timer()
        op.record['reservations'].append(dict(index=op.index, at=op.clock(),
            source_requests=budget.requests, source_connections_used=worker.connection_allowance_used()))
        op.write()


class SelectedFeeOperation:
    def __init__(self, runtime, *, directory=None, client_factory=FeeREST,
                 identity=None, clock=utc, timer=time.monotonic):
        self.runtime = runtime
        self.directory = Path(directory) if directory is not None else ROOT/'.local/selected-fee-operations'/OPERATION
        self.client_factory = client_factory; self.identity = identity or (
            lambda:selected_identity(runtime.connector, self.clock()))
        self.clock = clock; self.timer = timer
        self.task = self.client = self.worker = None
        self.record = None; self.last_dispatch = None; self.index = None
        self.stop_reason = None; self.started = None
        self.run_entered = False

    def write(self):
        raw = json.dumps(self.record, sort_keys=True, indent=2, allow_nan=False).encode()
        if len(raw) > 64*1024:raise ValueError('selected_fee_receipt_capacity')
        target = self.directory/'result.json'; temp = self.directory/'result.tmp'
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(temp, target)

    def existing(self):
        path = self.directory/'attempt.json'
        if not path.exists():return None
        # A consumed attempt with no terminal receipt is interrupted/unknown,
        # never permission to repeat any of its possibly dispatched requests.
        result = self.directory/'result.json'
        if result.is_file() and not result.is_symlink() and result.stat().st_size <= 64*1024:
            value=json.loads(result.read_text())
            if value.get('state') in {'accepted','running'} and (self.task is None or self.task.done()):
                return dict(operation_id=OPERATION,state='consumed_interrupted_unknown',consumed=True,
                    context=None,cleanup_confirmed=None)
            return value
        return dict(operation_id=OPERATION, state='consumed_result_unknown', consumed=True)

    def guard(self):
        r = self.runtime; service = r.service
        if (self.stop_reason or r.stopping.is_set() or r.global_stopped or service.globally_stopped
                or 'kalshi' in r.paused_sources or self.worker.closed or not service.dispatch):
            raise BudgetStop(self.stop_reason or 'selected_fee_stopped')
        if (service.workers.get('kalshi') is not self.worker or service.config.get('authority') != GRANT
                or 'NFL' not in native_scope(service.config) or 'moneyline' not in native_markets(service.config)
                or self.record is not None and service.runtime_id != self.record['runtime_id']):
            raise BudgetStop('selected_fee_source_owner_conflict')
        if self.started is not None and self.timer()-self.started >= DEADLINE_SECONDS:
            raise BudgetStop('selected_fee_absolute_deadline')
        try:self.worker.guard()
        except asyncio.CancelledError:raise BudgetStop('selected_fee_stopped') from None
        if self.worker.backoff_until > self.timer():raise BudgetStop('provider_backoff_pending')
        r.resource_guard()
        if instant(self.clock()) >= instant(START):raise BudgetStop('selected_fee_pregame_ended')

    async def start(self, body):
        expected = dict(scope=SCOPE, authority=AUTHORITY, runtime_id=self.runtime.service.runtime_id,
                        candidate_digest=self.runtime.service.digest)
        if body != expected or not expected['candidate_digest'] or candidate()[0] != expected['candidate_digest']:
            raise ValueError('selected_fee_command_binding_conflict')
        old = self.existing()
        if old is not None:
            return dict(operation_id=OPERATION, operation_state=old['state'], consumed=True,
                        evidence_directory=str(self.directory))
        self.worker = self.runtime.service.workers.get('kalshi')
        if self.worker is None or self.worker.client is None:raise ValueError('selected_fee_source_unavailable')
        self.guard(); proof = self.identity()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory.is_symlink():raise ValueError('selected_fee_evidence_path_invalid')
        self.record = dict(version=SCOPE, operation_id=OPERATION, consumed=True, state='accepted',
            authority=AUTHORITY, runtime_id=expected['runtime_id'], candidate_digest=expected['candidate_digest'],
            accepted_at=self.clock(), selection=proof, reservations=[], responses=[],
            routes=[dict(path=p, params=q) for p,q in ROUTES], credentials_used=False,
            model_applicability_granted=False, odds_api_credits=0)
        fd = os.open(self.directory/'attempt.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(self.record,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        parent = os.open(self.directory, os.O_RDONLY)
        try:os.fsync(parent)
        finally:os.close(parent)
        self.write(); self.started = self.timer()
        self.task = asyncio.create_task(self.run(), name=OPERATION)
        return dict(operation_id=OPERATION, operation_state='accepted', consumed=True,
                    evidence_directory=str(self.directory))

    def receipt(self, row):
        raw = base64.b64decode(row['body_b64'], validate=True)
        if len(raw) > CAP:raise ValueError('selected_fee_retention_cap')
        path = self.directory/f'response-{self.index+1}.body'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        item = dict(index=self.index, path=row['path'], params=row['params'], status=row['status'],
            started_at=row['started_at'], received_at=row['received_at'],
            complete=row['complete'], usable_metadata=row['usable_metadata'], reason=row.get('delivery_reason'),
            body_path=path.name, body_sha256=sha256(raw).hexdigest(), body_bytes=len(raw),
            wire_bytes=row['resource_usage']['wire_bytes'], decoded_bytes=row['resource_usage']['decoded_bytes'],
            http_plaintext_sha256=row.get('http_plaintext_sha256'),
            request_provenance=row.get('request_provenance'), response_url=row.get('response_url'),
            transport_policy=dict(self.client.transport_policy) if self.client else None,
            wire_accounting='HTTP plaintext; excludes encrypted TLS and TCP/IP',
            response_headers=[pair for pair in row.get('response_headers', [])
                              if pair[0].lower() in {'content-type','content-length','date','retry-after'}])
        self.record['responses'].append(item)
        self.write()
        self.worker.apply_http_backoff(row)
        if (item['wire_bytes'] > CAP or item['decoded_bytes'] > CAP
                or sum(x['wire_bytes'] for x in self.record['responses']) > TOTAL
                or sum(x['decoded_bytes'] for x in self.record['responses']) > TOTAL):
            raise BudgetStop('selected_fee_response_cap')

    async def watch(self):
        while True:
            await asyncio.sleep(.25)
            try:self.guard()
            except (Exception, asyncio.CancelledError) as exc:
                self.stop_reason = str(exc) or 'selected_fee_stopped'
                if self.task and not self.task.done():self.task.cancel()
                return

    async def close_transport(self):
        """Stop cannot cancel the closure that makes its acknowledgment safe."""
        closing=asyncio.create_task(self.client.aclose())
        closing.add_done_callback(lambda task:None if task.cancelled() else task.exception())
        deadline=asyncio.get_running_loop().time()+CLEANUP_SECONDS
        while True:
            try:
                done,pending=await asyncio.wait({closing},timeout=max(0,deadline-asyncio.get_running_loop().time()))
            except asyncio.CancelledError:
                self.stop_reason=self.stop_reason or 'selected_fee_cancelled'
                continue
            if pending:
                closing.cancel()
                raise TimeoutError('selected_fee_cleanup_timeout')
            for task in done:task.result()
            return

    async def run(self):
        self.run_entered = True
        watcher = asyncio.create_task(self.watch())
        reserved = 0; reason = None; values = []
        try:
            async with asyncio.timeout(DEADLINE_SECONDS):
                async with self.worker.http_lock:
                    self.guard(); self.identity()
                    budget = self.worker.client.budget
                    if (budget.requests+3 > self.worker.config['requests_per_source']
                            or self.worker.connection_allowance_used()+3 > self.worker.config['connections_per_source']
                            or budget.remaining_bytes() < TOTAL):
                        raise BudgetStop('selected_fee_source_allowance_insufficient')
                    if any(Decimal(str(budget.limits.get(k, '-1'))) != 0 for k in
                           ('dollars_per_discovery_request','dollars_per_connection','dollar_cap_per_source')):
                        raise BudgetStop('selected_fee_commercial_cost_unestablished')
                    budget.charge_bytes(TOTAL); reserved = TOTAL
                    self.worker.http_active = True
                    self.record.update(state='running', source_byte_reservation=TOTAL,
                        source_budget_window_started_monotonic=self.worker.budget_started)
                    self.write(); self.client = self.client_factory(self)
                    try:
                        for self.index,(path,params) in enumerate(ROUTES):
                            self.guard(); self.identity()
                            if candidate()[0] != self.record['candidate_digest']:
                                raise ValueError('selected_fee_candidate_changed')
                            response = await asyncio.wait_for(self.client.get(
                                ENDPOINTS['kalshi']['rest']+path, deepcopy(params)), REQUEST_SECONDS)
                            self.guard(); self.identity()
                            if response.status_code != 200:raise ValueError('selected_fee_http_'+str(response.status_code))
                            if (len(self.record['responses']) != self.index+1
                                    or not self.record['responses'][-1]['complete']
                                    or not self.record['responses'][-1]['usable_metadata']):
                                raise ValueError('selected_fee_response_incomplete')
                            raw = response.content
                            if len(raw) > CAP:raise ValueError('selected_fee_decoded_cap')
                            data = json.loads(raw.decode('utf-8'), parse_float=Decimal)
                            validate_response(self.index, data); values.append(data)
                        first = self.record['responses'][0]
                        last = self.record['responses'][-1]
                        changes = [*values[1]['series_fee_change_arr'], *values[2]['event_fee_changes']]
                        if any(instant(first['started_at']) <= instant(x['scheduled_ts']) <= instant(last['received_at']) for x in changes):
                            raise ValueError('selected_fee_change_crossed_read_interval')
                        # Current series baseline begins at its own receipt, never
                        # at the later assembly clock or before its observation.
                        bound = context(values[0]['series'], values[1], values[2], SERIES, EVENT, first['received_at'])
                        bound = json.loads(json.dumps(bound,default=str))
                        self.guard(); self.identity()
                        self.record.update(context=bound, baseline_observed_at=first['received_at'],
                            assembled_at=self.clock(), state='complete_evidence_only',
                            governing_document_urls={k:v for k,v in values[0]['series'].items()
                                if k in {'contract_terms_url','contract_url'} and isinstance(v,str)})
                    finally:
                        watcher.cancel()
                        if self.client:
                            await self.close_transport()
                        used = 0 if self.client is None else getattr(self.client,'http_wire_bytes',0)
                        budget.bytes -= reserved-used; reserved = 0
                        self.worker.metrics['bytes'] = self.worker.budget_totals['bytes']+budget.bytes
                        self.worker.http_active = False
                    self.guard(); self.identity()
                    if candidate()[0] != self.record['candidate_digest']:
                        raise ValueError('selected_fee_candidate_changed')
        except asyncio.CancelledError:
            reason = self.stop_reason or 'selected_fee_cancelled'
        except TimeoutError:
            reason = 'selected_fee_timeout'
        except Exception as exc:
            code = str(exc)
            reason = code if code.replace('_','').isalnum() and len(code)<160 else 'selected_fee_'+type(exc).__name__
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            if reserved:
                # A failed/unfinished cleanup keeps its full reservation and
                # prevents further acquisition; no optimistic budget release.
                self.worker.failed = True
                self.runtime.service.cleanup_errors.append('selected_fee_cleanup_unresolved')
                reason = 'selected_fee_cleanup_unresolved'
            if reason or self.stop_reason:
                self.record.update(state='stopped' if self.stop_reason else 'unbound',
                    reason=self.stop_reason or reason, context=None)
            self.record.update(finished_at=self.clock(), elapsed_seconds=self.timer()-self.started,
                requests_reserved=len(self.record['reservations']),
                observed_wire_bytes=sum(x['wire_bytes'] for x in self.record['responses']),
                observed_decoded_bytes=sum(x['decoded_bytes'] for x in self.record['responses']),
                cleanup_confirmed=not bool(reserved))
            try:self.write()
            except ValueError as exc:
                if str(exc)!='selected_fee_receipt_capacity':raise
                # Complete raw responses survive even when their optional
                # derived context cannot fit this small terminal receipt.
                self.record.update(state='unbound',reason='selected_fee_receipt_capacity',context=None)
                self.record.pop('governing_document_urls',None)
                self.write()

    async def stop(self, reason='selected_fee_stopped'):
        if self.task is None:return True
        if self.task.done():return bool(self.record.get('cleanup_confirmed'))
        self.stop_reason = reason; self.task.cancel()
        done,pending = await asyncio.wait({self.task}, timeout=CLEANUP_SECONDS)
        if pending:
            self.worker.failed = True
            self.runtime.service.cleanup_errors.append('selected_fee_cleanup_unresolved')
            return False
        for task in done:
            if not task.cancelled():task.result()
        if not self.run_entered:
            self.record.update(state='stopped', reason=reason, context=None,
                finished_at=self.clock(), elapsed_seconds=self.timer()-self.started,
                requests_reserved=0, observed_wire_bytes=0, observed_decoded_bytes=0,
                cleanup_confirmed=True)
            self.write()
        return bool(self.record.get('cleanup_confirmed'))
