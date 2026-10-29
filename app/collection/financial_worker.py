"""Disposable normal financial worker, sharing Coverage's bounded process lane."""
import json
import os
from pathlib import Path
import sys
import time
from psycopg.errors import LockNotAvailable,SerializationFailure,DeadlockDetected
from .coverage_worker import MAX_PROCESS_BYTES,MAX_SECONDS


def main():
    from app.storage import store
    store.ROOT=Path(sys.argv[1]);parent=int(sys.argv[2]);admission=json.loads(sys.argv[3])
    start=time.monotonic()
    from app.collection.continuous import rss
    from app.collection.background_work import BACKGROUND
    from app.comparison.calculation_control import cancellation
    from app.storage.latest_board import reconcile,LOCK
    BACKGROUND.limit=MAX_PROCESS_BYTES;BACKGROUND.runway=0
    def guard():
        if os.getppid()!=parent:return True
        if time.monotonic()-start>MAX_SECONDS:raise ValueError('financial_worker_deadline')
        if rss()>=MAX_PROCESS_BYTES:raise ValueError('financial_worker_memory_capacity')
        return False
    try:
        progress_count=0
        def progress(value):
            nonlocal progress_count
            # A bounded control message, never a financial payload. Completed
            # components survive parent pressure cancellation of this child.
            if progress_count<64:
                print(json.dumps(dict(worker_progress={k:v for k,v in value.items()
                    if k in ('estimates_cursor','estimates_after')})),flush=True)
                progress_count+=1
        with cancellation(guard),store.connect() as db:
            if not db.execute('SELECT pg_try_advisory_lock(%s) owned',(LOCK,)).fetchone()['owned']:
                result=dict(published=False,reason='another_board_owner')
            else:
                try:result=reconcile(db,admission=admission,turn_seconds=60,progress=progress)
                finally:db.execute('SELECT pg_advisory_unlock(%s)',(LOCK,))
        result.update(worker_pid=os.getpid(),worker_peak_rss_bytes=rss(),worker_maximum_bytes=MAX_PROCESS_BYTES,
            worker_seconds=time.monotonic()-start,provider_requests=0,
            worker_admission={k:v for k,v in admission.items() if k.startswith('estimates')})
    except LockNotAvailable:
        result=dict(published=False,deferred=True,reason='financial_publication_busy',errors=[],provider_requests=0,
            worker_admission={k:v for k,v in admission.items() if k.startswith('estimates')})
    except (SerializationFailure,DeadlockDetected):
        result=dict(published=False,deferred=True,reason='financial_publication_retry',errors=[],provider_requests=0,
            worker_admission={k:v for k,v in admission.items() if k.startswith('estimates')})
    except Exception as exc:
        from app.diagnostics import failure_details
        result=dict(worker_error='financial_worker_failed',worker_failure=failure_details(exc),provider_requests=0)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
