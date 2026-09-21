"""Explicit-connection PostgreSQL persistence over the existing reference Store."""
from hashlib import sha256
from pathlib import Path

from psycopg import sql
from app.reference.storage import ReferenceStore, TABLES
from app.reference.records import import_records, packed, as_of
from app.pricing.baseline import recompute, restore


class FairPriceStore:
    def __init__(self, connection):
        self.db = connection
        self.references = ReferenceStore(connection)
        self.foundation = self.references.foundation

    def save(self, estimate):
        # Recompute validates ALL receipt/knowledge/effective cutoffs, not just
        # included inputs. No mutable caller-supplied decision can enter storage.
        recompute(estimate)
        data = estimate.data
        with self.db.transaction():
            # Freeze the bounded reference history while checking complete as-of
            # selection and writing links. A caller cannot silently omit a newer
            # rejected arrival. Existing immutable records remain readable later.
            for table in TABLES.values():
                self.db.execute(sql.SQL('LOCK TABLE {} IN SHARE MODE').format(sql.Identifier(table)))
            existing = self.db.execute('SELECT 1 FROM fair_price WHERE id=%s', (estimate.id,)).fetchone()
            if not existing:
                current = tuple(self.references._decode(r) for table in TABLES.values() for r in
                    self.db.execute(sql.SQL('SELECT payload,payload_sha256 FROM {}').format(sql.Identifier(table))))
                if as_of(current, data['as_of']) != data['dependencies']:
                    raise ValueError('estimate omits or changes current as-of dependencies')
            for record in import_records(data['dependencies']):
                if self.references.get(type(record), record.id) != record:
                    raise ValueError('durable dependency differs from saved input')
            body = estimate.export()
            self.foundation.immutable('fair_price', {
                'id': estimate.id, 'target_venue': data['target']['venue'],
                'as_of': data['as_of'], 'estimated_at': data['estimated_at'],
                'method': data['method'], 'policy_version': data['policy']['version'],
                'payload': body, 'payload_sha256': sha256(body.encode()).hexdigest()}, ['id'])
            for row in data['candidates']:
                body = packed(row)
                self.foundation.immutable('fair_price_input', {
                    'estimate_id': estimate.id, 'receipt_id': row['receipt_id'],
                    'enrichment_id': row['enrichment_id'], 'source_id': row['source_id'],
                    'included': row['included'], 'payload': body,
                    'payload_sha256': sha256(body.encode()).hexdigest()}, ['estimate_id', 'receipt_id'])

    def get(self, identity):
        row = self.db.execute('SELECT payload,payload_sha256 FROM fair_price WHERE id=%s', (identity,)).fetchone()
        if not row or sha256(row['payload'].encode()).hexdigest() != row['payload_sha256']:
            raise ValueError('missing or corrupted durable estimate')
        estimate = restore(row['payload'])
        if estimate.id != identity:
            raise ValueError('durable estimate identity mismatch')
        for record in import_records(estimate.data['dependencies']):
            if self.references.get(type(record), record.id) != record:
                raise ValueError('durable dependency mismatch')
        rows = self.db.execute('SELECT payload,payload_sha256 FROM fair_price_input WHERE estimate_id=%s ORDER BY receipt_id', (identity,)).fetchall()
        expected = sorted(estimate.data['candidates'], key=lambda r: r['receipt_id'])
        if len(rows) != len(expected) or any(r['payload'] != packed(e) or r['payload_sha256'] != sha256(r['payload'].encode()).hexdigest() for r, e in zip(rows, expected)):
            raise ValueError('durable input linkage mismatch')
        return estimate

    def export(self, identity, path):
        text = self.get(identity).export()
        Path(path).write_text(text)
        return sha256(text.encode()).hexdigest()

    def restore(self, path):
        # Restore E2 reference-bundle-1 first on a fresh store. Retains all E2
        # arrivals, including later observations beyond individual estimate cuts.
        estimate = restore(Path(path).read_text())
        self.save(estimate)
        return estimate
