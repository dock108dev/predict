"""Narrow integrated extension; original controller and spent ledgers are immutable."""
import json
from pathlib import Path
from . import engineering_authorization as base

LIMITS = dict(sessions=2, integrated=2, http_requests=266,
    native_http_requests=192, aggregate_http_requests=74, websocket_connections=8,
    aggregate_credits=270, collection_seconds=360, owned_wall_seconds=480,
    output_bytes=256*1024*1024, control_bytes=8*1024*1024)


def validate(package):
    package = Path(package)
    value = base._read_json(package/'extension.json')
    if value.get('format')!='predict-integrated-extension-v1' or value.get('limits')!=LIMITS:
        raise ValueError('Exact narrower integrated extension required')
    approval = base._read_json(package/'extension-approval.json')
    if approval != dict(approved=True, extension_sha256=base.digest(value)):
        raise ValueError('Exact extension owner approval required')
    parent = Path(value['exhausted_parent_master'])
    old = base._read_json(parent)
    if base.digest(old)!=value['exhausted_parent_sha256']:
        raise ValueError('Exhausted parent changed')
    rows = base._ledger(parent.parent/'reservations.jsonl',base.digest(old))
    if len(rows)!=4 or sum(r['kind']=='integrated' for r in rows)!=2 or rows[-1]['sha256']!=value['exhausted_parent_last_reservation']:
        raise ValueError('Exhausted parent reservations changed')
    master=base.validate_master(package/'master.json',package/'owner-approval.json')
    if base.digest(master)!=value['extension_master_sha256'] or master['validity_window']['expires']!='2026-10-08T01:30:00+00:00':
        raise ValueError('Extension master or expiry changed')
    current=base._ledger(package/'reservations.jsonl',base.digest(master))
    if len(current)>2 or any(r['kind']!='integrated' for r in current):
        raise ValueError('Extension integrated-only session ceiling')
    if current and any(v>LIMITS[k] for k,v in current[-1]['cumulative'].items()):
        raise ValueError('Extension cumulative ceiling')
    return value,current


def reserve(package,spec,endpoints,**kwargs):
    package=Path(package)
    _,rows=validate(package)
    if len(rows)>=2:raise ValueError('Integrated extension consumed')
    if kwargs.get('kind','integrated')!='integrated':raise ValueError('Integrated-only extension')
    kwargs['kind']='integrated'
    # The unchanged controller locks, durably spends and enforces two integrated
    # reservations. Their worst-case totals equal the narrower extension limits.
    result=base.reserve_session(package/'master.json',package/'owner-approval.json',spec,endpoints,**kwargs)
    validate(package)
    return result


def gate(approval_path):
    """Run before ordinary Start consumption and credential resolution."""
    if not approval_path:return
    approval=base._read_json(approval_path)
    binding=approval.get('engineering_master')
    if not binding:return
    package=Path(binding['master_path']).parent
    # Legacy approvals keep their original contract. The extension master names
    # its narrow authority in a required sibling record, sealed before dispatch.
    if package.name.startswith('source-engineering-extension-'):
        _,rows=validate(package)
        if not any(r['sha256']==binding['reservation_sha256'] for r in rows):
            raise ValueError('Missing durable extension reservation')
