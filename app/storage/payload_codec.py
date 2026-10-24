"""Lossless bounded physical encoding; logical JSON bytes and identities stay exact."""
import base64
import binascii
from hashlib import sha256
import lzma
import re
import zlib

LEGACY_PREFIX = 'predict-payload-zlib-1:'
PREFIX = 'predict-payload-xz-2:'
from .domain_delta import PREFIX as DOMAIN_PREFIX
from .domain_frame import FRAME_PREFIX
DOMAIN_PREFIXES = (DOMAIN_PREFIX, FRAME_PREFIX)
PREFIXES = (LEGACY_PREFIX, PREFIX)
MAX_LOGICAL_BYTES = 8 * 1024 * 1024
MAX_COMPRESSED_BYTES = MAX_LOGICAL_BYTES + 1024
MAX_ENCODED_BYTES = max(map(len, PREFIXES)) + 80 + 4 * ((MAX_COMPRESSED_BYTES + 2) // 3)
XZ_FILTERS = [dict(id=lzma.FILTER_LZMA2, preset=0, dict_size=1024*1024)]
XZ_DECODE_MEMORY = 16 * 1024 * 1024
TABLES = ('current_game_snapshot', 'current_game_result', 'current_envelope')


def decode(value):
    """Accept legacy JSON or verify and restore the exact encoded UTF-8 string."""
    if not isinstance(value, str):
        raise ValueError('saved_payload_text_required')
    if value.startswith(DOMAIN_PREFIXES):
        raise ValueError('saved_domain_connection_required')
    prefix = next((p for p in PREFIXES if value.startswith(p)), None)
    if prefix is None:
        return value
    if len(value) > MAX_ENCODED_BYTES:
        raise ValueError('saved_payload_encoded_capacity')
    parts = value[len(prefix):].split(':', 2)
    if len(parts) != 3 or not re.fullmatch(r'[0-9]{1,8}', parts[0]) or not re.fullmatch(r'[a-f0-9]{64}', parts[1]):
        raise ValueError('saved_payload_encoding_invalid')
    size = int(parts[0])
    if size > MAX_LOGICAL_BYTES:
        raise ValueError('saved_payload_logical_capacity')
    try:
        body = base64.b64decode(parts[2], validate=True)
        if len(body) > MAX_COMPRESSED_BYTES:
            raise ValueError('saved_payload_compressed_capacity')
        inflater = (zlib.decompressobj() if prefix == LEGACY_PREFIX else
                    lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=XZ_DECODE_MEMORY))
        original = inflater.decompress(body, size + 1)
        if (len(original) != size or not inflater.eof or inflater.unused_data
                or prefix == LEGACY_PREFIX and inflater.unconsumed_tail):
            raise ValueError('saved_payload_length_or_stream_invalid')
        if sha256(original).hexdigest() != parts[1]:
            raise ValueError('saved_payload_hash_mismatch')
        return original.decode('utf-8')
    except (zlib.error, lzma.LZMAError, UnicodeError, binascii.Error) as exc:
        raise ValueError('saved_payload_encoding_invalid') from exc


def encode(value):
    """Compress only when smaller; repeated encodings keep one representation."""
    original = decode(value)
    body = original.encode('utf-8')
    if len(body) > MAX_LOGICAL_BYTES:
        raise ValueError('saved_payload_logical_capacity')
    compressed = lzma.compress(body, format=lzma.FORMAT_XZ, filters=XZ_FILTERS)
    encoded = PREFIX + str(len(body)) + ':' + sha256(body).hexdigest() + ':' + base64.b64encode(compressed).decode('ascii')
    return encoded if len(encoded.encode()) < len(body) else original


def decode_for_connection(value,db):
    if isinstance(value,str) and value.startswith(DOMAIN_PREFIXES):
        from .domain_history import decode as domain_decode
        return domain_decode(value,db)
    return decode(value)


def payload_row(cursor):
    """Decode saved payload columns at the shared read boundary, never in SQL."""
    from psycopg.rows import dict_row
    make_row = dict_row(cursor)
    # A row factory belongs to its cursor. Capturing that cursor here creates
    # a cycle which retains its entire libpq result until cyclic GC, even after
    # fetchall and connection close. Keep only the decoder's connection/type.
    from psycopg import ServerCursor
    connection=cursor.connection
    server_cursor=isinstance(cursor,ServerCursor)
    def row(values):
        result = make_row(values)
        value = result.get('payload')
        if isinstance(value, str) and value.startswith(PREFIXES+DOMAIN_PREFIXES):
            if value.startswith(DOMAIN_PREFIXES) and server_cursor:
                raise ValueError('saved_domain_server_cursor_requires_explicit_decode')
            result['payload'] = decode_for_connection(value,connection) if value.startswith(DOMAIN_PREFIXES) else decode(value)
        return result
    return row


def logical_size_sql(column='payload'):
    """Reject bad headers and bound expanded UTF-8 bytes before returning rows."""
    from psycopg import sql
    if not re.fullmatch(r'[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?',column):
        raise ValueError('saved_payload_sql_identifier_invalid')
    field=sql.Identifier(*column.split('.'))
    rejected=sql.Literal(MAX_LOGICAL_BYTES*257)
    branches=[]
    for prefix in PREFIXES+DOMAIN_PREFIXES:
        start=sql.Literal(len(prefix)+1)
        head=sql.SQL("split_part(substring({} from {} for 9),':',1)").format(field,start)
        branches.append(sql.SQL("""WHEN left({field},{prefix_length})={prefix} THEN
          CASE WHEN {head} ~ '^[0-9]{{1,8}}$' AND
            substring({field} from {start} for 76) ~ '^[0-9]{{1,8}}:[a-f0-9]{{64}}:' THEN
            CASE WHEN {head}::bigint<={maximum} AND octet_length({field})<{head}::bigint
              THEN {head}::bigint ELSE {rejected} END
            ELSE {rejected} END""").format(field=field,prefix_length=sql.Literal(len(prefix)),prefix=sql.Literal(prefix),
            head=head,start=start,maximum=sql.Literal(MAX_LOGICAL_BYTES),rejected=rejected))
    return sql.SQL('CASE {} ELSE octet_length({}) END').format(sql.SQL(' ').join(branches),field)
