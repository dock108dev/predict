"""App-side database reader/control proxy. Its lifecycle never owns acquisition."""
import asyncio
from app.diagnostics import failure
from copy import deepcopy
import time
from .current_policy import load
from .runtime_status import RuntimeState, COMMAND_SECONDS, HEARTBEAT_SECONDS
from app.dashboard.current_state import unavailable, SelectionError


class _DatabaseStatus:
    def __init__(self, client):
        self.client = client

    def status(self):
        return self.client.status().get('database', dict(state='unavailable', error='data_runtime_unavailable'))


class RuntimeClient:
    allow_synthetic = False
    database_mode = True
    remote_runtime = True

    def __init__(self, *, connector=None):
        self.state = RuntimeState(**({'connector': connector} if connector else {}))
        self._closed = False
        self._fallback = load()
        self.store = None
        self.database = _DatabaseStatus(self)

    def runtime(self):
        try:
            return self.state.read()
        except Exception as exc:
            failure(__name__, 'data_runtime_read', exc)
            return dict(healthy=False, active=False, dispatch=False, runtime_id=None,
                        config=self._fallback, states=unavailable()['source_status'],
                        revision=0, service_state='unavailable', reason_code='data_runtime_unavailable')

    @property
    def config(self):
        return self.runtime()['config'] or deepcopy(self._fallback)

    @property
    def states(self):
        return self.runtime()['states'] or unavailable()['source_status']

    @property
    def dispatch(self):
        return self.runtime()['dispatch']

    @property
    def runtime_id(self):
        return self.runtime()['runtime_id']

    @property
    def digest(self):
        return self.runtime().get('status', {}).get('candidate_digest')

    @property
    def closed(self):
        return self._closed

    @property
    def closing(self):
        return False

    def initial_state(self):
        raw = unavailable()
        current = self.runtime()
        raw['source_status'] = current['states'] or raw['source_status']
        if current['runtime_id']:
            raw['runtime_id'] = current['runtime_id']
        return raw

    async def start(self, store):
        self.store = store

    async def close(self):
        # Closing a page/server only detaches this reader. Explicit Stop uses
        # the acknowledged control path below and belongs to the data runtime.
        self._closed = True

    def status(self):
        current = self.runtime()
        status = deepcopy(current.get('status', {}))
        status.update(runtime_id=current['runtime_id'], config=current['config'] or self._fallback,
                      source_status=current['states'], dispatch_enabled=current['dispatch'])
        health = dict(healthy=current['healthy'], heartbeat_at=current.get('heartbeat_at'),
                      heartbeat_timeout_seconds=HEARTBEAT_SECONDS, revision=current['revision'],
                      owner_pid=current.get('owner_pid'), reason_code=current.get('reason_code'))
        status['data_runtime'] = dict(status.get('data_runtime', {}), **health)
        if not current['healthy']:
            status.update(service_state='unavailable', ownership_held=False,
                          recovery=dict(reason='data_runtime_unavailable', mode='background_runtime_start'),
                          deadline_remaining_seconds=None)
            for panel in status.get('sources', []):
                panel['status'] = {v: current['states'][v] for v in panel['affected_venues'] if v in current['states']}
                panel['comparison_eligible'] = 0
                panel['calculation_eligible'] = {k: 0 for k in panel.get('calculation_eligible', {})}
        return status

    async def _command(self, action, body):
        current = self.runtime()
        try:
            identity = self.state.submit(current['runtime_id'], action, body)
        except Exception as exc:
            failure(__name__, 'data_runtime_submit', exc)
            raise SelectionError(503, 'data_runtime_unavailable',
                                 'Background data runtime did not accept the control. Inspect its status.') from None
        deadline = time.monotonic() + COMMAND_SECONDS + 1
        while time.monotonic() < deadline:
            try:
                result = await asyncio.to_thread(self.state.result, identity)
            except Exception as exc:
                failure(__name__, 'data_runtime_control_result', exc)
                raise SelectionError(503, 'data_runtime_control_unknown',
                    'Control was submitted, but its acknowledgment is unavailable; inspect status before retrying.') from None
            if result and result['state'] != 'pending':
                ack = result['acknowledgment'] or {}
                if result['state'] == 'failed':
                    raise SelectionError(409, ack.get('error', 'data_runtime_control_failed'),
                                         ack.get('reason', 'The owning data runtime rejected this control.'))
                return ack
            await asyncio.sleep(.1)
        raise SelectionError(503, 'data_runtime_control_timeout',
                             'The owning data runtime did not acknowledge this control; inspect status before retrying.')

    async def stop(self):
        return await self._command('stop', {})

    async def pause(self, venue):
        return await self._command('pause', dict(source=venue))

    async def refresh_aggregate(self, sports, identity, reference=False):
        return await self._command('refresh', dict(sports=sports, request_id=identity, reference=reference))

    async def recover(self, runtime, digest):
        return await self._command('recover', dict(runtime_id=runtime, candidate_digest=digest))

    async def recover_accounting(self, runtime, digest, recovery_id, covered_attempts):
        return await self._command('recover_accounting', dict(runtime_id=runtime, candidate_digest=digest,
                                   recovery_id=recovery_id, covered_attempts=covered_attempts))
