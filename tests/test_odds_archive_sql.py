"""Quote admission and export against the disposable PostgreSQL fixture."""

import json
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from app.storage.odds_archive import observation, record
from app.storage.store import Store


@pytest.fixture
def db():
    socket = os.environ.get('DA_TEST_PGSOCKET')
    if socket is None:
        pytest.skip('Disposable PostgreSQL required')
    root = Path(socket).resolve().parent.parent
    assert root.parent == Path('/tmp').resolve() and root.name.startswith('predict-pg-')
    assert Path(socket).resolve() == root / '.local' / 'pgsocket'
    options = dict(host=socket, port=55432, user='prediction_arb', autocommit=True,
                   row_factory=dict_row, connect_timeout=5)
    name = 'prediction_arb_archive_' + uuid4().hex[:12]
    with psycopg.connect(dbname='prediction_arb', **options) as admin:
        assert Path(admin.execute('SHOW data_directory').fetchone()['data_directory']).resolve() == root / 'db'
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            with psycopg.connect(dbname=name, **options) as connection:
                Store(connection).migrate()
                yield connection
        finally:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


FEED = 'kalshi'


def quote(price='0.51000000000000000001', *, minute=0):
    received_at = f'2026-10-01T22:{minute:02d}:01+00:00'
    source_at = f'2026-10-01T22:{minute:02d}:00+00:00'
    identity = ['fixture-winner', 'away', 'asks']
    size = '9007199254740993.00001'
    book = [*identity, price, 'usd_per_contract', size, 'contracts', 'available']
    return observation(FEED, 'top', identity, 'fixture-event', source_at,
                       received_at, [f'book-{minute}', str(minute)], book)


def staged(db):
    return db.execute('SELECT id,body,batch_id FROM odds_archive_stage ORDER BY received_at').fetchall()


def usage(db):
    return db.execute('SELECT staged_bytes FROM odds_archive_usage WHERE singleton').fetchone()['staged_bytes']


def status(db):
    return db.execute('SELECT * FROM odds_archive_feed_status WHERE feed=%s', (FEED,)).fetchone()


def test_stage_rolls_back_with_admission_and_compacts_unchanged_quotes(db):
    first, unchanged, moved = quote(), quote(minute=1), quote('0.52', minute=2)
    with pytest.raises(RuntimeError, match='rejected source transaction'):
        with db.transaction():
            record(db, FEED, [first])
            assert usage(db) == first['bytes']
            raise RuntimeError('rejected source transaction')
    assert staged(db) == []
    assert usage(db) == 0
    assert status(db) is None
    assert db.execute('SELECT count(*) n FROM odds_archive_head').fetchone()['n'] == 0

    returned = quote(minute=3)
    with db.transaction():
        record(db, FEED, [first, unchanged, moved, returned])
    first_changes = [first, moved, returned]
    assert [row['id'].hex() for row in staged(db)] == [row['id'] for row in first_changes]
    assert [row['body'] for row in staged(db)] == [row['body'] for row in first_changes]
    assert usage(db) == sum(row['bytes'] for row in first_changes)
    assert status(db)['staged'] == 3
    assert status(db)['skipped'] == 0


def test_capacity_gap_keeps_admission_and_allows_exact_witness_recovery(db):
    first, second = quote(), quote('0.52', minute=1)
    with db.transaction():
        record(db, FEED, [first])
        record(db, FEED, [second], limit=first['bytes'])
        # Unrelated source transactions still commit while history is full.
        db.execute("UPDATE current_row_state SET epoch='archive-fixture' WHERE kind='epoch'")
    assert db.execute("SELECT epoch FROM current_row_state WHERE kind='epoch'").fetchone()['epoch'] == 'archive-fixture'
    assert [row['id'].hex() for row in staged(db)] == [first['id']]
    refused = status(db)
    assert refused['gap_reason'] == 'staging_or_disk_capacity'
    assert refused['skipped'] == 1
    assert refused['first_gap_at'] <= refused['last_gap_at']

    record(db, FEED, [second])
    assert [row['id'].hex() for row in staged(db)] == [first['id'], second['id']]
    assert status(db)['first_gap_at'] == refused['first_gap_at']


