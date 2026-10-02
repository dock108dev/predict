"""Prepare inert review artifacts only; never approve, reserve or execute."""
import json,sys,zipfile
from pathlib import Path
from hashlib import sha256
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.collection.native_approval import implementation,digest
from app.collection.run_spec import preflight
P=ROOT/'scripts/v1_counterpart_package';OUT=ROOT/'evidence/v1-counterpart-completion-20261001-v1'
def save(n,v):(P/n).write_text(json.dumps(v,indent=2)+'\n')
def seal():
 assert not any((P/n).exists() for n in ('owner-approval.json','reservations.jsonl','reservations-started.json','children'))
 spec=json.loads((P/'run-spec.json').read_text());assert preflight(spec)['valid']
 inventory=json.loads((OUT/'counterpart-inventory.json').read_text());save('TARGETS.json',inventory['targets'])
 operations=dict(version='v1-counterpart-operations-1',kalshi=[dict(kind='read_only_account_budget_checks',maximum=2),dict(kind='documented_series_listing',maximum=4,event_page_size=5),dict(kind='selected_event_market_page',maximum=4,market_page_size=50)],polymarket_us=[dict(kind='sport_game_listing_identity_only',maximum=2,page_size=5),dict(kind='current_selected_event_detail',maximum=2),dict(kind='selected_market_detail',maximum=2),dict(kind='documented_H1_family_page',maximum=4,page_size=5)],aggregate=[dict(kind='fresh_quota',maximum=1,credits=0),dict(kind='shared_selected_event_discovery',maximum=2,credits=0),dict(kind='H1_spread_total_counterpart_or_offering_query',maximum=4,credits=8,cycles=2)],no_requests_for_other_44_missing_requirements=True,source_receipts_are_not_books=True)
 save('OPERATIONS.json',operations)
 limits=json.loads((ROOT/'scripts/v1_coverage_package/LIMITS.json').read_text());limits.update(http_attempts=dict(kalshi=10,polymarket_us=10,aggregate=7,total=27),maximum_connection_establishments=31,websocket_attempts=4,simultaneous_websockets=4,simultaneous_http=3,simultaneous_connections_total=7,prepaid_credits=8,aggregate_discovery_per_sport=1,aggregate_selected_games_per_sport=1)
 limits['cumulative']=dict(sessions=2,http_attempts=54,websocket_attempts=8,credits=16,collection_seconds=360,supervised_seconds=480,output_bytes=268435456,control_bytes=6291456)
 # Existing shared socket gate is six total HTTP/WS connections; lower intersection binds.
 limits['simultaneous_connections_total']=6;limits['simultaneous_websockets']=3
 limits['operating_subscription_markets']=dict(kalshi=40,polymarket_us=64)
 save('LIMITS.json',limits)
 manifest=implementation();save('SOURCE-MANIFEST.json',manifest)
 with zipfile.ZipFile(P/'SOURCE.zip','w',zipfile.ZIP_DEFLATED) as z:
  for n in manifest:z.write(ROOT/n,n)
 fresh='v1-counterpart-'+str(uuid4());output=ROOT/'evidence'/('LIVE-'+fresh);assert not output.exists()
 reservation=dict(http=27,credits=8,websocket_attempts=4,collection_seconds=180,supervised_seconds=240,output_bytes=134217728)
 files={p.name:sha256(p.read_bytes()).hexdigest() for p in P.iterdir() if p.is_file() and p.name!='master.json' and p.suffix in ('.py','.json','.txt','.md','.zip')}
 m=dict(format='predict-counterpart-master-1',fresh_package_id=fresh,initial_implementation_sha256=digest(manifest),spec_sha256=digest(spec),output_root=str(output),max_sessions=2,per_session_reservation=reservation,cumulative=limits['cumulative'],validity_window=dict(start=spec['start_after'],latest_start=spec['start_before'],expires='2026-10-08T03:59:59Z'),protected_files={n:sha256((ROOT/n).read_bytes()).hexdigest() for n in ('app/collection/native_approval.py','app/collection/engineering_authorization.py')},file_hashes=files,approved=False,collection_authorized=False)
 save('master.json',m);print(json.dumps(dict(master_sha256=digest(m),candidate=m['initial_implementation_sha256'],spec=m['spec_sha256'],output=m['output_root'],approved=False),indent=2))
if __name__=='__main__':seal()
