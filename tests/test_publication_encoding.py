"""Disposable oversized publication regressions, without provider calls."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch
from app.comparison.readiness_encoding import compact, expand, transport_size
from app.comparison.scanner_readiness import MAX_BYTES
from app.storage.store import encoded
from tests.test_sc01_readiness import pair_rows, projection


class PublicationEncoding(TestCase):
    def test_wide_board_name_growth_preserves_every_literal_and_clock(self):
        from app.dashboard.comparison_board import compact_price_fields, expand_price_fields, MAX_RESPONSE
        original = dict(prices=[dict(quote_id=str(n), quote_revision='revision:'+str(n),
            times={'source_at':'2026-10-22T21:00:00Z','received_at':'2026-10-22T21:00:01Z'},
            original={'value':'0.4700','units':'probability'},
            **{f'inspectable_source_fact_{k:02}_long_provenance':f'{n}:{k}:'+('x'*120) for k in range(30)}) for n in range(110)])
        self.assertGreater(len(encoded(original)), MAX_RESPONSE)
        wire = compact_price_fields(deepcopy(original))
        self.assertIn('price_key_pool', wire)
        self.assertLess(len(encoded(wire)), MAX_RESPONSE)
        self.assertEqual(expand_price_fields(deepcopy(wire)), original)
        self.assertEqual(compact_price_fields(deepcopy(wire)), wire)
        bad = deepcopy(wire)
        bad['prices'][0]['999999'] = 'crossed'
        with self.assertRaisesRegex(ValueError, 'comparison_field_reference_conflict'):
            expand_price_fields(bad)

    def test_complete_readiness_above_old_limit_preserves_peers_and_identity(self):
        a, b = pair_rows()
        rows = []
        for n in range(2400):
            for source in (a, b):
                row = deepcopy(source)
                row['id'] += ':' + str(n)
                row['occurrence_id'] += ':' + str(n)
                rows.append(row)
        result = projection(rows)
        self.assertGreater(len(encoded(result)), MAX_BYTES)
        self.assertLess(transport_size(result), MAX_BYTES)
        wire = compact(result)
        self.assertEqual(expand(wire), result)
        self.assertEqual(len(result['pairs']), 2400)
        self.assertEqual(len(result['instruments']), 4800)
        self.assertEqual({leg for p in result['pairs'] for leg in p['legs']}, {i['id'] for i in rows})
        restored = expand(wire)
        restored['instruments'][0]['checks']['execution']['state'] = 'changed'
        self.assertNotEqual(restored['instruments'][1]['checks']['execution']['state'], 'changed')
        self.assertEqual(expand(wire), result)

    def test_exact_transport_boundary_and_one_byte_overflow(self):
        result = projection(pair_rows())
        size = transport_size(result)
        with patch('app.comparison.scanner_readiness.MAX_BYTES', size):
            self.assertEqual(projection(pair_rows()), result)
        with patch('app.comparison.scanner_readiness.MAX_BYTES', size - 1):
            with self.assertRaisesRegex(ValueError, 'readiness_response_capacity'):
                projection(pair_rows())

    def test_references_are_validated_and_native_reference_shaped_values_are_literal(self):
        result = projection(pair_rows())
        result['instruments'][0]['native_extra'] = {'field_refs': {'x': 0}}
        wire = compact(result)
        self.assertEqual(expand(wire), result)
        bad = deepcopy(wire)
        refs = bad['instruments']['rows'][0][1]
        self.assertTrue(refs)
        refs[0][1] = len(wire['field_pool'])
        with self.assertRaisesRegex(ValueError, 'readiness_field_reference_invalid'):
            expand(bad)
        bad = deepcopy(wire)
        bad['instruments']['rows'][0][0].append(deepcopy(bad['instruments']['rows'][0][0][0]))
        with self.assertRaisesRegex(ValueError, 'readiness_field_reference_invalid'):
            expand(bad)

    def test_financial_rows_share_frozen_values_without_losing_any_result(self):
        from app.dashboard.comparison_board import compact_price_fields, expand_price_fields, MAX_RESPONSE
        shared={'basis':'authored scenario', 'evidence':['exact original '+str(i) for i in range(250)]}
        original=dict(view='ev',prices=[],rows=[dict(quote_id=str(n),quote_revision='r'+str(n),
            modeled_basis=deepcopy(shared),financial_metrics={'conditional_net_ev_usd':str(n-55)},
            availability={'state':'numeric_current','reason_codes':[]}) for n in range(110)])
        self.assertGreater(len(encoded(original)),MAX_RESPONSE)
        wire=compact_price_fields(deepcopy(original))
        self.assertLess(len(encoded(wire)),MAX_RESPONSE)
        self.assertEqual(expand_price_fields(deepcopy(wire)),original)
        self.assertEqual(compact_price_fields(deepcopy(wire)),wire)
        restored=expand_price_fields(deepcopy(wire))
        restored['rows'][0]['modeled_basis']['basis']='changed'
        self.assertEqual(restored['rows'][1]['modeled_basis'],shared)
        for index in (-1,True,len(wire['financial_field_pool'])):
            bad=deepcopy(wire);bad['rows'][0]['financial_field_refs']['modeled_basis']=index
            with self.assertRaisesRegex(ValueError,'financial_field_reference_conflict'):expand_price_fields(bad)
        bad=deepcopy(wire);bad['rows'][0]['modeled_basis']={}
        with self.assertRaisesRegex(ValueError,'financial_field_reference_conflict'):expand_price_fields(bad)

    def test_retained_wide_spread_nested_names_and_boundary(self):
        import gzip,json
        from pathlib import Path
        from app.dashboard.comparison_board import compact_price_fields, expand_price_fields, MAX_RESPONSE
        # Authentic retained SQL-derived source projection, not live freshness evidence.
        old=json.loads(gzip.decompress(Path('tests/fixtures/wide-spread-board-20261022.json.gz').read_bytes()))
        self.assertEqual(len(encoded(old)),526686)
        self.assertGreater(len(encoded(old)),MAX_RESPONSE)
        original=expand_price_fields(deepcopy(old))
        wire=compact_price_fields(deepcopy(original))
        self.assertEqual(len(encoded(wire)),451371)
        self.assertEqual(len(wire['prices']),114)
        self.assertEqual(expand_price_fields(deepcopy(wire)),original)
        self.assertEqual(compact_price_fields(deepcopy(wire)),wire)
        for view in ('odds','ev','arbs'):
            other=deepcopy(original);other['view']=view
            packed=compact_price_fields(deepcopy(other))
            self.assertLess(len(encoded(packed)),MAX_RESPONSE)
            self.assertEqual(expand_price_fields(packed),other)
        for invalid in ('-1','01','999999','1.0','x'):
            bad=deepcopy(wire)
            # A direct object field; the pool is decoded by the same path.
            field=next(k for k,v in bad['prices'][0].items() if isinstance(v,dict) and k!='field_refs')
            bad['prices'][0][field][invalid]='crossed'
            with self.assertRaisesRegex(ValueError,'comparison_object_key_conflict'):expand_price_fields(bad)
        for names in (['duplicate','duplicate'],['__proto__'],[True],{}):
            bad=deepcopy(wire);bad['price_object_keys']=names
            with self.assertRaisesRegex(ValueError,'comparison_object_key_conflict'):expand_price_fields(bad)

    def test_object_names_without_value_pool_preserve_nested_literals(self):
        from app.dashboard.comparison_board import compact_price_fields, expand_price_fields
        source={'field_refs':{'0':'literal'},'0':None,'array':[{'1':'literal'}]}
        original=dict(prices=[dict(quote_id=str(n),quote_revision=n,
            unique_source={f'inspectable_source_fact_{k:03}':str(n)+':'+str(k)+'x'*20 for k in range(100)},
            nested=dict(deepcopy(source),unique=n) if n else {},empty_array=[]) for n in range(120)])
        wire=compact_price_fields(deepcopy(original))
        self.assertIn('price_object_keys',wire)
        self.assertNotIn('price_field_pool',wire)
        self.assertEqual(expand_price_fields(deepcopy(wire)),original)
        for names in (None,False):
            bad=deepcopy(wire);bad['price_object_keys']=names
            with self.assertRaisesRegex(ValueError,'comparison_object_key_conflict'):expand_price_fields(bad)
