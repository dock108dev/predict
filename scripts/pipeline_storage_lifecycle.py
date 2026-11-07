"""Exact retained populations and lifecycle candidates, no mutation or acquisition."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect
from app.storage.recovery_codec import thaw


def snapshot(db):
    out={}
    queries={
        'catalog':'''SELECT source,count(*) rows,count(*) FILTER(WHERE parsed IS NOT NULL) parsed,
            sum(pg_column_size(metadata)) metadata_storage_bytes,sum(pg_column_size(parsed)) parsed_storage_bytes,
            coalesce(sum(pg_column_size(receipt_fields)),0) receipt_storage_bytes
            FROM current_native_market_recovery GROUP BY source''',
        'images':'''SELECT i.source,count(*) rows,
            count(*) FILTER(WHERE m.market_id IS NOT NULL AND NOT m.withdrawn) current_membership,
            count(*) FILTER(WHERE i.received_at<now()-interval '2 days' AND (m.market_id IS NULL OR m.withdrawn)) cleanup_eligible,
            sum(pg_column_size(i.image)+coalesce(pg_column_size(i.depth_payload),0)+coalesce(pg_column_size(i.wire_payload),0)) image_storage_bytes
            FROM current_acquisition_image_parts i LEFT JOIN current_acquisition_market m USING(source,event_id,market_id) GROUP BY i.source''',
        'queries':'''SELECT q.source,q.generation,count(DISTINCT q.query_key) queries,count(p.position) pages,
            sum(pg_column_size(p.receipt)) receipt_storage_bytes,min(q.completed_at) oldest_completed
            FROM current_acquisition_query q LEFT JOIN current_acquisition_page p USING(source,query_key)
            GROUP BY q.source,q.generation''',
        'depth':'''SELECT venue,count(*) rows,count(DISTINCT (event_id,native_market_id)) books,
            count(*) FILTER(WHERE side='asks') asks FROM current_native_depth GROUP BY venue''',
        'contracts':'''SELECT c.venue,count(*) rows,count(DISTINCT c.event_id) events,
            count(*) FILTER(WHERE e.expires_order<extract(epoch FROM now())) expiry_eligible
            FROM current_contract c JOIN current_event e ON e.id=c.event_id GROUP BY c.venue''',
        'publications':'''SELECT count(*) rows,sum(retained_bytes) logical_bytes,min(calculated_at) oldest_calculation,
            min(observation_as_of) oldest_observation FROM latest_board''',
        'generations':'''SELECT disposition,count(*) rows,count(*) FILTER(WHERE trace<>'{}'::jsonb) traces,
            sum(pg_column_size(trace)) trace_storage_bytes FROM pipeline_generation GROUP BY disposition''',
        'diagnostics':'''SELECT branch,disposition,reason,count(*) rows FROM current_pipeline_attempt GROUP BY branch,disposition,reason''',
        'current_membership':'''SELECT source,disposition,withdrawn,count(*) rows FROM current_acquisition_market GROUP BY source,disposition,withdrawn''',
    }
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        out['at']=db.execute('SELECT transaction_timestamp() at').fetchone()['at']
        for key,query in queries.items():out[key]=db.execute(query).fetchall()
        counts={r['source']:0 for r in out['catalog']}
        # For historical recovery packets the disposition is inside the metadata;
        # split packets retain it in the observation section. Never count only the
        # SQL-visible display fields of a compressed value.
        with db.cursor(name='lifecycle_absence') as cursor:
            cursor.itersize=64
            cursor.execute('SELECT source,receipt_fields IS NOT NULL AS split,'
                'coalesce(receipt_fields,metadata) AS packet FROM current_native_market_recovery')
            for r in cursor:
                value=thaw(r['packet'])
                if r['split']:value=value['metadata']
                if value.get('inventory_recovery_disposition')=='suspected_absent':counts[r['source']]+=1
        for r in out['catalog']:r['suspected_absent']=counts[r['source']]
    return out

if __name__=='__main__':
    with connect() as db:out=snapshot(db)
    Path(sys.argv[1]).write_text(json.dumps(out,indent=2,default=str)+'\n')
    print(json.dumps(out,default=str))
