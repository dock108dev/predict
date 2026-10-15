"""Exact domain fact frames. Only named semantic slots are shared; no ref chains."""
import base64
from hashlib import sha256
import json
import re
import struct
from . import domain_delta as delta

FRAME_PREFIX='predict-domain-frame-2:'
MAX_REFS=2048
MAX_TOTAL_BYTES=16*1024*1024
MAX_DEPTH=64
MAX_NODES=262144
MAX_FRAME_BYTES=delta.MAX_BYTES


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')


def check_depth(raw,maximum=MAX_DEPTH):
    depth=0;quoted=False;escaped=False
    for char in raw:
        if quoted:
            if escaped:escaped=False
            elif char==92:escaped=True
            elif char==34:quoted=False
        elif char==34:quoted=True
        elif char in (123,91):
            depth+=1
            if depth>maximum:raise ValueError('domain_frame_depth_capacity')
        elif char in (125,93):depth-=1
    if quoted or depth!=0:raise ValueError('domain_frame_json_invalid')


def node_count(value):
    pending=[value];count=0
    while pending:
        item=pending.pop();count+=1
        if isinstance(item,dict):
            count+=len(item)
            if count+len(pending)+len(item)>MAX_NODES:raise ValueError('domain_frame_node_capacity')
            pending.extend(item.values())
        elif isinstance(item,list):
            if count+len(pending)+len(item)>MAX_NODES:raise ValueError('domain_frame_node_capacity')
            pending.extend(item)
        if count>MAX_NODES:raise ValueError('domain_frame_node_capacity')
    return count


def parse(raw,maximum=delta.MAX_BYTES,depth_limit=MAX_DEPTH):
    if not isinstance(raw,bytes) or len(raw)>maximum:raise ValueError('domain_frame_byte_capacity')
    check_depth(raw,depth_limit)
    try:
        value=json.loads(raw)
        node_count(value)
        if canonical(value)!=raw:raise ValueError('domain_frame_noncanonical')
    except (UnicodeError,RecursionError,TypeError,OverflowError,json.JSONDecodeError) as exc:
        raise ValueError('domain_frame_json_invalid') from exc
    return value


def event_metadata(value):
    return isinstance(value,dict) and 'groups' not in value and bool(set(value)&{'participants','scheduled_start','competition','title','home','away','sport'})


def extract(raw):
    """Return canonical frame and raw facts, or None for noncanonical legacy text."""
    try:root=parse(raw)
    except ValueError as exc:
        if str(exc)=='domain_frame_noncanonical':return None
        raise
    facts={};refs=[];expanded=0
    def fact(value,path):
        nonlocal expanded
        body=canonical(value);identity=sha256(body).hexdigest()
        refs.append([list(path),identity,len(body)]);expanded+=len(body)
        if len(refs)>MAX_REFS or expanded>MAX_TOTAL_BYTES:raise ValueError('domain_frame_fact_capacity')
        facts[identity]=body
        return None
    def visit(value,path=(),key=None):
        if key in ('policy','model_versions','inventory') and isinstance(value,(dict,list)):
            return fact(value,path)
        if key=='event' and event_metadata(value):return fact(value,path)
        if isinstance(value,dict):
            result={}
            for name,item in value.items():
                child=path+(name,)
                if name=='templates' and key in ('profiles','comparison_profiles') and isinstance(item,dict):
                    result[name]={k:fact(v,child+(k,)) for k,v in item.items()}
                else:result[name]=visit(item,child,name)
            return result
        if isinstance(value,list):
            return [fact(item,path+(i,)) if key=='events' and event_metadata(item) else visit(item,path+(i,)) for i,item in enumerate(value)]
        return value
    frame=canonical(dict(data=visit(root),facts=refs))
    if len(frame)>MAX_FRAME_BYTES or len(frame)+expanded>MAX_TOTAL_BYTES:raise ValueError('domain_frame_expansion_capacity')
    return frame,facts


