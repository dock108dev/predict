"""Exact retained catalog scope is independent of market predicates/admission."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import unittest

from app.adapters.kalshi import Response, parse_event, parse_market, KalshiAdapter
from app.collection.coverage import market_record
from app.collection.native_scope_bindings import (PATH, POLICY, catalog_cell_bindings,
    selectors_for, series_binding, validate_catalog)

ROOT = Path(__file__).resolve().parents[1]


class NativeScopeBindings(unittest.TestCase):
    def test_every_key_and_copied_field_matches_the_complete_primary_catalog(self):
        value=json.loads(PATH.read_text()); original=(ROOT/value['source_path']).read_bytes()
        self.assertEqual(sha256(original).hexdigest(),value['source_catalog_sha256'])
        originals={x['ticker']:x for x in json.loads(original)['series']}
        self.assertEqual(len(value['bindings']),110)
        self.assertEqual(len(catalog_cell_bindings()),46)
        for row in value['bindings']:
            source=originals[row['series_ticker']]
            self.assertEqual(sha256(json.dumps(source,sort_keys=True,separators=(',',':')).encode()).hexdigest(),row['source_record_sha256'])
            self.assertEqual(source['category'],'Sports')
            for field in ('title','contract_terms_url','contract_url','last_updated_ts','settlement_sources','tags'):
                self.assertEqual(source.get(field),row[field])
        self.assertFalse(value['collection_authorized'])

    def test_exact_families_periods_and_distinct_conference_awards(self):
        cells=catalog_cell_bindings()
        self.assertEqual(series_binding('KXNFLSPREAD')['family'],'spread')
        self.assertEqual(series_binding('KXNBA1HTOTAL')['period'],'first_half')
        self.assertEqual(series_binding('KXMLBF3')['period'],'first_3')
        self.assertEqual(series_binding('KXMLBF5TOTAL')['period'],'first_5')
        self.assertEqual(series_binding('KXMARMAD')['sport'],'NCAAB')
        self.assertEqual(series_binding('KXNCAAMBACCREG')['award_variant'],'conference_regular_season_champion')
        self.assertEqual(series_binding('KXNCAAMBACC')['award_variant'],'conference_tournament_champion')
        for cell in ('MLB/first_6/moneyline','MLB/regulation_9/total','NHL/period_1/moneyline','MLB/first_3/spread'):
            self.assertNotIn(cell,cells);self.assertEqual(selectors_for(cell),[])
        self.assertEqual(selectors_for('NBA/full_game/spread','polymarket_us'),[])

    def test_new_adapter_scope_is_explicit_and_does_not_rewrite_legacy_winner_assumptions(self):
        with self.assertRaisesRegex(ValueError,'explicit supported'):
            KalshiAdapter(series=('KXNFLSPREAD',),client=object())
        adapter=KalshiAdapter(series=('KXNFLSPREAD',),scope_policy=POLICY,client=object())
        self.assertTrue(adapter.typed_scope)
        at=datetime(2026,9,30,tzinfo=timezone.utc)
        data=dict(event_ticker='SYNTHETIC-NFL-SPREAD',ticker='SYNTHETIC-NFL-SPREAD-BUF',title='Synthetic title',status='active')
        response=Response(json.dumps({'markets':[data]}),'isolated catalog-control',at)
        old=parse_market(response,data,data['event_ticker'],'KXNFLSPREAD')
        new=parse_market(response,data,data['event_ticker'],'KXNFLSPREAD',typed_scope=True)
        self.assertEqual(old.market_type.value,'unknown');self.assertIsNone(old.period)
        self.assertEqual(new.market_type.value,'spread');self.assertEqual(new.period,'full_game')
        with self.assertRaisesRegex(ValueError,'series relationship'):
            parse_event(response,dict(event_ticker='X',series_ticker='KXNBA1HTOTAL',title='X'),'KXNFLSPREAD',typed_scope=True)

    def test_typed_catalog_never_invents_threshold_predicate_completion_or_admission(self):
        at='2026-09-30T00:00:00+00:00'
        data=dict(event_ticker='ISOLATED',ticker='ISOLATED-BUF',title='Buffalo -3',status='active',floor_strike=3)
        body=json.dumps({'markets':[data]})
        page=dict(path='/trade-api/v2/markets',params={'event_ticker':'ISOLATED'},received_at=at,
                  source='kalshi',native_scope_policy=POLICY)
        record=market_record('kalshi',page,body,data,'ISOLATED',1,'KXNFLSPREAD')
        self.assertEqual(record['market_type'],'spread');self.assertEqual(record['period'],'full_game')
        self.assertEqual(record['exclusion'],'native_scope_predicate_review_required')
        self.assertNotIn('line',record);self.assertNotIn('product_descriptor',record)
        self.assertEqual(record['native_scope_binding']['series_ticker'],'KXNFLSPREAD')

    def test_changed_fixture_digest_rejects(self):
        value=json.loads(PATH.read_text());value['bindings'][0]['period']='period_1'
        with self.assertRaisesRegex(ValueError,'digest'):
            validate_catalog(value)
