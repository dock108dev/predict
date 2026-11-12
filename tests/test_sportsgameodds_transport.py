import asyncio


def test_cursor_error_classification_is_narrow():
    from app.collection.sportsgameodds_transport import _invalid_cursor
    assert _invalid_cursor(b'{"success":false,"error":"Invalid cursor"}')
    assert _invalid_cursor(b'{"success":false,"error":"Cursor expired"}')
    assert not _invalid_cursor(b'{"success":false,"error":"Invalid league"}')
    assert not _invalid_cursor(b'{"success":true,"error":"Invalid cursor"}')
    assert not _invalid_cursor(b'not json')

import pytest

from app.collection.sportsgameodds_transport import SportsgameoddsTransport, TransportFailure, validate_params

PARAMS = {'leagueID': 'NBA,NHL', 'oddID': 'points-home-game-ml-home', 'limit': 5}


class Content:
    def __init__(self, body):
        self.body = body

    async def iter_chunked(self, _size):
        yield self.body


class Response:
    def __init__(self, status=200, body=b'{}', headers=None):
        self.status = status
        self.headers = headers or {}
        self.content = Content(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_filters_are_scoped_and_bounded():
    assert validate_params(PARAMS) == PARAMS
    for change in ({'limit': 101}, {'leagueID': 'NBA,SOCCER'}, {'oddID': 'player-prop'}, {'apiKey': 'secret'}, {'eventIDs': 'id'}, {'cursor': '\n'}):
        with pytest.raises(ValueError):
            validate_params({**PARAMS, **change})


def test_transport_limits_and_no_retries_or_error_body():
    asyncio.run(_transport_limits_and_no_retries_or_error_body())


async def _transport_limits_and_no_retries_or_error_body():
    session = Session(Response(429, b'error with private details', {'Retry-After': '30'}))
    transport = SportsgameoddsTransport(session=session)
    result = await transport.fetch({**PARAMS, 'includeAltLines': False}, 'secret')
    assert result.status == 429 and result.body == b'' and result.retry_after_seconds == 30
    assert len(session.calls) == 1
    assert session.calls[0][1]['headers']['x-api-key'] == 'secret'
    assert session.calls[0][1]['params']['includeAltLines'] == 'false'
    assert session.calls[0][1]['allow_redirects'] is False


def test_response_bound_and_secret_echo_are_suppressed():
    asyncio.run(_response_bound_and_secret_echo_are_suppressed())


async def _response_bound_and_secret_echo_are_suppressed():
    transport = SportsgameoddsTransport(session=Session(Response(body=b'0123456789')), response_bytes=5)
    with pytest.raises(TransportFailure, match='size'):
        await transport.fetch(PARAMS, 'secret')
    transport = SportsgameoddsTransport(session=Session(Response(body=b'secret')))
    with pytest.raises(TransportFailure, match='suppressed'):
        await transport.fetch(PARAMS, 'secret')
