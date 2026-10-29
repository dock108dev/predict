"""One projection's verified accounting reads; never used by ledger mutations."""
from contextlib import contextmanager
from contextvars import ContextVar

_reads = ContextVar('quota_status_reads', default=None)


def signature(ledger):
    paths=(ledger.directory/'quota.json', ledger.directory/'initialized')
    result=[]
    for path in paths:
        try:
            s=path.lstat()
            result.append((s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns))
        except FileNotFoundError:
            result.append(None)
    return tuple(result)


def read(ledger):
    cache=_reads.get()
    if cache is None:
        return ledger._read()
    key=str(ledger.directory.absolute())
    before=signature(ledger)
    entry=cache.get(key)
    if entry is not None and entry[0]==before:
        return entry[1]
    value=ledger._read()
    # Never label a read with the identity of a replacement file.
    if signature(ledger)==before:
        cache[key]=(before,value)
    else:
        cache.pop(key,None)
    return value


@contextmanager
def projection(cache=None):
    existing=_reads.get()
    token=_reads.set(existing if existing is not None else {} if cache is None else cache)
    try:
        yield _reads.get()
    finally:
        _reads.reset(token)


def prepare(ledgers):
    with projection({}) as cache:
        for ledger in ledgers:
            try:
                read(ledger)
            except (OSError,ValueError):
                # The normal status path renders failures; do not retain them.
                pass
        return cache


def account_projection(directory, failed, retained_directory, evidence):
    """Read-only child projection. No lock authority, transport or ledger writes."""
    from .current_quota import QuotaLedger
    from .current_conservative import pending_reason
    with projection():
        ledger=QuotaLedger(directory) if directory is not None else None
        if ledger is not None:ledger.failed=failed
        quota=ledger.snapshot() if ledger is not None else None
        pending=None
        if retained_directory is not None:
            try:pending=pending_reason(read(QuotaLedger(retained_directory)))
            except (ValueError,OSError):pending='quota_ledger_unavailable'
        try:reason=ledger.recovery_reason(evidence) if ledger is not None else None
        except (ValueError,OSError):reason='reset_window_evidence_unverified'
        return dict(quota=quota,pending=pending,ledger_reason=reason)


class AccountProjection:
    """One joined status job; the parent receives only compact display facts."""
    def __init__(self):
        from concurrent.futures import ProcessPoolExecutor
        from multiprocessing import get_context
        self.pool=ProcessPoolExecutor(max_workers=1,mp_context=get_context('spawn'))

    async def read(self,*args):
        import asyncio
        future=asyncio.wrap_future(self.pool.submit(account_projection,*args))
        try:return await asyncio.shield(future)
        except asyncio.CancelledError:
            await asyncio.gather(future,return_exceptions=True)
            raise

    async def close(self):
        from .bulk_checkpoint import owned_thread
        await owned_thread(self.pool.shutdown,wait=True,cancel_futures=True)
