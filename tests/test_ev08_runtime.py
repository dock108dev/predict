"""Canonical encoding, scoped probe reuse and selected-read regressions."""
from copy import deepcopy
import asyncio
from datetime import timedelta
import json
import unittest

from app.dashboard.current_contract import packed, serialize, quotes_of
from app.dashboard.current_state import CurrentStore
from tests.current_fixture import InjectedTestProvider, fixture
from app.comparison.estimated_consumer import AllocationInputs, consume
from app.comparison.effective_policy import effective_policy, recalculate
from app.comparison.metrics import snapshot_metrics
from app.comparison.current_details import selected
from app.comparison.estimated_pair import evaluate, Leg
from tests.test_ev05_funded import vector, AT
from tests.test_ev06_pairs import cross_group_workload
from app.comparison.estimated_policy import EstimatePolicy


class RuntimeRepairs(unittest.TestCase):
    def test_encoded_read_cache_is_bound_to_clock_revision_and_context(self):
        clock=[0];store=CurrentStore(InjectedTestProvider(),monotonic=lambda:clock[0]);calls=[]
        def build():calls.append(1);return packed(store._state)
        first=store.comparison_body(('policy','generation:1'),build)
        self.assertIs(store.comparison_body(('policy','generation:1'),build),first)
        self.assertEqual(len(calls),1)
        store.comparison_body(('policy','generation:2'),build);self.assertEqual(len(calls),2)
        clock[0]=1;store.refresh_age()
        aged=store.comparison_body(('policy','generation:2'),build)
        self.assertNotEqual(first,aged)
        raw=fixture();raw['runtime_id']='synthetic:new-runtime';store.commit(raw)
        revised=store.comparison_body(('policy','generation:2'),build)
        self.assertNotEqual(revised,aged)
        self.assertEqual(len(calls),4)
    def test_transport_write_bound_and_exact_body(self):
        from app.dashboard.current_response import BoundedBytes, WRITE_BYTES
        data=packed({'values':['é'*40000]*7})
        class Writer:
            def __init__(self):self.parts=[]
            async def write(self,part):
                self.parts.append(bytes(part))
                await asyncio.sleep(0)
        writer=Writer();asyncio.run(BoundedBytes(data).write(writer))
        self.assertEqual(b''.join(writer.parts),data)
        self.assertTrue(all(len(part)<=WRITE_BYTES for part in writer.parts))

    def test_completed_keepalive_response_releases_large_body(self):
        from app.dashboard.current_response import CurrentResponse
        data=packed({'text':'é'*200000})
        class Writer:
            output_size=0
            def __init__(self):self.parts=[]
            async def write(self,part):self.parts.append(bytes(part));self.output_size+=len(part)
            async def write_eof(self,data=b''):self.parts.append(data)
        response=CurrentResponse(body=data,content_type='application/json');writer=Writer()
        response._req=object();response._payload_writer=writer
        self.assertEqual(response.body,data)
        asyncio.run(response.write_eof())
        self.assertEqual(b''.join(writer.parts),data)
        self.assertIsNone(response.body)
    def test_encoding_exact_unicode_large_graph_and_refusals(self):
        values=[None,{},[],{3:'number key'},['é','🙂','\\\n"',True,False,1.5],
            {'events':[{'groups':[{'outcomes':[{'q':'é'*600000}]}]}]*3}]
        for value in values:
            self.assertEqual(packed(value),json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode())
        for value in (float('nan'),float('inf'),{'bad':object()},{1:0,'a':1}):
            with self.assertRaises((ValueError,TypeError)):packed(value)
        circular=[];circular.append(circular)
        with self.assertRaises(ValueError):packed(circular)

    def test_probe_reuse_matches_independent_allocation_calls_and_scope(self):
        q,profiles,_=vector();at=AT
        prepared=AllocationInputs(q,profiles,at)
        for quantity in ('17','531','1000'):
            for rich in (False,True):
                args=dict(at=at,native_quantity=quantity,retain_profiles=rich,settlement_metadata=True)
                self.assertEqual(packed(consume(q,profiles,**args,_inputs=prepared)),packed(consume(q,profiles,**args)))
        for wrong in (dict(q=deepcopy(q),profiles=profiles,at=at),dict(q=q,profiles=deepcopy(profiles),at=at),dict(q=q,profiles=profiles,at=at+timedelta(seconds=1))):
            with self.assertRaises(ValueError):consume(**wrong,native_quantity='17',_inputs=prepared)

    def test_selected_pairs_preserve_exact_results_across_groups(self):
        state=serialize(cross_group_workload(),allow_synthetic=True,estimate_policy=EstimatePolicy())
        pair=next(p for p in state['events'][0]['funded_pairs'] if p['legs'][0]['group_id']!=p['legs'][1]['group_id'])
        quote_id=pair['legs'][0]['quote_id']
        value=selected(state,quote_id,pair_id=pair['id'],pair_revision=pair['revision'])
        self.assertEqual(value['funded_pairs'][0]['revision'],pair['revision'])
        self.assertEqual(len(value['funded_pairs']),1)
        by_quote={q['id']:(g,q) for g in state['events'][0]['groups'] for o in g['outcomes'] for q in quotes_of(o)}
        policy=effective_policy(state['estimate_policy'],ceiling='500',buffer='0.01')
        from app.dashboard.current_contract import stamp
        legs=[Leg(by_quote[l['quote_id']][1],by_quote[l['quote_id']][0],state['comparison_profiles'],state['events'][0],stamp(state['clock_at'])) for l in pair['legs']]
        expected=evaluate(legs,policy=policy)
        resized=selected(state,quote_id,ceiling='500',buffer='0.01',pair_id=pair['id'],pair_revision=expected['revision'])
        self.assertEqual(resized['funded_pairs'][0]['revision'],expected['revision'])
        self.assertEqual(set(resized['leg_quotes']),{leg['quote_id'] for leg in pair['legs']})

    def test_readonly_metrics_and_override_do_not_mutate_publication(self):
        state=serialize(cross_group_workload(),allow_synthetic=True,estimate_policy=EstimatePolicy())
        before=packed(state)
        for filters in ({},{'venue':'kalshi'},{'results':'negative'},{'basis':'modeled_complete'}):
            self.assertEqual(packed(snapshot_metrics(state,**filters)),packed(snapshot_metrics(state,**filters,copy_graph=False)))
        changed=recalculate(state,effective_policy(state['estimate_policy'],ceiling='500'))
        self.assertIs(changed['comparison_profiles'],state['comparison_profiles'])
        self.assertEqual(packed(state),before)
        self.assertNotEqual(changed['estimate_policy'],state['estimate_policy'])
