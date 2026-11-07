"""Bounded row-wise catalog transfer between the owner and its CPU worker.

Files belong to one private temporary job. Source facts are never dropped: the
reader reuses equal immutable subtrees as each row arrives, before reading the
next row. Neither process stages a whole serialized catalog message.
"""
import json
import base64
import gzip
import io
from hashlib import sha256
from pathlib import Path
from .current_native_catalog import CatalogStrings, share_immutable

MAX_ROW_BYTES=8*1024*1024
MAX_TRANSFER_BYTES=512*1024*1024


def packet(value):
    body=json.dumps(value,separators=(',',':'),ensure_ascii=True).encode()+b'\n'
    if len(body)>MAX_ROW_BYTES:raise ValueError('catalog_transfer_capacity')
    if len(body)>=4096:
        # The unchanged file cap measures bytes actually transferred. Bound the
        # decoded row separately, and retain the worker's resident-memory guard.
        # No shared dictionary can outlive this private job or lose its base.
        compressed=json.dumps(['gzip-1',len(body),sha256(body).hexdigest(),
            base64.b64encode(gzip.compress(body,compresslevel=1,mtime=0)).decode()],separators=(',',':')).encode()+b'\n'
        if len(compressed)<len(body):return compressed
    return body


def unpacket(body):
    value=json.loads(body)
    if isinstance(value,list) and value and value[0]=='gzip-1':
        if len(value)!=4 or type(value[1]) is not int or not 0<value[1]<=MAX_ROW_BYTES:
            raise ValueError('catalog_transfer_capacity')
        with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(value[3],validate=True))) as stream:
            raw=stream.read(MAX_ROW_BYTES+1)
        if len(raw)!=value[1] or sha256(raw).hexdigest()!=value[2]:
            raise ValueError('catalog_transfer_integrity')
        value=json.loads(raw)
    return value


def write(path,catalogs,delta=None,*,previous=None):
    from .current_storage_policy import require_disk_space
    require_disk_space(Path(path).parent,append_bytes=MAX_TRANSFER_BYTES)
    total=0
    with Path(path).open('wb') as stream:
        def emit(value):
            nonlocal total
            body=packet(value)
            total+=len(body)
            if len(body)>MAX_ROW_BYTES or total>MAX_TRANSFER_BYTES:
                raise ValueError('catalog_transfer_capacity')
            stream.write(body)
        for source,catalog in catalogs.items():
            emit(['header',source,{k:v for k,v in catalog.items() if k not in ('events','markets')}])
            for kind in ('events','markets'):
                prior = {r['id']: r for r in (previous or {}).get(source, {}).get(kind, ())}
                for row in catalog[kind]:
                    base = prior.get(row['id'])
                    if base is not None:
                        # Only borrow objects already owned by the exact job base.
                        # Preserve field order, removals, explicit nulls and types.
                        borrowed = [k for k in row if k in base and row[k] is base[k]]
                        if any(isinstance(row[k], (dict, list)) for k in borrowed):
                            changed = {k: v for k, v in row.items() if k not in borrowed}
                            emit(['patch', source, [kind, row['id'], list(row), changed]])
                            continue
                    emit([kind, source, row])
        if delta is not None:
            for kind,values in delta.items():
                for key in sorted(values):emit(['delta',kind,list(key)])
        emit(['end',None,None])
    return total


def read(path,previous=None,guard=None):
    catalogs={};delta={k:set() for k in ('retained','withdraw','refresh')};indices={};total=0;ended=False
    previous=previous or {}
    strings = CatalogStrings()
    with Path(path).open('rb') as stream:
        for count in range(1000000):
            body=stream.readline(MAX_ROW_BYTES+1)
            if not body:break
            total+=len(body)
            if len(body)>MAX_ROW_BYTES or total>MAX_TRANSFER_BYTES or not body.endswith(b'\n'):
                raise ValueError('catalog_transfer_capacity')
            kind,source,value=unpacket(body)
            if guard and count%128==0:guard()
            if kind=='end':
                if stream.read(1):raise ValueError('catalog_transfer_trailing_data')
                ended=True;break
            if kind=='header':
                if source in catalogs:raise ValueError('catalog_transfer_duplicate_source')
                catalogs[source]=dict(value,events=[],markets=[])
                indices[source]={k:{r['id']:r for r in previous.get(source,{}).get(k,[])} for k in ('events','markets')}
            elif kind == 'patch' and source in catalogs:
                field, rid, keys, changed = value
                base = indices[source][field].get(rid)
                if base is None or len(keys) != len(set(keys)) or not changed.keys() <= set(keys):
                    raise ValueError('catalog_transfer_patch_base')
                for key, item in changed.items():
                    changed[key] = share_immutable(base[key], item) if key in base else strings.compact(item)
                row = {k: changed[k] if k in changed else base[k] for k in keys}
                if row.get('id') != rid:
                    raise ValueError('catalog_transfer_patch_identity')
                catalogs[source][field].append(row)
            elif kind in ('events','markets') and source in catalogs:
                prior=indices[source][kind].get(value['id'])
                catalogs[source][kind].append(dict(share_immutable(prior,value)) if prior is not None else strings.compact(value))
            elif kind=='delta' and source in delta:delta[source].add(tuple(value))
            else:raise ValueError('catalog_transfer_invalid_record')
    if not ended:raise ValueError('catalog_transfer_incomplete')
    return catalogs,delta


def prepare(input_path,replacement_path,output_path,source,maximum_bytes):
    from .continuous import rss
    def guard():
        if rss()>=maximum_bytes:raise ValueError('catalog_worker_memory_guard')
    replacement,_=read(replacement_path,guard=guard)
    inventory,_=read(input_path,previous=replacement,guard=guard)
    from .current_ingress import prepare_catalog_change
    from app.comparison.calculation_control import cancellation
    def cancelled():guard();return False
    with cancellation(cancelled):prepared,delta=prepare_catalog_change(inventory,source,replacement[source])
    guard();size=write(output_path,prepared,delta,previous=dict(inventory,**replacement));guard()
    return dict(transfer_bytes=size,worker_peak_rss_bytes=rss())
