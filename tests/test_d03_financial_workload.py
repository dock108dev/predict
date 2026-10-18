"""The authored financial500fixture keeps strict production guards intact."""
from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from app.comparison.combined_inputs import prepare
from app.storage.comparison_board import ReadContext,discover,calculate_current
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.dashboard.comparison_board import entries,response
from tests.test_ev09_n01 import AT,envelopes,SELECTED
from tests.d03_financial_workload import authored_records,serialize_synthetic


def seed():
    records=next(g for g in prepare(envelopes(),at=AT)['groups'] if any((r['quote']['source']['provider'],r['quote']['source']['native_event_id'])==SELECTED for r in g))
    records=[r for r in records if r['market_identity']['family']=='moneyline' and r['market_identity']['period']=='full_game']
    for record in records:record['quote']['provenance'].update(mode='synthetic',real_source=False)
    return records


class D03FinancialWorkload(unittest.TestCase):
    def test_authoring_keeps_prices_clocks_and_removes_real_confirmation(self):
        original=seed();rows=authored_records(original)
        for old,new in zip(original,rows):
            self.assertEqual(old['quote']['original'],new['quote']['original'])
            self.assertEqual(old['quote']['times'],new['quote']['times'])
            self.assertEqual(old['quote'].get('depth'),new['quote'].get('depth'))
            self.assertNotIn('book_confirmation',new['quote'])
            self.assertNotIn('native_predicate',new['quote'])
            self.assertFalse(new['quote']['provenance']['real_source'])
        original[0]['quote']['provenance'].update(mode='current',real_source=True)
        with self.assertRaisesRegex(ValueError,'explicitly synthetic'):authored_records(original)

    def test_normal_owner_outputs_and_guard_without_production_bypass(self):
        rows=authored_records(seed())
        with patch('app.storage.current_rows.CurrentRowStore.capture',return_value=dict(records=rows,epoch='authored-qa',revision='authored-qa')):
            context=ReadContext(SimpleNamespace(db=None),at=AT);bundle=discover(context.store,context=context)[0]
            with self.assertRaisesRegex(ValueError,'Evidence mode conflict'):calculate_current(bundle,DEFAULT_POLICY,context=context)
            with patch('app.dashboard.current_contract.serialize',side_effect=serialize_synthetic):value=calculate_current(bundle,DEFAULT_POLICY,context=context)
        singles=[q['calculations']['funded_estimate'] for _,_,q in entries(value['state'])]
        self.assertEqual(sum(row['model_available'] for row in singles),7)
        refused=[q for _,_,q in entries(value['state']) if not q['calculations']['funded_estimate']['model_available']]
        self.assertEqual(sorted(q['venue'] for q in refused),['novig','novig','polymarket_us'])
        pairs=value['state']['events'][0]['funded_pairs'];self.assertEqual(len(pairs),12)
        arbs=response(bundle,value,DEFAULT_POLICY,view='arbs',filter='all',at=AT)
        self.assertEqual(len(arbs['rows']),7)
        for row in singles+pairs:
            if not row['model_available']:continue
            self.assertEqual(Fraction(row['buffer_usd']),Fraction(row['funding']['deployed_usd'])/200)
            self.assertEqual(Fraction(row['funding']['requested_usd']),1000)
            self.assertFalse(row['funding']['actual_fill_support'])
            self.assertIsNotNone(row['financial_metrics']['conditional_buffered_ev_usd'])
        for row in arbs['rows']:self.assertEqual(len({leg['venue'] for leg in row['legs']}),2)


if __name__=='__main__':unittest.main()
