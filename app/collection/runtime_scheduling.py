"""Bounded CPU turns for the data process's socket and storage threads."""
from contextlib import contextmanager
import sys


@contextmanager
def collection_scheduling():
    # Native sampling showed socket reads waiting to reacquire the GIL while
    # metadata/SQL threads ran. The default five-ms turn compounds across the
    # many short I/O calls. Shorter turns preserve all work and ordering while
    # allowing the socket loop and process-result readers to make progress.
    previous=sys.getswitchinterval()
    sys.setswitchinterval(min(previous,.001))
    try:
        yield
    finally:
        sys.setswitchinterval(previous)
