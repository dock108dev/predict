"""Semantic controls only: these complete envelopes are synthetic, not evidence."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import unittest

from app.collection import us_metadata_diagnostic as diagnostic
from app.collection.native_payload import TRANSPORT_CONTRACT


class MetadataDiagnosticSemantics(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc)
        self.baseline = diagnostic.baseline_from_review()
        self.spec = dict(native_discovery=deepcopy(diagnostic.CONTRACT),
            native_transport=deepcopy(TRANSPORT_CONTRACT), native_review_records=[],
            assessment_revisions={}, us_metadata_diagnostic=dict(policy=diagnostic.POLICY,
                target=deepcopy(diagnostic.TARGET), request=deepcopy(diagnostic.REQUEST),
                historical_baseline=deepcopy(self.baseline), validity_window=dict(
                    start='2026-09-30T21:00:00+00:00', expires='2026-10-01T01:00:00+00:00',
                    basis=diagnostic.WINDOW_BASIS)))
        self.event = deepcopy(self.baseline['event'])
        self.event['markets'] = [deepcopy(self.baseline['market'])]

    def receipt(self, event=None, *, raw=None, complete=True, usable=True, reason=None):
        raw = json.dumps({'event': event or self.event}).encode() if raw is None else raw
        return dict(type='prediction_discovery_http', source='polymarket_us',
            path='/v1/events/127804', params={}, transport_policy=deepcopy(TRANSPORT_CONTRACT),
            complete=complete, wire_complete=complete, usable_metadata=usable, status=200,
            body_b64=base64.b64encode(raw).decode(), body_sha256=sha256(raw).hexdigest(),
            delivery_reason=reason, resource_usage=dict(wire_bytes=len(raw)+100,
                entity_bytes_read=len(raw), retained_body_bytes=len(raw), decoded_bytes=len(raw),
                http_header_wire_bytes=100, framed_entity_bytes=len(raw), http_framing_state='complete',
                peer_close_observed=complete), http_plaintext_sha256='a'*64,
            received_at=self.at.isoformat())

    def report(self, event=None, **kw):
        return diagnostic.evaluate([self.receipt(event, **kw)], self.spec, self.at)

    def test_complete_open_identity_terms_and_pregame_independent(self):
        report = self.report()
        self.assertTrue(report['delivery']['transport_complete'])
        self.assertTrue(report['json']['whole_document_valid'])
        self.assertTrue(report['json']['expected_envelope_valid'])
        self.assertTrue(report['target_identity']['agrees'])
        self.assertTrue(report['material_terms']['event_agrees'])
        self.assertTrue(report['material_terms']['market_agrees'])
        self.assertTrue(report['current_state']['supported'])
        self.assertTrue(report['pregame_eligibility']['eligible'])
        self.assertFalse(report['scope']['new_supported_review'])

    def test_closed_complete_response_delivery_and_terms_supported_but_not_pregame(self):
        for value in (self.event, self.event['markets'][0]):
            value['closed'] = True
            value['active'] = False
        self.event['markets'][0]['status'] = 'MARKET_STATUS_CLOSED'
        self.event['markets'][0]['ep3Status'] = 'CLOSED'
        report = self.report()
        self.assertTrue(report['delivery']['transport_complete'])
        self.assertTrue(report['json']['whole_document_valid'])
        self.assertTrue(report['target_identity']['agrees'])
        self.assertTrue(report['material_terms']['event_agrees'])
        self.assertTrue(report['material_terms']['market_agrees'])
        self.assertFalse(report['current_state']['supported'])
        self.assertFalse(report['pregame_eligibility']['eligible'])
        self.assertFalse(report['material_terms']['ordinary_paired_semantic_review']['event']['admitted'])

    def test_started_complete_delivery_is_success_without_pregame_admission(self):
        report = diagnostic.evaluate([self.receipt()], self.spec,
            datetime(2026, 9, 30, 23, 31, tzinfo=timezone.utc))
        self.assertTrue(report['delivery']['transport_complete'])
        self.assertTrue(report['target_identity']['agrees'])
        self.assertTrue(report['material_terms']['market_agrees'])
        self.assertFalse(report['pregame_eligibility']['eligible'])
        self.assertEqual(report['pregame_eligibility']['reason'], 'target_outside_prestart_applicability')

    def test_incomplete_prefix_never_establishes_identity_or_absence(self):
        report = self.report(raw=b'{"event":{"id":"127804","markets":[]}',
            complete=False, usable=False, reason='native_entity_byte_cap')
        self.assertFalse(report['delivery']['transport_complete'])
        self.assertIsNone(report['json']['whole_document_valid'])
        self.assertIsNone(report['target_identity']['agrees'])
        self.assertIsNone(report['pregame_eligibility']['eligible'])
        self.assertEqual(report['metadata_admission']['reason'], 'native_entity_byte_cap')

    def test_complete_wrong_envelope_has_valid_json_and_unknown_identity(self):
        report = self.report(raw=b'{"events":[]}', usable=False, reason='native_unexpected_envelope')
        self.assertTrue(report['delivery']['transport_complete'])
        self.assertTrue(report['json']['whole_document_valid'])
        self.assertFalse(report['json']['expected_envelope_valid'])
        self.assertIsNone(report['target_identity']['agrees'])

    def test_complete_malformed_and_duplicate_json_are_not_admitted(self):
        for raw, reason in ((b'{"event":', 'native_incomplete_json'),
                            (b'{"event":{},"event":{}}', 'native_json_duplicate_key')):
            with self.subTest(reason=reason):
                report = self.report(raw=raw, usable=False, reason=reason)
                self.assertTrue(report['delivery']['transport_complete'])
                self.assertFalse(report['json']['whole_document_valid'])
                self.assertFalse(report['metadata_admission']['admitted'])
                self.assertIsNone(report['target_identity']['agrees'])

    def test_material_change_and_mutable_price_change_are_distinct(self):
        self.event['markets'][0]['bestAskQuote']['value'] = '0.51'
        report = self.report()
        self.assertTrue(report['material_terms']['market_agrees'])
        self.event['markets'][0]['description'] += ' New settlement rule.'
        report = self.report()
        self.assertTrue(report['delivery']['transport_complete'])
        self.assertTrue(report['target_identity']['agrees'])
        self.assertFalse(report['material_terms']['market_agrees'])
        self.assertFalse(report['pregame_eligibility']['eligible'])

    def test_unknown_added_term_requires_review(self):
        self.event['new_provider_contract_field'] = 'unknown'
        report = self.report()
        self.assertTrue(report['target_identity']['agrees'])
        self.assertFalse(report['material_terms']['event_agrees'])

    def test_selected_side_conflict_and_duplicate_selected_market_fail_identity(self):
        self.event['markets'][0]['marketSides'][0]['teamId'] = 1490
        report = self.report()
        self.assertFalse(report['target_identity']['agrees'])
        self.assertEqual(report['target_identity']['reason'], 'conflicting_selected_market_side_identity')
        self.event['markets'].append(deepcopy(self.event['markets'][0]))
        report = self.report()
        self.assertFalse(report['target_identity']['agrees'])
        self.assertEqual(report['target_identity']['reason'], 'duplicate_selected_market_in_complete_response')

    def test_catalog_admission_failure_preserves_delivery_and_blocks_semantics(self):
        report = diagnostic.evaluate([self.receipt()], self.spec, self.at,
                                     admission_error='native_source_inventory_cap')
        self.assertTrue(report['delivery']['transport_complete'])
        self.assertTrue(report['json']['whole_document_valid'])
        self.assertFalse(report['metadata_admission']['admitted'])
        self.assertIsNone(report['target_identity']['agrees'])

    def test_exact_baseline_and_finite_independent_window_required(self):
        changed = deepcopy(self.spec)
        changed['us_metadata_diagnostic']['historical_baseline']['market']['description'] += 'edited'
        with self.assertRaisesRegex(ValueError, 'baseline contents changed'):
            diagnostic.validate_spec(changed)
        changed = deepcopy(self.spec)
        changed['us_metadata_diagnostic']['validity_window']['expires'] = '2026-10-03T21:00:00+00:00'
        with self.assertRaisesRegex(ValueError, 'at most 24 hours'):
            diagnostic.validate_spec(changed)
        changed = deepcopy(self.spec)
        changed['native_review_records'] = [{}]
        with self.assertRaisesRegex(ValueError, 'paired reviews'):
            diagnostic.validate_spec(changed)

    def test_fresh_report_recomputation_is_exact_and_tamper_refused(self):
        receipt = self.receipt()
        report = diagnostic.evaluate([receipt], self.spec, self.at)
        rows = [dict(type='session_started', spec=self.spec), receipt, report]
        self.assertTrue(diagnostic.verify(rows)['verified'])
        report['pregame_eligibility']['eligible'] = False
        with self.assertRaisesRegex(ValueError, 'assessment changed'):
            diagnostic.verify(rows)

    def test_unexpected_saved_report_claims_and_economics_are_refused(self):
        receipt = self.receipt()
        report = diagnostic.evaluate([receipt], self.spec, self.at)
        rows = [dict(type='session_started', spec=self.spec), receipt, report]
        report['provider_absence_established'] = True
        with self.assertRaisesRegex(ValueError, 'assessment changed'):
            diagnostic.verify(rows)
        report.pop('provider_absence_established')
        report['economics'] = {'EV': 1}
        with self.assertRaisesRegex(ValueError, 'assessment changed'):
            diagnostic.verify(rows)


if __name__ == '__main__':
    unittest.main()
