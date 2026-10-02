"""Offline repairs over whole immutable authorized provider receipts."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from datetime import timedelta
import unittest
from app.collection import coverage
from app.collection.native_review_binding import apply,verify_successor,revalidated_sources,assess
from app.collection.native_score_binding import bind
from app.dashboard.native_reviews import validate
from app.dashboard.session_history import verified
from app.dashboard.session_projection import stamp

BASE=Path(__file__).resolve().parents[1]/'evidence/LIVE-source-engineering-0701b59d-886f-444c-95b1-206144ef46c2'
SECOND=BASE/'da1253ec-9c7e-4ca2-b493-bfa83e21f0a6/782c034e-5c9f-4773-b9db-9cb9a9776084'
FOURTH=BASE/'fbb52528-553e-4afc-b62c-e6bb04b94e68/b13c2e60-b2a1-4f98-b5ac-e906632a5426'

class CapturedBindings(unittest.TestCase):
    def test_actual_fourth_receipts_renew_v2_without_extending_economics(self):
        rows=list(verified(FOURTH)['rows']);pages=[r for r in rows if r['type']=='prediction_discovery_http']
        at=max(stamp(p['received_at']) for p in pages)+timedelta(microseconds=1)
        cats={v:coverage.catalog(pages,v,at) for v in ('kalshi','polymarket_us')}
        emitted=[];spec=rows[0]['spec']
        session=SimpleNamespace(spec=spec,sid=rows[0]['session_id'],projection=SimpleNamespace(started=rows[0]['observed_at']),emit=lambda source,row:emitted.append(row))
        d=SimpleNamespace(session=session,pages=pages)
        apply(d,cats,at)
        self.assertEqual(len(emitted),2)
        for row in emitted:
            current=validate(row['review'])
            parent=next(r for r in spec['native_review_records'] if r['review_id']==current['review_id'])
            verify_successor(current,parent,session.sid)
            self.assertEqual(revalidated_sources(current),{'kalshi','polymarket_us'})
            self.assertEqual(current['settlement_assessment'],parent['settlement_assessment'])
        receipts={(p['source'],p['body_sha256']):p['received_at'] for p in pages if p.get('usable_metadata')}
        template=spec['native_review_records'][0];altered=deepcopy(cats)
        target=next(m for m in altered['polymarket_us']['markets'] if m['id']==template['sources']['polymarket_us']['market_id'])
        target['_native']['updatedAt']='malformed'
        result=assess(template,'polymarket_us',altered['polymarket_us'],at,receipts)
        self.assertFalse(result['admitted']);self.assertFalse(result['material_terms'])

    def test_actual_score_predicates_apply_and_material_conflicts_reject(self):
        found={};sample=None
        for row in verified(SECOND)['rows']:
            scope=row.get('native_scope_binding')
            if row['type']!='prediction_discovery_http' or row['source']!='kalshi' or row['path']!='/trade-api/v2/markets' or not scope or not row.get('usable_metadata'):continue
            _,data=coverage.decode_page(row)
            for native in data['markets']:
                fact=bind(native,scope)
                if fact:
                    key=scope['sport']+'/'+scope['period']+'/'+scope['family'];found[key]=found.get(key,0)+1
                    self.assertTrue(fact['missing'])
                    if scope['family']=='spread':sample=(native,scope)
        self.assertEqual(found['NFL/full_game/spread'],25)
        self.assertEqual(found['NFL/first_half/total'],14)
        self.assertEqual(found['MLB/first_5/spread'],4)
        self.assertEqual(found['NFL/first_half/moneyline'],3)
        self.assertEqual(found['MLB/first_3/moneyline'],3)
        native,scope=sample;bad=deepcopy(native);bad['floor_strike']=99.5
        self.assertIsNone(bind(bad,scope))
        bad=deepcopy(native);bad['rules_primary']='If Cleveland wins by more than '+bad['rules_primary'].split(' wins by more than ',1)[1]
        self.assertIsNone(bind(bad,scope))
