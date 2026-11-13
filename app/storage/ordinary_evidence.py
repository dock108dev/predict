"""Bounded reads of immutable members of the displayed comparison generation."""

from collections import defaultdict
import json
import zlib

from app.comparison.calculation_control import checkpoint
from . import comparison_snapshot as snapshots
from .store import hashed

MAX_MEMBERS = 4096
MAX_MEMBER_BYTES = 8 * 1024 * 1024


def event_id(source):
    return hashed([source['provider'], source['native_event_id']])


def members(db, *, legacy_components=None):
    """Read only index metadata; work staged ahead of the head is invisible."""
    rows = db.execute('''
        SELECT m.result_id AS member_id, c.id AS component_id, r.read_summary->'event_ids' AS event_ids,
               octet_length(r.result) AS stored_bytes
        FROM comparison_publication h
        JOIN comparison_result_reference m ON m.kind='member' AND m.holder=h.result_id
        JOIN comparison_snapshot_result r ON r.id=m.result_id
        LEFT JOIN comparison_publication c ON c.kind='component' AND c.result_id=m.result_id
        WHERE h.kind='live' AND h.id=''
        ORDER BY m.result_id LIMIT %s
    ''', (MAX_MEMBERS + 1,)).fetchall()
    if len(rows) > MAX_MEMBERS:
        raise snapshots.SnapshotOperationError('ordinary_member_index_capacity')
    by_event = defaultdict(list)
    if legacy_components is None and any(row['event_ids'] is None for row in rows):
        from .board_capture import capture_batches
        legacy_components = {hashed(sorted(group)): group for group in capture_batches(db)}
    for row in rows:
        ids = row['event_ids']
        if ids is None:
            ids = (legacy_components or {}).get(row['component_id'], ())
        for id_ in ids:
            by_event[id_].append(row)
    return by_event


def selected_members(index, event_ids):
    return list({r['member_id']: r for event in event_ids for r in index.get(event, ())}.values())


def read_member(db, member, *, capacity=MAX_MEMBER_BYTES):
    checkpoint()
    if member['stored_bytes'] > capacity:
        raise snapshots.SnapshotOperationError('ordinary_member_read_capacity')
    raw = db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',
                     (member['member_id'],)).fetchone()['result']
    # Automatic members are emitted by pack(fast=True) or pack_read. Limit
    # expansion before the JSON decoder allocates the result object graph.
    if raw.startswith(b'PJ1'):
        raw = raw[3:]
    if not raw.startswith(b'\x1f\x8b'):
        raise snapshots.SnapshotOperationError('ordinary_member_read_encoding')
    inflate = zlib.decompressobj(wbits=31)
    body = inflate.decompress(raw, capacity + 1)
    if len(body) > capacity or not inflate.eof or inflate.unused_data:
        raise snapshots.SnapshotOperationError('ordinary_member_read_capacity')
    result = json.loads(body)
    if result.get('id') != member['member_id'] or '_read_fragments' in result:
        raise snapshots.SnapshotOperationError('ordinary_member_read_identity')
    return result
