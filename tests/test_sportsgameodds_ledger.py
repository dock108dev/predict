from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from app.collection.sportsgameodds_ledger import ObjectLedger

NOW = datetime(2026, 11, 10, 20, tzinfo=timezone.utc)


def ledger(tmp_path):
    result = ObjectLedger(tmp_path / 'disposable.sqlite')
    result.create_window('w', limit=100, initial_used=10, reserve=10, requests_per_minute=10)
    return result


def test_holds_survive_restart_and_only_evidence_resolves(tmp_path):
    book = ledger(tmp_path)
    book.reserve('w', 'a', objects=25, now=NOW)
    book = ObjectLedger(book.path)
    assert book.status('w')['held'] == 25
    with pytest.raises(ValueError):
        book.resolve('a', charged=1, evidence='', now=NOW)
    assert book.status('w')['held'] == 25
    book.resolve('a', charged=1, evidence='successful empty response', now=NOW)
    assert book.status('w')['available'] == 79
    with pytest.raises(RuntimeError):
        book.resolve('a', charged=1, evidence='duplicate', now=NOW)


def test_concurrent_reservations_are_atomic(tmp_path):
    book = ledger(tmp_path)
    def attempt(i):
        try:
            book.reserve('w', str(i), objects=30, now=NOW)
            return True
        except RuntimeError:
            return False
    with ThreadPoolExecutor(max_workers=5) as executor:
        assert sum(executor.map(attempt, range(5))) == 1
    assert book.status('w')['held'] == 30


def test_pause_stop_retry_and_window_expiry(tmp_path):
    book = ledger(tmp_path)
    book.set_paused('w', True)
    book = ObjectLedger(book.path)
    with pytest.raises(RuntimeError):
        book.reserve('w', 'a', objects=1, now=NOW)
    book.set_paused('w', False)
    for control in ({'stopped': True}, {'source_paused': True}):
        with pytest.raises(RuntimeError):
            book.reserve('w', 'a', objects=1, now=NOW, **control)
    book.note_rate_limit('w', retry_after=NOW + timedelta(minutes=3), now=NOW)
    book.note_rate_limit('w', retry_after=NOW + timedelta(minutes=1), now=NOW)
    with pytest.raises(RuntimeError):
        book.reserve('w', 'a', objects=1, now=NOW + timedelta(minutes=2))
    book.reserve('w', 'a', objects=1, now=NOW + timedelta(minutes=3))
    book.create_window('next', limit=100, initial_used=0, reserve=0, reset_at=NOW + timedelta(hours=1))
    with pytest.raises(RuntimeError):
        book.reserve('next', 'b', objects=1, now=NOW + timedelta(hours=1))


def test_overrun_latches_pause_and_retains_hold(tmp_path):
    book = ledger(tmp_path)
    book.reserve('w', 'a', objects=1, now=NOW)
    with pytest.raises(ValueError):
        book.resolve('a', charged=2, evidence='unexpected response', now=NOW)
    assert book.status('w')['paused']
    assert book.status('w')['held'] == 2
    with pytest.raises(RuntimeError):
        book.set_paused('w', False)
    book.resolve('a', charged=2, evidence='overrun verified', now=NOW)
    book.set_paused('w', False)
    assert book.status('w')['charged'] == 2


def test_existing_unrelated_records_preserved(tmp_path):
    path = tmp_path / 'existing.sqlite'
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE protected_holds (id TEXT)')
        db.execute("INSERT INTO protected_holds VALUES ('keep')")
        db.commit()
    ObjectLedger(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT id FROM protected_holds').fetchall() == [('keep',)]


def test_request_rate_survives_restart(tmp_path):
    book = ObjectLedger(tmp_path / 'rate.sqlite')
    book.create_window('w', limit=100, initial_used=0, reserve=0, requests_per_minute=1)
    book.reserve('w', 'a', objects=1, now=NOW)
    book = ObjectLedger(book.path)
    with pytest.raises(RuntimeError, match='request rate'):
        book.reserve('w', 'b', objects=1, now=NOW + timedelta(seconds=59))
    book.resolve('a', charged=1, evidence='received one object', now=NOW + timedelta(seconds=59))
    book.reserve('w', 'b', objects=1, now=NOW + timedelta(seconds=60))


def test_usage_and_event_requests_share_persistent_rate_limit(tmp_path):
    book = ObjectLedger(tmp_path / 'shared.sqlite')
    book.create_window('account:window', limit=100, initial_used=0, reserve=0, requests_per_minute=2)
    book.reserve_request('account', requests_per_minute=2, now=NOW)
    book = ObjectLedger(book.path)
    book.reserve('account:window', 'first', objects=1, now=NOW)
    book.resolve('first', charged=1, evidence='response', now=NOW)
    with pytest.raises(RuntimeError, match='request rate'):
        book.reserve_request('account', requests_per_minute=2, now=NOW+timedelta(seconds=5))
    book.reserve_request('account', requests_per_minute=2, now=NOW+timedelta(seconds=60))


def test_unresolved_previous_window_blocks_new_window_after_restart(tmp_path):
    book = ObjectLedger(tmp_path / 'window.sqlite')
    book.create_window('account:old', limit=100, initial_used=0, reserve=0, requests_per_minute=10)
    book.reserve('account:old', 'old', objects=2, now=NOW)
    book.create_window('account:new', limit=100, initial_used=0, reserve=0, requests_per_minute=10)
    book = ObjectLedger(book.path)
    with pytest.raises(RuntimeError, match='unresolved'):
        book.reserve('account:new', 'new', objects=2, now=NOW+timedelta(minutes=1))
    book.resolve('old', charged=1, evidence='verified response', now=NOW+timedelta(minutes=1))
    book.reserve('account:new', 'new', objects=2, now=NOW+timedelta(minutes=1))


def test_rate_history_pruned_but_clock_regression_stays_blocked(tmp_path):
    book = ObjectLedger(tmp_path / 'bounded.sqlite')
    for i in range(120):
        book.reserve_request('account', requests_per_minute=5, now=NOW+timedelta(minutes=i))
    with closing(sqlite3.connect(book.path)) as db:
        assert db.execute('SELECT count(*) FROM sgo_http_request').fetchone()[0] == 1
    with pytest.raises(RuntimeError, match='clock regressed'):
        book.reserve_request('account', requests_per_minute=5, now=NOW)


def test_connections_close_on_success_and_failure(tmp_path):
    from unittest.mock import patch
    created = []
    real_connect = sqlite3.connect
    class TrackingConnection(sqlite3.Connection):
        def close(self):
            self.closed_by_ledger = True
            return super().close()
    def connect(*args, **kwargs):
        db = real_connect(*args, factory=TrackingConnection, **kwargs)
        db.closed_by_ledger = False
        created.append(db)
        return db
    with patch('app.collection.sportsgameodds_ledger.sqlite3.connect', side_effect=connect):
        book = ObjectLedger(tmp_path / 'closed.sqlite')
        book.create_window('w', limit=10, initial_used=0, reserve=0)
        book.reserve('w', 'a', objects=1, now=NOW)
        with pytest.raises(RuntimeError):
            book.reserve('w', 'b', objects=1, now=NOW)
        book.status('w')
    assert created and all(db.closed_by_ledger for db in created)
