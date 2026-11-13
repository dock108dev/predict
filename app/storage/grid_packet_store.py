"""Immutable published evidence, pinned only by bounded ordinary-read leases."""
from hashlib import sha256
from contextlib import contextmanager
import psycopg
from psycopg.types.json import Jsonb
from .store import encoded
from .payload_codec import payload_row

# A snapshot capture is bounded to 60 seconds; its first pin must fit inside
# this grace after a current packet is superseded. Active leases then own it.
GRACE_SECONDS=180

def identity(packet):return sha256(packet).hexdigest()

def retained_bytes(db):
    return db.execute('SELECT COALESCE(sum(retained_bytes),0) n FROM current_grid_blob').fetchone()['n']

def extra_bytes(db,packets):
    values={identity(p):p for p in packets}
    present={r['id'] for r in db.execute('SELECT id FROM current_grid_blob WHERE id=ANY(%s)',(list(values),))}
    return sum(len(p) for key,p in values.items() if key not in present)

def put(db,packet):
    key=identity(packet)
    db.execute('INSERT INTO current_grid_blob(id,packet,unreferenced_at) VALUES (%s,%s,clock_timestamp()) ON CONFLICT(id) DO NOTHING',(key,packet))
    return key

def cleanup(db):
    # Serialize lease creation against deletion on the immutable packet itself.
    # A single DELETE snapshot can miss a lease committed while waiting for its
    # row lock. Lock candidates first, then check leases in a fresh statement.
    with db.transaction():
        db.execute('DELETE FROM current_grid_read_lease WHERE expires_at<clock_timestamp()')
        candidates=[r['id'] for r in db.execute("""SELECT b.id FROM current_grid_blob b
            WHERE b.unreferenced_at<clock_timestamp()-interval '180 seconds'
            AND NOT EXISTS(SELECT 1 FROM current_grid_projection g WHERE g.blob_id=b.id)
            AND NOT EXISTS(SELECT 1 FROM current_result_unit u WHERE u.original_blob_id=b.id)
            AND NOT EXISTS(SELECT 1 FROM current_result_parent_original p WHERE p.blob_id=b.id)
            ORDER BY b.unreferenced_at,b.id LIMIT 128 FOR UPDATE OF b SKIP LOCKED""")]
        if candidates:
            db.execute("""DELETE FROM current_grid_blob b WHERE b.id=ANY(%s)
                AND NOT EXISTS(SELECT 1 FROM current_grid_projection g WHERE g.blob_id=b.id)
            AND NOT EXISTS(SELECT 1 FROM current_result_unit u WHERE u.original_blob_id=b.id)
            AND NOT EXISTS(SELECT 1 FROM current_result_parent_original p WHERE p.blob_id=b.id)
                AND NOT EXISTS(SELECT 1 FROM current_grid_read_lease l WHERE l.packet_ids @> ARRAY[b.id])""",(candidates,))


class PacketStore:
    def __init__(self,parameters,*,retained=False):self.parameters=parameters;self.retained=retained
    @classmethod
    def from_connection(cls,db):
        schema=db.execute('SELECT current_schemas(false) AS names').fetchone()['names']
        return cls(db.info.get_parameters(),retained='retained' in schema)
    @contextmanager
    def connection(self):
        with psycopg.connect(**dict(self.parameters,connect_timeout=5),autocommit=True,row_factory=payload_row) as db:
            if self.retained:
                from .store import open_retained
                open_retained(db)
            db.execute("SET statement_timeout='5s'")
            yield db
    def load(self,key):
        with self.connection() as db:
            row=db.execute('SELECT packet FROM current_grid_blob WHERE id=%s',(key,)).fetchone()
        if row is None:raise ValueError('current_slate_read_expired')
        return bytes(row['packet'])
    def pin(self,token,keys,seconds):
        keys=sorted(set(keys))
        with self.connection() as db,db.transaction():
            found=db.execute('SELECT id FROM current_grid_blob WHERE id=ANY(%s) FOR KEY SHARE',(keys,)).fetchall()
            if len(found)!=len(keys):raise ValueError('current_slate_read_expired')
            db.execute('''INSERT INTO current_grid_read_lease VALUES (%s,clock_timestamp()+%s*interval '1 second',%s)
                ON CONFLICT(token) DO UPDATE SET expires_at=EXCLUDED.expires_at,packet_ids=EXCLUDED.packet_ids''',(token,seconds,keys))
    def renew(self,token,seconds):
        with self.connection() as db:
            if db.execute("UPDATE current_grid_read_lease SET expires_at=clock_timestamp()+%s*interval '1 second' WHERE token=%s AND expires_at>=clock_timestamp()",(seconds,token)).rowcount!=1:
                raise ValueError('current_slate_read_expired')
    def release(self,token):
        # An interrupted cache cleanup cannot extend the SQL lease's deadline.
        try:
            with self.connection() as db:db.execute('DELETE FROM current_grid_read_lease WHERE token=%s',(token,))
        except psycopg.Error:pass
