"""Exact old financial/clock evidence survives bounded domain delta history."""
import json
from hashlib import sha256
import struct
import unittest
from app.storage.domain_delta import (make_delta,apply_delta,encode_header,restore,
    scope_for_record,MAX_BYTES,compress,decompress)

class DomainDelta(unittest.TestCase):
    def evidence(self):
        return json.dumps(dict(participant='Città',source_at='2026-10-14T00:00:00.000000002Z',
            price='0.4800',unknown=None,depth=[{'price':str(n/10000),'quantity':'1.0000'} for n in range(400)]),ensure_ascii=False,sort_keys=True).encode()
    def test_changed_clock_price_depth_and_original_nulls_reconstruct_exact_bytes(self):
        old=self.evidence()
        for new in (old,old.replace(b'.000000002Z',b'.000000003Z'),old.replace(b'0.4800',b'0.4900'),old.replace(b'1.0000',b'9.3210'),b' { "value": null }\n'):
            with self.subTest(new=new[:30]):
                delta=make_delta(old,new);self.assertEqual(apply_delta(old,delta,len(new)),new)
                self.assertEqual(restore(encode_header(sha256(old).hexdigest(),new,delta),old),new)
    def test_copy_bounds_and_expanded_length_are_verified(self):
        for patch in (b'C'+struct.pack('>II',20,99),b'L'+struct.pack('>I',3)+b'x',b'X',b'C'):
            with self.subTest(patch=patch),self.assertRaises(ValueError):apply_delta(b'original',patch,8)
        with self.assertRaises(ValueError):apply_delta(b'x',b'L'+struct.pack('>I',2)+b'xx',1)
        with self.assertRaises(ValueError):apply_delta(b'x',b'',True)
    def test_anchor_and_original_hashes_refuse_wrong_bytes(self):
        base=self.evidence();new=base.replace(b'0.4800',b'0.4900')
        packed=encode_header(sha256(base).hexdigest(),new,make_delta(base,new))
        with self.assertRaises(ValueError):restore(packed,base+b'corruption')
        with self.assertRaises(ValueError):restore(packed.replace(sha256(new).hexdigest(),'0'*64),base)
    def test_domain_scope_retains_instrument_identity_and_does_not_use_new_receipt_time(self):
        row={'source':'kalshi','kind':'admitted_books','value':{'observations':[{'book':{'raw':{'ref':{'event_id':'game1','market_id':'home'}}}}]}}
        before=scope_for_record(row);row['retained_at']='2026-10-14T00:01:00Z'
        self.assertEqual(scope_for_record(row),before)
        row['value']['observations'][0]['book']['raw']['ref']['market_id']='away'
        self.assertNotEqual(scope_for_record(row),before)
    def test_stored_stream_memory_size_and_trailing_bytes_are_bounded(self):
        body=compress(self.evidence())
        self.assertEqual(decompress(body),self.evidence())
        for bad in (body[:-3],body+compress(b'another')):
            with self.assertRaises(ValueError):decompress(bad)
        with self.assertRaises(ValueError):decompress(body,12)
        with self.assertRaises(ValueError):make_delta(b'',b'x'*(MAX_BYTES+1))

if __name__=='__main__':unittest.main()
