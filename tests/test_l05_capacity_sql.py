"""Optional captured-load replay in disposable SQL; never live finance proof."""
import cProfile
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import pstats
from time import perf_counter, process_time
from unittest import skipUnless
from unittest.mock import patch
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from app.storage.current_rows import CurrentRowStore
from app.storage import comparison_snapshot as snapshots, ordinary_publication as live
from app.storage.store import stamp


@skipUnless(SOCKET and os.environ.get('L05_CAPTURE_LOAD'), 'Explicit disposable captured-load replay required')
class CapacitySQL(LatestBoardFixture):
    async def test_capture_and_active_finance_replay(self):
        source=Path(os.environ['L05_CAPTURE_LOAD'])
        output=Path(os.environ['L05_LOAD_OUTPUT']);output.mkdir(parents=True,exist_ok=True)
        inputs=json.loads(source.read_text())
        self.at=stamp(inputs[0]['captured_at'])
        records={r['id']:r['original_record'] for v in inputs for r in v['quotes']+v['references']}
        del inputs
        with self.connect() as db:
            db.execute('TRUNCATE current_event CASCADE')
            db.execute('TRUNCATE comparison_snapshot_result,comparison_snapshot CASCADE')
            db.execute("INSERT INTO comparison_publication(kind,id,generation,facts) VALUES('live','',0,'{}')")
            self.state.write(self.service)
            rows=CurrentRowStore(db);rows.upsert_records(list(records.values()),now=self.at.isoformat())
            timings=[];profile=cProfile.Profile()
            focused=os.environ.get('L05_MEMBER_ORACLE')=='1'
            for index in range(0 if focused else 3):
                start=perf_counter();profile.enable()
                rows.upsert_records(list(records.values()),now=self.at.isoformat())
                profile.disable();timings.append(perf_counter()-start)
            if timings:
                with (output/'admission-profile.txt').open('w') as f:pstats.Stats(profile,stream=f).sort_stats('cumulative').print_stats(35)
            events=[r['id'] for r in db.execute('select id from current_event order by id')]
            start=perf_counter();captured=snapshots.capture(db,ordinary=True,event_ids=events,at=self.at.isoformat());capture_seconds=perf_counter()-start
            # Compare exact reconstructed observations across implementation variants.
            for field in ('id','capture_seconds','policy_identity'):captured.pop(field,None)
            if not focused:(output/'capture.json').write_text(json.dumps(captured,sort_keys=True))
            comparisons=[];context=snapshots.ReadContext
            incremental=bool(os.environ.get('L05_INCREMENTAL_LOAD'))
            for reuse in ((False,True) if focused else (False,True,True,False,False,True)):
                def factory(*a,**kw):return context(*a,**dict(kw,reuse_catalog_inputs=reuse))
                start=perf_counter();cpu=process_time()
                if incremental:
                    value=snapshots.capture(db,ordinary=True,event_ids=events,at=self.at.isoformat(),capture_binding='controlled' if reuse else None)
                else:
                    with patch.object(snapshots,'ReadContext',side_effect=factory):
                        value=snapshots.capture(db,ordinary=True,event_ids=events,at=self.at.isoformat())
                comparisons.append(dict(reuse=reuse,seconds=perf_counter()-start,cpu_seconds=process_time()-cpu))
                for field in ('id','capture_seconds','policy_identity'):value.pop(field,None)
                self.assertEqual(value,captured)
                del value
            captured_count=len(captured['quotes']);captured_issues=captured['issues'];del captured
            with patch('app.storage.ordinary_publication.utc',return_value=self.at.isoformat()), patch('app.storage.comparison_snapshot.utc',return_value=self.at.isoformat()):
                turns=[]
                for _ in range(20):
                    result=live.turn(db,capture_cache=output/'plans.json' if incremental else None);turns.append(result)
                    self.assertGreater(result['computed'],0)
                    root=snapshots.unpack(db.execute("SELECT result FROM comparison_snapshot_result WHERE id=(SELECT result_id FROM comparison_publication WHERE kind='live')").fetchone()['result'],db=db)
                    if root['publication']['finance']=='ready' and result['remaining_components']==0:break
                self.assertEqual(root['publication']['finance'],'ready')
                self.assertEqual(result['remaining_components'],0)
                self.assertEqual(root['publication']['component_count'],result['expected_components'])
                numeric=sum(r.get('conditional_return_percent') is not None for r in root['rows'])
                self.assertGreater(numeric,0)
            churn=[]
            if incremental:
                prior_read=snapshots.unpack(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(root['id'],)).fetchone()['result'],lazy=True,db=db)
                member=root['rows'][0]['evidence_result_id'];token=live.retain(db,member)
                selected=snapshots.unpack(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(member,)).fetchone()['result'],db=db)
                repeats=int(os.environ.get('L05_REPEAT_LOAD','1'))
                self.assertTrue(1<=repeats<=5)
                for phase,kind in enumerate(('material','confirmation','reference')*repeats):
                    cycle_index=phase//3
                    phase_key=kind if repeats==1 else str(cycle_index+1)+'-'+kind
                    phase_started=perf_counter()
                    self.at+=timedelta(seconds=2);changed=[]
                    for i,(record_id,record) in enumerate(list(records.items())):
                        if (kind=='reference' and record['quote']['venue']=='pinnacle' or
                                kind!='reference' and record['quote']['venue'] in ('kalshi','polymarket_us') and i%4==0):
                            r=deepcopy(record);q=r['quote'];prior_receipt=q['times']['received_at']
                            q['times']['received_at']=self.at.isoformat()
                            metadata=r.get('comparison_source_metadata',{})
                            if metadata.get('combined_native_binding') and metadata.get('observed_at')==prior_receipt:
                                metadata['observed_at']=self.at.isoformat()
                            if kind in ('material','reference'):
                                q['times'].update(source_at=self.at.isoformat(),source_time_kind='provider_quote' if kind=='reference' else 'provider_book')
                                if q.get('provider_clocks'):
                                    q['provider_clocks']=dict(q['provider_clocks'],book=self.at.isoformat(),selected_basis='book')
                                q.pop('book_confirmation',None)
                            if kind=='material':
                                price='0.37' if cycle_index%2==0 else '0.38'
                                q['original']['value']=price
                                if q['original'].get('transformation')=='one_minus_native_bid':q['original']['native_value']='0.63' if cycle_index%2==0 else '0.62'
                                elif 'native_value' in q['original']:q['original']['native_value']=price
                            elif kind=='reference':q['original']['value']='2.05' if cycle_index%2==0 else '2.10'
                            changed.append(r);records[record_id]=r
                    rows.upsert_records(changed,now=self.at.isoformat());self.state.write(self.service)
                    full=snapshots.capture(db,ordinary=True,event_ids=events,at=self.at.isoformat())
                    reused=snapshots.capture(db,ordinary=True,event_ids=events,at=self.at.isoformat(),capture_binding='controlled')
                    for value in (full,reused):
                        for field in ('id','capture_seconds','policy_identity'):value.pop(field,None)
                    self.assertEqual(reused,full)
                    self.assertEqual(len(full['quotes']),captured_count)
                    self.assertEqual(full['issues'],captured_issues)
                    full['id']=reused['id']='controlled-exact-input'
                    full['capture_seconds']=reused['capture_seconds']=0
                    with patch.object(snapshots,'utc',return_value=self.at.isoformat()),patch.object(live,'utc',return_value=self.at.isoformat()):
                        a=snapshots.calculate(full);b=snapshots.calculate(reused)
                        a.pop('id');b.pop('id');self.assertEqual(a,b)
                        expected_sources=sorted(json.dumps(r['source'],sort_keys=True) for r in a['rows'])
                        del a,b,full,reused
                        cycle=[]
                        for _ in range(20):
                            result=live.turn(db,capture_cache=output/'plans.json');cycle.append(result)
                            if result['remaining_components']==0:break
                        self.assertEqual(result['remaining_components'],0)
                    # Every incrementally captured member matches a complete
                    # recapture of its exact scope and evaluation clock.
                    price_paths=[]
                    from app.storage.store import hashed
                    for member_row in db.execute("SELECT c.id,s.inputs,r.result FROM comparison_publication c JOIN comparison_snapshot_result r ON r.id=c.result_id JOIN comparison_snapshot s ON s.id=r.snapshot_id WHERE c.kind='component'"):
                        saved=snapshots.unpack(member_row['inputs']);price_paths.append(saved.get('_price_capture'))
                        event_scope=sorted({hashed([q['original_record']['quote']['source']['provider'],q['original_record']['quote']['source']['native_event_id']]) for q in saved['quotes']+saved['references']})
                        oracle=snapshots.capture(db,ordinary=True,event_ids=event_scope,at=saved['captured_at'])
                        def exact(value):return {k:v for k,v in value.items() if k not in ('id','capture_seconds','_price_basis','_price_capture')}
                        for field in exact(oracle):
                            self.assertEqual(saved[field],oracle[field],(phase_key,member_row['id'],field))
                        self.assertEqual(exact(saved).keys(),exact(oracle).keys())
                        # Compare the actual immutable financial member, including
                        # every bound authority witness/pair, not just source IDs.
                        member_result=snapshots.unpack(member_row['result'])
                        oracle.update(id=saved['id'],capture_seconds=saved['capture_seconds'])
                        with patch.object(snapshots,'utc',return_value=member_result['calculated_at']):
                            expected=live.bind(snapshots.calculate(oracle,member_result['assumptions']),oracle,'ready')
                        expected['id']=member_result['id']
                        self.assertEqual(member_result,expected,(phase_key,member_row['id']))
                    retained=snapshots.unpack(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(member,)).fetchone()['result'],db=db)
                    self.assertEqual(retained,selected)
                    self.assertEqual(db.execute("SELECT result_id FROM comparison_result_reference WHERE kind='lease' AND holder=%s",(token['lease_id'],)).fetchone()['result_id'],member)
                    self.assertLessEqual(live.retained_bytes(db),live.MAX_BYTES)
                    root=snapshots.unpack(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(live.status(db)['result_id'],)).fetchone()['result'],db=db)
                    content=db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(root['id'],)).fetchone()['result']
                    read_started=perf_counter()
                    reused_read=snapshots.unpack(content,lazy=True,db=db,previous=prior_read)
                    read_seconds=perf_counter()-read_started
                    self.assertEqual(reused_read,snapshots.unpack(content,lazy=True,db=db))
                    reused_members=len(reused_read['component_slices'].keys()&prior_read['component_slices'].keys())
                    prior_read=reused_read
                    (output/(phase_key+'-census.json')).write_text(json.dumps(dict(root_rows=len(root['rows']),full_rows=len(expected_sources),components=db.execute("SELECT c.id,c.result_id,r.read_summary AS summary FROM comparison_publication c JOIN comparison_snapshot_result r ON r.id=c.result_id WHERE c.kind='component' ORDER BY c.id").fetchall()),default=str,indent=2))
                    self.assertEqual(sorted(json.dumps(r['source'],sort_keys=True) for r in root['rows']), expected_sources)
                    root_bytes=len(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(root['id'],)).fetchone()['result'])
                    flat_bytes=len(snapshots.pack_read(snapshots.defer_details(root)))
                    fragment_bytes=db.execute('SELECT COALESCE(sum(octet_length(read_fragment)),0) n FROM comparison_snapshot_result').fetchone()['n']
                    db.execute('VACUUM comparison_snapshot_result,comparison_snapshot')
                    physical=db.execute("SELECT COALESCE(p.relname,c.relname) relname,sum(pg_total_relation_size(c.oid))::bigint bytes "
                        "FROM pg_class c LEFT JOIN pg_inherits i ON i.inhrelid=c.oid LEFT JOIN pg_class p ON p.oid=i.inhparent "
                        "WHERE c.relnamespace='public'::regnamespace AND c.relkind='r' AND COALESCE(p.relname,c.relname)=ANY(%s) "
                        "GROUP BY COALESCE(p.relname,c.relname)",(['comparison_snapshot','comparison_snapshot_result'],)).fetchall()
                    churn.append(dict(price_paths=price_paths,kind=phase_key,changed=len(changed),turns=cycle,phase_seconds=perf_counter()-phase_started,physical=physical,retained_bytes=live.retained_bytes(db),
                        read_reuse_seconds=read_seconds,reused_members=reused_members,
                        root_bytes=root_bytes,equivalent_flat_root_bytes=flat_bytes,retained_fragment_bytes=fragment_bytes))
                # Adopt a coherent latest member for the exact originally
                # selected row. Verify both leases coexist until explicit swap.
                row_id=selected['rows'][0]['id']
                replacement=next(r['evidence_result_id'] for r in root['rows'] if r['id']==row_id)
                adopted=live.retain(db,replacement)
                latest_member=snapshots.unpack(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(replacement,)).fetchone()['result'])
                self.assertNotEqual(member,replacement)
                self.assertEqual(latest_member['id'],replacement)
                self.assertEqual(next(r for r in latest_member['rows'] if r['id']==row_id)['source'],selected['rows'][0]['source'])
                self.assertEqual(db.execute("SELECT count(*) n FROM comparison_result_reference WHERE kind='lease' AND holder=ANY(%s)",([adopted['lease_id'],token['lease_id']],)).fetchone()['n'],2)
                db.execute("DELETE FROM comparison_result_reference WHERE kind='lease' AND holder=%s",(token['lease_id'],))
                self.assertEqual(db.execute("SELECT result_id FROM comparison_result_reference WHERE kind='lease' AND holder=%s",(adopted['lease_id'],)).fetchone()['result_id'],replacement)
                db.execute("DELETE FROM comparison_result_reference WHERE kind='lease' AND holder=%s",(adopted['lease_id'],))
                self.assertIsNone(db.execute("SELECT holder FROM comparison_result_reference WHERE kind='lease' AND holder=%s",(token['lease_id'],)).fetchone())
            (output/'timings.json').write_text(json.dumps(dict(records=len(records),admission=timings,capture=capture_seconds,capture_ab=comparisons,incremental=incremental,churn=churn,active_finance=result,active_turns=turns,rows=len(root['rows']),numeric=numeric),indent=2))
