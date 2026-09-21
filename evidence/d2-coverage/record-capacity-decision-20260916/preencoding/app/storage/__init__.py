"""Finite historical capture. Synchronous commits provide backpressure, no queue."""
from .store import Store, CapturePolicy, connect
