from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock

from app.storage import ordinary_publication as live


def dependency(event_id, index):
    return dict(event_id=event_id, id=f'{index:064x}', price='price', contract='contract',
                event='event', receipt='receipt')


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
