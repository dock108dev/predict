"""Immutable domain-owned frame anchors + globally shared exact semantic facts.

V1 byte-anchor readers remain compatible. V2 facts are raw canonical JSON in the
same immutable anchor table, never references to other facts or current models.
"""
from hashlib import sha256
import json
from . import domain_delta as delta
from . import domain_frame as frame

FRAME_PREFIX=frame.FRAME_PREFIX


def scope(value,table=''):
    v=json.loads(value)
    if isinstance(v,dict) and 'source' in v and 'kind' in v:return delta.scope_for_record(v)
    if isinstance(v,dict):
        policy=v.get('policy');revision=policy.get('revision') if isinstance(policy,dict) else None
        return json.dumps([table,v.get('game_key'),revision,v.get('engine_binding')],separators=(',',':'))
    return table


def anchor(db,identity):
    if not isinstance(identity,str) or len(identity)!=64:
        raise ValueError('current_domain_anchor_identity_invalid')
    try:binary=bytes.fromhex(identity)
    except ValueError as exc:raise ValueError('current_domain_anchor_identity_invalid') from exc
    row=db.execute('''SELECT logical_bytes,CASE WHEN octet_length(content)<=9437184
      THEN content ELSE NULL END AS content FROM current_domain_anchor WHERE id=%s''',(binary,)).fetchone()
    if not row:raise ValueError('current_domain_anchor_missing')
    if type(row['logical_bytes']) is not int or not 0<=row['logical_bytes']<=delta.MAX_BYTES or row['content'] is None:
        raise ValueError('current_domain_anchor_capacity')
    raw=delta.decompress(bytes(row['content']),row['logical_bytes'])
    if len(raw)!=row['logical_bytes'] or sha256(raw).hexdigest()!=identity:raise ValueError('current_domain_anchor_corrupt')
    return raw


def _facts(db,sizes):
    if not sizes:return {}
    ids=[bytes.fromhex(key) for key in sizes]
    rows=db.execute('''SELECT id,logical_bytes,octet_length(content) AS encoded_bytes
      FROM current_domain_anchor WHERE id=ANY(%s::bytea[])''',(ids,)).fetchall()
    found={};encoded=0;logical=0
    for row in rows:
        identity=bytes(row['id']).hex()
        if identity in found or identity not in sizes or row['logical_bytes']!=sizes[identity] or type(row['encoded_bytes']) is not int or not 0<row['encoded_bytes']<=delta.MAX_BYTES+1024*1024:
            raise ValueError('current_domain_fact_metadata_corrupt')
        found[identity]=row['logical_bytes'];encoded+=row['encoded_bytes'];logical+=row['logical_bytes']
    if set(found)!=set(sizes):raise ValueError('current_domain_fact_missing')
    if max(encoded,logical)>frame.MAX_TOTAL_BYTES:raise ValueError('current_domain_fact_capacity')
    # Metadata is checked first so corrupt oversized rows never enter Python.
    rows=db.execute('''SELECT id,logical_bytes,CASE WHEN octet_length(content)<=9437184
      THEN content ELSE NULL END AS content FROM current_domain_anchor WHERE id=ANY(%s::bytea[])''',(ids,)).fetchall()
    facts={};total=0
    for row in rows:
        identity=bytes(row['id']).hex()
        if identity not in found or identity in facts or row['logical_bytes']!=found[identity] or row['content'] is None:
            raise ValueError('current_domain_fact_corrupt')
        content=bytes(row['content']);total+=len(content)
        if total>frame.MAX_TOTAL_BYTES:raise ValueError('current_domain_fact_capacity')
        body=delta.decompress(content,found[identity])
        if len(body)!=found[identity] or sha256(body).hexdigest()!=identity:raise ValueError('current_domain_fact_corrupt')
        # Expansion performs the canonical/depth JSON parse once, after all
        # referenced byte hashes and lengths have been checked here.
        facts[identity]=body
    if set(facts)!=set(sizes):raise ValueError('current_domain_fact_missing')
    return facts


