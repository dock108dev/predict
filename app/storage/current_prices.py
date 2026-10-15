"""Exact domain facts + compact two-sided current prices and immutable evidence.

This catalog is independent of bounded expanded active-game calculations. Every
receipt/source clock stays in the immutable revision; rereading identical evidence
is idempotent. No depth levels are dropped by this serializer.
"""
import hashlib
import json
import lzma
from .store import exact_time
from . import domain_delta as delta

MAX_BYTES = 512 * 1024
VENUES = ('kalshi','polymarket_us','novig','prophetx','pinnacle')


def pack(value):
    body = json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    if not body or len(body)>MAX_BYTES:raise ValueError('current_price_payload_capacity')
    compressed = lzma.compress(body,format=lzma.FORMAT_XZ,filters=[dict(id=lzma.FILTER_LZMA2,preset=0,dict_size=1024*1024)])
    small = len(compressed)<len(body)
    return hashlib.sha256(body).digest(), compressed if small else body,len(body),int(small)


def _normal_bytes(identity,payload,logical_bytes,encoding):
    if not isinstance(payload,(bytes,bytearray,memoryview)) or not isinstance(identity,(bytes,bytearray,memoryview)):
        raise ValueError('current_price_payload_missing_or_type')
    payload=bytes(payload);identity=bytes(identity)
    if type(logical_bytes) is not int or not 0<logical_bytes<=MAX_BYTES or len(payload)>MAX_BYTES:raise ValueError('current_price_payload_capacity')
    if encoding==0:
        if payload.startswith(delta.PREFIX.encode('ascii')):raise ValueError('current_price_reference_requires_connection')
        body=payload
    elif encoding==1:
        try:
            decoder=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=16*1024*1024)
            body=decoder.decompress(payload,max_length=logical_bytes+1)
        except lzma.LZMAError as exc:raise ValueError('current_price_encoding_invalid') from exc
        if not decoder.eof or decoder.unused_data:raise ValueError('current_price_stream_invalid')
    else:raise ValueError('current_price_encoding_invalid')
    if len(body)!=logical_bytes or hashlib.sha256(body).digest()!=identity:raise ValueError('current_price_hash_mismatch')
    return body


def unpack(identity,payload,logical_bytes,encoding):
    return json.loads(_normal_bytes(identity,payload,logical_bytes,encoding))


def _revision_row(db,identity):
    return db.execute('''SELECT id,game_id,venue,fact_id,logical_bytes,encoding,
      CASE WHEN octet_length(payload)<=524288 THEN payload ELSE NULL END AS payload
      FROM current_price_revision WHERE id=%s''',(identity,)).fetchone()


def _owned_value(raw,row):
    value=json.loads(raw)
    if not isinstance(value,dict) or value.get('version')!='predict-current-price-revision-1' or value.get('game_fact_sha256')!=bytes(row['fact_id']).hex() or value.get('venue')!=row['venue']:
        raise ValueError('current_price_revision_owner_conflict')
    return value


def _resolved_revision(db,row):
    """One indexed immutable full base; delta-to-delta references are refused."""
    if not row or row['payload'] is None or type(row['logical_bytes']) is not int or not 0<row['logical_bytes']<=MAX_BYTES:
        raise ValueError('current_price_revision_missing_or_capacity')
    payload=bytes(row['payload']);identity=bytes(row['id'])
    if len(payload)>MAX_BYTES:raise ValueError('current_price_payload_capacity')
    if row['encoding']==0 and payload.startswith(delta.PREFIX.encode('ascii')):
        try:aid,size,digest,operations=delta.decode_header(payload.decode('ascii'))
        except (ValueError,UnicodeError) as exc:raise ValueError('current_price_reference_invalid') from exc
        if size!=row['logical_bytes'] or size>MAX_BYTES or digest!=identity.hex() or aid==identity.hex() or len(operations)>MAX_BYTES+65536:
            raise ValueError('current_price_reference_identity_or_capacity')
        base=_revision_row(db,bytes.fromhex(aid))
        if not base or base['payload'] is None:raise ValueError('current_price_base_missing')
        if (base['game_id'],base['venue'],bytes(base['fact_id']))!=(row['game_id'],row['venue'],bytes(row['fact_id'])):
            raise ValueError('current_price_base_owner_conflict')
        if base['encoding']==0 and bytes(base['payload']).startswith(delta.PREFIX.encode('ascii')):
            raise ValueError('current_price_reference_chain_forbidden')
        full=_normal_bytes(base['id'],base['payload'],base['logical_bytes'],base['encoding']);_owned_value(full,base)
        raw=delta.restore_parts((aid,size,digest,operations),full)
        return raw,bytes(base['id']),full,_owned_value(raw,row)
    raw=_normal_bytes(row['id'],payload,row['logical_bytes'],row['encoding'])
    return raw,identity,raw,_owned_value(raw,row)


