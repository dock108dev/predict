"""Thread completion ownership shared by collection and dashboard callers."""
import asyncio

from app.diagnostics import failure


async def joined_thread(logger, operation, fn, /, *args, **kwargs):
    """Join actual completion before propagating cancellation or releasing a slot.

    Diagnostic names belong to the caller; cancellation/error precedence lives
    here. This does not impose a deadline or undo a completed write.
    """
    def outcome():
        # A shielded task must not raise provider/storage exceptions: Python
        # can log their raw messages after its original waiter is cancelled.
        try:
            return fn(*args, **kwargs), None
        except BaseException as exc:
            return None, exc

    task = asyncio.create_task(asyncio.to_thread(outcome))
    cancelled = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancelled = cancelled or exc
    value, error = task.result()
    if cancelled is not None:
        if error is not None:
            failure(logger, operation, error)
        raise cancelled
    if error is not None:
        raise error
    return value
