"""Bounded native HTTP framing, plaintext accounting and provenance redaction.

This layer knows only the HTTP protocol and its owner's wire state. Collection
budgets, payload admission and stream orchestration remain with the producer.
"""

import asyncio
import inspect
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp

from .odds_http import BudgetStop


_SECRET_NAME = re.compile(
    r"key|secret|token|signature|authorization|cookie|password", re.I
)
_RESPONSE_HEADERS = {
    "content-type",
    "content-length",
    "content-encoding",
    "transfer-encoding",
    "date",
    "server",
    "retry-after",
    "via",
    "location",
    "connection",
    "cf-cache-status",
    "x-request-id",
    "request-id",
    "cf-ray",
}


def _safe_url(value):
    """URLs are provenance, not an alternate credential persistence channel."""
    parts = urlsplit(str(value))
    host = parts.hostname or ""
    if ":" in host:
        host = "[" + host + "]"
    if parts.port:
        host += ":" + str(parts.port)
    values = parse_qsl(parts.query, keep_blank_values=True)
    query = (
        urlencode(
            [(k, "<redacted>" if _SECRET_NAME.search(k) else v) for k, v in values]
        )
        if any(_SECRET_NAME.search(k) for k, _ in values)
        else parts.query
    )
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def _safe_headers(headers, *, response=False):
    result = []
    for key, value in headers.items():
        lower = key.lower()
        if _SECRET_NAME.search(lower):
            # Names demonstrate signing without persisting secret values.
            if not response:
                result.append([key, "<redacted>"])
        elif not response or lower in _RESPONSE_HEADERS:
            result.append([key, _safe_url(value) if lower == "location" else value])
    return result


def _safe_params(query):
    if isinstance(query, str):
        values = parse_qsl(query, keep_blank_values=True)
        if not any(_SECRET_NAME.search(k) for k, _ in values):
            return query
        return urlencode(
            [(k, "<redacted>" if _SECRET_NAME.search(k) else v) for k, v in values]
        )
    if hasattr(query, "items"):
        return {
            k: "<redacted>" if _SECRET_NAME.search(str(k)) else v
            for k, v in query.items()
        }
    return [[k, "<redacted>" if _SECRET_NAME.search(str(k)) else v] for k, v in query]


def _transport_capability(callback_bytes):
    """The verified private aiohttp hook must fail closed after incompatible drift."""
    from aiohttp.client_proto import ResponseHandler
    from asyncio.selector_events import _SelectorSocketTransport
    from asyncio.sslproto import SSLProtocol

    if (
        not aiohttp.__version__.startswith("3.14.")
        or "max_headers" not in inspect.signature(aiohttp.ClientSession).parameters
        or not callable(getattr(ResponseHandler, "data_received", None))
        or not callable(
            getattr(_SelectorSocketTransport, "_read_ready__get_buffer", None)
        )
        or not callable(getattr(SSLProtocol, "_do_read__buffered", None))
        or type(callback_bytes) is not int
        or not 0 < callback_bytes <= 256 * 1024
    ):
        raise BudgetStop("native_http_transport_capability_unverified")


