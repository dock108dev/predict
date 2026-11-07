"""Native close diagnostics preserve causes without retaining remote text."""
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close
from app.collection.current_transport_diagnostics import websocket_close_kind


def test_local_keepalive_timeout_is_distinguished_from_remote_and_abrupt_close():
    timeout=ConnectionClosedError(None,Close(1011,'keepalive ping timeout'))
    timeout.__cause__=TimeoutError('private provider detail')
    assert websocket_close_kind(timeout)==dict(kind='keepalive_timeout',cause=dict(category='timeout',type='TimeoutError'))
    remote=ConnectionClosedError(Close(1011,'private provider detail'),None)
    assert websocket_close_kind(remote)==dict(kind='remote_close',cause=None)
    abrupt=ConnectionClosedError(None,None)
    abrupt.__cause__=OSError('private socket detail')
    assert websocket_close_kind(abrupt)==dict(kind='transport_lost',cause=dict(category='os',type='OSError'))
    assert websocket_close_kind(ValueError('private detail')) is None