def test_archive_gap_restores_the_callers_lock_timeout(db):
    from app.storage.odds_archive import note_gap

    with db.transaction():
        db.execute("SET LOCAL lock_timeout='750ms'")
        note_gap(db, FEED, 1, 'archive_projection_failed')
        assert db.execute('SHOW lock_timeout').fetchone()['lock_timeout'] == '750ms'
        assert status(db)['skipped'] == 1
        assert status(db)['gap_reason'] == 'archive_projection_failed'


def test_sgo_shadow_records_only_material_quotes_and_leaves_discovery_absence_unknown(db, monkeypatch, tmp_path):
    import gzip

    from app.collection.sportsgameodds_adapter import parse_page
    from app.dashboard.u0_display import quote_display
    from app.storage.odds_archive_export import DirectoryArchive, claim, load_batch
    from app.storage.sportsgameodds_reference import prepare_page, upsert_rows
    from tests.test_sportsgameodds_adapter import response

    monkeypatch.setenv('PREDICT_ODDS_ARCHIVE_CAPTURE', '1')

    def prepare(source_at, received_at, *, available=True):
        raw = response()
        quote = raw['data'][0]['odds']['points-home-game-sp-home']['byBookmaker']['book']
        quote.update(lastUpdatedAt=source_at, available=available)
        return prepare_page(parse_page(json.dumps(raw).encode(), received_at))

    source = '2026-11-10T19:59:00Z'
    received = '2026-11-10T20:00:01Z'
    initial, = prepare(source, received)
    with db.transaction():
        assert upsert_rows(db, [initial]) == 1
    captured = staged(db)
    assert {row['body'][1] for row in captured} >= {'event', 'definition', 'top'}
    admitted = db.execute('SELECT facts FROM current_sgo_reference').fetchone()['facts']
    expected_odds = quote_display(admitted['price_american'], 'american_odds')

    newer_source = '2026-11-10T19:59:30Z'
    later_receipt = '2026-11-10T20:00:31Z'
    unchanged, = prepare(newer_source, later_receipt)
    with db.transaction():
        assert upsert_rows(db, [unchanged]) == 1
        assert upsert_rows(db, []) == 0
    live = db.execute('SELECT facts FROM current_sgo_reference').fetchone()['facts']
    assert live['received_at'] == later_receipt and live['available'] is True
    assert len([row for row in staged(db) if row['body'][1] == 'top']) == 1

    closed_at = '2026-11-10T20:01:00Z'
    closed, = prepare(newer_source, closed_at, available=False)
    with db.transaction():
        assert upsert_rows(db, [closed]) == 1
    top = [row['body'] for row in staged(db) if row['body'][1] == 'top']
    assert [row[4:6] for row in top] == [[source, received], [newer_source, closed_at]]
    assert [row[7][:5] for row in top] == [
        ['-110', 'american_odds', None, None, True],
        ['-110', 'american_odds', None, None, False],
    ]
    assert db.execute('SELECT facts FROM current_sgo_reference').fetchone()['facts']['available'] is False

    (tmp_path / '.predict-archive-id').write_text('sgo-fixture\n')
    batch = claim(db)
    receipt = DirectoryArchive(tmp_path, 'sgo-fixture').write(batch, load_batch(db, batch))
    with gzip.open(tmp_path / receipt['path'], 'rt') as archive:
        rows = [json.loads(line) for line in archive]
    as_of_initial_receipt = next(row for row in rows if row[2] == 'top' and row[6] == received)
    definition = next(row for row in rows if row[2] == 'definition' and row[3] == as_of_initial_receipt[3])
    assert as_of_initial_receipt[4:7] == [admitted[k] for k in ('event_id', 'source_at', 'received_at')]
    assert as_of_initial_receipt[7][:2] == [initial['revision'], admitted['receipt_sha256']]
    assert {k: definition[8][k] for k in ('line', 'period', 'settlement')} == {
        k: admitted[k] for k in ('line', 'period', 'settlement')}
    assert quote_display(*as_of_initial_receipt[8][:2]) == expected_odds
    assert expected_odds['american'] == '-110'


