"""Protect explicit retained HTTPX tools with the same owner and quota.

An injected offline transport remains an offline test seam. Real network tools
cannot bypass operational accounting through historical finite budgets.
"""
from functools import wraps
from contextvars import ContextVar
from uuid import uuid4
from urllib.parse import urlsplit
from .local_ownership import LocalOwnership
from .current_quota import QuotaLedger, load_window
from .current_policy import candidate

_CONTEXT=ContextVar('predict_shared_odds',default=None)


def shared_capture(function):
    @wraps(function)
    async def guarded(*args,**kwargs):
        if kwargs.get('transport') is not None:
            return await function(*args,**kwargs)
        ownership=LocalOwnership();ownership.acquire('retained-odds-'+str(uuid4()))
        token=_CONTEXT.set(ownership)
        try:
            return await function(*args,**kwargs)
        finally:
            _CONTEXT.reset(token);ownership.release()
    return guarded


def before_request(endpoint,params,cost,client):
    import httpx
    if isinstance(getattr(client,'_transport',None),httpx.MockTransport):return None
    owner=_CONTEXT.get()
    if owner is None:raise ValueError('Shared acquisition ownership required for real retained request')
    q=QuotaLedger();q.bind_window(load_window())
    request=dict(path=urlsplit(endpoint).path,params=params)
    bootstrap=request['path'].rstrip('/')=='/v4/sports'
    attempt=q.reserve(owner,candidate()[0],request,cost,bootstrap=bootstrap)
    q.dispatched(attempt,owner)
    return q,attempt


def reconcile(reservation,items):
    if reservation:
        q,attempt=reservation;q.reconcile(attempt,items)
        if q.snapshot()['pause']:raise ValueError('Shared provider quota reconciliation paused')