class _HTTPFraming:
    """Bounded HTTP/1 response scanner, independent of JSON and aiohttp EOF.

    aiohttp may ignore bytes after an already completed Content-Length body.
    This scanner accounts for the entire observed plaintext message, including
    chunk extensions/trailers, and rejects any surplus. It stores at most 64
    bounded header lines and one bounded framing line, never a body copy.
    """

    def __init__(self):
        self.phase = "headers"
        self.line = bytearray()
        self.headers = []
        self.header_bytes = self.trailer_count = self.entity_bytes = 0
        self.status = None
        self.remaining = 0

    def _header_line(self, line):
        if self.status is None:
            match = re.match(rb"^HTTP/1\.[01] ([0-9]{3})(?: |$)", line)
            if match is None:
                raise BudgetStop("native_http_framing_error")
            self.status = int(match.group(1))
            if self.status < 200:
                raise BudgetStop("native_http_informational_refused")
        elif line:
            if len(self.headers) >= 64 or b":" not in line:
                raise BudgetStop("native_http_framing_error")
            key, value = line.split(b":", 1)
            if not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key):
                raise BudgetStop("native_http_framing_error")
            self.headers.append((key.lower(), value.strip()))
        else:
            lengths = [v for k, v in self.headers if k == b"content-length"]
            transfers = [
                v.lower() for k, v in self.headers if k == b"transfer-encoding"
            ]
            if (
                len(lengths) > 1
                or len(transfers) > 1
                or (lengths and transfers)
                or lengths
                and not re.fullmatch(rb"[0-9]{1,20}", lengths[0])
            ):
                raise BudgetStop("native_http_framing_error")
            if self.status in (204, 304):
                self.phase = "done"
            elif transfers:
                if transfers != [b"chunked"]:
                    raise BudgetStop("native_unsupported_transfer_encoding")
                self.phase = "chunk_size"
            elif lengths:
                self.remaining = int(lengths[0])
                self.phase = "fixed" if self.remaining else "done"
            else:
                self.phase = "close"
            self.headers.clear()

    def feed(self, data):
        position = 0
        while position < len(data):
            if self.phase == "done":
                raise BudgetStop("native_http_surplus_bytes")
            if self.phase == "close":
                self.entity_bytes += len(data) - position
                return
            if self.phase in ("fixed", "chunk_data"):
                take = min(self.remaining, len(data) - position)
                self.entity_bytes += take
                self.remaining -= take
                position += take
                if self.remaining == 0:
                    self.phase = "done" if self.phase == "fixed" else "chunk_crlf"
                continue
            if self.phase == "chunk_crlf":
                take = min(2 - len(self.line), len(data) - position)
                self.line.extend(data[position : position + take])
                position += take
                if len(self.line) == 2:
                    if self.line != b"\r\n":
                        raise BudgetStop("native_http_framing_error")
                    self.line.clear()
                    self.phase = "chunk_size"
                continue
            end = data.find(b"\n", position)
            stop = len(data) if end == -1 else end + 1
            if len(self.line) + stop - position > 8190:
                raise BudgetStop("native_http_framing_error")
            self.line.extend(data[position:stop])
            if self.phase == "headers":
                self.header_bytes += stop - position
            position = stop
            if end == -1:
                return
            if not self.line.endswith(b"\r\n"):
                raise BudgetStop("native_http_framing_error")
            line = bytes(self.line[:-2])
            self.line.clear()
            if self.phase == "headers":
                self._header_line(line)
            elif self.phase == "chunk_size":
                size = line.split(b";", 1)[0]
                if not re.fullmatch(rb"[0-9A-Fa-f]{1,16}", size):
                    raise BudgetStop("native_http_framing_error")
                self.remaining = int(size, 16)
                self.phase = "chunk_data" if self.remaining else "trailers"
            elif self.phase == "trailers":
                if not line:
                    self.phase = "done"
                else:
                    self.trailer_count += 1
                    if self.trailer_count > 64 or b":" not in line:
                        raise BudgetStop("native_http_framing_error")
                    key = line.split(b":", 1)[0]
                    if not re.fullmatch(
                        rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key
                    ) or key.lower() in (b"content-length", b"transfer-encoding"):
                        raise BudgetStop("native_http_framing_error")

    def eof(self):
        if self.phase == "close":
            self.phase = "done"
        if self.phase != "done":
            raise BudgetStop(
                "native_http_length_mismatch"
                if self.phase == "fixed"
                else "native_http_framing_error"
            )


class _StrictCloseResponse(aiohttp.ClientResponse):
    def _response_eof(self):
        # Content EOF is not permission to silently drop later TCP callbacks.
        # The v2 reader awaits actual peer close before context-manager release.
        self._native_payload_eof = True


