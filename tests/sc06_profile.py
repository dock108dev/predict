"""Separate diagnostic profile; never used as a responsiveness timing pass."""

import asyncio
import cProfile
import json
from pathlib import Path
import pstats
import resource
import shutil
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

from app.dashboard.scanner_api import Scanner
from app.storage.current_rows import CurrentRowStore
from app.storage.scanner_publication import transaction
from tests import test_sc02_sql as sql
from tests.sc06_fixture import AuthoredAdapters, Clock, records, native_books
from copy import deepcopy
from decimal import Decimal


def run(output):
    if not sql.SOCKET:
        raise RuntimeError("Verified disposable SQL required")
    sql.SQL.setUpClass()
    try:
        clock = Clock()
        rows = records(500, at=clock())
        with sql.SQL.connect() as db:
            db.execute("TRUNCATE current_event CASCADE")
            with transaction(db):
                s = CurrentRowStore(db)
                s.upsert_records(rows)
                s.replace_native_books(native_books(rows))
        with TemporaryDirectory(prefix="sc06-profile-summary-") as directory:
            worker = Scanner(
                sql.SQL.provider(None),
                connector=sql.SQL.connect,
                clock=clock,
                summary_path=Path(directory) / "summary",
            )
            profile = cProfile.Profile()
            started = perf_counter()
            try:
                with AuthoredAdapters():
                    profile.enable()
                    frame, inputs, metadata, elapsed = worker._capture()
                    profile.disable()
                    cold_stats = (
                        worker.preparation.stats()
                        if hasattr(worker, "preparation")
                        else None
                    )
                    repeat_frame, _, repeat_metadata, repeat_ms = worker._capture()
                    changed = deepcopy(rows[:2])
                    at = clock()
                    for leg, row in enumerate(changed):
                        quote = row["quote"]
                        quote["times"].update(
                            source_at=at, received_at=at, projected_at=at
                        )
                        quote["original"]["value"] = str(
                            Decimal(quote["original"]["value"])
                            - Decimal("0.001") * (leg + 1)
                        )
                        quote["depth"][0]["price"] = quote["original"]["value"]
                        quote["original"].update(
                            native_value=quote["original"]["value"],
                            native_units=quote["original"]["units"],
                            transformation="identity",
                        )
                    with sql.SQL.connect() as db:
                        with transaction(db):
                            store = CurrentRowStore(db)
                            store.upsert_records(changed)
                            store.replace_native_books(native_books(changed))
                    material_profile = cProfile.Profile()
                    material_profile.enable()
                    changed_frame, changed_inputs, changed_metadata, changed_ms = (
                        worker._capture()
                    )
                    material_profile.disable()
                    pair = next(
                        p
                        for p in changed_frame["pairs"]
                        if any(
                            changed_inputs[k]["quote"]["source"]["native_event_id"]
                            == changed[0]["quote"]["source"]["native_event_id"]
                            for k in p["legs"]
                        )
                    )
                    selected_start = perf_counter()
                    selected_frame, _ = worker._capture_selected(
                        dict(inputs={k: changed_inputs[k] for k in pair["legs"]})
                    )
                    selected_ms = (perf_counter() - selected_start) * 1000
                peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
                    1 if sys.platform == "darwin" else 1024
                )
                with sql.SQL.connect() as db:
                    sql_bytes = db.execute(
                        "select pg_database_size(current_database()) n"
                    ).fetchone()["n"]
                if (
                    peak > 768 * 1024**2
                    or sql_bytes > 2 * 1024**3
                    or shutil.disk_usage(directory).free < 1024**3
                ):
                    raise RuntimeError("SC06 profiling resource guard")
                stats = pstats.Stats(profile)
                entries = [
                    dict(
                        file=key[0],
                        line=key[1],
                        function=key[2],
                        primitive_calls=value[0],
                        calls=value[1],
                        self_ms=value[2] * 1000,
                        cumulative_ms=value[3] * 1000,
                    )
                    for key, value in stats.stats.items()
                ]
                material_entries = [
                    dict(
                        file=key[0],
                        line=key[1],
                        function=key[2],
                        primitive_calls=value[0],
                        calls=value[1],
                        self_ms=value[2] * 1000,
                        cumulative_ms=value[3] * 1000,
                    )
                    for key, value in pstats.Stats(material_profile).stats.items()
                ]
                from app.collection.current_policy import candidate
                from app.storage.current_games import engine_binding

                result = dict(
                    application=candidate()[0],
                    engine=engine_binding(),
                    one_material_profile_note="diagnostic cProfile overhead; do not use profiled duration as responsiveness timing",
                    one_material_by_cumulative=sorted(
                        material_entries, key=lambda v: -v["cumulative_ms"]
                    )[:60],
                    one_material_by_self=sorted(
                        material_entries, key=lambda v: -v["self_ms"]
                    )[:60],
                    evidence_class="separate cProfile diagnostic; profiler overhead excluded from timing campaign",
                    events=len({i["occurrence_id"] for i in frame["instruments"]}),
                    instruments=len(frame["instruments"]),
                    pairs=len(frame["pairs"]),
                    capture_ms=elapsed,
                    total_ms=(perf_counter() - started) * 1000,
                    provider_requests=0,
                    current_rows_revision=metadata["current_rows_revision"],
                    peak_rss_bytes=peak,
                    sql_bytes=sql_bytes,
                    captures=dict(
                        cold_profiled=dict(ms=elapsed, cache=cold_stats),
                        unchanged=dict(
                            ms=repeat_ms,
                            instruments=len(repeat_frame["instruments"]),
                            metadata=repeat_metadata,
                        ),
                        one_material_event=dict(
                            ms=changed_ms,
                            instruments=len(changed_frame["instruments"]),
                            metadata=changed_metadata,
                        ),
                        selected_fresh=dict(
                            ms=selected_ms,
                            instruments=len(selected_frame["instruments"]),
                            pairs=len(selected_frame["pairs"]),
                        ),
                    ),
                    by_cumulative=sorted(entries, key=lambda v: -v["cumulative_ms"])[
                        :60
                    ],
                    by_self=sorted(entries, key=lambda v: -v["self_ms"])[:60],
                )
                Path(output).write_text(json.dumps(result, indent=2) + "\n")
            finally:
                asyncio.run(worker.close())
    finally:
        sql.SQL.tearDownClass()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    run(p.parse_args().output)
