"""Lossless journal-row encoding without references, batching or external payload storage."""
import base64
import json
import zlib
from app.reference.records import packed, _json_scalar

VERSION = 'd2-zlib-row-1'
MAX_EXPANDED = 32 * 1024 * 1024


def packed_chunks(row):
    encoder=json.JSONEncoder(sort_keys=True,separators=(',',':'),ensure_ascii=False,
                             allow_nan=False,default=_json_scalar)
    for chunk in encoder.iterencode(row):yield chunk.encode()


def packed_size(row):
    return sum(len(chunk) for chunk in packed_chunks(row))


def encode(row):
    raw = packed(row).encode()
    if len(raw) > MAX_EXPANDED:
        raise ValueError('journal expanded row cap')
    return dict(journal_encoding=VERSION, expanded_bytes=len(raw),
                payload_b64=base64.b64encode(zlib.compress(raw)).decode())


def decode(value):
    if 'journal_encoding' not in value:
        return value
    if value.get('journal_encoding') != VERSION:
        raise ValueError('unsupported journal encoding')
    try:
        n = value['expanded_bytes']
        if type(n) is not int or not 0 <= n <= MAX_EXPANDED:
            raise ValueError('journal expanded row cap')
        body = base64.b64decode(value['payload_b64'], validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(body, n + 1)
        if len(raw) != n or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('incomplete or overbound journal payload')
        row = json.loads(raw)
        if not isinstance(row, dict) or 'type' not in row:
            raise ValueError('invalid journal row')
        offset=0;view=memoryview(raw)
        for chunk in packed_chunks(row):
            if view[offset:offset+len(chunk)]!=chunk:raise ValueError('invalid journal row')
            offset+=len(chunk)
        if offset!=len(raw):raise ValueError('invalid journal row')
        return row
    except (KeyError, TypeError, zlib.error, UnicodeError) as exc:
        raise ValueError('invalid journal payload') from exc