def _bounded_connector(owner, callback_bytes):
    """Count HTTP plaintext before aiohttp strips framing or buffers the entity.

    An admitted response fits the wire cap. The violating callback is counted,
    charged and rejected before parsing, with a separate finite read-ahead bound.
    This does not claim to count encrypted TLS records or IP/TCP traffic.
    """
    from aiohttp.client_proto import ResponseHandler

    _transport_capability(callback_bytes)

    class CountedResponse(ResponseHandler, asyncio.BufferedProtocol):
        def __init__(self, *, loop, state):
            super().__init__(loop)
            self.wire_state = state
            # BufferedProtocol also directs TLS decryption into this fixed
            # buffer; SSLProtocol's copied path can otherwise join many reads.
            self.ingress_buffer = bytearray(callback_bytes)

        def get_buffer(self, sizehint):
            return memoryview(self.ingress_buffer)

        def buffer_updated(self, nbytes):
            if type(nbytes) is not int or not 0 <= nbytes <= len(self.ingress_buffer):
                self._reject("native_http_transport_capability_unverified")
                return
            self.data_received(bytes(memoryview(self.ingress_buffer)[:nbytes]))

        def connection_made(self, transport):
            super().connection_made(transport)
            ssl_protocol = getattr(transport, "_ssl_protocol", None)
            if ssl_protocol is not None:
                supported = (
                    getattr(ssl_protocol, "_app_protocol_is_buffer", False) is True
                    and getattr(ssl_protocol, "_app_protocol", None) is self
                )
                mode = "TLS BufferedProtocol"
            else:
                from asyncio.selector_events import _SelectorSocketTransport

                supported = (
                    getattr(
                        getattr(transport, "_read_ready_cb", None), "__func__", None
                    )
                    is _SelectorSocketTransport._read_ready__get_buffer
                )
                mode = "TCP BufferedProtocol"
            self.wire_state["read_mode"] = mode
            if not supported:
                self._reject("native_http_transport_capability_unverified")

        def _reject(self, reason):
            self.wire_state["reason"] = reason
            exc = BudgetStop(reason)
            if self._payload is not None:
                self._payload.set_exception(exc)
            self.set_exception(exc)
            if self.transport is not None:
                self.transport.abort()

        def connection_lost(self, exc):
            state = self.wire_state
            if state["reason"] is None:
                try:
                    state["framing"].eof()
                except BudgetStop as error:
                    state["reason"] = str(error)
            if exc is not None and state["reason"] is None:
                state["reason"] = "native_http_transport_error"
            try:
                super().connection_lost(exc)
            finally:
                if not state["closed"].done():
                    state["closed"].set_result(True)

        def data_received(self, data):
            # aiohttp can recursively feed an already received upgrade tail.
            # It is plaintext from the same callback, not another arrival.
            if getattr(self, "_processing_wire", False):
                super().data_received(data)
                return
            state = self.wire_state
            state["received"] += len(data)
            state["sha256"].update(data)
            state["max_callback"] = max(state["max_callback"], len(data))
            if state["reason"] is not None:
                return
            if len(data) > callback_bytes:
                self._reject("native_http_ingress_callback_cap")
                return
            if state["received"] > state["cap"]:
                self._reject(state["cap_reason"])
                return
            try:
                state["framing"].feed(data)
            except BudgetStop as exc:
                self._reject(str(exc))
                return
            state["admitted"] += len(data)
            self._processing_wire = True
            try:
                super().data_received(data)
            finally:
                self._processing_wire = False

    connector = aiohttp.TCPConnector(limit=1, limit_per_host=1, force_close=True)
    if not hasattr(connector, "_factory"):
        raise BudgetStop("native_http_transport_capability_unverified")
    connector._factory = lambda: CountedResponse(
        loop=connector._loop, state=owner._wire_state
    )
    return connector
