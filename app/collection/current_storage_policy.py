"""Approved light local disk allowances for ordinary Predict collection.

These are disk allowances, separate from the unchanged runtime memory guard.
The free-space floor protects the host filesystem without reserving the entire
journal allowance up front. No helper deletes observations or modifies SQL.
"""
from decimal import Decimal
from pathlib import Path
import shutil

from .odds_http import BudgetStop


VERSION = 'predict-local-storage-1'
MIB = 1024 * 1024
GIB = 1024 * MIB
JOURNAL_SEGMENT_BYTE_CAP = 256 * MIB
JOURNAL_BYTE_CAP = 8 * GIB
JOURNAL_RECORD_BYTE_CAP = 8 * MIB
SQL_BYTE_CAP = 2 * GIB
FREE_DISK_BYTE_FLOOR = GIB


def sql_usage(db):
    """Read current-table heap, indexes and TOAST bytes, including SQL history."""
    row = db.execute(
        "SELECT sum(pg_total_relation_size(format('%I.%I',schemaname,tablename))) AS n "
        "FROM pg_tables WHERE schemaname='public' AND left(tablename,8)='current_'"
    ).fetchone()
    value = row['n']
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError('current_database_storage_usage')
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError('current_database_storage_usage')
    if value < 0 or int(value) != value:
        raise ValueError('current_database_storage_usage')
    return int(value)


def require_disk_space(path, append_bytes=0):
    """Refuse a write that would consume the final GiB on its filesystem.

    New observation directories use the nearest existing ancestor. A check is
    advisory against external disk writers; the actual write can still fail and
    its owner must preserve/retain that failure through the existing path.
    """
    if isinstance(append_bytes, bool) or not isinstance(append_bytes, int) or append_bytes < 0:
        raise ValueError('current_observation_write_size')
    directory = Path(path)
    while not directory.exists():
        directory = directory.parent
    if shutil.disk_usage(directory).free < FREE_DISK_BYTE_FLOOR + append_bytes:
        raise BudgetStop('current_observation_disk_free_floor')
