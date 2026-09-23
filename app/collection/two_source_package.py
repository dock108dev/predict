"""Bind an explicitly approved execution time to a sealed, otherwise fixed package.

Offline only. Calling this module does not launch a server or resolve credentials.
The caller must already have the owner's approval; text records that decision.
"""
import argparse
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
from pathlib import Path
from .native_approval import digest,implementation
from .two_source_policy import validate


def verify(package):
    p=Path(package).resolve();seal=json.loads((p/'seal.json').read_text())
    if digest(seal['files'])!=seal['sha256']:raise ValueError('package seal changed')
    for name,h in seal['files'].items():
        f=p/name
        if f.parent!=p or sha256(f.read_bytes()).hexdigest()!=h:raise ValueError('package file changed: '+name)
    spec=json.loads((p/'run-spec.template.json').read_text());validate(spec)
    a=json.loads((p/'approval.draft.json').read_text())
    candidate=json.loads((p/'candidate.json').read_text())
    if spec['mode']!='real' or a['approved'] is not False:raise ValueError('invalid pending package')
    if implementation()!=candidate['files'] or digest(candidate['files'])!=a['implementation_sha256']:raise ValueError('candidate changed')
    if digest(spec)!=a['spec_sha256']:raise ValueError('template scope changed')
    if (Path(a['output'])/'b3-attempt.json').exists():raise ValueError('attempt consumed')
    return spec,a,seal['sha256']


def activate(package,start,owner_approval,*,now=None):
    p=Path(package).resolve();spec,draft,seal=verify(p)
    if not owner_approval.strip():raise ValueError('record explicit owner approval first')
    now=now or datetime.now(timezone.utc)
    at=now if start=='now' else datetime.fromisoformat(start.replace('Z','+00:00'))
    if at.utcoffset() is None:raise ValueError('aware UTC or offset start required')
    at=at.astimezone(timezone.utc)
    if at+timedelta(minutes=15)<now:raise ValueError('requested window already expired')
    spec.update(start_after=at.isoformat(),start_before=(at+timedelta(minutes=15)).isoformat());validate(spec)
    approved=dict(draft,approved=True,spec_sha256=digest(spec),package_seal_sha256=seal,
        owner_approval=owner_approval,approved_at=now.isoformat())
    # Exclusive timing binding: a second invocation cannot silently rebook it.
    folder=p/'activation';folder.mkdir()
    for name,value in [('run-spec.json',spec),('approval.json',approved)]:
        with (folder/name).open('x') as f:json.dump(value,f,indent=2);f.write('\n')
    return dict(start_after=spec['start_after'],start_before=spec['start_before'],spec_sha256=digest(spec),attempt_id=spec['two_source_qualification']['attempt_id'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('package',type=Path)
    p.add_argument('--start',help='now or aware ISO start chosen by owner');p.add_argument('--approval-text')
    a=p.parse_args()
    if a.start:
        if not a.approval_text:p.error('--approval-text required after explicit owner approval')
        print(json.dumps(activate(a.package,a.start,a.approval_text),indent=2))
    else:
        verify(a.package);print('PASS: sealed candidate/scope; unused attempt. No launch or access.')

if __name__=='__main__':main()