def test_restart_after_remote_write_reuses_batch_and_keeps_late_rows(db, tmp_path):
    from app.storage.odds_archive_export import DirectoryArchive, acknowledge, claim, load_batch

    path = tmp_path / 'mounted-archive'
    path.mkdir()
    identity = 'archive-fixture'
    (path / '.predict-archive-id').write_text(identity + '\n')
    remote = DirectoryArchive(path, identity)
    first, late = quote(), quote('0.52', minute=1)
    record(db, FEED, [first])
    batch = claim(db)
    original = load_batch(db, batch)
    uploaded = remote.write(batch, original)
    assert json.loads(original)[0] == first['id']
    assert len(staged(db)) == 1
    assert usage(db) == first['bytes']

    # The first exporter crashes after verification but before its SQL ack.
    # A later same-day receipt must not change that already-uploaded membership.
    record(db, FEED, [late])
    with psycopg.connect(db.info.dsn, autocommit=True, row_factory=dict_row) as resumed:
        retry = claim(resumed)
        assert retry == batch
        assert load_batch(resumed, retry) == original
        receipt = DirectoryArchive(path, identity).write(retry, original)
        assert receipt == uploaded
        assert files(path) == 1
        with pytest.raises(ValueError, match='odds_archive_remote_receipt_conflict'):
            acknowledge(resumed, retry, dict(receipt, sha256='0'*64))
        assert len(staged(resumed)) == 2
        assert acknowledge(resumed, retry, receipt)
        assert not acknowledge(resumed, retry, receipt)
        assert [row['id'].hex() for row in staged(resumed)] == [late['id']]

        patch = claim(resumed)
        assert patch != batch
        late_bytes = load_batch(resumed, patch)
        assert json.loads(late_bytes)[0] == late['id']
        acknowledge(resumed, patch, remote.write(patch, late_bytes))
    assert files(path) == 2
    assert staged(db) == []
    assert usage(db) == 0
    assert status(db)['verified'] == 2
    assert claim(db) is None


def files(path):
    return len(list(path.rglob('*.jsonl.gz')))


def test_exporter_reuses_verified_object_and_refuses_wrong_mount_or_content(tmp_path):
    import gzip

    from app.storage.odds_archive_export import DirectoryArchive
    from app.storage.store import encoded

    marker = tmp_path / '.predict-archive-id'
    marker.write_text('wrong-destination\n')
    archive = DirectoryArchive(tmp_path, 'archive-fixture')
    batch = dict(feed=FEED, receipt_day=date(2026, 10, 1), id='9'*64)
    first = quote()
    raw = encoded([first['id'], *first['body']]) + b'\n'
    with pytest.raises(ValueError, match='odds_archive_mount_identity_mismatch'):
        archive.write(batch, raw)
    assert files(tmp_path) == 0

    marker.write_text('archive-fixture\n')
    receipt = archive.write(batch, raw)
    target = tmp_path / receipt['path']
    before = target.read_bytes()
    assert gzip.decompress(before) == raw
    assert archive.write(batch, raw) == receipt
    assert files(tmp_path) == 1

    target.write_bytes(gzip.compress(b'different archived content'))
    with pytest.raises(ValueError, match='odds_archive_remote_content_conflict'):
        archive.write(batch, raw)
    assert gzip.decompress(target.read_bytes()) == b'different archived content'


