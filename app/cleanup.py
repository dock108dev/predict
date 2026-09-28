"""Close every owned resource, retaining the first failure for the owner."""
import asyncio

from app.diagnostics import failure


async def close_all(resources):
    # Gather observes each failure and lets independent closes finish. Cancellation
    # returned by a resource is a failed close, never a successful acknowledgement.
    results = await asyncio.gather(*(resource.aclose() for resource in resources),
                                   return_exceptions=True)
    errors = [result for result in results if isinstance(result, BaseException)]
    for error in errors:
        failure(__name__, 'owned_resource_close', error)
    if errors:
        raise errors[0]


async def close_outcome(connection, timeout):
    """Return a bounded close result so shielded-task errors cannot log raw details."""
    try:
        await asyncio.wait_for(connection.close(), timeout)
    except (Exception, asyncio.CancelledError) as exc:
        return exc
    return None
