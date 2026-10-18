"""Local policy controls; no installed journal, database or provider access."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.collection.current_storage_policy import (
    FREE_DISK_BYTE_FLOOR, GIB, JOURNAL_BYTE_CAP, JOURNAL_RECORD_BYTE_CAP,
    JOURNAL_SEGMENT_BYTE_CAP, MIB, SQL_BYTE_CAP, require_disk_space, sql_usage,
)
from app.collection.odds_http import BudgetStop


class Policy(unittest.TestCase):
    def test_approved_disk_allowances_are_separate(self):
        self.assertEqual(JOURNAL_SEGMENT_BYTE_CAP, 256 * MIB)
        self.assertEqual(JOURNAL_RECORD_BYTE_CAP, 8 * MIB)
        self.assertEqual(JOURNAL_BYTE_CAP, 8 * GIB)
        self.assertEqual(SQL_BYTE_CAP, 2 * GIB)

    def database(self, value):
        database = Mock()
        database.execute.return_value.fetchone.return_value = {'n': value}
        return database

    def test_sql_usage_reads_current_and_latest_public_table_storage(self):
        database = self.database(Decimal('2147483648'))
        self.assertEqual(sql_usage(database), SQL_BYTE_CAP)
        query = database.execute.call_args.args[0]
        self.assertIn("schemaname='public'", query)
        self.assertIn("left(tablename,8)='current_'", query)
        self.assertIn('pg_total_relation_size', query)
        self.assertIn("format('%%I.%%I'", query)
        self.assertEqual(database.execute.call_args.args[1],
                         (['data_runtime', 'data_runtime_command', 'scanner_latest', 'latest_board', 'latest_board_status', 'coverage_latest'],))
        database.execute.assert_called_once()

    def test_empty_sql_sum_is_zero(self):
        self.assertEqual(sql_usage(self.database(None)), 0)

    def test_sql_usage_refuses_invalid_accounting(self):
        for value in (True, -1, Decimal('.5'), Decimal('NaN'), Decimal('Infinity'), '123', 12.0):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'current_database_storage_usage'):
                sql_usage(self.database(value))

    def test_disk_floor_includes_only_prospective_write(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.collection.current_storage_policy.shutil.disk_usage', return_value=SimpleNamespace(free=FREE_DISK_BYTE_FLOOR + 123)):
                require_disk_space(folder, 123)
                with self.assertRaisesRegex(BudgetStop, 'current_observation_disk_free_floor'):
                    require_disk_space(folder, 124)

    def test_missing_directory_uses_existing_ancestor_without_creating_it(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'future' / 'observations'
            with patch('app.collection.current_storage_policy.shutil.disk_usage', return_value=SimpleNamespace(free=2 * GIB)) as disk:
                require_disk_space(directory, JOURNAL_RECORD_BYTE_CAP)
                disk.assert_called_once_with(Path(folder))
            self.assertFalse(directory.exists())

    def test_invalid_write_size_never_reads_disk(self):
        with patch('app.collection.current_storage_policy.shutil.disk_usage') as disk:
            for value in (True, -1, 0.5, '1'):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'current_observation_write_size'):
                    require_disk_space('.', value)
            disk.assert_not_called()


if __name__ == '__main__':
    unittest.main()
