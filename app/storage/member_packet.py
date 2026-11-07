"""Self-contained immutable capture: stable evidence and visit-specific observations.

Only the private replacement reader may lend a compressed section. Demand the
same objects in the same slots. No database reference chain or retained cache.
"""
import struct

MAGIC=b'PMI1'


def split(value):
    body=dict(value);basis=dict(body['_price_basis']);body['_price_basis']=basis
    fixed={k:body.pop(k) for k in ('games','references')};fixed['catalogs']=basis.pop('catalogs')
    fixed['records']=[];body['quotes']=[]
    for q in value['quotes']:
        row=dict(q);record=dict(q['original_record']);row['original_record']=record
        slot={'id':q['id']}
        if 'event' in record:slot['event']=record.pop('event')
        if 'comparison_source_metadata' in record:
            meta=record['comparison_source_metadata'];slot['metadata']={k:v for k,v in meta.items() if k!='observed_at'}
            record['comparison_source_metadata']={k:meta[k] for k in ('observed_at',) if k in meta}
        fixed['records'].append(slot);body['quotes'].append(row)
    return fixed,body


def same_parts(a,b):
    if any(a[k] is not b[k] for k in ('games','references','catalogs')) or len(a['records'])!=len(b['records']):return False
    for x,y in zip(a['records'],b['records']):
        if x.keys()!=y.keys() or x['id']!=y['id'] or x.get('event') is not y.get('event'):return False
        m=x.get('metadata',{});n=y.get('metadata',{})
        if m.keys()!=n.keys() or any(v is not n[k] for k,v in m.items()):return False
    return True


def encode(value,prior=None):
    from .comparison_snapshot import pack,SnapshotOperationError
    fixed,body=split(value)
    reuse=prior is not None and same_parts(fixed,prior[0])
    block=prior[1] if reuse else pack(fixed,fast=True)
    moving=pack(body,fast=True)
    if 8+len(block)+len(moving)>96*1024*1024:raise SnapshotOperationError('Snapshot storage capacity reached')
    return MAGIC+struct.pack('>I',len(block))+block+moving, len(block) if reuse else 0


def read(blob,*,borrow=False):
    from .comparison_snapshot import _decode,SnapshotOperationError
    if len(blob)<8:raise SnapshotOperationError('Invalid immutable member packet')
    size=struct.unpack_from('>I',blob,4)[0]
    if not 0<size<len(blob)-8:raise SnapshotOperationError('Invalid immutable member section')
    block=blob[8:8+size];fixed=_decode(block);body=_decode(blob[8+size:])
    body.update(games=fixed['games'],references=fixed['references']);body['_price_basis']['catalogs']=fixed['catalogs']
    for q,slot in zip(body['quotes'],fixed['records'],strict=True):
        if q['id']!=slot['id']:raise SnapshotOperationError('Crossed immutable member record')
        record=q['original_record']
        if 'event' in slot:record['event']=slot['event']
        if 'metadata' in slot:record['comparison_source_metadata']={**slot['metadata'],**record['comparison_source_metadata']}
    return (body,(fixed,block)) if borrow else body
