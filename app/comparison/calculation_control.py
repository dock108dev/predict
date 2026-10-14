"""Cooperative cancellation of a local calculation; no source or clock changes."""
from contextlib import contextmanager
from contextvars import ContextVar

_cancelled = ContextVar('predict_calculation_cancelled', default=None)

class CalculationStopped(Exception):
    pass

def checkpoint():
    cancelled = _cancelled.get()
    if cancelled is not None and cancelled():
        raise CalculationStopped('saved_calculation_stopped')

@contextmanager
def cancellation(cancelled):
    token = _cancelled.set(cancelled)
    try:
        checkpoint()
        yield
    finally:
        _cancelled.reset(token)