def _put_facts(db,facts):
    if not facts:return
    ids=[];sizes=[];contents=[]
    for identity,body in facts.items():
        ids.append(bytes.fromhex(identity));sizes.append(len(body));contents.append(delta.compress(body))
    db.execute('''INSERT INTO current_domain_anchor(id,logical_bytes,content)
      SELECT * FROM unnest(%s::bytea[],%s::integer[],%s::bytea[]) ON CONFLICT DO NOTHING''',(ids,sizes,contents))
    saved=_facts(db,{key:len(body) for key,body in facts.items()})
    if saved!=facts:raise ValueError('current_domain_fact_identity_conflict')


def decode(value,db):
    if isinstance(value,str) and value.startswith(FRAME_PREFIX):
        aid,size,digest,frame_size,operations=frame.decode_header(value)
        base=anchor(db,aid)
        raw=delta.apply_delta(base,operations,frame_size) if operations else base
        if len(raw)!=frame_size:raise ValueError('domain_frame_length_mismatch')
        validated=frame.descriptor(raw)
        return frame._expand_from_descriptor(validated,_facts(db,validated[1]),size,digest).decode('utf-8')
    parts=delta.decode_header(value)
    return delta.restore_parts(parts,anchor(db,parts[0])).decode('utf-8')


def _legacy_encode(value,db,table=''):
    raw=value.encode('utf-8')
    key=sha256(scope(value,table).encode()).digest()
    head=db.execute('SELECT anchor_id FROM current_domain_head WHERE scope=%s',(key,)).fetchone()
    if head:
        aid=bytes(head['anchor_id']).hex();base=anchor(db,aid)
        if raw==base:return delta.encode_header(aid,raw,b'')
        if frame.delta_safe(base,raw):
            changes=delta.make_delta(base,raw);encoded=delta.encode_header(aid,raw,changes)
            if len(encoded)<len(raw)//2 and len(encoded)<len(delta.compress(raw))*1.5+200:return encoded
    aid=sha256(raw).digest()
    db.execute('INSERT INTO current_domain_anchor VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(aid,len(raw),delta.compress(raw)))
    if anchor(db,aid.hex())!=raw:raise ValueError('current_domain_anchor_identity_conflict')
    db.execute('''INSERT INTO current_domain_head VALUES (%s,%s) ON CONFLICT(scope)
      DO UPDATE SET anchor_id=excluded.anchor_id''',(key,aid))
    return delta.encode_header(aid.hex(),raw,b'')


def encode(value,db,table=''):
    raw=value.encode('utf-8')
    if len(raw)>delta.MAX_BYTES:raise ValueError('current_domain_logical_capacity')
    if len(raw)<512:return value
    if table=='current_envelope':
        record=json.loads(value)
        # Aggregate bodies are exact base64 and books own dynamic depth/clocks.
        # Their v1 source/instrument anchors already share the retained frame.
        if isinstance(record,dict) and record.get('kind')!='catalog':return _legacy_encode(value,db,table)
    extracted=frame.extract(raw)
    if extracted is None:return _legacy_encode(value,db,table)
    target,facts=extracted
    # The separate namespace prevents a legacy raw anchor being used as a frame.
    key=sha256(('frame2:'+scope(value,table)).encode()).digest()
    _put_facts(db,facts)
    head=db.execute('SELECT anchor_id FROM current_domain_head WHERE scope=%s',(key,)).fetchone()
    if head:
        aid=bytes(head['anchor_id']).hex();base=anchor(db,aid);frame.descriptor(base)
        if target==base:return frame.encode_header(aid,raw,len(target),b'')
        if frame.delta_safe(base,target):
            operations=delta.make_delta(base,target)
            packed=frame.encode_header(aid,raw,len(target),operations)
            if len(packed)<len(target)//2 and len(packed)<len(delta.compress(target))*1.5+200:return packed
    aid=sha256(target).digest()
    db.execute('INSERT INTO current_domain_anchor VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(aid,len(target),delta.compress(target)))
    if anchor(db,aid.hex())!=target:raise ValueError('current_domain_anchor_identity_conflict')
    db.execute('''INSERT INTO current_domain_head VALUES (%s,%s) ON CONFLICT(scope)
      DO UPDATE SET anchor_id=excluded.anchor_id''',(key,aid))
    return frame.encode_header(aid.hex(),raw,len(target),b'')
