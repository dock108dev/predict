"""Bounded read-only workload samples; source counters and SQL units stay separate."""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect
from app.storage.latest_board import runtime
from app.storage.current_games import utc


def sample(db):
    r=runtime(db);s=r.get('status',{})
    sources=[]
    for row in s.get('sources',[]):
        m=row.get('metrics') or {}
        sources.append(dict(provider=row.get('provider'),**{k:m.get(k) for k in (
            'complete_images_received','initial_images_received','meaningful_images_received','clock_images_received','repeated_images_received','normalization_keys_enqueued','normalization_attempted_images','pending_images_replaced','received_instruments_last_second','socket_reads','receive_buffer_bytes','frames','connections','selected_markets','initial_images','stream_connected',
            'receive_buffer_frames','receive_oldest_seconds','raw_backlog','raw_images_persisted',
            'raw_write_ms','raw_oldest_pending_seconds','pending_books','derived_images_published',
            'derived_oldest_pending_seconds','receipt_projection_ms','reconstruction_coalesced_frames')}))
    return dict(at=utc(),runtime_id=r.get('runtime_id'),healthy=r.get('healthy'),sources=sources,
        ingress=s.get('ingress'),sink=s.get('sink'),resources=s.get('resources'),
        progress=s.get('background_work',{}).get('progress'),
        counts=db.execute('''SELECT (SELECT count(*) FROM current_contract) instruments,
            (SELECT count(*) FROM current_offer) offers,
            (SELECT count(*) FROM current_result_work WHERE active) active_keys,
            (SELECT count(*) FROM current_result_work WHERE active AND refresh_order IS NOT NULL) queued_keys,
            (SELECT count(*) FROM current_result_unit) sealed_units,
            (SELECT max(published_at)::text FROM current_result_unit) latest_seal,
            (SELECT pg_total_relation_size('current_result_work')) work_bytes,
            (SELECT pg_database_size(current_database())) database_bytes''').fetchone(),
        work=db.execute('''SELECT count(*) FILTER(WHERE active AND pending_version>acknowledged_version) dirty_keys,
            count(*) FILTER(WHERE active AND claimed_version IS NOT NULL AND pending_version>claimed_version) newer_than_claim,
            max(extract(epoch FROM clock_timestamp()-dirty_since)) FILTER(WHERE active AND pending_version>acknowledged_version) oldest_dirty_seconds,
            count(*) FILTER(WHERE active AND visits=0) never_visited
            FROM current_result_work''').fetchone(),
        leases=db.execute('SELECT count(*) n,COALESCE(sum(cardinality(packet_ids)),0) packet_references FROM current_grid_read_lease').fetchone(),
        publications=db.execute('''SELECT game_key,unit_id,generation_id,published_at,captured_at
            FROM current_result_unit WHERE published_at>clock_timestamp()-interval '10 seconds' ''').fetchall(),
        generations=db.execute('SELECT disposition,count(*) n,sum(commits) commits,sum(calculations) calculations FROM pipeline_generation GROUP BY disposition').fetchall())


def main():
    p=argparse.ArgumentParser();p.add_argument('output');p.add_argument('--seconds',type=float,default=120);args=p.parse_args()
    start=time.monotonic()
    with Path(args.output).open('x') as out,connect() as db:
        db.execute("SET statement_timeout='10s'")
        while True:
            out.write(json.dumps(sample(db),default=str)+'\n');out.flush()
            if time.monotonic()-start>=args.seconds:break
            time.sleep(5)

if __name__=='__main__':main()