def prepare(game,venue,sides,evidence):
    """Shared ordinary/bulk serialization. Native identity and clocks are exact."""
    if venue not in VENUES:raise ValueError('current_price_venue_invalid')
    if not isinstance(game,dict) or not isinstance(game.get('game_key'),str) or not game['game_key']:raise ValueError('current_price_game_key_required')
    if not isinstance(sides,(list,tuple)) or len(sides)!=2:raise ValueError('current_price_two_sides_required')
    if not isinstance(evidence,dict) or not evidence.get('received_at'):raise ValueError('current_price_receipt_required')
    received=exact_time(evidence['received_at']);source=exact_time(evidence.get('source_at') or evidence['received_at'])
    fact=pack(game)
    revision=pack(dict(version='predict-current-price-revision-1',game_fact_sha256=fact[0].hex(),venue=venue,sides=sides,evidence=evidence))
    return dict(game=game['game_key'],venue=venue,fact=fact,revision=revision,source_order=source,received_order=received)


class CurrentPriceStore:
    def __init__(self,db):self.db=db

    def upsert(self,game,venue,sides,evidence):
        p=prepare(game,venue,sides,evidence);fid,body,size,encoding=p['fact'];rid,rbody,rsize,rencoding=p['revision']
        with self.db.transaction():
            self.db.execute('INSERT INTO current_price_game_fact VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',(fid,body,size,encoding))
            fact=self.db.execute('''SELECT id,logical_bytes,encoding,CASE WHEN octet_length(payload)<=524288 THEN payload ELSE NULL END AS payload
              FROM current_price_game_fact WHERE id=%s''',(fid,)).fetchone()
            if not fact or fact['payload'] is None or fact['logical_bytes']!=size or unpack(fact['id'],fact['payload'],fact['logical_bytes'],fact['encoding'])!=game:
                raise ValueError('current_price_fact_publication_conflict')
            self.db.execute('''INSERT INTO current_price_game (game_key,fact_id,received_order) VALUES (%s,%s,%s) ON CONFLICT(game_key) DO UPDATE
              SET fact_id=excluded.fact_id,received_order=excluded.received_order
              WHERE excluded.received_order>current_price_game.received_order''',(p['game'],fid,p['received_order']))
            game_id=self.db.execute('SELECT id FROM current_price_game WHERE game_key=%s',(p['game'],)).fetchone()['id']
            old=self.db.execute('SELECT revision_id,source_order,received_order FROM current_price_latest WHERE game_id=%s AND venue=%s FOR UPDATE',(game_id,venue)).fetchone()
            if old and (old['source_order'],old['received_order'])==(p['source_order'],p['received_order']) and bytes(old['revision_id'])!=rid:
                raise ValueError('current_price_equal_clock_conflict')
            if old:
                prior=_revision_row(self.db,old['revision_id'])
                if not prior or (prior['game_id'],prior['venue'])!=(game_id,venue):raise ValueError('current_price_latest_reference_conflict')
                _,base_id,base_raw,_=_resolved_revision(self.db,prior)
                if bytes(prior['fact_id'])==fid and bytes(prior['id'])!=rid:
                    raw=_normal_bytes(rid,rbody,rsize,rencoding)
                    reference=delta.encode_header(base_id.hex(),raw,delta.make_delta(base_raw,raw)).encode('ascii')
                    if len(reference)<len(rbody):rbody=reference;rencoding=0
            added=self.db.execute('''INSERT INTO current_price_revision VALUES (%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT DO NOTHING RETURNING id''',(rid,game_id,venue,fid,rbody,rsize,rencoding)).fetchone() is not None
            revision=_revision_row(self.db,rid)
            if not revision or revision['payload'] is None or revision['game_id']!=game_id or revision['venue']!=venue or bytes(revision['fact_id'])!=fid or revision['logical_bytes']!=rsize:
                raise ValueError('current_price_revision_publication_conflict')
            restored=_resolved_revision(self.db,revision)[3]
            if restored!=dict(version='predict-current-price-revision-1',game_fact_sha256=fid.hex(),venue=venue,sides=sides,evidence=evidence):
                raise ValueError('current_price_revision_publication_conflict')
            self.db.execute('''INSERT INTO current_price_latest VALUES (%s,%s,%s,%s,%s)
              ON CONFLICT(game_id,venue) DO UPDATE SET revision_id=excluded.revision_id,
              source_order=excluded.source_order,received_order=excluded.received_order
              WHERE (excluded.source_order,excluded.received_order)>(current_price_latest.source_order,current_price_latest.received_order)''',
              (game_id,venue,rid,p['source_order'],p['received_order']))
        return dict(revision_id=rid.hex(),fact_id=fid.hex(),revision_added=added)

    def current(self,game_key,venue):
        row=self.db.execute('''SELECT r.id,r.game_id,r.venue,CASE WHEN octet_length(r.payload)<=524288 THEN r.payload ELSE NULL END AS payload,r.logical_bytes,r.encoding,f.id AS fact_id,
          CASE WHEN octet_length(f.payload)<=524288 THEN f.payload ELSE NULL END AS fact_payload,f.logical_bytes AS fact_bytes,f.encoding AS fact_encoding
          FROM current_price_latest l JOIN current_price_revision r ON r.id=l.revision_id
          JOIN current_price_game_fact f ON f.id=r.fact_id
          JOIN current_price_game g ON g.id=l.game_id WHERE g.game_key=%s AND l.venue=%s''',(game_key,venue)).fetchone()
        if not row:
            pointer=self.db.execute('''SELECT 1 FROM current_price_latest l JOIN current_price_game g ON g.id=l.game_id WHERE g.game_key=%s AND l.venue=%s''',(game_key,venue)).fetchone()
            if pointer:raise ValueError('current_price_latest_reference_missing')
            return None
        value=_resolved_revision(self.db,row)[3]
        if value.get('game_fact_sha256')!=bytes(row['fact_id']).hex():raise ValueError('current_price_fact_reference_conflict')
        value['game']=unpack(row['fact_id'],row['fact_payload'],row['fact_bytes'],row['fact_encoding'])
        if value['game'].get('game_key')!=game_key or value.get('venue')!=venue:raise ValueError('current_price_latest_reference_conflict')
        return value

    def revision(self,revision_id):
        try:identity=bytes.fromhex(revision_id)
        except (TypeError,ValueError) as exc:raise ValueError('current_price_revision_identity_invalid') from exc
        if len(identity)!=32:raise ValueError('current_price_revision_identity_invalid')
        row=self.db.execute('''SELECT r.id,r.game_id,r.venue,CASE WHEN octet_length(r.payload)<=524288 THEN r.payload ELSE NULL END AS payload,r.logical_bytes,r.encoding,f.id AS fact_id,
          CASE WHEN octet_length(f.payload)<=524288 THEN f.payload ELSE NULL END AS fact_payload,f.logical_bytes AS fact_bytes,f.encoding AS fact_encoding
          FROM current_price_revision r JOIN current_price_game_fact f ON f.id=r.fact_id WHERE r.id=%s''',(identity,)).fetchone()
        if not row:raise ValueError('current_price_revision_missing')
        value=_resolved_revision(self.db,row)[3]
        if value.get('game_fact_sha256')!=bytes(row['fact_id']).hex():raise ValueError('current_price_fact_reference_conflict')
        value['game']=unpack(row['fact_id'],row['fact_payload'],row['fact_bytes'],row['fact_encoding'])
        return value
