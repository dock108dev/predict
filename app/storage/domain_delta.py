"""Bounded exact byte deltas against immutable, domain-owned evidence anchors.

Anchors are owned by SQL/journal adapters. This module has no I/O or clock owner.
Delta copies refer to exact original byte ranges, never to today's financial model.
"""
import base64
from hashlib import sha256
import json
import lzma
import re
import struct
from bisect import bisect_left

PREFIX='predict-domain-delta-1:'
MAX_BYTES=8*1024*1024
MAX_OPERATIONS=262144
FILTERS=[dict(id=lzma.FILTER_LZMA2,preset=0,dict_size=1024*1024)]
BOUNDARY=re.compile(rb'[}\]],')

def compress(raw):
    if not isinstance(raw,bytes) or len(raw)>MAX_BYTES+1024*1024:raise ValueError('domain_byte_capacity')
    return lzma.compress(raw,format=lzma.FORMAT_XZ,filters=FILTERS)

def decompress(body,max_bytes=MAX_BYTES):
    if not isinstance(body,bytes) or len(body)>MAX_BYTES+1024*1024:raise ValueError('domain_encoded_capacity')
    try:
        reader=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=16*1024*1024)
        raw=reader.decompress(body,max_bytes+1)
        if len(raw)>max_bytes or not reader.eof or reader.unused_data:raise ValueError('domain_stream_capacity_or_trailing')
        return raw
    except lzma.LZMAError as exc:raise ValueError('domain_encoding_invalid') from exc

def chunks(raw):
    start=0
    for match in BOUNDARY.finditer(raw):
        end=match.end()
        if end-start>=64:
            # One field containing a huge raw base64 string remains bounded too.
            while end-start>16384:
                yield start,start+8192;start+=8192
            yield start,end;start=end
    while len(raw)-start>16384:
        yield start,start+8192;start+=8192
    if start<len(raw):yield start,len(raw)

def make_delta(base,raw):
    if max(len(base),len(raw))>MAX_BYTES:raise ValueError('domain_logical_capacity')
    # Index content windows at JSON lexical boundaries. Positions, lengths and
    # spelling remain byte-exact even for punctuation inside string values.
    # Matching does not depend on whole-object hashes or a clock field's offset.
    width=64;index={}
    boundaries=re.compile(rb'[{}\[\],:]')
    for position in [0]+[m.end() for m in boundaries.finditer(base)]:
        if position+width>len(base):continue
        key=sha256(base[position:position+width]).digest()
        prior=index.get(key)
        if prior is None:index[key]=(position,)
        elif len(prior)==1:index[key]=(prior[0],position)
        else:index[key]=(prior[0],position)
    points=[0]+[m.end() for m in boundaries.finditer(raw)]
    ops=[];literal_start=0;point_index=0;position=0
    while point_index<len(points):
        position=points[point_index];point_index+=1
        if position+width>len(raw):break
        candidates=index.get(sha256(raw[position:position+width]).digest(),())
        best=None
        for start in candidates:
            if base[start:start+width]!=raw[position:position+width]:continue
            maximum=min(len(base)-start,len(raw)-position,262144)
            low=width;high=maximum+1
            while low+1<high:
                middle=(low+high)//2
                if base[start:start+middle]==raw[position:position+middle]:low=middle
                else:high=middle
            if best is None or low>best[1]:best=(start,low)
        if best:
            if literal_start<position:
                part=raw[literal_start:position];ops.append(b'L'+struct.pack('>I',len(part))+part)
            ops.append(b'C'+struct.pack('>II',*best))
            position+=best[1];literal_start=position
            point_index=bisect_left(points,position,point_index)
    if literal_start<len(raw):
        part=raw[literal_start:];ops.append(b'L'+struct.pack('>I',len(part))+part)
    if len(ops)>MAX_OPERATIONS:raise ValueError('domain_operation_capacity')
    return b''.join(ops)

def apply_delta(base,delta,size):
    if type(size) is not int or not 0<=size<=MAX_BYTES or len(base)>MAX_BYTES:raise ValueError('domain_logical_capacity')
    result=bytearray();offset=0;operations=0
    while offset<len(delta):
        operations+=1
        if operations>MAX_OPERATIONS:raise ValueError('domain_operation_capacity')
        opcode=delta[offset:offset+1];offset+=1
        if opcode==b'C':
            if offset+8>len(delta):raise ValueError('domain_delta_truncated')
            start,length=struct.unpack_from('>II',delta,offset);offset+=8
            if start+length>len(base) or length==0:raise ValueError('domain_copy_range')
            part=base[start:start+length]
        elif opcode==b'L':
            if offset+4>len(delta):raise ValueError('domain_delta_truncated')
            length=struct.unpack_from('>I',delta,offset)[0];offset+=4
            if offset+length>len(delta) or length==0:raise ValueError('domain_literal_range')
            part=delta[offset:offset+length];offset+=length
        else:raise ValueError('domain_delta_opcode')
        if len(result)+len(part)>size:raise ValueError('domain_expansion_capacity')
        result.extend(part)
    if len(result)!=size:raise ValueError('domain_length_mismatch')
    return bytes(result)

def encode_header(base_id,raw,delta):
    if not re.fullmatch('[0-9a-f]{64}',base_id) or len(raw)>MAX_BYTES:raise ValueError('domain_identity_or_capacity')
    body=base64.b64encode(compress(delta)).decode() if delta else ''
    return PREFIX+str(len(raw))+':'+sha256(raw).hexdigest()+':'+base_id+':'+body

def decode_header(value):
    if not isinstance(value,str) or not value.startswith(PREFIX) or len(value)>12*1024*1024:raise ValueError('domain_header_invalid')
    parts=value[len(PREFIX):].split(':',3)
    if len(parts)!=4 or not re.fullmatch('[0-9]{1,8}',parts[0]) or not all(re.fullmatch('[0-9a-f]{64}',s) for s in parts[1:3]):raise ValueError('domain_header_invalid')
    size=int(parts[0])
    if size>MAX_BYTES:raise ValueError('domain_logical_capacity')
    try:delta=decompress(base64.b64decode(parts[3],validate=True),MAX_BYTES+1024*1024) if parts[3] else b''
    except (ValueError,TypeError) as exc:raise ValueError('domain_delta_encoding_invalid') from exc
    return parts[2],size,parts[1],delta

def restore(value,base):
    return restore_parts(decode_header(value),base)

def restore_parts(parts,base):
    base_id,size,digest,delta=parts
    if sha256(base).hexdigest()!=base_id:raise ValueError('domain_anchor_hash_mismatch')
    raw=apply_delta(base,delta,size) if delta else base
    if len(raw)!=size or sha256(raw).hexdigest()!=digest:raise ValueError('domain_payload_hash_mismatch')
    return raw

def scope_for_record(record):
    """Exact source/instrument ownership; clocks stay in the retained revision."""
    source=record.get('source','unknown');kind=record.get('kind','unknown');value=record.get('value',{})
    refs=[]
    if kind=='admitted_books':
        for item in value.get('observations',[]):
            ref=item.get('book',{}).get('raw',{}).get('ref',{})
            refs.append([ref.get('event_id'),ref.get('market_id')])
    elif kind=='aggregate_batch':refs=[value.get('sport')]
    return json.dumps(['observation',source,kind,sorted(refs,key=str)],sort_keys=True,separators=(',',':'))
