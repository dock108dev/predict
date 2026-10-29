#!/usr/bin/env python3
"""Losslessly repack retained boards with compare-and-swap; no acquisition."""
import json
from pathlib import Path
import sys
from time import monotonic
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from psycopg.types.json import Jsonb
from app.storage.store import connect,encoded
from app.dashboard.comparison_board import compact_price_fields,expand_price_fields

start=monotonic();count=raced=before=after=0
with connect() as reader,connect() as writer,reader.transaction():
    with reader.cursor(name='recompact_current_publications') as cursor:
        cursor.itersize=1;cursor.execute('SELECT game_key,facts FROM latest_board ORDER BY game_key')
        for row in cursor:
            original=encoded(row['facts']);facts=row['facts'];before+=len(original)
            for board in facts['boards'].values():
                old=encoded(expand_price_fields(board));compact_price_fields(board)
                assert encoded(expand_price_fields(json.loads(encoded(board))))==old
            packed=encoded(facts);after+=len(packed)
            result=writer.execute('UPDATE latest_board SET facts=%s WHERE game_key=%s AND facts=%s',
                (Jsonb(facts),row['game_key'],Jsonb(json.loads(original))))
            if result.rowcount:count+=1
            else:raced+=1
result=dict(repacked=count,raced=raced,before_bytes=before,after_bytes=after,
    every_expanded_field_equal=True,provider_requests=0,seconds=monotonic()-start)
Path(sys.argv[1]).write_text(json.dumps(result));print(json.dumps(result))
