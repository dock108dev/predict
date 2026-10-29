"""Owned CPU isolation for strict ledger transactions; never performs transport.

The child receives a duplicate of the already-held acquisition lock descriptor.
It cannot create/acquire replacement authority. Stop joins outstanding work and
closes the process before the parent releases that ownership. Every transaction
still reloads, validates, locks, fsyncs and replaces the same ledger file.
"""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from multiprocessing.reduction import DupFd
import os
from types import SimpleNamespace
from .bulk_checkpoint import owned_thread
from .current_quota import QuotaLedger, QuotaStop

_LEDGER = None
_OWNER = None


def initialize(directory, descriptor, authority_path):
    global _LEDGER, _OWNER
    from pathlib import Path
    from . import alternate_acquisition
    alternate_acquisition.AUTHORITY_PATH = Path(authority_path)
    _LEDGER = QuotaLedger(directory)
    _OWNER = SimpleNamespace(file=os.fdopen(descriptor.detach(), 'r'))


def invoke(method, args, kwargs):
    if method == 'snapshot':
        return _LEDGER.snapshot()
    if method in ('reserve', 'prepare_clock', 'dispatched', 'cancel_before_transport'):
        if method in ('reserve','prepare_clock'):
            return getattr(_LEDGER,method)(_OWNER, *args, **kwargs)
        return getattr(_LEDGER, method)(*args, _OWNER, **kwargs)
    if method == 'check_binding':
        from .current_aggregate import check_account_binding
        from .current_quota import load_window
        return check_account_binding(_LEDGER, load_window)
    if method == 'account_response':
        aid, receipt = args
        _LEDGER.reconcile(aid, receipt['headers'], received_at=receipt['received_at'])
        _LEDGER.record_response(aid, receipt)
        return _LEDGER._read()['attempts'][aid].get('charged'), _LEDGER.snapshot()
    raise ValueError('Unsupported accounting worker operation')


class AccountingProcess:
    def __init__(self, ledger, owner):
        if owner.file is None:
            raise QuotaStop('acquisition_ownership_required')
        self.ledger = ledger
        from .alternate_acquisition import AUTHORITY_PATH
        self.pool = ProcessPoolExecutor(max_workers=1, mp_context=get_context('spawn'),
            initializer=initialize, initargs=(str(ledger.directory), DupFd(owner.file.fileno()), str(AUTHORITY_PATH)))
        self.closed = False

    async def call(self, method, *args, result=None, **kwargs):
        if self.closed:
            raise QuotaStop('aggregate_dispatch_revoked')
        future = asyncio.wrap_future(self.pool.submit(invoke, method, args, kwargs))
        cancelled = None
        while True:
            try:
                value = await asyncio.shield(future)
                if result is not None:
                    result['id'] = value
                break
            except asyncio.CancelledError as exc:
                if future.cancelled():raise
                cancelled = cancelled or exc
                # Repeated cancellation cannot detach a ledger mutation.
                continue
            except BaseException as exc:
                if isinstance(exc, QuotaStop) and str(exc) == 'quota_persistence_failed':
                    self.ledger.failed = str(exc)
                if cancelled:
                    raise cancelled from exc
                raise
        if cancelled:
            raise cancelled
        return value

    async def close(self):
        self.closed = True
        await owned_thread(self.pool.shutdown, wait=True, cancel_futures=False)
