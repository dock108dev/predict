"""Bounded ordinary replacement turn in the existing auxiliary process lane."""
import json
import os
from pathlib import Path
import sys
import time


def main():
    from app.storage import store
    from .coverage_worker import MAX_SECONDS, MAX_PROCESS_BYTES
    from .continuous import rss
    from app.comparison.calculation_control import cancellation
    from app.storage.ordinary_publication import turn
    store.ROOT = Path(sys.argv[1])
    parent = int(sys.argv[2])
    start = time.monotonic()
    if hasattr(os,'nice'):os.nice(10)
    from .worker_pause import WorkerPause
    pause=WorkerPause();db=None
    if '--cooperative-pause' in sys.argv[3:]:
        pause.install()
        print(json.dumps(dict(worker_ready='cooperative_pause')),flush=True)

    def stopped():
        if os.getppid() != parent: return True
        if time.monotonic()-start > MAX_SECONDS: raise ValueError('ordinary_worker_deadline')
        if rss() >= MAX_PROCESS_BYTES: raise ValueError('ordinary_worker_memory_capacity')
        return False

    try:
        with cancellation(lambda:pause.checkpoint(db,stopped)), store.connect() as db:
            result = turn(db,capture_cache=store.ROOT/'.local/ordinary-capture-structure.json')
        result.update(worker_seconds=round(time.monotonic()-start,3), worker_peak_rss_bytes=rss())
    except Exception as exc:
        from app.diagnostics import failure_details
        result = dict(worker_error='ordinary_publication_failed', worker_failure=failure_details(exc), provider_requests=0)
    print(json.dumps(result), flush=True)


if __name__ == '__main__': main()
