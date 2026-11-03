"""Cooperative CPU yielding without suspending a SQL transaction or its locks."""
import signal
import time
from psycopg.pq import TransactionStatus


class WorkerPause:
    def __init__(self):
        self.requested = False

    def install(self):
        signal.signal(signal.SIGUSR1, lambda *_: self.set(True))
        signal.signal(signal.SIGUSR2, lambda *_: self.set(False))

    def set(self, value):
        self.requested = value

    def checkpoint(self, db, guard):
        # Finish short SQL sections before yielding. In particular, never hold
        # the ingress transaction lock while waiting for ingress to catch up.
        while self.requested and (db is None or db.info.transaction_status == TransactionStatus.IDLE):
            if guard(): return True
            time.sleep(.05)
        return guard()
