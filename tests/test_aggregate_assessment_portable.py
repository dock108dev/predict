"""Synthetic rule-analysis contracts; original public archives remain local."""
from decimal import Decimal
import json
from unittest.mock import patch

from app.dashboard import coverage_owner
from app.dashboard.price_comparison import comparisons
from app.dashboard.session_history import load
from app.reference import aggregate_assessment as rules
from tests import test_aggregate_assessment as archive
from tests.aggregate_fixture import packages


class SyntheticAssessment:
    def setUp(self):
        fixture = packages()
        for target, name, value in (
            (archive, 'ROOT', fixture['root']),
            (archive, 'F', fixture['half']),
            (coverage_owner, 'ROOT', fixture['root']),
            (rules, 'ROOT', fixture['root']),
            (rules, 'DATA', fixture['data']),
            (rules, 'DATA_SHA256', fixture['data_sha256']),
        ):
            override = patch.object(target, name, value)
            override.start()
            self.addCleanup(override.stop)


class Assessments(SyntheticAssessment, archive.Assessments):
    def test_original_outputs_exact_and_research_deterministic(self):
        folder = packages()['half']
        original = comparisons(load(folder), {'rule_version': 'original'})
        self.assertEqual(len(original), 2)
        for row in original:
            self.assertNotIn('rule_analysis', row)
            # Hand oracle: 1/2.5 versus 1/2.0 => a ten-point raw gap.
            self.assertEqual(abs(Decimal(row['raw_difference'])), Decimal('0.1'))
            self.assertIsNone(row['net'])
            self.assertIsNone(row['ev'])
        current = comparisons(load(folder), {})
        self.assertEqual(current, comparisons(load(folder), {'rule_version': rules.VERSION}))
        self.assertEqual(current, comparisons(load(folder, current[0]['cutoff']), {}))
        # Research is additive; every original field except the explanation remains.
        for before, after in zip(original, current):
            for field in ('legs', 'identity', 'raw_difference', 'net', 'ev', 'hash', 'cutoff'):
                self.assertEqual(before[field], after[field])
        full = packages()['full']
        self.assertEqual(comparisons(load(full), {}),
                         comparisons(load(full), {'rule_version': 'original'}))

    def test_changed_source_bytes_with_valid_assessment_seal_withhold_research(self):
        fixture = packages()
        source = json.loads(fixture['data'].read_text())['sources'][0]
        path = fixture['root'] / source['retained_path']
        original = path.read_bytes()
        row = comparisons(load(fixture['half']), {'rule_version': 'original'})[0]
        try:
            path.write_bytes(original + b'SYNTHETIC CORRUPTION\n')
            result = rules.enrich(dict(row))
            self.assertEqual(result['rule_analysis']['status'], 'unavailable')
            self.assertEqual(result['legs'], row['legs'])
            self.assertEqual(result['raw_difference'], row['raw_difference'])
            self.assertIsNone(result['net'])
            self.assertIsNone(result['ev'])
        finally:
            path.write_bytes(original)


class Routes(SyntheticAssessment, archive.Routes):
    pass
