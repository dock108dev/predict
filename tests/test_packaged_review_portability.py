"""Optional local catalogs must not be prerequisites for an offline checkout."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.dashboard import native_reviews


class PackagedReviewPortability(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)/'reviews'
        self.directory.mkdir()
        override = patch.object(native_reviews, 'DIRECTORY', self.directory)
        override.start()
        self.addCleanup(override.stop)
        self.projection = SimpleNamespace(sid='synthetic', spec={}, native_reviews={})

    def write_index(self, value):
        (self.directory/'index-v4.json').write_text(json.dumps(value))

    def test_absent_catalog_has_no_history_or_accepted_judgments(self):
        self.assertEqual(native_reviews.historical_paths(), {})
        self.assertEqual(native_reviews.records(self.projection), ([], {}))
        self.assertFalse(hasattr(self.projection, 'packaged_review_cache_key'))

    def test_missing_catalog_is_not_cached_as_an_existing_empty_catalog(self):
        self.assertEqual(native_reviews.records(self.projection), ([], {}))
        self.write_index({'historical_sessions': {'synthetic': ['missing.json']},
                          'records': {'missing.json': 'unavailable'}})
        with self.assertRaises(FileNotFoundError):
            native_reviews.records(self.projection)

    def test_corrupt_existing_catalog_is_not_treated_as_absent(self):
        (self.directory/'index-v4.json').write_text('{invalid')
        for read in (native_reviews.historical_paths,
                     lambda: native_reviews.records(self.projection)):
            with self.subTest(reader=read), self.assertRaises(json.JSONDecodeError):
                read()

    def test_unsafe_existing_history_binding_is_still_rejected(self):
        self.write_index({'historical_paths': {'synthetic': {'folder': '../private'}}})
        with self.assertRaisesRegex(ValueError, 'Unsafe retained native history path'):
            native_reviews.historical_paths()
