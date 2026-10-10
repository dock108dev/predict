"""Independent transport oracles; no public requests in the offline suite."""
from email.message import Message
import gzip
import io
import json
import tempfile
import time
from pathlib import Path
import unittest

from app.comparison.event_evidence import exact_path, read_response


class Response:
    def __init__(self, body, *, status=200, encoding='identity', length=None, closed=True):
        self.body = io.BytesIO(body)
        self.status = status
        self.closed = closed
        self.headers = Message()
        self.headers['Content-Type'] = 'application/json'
        self.headers['Content-Encoding'] = encoding
        if length is not None:
            self.headers['Content-Length'] = str(length)

    def read(self, count):
        return self.body.read(count)

    def isclosed(self):
        return self.closed and self.body.tell() == len(self.body.getvalue())


class EventEvidenceTransport(unittest.TestCase):
    def read(self, body=b'{"events":[]}', **kwargs):
        options = {k: kwargs.pop(k) for k in ('limit', 'deadline') if k in kwargs}
        with tempfile.TemporaryDirectory() as directory:
            record, graph = read_response(Response(body, **kwargs), directory, **options)
            record['retained_sizes'] = {p.name: p.stat().st_size for p in Path(directory).iterdir()}
            return record, graph

    def test_exact_exploded_filter(self):
        self.assertEqual(exact_path(), '/v1/events?id=129629&limit=1&includePopularPlayerProps=false')
        for ids in ((), ('129629,1',), ('129629', '1')):
            with self.assertRaises(ValueError):
                exact_path(ids)

    def test_complete_below_limit(self):
        result, graph = self.read(length=13)
        self.assertTrue(result['json_complete'])
        self.assertTrue(result['eof'])
        self.assertEqual(graph, {'events': []})
        self.assertEqual(result['wire_bytes'], 13)

    def test_complete_at_known_length_limit(self):
        result, _ = self.read(length=13, limit=13)
        self.assertTrue(result['json_complete'])

    def test_oversize_without_length_stops_at_cap(self):
        result, graph = self.read(b' ' * 1000, limit=100)
        self.assertEqual(result['reason'], 'wire_byte_limit_no_eof')
        self.assertEqual(result['retained_sizes']['response.bin'], 100)
        self.assertIsNone(graph)

    def test_declared_oversize_stops_before_read(self):
        result, graph = self.read(length=1000, limit=100)
        self.assertEqual(result['wire_bytes'], 0)
        self.assertIsNone(graph)

    def test_truncated_content_length(self):
        result, graph = self.read(length=20)
        self.assertEqual(result['reason'], 'content_length_mismatch')
        self.assertIsNone(graph)

    def test_timeout(self):
        result, graph = self.read(deadline=time.monotonic() - 1)
        self.assertEqual(result['reason'], 'request_timeout')
        self.assertIsNone(graph)

    def test_gzip_complete_and_decoded_bomb(self):
        body = gzip.compress(b'{"events":[]}')
        result, graph = self.read(body, encoding='gzip', length=len(body), limit=100)
        self.assertTrue(result['json_complete'])
        self.assertEqual(graph, {'events': []})
        result, graph = self.read(gzip.compress(b' ' * 10000), encoding='gzip', limit=100)
        self.assertEqual(result['reason'], 'decoded_byte_limit')
        self.assertIsNone(graph)

    def test_gzip_truncated_and_trailing(self):
        body = gzip.compress(b'{"events":[]}')
        for value in (body[:-4], body + b'extra'):
            result, graph = self.read(value, encoding='gzip')
            self.assertEqual(result['reason'], 'gzip_incomplete_or_trailing')
            self.assertIsNone(graph)

    def test_bad_status_encoding_json_and_duplicate_keys(self):
        for body, options in [(b'{}', {'status': 302}), (b'{}', {'encoding': 'br'}),
                              (b'{', {}), (b'{"a":1,"a":2}', {}), (b'{"a":NaN}', {})]:
            result, graph = self.read(body, **options)
            self.assertFalse(result['json_complete'])
            self.assertIsNone(graph)

    def test_depth_bound(self):
        result, graph = self.read(b'[' * 65 + b']' * 65)
        self.assertEqual(result['reason'], 'json_complexity_limit')
        self.assertIsNone(graph)

    def test_numeric_original_strings_preserved(self):
        result, graph = self.read(json.dumps({'value': 0.235}).encode())
        self.assertTrue(result['json_complete'])
        self.assertEqual(graph['value'], '0.235')
