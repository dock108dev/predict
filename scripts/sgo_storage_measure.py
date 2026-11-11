"""Measure cached SGO pages in a disposable project database; no provider I/O.

Run as ``python -m scripts.sgo_storage_measure capture.json ...``. The script
creates and drops only its own randomly named prediction_arb_sgo_measure databases.
"""
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
import tracemalloc
from uuid import uuid4

from psycopg import sql

from app.collection.sportsgameodds_adapter import parse_page
from app.storage.sportsgameodds_reference import prepare_page, upsert_rows
from app.storage.store import Store, connect, encoded


def measure(db, label, page, *, parse_seconds=None, peak_bytes=None, body_bytes=None):
    start = time.perf_counter()
    rows = prepare_page(page)
    preparation = time.perf_counter() - start
    before = db.execute("SELECT pg_total_relation_size('current_sgo_reference') AS n").fetchone()['n']
    start = time.perf_counter()
    with db.transaction():
        inserted = upsert_rows(db, rows)
    initial = time.perf_counter() - start
    after = db.execute("SELECT pg_total_relation_size('current_sgo_reference') AS n").fetchone()['n']
    start = time.perf_counter()
    with db.transaction():
        changed = upsert_rows(db, rows)
    replay = time.perf_counter() - start
    print(json.dumps(dict(label=label, events=len(page.events), rows=len(rows),
        payload_bytes=body_bytes, parse_seconds=parse_seconds,
        parse_peak_bytes=peak_bytes, reference_batch_bytes=len(encoded(rows)),
        prepare_seconds=preparation, initial_seconds=initial, initial_changed=inserted,
        repeat_seconds=replay, repeat_changed=changed, table_growth_bytes=after-before), sort_keys=True))


def main(paths):
    if not paths:
        raise ValueError('at least one cached response wrapper path is required')
    name = 'prediction_arb_sgo_measure_' + uuid4().hex[:10]
    with connect() as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with connect(name) as db:
            Store(db).migrate()
            first = None
            for path in paths:
                wrapper = json.loads(Path(path).read_bytes())
                body = json.dumps(wrapper['response'], separators=(',', ':')).encode()
                tracemalloc.start()
                start = time.perf_counter()
                try:
                    page = parse_page(body, wrapper['received_at'])
                    seconds = time.perf_counter() - start
                    peak = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                measure(db, Path(path).name + ':compact-cache-replay', page,
                        parse_seconds=seconds, peak_bytes=peak, body_bytes=len(body))
                if first is None:
                    first = page
            base = {}
            for quote in first.quotes:
                base.setdefault((quote['event_id'], quote['odd_id']), quote)
            synthetic = replace(first, quotes=tuple(dict(q, venue='synthetic_book_' + str(i))
                for q in base.values() for i in range(100)))
            scale_name = 'prediction_arb_sgo_measure_' + uuid4().hex[:10]
            with connect() as admin:
                admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(scale_name)))
            try:
                with connect(scale_name) as scale_db:
                    Store(scale_db).migrate()
                    measure(scale_db, 'synthetic-100-book-scale', synthetic)
            finally:
                with connect() as admin:
                    admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(scale_name)))
    finally:
        with connect() as admin:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


if __name__ == '__main__':
    main(sys.argv[1:])
