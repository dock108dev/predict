"""Scoped original aggregate receipts used by acquisition and diagnostics."""

from psycopg.types.json import Jsonb


def save(db, *, kind, sport, received_at, payload, event_id='', cycle_id=None,
         receipt_sha256=None, disposition=None):
    """Replace a source scope with its latest accepted original receipt."""
    db.execute('''INSERT INTO acquisition_receipt AS receipt
        (source,kind,scope,event_id,received_at,cycle_id,receipt_sha256,disposition,payload)
        VALUES ('the_odds_api',%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (kind,source,scope,event_id,position) DO UPDATE SET
            received_at=excluded.received_at,cycle_id=excluded.cycle_id,
            receipt_sha256=excluded.receipt_sha256,disposition=excluded.disposition,payload=excluded.payload
        WHERE receipt.kind='census' OR receipt.received_at<=excluded.received_at''',
        (kind,sport,event_id,received_at,cycle_id,receipt_sha256,disposition,Jsonb(payload)))


def expire_alternates(db, *, sport, event_census):
    db.execute('''DELETE FROM acquisition_receipt AS receipt
        WHERE source='the_odds_api' AND kind='alternate' AND scope=%s AND received_at<now()-interval '2 days'
        AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(%s::jsonb) e WHERE e->>'id'=receipt.event_id)''',
        (sport,Jsonb(event_census)))
