"""PostgreSQL reference repository using existing migrations, artifacts and sessions.

Caller owns the explicit connection; this module never discovers an owner DB.
"""
from hashlib import sha256
import json
from pathlib import Path
from psycopg import sql

from app.storage.store import Store, exact_time
from .records import (SourceRevision, Receipt, QuoteRevision, ReferenceGap, EVENT,
                      packed, wire, unwire, export_records, import_records, validate_bindings, as_of)

TABLES = {SourceRevision: 'reference_source_revision', Receipt: 'reference_receipt',
          QuoteRevision: 'reference_quote_revision', ReferenceGap: 'reference_gap'}


class ReferenceStore:
    def __init__(self, connection):
        self.db = connection
        self.foundation = Store(connection)

    def save(self, record):
        table = TABLES[type(record)]
        body = packed(wire(record))
        row = {'id': record.id, 'payload': body, 'payload_sha256': sha256(body.encode()).hexdigest()}
        with self.db.transaction():
            if isinstance(record, SourceRevision):
                row.update(provider=record.provider, book=record.book, effective_at=record.effective_at, known_at=record.known_at)
            else:
                session = self.db.execute('SELECT evidence_class,environment FROM capture_session WHERE id=%s', (record.session_id,)).fetchone()
                if session != {'evidence_class': 'synthetic', 'environment': 'synthetic'}:
                    raise ValueError('reference implementation requires an explicit synthetic session')
                row['session_id'] = record.session_id
            if isinstance(record, Receipt):
                row.update(native_event_id=EVENT, received_at=record.received_at,
                           raw_hash=self.foundation.raw(record.body))
            if isinstance(record, QuoteRevision):
                dependencies = [self.get(Receipt, record.receipt_id), self.get(SourceRevision, record.source_id), record]
                validate_bindings(dependencies)
                row.update(receipt_id=record.receipt_id, source_id=record.source_id,
                           known_at=record.known_at, effective_at=record.effective_at)
            if isinstance(record, ReferenceGap):
                dependencies = [record]
                if record.receipt_id: dependencies.append(self.get(Receipt, record.receipt_id))
                if record.prior_gap_id:
                    prior = self.get(ReferenceGap, record.prior_gap_id)
                    # Validate direct causal linkage; earlier records were checked on insertion.
                    if prior.session_id != record.session_id or exact_time(prior.detected_at) > exact_time(record.detected_at):
                        raise ValueError('invalid recovery binding')
                if record.receipt_id:
                    if exact_time(dependencies[1].received_at) > exact_time(record.detected_at):
                        raise ValueError('gap precedes receipt')
                row.update(receipt_id=record.receipt_id, prior_gap_id=record.prior_gap_id, detected_at=record.detected_at)
            self.foundation.immutable(table, row, ['id'])

    def get(self, cls, identity):
        row = self.db.execute(sql.SQL('SELECT payload,payload_sha256 FROM {} WHERE id=%s').format(sql.Identifier(TABLES[cls])), (identity,)).fetchone()
        if not row: raise ValueError('missing reference dependency')
        return self._decode(row)

    @staticmethod
    def _decode(row):
        if sha256(row['payload'].encode()).hexdigest() != row['payload_sha256']:
            raise ValueError('durable reference payload hash mismatch')
        return unwire(json.loads(row['payload']))

    def records(self):
        with self.db.transaction():
            self.db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            records = tuple(self._decode(r) for table in TABLES.values() for r in
                self.db.execute(sql.SQL('SELECT payload,payload_sha256 FROM {} ORDER BY id').format(sql.Identifier(table))))
            for r in records:
                if isinstance(r, Receipt):
                    artifact = self.db.execute('SELECT content FROM artifact WHERE hash=%s', (r.body_sha256,)).fetchone()
                    if not artifact or bytes(artifact['content']) != r.body: raise ValueError('raw artifact mismatch')
        validate_bindings(records)
        return records

    def export(self, path):
        text = export_records(self.records())
        Path(path).write_text(text)
        return sha256(text.encode()).hexdigest()

    def restore(self, path):
        records = import_records(Path(path).read_text())
        with self.db.transaction():
            if any(self.db.execute(sql.SQL('SELECT 1 FROM {} LIMIT 1').format(sql.Identifier(t))).fetchone() for t in TABLES.values()):
                raise ValueError('reference restore requires empty reference tables')
            # E2 owns no production session state; recreate explicit synthetic provenance.
            for session_id in sorted({r.session_id for r in records if hasattr(r, 'session_id')}):
                if self.db.execute('SELECT 1 FROM capture_session WHERE id=%s', (session_id,)).fetchone():
                    raise ValueError('restore requires fresh session identities')
                self.foundation.start('synthetic', 'synthetic', 'E2 synthetic reference-bundle-1 restore', session_id=session_id)
            for cls in TABLES:
                rows = [r for r in records if isinstance(r, cls)]
                if cls is ReferenceGap:
                    # Topological order, including equal-clock arrival IDs.
                    done = set()
                    while rows:
                        ready = [r for r in rows if r.prior_gap_id is None or r.prior_gap_id in done]
                        if not ready: raise ValueError('cyclic gap references')
                        for r in ready:
                            self.save(r); done.add(r.id); rows.remove(r)
                else:
                    for r in rows: self.save(r)

    def replay(self, cutoff):
        return as_of(self.records(), cutoff)