def test_archive_replay_uses_receipt_cutoff_and_quote_time_definition(tmp_path):
    from app.storage.odds_archive import digest
    from app.storage.odds_archive_export import DirectoryArchive
    from app.storage.odds_archive_replay import daily, odds, replay_event
    from app.storage.store import encoded

    (tmp_path / '.predict-archive-id').write_text('replay-fixture\n')
    archive = DirectoryArchive(tmp_path, 'replay-fixture')
    day = date(2026, 10, 1)
    original = quote()
    moved = quote('0.52', minute=3)
    event = 'fixture-event'
    identity = ['fixture-winner', 'away', 'asks']
    source = {'native_market_id': identity[0], 'native_outcome_id': identity[1]}
    definition = observation(FEED, 'definition', 'fixture-contract', event, None,
                             original['received_at'], 'definition-before',
                             {'source': source, 'contract': {'line': '1.5'}})
    updated = observation(FEED, 'definition', 'fixture-contract', event, None,
                          '2026-10-01T22:01:01Z', 'definition-after',
                          {'source': source, 'contract': {'line': '2.5'}})
    gap = observation(FEED, 'discovery_gap', identity[0], event, None,
                      '2026-10-01T22:01:00Z', None, [identity[0], 'discovery_missed'])
    for group in ([original, definition], [updated, gap, moved]):
        records = sorted([item['id'], *item['body']] for item in group)
        batch = dict(feed=FEED, receipt_day=day,
                     id=digest([FEED, day.isoformat(), [row[0] for row in records]]))
        archive.write(batch, b''.join(encoded(row)+b'\n' for row in records))

    changes = replay_event(tmp_path, FEED, event, day, day, '2026-10-01T22:02:00Z')
    result = odds(changes, FEED, event, identity)
    assert result['price'] == '0.51000000000000000001'
    assert result['size'] == '9007199254740993.00001'
    assert result['definition']['contract']['line'] == '1.5'
    assert result['subsequent_status_changes'] == [gap['id']]
    assert result['freshness'] == 'not_established'
    changes = replay_event(tmp_path, FEED, event, day, day, '2026-10-01T22:03:01Z')
    assert odds(changes, FEED, event, identity)['definition']['contract']['line'] == '2.5'
    assert daily(tmp_path, day)[FEED]['records_by_kind'] == {'top': 2, 'definition': 2, 'discovery_gap': 1}


def test_native_admission_archives_exact_top_and_keeps_deeper_book_in_sql(db, monkeypatch):
    from psycopg.types.json import Jsonb
    from app.storage.current_rows import CurrentRowStore
    from app.storage.store import exact_time, hashed

    monkeypatch.setenv('PREDICT_ODDS_ARCHIVE_CAPTURE', '1')
    event = 'fixture-event'
    identity = hashed([FEED,event])
    start = '2026-10-01T22:03:00Z'
    db.execute('INSERT INTO current_event VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
               (identity,FEED,event,'NFL',start,exact_time(start),Jsonb({}),'fixture-event-revision'))
    store = CurrentRowStore(db)

    def image(minute, price, deeper):
        at = f'2026-10-01T22:{minute:02d}:00Z'
        receipt = f'2026-10-01T22:{minute:02d}:01Z'
        level = lambda px: dict(price={'value': px}, quantity={'value': '9007199254740993.01', 'unit': 'contracts'})
        return dict(raw=dict(ref=dict(venue=FEED,event_id=event,market_id='market'),
                             exchange_at=at,received_at=receipt), sync='synchronized', state='active',
                    quantity_unit='contracts', sequence=minute, outcomes=[
                        dict(outcome_id='yes', asks=dict(levels=[level(price),level(deeper)]), bids=None)])

    with db.transaction():
        store.replace_native_books([image(0,'0.51','0.61')])
        store.replace_native_books([image(1,'0.51','0.66')])
        store.replace_native_books([image(2,'0.53','0.66')])
        store.replace_native_books([image(3,'0.57','0.71')])
    changes = [row['body'] for row in staged(db)
               if row['body'][1]=='top' and row['body'][7][2]=='asks']
    assert [row[7][3:7] for row in changes] == [
        ['0.51','usd_per_contract','9007199254740993.01','contracts'],
        ['0.53','usd_per_contract','9007199254740993.01','contracts'],
    ]
    assert [row[6][1] for row in changes] == ['0','2']
    depth = db.execute("""SELECT price_value FROM current_native_depth
                          WHERE side='asks' ORDER BY level""").fetchall()
    assert [row['price_value'] for row in depth] == ['0.57','0.71']


def test_pre_start_quote_received_after_kickoff_is_excluded():
    from app.storage.odds_archive import native_book
    from app.storage.odds_retention import pregame

    start = '2026-11-10T20:00:00.123456789Z'
    before = '2026-11-10T20:00:00.123456788Z'
    assert pregame(start,before)
    assert not pregame(start,start)
    assert not pregame(start,before,source_at=start)
    assert not pregame(start,before,event={'status': {'live': True}})
    assert not pregame(start,before,event={'status': {'started': True}})
    book = dict(raw=dict(ref=dict(venue='kalshi', event_id='event', market_id='market'),
                         exchange_at=before, received_at=start),
                state='active', outcomes=[])
    assert not native_book(book, revision='witness', event={}, starts_at=start)


