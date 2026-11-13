"""Real PostgreSQL boundary proofs; no providers or production database."""
from unittest import skipUnless
from copy import deepcopy
from datetime import timedelta
from app.storage import observation_publication as publication
from app.storage import result_dependencies as units
from app.storage import latest_board as latest
from app.storage.comparison_board import discover
from tests.latest_board_fixture import LatestBoardFixture, SOCKET, inline_fixture_offers


@skipUnless(SOCKET, 'Explicit disposable PostgreSQL lane required')
class ResultDependenciesSQL(LatestBoardFixture):
    def assert_unselectable_parent_yields(self,refresh):
        from unittest.mock import patch
        from app.storage import result_inventory as inventory
        self.fresh_sources()
        with self.connect() as db:
            frame,bundle=self.capture(db)
            proof=inventory.proof(frame,publication.manifest(frame,bundle)['selector'],engine='retained',policy='retained')
            # Unknown membership cannot be declared withdrawn, but it is not
            # a selectable occurrence in the current complete catalog either.
            proof['selector']['events'].append('unobserved-member')
            ghost=dict(bundle,game_key='retained-unselectable-occurrence')
            inventory.record(db,ghost,[dict(id='pending-retained-unit',groups=['unknown'])],proof)
            # Finish fixture setup even under concurrent production load; an
            # eight-second setup yield leaves genuinely selectable siblings and
            # would no longer exercise the intended no-progress parent case.
            with patch('app.storage.result_publication.MAX_TURN_SECONDS',float('inf')):
                self.reconcile()
            before=db.execute('SELECT visit_order,visits FROM current_result_work WHERE game_key=%s',(ghost['game_key'],)).fetchone()
            self.assertEqual(before['visits'],0)
            if refresh:
                db.execute("UPDATE current_result_work SET refresh_order=nextval('current_result_refresh_order'),refresh_visit_order=visit_order WHERE game_key=%s",(ghost['game_key'],))
            captured=[];clock=[0.0];original=latest._reconcile
            def reconcile(*args,**kwargs):
                captured.append(set(kwargs['event_ids']))
                value=original(*args,**kwargs)
                clock[0]+=10
                return value
            # Run real SQL capture/calculation/publication for two parent
            # slices. The test clock bounds the loop, not the work or results.
            with patch.object(latest,'_reconcile',side_effect=reconcile),patch.object(latest,'monotonic',side_effect=lambda:clock[0]):
                result=latest.reconcile(db,at=self.at.isoformat(),admission={'estimates_window_turn':0 if refresh else 1},turn_seconds=20)
            self.assertEqual(len(captured),2,result)
            self.assertNotEqual(captured[0],captured[1])
            self.assertGreater(result['no_progress_parent_yields'],0,result)
            self.assertEqual(before,db.execute('SELECT visit_order,visits FROM current_result_work WHERE game_key=%s',(ghost['game_key'],)).fetchone())
            self.assertTrue(db.execute('SELECT active FROM current_result_work WHERE game_key=%s',(ghost['game_key'],)).fetchone()['active'])

    async def test_first_visit_turn_does_not_repeat_unselectable_parent(self):
        self.assert_unselectable_parent_yields(False)

    async def test_refresh_turn_does_not_repeat_unselectable_parent(self):
        self.assert_unselectable_parent_yields(True)

    async def test_hot_source_turn_survives_window_sort_and_quiet_turn_still_advances(self):
        from unittest.mock import patch
        from app.storage.pipeline_attempt import enqueue
        self.fresh_sources();self.reconcile()
        self.at+=timedelta(days=1,hours=19);self.state.write(self.service)
        calls=[];admission={}
        def capture(db,**kwargs):
            calls.append(kwargs['event_ids'])
            return dict(published=True,computed=0,reused=0,errors=[],inventory_complete=True)
        with self.connect() as db:
            rows=db.execute('SELECT publication_events FROM latest_board ORDER BY game_key').fetchall()
            self.assertEqual(len(rows),2)
            native={r['event_id'] for r in db.execute("SELECT event_id FROM current_contract WHERE venue IN ('kalshi','polymarket_us')")}
            hot=next(r['publication_events'] for r in rows if native.intersection(r['publication_events']))
            cold=next(r['publication_events'] for r in rows if r['publication_events']!=hot)
            inline_fixture_offers(db)
            db.execute('UPDATE current_offer SET source_at=%s',((self.at-timedelta(minutes=5)).isoformat(),))
            changed=db.execute("UPDATE current_offer SET source_at=%s WHERE contract_id IN (SELECT id FROM current_contract WHERE event_id=ANY(%s) AND venue IN ('kalshi','polymarket_us'))",((self.at-timedelta(seconds=1)).isoformat(),hot))
            self.assertGreater(changed.rowcount,0)
            enqueue(db,hot+cold,observations_only=True)
            def reset_attempts():
                for events,ago in ((hot,1),(cold,10)):
                    db.execute("UPDATE current_pipeline_attempt SET last_attempt=%s WHERE branch='raw_grid' AND event_id=ANY(%s)",(self.at-timedelta(minutes=ago),events))
            with patch.object(latest,'capture_batches',return_value=[cold,hot]),patch.object(latest,'_reconcile',side_effect=capture):
                reset_attempts()
                latest.reconcile(db,at=self.at.isoformat(),observations_only=True,admission=admission)
                self.assertEqual(calls[0],hot)
                calls.clear();reset_attempts()
                latest.reconcile(db,at=self.at.isoformat(),observations_only=True,admission=admission)
                self.assertEqual(calls[0],cold)

    async def test_inventory_survives_all_calculations_failing_before_any_seal(self):
        from unittest.mock import patch
        from app.storage.slate_reads import CapturedReads
        self.fresh_sources()
        with patch.object(latest,'calculate_current',side_effect=ValueError('source secret must not be retained')):
            self.reconcile()
        with self.connect() as db:
            inventories=db.execute('SELECT units FROM current_result_inventory').fetchall()
            self.assertTrue(inventories)
            self.assertTrue(all(row['units'] for row in inventories))
            self.assertEqual(db.execute('SELECT count(*) n FROM current_result_unit').fetchone()['n'],0)
            failures=db.execute("SELECT facts FROM pipeline_generation WHERE reason='result_unit_calculation_failed'").fetchall()
            self.assertTrue(failures)
            self.assertTrue(all(row['facts']['failure']['exception']=='ValueError' for row in failures))
            from app.storage.store import encoded
            self.assertNotIn(b'source secret',encoded(failures))
            reads=CapturedReads(resource_bytes=lambda:0)
            self.addCleanup(reads.clear)
            page,_=latest.slate(db,latest.load(),view='ev',filter='all',read_frames=reads)
            self.assertFalse(page['errors'])
            for board in page['boards']:
                self.assertGreater(board['result_unit_coverage']['pending'],0)
                self.assertEqual(board['delivery_state'],'pending')
                self.assertNotIn('result_units',board)
                self.assertTrue(board['pending_result_inventory'])
            import subprocess,json
            checked=subprocess.run(['node','--input-type=module','-e',
                "import {checkSlate,defaults} from './app/dashboard/opportunity_static/current/board-client.js'; let body='';for await(const chunk of process.stdin)body+=chunk;checkSlate(JSON.parse(body),{...defaults,view:'ev',filter:'all'});"],
                input=json.dumps(page),text=True,capture_output=True)
            self.assertEqual(checked.returncode,0,checked.stderr)

    async def test_thousand_units_traverse_durably_despite_arrivals_and_membership_revision(self):
        from app.storage import result_inventory as inventory
        with self.connect() as db:
            frame,bundle=self.capture(db)
            base=publication.manifest(frame,bundle)
            proof=inventory.proof(frame,base['selector'],engine='authored-engine',policy='authored-policy')
            units=[dict(id=f'original-{i:04}',groups=[str(i)]) for i in range(1000)]
            inventory.record(db,bundle,units,proof)
            seen=set()
            for turn in range(20):
                units.extend(dict(id=f'arrival-{turn}-{i}',groups=[str(i)]) for i in range(10))
                inventory.record(db,bundle,units,proof)
                for unit in inventory.ordered(db,bundle['game_key'],units)[:50]:
                    inventory.visit(db,bundle['game_key'],unit['id']);seen.add(unit['id'])
            self.assertTrue({f'original-{i:04}' for i in range(1000)}<=seen)
            before=inventory.ordered(db,bundle['game_key'],units)
        with self.connect() as db:
            self.assertEqual(before,inventory.ordered(db,bundle['game_key'],units))
            removed=units[:3];remaining=units[3:]
            inventory.record(db,bundle,remaining,proof)
            retired=db.execute('SELECT unit_id,active,reason,visits FROM current_result_work WHERE game_key=%s AND unit_id=ANY(%s)',
                (bundle['game_key'],[u['id'] for u in removed])).fetchall()
            self.assertTrue(all(not r['active'] and r['reason']=='inventory_revision_removed' and r['visits']==1 for r in retired))
            inventory.record(db,bundle,units,proof)
            self.assertEqual(len(inventory.ordered(db,bundle['game_key'],units)),len(units))
            db.execute("UPDATE current_result_inventory SET discovered_at=clock_timestamp()-interval '3 hours'")
            db.execute("UPDATE current_event SET scheduled_start=(clock_timestamp()+interval '1 day')::text WHERE id=ANY(%s)",
                (proof['selector']['events'],))
            inventory.prune(db)
            self.assertTrue(db.execute('SELECT 1 FROM current_result_inventory').fetchone())
            db.execute("UPDATE current_event SET scheduled_start=(clock_timestamp()-interval '1 day')::text WHERE id=ANY(%s)",
                (proof['selector']['events'],))
            inventory.prune(db)
            self.assertIsNone(db.execute('SELECT 1 FROM current_result_inventory').fetchone())
            unknown=deepcopy(proof);unknown['selector']['events'].append('missing-event-is-not-withdrawal')
            inventory.record(db,bundle,units,unknown)
            db.execute("UPDATE current_result_inventory SET discovered_at=clock_timestamp()-interval '3 hours'")
            inventory.prune(db)
            self.assertTrue(db.execute('SELECT 1 FROM current_result_inventory').fetchone())

    async def test_parent_priority_follows_oldest_unit_despite_hot_arrivals(self):
        from app.storage import result_inventory as inventory
        from app.storage.board_capture import prioritize_unit_waiters
        with self.connect() as db:
            frame,bundle=self.capture(db)
            base=publication.manifest(frame,bundle)
            proof=inventory.proof(frame,base['selector'],engine='e',policy='p')
            units=[dict(id=f'old-{i}',groups=[str(i)]) for i in range(10)]
            inventory.record(db,bundle,units,proof)
            old=proof['selector']['events']
            other=dict(bundle,game_key='authored-hot-parent')
            hot_id=db.execute('SELECT id FROM current_event WHERE NOT(id=ANY(%s)) LIMIT 1',(old,)).fetchone()['id']
            db.execute('UPDATE current_event SET scheduled_start=%s WHERE id=ANY(%s)',((self.at+timedelta(hours=1)).isoformat(),old+[hot_id]))
            hot_proof=deepcopy(proof);hot_proof['selector']['events']=[hot_id]
            inventory.record(db,other,[dict(id='hot',groups=['hot'])],hot_proof)
            for unit in units:
                self.assertEqual(prioritize_unit_waiters(db,[[hot_id],old],self.at.isoformat())[0],old)
                inventory.visit(db,bundle['game_key'],unit['id'])
            self.assertEqual(prioritize_unit_waiters(db,[old,[hot_id]],self.at.isoformat())[0],[hot_id])
            inventory.visit(db,other['game_key'],'hot')
            self.assertEqual(prioritize_unit_waiters(db,[[hot_id],old],self.at.isoformat())[0],old)

    async def test_inventory_proof_separates_execution_prices_from_structure(self):
        from app.storage import result_inventory as inventory
        with self.connect() as db:
            frame,bundle=self.capture(db);base=publication.manifest(frame,bundle)
            first=inventory.proof(frame,base['selector'],engine='e',policy='p')
            cid=next(iter(base['observations']))
            inline_fixture_offers(db,[cid])
            db.execute("UPDATE current_offer SET price_value='0.17',revision=revision||'-price' WHERE contract_id=%s",(cid,))
            changed=publication.capture(db,frame['states'])
            self.assertEqual(first,inventory.proof(changed,base['selector'],engine='e',policy='p'))
            db.execute('DELETE FROM current_offer WHERE contract_id=%s',(cid,))
            changed=publication.capture(db,frame['states'])
            self.assertNotEqual(first,inventory.proof(changed,base['selector'],engine='e',policy='p'))

    async def test_validated_catalog_supersedes_old_occurrence_without_treating_absence_as_withdrawal(self):
        from unittest.mock import patch
        from app.storage import result_inventory as inventory
        self.fresh_sources();self.reconcile()
        with self.connect() as db:
            frame,bundle=self.capture(db);base=publication.manifest(frame,bundle)
            proof=inventory.proof(frame,base['selector'],engine='retained',policy='retained')
            old=dict(bundle,game_key='authored-old-occurrence')
            units=[dict(id='old-unit',groups=['retained-group'])]
            inventory.record(db,old,units,proof)
            absent=dict(bundle,game_key='authored-unknown-member')
            unknown=deepcopy(proof);unknown['selector']['events'].append('unobserved-member')
            inventory.record(db,absent,units,unknown)
            original_publish=latest.publish
            def incomplete(connection,**kw):
                kw['status']=dict(kw['status'],scope_complete=False)
                return original_publish(connection,**kw)
            with patch.object(latest,'publish',side_effect=incomplete):
                latest._reconcile(db,at=self.at.isoformat(),event_ids=proof['selector']['events'],unit_priority=True)
            self.assertTrue(db.execute('SELECT active FROM current_result_work WHERE game_key=%s',(old['game_key'],)).fetchone()['active'])
            latest._reconcile(db,at=self.at.isoformat(),event_ids=proof['selector']['events'],unit_priority=True)
            retired=db.execute('SELECT active,reason FROM current_result_work WHERE game_key=%s',(old['game_key'],)).fetchone()
            self.assertEqual(retired,dict(active=False,reason='occurrence_inventory_superseded'))
            saved=db.execute('SELECT units,superseded_by FROM current_result_inventory WHERE game_key=%s',(old['game_key'],)).fetchone()
            self.assertEqual(saved['units'],units)
            self.assertIn(bundle['game_key'],saved['superseded_by'])
            self.assertTrue(db.execute('SELECT active FROM current_result_work WHERE game_key=%s',(absent['game_key'],)).fetchone()['active'])
            with self.assertRaisesRegex(ValueError,'result_inventory_capture_obsolete'):
                inventory.record(db,old,units,proof)
            self.at+=timedelta(seconds=1)
            inventory.record(db,dict(old,as_of=self.at.isoformat()),units,proof)
            self.assertTrue(db.execute('SELECT active FROM current_result_work WHERE game_key=%s',(old['game_key'],)).fetchone()['active'])

    async def test_serialized_ev_units_keep_authority_and_exact_selected_evidence(self):
        from unittest.mock import patch
        from app.storage.slate_reads import CapturedReads
        from psycopg.types.json import Jsonb
        self.fresh_sources()
        with patch.object(latest,'_control_barrier',return_value='authored-retained-control'):
            self.reconcile()
            with self.connect() as db:
                value=dict(boards={'ev':{'rows':['ev']},'arbs':{'rows':['other']}},
                    result_units={'unit':dict(facts=dict(selected_frame='exact original',boards={'ev':{'rows':['ev']},'arbs':{'rows':['other']}}))})
                compact=db.execute("SELECT current_result_read_facts(%s,'ev') facts",(Jsonb(value),)).fetchone()['facts']
                self.assertNotIn('boards',compact)
                child=compact['result_units']['unit']['facts']
                self.assertEqual(set(child['boards']),{'ev'})
                self.assertEqual(child['selected_frame'],'exact original')
                reads=CapturedReads(resource_bytes=lambda:0);self.addCleanup(reads.clear)
                page,_=latest.slate(db,latest.load(),view='ev',filter='all',read_frames=reads)
                self.assertFalse(page['errors'])
                states=[u for b in page['boards'] for u in b.get('result_units',[])]
                self.assertTrue(states)
                self.assertTrue(any(u['state']=='current' for u in states),states)

    async def test_reusable_discovery_sql_price_churn_selected_hydration_and_restart(self):
        from app.storage import discovery_index as index
        from app.storage.current_rows import contract_id
        from app.dashboard.comparison_board import entries
        from app.comparison.shared_templates import keys,resolve
        from unittest.mock import patch
        index.clear()
        def prepare(db):
            c=latest.read_context(db,at=self.at.isoformat())
            c.publication_runtime=latest.runtime_identity(latest.runtime(db,at=self.at.isoformat()))
            c.result_control=latest._control_barrier(db)
            c.publication_frame=publication.capture(db,c.source_status)
            observed=c.observation_bundles(game=self.first['game_key'])[0]
            return c,index.prepare(c,self.first['game_key'],latest.load(),observed)
        with self.connect() as db:
            inline_fixture_offers(db)
            c,first=prepare(db)
            self.assertFalse(first['_discovery_reused'])
            cid=next(contract_id(dict(quote=q)) for _,_,q in entries(first['state_inputs'])
                if q['original']['units']=='usd_per_contract' and q['original'].get('transformation') is None)
            db.execute("UPDATE current_offer SET price_value='0.37',revision=revision||'-churn' WHERE contract_id=%s",(cid,))
            c,warm=prepare(db)
            self.assertTrue(warm['_discovery_reused'])
            self.assertTrue(c.occurrence_index_reused)
            complete=discover(c.store,context=c,game=self.first['game_key'])[0]
            frame=publication.capture(db,c.source_status)
            self.assertEqual(publication.manifest(frame,warm),publication.manifest(frame,complete))
            calls=[]
            from app.storage.current_rows import CurrentRowStore
            hydrate=CurrentRowStore.hydrate_records
            def tracked(store,records,**kwargs):
                calls.append({contract_id(r) for r in records})
                return hydrate(store,records,**kwargs)
            for unit in warm['_discovery_plan']['units']:
                with patch.object(CurrentRowStore,'hydrate_records',tracked):
                    actual=index.hydrate(c,warm,unit,latest.load())
                expected=units.slice_bundle(complete,unit)
                for value in (actual,expected):
                    profiles=value['state_inputs']['comparison_profiles']
                    value['state_inputs']['comparison_profiles']={key:resolve(profiles,key) for key in keys(profiles)}
                self.assertEqual(actual['state_inputs'],expected['state_inputs'])
                self.assertEqual(units.capture(frame,warm,unit,sliced=actual),units.capture(frame,complete,unit,sliced=expected))
                self.assertEqual(calls[-1],set(warm['_discovery_plan']['contracts'][unit['id']]))
            unit=next(u for u in warm['_discovery_plan']['units'] if cid in warm['_discovery_plan']['contracts'][u['id']])
            db.execute("UPDATE current_offer SET price_value='0.39',revision=revision||'-after-capture' WHERE contract_id=%s",(cid,))
            with self.assertRaisesRegex(ValueError,'result_discovery_hydration_changed'):
                index.hydrate(c,warm,unit,latest.load())
            with db.transaction(),self.assertRaisesRegex(ValueError,'result_discovery_snapshot_required'):
                index.hydrate(c,warm,unit,latest.load())
            index.clear()
            self.assertFalse(prepare(db)[1]['_discovery_reused'])

    async def test_discovery_sql_candidate_removal_restore_reference_and_authority(self):
        from app.storage import discovery_index as index
        from app.storage.current_rows import contract_id
        index.clear()
        def prepare(db,control=None):
            c=latest.read_context(db,at=self.at.isoformat())
            c.publication_runtime=latest.runtime_identity(latest.runtime(db,at=self.at.isoformat()))
            c.result_control=control
            observed=c.observation_bundles(game=self.first['game_key'])[0]
            return index.prepare(c,self.first['game_key'],latest.load(),observed)
        with self.connect() as db:
            first=prepare(db)
            self.assertTrue(prepare(db)['_discovery_reused'])
            cid=next(contract_id(r) for r in first['records'] if r['quote']['venue']=='pinnacle')
            db.execute("UPDATE current_offer SET received_at=%s WHERE contract_id=%s",((self.at+timedelta(seconds=1)).isoformat(),cid))
            self.assertFalse(prepare(db)['_discovery_reused'])
            self.assertFalse(prepare(db,control='new-control')['_discovery_reused'])
            # A rollback restores membership, but must revalidate the old key.
            with db.transaction(force_rollback=True):
                ids=first['_discovery_plan']['contracts'][first['_discovery_plan']['units'][0]['id']]
                db.execute('DELETE FROM current_offer WHERE contract_id=%s',(ids[0],))
                self.assertFalse(prepare(db)['_discovery_reused'])
            restored=prepare(db)
            self.assertEqual(first['_discovery_plan'],restored['_discovery_plan'])

    def capture(self, db):
        context=latest.read_context(db,at=self.at.isoformat())
        frame=publication.capture(db,context.source_status)
        bundles=discover(context.store,context=context)
        bundle=max(bundles,key=lambda b:len(units.partitions(b)))
        return frame,bundle

    def check(self, db, saved):
        frame=publication.capture(db,latest.source_states({},latest.runtime(db,at=self.at.isoformat())))
        return units.reasons(frame,saved,at=self.at.isoformat())

    @staticmethod
    def invalid(check):
        return bool(check['all'] or any(check['observations'].values()) or any(check['comparisons'].values()))

    async def test_independent_market_price_and_required_selected_price(self):
        with self.connect() as db:
            frame,bundle=self.capture(db)
            partitions=units.partitions(bundle)
            self.assertGreater(len(partitions),1)
            saved=[units.capture(frame,bundle,u) for u in partitions]
            # Real offer value and its semantic revision change together.
            first=saved[0];other=next(v for v in saved[1:] if set(v['observations'])-set(first['observations']))
            cid=next(iter(set(other['observations'])-set(first['observations'])))
            inline_fixture_offers(db,[cid])
            db.execute("UPDATE current_offer SET price_value='0.17',revision=revision||'-price' WHERE contract_id=%s",(cid,))
            self.assertFalse(self.invalid(self.check(db,first)))
            self.assertTrue(self.invalid(self.check(db,other)))

    async def test_candidate_removal_invalidates_completeness(self):
        with self.connect() as db:
            frame,bundle=self.capture(db)
            saved=units.capture(frame,bundle,units.partitions(bundle)[0])
            cid=next(iter(saved['observations']))
            db.execute('DELETE FROM current_offer WHERE contract_id=%s',(cid,))
            checks=self.check(db,saved)
            self.assertIn('result_candidate_universe_changed',checks['all'])

    async def test_receipt_only_execution_and_reference_selection_order(self):
        with self.connect() as db:
            frame,bundle=self.capture(db)
            saved=units.capture(frame,bundle,units.partitions(bundle)[0])
            cid=next(iter(saved['observations']))
            inline_fixture_offers(db,[cid])
            db.execute("UPDATE current_offer SET received_at=%s WHERE contract_id=%s",(self.at.isoformat(),cid))
            self.assertFalse(self.invalid(self.check(db,saved)))
            refs=[cid for cid,r in frame['offers'].items() if r['venue']=='pinnacle' and r['event_id'] in {x[0] for x in publication.neighborhood(frame,saved['selector'])}]
            self.assertTrue(refs)
            db.execute("UPDATE current_offer SET received_at=%s WHERE contract_id=%s",(self.at.isoformat(),refs[0]))
            self.assertIn('result_candidate_universe_changed',self.check(db,saved)['all'])

    async def test_future_receipt_source_clock_and_temporal_boundary(self):
        with self.connect() as db:
            frame,bundle=self.capture(db)
            saved=units.capture(frame,bundle,units.partitions(bundle)[0])
            cid=next(iter(saved['observations']))
            inline_fixture_offers(db,[cid])
            db.execute('UPDATE current_offer SET received_at=%s WHERE contract_id=%s',((self.at+timedelta(seconds=1)).isoformat(),cid))
            self.assertIn('result_receipt_clock_invalid',self.check(db,saved)['observations'][cid])
            db.execute('UPDATE current_offer SET received_at=%s,source_at=%s WHERE contract_id=%s',(self.at.isoformat(),self.at.isoformat(),cid))
            self.assertTrue(self.invalid(self.check(db,saved)))
            boundary=saved['result_unit']['valid_until']
            self.assertIsNotNone(boundary)
            self.assertIn('result_temporal_boundary',units.reasons(frame,saved,at=boundary)['all'])

    async def test_independent_sql_seal_rejects_peer_and_preserves_newer(self):
        from unittest.mock import patch
        from app.storage import result_publication
        from app.storage.comparison_board import calculate_current
        from app.comparison.estimated_policy import DEFAULT_POLICY
        from app.storage.current_games import observation_binding
        with self.connect() as db:
            db.execute('TRUNCATE current_result_unit')
            context=latest.read_context(db,at=self.at.isoformat())
            owner=latest.runtime(db,at=self.at.isoformat())
            context.publication_runtime=latest.runtime_identity(owner)
            context.publication_frame=publication.capture(db,context.source_status)
            context.observation_binding=observation_binding()
            bundle=max(discover(context.store,context=context),key=lambda b:len(units.partitions(b)))
            partition=max(units.partitions(bundle),key=lambda u:len(units.capture(context.publication_frame,bundle,u)['result_unit']['peer_inputs']))
            sliced=units.slice_bundle(bundle,partition)
            manifest=units.capture(context.publication_frame,bundle,partition)
            value=calculate_current(sliced,DEFAULT_POLICY,context=context)
            facts=latest._selection_payload(deepcopy(sliced),sliced,value,DEFAULT_POLICY,context,dependencies=manifest)
            with patch('app.storage.result_publication.utc',return_value=self.at.isoformat()),patch('app.comparison.estimated_policy.load',return_value=DEFAULT_POLICY):
                first=result_publication.seal(db,bundle['game_key'],facts,calculated_at=value['calculated_at'])
                self.assertTrue(first['published'],first)
                again=result_publication.seal(db,bundle['game_key'],facts,calculated_at=value['calculated_at'])
                self.assertEqual(again['reason'],'newer_or_equal_result_unit')
                peer=next(iter(manifest['result_unit']['peer_inputs']))
                inline_fixture_offers(db,[peer])
                db.execute("UPDATE current_offer SET price_value='0.19',revision=revision||'-peer' WHERE contract_id=%s",(peer,))
                rejected=result_publication.seal(db,bundle['game_key'],facts,calculated_at=value['calculated_at'])
                self.assertFalse(rejected['published'])
                self.assertIn('result_candidate_input_changed',rejected['checks']['all'])
                self.assertEqual(db.execute('SELECT generation_id FROM current_result_unit').fetchone()['generation_id'],first['generation_id'])

    async def test_ordinary_read_withdraws_changed_unit_without_sibling_authority(self):
        from app.dashboard.comparison_board import expand_price_fields
        self.fresh_sources();self.reconcile()
        with self.connect() as db:
            saved=max(db.execute('SELECT game_key,facts FROM latest_board').fetchall(),
                      key=lambda r:len(r['facts'].get('result_units',{})))
            key=saved['game_key'];values=saved['facts']['result_units']
            self.assertGreater(len(values),1)
            before=expand_price_fields(latest.board(latest.snapshot(db,game=key,at=self.at.isoformat()),key,view='ev',filter='all'))
            current={u['unit_id'] for u in before['result_units'] if u['state']=='current'}
            self.assertGreater(len(current),1)
            affected=next(iter(current));manifest=values[affected]['facts']['publication_dependencies']
            cid=next(iter(manifest['observations']))
            independent=next(uid for uid in current-{affected}
                if cid not in values[uid]['facts']['publication_dependencies']['observations']
                and cid not in values[uid]['facts']['publication_dependencies']['result_unit']['peer_inputs'])
            inline_fixture_offers(db,[cid])
            db.execute("UPDATE current_offer SET price_value='0.23',revision=revision||'-meaningful' WHERE contract_id=%s",(cid,))
            after=expand_price_fields(latest.board(latest.snapshot(db,game=key,at=self.at.isoformat()),key,view='ev',filter='all'))
            states={u['unit_id']:u['state'] for u in after['result_units']}
            self.assertEqual(states[affected],'historical');self.assertEqual(states[independent],'current')
            self.assertEqual(after['result_unit_coverage']['total'],len(values))
            self.assertTrue(all(not r.get('ranking_eligible') for r in after['rows'] if r['result_unit_id']==affected))

    async def test_new_candidate_and_rule_change_invalidate_even_without_price_change(self):
        with self.connect() as db:
            frame,bundle=self.capture(db)
            saved=units.capture(frame,bundle,units.partitions(bundle)[0])
            record=deepcopy(next(r for r in bundle['records'] if r['quote']['venue'] in ('novig','prophetx')))
            record['quote']['source']['native_market_id']+='-new-candidate'
            from app.storage.current_rows import CurrentRowStore
            before=db.execute('SELECT count(*) n FROM current_offer').fetchone()['n']
            CurrentRowStore(db).upsert_records([record],now=self.at.isoformat())
            self.assertEqual(db.execute('SELECT count(*) n FROM current_offer').fetchone()['n'],before+1)
            self.assertIn('result_candidate_universe_changed',self.check(db,saved)['all'])
            frame,bundle=self.capture(db)
            saved=units.capture(frame,bundle,units.partitions(bundle)[0])
            cid=next(iter(saved['observations']))
            db.execute("UPDATE current_contract SET facts=jsonb_set(facts,'{result_policy}', '\"changed-authoritative-rule\"'::jsonb) WHERE id=%s",(cid,))
            self.assertTrue(self.invalid(self.check(db,saved)))

    async def test_source_pause_epoch_and_engine_policy_fail_closed(self):
        from app.storage.result_publication import validate,invalid
        from app.storage.current_games import engine_binding,observation_binding
        from app.comparison.estimated_policy import DEFAULT_POLICY
        with self.connect() as db:
            frame,bundle=self.capture(db);owner=latest.runtime(db,at=self.at.isoformat())
            saved=units.capture(frame,bundle,units.partitions(bundle)[0])
            facts=dict(publication_dependencies=saved,publication_runtime=latest.runtime_identity(owner),
                observation_binding=observation_binding(),context=dict(engine_binding=engine_binding(),policy_revision=DEFAULT_POLICY.revision))
            def check(**kw):return validate(frame,facts,at=self.at.isoformat(),owner=kw.get('owner',owner),engine=kw.get('engine',engine_binding()),policy=kw.get('policy',DEFAULT_POLICY.revision))
            self.assertFalse(invalid(check()))
            self.assertTrue(invalid(check(owner=dict(owner,active=False))))
            self.assertTrue(invalid(check(owner=dict(owner,paused_sources=['kalshi']))))
            self.assertTrue(invalid(check(engine='changed-engine')))
            self.assertTrue(invalid(check(policy='changed-policy')))
            frame['control_barrier']='stop-then-recover'
            self.assertTrue(invalid(check()))
            frame.pop('control_barrier');frame['epoch']='replacement-epoch'
            self.assertTrue(invalid(check()))

    def calculated_units(self,db):
        from app.storage.comparison_board import calculate_current
        from app.comparison.estimated_policy import DEFAULT_POLICY
        from app.storage.current_games import observation_binding
        context=latest.read_context(db,at=self.at.isoformat())
        context.publication_runtime=latest.runtime_identity(latest.runtime(db,at=self.at.isoformat()))
        context.publication_frame=publication.capture(db,context.source_status)
        context.observation_binding=observation_binding()
        bundle=max(discover(context.store,context=context),key=lambda b:len(units.partitions(b)))
        values=[]
        for unit in units.partitions(bundle)[:2]:
            sliced=units.slice_bundle(bundle,unit)
            manifest=units.capture(context.publication_frame,bundle,unit)
            value=calculate_current(sliced,DEFAULT_POLICY,context=context)
            facts=latest._selection_payload(deepcopy(sliced),sliced,value,DEFAULT_POLICY,context,dependencies=manifest)
            values.append((bundle['game_key'],facts,value['calculated_at']))
        return values

    async def test_repeated_seals_while_unrelated_market_changes(self):
        from app.storage.result_publication import seal
        self.fresh_sources();generations=[]
        for iteration in range(3):
            self.at+=timedelta(seconds=1);self.state.write(self.service)
            with self.connect() as db:
                first,second=self.calculated_units(db)
                selected=set(first[1]['publication_dependencies']['observations'])
                peer=set(first[1]['publication_dependencies']['result_unit']['peer_inputs'])
                other=next(iter(set(second[1]['publication_dependencies']['observations'])-selected-peer))
                inline_fixture_offers(db,[other])
                db.execute("UPDATE current_offer SET price_value=%s,revision=revision||%s WHERE contract_id=%s",(str(.2+iteration/100),'-unrelated'+str(iteration),other))
                result=seal(db,first[0],first[1],calculated_at=first[2]);self.assertTrue(result['published'],result)
                generations.append(result['generation_id'])
                # The changed sibling cannot borrow the first unit's authority.
                self.assertFalse(seal(db,second[0],second[1],calculated_at=second[2])['published'])
        self.assertEqual(len(set(generations)),3)

    async def test_concurrent_siblings_lock_timeout_cancellation_and_failure_release(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch
        from psycopg.errors import LockNotAvailable
        from app.storage.result_publication import seal
        from app.storage.current_rows import LOCK
        from app.comparison.calculation_control import CalculationStopped
        self.fresh_sources()
        with self.connect() as db:first,second=self.calculated_units(db)
        def publish(item):
            with self.connect() as db:return seal(db,item[0],item[1],calculated_at=item[2])
        with self.connect() as blocker,blocker.transaction():
            blocker.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            with self.connect() as db:
                db.execute("SET lock_timeout='40ms'")
                with self.assertRaises(LockNotAvailable):seal(db,first[0],first[1],calculated_at=first[2])
                self.assertEqual(db.execute('SELECT 1 n').fetchone()['n'],1)
        with patch('app.storage.result_publication.checkpoint',side_effect=[None,CalculationStopped('authored cancellation')]):
            with self.assertRaises(CalculationStopped):publish(first)
        with patch('app.storage.result_publication.validate',side_effect=ValueError('authored failure after locks')):
            with self.assertRaises(ValueError):publish(first)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(publish,[first,second]))
        self.assertTrue(all(r['published'] for r in results),results)
        with self.connect() as db:self.assertEqual(db.execute('SELECT count(*) n FROM current_result_unit').fetchone()['n'],2)

    async def test_selected_unit_evidence_survives_replacement_pruning_and_restart_read(self):
        from concurrent.futures import ThreadPoolExecutor
        from app.storage.slate_reads import CapturedReads
        from app.storage.store import encoded
        from app.storage.result_publication import prune
        self.fresh_sources();self.reconcile();reads=CapturedReads(resource_bytes=lambda:0)
        self.addCleanup(reads.clear)
        with self.connect() as db:
            frame=latest.snapshot(db,at=self.at.isoformat());key=max(frame['rows'],key=lambda k:len(frame['rows'][k]['facts']['result_units']))
            row=frame['rows'][key];before=deepcopy(row['facts']['result_units'])
            captured=reads.capture({},[reads.freeze(encoded(dict(game_key=key,row=row)))],context='completed',authority='fixture')
        def selected():return reads.selection(captured.token,key)[0]['facts']['result_units']
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(selected) for _ in range(2)]
            with self.connect() as db:
                db.execute("UPDATE current_result_unit SET published_at=clock_timestamp()-interval '3 hours'")
                prune(db)
                self.assertEqual(db.execute('SELECT count(*) n FROM current_result_unit').fetchone()['n'],0)
            self.assertTrue(all(f.result()==before for f in futures))
        self.assertEqual(selected(),before)
        # A new connection reconstructs retained selected evidence from the
        # parent projection; pruning working units never rewrites those inputs.
        with self.connect() as db:
            after=latest.snapshot(db,game=key,at=self.at.isoformat())
            restored=after['rows'][key]['facts']['result_units']
            self.assertEqual(set(restored),set(before))
            from app.storage.store import stamp
            for uid in before:
                self.assertEqual(restored[uid]['facts'],before[uid]['facts'])
                self.assertEqual(stamp(restored[uid]['calculated_at']),stamp(before[uid]['calculated_at']))

    async def test_bounded_unit_turn_keeps_pending_inventory_and_rotates(self):
        from unittest.mock import patch
        from app.storage import result_publication
        self.fresh_sources()
        with patch.object(result_publication,'MAX_TURN_SECONDS',0):self.reconcile()
        with self.connect() as db:
            rows=db.execute('SELECT game_key,facts FROM latest_board').fetchall()
            first={r['game_key']:set(r['facts']['result_units']) for r in rows if len(r['facts']['result_unit_inventory'])>1}
            self.assertTrue(first)
            for row in rows:
                if row['game_key'] not in first:continue
                self.assertEqual(len(row['facts']['result_units']),1)
                self.assertGreater(len(row['facts']['result_unit_inventory']),1)
            self.at+=timedelta(seconds=1);self.state.write(self.service)
        with patch.object(result_publication,'MAX_TURN_SECONDS',0):self.reconcile()
        with self.connect() as db:
            for row in db.execute('SELECT game_key,facts FROM latest_board'):
                if row['game_key'] not in first:continue
                self.assertGreater(len(row['facts']['result_units']),len(first[row['game_key']]))
                self.assertTrue(first[row['game_key']]<=set(row['facts']['result_units']))

    async def test_oldest_unit_batch_does_not_spend_slices_on_younger_games(self):
        from app.storage import result_inventory
        self.reconcile()
        with self.connect() as db:
            games=[r['game_key'] for r in db.execute('SELECT game_key FROM current_result_inventory ORDER BY game_key')]
            self.assertGreaterEqual(len(games),2)
            first,second=games[:2]
            for row in db.execute('SELECT unit_id FROM current_result_work WHERE game_key=%s',(second,)).fetchall():
                result_inventory.visit(db,second,row['unit_id'])
            before={r['game_key']:r['visits'] for r in db.execute('SELECT game_key,sum(visits) visits FROM current_result_work GROUP BY game_key')}
            # Both complete parent frames require a fresh engine pass. Their
            # immutable child evidence remains available for valid unit reuse.
            db.execute("UPDATE latest_board SET facts=jsonb_set(facts,'{context,engine_binding}','\"previous-engine\"'::jsonb)")
            older=db.execute('SELECT facts FROM latest_board WHERE game_key=%s',(second,)).fetchone()['facts']
            result=latest._reconcile(db,at=self.at.isoformat(),unit_priority=True)
            after={r['game_key']:r['visits'] for r in db.execute('SELECT game_key,sum(visits) visits FROM current_result_work GROUP BY game_key')}
            self.assertGreater(after[first],before[first])
            self.assertEqual(after[second],before[second])
            self.assertIn(second,result['deferred_game_keys'])
            self.assertFalse(result['inventory_complete'])
            self.assertEqual(db.execute('SELECT facts FROM latest_board WHERE game_key=%s',(second,)).fetchone()['facts'],older)
            latest._reconcile(db,at=self.at.isoformat(),unit_priority=True)
            final=db.execute('SELECT sum(visits) n FROM current_result_work WHERE game_key=%s',(second,)).fetchone()['n']
            self.assertGreater(final,after[second])

    async def test_capacity_reclaims_outside_work_but_preserves_originals_and_unknown_inventory(self):
        from unittest.mock import patch
        from app.storage.result_publication import seal,prune
        from app.storage.store import encoded
        self.fresh_sources();self.reconcile()
        self.at+=timedelta(seconds=1);self.state.write(self.service)
        with self.connect() as db:
            first,_=self.calculated_units(db)
            other=db.execute('SELECT game_key,facts FROM latest_board WHERE game_key<>%s LIMIT 1',(first[0],)).fetchone()
            key=other['game_key'];original=deepcopy(other['facts'])
            events=db.execute('SELECT events FROM current_result_inventory WHERE game_key=%s',(key,)).fetchone()['events']
            # Missing schedule is uncertainty, not authority to reclaim.
            db.execute("UPDATE current_event SET scheduled_start='' WHERE id=ANY(%s)",(events,))
            before=db.execute('SELECT count(*) n FROM current_result_unit WHERE game_key=%s',(key,)).fetchone()['n']
            prune(db)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_result_unit WHERE game_key=%s',(key,)).fetchone()['n'],before)
            db.execute('UPDATE current_event SET scheduled_start=%s WHERE id=ANY(%s)',((self.at-timedelta(hours=1)).isoformat(),events))
            uid=first[1]['publication_dependencies']['result_unit']['id']
            remaining=db.execute('SELECT coalesce(sum(retained_bytes),0) n FROM current_result_unit WHERE game_key<>%s AND NOT(game_key=%s AND unit_id=%s)',(key,first[0],uid)).fetchone()['n']
            limit=int(remaining)+len(encoded(first[1]))+100
            with patch('app.storage.result_publication.MAX_BYTES',limit):
                result=seal(db,first[0],first[1],calculated_at=first[2])
            self.assertTrue(result['published'],result)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_result_unit WHERE game_key=%s',(key,)).fetchone()['n'],0)
            self.assertEqual(db.execute('SELECT facts FROM latest_board WHERE game_key=%s',(key,)).fetchone()['facts'],original)
            restored=latest.snapshot(db,game=key,at=self.at.isoformat())['rows'][key]['facts']['result_units']
            import json
            for child in original['result_units'].values():
                pointer=child['facts'].get('selected_frame')
                if isinstance(pointer,dict) and pointer.get('original_packet'):
                    packet=db.execute('SELECT packet FROM current_grid_blob WHERE id=%s',
                        (pointer['original_packet'],)).fetchone()['packet']
                    child['facts']['selected_frame']=json.loads(bytes(packet))
            self.assertEqual(restored,original['result_units'])

    async def test_obsolete_authority_reclaim_requires_exact_retained_parent_original(self):
        from app.storage.result_publication import prune
        self.fresh_sources();self.reconcile()
        with self.connect() as db:
            before={r['game_key']:deepcopy(r['facts']) for r in db.execute('SELECT game_key,facts FROM latest_board')}
            # Test-only engine transition; current-engine units remain untouched.
            from unittest.mock import patch
            prune(db)
            count=db.execute('SELECT count(*) n FROM current_result_unit').fetchone()['n']
            self.assertGreater(count,0)
            orphan=db.execute('SELECT game_key,unit_id FROM current_result_unit LIMIT 1').fetchone()
            # A parent with a different generation is not a preserved copy.
            db.execute("UPDATE latest_board SET facts=jsonb_set(facts,ARRAY['result_units',%s,'generation_id'],'\"different\"'::jsonb) WHERE game_key=%s",(orphan['unit_id'],orphan['game_key']))
            with patch('app.storage.result_publication.engine_binding',return_value='new-engine'):
                prune(db)
            rows=db.execute('SELECT game_key,unit_id FROM current_result_unit').fetchall()
            self.assertEqual(rows,[orphan])
            for row in db.execute('SELECT game_key,facts FROM latest_board'):
                for uid,unit in row['facts']['result_units'].items():
                    self.assertEqual(unit['facts'],before[row['game_key']]['result_units'][uid]['facts'])

    async def test_changed_sealed_unit_refreshes_before_unvisited_siblings_without_removing_their_turn(self):
        from unittest.mock import patch
        from app.storage import result_publication
        from app.storage.board_capture import refresh_waiters,prioritize_refresh_waiters
        from app.storage.current_games import engine_binding
        self.fresh_sources()
        with patch.object(result_publication,'MAX_TURN_SECONDS',0):self.reconcile()
        self.at+=timedelta(seconds=1);self.state.write(self.service)
        with self.connect() as db:
            chosen=db.execute("SELECT u.game_key,u.unit_id,u.generation_id,u.facts,i.events FROM current_result_unit u JOIN current_result_inventory i USING(game_key) WHERE jsonb_array_length(i.units)>1 ORDER BY u.game_key LIMIT 1").fetchone()
            key=chosen['game_key'];uid=chosen['unit_id']
            pending=db.execute('SELECT count(*) n FROM current_result_work WHERE game_key=%s AND visits=0',(key,)).fetchone()['n']
            self.assertGreater(pending,0)
            ids=list(chosen['facts']['publication_dependencies']['observations'])
            inline_fixture_offers(db,ids)
            changed=db.execute("UPDATE current_offer SET price_value='0.37',revision=revision||'-required-refresh',received_at=%s WHERE contract_id=(SELECT id FROM current_contract WHERE id=ANY(%s) AND venue IN ('kalshi','polymarket_us') LIMIT 1) RETURNING contract_id",(self.at.isoformat(),ids)).fetchone()
            self.assertIsNotNone(changed)
            waiters=refresh_waiters(db,self.at.isoformat(),engine=engine_binding(),runtime_id=self.service.runtime_id)
            self.assertTrue(any(r['unit_id']==uid for r in waiters))
            self.assertEqual(prioritize_refresh_waiters([['unrelated-arrival'],chosen['events']],waiters)[0],chosen['events'])
            with patch.object(result_publication,'MAX_TURN_SECONDS',0):
                result=latest._reconcile(db,at=self.at.isoformat(),event_ids=chosen['events'],unit_priority=True,refresh_candidates=waiters)
            self.assertTrue(result['published'],result)
            refreshed=db.execute('SELECT generation_id,facts FROM current_result_unit WHERE game_key=%s AND unit_id=%s',(key,uid)).fetchone()
            self.assertNotEqual(refreshed['generation_id'],chosen['generation_id'])
            self.assertTrue(refreshed['facts']['unit_stage_timings']['refresh_priority'])
            self.assertEqual(db.execute('SELECT count(*) n FROM current_result_work WHERE game_key=%s AND visits=0',(key,)).fetchone()['n'],pending)
            board=latest.board(latest.snapshot(db,game=key,at=self.at.isoformat()),key,view='ev',filter='all')
            self.assertTrue(any(u['unit_id']==uid and u['state']=='current' for u in board['result_units']))
            with patch.object(result_publication,'MAX_TURN_SECONDS',0):
                latest._reconcile(db,at=self.at.isoformat(),event_ids=chosen['events'],unit_priority=True)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_result_work WHERE game_key=%s AND visits=0',(key,)).fetchone()['n'],pending-1)

    async def test_later_dirty_old_visit_cannot_overtake_durable_refresh_waiter(self):
        from unittest.mock import patch
        from app.storage import result_publication
        from app.storage.board_capture import refresh_waiters
        from app.storage.current_games import engine_binding
        self.fresh_sources();self.reconcile()
        with self.connect() as db:
            rows=db.execute('SELECT u.*,w.visit_order,w.visits,i.events FROM current_result_unit u JOIN current_result_work w USING(game_key,unit_id) JOIN current_result_inventory i USING(game_key) ORDER BY w.visit_order').fetchall()
            older,younger=next((a,b) for a in rows for b in rows if a['game_key']==b['game_key']
                and a['visit_order']<b['visit_order'] and not set(a['facts']['publication_dependencies']['observations'])&set(b['facts']['publication_dependencies']['observations']))
        def dirty(db,row):
            ids=list(row['facts']['publication_dependencies']['observations'])
            inline_fixture_offers(db,ids)
            changed=db.execute("UPDATE current_offer SET price_value='0.37',revision=revision||'-queue-change',received_at=%s WHERE contract_id=(SELECT id FROM current_contract WHERE id=ANY(%s) AND venue IN ('kalshi','polymarket_us') LIMIT 1) RETURNING contract_id",(self.at.isoformat(),ids)).fetchone()
            self.assertIsNotNone(changed)
        self.at+=timedelta(seconds=1);self.state.write(self.service)
        with self.connect() as db:
            dirty(db,younger)
            first=refresh_waiters(db,self.at.isoformat(),engine=engine_binding(),runtime_id=self.service.runtime_id,enqueue=True)
            queued=next(r for r in first if r['unit_id']==younger['unit_id'])
            self.assertNotIn(older['unit_id'],{r['unit_id'] for r in first})
        # A fresh connection models loss of the scheduling process. The older
        # visit becomes dirty later; the persisted waiter must retain its place.
        self.at+=timedelta(seconds=1);self.state.write(self.service)
        with self.connect() as db:
            dirty(db,older)
            waiting=refresh_waiters(db,self.at.isoformat(),engine=engine_binding(),runtime_id=self.service.runtime_id,enqueue=True)
            order={r['unit_id']:r['refresh_order'] for r in waiting}
            self.assertEqual(order[younger['unit_id']],queued['refresh_order'])
            self.assertLess(order[younger['unit_id']],order[older['unit_id']])
            # A new runtime and reclaimed redundant working copy must not
            # erase already-earned queue positions. This is only scheduling;
            # _reconcile below reconstructs and validates the complete inputs.
            db.execute('DELETE FROM current_result_unit WHERE game_key=%s AND unit_id=%s',
                (younger['game_key'],younger['unit_id']))
            waiting=refresh_waiters(db,self.at.isoformat(),engine=engine_binding(),runtime_id='replacement-runtime',enqueue=True)
            restored={r['unit_id']:r['refresh_order'] for r in waiting}
            self.assertEqual(order[younger['unit_id']],restored[younger['unit_id']])
            self.assertEqual(order[older['unit_id']],restored[older['unit_id']])
            with patch.object(result_publication,'MAX_TURN_SECONDS',0):
                latest._reconcile(db,at=self.at.isoformat(),event_ids=younger['events'],unit_priority=True,refresh_candidates=waiting)
            counts={r['unit_id']:r['visits'] for r in db.execute('SELECT unit_id,visits FROM current_result_work WHERE game_key=%s',(younger['game_key'],))}
            self.assertEqual(counts[younger['unit_id']],younger['visits']+1)
            self.assertEqual(counts[older['unit_id']],older['visits'])
            refresh_waiters(db,self.at.isoformat(),engine=engine_binding(),runtime_id=self.service.runtime_id,enqueue=True)
            self.assertIsNone(db.execute('SELECT refresh_order FROM current_result_work WHERE game_key=%s AND unit_id=%s',(younger['game_key'],younger['unit_id'])).fetchone()['refresh_order'])
            db.execute('UPDATE current_result_work SET active=false WHERE game_key=%s AND unit_id=%s',(older['game_key'],older['unit_id']))
            refresh_waiters(db,self.at.isoformat(),engine=engine_binding(),runtime_id=self.service.runtime_id,enqueue=True)
            self.assertIsNone(db.execute('SELECT refresh_order FROM current_result_work WHERE game_key=%s AND unit_id=%s',(older['game_key'],older['unit_id'])).fetchone()['refresh_order'])


    async def test_pending_version_race_is_not_acknowledged_by_older_claim(self):
        from app.storage import result_inventory as inventory
        self.fresh_sources()
        with self.connect() as db:
            frame,bundle=self.capture(db)
            proof=inventory.proof(frame,publication.manifest(frame,bundle)['selector'],engine='test',policy='test')
            inventory.record(db,bundle,[dict(id='racing-key',groups=[])],proof)
            token=inventory.visit(db,bundle['game_key'],'racing-key')
            # An independently committed new input races with the old worker.
            with self.connect() as writer:
                writer.execute("UPDATE current_result_work SET pending_version=pending_version+1 WHERE unit_id='racing-key'")
            inventory.acknowledge(db,bundle['game_key'],'racing-key',token)
            row=db.execute("SELECT * FROM current_result_work WHERE unit_id='racing-key'").fetchone()
            self.assertGreater(row['pending_version'],row['acknowledged_version'])
            self.assertIsNotNone(row['dirty_since'])
        # Failure/restart does not consume the remaining version.
        with self.connect() as db:
            newer=inventory.visit(db,bundle['game_key'],'racing-key')
            self.assertGreater(newer,token)
            inventory.acknowledge(db,bundle['game_key'],'racing-key',newer)
            row=db.execute("SELECT * FROM current_result_work WHERE unit_id='racing-key'").fetchone()
            self.assertEqual(row['pending_version'],row['acknowledged_version'])
            self.assertIsNone(row['dirty_since'])

    async def test_burst_pending_cardinality_tracks_keys_and_failed_claim_rotates(self):
        from app.storage import result_inventory as inventory
        self.fresh_sources()
        with self.connect() as db:
            frame,bundle=self.capture(db)
            proof=inventory.proof(frame,publication.manifest(frame,bundle)['selector'],engine='test',policy='test')
            population=[dict(id='burst-'+str(n),groups=[]) for n in range(4000)]
            inventory.record(db,bundle,population,proof)
            # 100,000 replacements across 4,000 dependency units; no job rows.
            for _ in range(25):
                db.execute("UPDATE current_result_work SET pending_version=pending_version+1 WHERE game_key=%s",(bundle['game_key'],))
            row=db.execute("SELECT count(*) n,min(pending_version) v FROM current_result_work WHERE game_key=%s",(bundle['game_key'],)).fetchone()
            self.assertEqual(row,dict(n=4000,v=26))
            first=inventory.ordered(db,bundle['game_key'],population)[0]
            inventory.visit(db,bundle['game_key'],first['id'])
            self.assertNotEqual(inventory.ordered(db,bundle['game_key'],population)[0]['id'],first['id'])
            self.assertEqual(db.execute("SELECT count(*) n FROM current_result_work WHERE pending_version>acknowledged_version").fetchone()['n'],4000)


    async def test_seal_rejects_superseding_queue_version_and_retry_acknowledges(self):
        from app.storage import result_inventory as inventory,result_publication
        self.fresh_sources();self.reconcile()
        with self.connect() as db:
            row=db.execute('SELECT * FROM current_result_unit ORDER BY game_key,unit_id LIMIT 1').fetchone()
            key,uid=row['game_key'],row['unit_id']
            token=inventory.visit(db,key,uid)
            with self.connect() as writer:
                writer.execute('UPDATE current_result_work SET pending_version=pending_version+1,dirty_since=clock_timestamp() WHERE game_key=%s AND unit_id=%s',(key,uid))
            rejected=result_publication.seal(db,key,row['facts'],calculated_at=row['calculated_at'],work_version=token)
            self.assertEqual(rejected['reason'],'newer_pending_result_version')
            work=db.execute('SELECT * FROM current_result_work WHERE game_key=%s AND unit_id=%s',(key,uid)).fetchone()
            self.assertGreater(work['pending_version'],work['acknowledged_version'])
            token=inventory.visit(db,key,uid)
            result_publication.seal(db,key,row['facts'],calculated_at=row['calculated_at'],work_version=token)
            work=db.execute('SELECT * FROM current_result_work WHERE game_key=%s AND unit_id=%s',(key,uid)).fetchone()
            self.assertEqual(work['pending_version'],work['acknowledged_version'])
