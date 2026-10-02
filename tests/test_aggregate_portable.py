"""Run shared aggregate guards against synthetic packages in a fresh checkout."""
from unittest.mock import patch

from tests import test_aggregate_ingestion as archive
from tests.aggregate_fixture import FOLDER


class Aggregate(archive.Aggregate):
    record_count = 60
    comparison_count = 12
    reference_count = 36
    invalid_price_count = 1
    @classmethod
    def setUpClass(cls):
        override = patch.object(archive, 'FOLDER', FOLDER)
        override.start()
        cls.addClassCleanup(override.stop)
        super().setUpClass()

    def test_real_retained_roles_feed_filters_and_raw_boundaries(self):
        # The same guards use explicit synthetic counts, not acquisition claims.
        super().test_real_retained_roles_feed_filters_and_raw_boundaries()
        self.assertTrue(all(r['evidence_mode'] == 'synthetic-fixture' for r in self.records))

class Routes(archive.Routes):
    comparison_count = 12
    async def asyncSetUp(self):
        override = patch.object(archive, 'FOLDER', FOLDER)
        override.start()
        self.addCleanup(override.stop)
