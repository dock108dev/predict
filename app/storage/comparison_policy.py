"""One active live settings revision, independent of saved comparisons."""

from psycopg.types.json import Jsonb

from app.comparison.snapshot_math import assumptions
from .comparison_snapshot import SnapshotOperationError


def read(db):
    row = db.execute(
        'SELECT assumptions FROM comparison_policy_revision WHERE active'
    ).fetchone()
    return row['assumptions'] if row else assumptions()[0]


def remember(db, value):
    revision = value['revision']
    existing = db.execute(
        'SELECT assumptions FROM comparison_policy_revision WHERE id=%s', (revision,)
    ).fetchone()
    if existing is None:
        # A settings change and a publication can discover the same new
        # revision independently. Check its bytes after the insert race.
        db.execute('''INSERT INTO comparison_policy_revision (id, assumptions)
            VALUES (%s,%s) ON CONFLICT (id) DO NOTHING''', (revision, Jsonb(value)))
        existing = db.execute(
            'SELECT assumptions FROM comparison_policy_revision WHERE id=%s', (revision,)
        ).fetchone()
    if existing['assumptions'] != value:
        raise SnapshotOperationError('Settings revision conflicts with stored assumptions')
    return revision


def activate(db, value, *, expected):
    value = assumptions(value)[0]
    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(901155)')
        if read(db)['revision'] != expected:
            raise SnapshotOperationError('Settings changed; reload before applying')
        remember(db, value)
        db.execute('UPDATE comparison_policy_revision SET active=false WHERE active AND id<>%s',
                   (value['revision'],))
        db.execute('UPDATE comparison_policy_revision SET active=true WHERE id=%s AND NOT active',
                   (value['revision'],))
    return value
