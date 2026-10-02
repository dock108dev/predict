"""Versioned offline r4 reconciliation and compact derived reopening; no I/O to providers."""
from copy import deepcopy
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
from app.collection.transport_session import reopen,ObservationJournal
from app.collection.journal_encoding import VERSION
from app.collection.native_approval import digest,implementation
from app.collection.continuous import Discovery
from app.collection.native_payload import POLICY
from app.collection.listing_evidence import retained_us_futures
from app.dashboard.session_history import load,project_rows
from app.dashboard.bounds import retained_bytes

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'evidence/integrated-acquisition-r4-20260930'
DERIVED=ROOT/'evidence/integrated-r4-derived-20260930-v1'
SOURCE=ROOT/'evidence/integrated-source-r4-attempt-12d7b909-bcb4-42be-a8c6-18225df18009'
SID='ea3936a3-8e9f-4557-b4be-ae7a56b98f73'


def main():
    folder=SOURCE/SID;rs=reopen(folder/(SID+'.jsonl'))['rows']
    report=json.loads((folder/'report.json').read_text());receipts=[r for r in rs if r['type']=='aggregate_http']
    native=[r for r in rs if r['type']=='prediction_discovery_http'];snapshots=[r for r in rs if r['type']=='aggregate_snapshot']
    charged=sum(int(dict(r['headers'])['x-requests-last']) for r in receipts);last=dict(receipts[-1]['headers'])
    try:load(folder)
    except ValueError as e:original_reopen_failure=str(e)
    else:raise AssertionError('Original r4 failure must not be silently reinterpreted')
    associations=retained_us_futures(native)
    (DERIVED/'listing-associations.json').write_text(json.dumps(associations,indent=2)+'\n')
    spec=json.loads((folder/'run-spec.json').read_text());spec['source_session']['native_discovery']=POLICY
    d=Discovery(SimpleNamespace(spec=spec,producers={},product_session=True))
    d.pages=[dict(r,acquisition_discovery_policy=POLICY) for r in native]
    cats,markets=d.project();assert all(not c['selection']['ids'] for c in cats.values())
    (DERIVED/'compact-inventory.json').write_text(json.dumps(cats,separators=(',',':')))
    target=DERIVED/'saved'/SID;target.mkdir(parents=True,exist_ok=True)
    path=target/(SID+'.jsonl');assert not path.exists(),'Derived version already exists; never overwrite'
    journal=ObservationJournal(path,encoding=VERSION)
    changes=[]
    try:
        for index,row in enumerate(rs):
            if row['type']=='coverage_inventory':
                updated=dict(row,inventory=cats,derivation=dict(version='r4-compact-catalog-1',original_row_sha256=digest(row),source_journal_sha256=hashlib.sha256((folder/(SID+'.jsonl')).read_bytes()).hexdigest(),qualification='No changed source bytes, identities, quotes, economics or completeness; excluded catalog moved to source references'))
                changes.append(dict(cursor=index+1,original_sha256=digest(row),derived_sha256=digest(updated)))
            else:updated=row
            journal.save(updated)
    finally:journal.close()
    saved=load(target);derived_rows=reopen(path)['rows'];assert saved==dict(project_rows(derived_rows,saved['durable_cursor']),state='incomplete')
    assert len(saved['aggregate_coverage'])==63
    (DERIVED/'derivation.json').write_text(json.dumps(dict(version='r4-compact-catalog-1',changes=changes,original_journal_sha256=hashlib.sha256((folder/(SID+'.jsonl')).read_bytes()).hexdigest(),derived_journal_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),saved_snapshot_sha256=digest(saved),saved_state='incomplete',original_not_rewritten=True),indent=2))
    result=dict(attempt_id='12d7b909-bcb4-42be-a8c6-18225df18009',consumed=(SOURCE/'b3-attempt.json').exists(),collection_seconds=report['collection_seconds'],stop_reason=report['reason'],cleanup_complete=report['cleanup_complete'],http={'aggregate':len(receipts),**dict(Counter(r['source'] for r in native))},http_total=len(receipts)+len(native),ws_attempts=0,native_book_admissions=0,aggregate_charged_credits=charged,aggregate_reserved_credits=39,last_reported_remaining=int(last['x-requests-remaining']),paid_dispatches=sum(r['request']['path'].endswith('/odds') for r in receipts),uncertain_dispatches=sum(r['type']=='aggregate_dispatch' for r in rs)-len(receipts),aggregate_snapshots={r['sport']:len(r['records']) for r in snapshots},aggregate_record_count=sum(len(r['records']) for r in snapshots),completed_aggregate_cycles=1,aggregate_repeated_update_evidence=False,native_repeated_update_evidence=False,cross_source_qualified=0,native_listing_associations=len(associations),required_cells=63,aggregate_comparisons=len(saved['aggregate_comparisons']),journal_complete=True,ordinary_finalization='failed: queue_capacity and replay_memory_reservation',original_ordinary_reopening=False,original_reopen_failure=original_reopen_failure,exact_derived_reopening=True,derived_saved_state='incomplete',resources=report['resources'],session_output_bytes=sum(f.stat().st_size for f in folder.rglob('*') if f.is_file()),control_marker_bytes=(SOURCE/'b3-attempt.json').stat().st_size,purchases=0,restarts=0)
    (PACKAGE/'live-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    (DERIVED/'engineering-verification.json').write_text(json.dumps(dict(implementation_sha256=digest(implementation()),compact_serialized_bytes=len(json.dumps(cats,separators=(',',':')).encode()),compact_retained_object_bytes=retained_bytes(cats),excluded_events=sum(len(c.get('excluded_catalog',{}).get('events',[])) for c in cats.values()),excluded_markets=sum(len(c.get('excluded_catalog',{}).get('markets',[])) for c in cats.values()),derived_reopening=True),indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
