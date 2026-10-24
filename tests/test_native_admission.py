"""Native admission refuses exact violations before any SQL or reducer adoption."""
from copy import deepcopy
from types import SimpleNamespace
import asyncio
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import patch

from app.collection.current_database import DatabaseIngressSink, NativeAdmissionError
from app.collection.current_policy import DEFAULT
from tests.test_current_service import native_fixture


class NativeAdmission(TestCase):
    def setUp(self):
        self.catalog,self.book=native_fixture()
        self.sink=DatabaseIngressSink(SimpleNamespace(),DEFAULT)
        self.sink.reducer.inventory={'kalshi':deepcopy(self.catalog)}
        self.sink.reducer.generation=7

    def observation(self,book):
        return dict(type='prediction_book',source='kalshi',observed_at=book['raw']['received_at'],book=book)

    def test_exact_predicates_and_atomic_mixed_batch(self):
        mutations=[
            ('native_market_not_in_catalog',lambda b:b['raw']['ref'].update(market_id='removed-market')),
            ('native_book_source_mismatch',lambda b:b['raw']['ref'].update(venue='polymarket_us')),
            ('native_book_not_synchronized',lambda b:b.update(sync='resyncing')),
            ('native_book_state_unknown',lambda b:b.update(state='unknown')),
            ('native_book_quantity_unit_invalid',lambda b:b.update(quantity_unit='usd')),
            ('native_book_outcomes_incomplete',lambda b:b['outcomes'].pop()),
        ]
        original=self.sink.reducer
        for reason,mutate in mutations:
            with self.subTest(reason=reason):
                bad=deepcopy(self.book);mutate(bad)
                batch=dict(type='prediction_books',source='kalshi',observed_at=self.book['raw']['received_at'],
                    observations=[self.observation(deepcopy(self.book)),self.observation(bad)])
                with patch('app.collection.current_database.connect',side_effect=AssertionError('SQL before native validation')):
                    with self.assertRaises(NativeAdmissionError) as raised:self.sink.prepare(batch,{})
                diagnostic=raised.exception.diagnostic
                self.assertEqual(str(raised.exception),reason)
                self.assertEqual(diagnostic['batch_index'],1)
                self.assertEqual(diagnostic['batch_size'],2)
                self.assertEqual(diagnostic['catalog_generation'],7)
                self.assertNotIn('json_text',diagnostic)
                self.assertIs(self.sink.reducer,original)
                self.assertEqual(original.books,{})

    def test_diagnostic_never_copies_raw_bodies_or_arbitrary_fields(self):
        book=deepcopy(self.book)
        book['raw'].update(json_text='private-provider-body',authorization='private-credential')
        book['sync']='private-invalid-sync'
        with self.assertRaises(NativeAdmissionError) as raised:
            self.sink.prepare(self.observation(book),{})
        self.assertNotIn('private',str(raised.exception.diagnostic))


class CatalogTransition(IsolatedAsyncioTestCase):
    async def test_rediscovery_quiesces_old_socket_and_batch_before_replacing_inventory(self):
        from tests.test_current_multisport_ingress import worker
        from tests.multisport_fixtures import source_case,fake_discovery,current_book
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                cases=[source_case('NFL','moneyline','retired-'+venue)]
                w,catalogs=worker(venue,['NFL'],['moneyline'])
                fake_discovery(w,cases);await w.discover()
                old=current_book(cases[0],venue)
                w.queue_book(old)
                closed=[]
                async def owned(label):
                    try:await asyncio.Event().wait()
                    finally:closed.append(label)
                stream=asyncio.create_task(owned('socket'))
                publication=asyncio.create_task(owned('batch'))
                w.stream_task=stream;w.publication_task=publication
                await asyncio.sleep(0)
                old_catalog=w.service.catalog
                def replace_catalog(source,catalog):
                    # This is the actual discovery -> catalog boundary. Without
                    # quiescence the old timer/batch races behind this command.
                    self.assertTrue(stream.done(),'old socket still owns the replaced catalog')
                    self.assertTrue(publication.done(),'old batch still targets the replaced catalog')
                    self.assertEqual(w.pending_books,{})
                    self.assertIsNone(w.publication_handle)
                    old_catalog(source,catalog)
                w.service.catalog=replace_catalog
                cases[:]=[source_case('NFL','moneyline','replacement-'+venue)]
                try:await w.discover()
                finally:await w.stop_stream()
                self.assertCountEqual(closed,['batch','socket'])
                self.assertEqual(w.metrics['catalog_transition']['pending_images'],1)
                self.assertEqual(w.metrics['catalog_transition']['retired_markets'],[old['raw']['ref']['market_id']])
                fresh=current_book(cases[0],venue)
                w.queue_book(fresh)
                self.assertIn(fresh['raw']['ref']['market_id'],w.pending_books)
                await w.stop_stream()

    async def test_unchanged_subscription_keeps_socket_and_original_pending_image(self):
        from tests.test_current_multisport_ingress import worker
        from tests.multisport_fixtures import source_case,fake_discovery,current_book
        for venue in ('kalshi','polymarket_us'):
            with self.subTest(venue=venue):
                cases=[source_case('NFL','moneyline','unchanged-'+venue)]
                w,catalogs=worker(venue,['NFL'],['moneyline'])
                fake_discovery(w,cases);await w.discover()
                book=current_book(cases[0],venue);w.queue_book(book)
                stream=asyncio.create_task(asyncio.Event().wait());w.stream_task=stream
                try:
                    await w.quiesce_catalog(w.markets,w.catalog)
                    self.assertFalse(stream.done())
                    self.assertEqual(w.pending_books[book['raw']['ref']['market_id']],book)
                finally:await w.stop_stream()
