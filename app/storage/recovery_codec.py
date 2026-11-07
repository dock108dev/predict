"""Lossless bounded storage of current metadata, not a new evidence format.

SQL list fields remain small and readable; recovery/census owners decode the
complete original object before interpreting it. Historical plain JSONB remains
readable. A stored packet is self-contained, with no dangling payload dictionary.
"""
import base64
import gzip
from hashlib import sha256
import io
import json
from .store import encoded

VERSION='predict-recovery-gzip-1'
MAX_BYTES=8*1024*1024
DISPLAY=('title','period','sides')


def freeze(value):
    if value is None:return None
    raw=encoded(value)
    # Leave exceptional large records on the original owner/guard path. This
    # storage optimization is never a new rejection or reduced source scope.
    if not 2048<=len(raw)<=MAX_BYTES:return value
    compressed=gzip.compress(raw,compresslevel=6,mtime=0)
    result={k:value[k] for k in DISPLAY if k in value}
    result['_predict_storage']=dict(version=VERSION,length=len(raw),sha256=sha256(raw).hexdigest(),
        body=base64.b64encode(compressed).decode())
    return result if len(encoded(result))<len(raw) else value


def thaw(value):
    if value is None or '_predict_storage' not in value:return value
    packet=value['_predict_storage']
    if set(value)-set(DISPLAY)-{'_predict_storage'} or packet.get('version')!=VERSION:
        raise ValueError('native_recovery_storage_format')
    if type(packet.get('length')) is not int or not 0<=packet['length']<=MAX_BYTES:
        raise ValueError('native_recovery_storage_capacity')
    if len(packet.get('body',''))>MAX_BYTES*2:raise ValueError('native_recovery_storage_capacity')
    with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(packet['body'],validate=True))) as stream:
        raw=stream.read(MAX_BYTES+1)
    if len(raw)!=packet['length'] or sha256(raw).hexdigest()!=packet['sha256']:
        raise ValueError('native_recovery_storage_integrity')
    result=json.loads(raw)
    if {k:result[k] for k in DISPLAY if k in result}!={k:value[k] for k in DISPLAY if k in value}:
        raise ValueError('native_recovery_display_conflict')
    return result


# The existing maintenance owner upgrades old self-contained values gradually.
# A bounded cursor revisits small/incompressible rows fairly without pinning a
# long transaction or waiting for a provider's complete catalog traversal.
_after={}
REPACK_ROWS=512
REPACK_BYTES=8*1024*1024
REPACK_SECONDS=1


def repack(db):
    from time import monotonic
    from psycopg.types.json import Jsonb
    from app.collection.current_storage_policy import SQL_BYTE_CAP,sql_usage,require_disk_space
    from .storage_maintenance import REWRITE_RUNWAY_BYTES
    from .store import ROOT
    result=dict(scanned=0,updated=0,input_bytes=0,output_bytes=0)
    if sql_usage(db)+2*REPACK_BYTES+REWRITE_RUNWAY_BYTES>=SQL_BYTE_CAP:
        return dict(result,deferred='recovery_repack_headroom')
    require_disk_space(ROOT/'.local/postgres',append_bytes=2*REPACK_BYTES)
    key=db.info.dbname;cursor=_after.get(key,('',''));started=monotonic()
    with db.transaction():
        keys=db.execute('SELECT source,market_id FROM current_native_market_recovery '
            "WHERE (source,market_id)>(%s,%s) AND (NOT(metadata ? '_predict_storage') "
            "OR (parsed IS NOT NULL AND NOT(parsed ? '_predict_storage') AND pg_column_size(parsed)>2048)) "
            'ORDER BY source,market_id LIMIT %s',(*cursor,REPACK_ROWS)).fetchall()
        if not keys:_after.pop(key,None);return result
        result['key_seconds']=round(monotonic()-started,6)
        reading=monotonic()
        # One bounded read and pipelined writes avoid two SQL round trips per
        # market. The SQL window bounds uncompressed JSON bytes before Python
        # materializes the batch; oversized records stay on their original path.
        rows=db.execute("""WITH sized AS MATERIALIZED (
            SELECT source,market_id,octet_length(metadata::text)+COALESCE(octet_length(parsed::text),0) bytes
            FROM current_native_market_recovery
            WHERE (source,market_id) IN (SELECT * FROM unnest(%s::text[],%s::text[]))),
          bounded AS (SELECT *,sum(bytes) OVER(ORDER BY source,market_id) running
            FROM sized WHERE bytes<=%s)
          SELECT r.source,r.market_id,r.metadata,r.parsed FROM current_native_market_recovery r
          JOIN bounded b USING(source,market_id) WHERE b.running<=%s
          ORDER BY r.source,r.market_id FOR UPDATE OF r SKIP LOCKED""",
          ([r['source'] for r in keys],[r['market_id'] for r in keys],REPACK_BYTES,REPACK_BYTES)).fetchall()
        result['read_seconds']=round(monotonic()-reading,6)
        # SQL has its own row/byte/statement bounds. Do not spend the encoding
        # budget before encoding begins and discard an already fetched batch.
        encoding=monotonic();jobs=[];last=None
        for value in rows:
            last=(value['source'],value['market_id']);result['scanned']+=1
            original=[value['metadata'],value['parsed']]
            replacement=[v if v is None or '_predict_storage'in v else freeze(v) for v in original]
            if original!=replacement:
                before=sum(len(encoded(v)) for v in original);after=sum(len(encoded(v)) for v in replacement)
                if result['output_bytes']+after>REPACK_BYTES:break
                jobs.append((Jsonb(replacement[0]),Jsonb(replacement[0]),
                    Jsonb(replacement[1]) if replacement[1] is not None else None,
                    Jsonb(replacement[1]) if replacement[1] is not None else None,*last))
                result['updated']+=1;result['input_bytes']+=before;result['output_bytes']+=after
            if monotonic()-encoding>=REPACK_SECONDS:break
        result['encode_seconds']=round(monotonic()-encoding,6)
        writing=monotonic()
        if jobs:
            with db.cursor() as writer:
                writer.executemany('UPDATE current_native_market_recovery SET '
                    'metadata=CASE WHEN metadata=%s THEN metadata ELSE %s END, '
                    'parsed=CASE WHEN parsed IS NOT DISTINCT FROM %s THEN parsed ELSE %s END '
                    'WHERE source=%s AND market_id=%s',jobs)
        result['write_seconds']=round(monotonic()-writing,6)
        # No usable rows (busy or oversized) still advance this bounded scan;
        # wrapping revisits them, without delaying unrelated native identities.
        _after[key]=last or (keys[-1]['source'],keys[-1]['market_id'])
    if len(_after)>8:_after.pop(next(iter(_after)))
    result['seconds']=round(monotonic()-started,6)
    return result
