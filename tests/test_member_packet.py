import unittest
from app.storage import member_packet as packet
from app.storage.comparison_snapshot import unpack


class MemberPacket(unittest.TestCase):
    def test_private_structure_reuse_requires_same_evidence_and_order(self):
        value=dict(games=[{'id':'game'}],references=[],_price_basis=dict(catalogs=[{'exact':10**90}]),
            quotes=[dict(id=str(n),original_record=dict(event={'id':'event'},comparison_source_metadata=
                dict(receipt_source='原本',observed_at='first',count=10**80),quote={'price':'0.005'})) for n in range(2)])
        first,_=packet.encode(value)
        new,prior=packet.read(first,borrow=True)
        new['quotes'][0]['original_record']['comparison_source_metadata']['observed_at']='second'
        new['quotes'][0]['original_record']['quote']['price']='0.0051'
        second,reused=packet.encode(new,prior)
        self.assertGreater(reused,0);self.assertEqual(unpack(second),new);self.assertEqual(unpack(first),value)
        for change in ('event','metadata','order'):
            revised,parts=packet.read(second,borrow=True)
            record=revised['quotes'][0]['original_record']
            if change=='event':record['event']={'id':'replacement'}
            if change=='metadata':record['comparison_source_metadata']['count']=False
            if change=='order':revised['quotes'].reverse()
            blob,reused=packet.encode(revised,parts)
            self.assertEqual(reused,0,change);self.assertEqual(unpack(blob),revised)
            self.assertEqual(unpack(first),value)
