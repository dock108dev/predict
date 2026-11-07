"""Bounded writes of disjoint side replacements inside the native book transaction."""
from psycopg.types.json import Jsonb
from .store import encoded


class LadderBatch:
    def __init__(self,execute):
        self.execute=execute
        self.keys=set()
        self.sides=[]
        self.size=0

    def append(self,key,ladders):
        # A repeated book is an order barrier even inside the same transaction.
        if key in self.keys or len(self.keys)>=32:
            self.flush()
        self.keys.add(key)
        # Exact leading-key predicates prune partitions and use the ladder PK.
        # Joining the roster as JSON made PostgreSQL scan the entire live owner.
        self.execute('DELETE FROM current_native_ladder WHERE venue=%s AND event_id=%s AND native_market_id=%s '
            'AND NOT ((native_outcome_id,side) IN (SELECT * FROM unnest(%s::text[],%s::text[])))',
            (*key,[outcome for outcome,_ in ladders],[side for _,side in ladders]))
        venue,event,market=key
        for (outcome,side),levels in ladders.items():
            row=dict(venue=venue,event_id=event,native_market_id=market,
                     native_outcome_id=outcome,side=side,levels=levels)
            size=len(encoded(row))+1
            if self.sides and self.size+size>32768:
                self.write_sides()
            self.sides.append(row)
            self.size+=size
            # An oversized individual side is one complete protocol message.
            if self.size>=32768:
                self.write_sides()

    def write_sides(self):
        if self.sides:
            self.execute("""INSERT INTO current_native_ladder
                SELECT * FROM jsonb_to_recordset(%s) AS x(venue text,event_id text,native_market_id text,
                    native_outcome_id text,side text,levels jsonb)
                ON CONFLICT (venue,event_id,native_market_id,native_outcome_id,side)
                DO UPDATE SET levels=excluded.levels WHERE current_native_ladder.levels IS DISTINCT FROM excluded.levels""",
                (Jsonb(self.sides),),synchronous=True)
            self.sides=[]
            self.size=0

    def flush(self):
        self.write_sides()
        self.keys.clear()