def test_sgo_archives_only_pregame_quotes_and_page_members():
    from copy import deepcopy

    from app.collection.sportsgameodds_adapter import parse_page
    from app.storage.odds_archive import sgo_page, sgo_quote
    from app.storage.sportsgameodds_reference import prepare_frames, prepare_page
    from app.storage.store import stamp
    from tests.test_sportsgameodds_adapter import AT, response

    raw = response()
    future = raw['data'][0]
    live = deepcopy(future)
    live['eventID'] = 'live'
    live['status'].update(started=True, live=True, startsAt='2026-11-10T19:00:00Z')
    raw['data'].append(live)
    page = parse_page(json.dumps(raw).encode(), AT)
    rows = prepare_page(page)
    frames = prepare_frames(page, rows)
    by_event = {row['event_id']: row for row in rows}
    pregame = by_event[future['eventID']]
    assert sgo_quote(pregame)
    assert not sgo_quote(by_event['live'])
    assert not sgo_quote(dict(pregame, facts=dict(pregame['facts'], received_at=pregame['facts']['starts_at'])))
    receipts = sgo_page(dict(sport='NBA', received_at=AT, sgo_reference_rows=rows, sgo_event_frames=frames,
                             event_scopes={event['event_id']: event['league'] for event in page.events}))
    assert receipts[0]['body'][-1] == [(future['eventID'], future['leagueID'])]
    hours = (stamp(by_event['live']['expires_at']) - stamp(AT)).total_seconds()/3600
    assert 6 <= hours <= 24
    assert by_event['live']['expires_at'] == next(frame['expires_at'] for frame in frames if frame['event_id']=='live')


def test_sgo_live_quote_stays_current_until_short_working_expiry(db, monkeypatch):
    from app.collection.sportsgameodds_adapter import parse_page
    from app.storage.sportsgameodds_reference import (
        prepare_frames, prepare_page, prune, prune_frames, read_event, read_event_frame, upsert_frames, upsert_rows,
    )
    from tests.test_sportsgameodds_adapter import response

    monkeypatch.setenv('PREDICT_ODDS_ARCHIVE_CAPTURE', '1')
    raw = response()
    event = raw['data'][0]
    event_id = event['eventID']
    event['status'].update(started=True, live=True, startsAt='2026-11-10T19:00:00Z')
    book = event['odds']['points-home-game-sp-home']['byBookmaker']['book']
    book['lastUpdatedAt'] = '2026-11-10T19:59:59Z'
    received = '2026-11-10T20:00:00Z'
    page = parse_page(json.dumps(raw).encode(), received)
    with db.transaction():
        rows = prepare_page(page)
        upsert_rows(db, rows)
        upsert_frames(db, prepare_frames(page, rows))
    assert read_event(db, event_id)[0]['facts']['phase'] == 'live'
    assert read_event_frame(db, event_id)['facts']['event_context']['phase'] == 'live'
    assert staged(db) == []

    # An installed database can still carry the old 14-day expiry. Its next
    # bounded legacy maintenance pass understands both original clocks.
    db.execute("UPDATE sgo_quote_revision SET expires_at=expires_at+interval '13 days'")
    db.execute("UPDATE sgo_event_evidence SET expires_at=expires_at+interval '13 days' WHERE kind='frame'")
    with db.transaction():
        assert prune(db, at=received, include_legacy=True)==0
        assert prune_frames(db, at=received, include_legacy=True)==0
        at = '2026-11-11T19:00:01Z'
        assert prune(db, at=at, include_legacy=True)==1
        assert prune_frames(db, at=at, include_legacy=True)==1
    assert read_event(db, event_id) == []
    assert read_event_frame(db, event_id) is None
    assert db.execute('SELECT count(*) n FROM current_sgo_history').fetchone()['n']==0
