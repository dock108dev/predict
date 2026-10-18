"""Authored reusable admission and source-book currentness; zero providers."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import unittest
from app.comparison.source_clock import assess
from app.comparison.combined_native import normalize
from tests.broad_pipeline_fixtures import captured_core_matrix
from tests.test_current_confirmation import observation,catalogs,Confirmations


class SharedSourceClock(unittest.TestCase):
    def test_coverage_prefers_exact_valid_copy_over_old_unresolved_binding(self):
        from tests.test_broad_coverage import observation,config,owner,AT
        from app.comparison.broad_coverage import build
        samples=[observation(venue=v) for v in ('kalshi','polymarket_us')]
        rows=[r for r,p in samples];prices=[p for r,p in samples]
        old=deepcopy(prices[1]);old['same_outcome']=dict(supported=False,key=None,reason='comparison_context_missing')
        old['observation_display']['publication_reason_codes']=['current_dependencies_changed']
        value=build(rows,[*prices,old],config=config(),owner=owner(),at=AT)
        self.assertEqual(value['global_totals']['supported_comparison_observations'],2)
        self.assertEqual(value['global_totals']['current_comparison_observations'],2)
    def test_old_retained_coverage_summary_keeps_new_metrics_unknown_until_capture(self):
        from app.comparison.broad_coverage import select
        from tests.test_broad_coverage import payload
        old=payload()
        old['aggregation'].pop('inputs');old['aggregation'].pop('publications')
        for cell in old['cells']:
            for key in ('identity_matched_observations','eligible_current_pairs','published_current_pairs'):
                cell['counts'].pop(key)
        selected=select(old,league='NFL')
        self.assertIsNone(selected['filtered_totals']['eligible_current_pairs'])
        self.assertIsNone(selected['filtered_totals']['identity_matched_observations'])
        self.assertEqual(selected['filtered_totals']['retained_observations'],6)

    def test_selected_pairs_touch_both_sources_even_when_peer_selects_another_price(self):
        from tests.test_broad_coverage import observation,config,owner,AT
        from app.comparison.broad_coverage import build,select
        samples=[observation(venue=v,suffix=v) for v in ('kalshi','polymarket_us','novig')]
        rows=[r for r,p in samples];prices=[p for r,p in samples]
        for selected,peer in ((0,1),(1,0),(2,1)):
            prices[selected]['current_comparison']['comparison_quote_id']=prices[peer]['quote_id']
        value=build(rows,prices,config=config(),owner=owner(),at=AT)
        self.assertEqual(value['global_totals']['published_current_pairs'],2)
        self.assertEqual(select(value,venue='polymarket_us')['filtered_totals']['published_current_pairs'],2)
        self.assertEqual(select(value,venue='novig')['filtered_totals']['published_current_pairs'],1)
    def test_receipt_noise_does_not_invalidate_but_new_book_or_withdrawal_does(self):
        from tests.test_current_publication_repair import PublicationDependencyIdentity
        from app.storage.observation_publication import own
        frame=PublicationDependencyIdentity().frame();before=own(frame,'selected')
        frame['offers']['selected']['received_at']='2026-10-17T15:00:02+00:00'
        self.assertEqual(own(frame,'selected'),before)
        frame['offers']['selected']['offer_revision']='new-confirmed-evidence'
        self.assertNotEqual(own(frame,'selected'),before)
        frame['offers']['selected']['offer_revision']='offer-1'
        frame['states']['kalshi']=dict(state='resyncing')
        self.assertNotEqual(own(frame,'selected'),before)
    def quote(self,venue):
        at=datetime.now(timezone.utc)
        market=catalogs()[venue]['markets'][0]
        book,data,raw=observation(venue,market,at)
        tracker=Confirmations(venue);tracker.begin(1)
        confirmation=tracker.observe(book,data,raw,generation=1,request_id='sub-1',
            requested_at=(at-timedelta(seconds=1)).isoformat() if venue=='kalshi' else None,
            sid=2 if venue=='kalshi' else None,sequence=data.get('seq'))
        ref=book['raw']['ref']
        q=dict(venue=venue,source=dict(native_event_id=ref['event_id'],native_market_id=ref['market_id']),
            times=dict(source_at=None,received_at=book['raw']['received_at']),freshness_policy=dict(maximum_age_seconds=30),book_confirmation=confirmation)
        return q,at

    def test_confirmed_unchanged_book_has_separate_basis_expiry_and_future_refusal(self):
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                q,at=self.quote(venue);original=deepcopy(q)
                clock=datetime.fromisoformat(q['book_confirmation']['confirmed_at'])
                for age,expected in ((29.999999,[]),(30,[]),(30.000001,['source_expired'])):
                    self.assertEqual(assess(q,clock+timedelta(seconds=age))['reasons'],expected)
                self.assertEqual(q,original)
                q['times']['source_at']=(at+timedelta(days=1)).isoformat()
                self.assertIn('source_future',assess(q,at+timedelta(seconds=2))['reasons'])
                q=deepcopy(original);q['source']['native_market_id']='other-book'
                self.assertIn('book_confirmation_invalid',assess(q,at+timedelta(seconds=2))['reasons'])
                q=deepcopy(original);q['book_confirmation']['confirmed_at']=(at-timedelta(seconds=1)).isoformat()
                self.assertIn('book_confirmation_invalid',assess(q,at+timedelta(seconds=2))['reasons'])

    def test_receipt_metadata_or_missing_clock_cannot_supply_confirmation(self):
        q,at=self.quote('kalshi');q.pop('book_confirmation')
        self.assertEqual(assess(q,at+timedelta(seconds=2))['reasons'],['source_unknown'])
        q['times']['source_at']=(at-timedelta(hours=1)).isoformat()
        self.assertEqual(assess(q,at+timedelta(seconds=2))['reasons'],['source_expired'])


class SharedAdmission(unittest.IsolatedAsyncioTestCase):
    async def test_complete_matrix_originals_survive_admission(self):
        rows,books=await captured_core_matrix()
        self.assertEqual(len(rows),72)
        self.assertTrue(all(r['comparison_source_metadata']['scoring_scope']['status']=='supported' for r in rows))
        self.assertEqual(len(books),36)

    async def test_rebinding_complete_catalog_replaces_old_context_refusal_across_matrix(self):
        from tests.test_current_multisport_ingress import worker
        from tests.multisport_fixtures import source_case,fake_discovery,SPORTS,FAMILIES,current_book
        cases=[source_case(s,f,'rebound-'+s+'-'+f) for s in SPORTS for f in FAMILIES]
        for venue in ('kalshi','polymarket_us'):
            native,published=worker(venue);fake_discovery(native,cases);await native.discover()
            catalog=published[-1]
            for market in catalog['markets']:
                market['comparison_admission']=dict(supported=False,reason='comparison_context_missing',missing_fields=['season','stage'])
            at=cases[0]['clock'].isoformat()
            source_books=[current_book(c,venue,clock=cases[0]['clock']) for c in cases]
            source=dict(id='authored',record=dict(source=venue,value=dict(inventory=catalog)))
            envelopes=[dict(id='authored-book',record=dict(retained_at=at,value=dict(observations=[dict(type='prediction_book',source=venue,observed_at=at,book=b) for b in source_books])))]
            rows,excluded=normalize(source,envelopes,at=at)
            self.assertFalse(excluded);self.assertEqual(len(rows),36)
            self.assertTrue(all(r.get('comparison_source_metadata',{}).get('comparison_admission',{}).get('supported') is not False for r in rows))
            self.assertTrue(all(r['comparison_source_metadata']['same_outcome'].get('reason') is None for r in rows))
            self.assertTrue(all(m.get('comparison_admission',{}).get('supported') is False for m in catalog['markets']),'original retained catalog remains unchanged')
