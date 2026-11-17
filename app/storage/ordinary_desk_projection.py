"""Compact Browse fragments and immutable indexes for ordinary desk reads."""
from collections import OrderedDict
from threading import RLock
from time import monotonic

from psycopg.types.json import Jsonb

from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage

from . import comparison_snapshot as snapshots
from .storage_maintenance import REWRITE_RUNWAY_BYTES
from .store import encoded, stamp


# Retain only the deferred fields used by the ordinary public Browse summary.
# Other callers still read the original immutable members and full fragments.
DISPLAY_FIELDS = frozenset({
    'book_confirmation', 'book_size', 'conditional_trade_benchmark', 'conservative_trade_benchmark',
    'cost_per_normal_claim', 'original_record', 'participant_label', 'probability_missing',
    'reference', 'reference_calculation', 'same_outcome', 'snapshot_benchmark', 'metric_status',
    'minimum_return_percent',
})


def fragment(part):
    rows = []
    for source in part['rows']:
        row = snapshots.expand_row(source)
        detail = {key: row[key] for key in DISPLAY_FIELDS if key in row}
        if record := detail.get('original_record'):
            detail['original_record'] = {'comparison_source_metadata': {
                'alternate': (record.get('comparison_source_metadata') or {}).get('alternate')}}
        for key in ('conditional_trade_benchmark', 'conservative_trade_benchmark'):
            if detail.get(key):
                detail[key] = {k: detail[key][k] for k in ('available', 'ranking_basis', 'reason') if k in detail[key]}
        display = dict(source, **{key: value for key, value in detail.items() if key not in source})
        display.pop('_detail_json', None)
        for name, keys in (
            ('pregame_reference', ('available', 'reason', 'book', 'snapshot_id', 'policy_version', 'conditioning')),
            ('settlement_assessment', ('available', 'reason', 'probability_missing')),
            ('sportsbook_baseline', ('book', 'source', 'prices', 'candidates', 'candidate_books', 'probability',
                                     'return_percent', 'fair_decimal_odds', 'current_until', 'indicative', 'conditioning')),
        ):
            if display.get(name):
                display[name] = {k: display[name][k] for k in keys if k in display[name]}
        authority = display['current_authority']
        price = authority['price']
        display['current_authority'] = dict(authority, price={k: price[k] for k in (
            'lifecycle', 'current_until', 'expected', 'dependency', 'clock_at', 'reasons') if k in price},
            references=[{k: ref[k] for k in ('current_until', 'clock_at') if k in ref}
                        for ref in authority['references']])
        display['current_authority']['price']['expected'] = bool(price.get('expected'))
        rows.append(display)
    return snapshots.pack_read(dict(part, rows=rows, pairs=[], references=[], issues=[]))


def store(db, part):
    rows = part['rows']
    footprint = dict(
        leagues=sorted({row['league'] for row in rows}),
        games=sorted({row['game_key'] for row in rows}),
        slots=sorted({f"{row['league']}:{stamp(row['start_at']).isoformat()}" for row in rows}),
        ids=sorted({row['id'] for row in rows}),
        contracts=sorted({key for row in rows
                          if (key := row['current_authority']['price'].get('dependency'))}),
        occurrences=sorted({key for row in rows
                            if (key := row['current_authority'].get('occurrence_id'))}))
    packed = fragment(part)
    size = len(packed) + len(encoded(footprint))
    if sql_usage(db) + 2 * size + REWRITE_RUNWAY_BYTES >= SQL_BYTE_CAP:
        return 0
    db.execute('''UPDATE comparison_snapshot_result SET desk_index=%s,desk_fragment=%s
        WHERE id=%s AND desk_index IS NULL''', (Jsonb(footprint), packed, part['id']))
    return size


def backfill(db, root, *, limit=16):
    """Prepare old rolling members on the ordinary worker with bounded work."""
    from app.comparison.calculation_control import checkpoint

    if not root:
        return 0
    rows = db.execute('''SELECT r.read_fragment FROM comparison_result_reference m
        JOIN comparison_snapshot_result r ON r.id=m.result_id
        WHERE m.kind='member' AND m.holder=%s AND r.desk_index IS NULL
          AND r.read_fragment IS NOT NULL ORDER BY m.position LIMIT %s''', (root, limit))
    written = 0
    for row in rows:
        checkpoint()
        written += store(db, snapshots._decode(row['read_fragment']))
    return written


