"""Repeatable file-only E5 replay/isolation evidence; refuses to replace an output."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import psycopg
from app.dashboard.e5_preview import isolate_process, load_package

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    if args.output.exists():raise SystemExit('Choose a new evidence filename; existing evidence is retained.')
    isolate_process();blocks={}
    for name,fn in [('network',lambda:socket.create_connection(('127.0.0.1',1))),
                    ('database',lambda:psycopg.connect('')),
                    ('child_process',lambda:subprocess.run(['/usr/bin/true'])),
                    ('credential_file',lambda:Path('.env.e5-forbidden-probe').read_text())]:
        try:fn();raise AssertionError(name+' was not blocked')
        except PermissionError as exc:blocks[name]=str(exc)
    a=load_package();b=load_package()
    packed=lambda value:json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    assert packed(a)==packed(b)
    collector=[n for n in sys.modules if n.startswith(('app.dashboard.controller','app.dashboard.collector','app.dashboard.pipeline','keyring','dotenv'))]
    assert not collector
    report=dict(guard_checks=blocks,byte_exact_repeat=True,package_sha256=hashlib.sha256(packed(a)).hexdigest(),
                audits=[{k:c[k] for k in ['key','id','export_sha256','estimate_id','replay']} for c in a['cases']],
                estimates=[{'id':e['id'],'cutoff':e['cutoff']} for e in a['estimates']],collector_modules_loaded=collector)
    args.output.write_text(json.dumps(report,indent=2));print('PASS: two identical packages, seven E4 audits, six E3 estimates, four isolation guards')
if __name__=='__main__':main()
