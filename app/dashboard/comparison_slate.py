"""Bounded database pages of background-owned compact ordinary results."""
from app.storage.latest_board import slate
from app.storage.store import encoded

VERSION='predict-comparison-slate-2'
MAX_GAMES=500
MAX_PAGE_GAMES=50
MAX_BYTES=8*1024*1024


def read(*args,**kwargs):
    output,pending=slate(*args,**kwargs)
    if len(encoded(output))>MAX_BYTES:raise ValueError('slate_response_byte_capacity')
    return output,pending
