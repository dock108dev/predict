"""Reset authority is exact: files and unknown SQL dependencies remain protected."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.storage.current_reset import sports_files, protected_files, apply


class ResetBoundaryTests(TestCase):
    def test_only_exact_sports_files_are_disposable(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            expected = [
                '.local/predict-observations/observations.jsonl',
                '.local/predict-observations/observations-000001.jsonl',
                '.local/predict-observations/observations.domains.sqlite3',
                '.local/predict-odds/diagnostics/NFL.json',
            ]
            protected = [
                '.env', '.local/predict-current-config.json',
                '.local/predict-odds/quota.json',
                '.local/predict-odds/independent-balances/proof.json',
                '.local/predict-current/attempt-keep.json',
            ]
            unrelated = ['.local/predict-observations/owner.json',
                         '.local/predict-odds/diagnostics/owner.json']
            for name in expected + protected + unrelated:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('retained')
            self.assertEqual({str(p.relative_to(root)) for p in sports_files(root)}, set(expected))
            self.assertEqual(set(protected_files(root)), set(protected))
            (root / expected[0]).unlink()
            (root / expected[0]).symlink_to(root / '.env')
            from app.storage.current_reset import fingerprint
            with self.assertRaisesRegex(ValueError, 'regular_file'):
                fingerprint(root / expected[0])

    def test_changed_plan_stops_before_any_mutation(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.local').mkdir()
            with patch('app.storage.current_reset.require_stopped'), \
                 patch('app.storage.current_reset.plan', return_value={'changed': True}):
                with self.assertRaisesRegex(ValueError, 'reset_plan_changed'):
                    apply(None, {}, root)
