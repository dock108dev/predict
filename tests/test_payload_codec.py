"""Physical payload encoding cannot change original JSON bytes or financial values."""
import base64
from hashlib import sha256
import json
import lzma
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

from app.storage import payload_codec as codec
from app.storage.store import encoded


class PayloadCodec(unittest.TestCase):
    def original(self):
        return encoded(dict(price='0.1234567890123456789',participant='Città',null=None,
            clock='2026-10-14T00:00:00.000000002+00:00',evidence=['unchanged original'] * 4096)).decode()

    def wrapped(self, original, *, size=None, digest=None, tail=b'', legacy=False, filters=None):
        body=original.encode()
        compressed=zlib.compress(body) if legacy else lzma.compress(body,format=lzma.FORMAT_XZ,filters=filters or codec.XZ_FILTERS)
        prefix=codec.LEGACY_PREFIX if legacy else codec.PREFIX
        return prefix + str(len(body) if size is None else size) + ':' + (digest or sha256(body).hexdigest()) + ':' + base64.b64encode(compressed+tail).decode()

    def test_exact_utf8_strings_nulls_and_clocks_survive_compact_round_trip(self):
        original=self.original();packed=codec.encode(original)
        self.assertTrue(packed.startswith(codec.PREFIX))
        self.assertLess(len(packed),len(original.encode())//10)
        self.assertEqual(codec.decode(packed).encode(),original.encode())
        self.assertEqual(json.loads(codec.decode(packed)),json.loads(original))
        self.assertEqual(codec.encode(packed),packed)

    def test_legacy_json_and_short_payloads_keep_exact_whitespace(self):
        original=' { "price" : "0.4800", "unknown": null }\n'
        self.assertEqual(codec.decode(original),original)
        self.assertEqual(codec.encode(original),original)

    def test_legacy_zlib_reads_exactly_and_new_writes_use_version_two(self):
        original=self.original();legacy=self.wrapped(original,legacy=True)
        self.assertEqual(codec.decode(legacy).encode(),original.encode())
        repacked=codec.encode(legacy)
        self.assertTrue(repacked.startswith(codec.PREFIX))
        self.assertEqual(codec.decode(repacked),original)

    def test_corrupt_hash_truncated_stream_and_trailing_stream_refuse(self):
        original=self.original()
        for legacy in (False,True):
            for packed in (self.wrapped(original,digest='0'*64,legacy=legacy),
                           self.wrapped(original,tail=b'extra',legacy=legacy),
                           self.wrapped(original,legacy=legacy)+base64.b64encode(b'another').decode()):
                with self.subTest(legacy=legacy,packed=packed[:80]),self.assertRaises(ValueError):codec.decode(packed)
            packed=self.wrapped(original,legacy=legacy)
            head,body=packed.rsplit(':',1)
            truncated=head+':'+base64.b64encode(base64.b64decode(body)[:-1]).decode()
            with self.assertRaises(ValueError):codec.decode(truncated)

    def test_declared_length_is_checked_before_unbounded_inflation(self):
        for legacy in (False,True):
            packed=self.wrapped('x'*1024*1024,size=12,legacy=legacy)
            with self.assertRaisesRegex(ValueError,'length_or_stream'):codec.decode(packed)
            with self.assertRaisesRegex(ValueError,'logical_capacity'):
                codec.decode(self.wrapped('x',size=codec.MAX_LOGICAL_BYTES+1,legacy=legacy))
        with patch.object(codec,'MAX_LOGICAL_BYTES',3),self.assertRaisesRegex(ValueError,'logical_capacity'):
            codec.encode('1234')

    def test_malformed_encoding_never_becomes_plain_legacy_data(self):
        for prefix in codec.PREFIXES:
            for value in (prefix,prefix+'1:bad:!',prefix+'1:'+'a'*64+':!',None,b'json'):
                with self.subTest(value=value),self.assertRaises(ValueError):codec.decode(value)

    def test_xz_memory_limit_rejects_unapproved_dictionary(self):
        packed=self.wrapped(self.original(),filters=[dict(id=lzma.FILTER_LZMA2,preset=0,dict_size=32*1024*1024)])
        with self.assertRaisesRegex(ValueError,'encoding_invalid'):codec.decode(packed)

    def test_xz_multiple_streams_and_invalid_utf8_refuse(self):
        original=self.original()
        trailing=lzma.compress(b'another',format=lzma.FORMAT_XZ,filters=codec.XZ_FILTERS)
        with self.assertRaisesRegex(ValueError,'length_or_stream'):codec.decode(self.wrapped(original,tail=trailing))
        raw=b'\xff';body=lzma.compress(raw,format=lzma.FORMAT_XZ,filters=codec.XZ_FILTERS)
        packed=codec.PREFIX+'1:'+sha256(raw).hexdigest()+':'+base64.b64encode(body).decode()
        with self.assertRaisesRegex(ValueError,'encoding_invalid'):codec.decode(packed)

    def test_shared_row_factory_only_decodes_payload_and_keeps_metadata(self):
        from psycopg.pq import ExecStatus
        names=('id','payload','payload_sha256','stored_payload')
        cursor=SimpleNamespace(connection=None,pgresult=SimpleNamespace(status=ExecStatus.TUPLES_OK,nfields=len(names),fname=lambda i:names[i].encode()),_encoding='utf-8')
        original=self.original();packed=codec.encode(original);digest=sha256(original.encode()).hexdigest()
        make_row=codec.payload_row(cursor)
        row=make_row(('immutable-id',packed,digest,packed))
        self.assertEqual(row,dict(id='immutable-id',payload=original,payload_sha256=digest,stored_payload=packed))
        self.assertEqual(make_row(('legacy-id','{}','hash','{}'))['payload'],'{}')
        self.assertEqual(make_row(('version-one',self.wrapped(original,legacy=True),digest,'physical'))['payload'],original)


if __name__ == '__main__':
    unittest.main()
