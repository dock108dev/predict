"""Authored global scheduling/protocol vectors; financial oracles are separate."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction as F
from unittest import TestCase
from unittest.mock import patch
from app.comparison.current_dependencies import digest, instant
from app.comparison.scanner_projection import Projection, Filters, validate_receipt
from app.comparison.scanner_finance import exact, BASES, dependencies
from tests.test_sc01_readiness import pair_rows, projection
from tests.test_ev09_n01 import AT


def frame(count=1):
    rows=[];inputs={};template=pair_rows()
    for index in range(count):
        items=deepcopy(template)
        for leg,i in enumerate(items):
            i['id']=f'{index}:{leg}';i['occurrence_id']=f'occurrence:{index:04}'
            i['native_key'][1]+=f':{index}'
            inputs[i['id']]=dict(quote=dict(original=dict(value=str(index+1)),times=dict(source_at=AT,received_at=AT)),
                profiles={},event=dict(id=i['occurrence_id']),group=dict(id='winner',period='full_game'))
        rows+=items
    result=projection(rows);result['engine_binding']='authored-engine'
    return result,inputs


def fake(pair,instruments,inputs,**kwargs):
    edge=F(inputs[pair['legs'][0]]['quote']['original']['value'])
    row=dict(category='covered_outcome_arb',metric=exact(edge),metric_basis=BASES['covered_outcome_arb'],
        conditioning='all_required_feasible_states',current=True,metrics=dict(complete_minimum_usd=exact((100+edge)*edge/100),decisive_minimum_usd=exact((100+edge)*edge/100),expected_profit_usd=None,deployed_capital_usd=str(100+edge),buffer_usd=str((100+edge)/200),buffer_applications=1),allocation=[],
        settlement_complete=True,state_profits={},reasons=[],size_basis='observed_legal_allocation',
        size_status='supported_size',supported_capital_usd=str(100+edge))
    return dict(rows=[row] if edge>0 else [],qualifying=edge>0,evaluated=True)


def immutable_capture(f,x):
    from app.storage.scanner_preparation import PreparationCache
    cache=PreparationCache()
    cache.put('authored',dict(instruments=f['instruments'],inputs=x),at=AT,
        until=(instant(AT)+timedelta(hours=1)).isoformat())
    shared=cache.get_shared('authored',at=AT)
    owned=deepcopy(f);owned['instruments']=list(shared['instruments'])
    return owned,dict(shared['inputs'])


class Global(TestCase):
    def make(self,n=1,evaluator=fake):
        self.now=AT
        p=Projection(clock=lambda:self.now,evaluator=evaluator)
        f,x=frame(n);p.ingest(f,x)
        return p,f,x

    def finish(self,p):
        while p.pending:p.drain()
        return p.view()

    def test_private_immutable_proofs_reuse_exact_facts_but_revalidate_clocks(self):
        from app.storage.store import encoded
        from app.storage.scanner_preparation import is_immutable_fact
        f,x=frame(2)
        for value in x.values():value['event']['unknown']={'items':[{'note':'preserved'}]}
        f,x=immutable_capture(f,x);self.now=AT;p=Projection(clock=lambda:self.now,evaluator=fake)
        with patch('app.comparison.scanner_projection.dependencies',wraps=dependencies) as owner, \
                patch('app.comparison.scanner_projection.validate_receipt',wraps=validate_receipt) as verify:
            p._ingest_capture(f,x,input_bytes_bound=len(encoded(x)));before=self.finish(p)
            self.assertEqual(owner.call_count,2);checked=verify.call_count
            self.now=(instant(AT)+timedelta(seconds=1)).isoformat()
            current=dict(f,revision='unrelated-whole-frame-revision',input_revision='unrelated-global-input')
            p._ingest_capture(current,dict(x),input_bytes_bound=len(encoded(x)));shown=self.finish(p)
            self.assertEqual(owner.call_count,2);self.assertGreater(verify.call_count,checked)
            self.assertEqual(p.evaluations,2)
            self.assertEqual([r['source_clocks'] for r in shown['rows']],[r['source_clocks'] for r in before['rows']])
            self.assertEqual([r['evaluated_at'] for r in shown['rows']],[AT,AT])
        self.assertIs(p.inputs['0:0'],x['0:0']);self.assertTrue(is_immutable_fact(x['0:0']))
        def ordinary(value):
            if isinstance(value,dict):
                self.assertIs(type(value),dict)
                for child in value.values():ordinary(child)
            elif isinstance(value,list):
                self.assertIs(type(value),list)
                for child in value:ordinary(child)
        ordinary(shown)
        original_price=shown['rows'][0]['positions'][0]['original_price']['value']
        shown['rows'][0]['positions'][0]['original_price']['value']='caller'
        self.assertEqual(p.view()['rows'][0]['positions'][0]['original_price']['value'],original_price)
        thawed=deepcopy(x);ordinary(thawed)
        thawed['0:0']['event']['unknown']['items'][0]['note']='caller'
        self.assertEqual(x['0:0']['event']['unknown']['items'][0]['note'],'preserved')

    def test_default_and_mutable_private_ingest_always_recompute_owner_proof(self):
        from app.storage.store import encoded
        f,x=frame();self.now=AT;p=Projection(clock=lambda:self.now,evaluator=fake)
        with patch('app.comparison.scanner_projection.dependencies',wraps=dependencies) as owner:
            for _ in range(2):p._ingest_capture(deepcopy(f),x,input_bytes_bound=len(encoded(x)));self.finish(p)
            self.assertEqual(owner.call_count,2);self.assertEqual(p._dependency_proofs,{})
            old=next(iter(p.rows.values()))['dependency_revision']
            x['0:0']['quote']['unknown_future_field']={'nested':['changed in same mutable object']}
            p._ingest_capture(deepcopy(f),x,input_bytes_bound=len(encoded(x)));self.finish(p)
            self.assertEqual(owner.call_count,3);self.assertNotEqual(next(iter(p.rows.values()))['dependency_revision'],old)
            frozen_f,frozen_x=immutable_capture(f,x)
            for _ in range(2):p.ingest(frozen_f,frozen_x);self.finish(p)
            self.assertEqual(owner.call_count,5);self.assertEqual(p._dependency_proofs,{})
            self.assertIs(type(p.inputs['0:0']),dict);self.assertIs(type(p.frame['instruments'][0]),dict)

    def test_immutable_proof_falls_back_for_identity_order_pair_context_and_temporal_changes(self):
        from app.storage.store import encoded
        from dataclasses import replace
        f,x=frame();f,x=immutable_capture(f,x);self.now=AT;p=Projection(clock=lambda:self.now,evaluator=fake)
        def install(current_f,current_x,policy=None):
            p._ingest_capture(current_f,current_x,input_bytes_bound=len(encoded(current_x)),policy=policy)
            self.finish(p)
        with patch('app.comparison.scanner_projection.dependencies',wraps=dependencies) as owner:
            install(f,x);self.assertEqual(owner.call_count,1)
            f,x=immutable_capture(deepcopy(f),deepcopy(x));install(f,x)  # Equal bytes, new immutable object identities.
            self.assertEqual(owner.call_count,2);self.assertEqual(p.evaluations,1)
            f=dict(f,pairs=deepcopy(f['pairs']));f['pairs'][0]['legs'].reverse();install(f,x)
            self.assertEqual(owner.call_count,3)
            f=dict(f,pairs=deepcopy(f['pairs']));f['pairs'][0]['id']='different-authored-pair';install(f,x)
            self.assertEqual(owner.call_count,4);self.assertEqual(len(p._dependency_proofs),1)
            install(f,x,replace(p.policy,buffer_rate='0.01'));self.assertEqual(owner.call_count,5)
            f=dict(f,engine_binding='different-engine');install(f,x);self.assertEqual(owner.call_count,6)
            with patch('app.comparison.scanner_projection.EVALUATOR','authored-new-version'), \
                    patch('app.comparison.scanner_finance.VERSION','authored-new-version'):
                install(f,x);self.assertEqual(owner.call_count,7)
            install(f,x);self.assertEqual(owner.call_count,8)
            for change in ('unknown','receipt','source','temporal'):
                with self.subTest(change=change):
                    plain_f,plain_x=deepcopy(f),deepcopy(x)
                    self.now=(instant(self.now)+timedelta(seconds=1)).isoformat()
                    previous=deepcopy(next(iter(p.rows.values())))
                    if change=='unknown':plain_x['0:0']['quote']['future_authority']={'nested':[{'meaning':'new'}]}
                    elif change=='receipt':
                        for i in plain_f['instruments']:
                            i['clocks']['received_at']=self.now;plain_x[i['id']]['quote']['times']['received_at']=self.now
                    elif change=='source':
                        for i in plain_f['instruments']:
                            i['clocks']['source_at']=self.now;plain_x[i['id']]['quote']['times']['source_at']=self.now
                    else:
                        deadline=(instant(self.now)+timedelta(seconds=5)).isoformat()
                        for i in plain_f['instruments']:i['expires_at']=deadline
                        plain_f['pairs'][0]['expires_at']=deadline
                    f,x=immutable_capture(plain_f,plain_x);count=owner.call_count;evals=p.evaluations;install(f,x)
                    self.assertEqual(owner.call_count,count+1)
                    current=next(iter(p.rows.values()))
                    if change=='receipt':
                        self.assertEqual(p.evaluations,evals);self.assertEqual(current['evaluated_at'],previous['evaluated_at'])
                    else:self.assertNotEqual(current['dependency_revision'],previous['dependency_revision'])

    def test_immutable_proof_metadata_caps_fall_back_and_prune_all_lifecycles(self):
        from app.storage.store import encoded
        f,x=frame(3);f,x=immutable_capture(f,x);self.now=AT;p=Projection(clock=lambda:self.now,evaluator=fake)
        def install(current_f=f,current_x=x):
            p._ingest_capture(current_f,current_x,input_bytes_bound=len(encoded(current_x)));self.finish(p)
        install();one_charge=next(iter(p._dependency_proofs.values()))[4]
        p.stop()
        with patch('app.comparison.scanner_projection.MAX_DEPENDENCY_PROOF_BYTES',one_charge), \
                patch('app.comparison.scanner_projection.dependencies',wraps=dependencies) as owner:
            install();install();self.assertEqual(owner.call_count,5)
            self.assertEqual(len(p.rows),3);self.assertEqual(len(p._dependency_proofs),1)
            self.assertLessEqual(p._dependency_proof_bytes,one_charge)
        install()
        reduced=dict(f,pairs=deepcopy(f['pairs'][:1]));legs=set(reduced['pairs'][0]['legs'])
        reduced['instruments']=[i for i in f['instruments'] if i['id'] in legs];subset={key:value for key,value in x.items() if key in legs}
        install(reduced,subset);self.assertEqual(set(p._dependency_proofs),{reduced['pairs'][0]['id']})
        for prior in p._dependency_proofs.values():
            for leg,facts in zip(prior[0],prior[1]):
                self.assertIs(facts[0],next(i for i in p.frame['instruments'] if i['id']==leg));self.assertIs(facts[1],p.inputs[leg])
        self.now=reduced['pairs'][0]['expires_at'];p.expire()
        self.assertEqual((p._dependency_proofs,p._dependency_proof_bytes),({},0))
        for action in ('stop','fail','epoch'):
            with self.subTest(action=action):
                self.now=AT;install();self.assertTrue(p._dependency_proofs)
                if action=='stop':p.stop()
                elif action=='fail':p.fail('authored failure')
                else:
                    with patch('app.comparison.scanner_projection.dependencies',wraps=dependencies) as owner:
                        install(dict(f,epoch='new-epoch'),x);self.assertEqual(owner.call_count,3)
                    p.stop()
                self.assertEqual((p._dependency_proofs,p._dependency_proof_bytes),({},0))

    def test_public_ingest_detaches_inputs_frame_and_pending_target_pairs(self):
        p,f,x=self.make()
        expected_frame,expected_inputs=deepcopy(f),deepcopy(x)
        pair_id=f['pairs'][0]['id']
        f['pairs'][0]['expires_at']=(instant(AT)-timedelta(seconds=1)).isoformat()
        f['instruments'][0]['predicate']['predicate']='caller-mutated-predicate'
        x['0:0']['quote']['original']['value']='0'
        x['0:0']['profiles']['caller-only']={'untrusted':'mutation'}
        self.assertEqual(p.frame,expected_frame)
        self.assertEqual(p.inputs,expected_inputs)
        self.assertEqual(p.targets[pair_id]['pair'],expected_frame['pairs'][0])
        self.finish(p)
        self.assertEqual(len(p.rows),1)
        self.assertEqual(next(iter(p.rows.values()))['metric']['value'],'1')

    def test_owned_capture_preserves_unknown_dependency_fields_and_receipt_clocks(self):
        from app.storage.store import encoded
        p,f,x=self.make();self.finish(p)
        before=deepcopy(next(iter(p.rows.values())))
        for meaning in ('first-unknown-value','second-unknown-value'):
            owned_frame,owned_inputs=deepcopy(f),deepcopy(x)
            owned_inputs['0:0']['quote']['new_authority_field']={'meaning':meaning}
            p._ingest_capture(owned_frame,owned_inputs,input_bytes_bound=len(encoded(owned_inputs)))
            self.assertEqual(len(p.pending),1)
            self.finish(p)
            current=next(iter(p.rows.values()))
            self.assertNotEqual(current['dependency_revision'],before['dependency_revision'])
            self.assertEqual(current['source_clocks'],before['source_clocks'])
            self.assertEqual(current['evaluated_at'],AT)
            before=deepcopy(current)
        self.assertEqual(p.evaluations,3)

    def test_private_capture_bound_rejects_bad_proof_before_mutating_authority(self):
        from dataclasses import replace
        from app.comparison.scanner_projection import MAX_INPUT_BYTES
        p,f,x=self.make();self.finish(p)
        before=deepcopy(p.rows);policy=p.policy
        for bound in (None,True,False,'4096',2.0,-1,0,1,MAX_INPUT_BYTES+1):
            with self.subTest(bound=bound),self.assertRaisesRegex(ValueError,'^scanner_capture_input_bound_invalid$'):
                p._ingest_capture(deepcopy(f),deepcopy(x),input_bytes_bound=bound,
                    policy=replace(policy,buffer_rate='0.01'))
            self.assertEqual(p.rows,before)
            self.assertIs(p.policy,policy)
            self.assertEqual(p.evaluations,1)

    def test_capture_and_public_capacity_equal_boundary_and_public_unknown_payload(self):
        from app.storage.store import encoded
        p,f,x=self.make()
        exact=len(encoded(x))
        with patch('app.comparison.scanner_projection.MAX_INPUT_BYTES',exact):
            p._ingest_capture(deepcopy(f),deepcopy(x),input_bytes_bound=exact)
            self.finish(p)
            self.assertEqual(len(p.rows),1)
            p.ingest(deepcopy(f),deepcopy(x))
            self.assertEqual(len(p.rows),1)
            changed=deepcopy(x)
            changed['0:0']['quote']['unknown_large_field']='must count this unknown payload'
            self.assertGreater(len(encoded(changed)),exact)
            p.ingest(deepcopy(f),changed)
            self.assertEqual(p.rows,{})
            self.assertIn('scanner_input_capacity',p.errors)

    def test_display_memo_reuses_only_presentation_and_rechecks_every_receipt(self):
        p,f,x=self.make(20)
        with patch.object(p,'_build_display_rows',wraps=p._build_display_rows) as build, \
                patch('app.comparison.scanner_projection.validate_receipt',wraps=validate_receipt) as verify:
            while p.pending:p.drain(maximum=1)
            p.publish()
            self.assertEqual(build.call_count,20)
            self.assertEqual(verify.call_count,sum(range(1,21))+20)
        before=p.publication
        with patch('app.comparison.scanner_projection.validate_receipt',side_effect=ValueError('fresh current proof refused')):
            with self.assertRaisesRegex(ValueError,'fresh current proof refused'):p.publish()
        self.assertEqual(p.publication,before)

    def test_display_memo_detaches_retained_evaluator_result_and_http_view(self):
        returned=[]
        def retains(*args,**kwargs):
            result=fake(*args,**kwargs);returned.append(result);return result
        p,f,x=self.make(evaluator=retains);self.finish(p)
        before=deepcopy(p.rows)
        returned[0]['rows'][0]['metric']['value']='999'
        returned[0]['rows'][0]['allocation'].append({'caller_mutation':'must not escape'})
        shown=p.view();shown['rows'][0]['metric']['value']='888'
        p.publish()
        self.assertEqual(p.rows,before)
        self.assertEqual(p.evaluations,1)

    def test_display_memo_replaces_exact_record_and_its_accounting_within_capture(self):
        p,f,x=self.make();self.finish(p);key=next(iter(p.cache))
        old=next(iter(p.rows.values()))['economic_revision']
        replacement=deepcopy(p.cache[key]);replacement['value']['rows'][0]['metric']=exact(2)
        p.cache[key]=replacement;p.publish()
        self.assertIs(p._display_memo[key][0],replacement)
        self.assertEqual(p._display_count,1)
        self.assertNotEqual(next(iter(p.rows.values()))['economic_revision'],old)
        replacement=deepcopy(replacement);replacement['value'].update(rows=[],qualifying=False)
        p.cache[key]=replacement;p.publish()
        self.assertEqual(p.rows,{})
        self.assertIs(p._display_memo[key][0],replacement)
        self.assertEqual(p._display_count,0)
        self.assertEqual(p._display_bytes,p._display_memo[key][2])

    def test_deferred_record_replacement_immediately_releases_old_memo_charge(self):
        p,f,x=self.make(2);self.finish(p)
        before=deepcopy(p.rows);publication=p.publication
        key,other=tuple(p.cache)
        other_charge=p._display_memo[other][2]
        for _ in range(3):
            old_record=p.cache[key]
            p.pending[key]=p.targets[key]
            p.drain(maximum=1,publish=False)
            self.assertIsNot(p.cache[key],old_record)
            self.assertNotIn(key,p._display_memo)
            self.assertEqual(p._display_bytes,other_charge)
            self.assertEqual(p._display_count,1)
            self.assertEqual(p.rows,before)
            self.assertEqual(p.publication,publication)
        p.publish()
        self.assertIs(p._display_memo[key][0],p.cache[key])
        self.assertEqual(p._display_bytes,sum(entry[2] for entry in p._display_memo.values()))
        self.assertEqual(p._display_count,2)

    def test_every_capture_rebuilds_display_for_receipt_price_and_context_changes(self):
        p,f,x=self.make()
        for value in x.values():value['quote']['original'].update(units='authored',payout='authored')
        with patch('app.dashboard.comparison_board.common_odds',side_effect=lambda q:{'price':q['original']['value']}), \
                patch.object(p,'_build_display_rows',wraps=p._build_display_rows) as build:
            p.ingest(f,x);self.finish(p)
            original=deepcopy(next(iter(p.rows.values())))
            evaluated=original['evaluated_at'];count=p.evaluations
            self.now=(instant(AT)+timedelta(seconds=1)).isoformat()
            f=deepcopy(f);x=deepcopy(x);f['revision']='receipt-only-capture'
            for instrument in f['instruments']:
                instrument['clocks']['received_at']=self.now
                x[instrument['id']]['quote']['times']['received_at']=self.now
            prior_builds=build.call_count;p.ingest(f,x);self.finish(p)
            receipt=next(iter(p.rows.values()))
            self.assertGreater(build.call_count,prior_builds)
            self.assertEqual(p.evaluations,count)
            self.assertEqual(receipt['evaluated_at'],evaluated)
            self.assertEqual(receipt['source_clocks'][0]['received_at'],self.now)
            self.assertEqual(receipt['positions'][0]['original_price'],original['positions'][0]['original_price'])
            x=deepcopy(x);x['0:0']['quote']['original']['value']='2';x['0:0']['event']['title']='Updated exact event display'
            p.ingest(f,x);self.finish(p)
            changed=next(iter(p.rows.values()))
            self.assertEqual(p.evaluations,count+1)
            self.assertNotEqual(changed['dependency_revision'],original['dependency_revision'])
            self.assertEqual(changed['positions'][0]['original_price']['value'],'2')
            self.assertEqual(changed['positions'][0]['common_odds']['price'],'2')
            self.assertEqual(changed['event_context']['title'],'Updated exact event display')

    def test_display_memo_caps_fall_back_without_dropping_rows_or_finance(self):
        for limits in ({'MAX_DISPLAY_BYTES':0},{'MAX_DISPLAY_PAIRS':1},{'MAX_DISPLAY_ROWS':1}):
            with self.subTest(limits=limits),patch.multiple('app.comparison.scanner_projection',**limits):
                p,f,x=self.make(3)
                while p.pending:p.drain(maximum=1)
                self.assertEqual(len(p.rows),3)
                self.assertEqual(p.evaluations,3)
                self.assertLessEqual(len(p._display_memo),1)
                self.assertLessEqual(p._display_count,1)
                if 'MAX_DISPLAY_BYTES' in limits:self.assertEqual(p._display_bytes,0)
                p.publish();self.assertEqual(len(p.rows),3);self.assertEqual(p.evaluations,3)

    def test_display_memo_clears_for_expiry_stop_failure_and_epoch(self):
        p,f,x=self.make(2);self.finish(p)
        self.assertTrue(p._display_memo)
        self.now=min((pair['expires_at'] for pair in f['pairs']),key=instant);p.expire()
        self.assertEqual((p._display_memo,p._display_bytes,p._display_count),({},0,0))
        for action in ('stop','fail'):
            with self.subTest(action=action):
                p,f,x=self.make();self.finish(p)
                if action=='stop':p.stop()
                else:p.fail('authored failure')
                self.assertEqual((p._display_memo,p._display_bytes,p._display_count),({},0,0))
        p,f,x=self.make();self.finish(p);f=deepcopy(f);f['epoch']='new-epoch'
        p.ingest(f,x)
        self.assertEqual((p._display_memo,p._display_bytes,p._display_count),({},0,0))
        self.assertEqual(p.rows,{})

    def test_global_best_on_later_occurrence_filters_before_top_n(self):
        p,f,x=self.make(30);self.finish(p)
        v=p.view(limit=2)
        self.assertEqual([r['occurrence_id'] for r in v['rows']],['occurrence:0029','occurrence:0028'])
        self.assertEqual(v['total_matching'],30)
        v=p.view(filters=Filters(minimum_edge='29'),limit=1)
        self.assertEqual(v['total_matching'],2)
        self.assertEqual(v['rows'][0]['metric']['value'],'30')
        self.assertEqual(p.view(filters=Filters(venues=('kalshi',)))['rows'],[])
        self.assertEqual(len(p.view(filters=Filters(minimum_size='129'))['rows']),2)
        self.assertEqual(p.view(filters=Filters(leagues=('NBA',)))['rows'],[])
        self.assertIn('leagues:NBA',p.view(filters=Filters(leagues=('NBA',)))['unsupported_filters'])

    def test_ties_stable_and_identity_native_predicates(self):
        p,f,x=self.make(3)
        for v in x.values():v['quote']['original']['value']='5'
        p.ingest(f,x);a=self.finish(p)
        self.assertEqual([r['occurrence_id'] for r in a['rows']],['occurrence:0000','occurrence:0001','occurrence:0002'])
        identity=a['rows'][0]['id'];count=p.evaluations
        changed=deepcopy(f);changed['revision']='scope-publication-change'
        p.ingest(changed,deepcopy(x));b=self.finish(p)
        self.assertEqual(p.evaluations,count);self.assertEqual(identity,b['rows'][0]['id'])
        changed['instruments'][0]['predicate']['predicate']='authored-different'
        p.ingest(changed,x);c=self.finish(p)
        self.assertNotEqual(identity,c['rows'][0]['id'])

    def test_receipt_only_whole_scope_churn_does_not_starve_completeness(self):
        p,f,x=self.make(35)
        for cycle in range(20):
            f=deepcopy(f);f['revision']=f'header-{cycle}'
            p.ingest(f,x);p.drain()
        self.assertEqual(p.evaluations,35)
        self.assertEqual(p.view()['coverage']['state'],'evaluated_positive')
        self.assertGreater(p.reuses,0)
        self.assertTrue(all(v['original_readiness_revision']!=f['revision'] for v in p.receipts.values()))

    def test_only_affected_pair_recalculates_and_policy_invalidates(self):
        p,f,x=self.make(4);self.finish(p);self.assertEqual(p.evaluations,4)
        x=deepcopy(x);x['2:0']['quote']['original']['value']='100'
        p.ingest(f,x);self.finish(p)
        self.assertEqual(p.evaluations,5)
        from dataclasses import replace
        p.policy=replace(p.policy,buffer_rate='0.01')
        p.ingest(f,x);self.finish(p);self.assertEqual(p.evaluations,9)

    def test_authoritative_zero_partial_unavailable_and_not_evaluated(self):
        p,f,x=self.make(2)
        self.assertEqual(p.view()['coverage']['state'],'not_evaluated')
        for v in x.values():v['quote']['original']['value']='0'
        p.ingest(f,x);p.drain(maximum=1)
        self.assertEqual(p.view()['coverage']['state'],'partial')
        self.assertFalse(p.view()['coverage']['complete'])
        self.finish(p);v=p.view()
        self.assertEqual(v['coverage']['state'],'evaluated_zero')
        self.assertTrue(v['coverage']['no_qualifying_opportunities'])
        for pair in f['pairs']:pair['input_check']['state']='blocked'
        p.ingest(f,x);self.assertFalse(p.view()['coverage']['no_qualifying_opportunities'])
        self.assertEqual(p.view()['coverage']['state'],'unavailable')

    def test_invalid_receipts_exact_dependencies_evaluator_and_clocks(self):
        p,f,x=self.make();self.finish(p);key=next(iter(p.receipts));r=p.receipts[key];pair=p.targets[key]['pair']
        dep=p.targets[key]['dependency']
        self.assertTrue(validate_receipt(r,pair,f,dep,evaluator_revision=p.evaluator_revision,at=AT))
        for change in (dict(dependency_revision='wrong'),dict(readiness_revision='stale'),dict(pair_id='not-member'),
                       dict(evaluator_revision='unknown'),dict(qualifying=1),dict(revalidated_at='2027-01-01T00:00:00Z')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_receipt(dict(r,**change),pair,f,dep,evaluator_revision=p.evaluator_revision,at=AT)

    def test_expiry_equality_without_packet_stop_restart_epoch(self):
        p,f,x=self.make();self.finish(p)
        self.now=f['pairs'][0]['expires_at']
        self.assertEqual(p.view()['rows'],[])
        self.assertFalse(p.view()['coverage']['no_qualifying_opportunities'])
        self.now=AT;p.ingest(f,x);self.finish(p);p.stop()
        self.assertEqual(p.view()['coverage']['state'],'stopped');self.assertEqual(p.rows,{})
        p.ingest(f,x);self.finish(p);self.assertEqual(len(p.rows),1)
        f=deepcopy(f);f['epoch']='new-epoch';p.ingest(f,x)
        self.assertEqual(p.rows,{})
        self.assertTrue(any(d['withdrawals'] for d in p.journal))

    def test_incremental_page_replacement_gap_filter_and_restart_resync(self):
        p,f,x=self.make(4);a=self.finish(p)
        args=dict(since=a['publication_revision'],epoch=a['epoch'],query_id=a['query_id'])
        self.assertEqual(p.view(**args)['mode'],'unchanged')
        x=deepcopy(x);x['0:0']['quote']['original']['value']='100';p.ingest(f,x);self.finish(p)
        b=p.view(**args);self.assertEqual(b['mode'],'replace_page')
        self.assertEqual(b['rows'][0]['occurrence_id'],'occurrence:0000')
        self.assertEqual(p.view(**dict(args,query_id='old-filter'))['mode'],'resync')
        self.assertEqual(p.view(**dict(args,epoch='old-epoch'))['mode'],'resync')
        with self.assertRaisesRegex(ValueError,'page_revision_changed'):p.view(offset=1,expected_revision=a['publication_revision'])
        for index in range(140):p._publish(p.rows,'authored-churn')
        self.assertEqual(p.view(**args)['mode'],'resync')
        self.assertLessEqual(len(p.journal),128)
        self.assertLessEqual(p.journal_bytes,4*1024**2)

    def test_changed_during_evaluation_and_stop_cannot_resurrect(self):
        p,f,x=self.make()
        def during(*args,**kwargs):
            p.stop();return fake(*args,**kwargs)
        p.evaluator=during;p.drain()
        self.assertEqual(p.rows,{})
        self.assertEqual(p.cache,{})

    def test_expiry_during_unpublished_drain_only_withdraws_and_preserves_survivors(self):
        p,f,x=self.make(3)
        f=deepcopy(f)
        f['pairs'][0]['expires_at']=(instant(AT)+timedelta(seconds=5)).isoformat()
        for pair in f['pairs'][1:]:pair['expires_at']=(instant(AT)+timedelta(seconds=20)).isoformat()
        p.ingest(f,x);p.drain(maximum=2)
        self.assertEqual(len(p.rows),2)
        survivor=next(row for row in p.rows.values() if row['occurrence_id']=='occurrence:0001')
        survivor_before=deepcopy(survivor)
        receipt_before=deepcopy(p.receipts[survivor['pair_id']])
        def crosses_expiry(*args,**kwargs):
            self.now=(instant(AT)+timedelta(seconds=5)).isoformat()
            return fake(*args,**kwargs)
        p.evaluator=crosses_expiry
        # The next loop's expire() sees an already completed, unpublished cache
        # result. It may withdraw the expired row, never grant new authority.
        p.drain(maximum=2,publish=False)
        self.assertEqual({row['occurrence_id'] for row in p.rows.values()},{'occurrence:0001'})
        self.assertEqual(next(iter(p.rows.values())),survivor_before)
        self.assertEqual(p.receipts,{survivor['pair_id']:receipt_before})
        unpublished=f['pairs'][2]['id']
        self.assertIn(unpublished,p.cache)
        self.assertNotIn(unpublished,p.receipts)
        self.assertEqual(p.state,'incomplete')
        self.assertIn('temporal_boundary_recapture_required',p.errors)
        self.assertIsNone(p.signature)
        self.assertEqual({row['occurrence_id'] for row in p.view()['rows']},{'occurrence:0001'})

    def test_key_churn_bounded_and_failures_incomplete(self):
        p,f,x=self.make(2);self.finish(p)
        for j in range(25):
            f=deepcopy(f);f['pairs'][0]['id']=f'changed-key-{j}'
            p.ingest(f,x);self.finish(p)
            self.assertLessEqual(len(p.cache),2);self.assertLessEqual(len(p.pending),2)
        p.fail('capacity_failure')
        v=p.view();self.assertEqual(v['coverage']['state'],'incomplete')
        self.assertFalse(v['coverage']['complete']);self.assertEqual(p.rows,{})

    def test_missing_finance_inputs_and_errors_cannot_report_checked_zero(self):
        p,f,x=self.make();p.ingest(f,{})
        self.assertFalse(p.view()['coverage']['complete'])
        p,f,x=self.make(evaluator=lambda *a,**kw:(_ for _ in ()).throw(ValueError('mandatory_cost_unknown')))
        self.finish(p);v=p.view()
        self.assertEqual(v['coverage']['state'],'incomplete')
        self.assertIsNone(v['coverage']['qualifying_pairs'])

    def test_cancellation_and_cache_capacity(self):
        from app.comparison.calculation_control import cancellation,CalculationStopped
        p,f,x=self.make()
        with self.assertRaises(CalculationStopped),cancellation(lambda:True):p.drain()
        big=deepcopy(f);big['pairs']=big['pairs']*2049
        p.ingest(big,x)
        self.assertEqual(p.view()['coverage']['state'],'incomplete')
        self.assertEqual(len(p.cache),0)


    def test_new_receipt_revalidates_without_backdating_or_new_finance(self):
        from app.comparison.scanner_projection import validate_receipts
        p,f,x=self.make();self.finish(p);evaluated=next(iter(p.receipts.values()))['evaluated_at']
        self.now=(instant(AT)+timedelta(seconds=1)).isoformat()
        f=deepcopy(f);x=deepcopy(x);f['revision']='receipt-publication'
        for i in f['instruments']:
            i['clocks']['received_at']=self.now
            x[i['id']]['quote']['times']['received_at']=self.now
        p.ingest(f,x);self.finish(p)
        self.assertEqual(p.evaluations,1)
        receipt=next(iter(p.receipts.values()))
        self.assertEqual(receipt['evaluated_at'],evaluated)
        self.assertEqual(receipt['revalidated_at'],self.now)
        with self.assertRaisesRegex(ValueError,'duplicate'):
            validate_receipts([receipt,receipt],f,{receipt['pair_id']:receipt['dependency_revision']},
                evaluator_revision=p.evaluator_revision,at=self.now)

    def test_mandatory_unknown_result_retains_conditional_but_incomplete_coverage(self):
        def unknown(*a,**kw):
            result=fake(*a,**kw);result['evaluation_complete']=False;return result
        p,f,x=self.make(evaluator=unknown);self.finish(p)
        self.assertEqual(p.view()['coverage']['state'],'incomplete')
        self.assertFalse(p.view()['coverage']['no_qualifying_opportunities'])
