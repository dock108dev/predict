"""Disposable SQL proves rejected native batches preserve admitted originals."""
from copy import deepcopy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.collection.current_database import DatabaseIngressSink,NativeAdmissionError
from app.collection.current_policy import DEFAULT
from app.dashboard.current_state import unavailable
from app.storage.store import connect
from tests import test_d03_current_rows as fixtures
from tests.test_ev09_n01 import envelopes,AT


class NativeAdmissionSQL(TestCase):
    setUpClass=classmethod(fixtures.CurrentRows.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.CurrentRows.tearDownClass.__func__)
    setUp=fixtures.CurrentRows.setUp

    def test_rejected_mixed_batch_preserves_sql_and_reducer_then_valid_neighbor_progresses(self):
        for source in ('kalshi','polymarket_us'):
            with self.subTest(source=source):
                self.setUp()
                raw=unavailable();store=SimpleNamespace(_state=raw)
                store.commit=lambda value:setattr(store,'_state',value)
                sink=DatabaseIngressSink(store,DEFAULT)
                catalog=next(e['record']['value']['inventory'] for e in envelopes()
                    if e['record']['kind']=='catalog' and e['record']['source']==source)
                observation=deepcopy(next(o for e in envelopes() if e['record']['kind']=='admitted_books'
                    and e['record']['source']==source for o in e['record']['value']['observations']))
                observation['book'].pop('book_confirmation',None)
                header=dict(source=source,session_id='native-admission-disposable',observed_at=AT)
                states=raw['source_status']
                with patch('app.collection.current_database.connect',lambda:connect(self.name)), \
                     patch('app.collection.current_database.utc',return_value=AT), \
                     patch('app.storage.current_rows.utc',return_value=AT):
                    sink.commit(dict(header,type='coverage_inventory',inventory={source:catalog},
                        generation=1,previous_generation=None),states)
                    sink.commit(dict(observation,**header),states)
                    before=self.store.capture();reducer=sink.reducer;sequence=sink.sequence
                    newer=deepcopy(observation)
                    newer['book']['raw'].update(exchange_at='2026-10-15T12:05:00Z',received_at='2026-10-15T12:05:01Z')
                    for reason,change in (
                        ('native_market_not_in_catalog',lambda b:b['raw']['ref'].update(market_id='retired-owned-market')),
                        ('native_book_not_synchronized',lambda b:b.update(sync='resyncing')),
                        ('native_book_state_unknown',lambda b:b.update(state='unknown')),
                        ('native_book_quantity_unit_invalid',lambda b:b.update(quantity_unit='usd')),
                        ('native_book_outcomes_incomplete',lambda b:b['outcomes'].pop()),
                    ):
                        bad=deepcopy(newer);change(bad['book'])
                        with self.subTest(reason=reason),self.assertRaisesRegex(NativeAdmissionError,reason):
                            sink.commit(dict(header,type='prediction_books',observations=[newer,bad]),states)
                        self.assertEqual(before,self.store.capture())
                        self.assertIs(reducer,sink.reducer)
                        self.assertEqual(sequence,sink.sequence)
                    sink.commit(dict(newer,**header),states)
                    self.assertGreater(sink.sequence,sequence)
                    saved=[r for r in self.store.records() if r['quote']['venue']==source]
                    self.assertTrue(saved)
                    self.assertTrue(all(r['quote']['times']['received_at']=='2026-10-15T12:05:01Z' for r in saved))
