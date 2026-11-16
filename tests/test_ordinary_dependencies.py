from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from app.storage import ordinary_publication as live


def dependency(event_id, index):
    return dict(event_id=event_id, id=f'{index:064x}', price='price', contract='contract',
                event='event', receipt='receipt')


def test_publication_policy_binds_calculations_and_ignores_http_edits(monkeypatch, tmp_path):
    monkeypatch.setattr('app.comparison.snapshot_fee_scope.ACCOUNT_PATH', tmp_path / 'account.json')
    provider = 'sportsgameodds'
    baseline = live.policy_identity(provider)
    read_bytes = Path.read_bytes
    changed = live.POLICY_ROOT / 'app/dashboard/snapshot_api.py'

    def edited(path):
        content = read_bytes(path)
        return content + b'\n# changed\n' if path == changed else content

    monkeypatch.setattr(Path, 'read_bytes', edited)
    assert live.policy_identity(provider) == baseline
    for name in ('app/comparison/game_phase.py', 'app/storage/ordinary_dependencies.py',
                 'app/storage/ordinary_result.py'):
        changed = live.POLICY_ROOT / name
        assert live.policy_identity(provider) != baseline


def test_aggregate_authority_prefers_committed_config_and_keeps_the_legacy_default(monkeypatch):
    from app.collection import current_policy

    local = Mock(return_value={'aggregate_provider': 'sportsgameodds'})
    monkeypatch.setattr(current_policy, 'load', local)
    db = Mock()
    stored = db.execute.return_value.fetchone

    stored.return_value = {'config': {'aggregate_provider': 'sportsgameodds'}}
    assert live.committed_aggregate_provider(db) == 'sportsgameodds'
    stored.return_value = {'config': {}}
    assert live.committed_aggregate_provider(db) == current_policy.DEFAULT['aggregate_provider']
    stored.return_value = None
    assert live.committed_aggregate_provider(db) == current_policy.DEFAULT['aggregate_provider']
    assert db.execute.call_count == 3
    local.assert_not_called()

    assert not hasattr(live, 'aggregate_provider')
    with pytest.raises(TypeError):
        live.policy_identity()
    for provider in (None, '', 'other'):
        with pytest.raises(ValueError, match='supported aggregate provider'):
            live.policy_identity(provider)
    local.assert_not_called()


def test_large_planning_scan_keeps_only_event_signatures():
    count = 33_000
    rows = [dependency(f'game-{index % 50}', index) for index in range(count)]
    batches = [rows[i:i+live.DEPENDENCY_BATCH] for i in range(0, count, live.DEPENDENCY_BATCH)]
    db = MagicMock()
    cursor = db.cursor.return_value.__enter__.return_value
    cursor.fetchmany.side_effect = [*batches, []]

    signatures = live.planning_signatures(db, sorted({row['event_id'] for row in rows}),
                                         frames=False, at=datetime.now(timezone.utc))

    assert len(signatures) == 50
    assert cursor.fetchmany.call_count == len(batches) + 1
    assert signatures['game-0'] == live.dependency_signatures(
        (row['event_id'], row['id'], live.dependency_value(row))
        for row in rows if row['event_id'] == 'game-0')['game-0']
    assert len(set(signatures.values())) == 50


def test_desk_resolves_only_published_witnesses_and_preserves_receipt_semantics():
    raw, exact, unrelated = [dependency('game', index) for index in range(3)]
    result = dict(rows=[dict(current_authority=dict(price=dict(dependency=raw['id']),
        references=[dict(dependency=exact['id'], exact_frame=True)]))])
    db = Mock()
    db.execute.return_value = [raw, exact]

    def read():
        return live.published_dependencies(db, result, provider='the_odds_api', at=datetime.now(timezone.utc))

    current, initial_revision = read()
    assert set(current) == {raw['id'], exact['id']}
    query, params = db.execute.call_args.args
    assert 'WHERE c.id=ANY(%s)' in query
    assert params[-1] == sorted(current)
    assert unrelated['id'] not in params[-1]
    raw['receipt'] = 'confirmation'
    assert read()[1] == initial_revision
    exact['receipt'] = 'replacement frame'
    assert read()[1] != initial_revision
