"""Closed-attempt resource receipt; no transport, credentials or replay mutation."""
from datetime import datetime, timezone
import json
import os
import time

from .continuous import rss
from .segmented import fsync_dir

RECEIPT_BYTES = 16 * 1024
RECEIPT_NAME = 'finalization-resources.json'


def write_supplement(output, history, result, *, started, closed):
    """Only history manifests may have been replaced; other attempt files are append-only.

    Measure through validation.json serialization, write, fsync, close and directory
    fsync. The fixed-size receipt is included in byte totals but its own creation is
    outside the timing/RSS boundary. No claim about process exit or lifetime peak.
    """
    if output.resolve() != history.output_root.resolve() or not history.closed:
        raise ValueError('closed history and exact attempt output root required')
    report_path = output/'validation.json'
    receipt_path = output/RECEIPT_NAME
    if report_path.exists() or receipt_path.exists():
        raise FileExistsError('supplemental evidence already exists')
    began = time.monotonic()
    body = json.dumps(result, indent=2).encode()
    history._guard(len(body) + RECEIPT_BYTES)
    before = history.disk_bytes()
    manifest_size = (history.folder/'manifest.json').stat().st_size
    replaced = history.manifest_write_bytes - manifest_size
    if replaced < 0:
        raise ValueError('manifest write accounting incomplete')
    projected_writes = before + len(body) + RECEIPT_BYTES + replaced
    if projected_writes > history.policy['write_bytes']:
        raise ValueError('supervised_finalization_write_cap')
    with report_path.open('xb', buffering=0) as f:
        if f.write(body) != len(body):
            raise OSError('short supplemental report write')
        os.fsync(f.fileno())
    fsync_dir(output)
    written = time.monotonic()
    # ru_maxrss is the process high-water, including temporary serialization
    # allocations even if released before this sample.
    post_write_peak = rss()
    retained = history.disk_bytes()
    measured = time.monotonic()
    receipt = dict(
        schema='predict-finalization-resources-v1',
        boundary='validation.json serialized, fsynced, closed and directory fsynced; receipt creation excluded from RSS/timing',
        byte_scope='attempt regular-file payload bytes; receipt included at fixed size; excludes OS metadata and external control/analysis artifacts',
        write_scope='retained payload bytes plus replaced history manifest payloads; all other attempt files append-only',
        memory_scope='process high-water sampled after supplemental report write, not process lifetime through exit',
        measured_utc=datetime.now(timezone.utc).isoformat(),
        supplemental_report_bytes=len(body), receipt_bytes=RECEIPT_BYTES,
        retained_before_supplement_bytes=before,
        retained_through_supplement_bytes=retained,
        final_retained_output_bytes=retained + RECEIPT_BYTES,
        history_manifest_writes=history.manifest_writes,
        history_manifest_write_bytes=history.manifest_write_bytes,
        retained_history_manifest_bytes=manifest_size,
        replaced_history_manifest_bytes=replaced,
        cumulative_application_file_write_bytes=retained + RECEIPT_BYTES + replaced,
        post_report_write_process_high_water_bytes=post_write_peak,
        supplemental_serialization_write_seconds=written-began,
        collection_closed_elapsed=closed-started,
        report_write_finished_elapsed=written-started,
        finalization_through_report_seconds=written-closed,
        measurement_finished_elapsed=measured-started,
    )
    receipt['checks'] = dict(
        retained_reconciles=retained == before + len(body),
        output_cap=receipt['final_retained_output_bytes'] <= history.policy['output'],
        write_cap=receipt['cumulative_application_file_write_bytes'] <= history.policy['write_bytes'],
        rss_cap=post_write_peak < history.policy['rss'],
        finalization_deadline=measured-closed <= history.policy['finalization_seconds'],
    )
    receipt['status'] = 'complete' if all(receipt['checks'].values()) else 'failed'
    encoded = json.dumps(receipt, indent=2).encode()
    if len(encoded) > RECEIPT_BYTES:
        raise ValueError('resource receipt size exceeded')
    # JSON permits trailing whitespace. Exact fixed length avoids self-accounting
    # iteration and includes this single successful write in the reported totals.
    with receipt_path.open('xb', buffering=0) as f:
        if f.write(encoded.ljust(RECEIPT_BYTES, b' ')) != RECEIPT_BYTES:
            raise OSError('short resource receipt write')
        os.fsync(f.fileno())
    fsync_dir(output)
    if history.disk_bytes() != receipt['final_retained_output_bytes']:
        raise ValueError('final retained output changed during receipt write')
    return receipt
