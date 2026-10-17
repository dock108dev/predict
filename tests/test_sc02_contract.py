"""Portable consumer protocol examples and independently checked schema shape."""
from copy import deepcopy
from pathlib import Path
from unittest import TestCase
import json
from tests.test_sc02_projection import frame,fake
from tests.test_ev09_n01 import AT
from app.comparison.scanner_projection import Projection


def examples():
    f,x=frame(3);p=Projection(clock=lambda:AT,evaluator=fake);cold=p.view();p.ingest(f,x)
    while p.pending:p.drain()
    snapshot=p.view();args=dict(since=snapshot['publication_revision'],epoch=snapshot['epoch'],query_id=snapshot['query_id'])
    unchanged=p.view(**args)
    x=deepcopy(x);x['0:0']['quote']['original']['value']='99';p.ingest(f,x)
    while p.pending:p.drain()
    changed=p.view(**args);resync=p.view(**dict(args,epoch='missed-epoch'))
    receipt=next(iter(p.receipts.values()))
    p.stop();stopped=p.view(**args)
    return dict(cold=cold,snapshot=snapshot,unchanged=unchanged,changed=changed,resync=resync,stopped=stopped,receipt=receipt)


class Contract(TestCase):
    def test_authored_examples_and_exact_protocol_field_inventory(self):
        values=examples();base=Path(__file__).resolve().parents[1]
        schema=json.loads((base/'docs/contracts/predict-opportunity-scanner-1.schema.json').read_text())
        for name,value in values.items():
            if name=='receipt':continue
            self.assertEqual(set(value),set(schema['required']))
            self.assertEqual(value['version'],'predict-opportunity-scanner-1')
            self.assertEqual(value['provider_requests'],0)
            self.assertLessEqual(len(value['rows']),100)
        self.assertEqual(values['changed']['mode'],'replace_page')
        self.assertEqual(values['stopped']['ranked_ids'],[])
        self.assertEqual(values['resync']['mode'],'resync')
