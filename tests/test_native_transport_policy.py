"""Explicit offline resource policy and immutable historical admission rules."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from app.collection import coverage, native_payload
from app.collection.run_spec import preflight

ROOT = Path(__file__).resolve().parents[1]


class TransportPolicy(unittest.TestCase):
    def spec(self):
        return json.loads((ROOT/'evidence/native-nyi-tor-20260930-v3/run-spec.json').read_text())

    def test_legacy_seal_has_no_revised_budget(self):
        spec = self.spec()
        client = SimpleNamespace(response_cap=524288)
        self.assertIsNone(native_payload.validate_transport(spec))
        native_payload.configure_transport(client, spec)
        self.assertIsNone(client.transport_policy)
        self.assertEqual(client.response_cap, 524288)

    def test_exact_new_contract_is_an_explicit_spec_change(self):
        spec = self.spec()
        original = deepcopy(spec)
        spec['native_transport'] = deepcopy(native_payload.TRANSPORT_CONTRACT)
        at = datetime(2026, 9, 30, 22, 31, tzinfo=timezone.utc)
        self.assertTrue(preflight(spec, at)['valid'])
        self.assertNotEqual(spec, original)
        self.assertEqual(native_payload.validate_transport(spec), native_payload.TRANSPORT_CONTRACT)
        for key in native_payload.TRANSPORT_CONTRACT:
            bad = deepcopy(spec)
            bad['native_transport'].pop(key)
            self.assertFalse(preflight(bad, at)['valid'], key)
        for value in (None, dict(native_payload.TRANSPORT_CONTRACT, json_depth=32.0)):
            bad = deepcopy(spec)
            bad['native_transport'] = value
            self.assertFalse(preflight(bad, at)['valid'])
        bad = deepcopy(spec)
        bad['native_discovery']['slice'] = 'native-reviewed-target-v1'
        with self.assertRaises(ValueError):native_payload.validate_transport(bad)

    def test_complete_unusable_receipt_cannot_enter_catalog(self):
        raw = b'{"event":{"id":"127804"}}'
        page = dict(path='/v1/events/127804', complete=True, usable_metadata=False,
            transport_policy=deepcopy(native_payload.TRANSPORT_CONTRACT),
            delivery_reason='native_unexpected_envelope', body_b64=base64.b64encode(raw).decode(),
            body_sha256=sha256(raw).hexdigest())
        with self.assertRaisesRegex(ValueError, 'native_unexpected_envelope'):
            coverage.decode_page(page)
        page['usable_metadata'] = True
        self.assertEqual(coverage.decode_page(page)[1], {'event': {'id': '127804'}, 'events': [{'id': '127804'}]})
        page['transport_policy']['response_entity_bytes'] += 1
        with self.assertRaisesRegex(ValueError, 'contract_mismatch'):coverage.decode_page(page)

    def test_parse_budget_limits_expansion_before_json_allocation(self):
        raw = b'{"event":{},"many":[' + b','.join([b'{}'] * 40000) + b']}'
        with self.assertRaisesRegex(ValueError, 'native_parse_expansion_cap'):
            native_payload.parse(raw, limits=native_payload.TRANSPORT_CONTRACT)
        metrics = {}
        self.assertEqual(native_payload.parse(b'{"event":{}}', limits=native_payload.TRANSPORT_CONTRACT,
            metrics=metrics), {'event': {}})
        self.assertLess(metrics['parse_object_bytes'], native_payload.TRANSPORT_CONTRACT['parse_expansion_bytes'])


if __name__ == '__main__':unittest.main()