MAX_FRAGMENT_BYTES = 8 * 1024 * 1024


class DeskFragments:
    """Reuse immutable compressed member reads across filtered requests and roots."""

    def __init__(self):
        self.lock = RLock()
        self.index = (None, None)
        self.members = OrderedDict()
        self.bytes = 0

    def read(self, db, root_id, *, leagues, game_key, selected, quote_key, browse, timings=None):
        def record(stage, started):
            if timings is not None:
                timings[stage] = timings.get(stage, 0) + (monotonic() - started) * 1000

        with self.lock:
            root, index = self.index if (self.index[0] or {}).get('id') == root_id else (None, None)
        if root is None:
            stage = monotonic()
            row = db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s', (root_id,)).fetchone()
            record('fragment_sql', stage)
            if not row:
                return None
            stage = monotonic()
            root = snapshots._decode(row['result'])
            record('fragment_decode', stage)
            if root.get('_read_fragments') != 'publication-members-v1':
                return None
            stage = monotonic()
            index = db.execute('''SELECT m.result_id, r.desk_index FROM comparison_result_reference m
                JOIN comparison_snapshot_result r ON r.id=m.result_id
                WHERE m.kind='member' AND m.holder=%s ORDER BY m.position''', (root_id,)).fetchall()
            record('fragment_sql', stage)
            if len(index) != root['publication']['component_count'] or any(r['desk_index'] is None for r in index):
                return None
            with self.lock:
                self.index = root, index
        if selected or game_key:
            if selected:
                first = [r for r in index if selected in r['desk_index']['ids'] or
                         quote_key and quote_key in r['desk_index']['contracts']]
            else:
                first = [r for r in index if game_key in r['desk_index']['games']]
                # An old Open Game link can follow source identity after a rename.
                if not first:
                    return None
            occurrences = {key for r in first for key in r['desk_index']['occurrences']}
            slots = {key for r in first for key in r['desk_index']['slots']} if game_key else set()
            ids = {r['result_id'] for r in first}
            entries = [r for r in index if r['result_id'] in ids or
                       occurrences.intersection(r['desk_index']['occurrences']) or
                       slots.intersection(r['desk_index']['slots'])]
        else:
            entries = [r for r in index if not leagues or leagues.intersection(r['desk_index']['leagues'])]
        member_keys = [(r['result_id'], browse) for r in entries]
        with self.lock:
            found = {}
            for key in member_keys:
                if key in self.members:
                    found[key[0]] = self.members[key][0]
                    self.members.move_to_end(key)
        missing = [key[0] for key in member_keys if key[0] not in found]
        if missing:
            column = 'desk_fragment' if browse else 'read_fragment'
            stage = monotonic()
            rows = db.execute(f'SELECT id,{column} AS content FROM comparison_snapshot_result WHERE id=ANY(%s)',
                              (missing,)).fetchall()
            record('fragment_sql', stage)
            for r in rows:
                raw = r['content']
                if not raw:
                    return None
                stage = monotonic()
                part = snapshots._decode(raw)
                record('fragment_decode', stage)
                if part['id'] != r['id']:
                    raise snapshots.SnapshotOperationError('ordinary_fragment_identity')
                found[r['id']] = part
                size = len(raw)
                with self.lock:
                    key = (r['id'], browse)
                    if key not in self.members and size <= MAX_FRAGMENT_BYTES:
                        self.members[key] = part, size
                        self.bytes += size
                        while self.bytes > MAX_FRAGMENT_BYTES or len(self.members) > 256:
                            _, (_, removed) = self.members.popitem(last=False)
                            self.bytes -= removed
        if len(found) != len(entries):
            return None
        return dict(root, **{field: [value for key, _ in member_keys for value in found[key][field]]
                             for field in ('rows', 'games', 'pairs', 'references', 'issues')})