def descriptor(raw):
    frame=parse(raw,MAX_FRAME_BYTES,MAX_DEPTH+1)
    if not isinstance(frame,dict) or set(frame)!={'data','facts'} or not isinstance(frame['facts'],list) or len(frame['facts'])>MAX_REFS:
        raise ValueError('domain_frame_descriptor_invalid')
    trie={};total=len(raw);sizes={}
    for ref in frame['facts']:
        if not isinstance(ref,list) or len(ref)!=3:raise ValueError('domain_frame_reference_invalid')
        path,identity,size=ref
        if not isinstance(path,list) or len(path)>MAX_DEPTH or not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{64}',identity) or type(size) is not int or not 0<size<=delta.MAX_BYTES:
            raise ValueError('domain_frame_reference_invalid')
        total+=size
        if total>MAX_TOTAL_BYTES:raise ValueError('domain_frame_expansion_capacity')
        if identity in sizes and sizes[identity]!=size:raise ValueError('domain_frame_fact_size_conflict')
        sizes[identity]=size;node=trie;target=frame['data']
        for token in path:
            if '$end' in node:raise ValueError('domain_frame_overlapping_path')
            if type(token) is int:
                if not isinstance(target,list) or not 0<=token<len(target):raise ValueError('domain_frame_path_invalid')
                target=target[token];typed=(0,token)
            elif isinstance(token,str):
                if not isinstance(target,dict) or token not in target:raise ValueError('domain_frame_path_invalid')
                target=target[token];typed=(1,token)
            else:raise ValueError('domain_frame_path_invalid')
            node=node.setdefault(typed,{})
        if node or target is not None:raise ValueError('domain_frame_duplicate_or_nonnull_path')
        node['$end']=True
    expected=len(canonical(frame['data']))+sum(ref[2]-4 for ref in frame['facts'])
    if not 0<=expected<=delta.MAX_BYTES:raise ValueError('domain_frame_original_capacity')
    return frame,sizes


def expand(raw,facts,original_size,original_hash):
    # Public callers always validate the complete manifest before expansion.
    return _expand_from_descriptor(descriptor(raw),facts,original_size,original_hash)


def _expand_from_descriptor(validated,facts,original_size,original_hash):
    """Private SQL-reader continuation; validated originates in descriptor()."""
    frame,sizes=validated
    expected=len(canonical(frame['data']))+sum(ref[2]-4 for ref in frame['facts'])
    if type(original_size) is not int or expected!=original_size or not 0<=original_size<=delta.MAX_BYTES:raise ValueError('domain_frame_original_capacity')
    if set(facts)!=set(sizes):raise ValueError('domain_frame_fact_missing')
    parsed={}
    # Every referenced hash/canonical byte length validates before any replacement.
    for identity,size in sizes.items():
        body=facts[identity]
        if not isinstance(body,bytes) or len(body)!=size or sha256(body).hexdigest()!=identity:raise ValueError('domain_frame_fact_corrupt')
        parsed[identity]=parse(body)
    expanded_nodes=node_count(frame['data']);fact_nodes={identity:node_count(value) for identity,value in parsed.items()}
    for path,identity,size in frame['facts']:
        expanded_nodes+=fact_nodes[identity]-1
        if expanded_nodes>MAX_NODES:raise ValueError('domain_frame_node_capacity')
    data=frame['data']
    for path,identity,size in frame['facts']:
        value=parsed[identity]
        if not path:data=value;continue
        target=data
        for token in path[:-1]:target=target[token]
        target[path[-1]]=value
    body=canonical(data)
    if len(body)!=original_size or sha256(body).hexdigest()!=original_hash:raise ValueError('domain_frame_original_hash_mismatch')
    # Fact depths plus destination path must respect the original root bound.
    check_depth(body)
    return body


def encode_header(anchor_id,original,frame_size,operations):
    if not re.fullmatch('[0-9a-f]{64}',anchor_id) or len(original)>delta.MAX_BYTES or not 0<frame_size<=MAX_FRAME_BYTES:
        raise ValueError('domain_frame_header_invalid')
    payload=struct.pack('>I',frame_size)+operations
    return FRAME_PREFIX+str(len(original))+':'+sha256(original).hexdigest()+':'+anchor_id+':'+base64.b64encode(delta.compress(payload)).decode('ascii')


def decode_header(value):
    if not isinstance(value,str) or not value.startswith(FRAME_PREFIX) or len(value)>12*1024*1024:raise ValueError('domain_frame_header_invalid')
    fields=value[len(FRAME_PREFIX):].split(':',3)
    if len(fields)!=4 or not re.fullmatch('[0-9]{1,8}',fields[0]) or not all(re.fullmatch('[0-9a-f]{64}',v) for v in fields[1:3]):raise ValueError('domain_frame_header_invalid')
    size=int(fields[0])
    if size>delta.MAX_BYTES:raise ValueError('domain_frame_original_capacity')
    try:body=delta.decompress(base64.b64decode(fields[3],validate=True),delta.MAX_BYTES+1024*1024)
    except (ValueError,TypeError) as exc:raise ValueError('domain_frame_encoding_invalid') from exc
    if len(body)<4:raise ValueError('domain_frame_payload_truncated')
    frame_size=struct.unpack_from('>I',body)[0]
    if not 0<frame_size<=MAX_FRAME_BYTES:raise ValueError('domain_frame_byte_capacity')
    return fields[2],size,fields[1],frame_size,body[4:]


def delta_safe(*bodies):
    """Bound the older byte matcher index even for punctuation-heavy JSON."""
    for body in bodies:
        count=0
        for _ in re.finditer(rb'[{}\[\],:]',body):
            count+=1
            if count>300000:return False
    return True
