#!/usr/bin/env python3
"""Measure cached SGO event responses locally; no network or database access."""
import gzip
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

for arg in sys.argv[1:]:
    path = Path(arg)
    raw = path.read_bytes()
    times, peaks = [], []
    for _ in range(3):
        tracemalloc.start()
        start = time.perf_counter()
        data = json.loads(raw)
        times.append(time.perf_counter() - start)
        peaks.append(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()
    events = data['response']['data']
    odds = [odd for event in events for odd in event.get('odds', {}).values()]
    candidates = [odd for odd in odds if odd.get('periodID') == 'game' and odd.get('betTypeID') in ('ml', 'sp', 'ou') and odd.get('statEntityID') in ('all', 'home', 'away')]
    books = lambda rows: sum(len(odd.get('byBookmaker', {})) for odd in rows)
    print(f'{path}: bytes={len(raw)} gzip_bytes={len(gzip.compress(raw))} events={len(events)} odds={len(odds)} books={books(odds)} candidate_odds={len(candidates)} candidate_books={books(candidates)} median_seconds={statistics.median(times):.3f} median_peak_mib={statistics.median(peaks)/1048576:.2f}')
