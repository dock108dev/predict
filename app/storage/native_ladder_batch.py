"""Immutable ladder bodies shared by native book revisions."""
from hashlib import sha256
import json

from psycopg.types.json import Jsonb

from .store import encoded


class LadderBatch:
    def __init__(self, execute):
        self.execute = execute
        self.pending = {}
        self.size = 0

    def append(self, ladders):
        refs = {}
        for (outcome, side), levels in ladders.items():
            # A ladder is an array of text. This matches PostgreSQL's jsonb
            # text spelling, including spaces after separators and literal UTF-8.
            identity = sha256(json.dumps(levels, ensure_ascii=False).encode()).hexdigest()
            refs.setdefault(outcome, {})[side] = identity
            if identity not in self.pending:
                row = dict(id=identity, levels=levels)
                size = len(encoded(row))
                if self.pending and self.size + size > 32768:
                    self.flush()
                self.pending[identity] = row
                self.size += size
        return refs

    def flush(self):
        if not self.pending:
            return
        self.execute('''INSERT INTO native_ladder_revision (id,levels)
            SELECT * FROM jsonb_to_recordset(%s) AS d(id text,levels jsonb)
            ON CONFLICT(id) DO NOTHING''', (Jsonb(list(self.pending.values())),), synchronous=True)
        self.pending.clear()
        self.size = 0


def prune(execute, *, limit=256, book_ids=None):
    """Release only unreferenced revisions, under the caller's current writer lock."""
    books = execute('''SELECT b.id,b.ladder_ids FROM native_book_revision b WHERE NOT b.is_current
          AND (%s::text[] IS NULL OR b.id=ANY(%s)) AND NOT EXISTS (
            SELECT 1 FROM current_offer_storage o WHERE o.native_book_id=b.id)
        ORDER BY b.id LIMIT %s''', (book_ids,book_ids,limit)).fetchall()
    if books:
        execute('DELETE FROM native_book_revision WHERE id=ANY(%s)', ([row['id'] for row in books],))
    ladder_ids = None
    if book_ids is not None:
        ladder_ids = sorted({id_ for book in books for id_ in book['ladder_ids']})
    if ladder_ids == []:
        return dict(books=len(books),ladders=0)
    ladders = execute('''WITH expired AS (
        SELECT d.id FROM native_ladder_revision d WHERE (%s::text[] IS NULL OR d.id=ANY(%s))
          AND NOT EXISTS (
            SELECT 1 FROM native_book_revision b WHERE b.ladder_ids @> ARRAY[d.id])
        ORDER BY d.id LIMIT %s)
        DELETE FROM native_ladder_revision d USING expired WHERE d.id=expired.id''',
        (ladder_ids,ladder_ids,limit * 4),synchronous=True).rowcount
    return dict(books=len(books),ladders=ladders)
