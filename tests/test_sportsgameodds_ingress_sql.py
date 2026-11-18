"""Atomic SGO page admission against a disposable PostgreSQL cluster."""
import asyncio
import json
from copy import deepcopy
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from psycopg import sql
from psycopg.types.json import Jsonb

from app.collection.current_database import DatabaseIngressSink
from app.collection.current_policy import DEFAULT
from app.collection.sportsgameodds_adapter import parse_page
from app.collection.sportsgameodds_current_rows import current_rows
from app.storage.sportsgameodds_reference import prepare_page, prepare_frames, upsert_rows, upsert_frames
from app.storage.current_rows import prepare
from app.storage.store import Store
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_sportsgameodds_adapter import parse, response
from tests.test_ev09_n01 import AT
from tests.test_pregame_reference import rule


def authored_book_rule(_observation, _book, family, _legs, _at):
    return rule(outcomes=('over', 'under') if family == 'total' else ('home', 'away'))


def authored_venue_rule(row):
    family = row['original_record']['market_identity']['family']
    return authored_book_rule(None, None, family, None, None), None


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class SportsGameOddsPregameDeskSQL(LatestBoardFixture):
    def reviewed_fixture(self):
        self.enterContext(patch('app.storage.pregame_reference_publication.reviewed_rules',
                                return_value=authored_book_rule))
        self.enterContext(patch('app.storage.pregame_reference_publication.venue_rules',
                                side_effect=authored_venue_rule))

    async def test_native_pregame_book_only_estimates_in_all_leagues(self):
        from datetime import timedelta
        from decimal import Decimal
        from fractions import Fraction

        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        from app.collection.admission_enrichment import repair_registry
        from app.dashboard.snapshot_api import mount
        from app.normalization.college_registry import expanded
        from app.normalization.registry import Registry
        from app.storage import ordinary_publication
        from app.storage.current_rows import CurrentRowStore
        from app.storage.store import stamp
        from tests.broad_pipeline_fixtures import captured_partial
        from tests.multisport_fixtures import FAMILIES, SPORTS, source_case

        self.reviewed_fixture()
        self.at = stamp('2026-11-15T16:00:00Z')
        received = self.at.isoformat()
        config = dict(DEFAULT, aggregate_provider='sportsgameodds', sports=list(SPORTS),
                      families=list(FAMILIES), live_enabled=False)
        self.service.config = config
        self.service.states['sportsgameodds'] = {'state': 'available'}
        self.state.write(self.service)
        self.enterContext(patch('app.collection.current_policy.load', return_value=config))
        self.enterContext(patch('app.comparison.public_sportsbook_estimate.read_captures', return_value={}))
        self.enterContext(patch('app.comparison.public_sportsbook_estimate.retained_prices', return_value={}))

        # Local transport IDs model reviewed native participants. Only the SGO
        # team labels exercise the production college alias registry.
        college = ('NCAAB:M:D1:NCAA254', 'NCAAB:M:D1:NCAA485')
        registry = json.loads(repair_registry().to_json())
        for cid in college:
            team = dict(expanded().entities[cid])
            registry['entities'].append(team)
            registry['aliases'].append(dict(kind='team', league='NCAAB', text=team['name'], targets=[cid], source='fixture'))
            for venue in ('kalshi', 'polymarket_us'):
                registry['native_mappings'].append(dict(kind='team', league='NCAAB', venue=venue, environment='production',
                    native_id=f'fixture-{cid}', target=cid, source='fixture'))
        native_fixture = Registry(registry)
        self.enterContext(patch('app.collection.admission_enrichment.repair_registry', return_value=native_fixture))
        self.enterContext(patch('app.normalization.native_registry.native_registry', return_value=native_fixture))

        records, books, events, expected = [], [], [], {}
        for league in SPORTS:
            for index, (family, bet_type) in enumerate(zip(FAMILIES, ('ml', 'sp', 'ou'), strict=True)):
                total = {'NBA': '225.5', 'NCAAB': '123.5', 'MLB': '8.5', 'NHL': '5.5'}.get(league, '45.5')
                spread = {'NCAAB': '11.5', 'MLB': '1.5', 'NHL': '1.5'}.get(league, '3.5')
                native_line = {'moneyline': None, 'spread': spread, 'total': total}[family]
                # Distinct start times keep repeated teams from becoming an ambiguous occurrence.
                case = source_case(league, family, f'book-only-{league}-{family}',
                                   clock=self.at + timedelta(minutes=index), line=native_line,
                                   participants=college if league == 'NCAAB' else None)
                start = case['event']['scheduled_start']
                case.update(period='full_game', clock=self.at)
                for venue in ('kalshi', 'polymarket_us'):
                    captured, exclusions, book, _ = await captured_partial(case, venue)
                    self.assertEqual(exclusions, [])
                    records.extend(captured)
                    books.append(book)

                event = dict(eventID=f'book-only-{league}-{family}', leagueID=league, odds={},
                             status=dict(startsAt=start, started=False, live=False),
                             teams={team['ordering']: dict(teamID=team['id'], names=dict(long=team['name']))
                                    for team in case['events']['polymarket_us']['teams']})
                if league == 'NCAAB':
                    event['teams']['home']['names']['long'] = 'Georgia State Panthers'
                    event['teams']['away']['names']['long'] = 'Norfolk State'
                sides = ('over', 'under') if family == 'total' else ('home', 'away')
                lines = (-Decimal(spread), Decimal(spread)) if family == 'spread' else (native_line, native_line)
                alternate_total = '144.5' if league == 'NCAAB' else str(Decimal(total) + 1)
                alternate_spread = Decimal(spread) + 1
                alternate = {'spread': (-alternate_spread, alternate_spread), 'total': (alternate_total, alternate_total)}.get(family)
                prices = ('-110', '-120')
                for position, (side, opposite, line, price) in enumerate(zip(sides, reversed(sides), lines, prices, strict=True)):
                    book = dict(available=True, odds=price, lastUpdatedAt=received)
                    by_book = {'fanduel': book}
                    if alternate:
                        field = 'spread' if family == 'spread' else 'overUnder'
                        book[field] = str(line)
                        by_book['draftkings'] = dict(book, odds='+500', **{field: str(alternate[position])})
                    odd_id = f'{bet_type}-{side}'
                    event['odds'][odd_id] = dict(oddID=odd_id, opposingOddID=f'{bet_type}-{opposite}',
                        periodID='game', statID='points', statEntityID='all' if family == 'total' else side,
                        betTypeID=bet_type, sideID=side, byBookmaker=by_book)
                    predicate = 'win' if family == 'moneyline' else 'cover' if family == 'spread' else side
                    key = (league, 'winner' if family == 'moneyline' else family, predicate,
                           case['event'][side] if side in ('home', 'away') else None,
                           None if line is None else Fraction(line))
                    implied = [Fraction(110, 210), Fraction(120, 220)]
                    probability = implied[position] / sum(implied)
                    venues = {'polymarket_us'} if family == 'moneyline' and side == 'away' else {'kalshi', 'polymarket_us'}
                    expected[key] = (price, prices[1-position], probability, venues)
                events.append(event)

        parsed = parse_page(json.dumps(dict(success=True, data=events)).encode(), received)
        self.assertEqual(current_rows(parsed, parsed.receipt_sha256)[0], [])
        references = prepare_page(parsed)
        with self.connect() as db:
            db.execute('TRUNCATE current_event,comparison_publication CASCADE')
            db.execute("INSERT INTO comparison_publication(kind,id,generation,facts) VALUES('live','',0,'{}')")
            store = CurrentRowStore(db)
            store.upsert_records(records, now=received)
            store.replace_native_books(books)
            upsert_rows(db, references)
            upsert_frames(db, prepare_frames(parsed, references))
            self.assertEqual(db.execute("SELECT count(*) AS n FROM current_event WHERE provider='sportsgameodds'").fetchone()['n'], 0)
            with patch('app.storage.ordinary_publication.utc', return_value=received), \
                    patch('app.storage.comparison_snapshot.utc', return_value=received):
                self.assertTrue(ordinary_publication.turn(db)['published'])

        from app.storage.current_pregame import affected
        from app.comparison.current_pregame import reference
        from app.comparison.public_sportsbook_estimate import outcome
        checked=set()
        with self.connect() as db:
            for record in records:
                source=record['quote']['source']
                events,observations,occurrence=affected(db,dict(provider=source['provider'],
                    native_event_id=source['native_event_id']),self.at)
                event=record['event']
                key=outcome(record['market_identity']['family'],record['selection'],event['home'],event['away'])
                if not key:
                    self.assertIn(record['selection']['predicate'],('not_win','not_cover'))
                    continue
                ref=reference(record,observations,at=self.at)
                family,side,line=key
                selected=record['selection']
                expected_key=(event['competition'],'winner' if family=='moneyline' else family,
                    selected['predicate'],selected.get('participant'),line)
                self.assertEqual(ref['book'],'fanduel')
                self.assertEqual(Fraction(ref['probability']),expected[expected_key][2])
                checked.add(expected_key)
        self.assertEqual(checked,set(expected))

    async def test_published_pregame_estimates_persist_and_leave_at_kickoff(self):
        from datetime import timedelta

        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        from app.dashboard.snapshot_api import mount
        from app.storage.store import stamp
        from tests.test_sportsgameodds_adapter import AT as receipt_at

        self.reviewed_fixture()
        self.at = stamp(receipt_at)
        prior_repair = (Path(__file__).resolve().parents[1] / 'app/storage/migrations/095_sgo_quote_state.sql').read_text()
        raw = response()
        event, = raw['data']
        event['eventID'] = 'ranked-pregame-e2e'
        event['teams']['home']['names']['long'] = 'Detroit Pistons'
        event['teams']['away']['names']['long'] = 'Boston Celtics'
        home, = event['odds'].values()
        book, = home['byBookmaker'].values()
        home['byBookmaker'] = {'novig': dict(book, odds='+120'),
                             'prophetexchange': dict(book, odds='+115'), 'fanduel': book}
        away = dict(home, oddID=home['opposingOddID'], opposingOddID=home['oddID'],
                    statEntityID='away', sideID='away', byBookmaker={'fanduel': dict(book, spread='1.5')})
        event['odds'][away['oddID']] = away
        self.service.config.update(aggregate_provider='sportsgameodds', sports=['NBA'], families=['spread'],
                                   direct_novig_enabled=False)
        self.service.states['sportsgameodds'] = {'state': 'available'}
        # The old venue transports are separate from the aggregate fallback.
        self.service.states.update(novig={'state': 'stopped'}, prophetx={'state': 'stopped'})
        self.state.write(self.service)
        sink = DatabaseIngressSink(SimpleNamespace(provider=self.service), self.service.config)

        def admit():
            received = self.at.isoformat().replace('+00:00', 'Z')
            parsed = parse_page(json.dumps(raw).encode(), received)
            records, _ = current_rows(parsed, parsed.receipt_sha256)
            references = prepare_page(parsed)
            with patch('app.collection.current_database.connect', side_effect=self.connect), \
                    patch('app.collection.current_database.utc', return_value=received):
                sink.prepare(dict(type='current_aggregate_records', source='sportsgameodds', sport='NBA',
                    records=records, sgo_reference_rows=references, sgo_event_frames=prepare_frames(parsed, references),
                    receipt_sha256=parsed.receipt_sha256, event_scopes={event['eventID']: 'NBA'},
                    complete_venues=[], received_at=received), self.service.states, Event())

        def publish():
            from app.storage import ordinary_publication
            self.state.write(self.service)
            with self.connect() as db, patch('app.storage.ordinary_publication.utc', return_value=self.at.isoformat()), \
                    patch('app.storage.comparison_snapshot.utc', return_value=self.at.isoformat()):
                result = ordinary_publication.turn(db)
                self.assertEqual(result['errors'], [])

        def offers(db):
            return db.execute('''SELECT c.venue,o.facts->>'state' state,o.source_at,o.received_at,
                o.revision,o.price_dependency,o.sgo_quote_id,o.sgo_quote_revision,c.native_outcome_id
                FROM current_offer_storage o JOIN current_contract_storage c ON c.id=o.contract_id
                WHERE o.sgo_quote_id IS NOT NULL ORDER BY c.venue,c.native_outcome_id''').fetchall()

        with self.connect() as db:
            db.execute('TRUNCATE current_event,comparison_publication CASCADE')
            db.execute("INSERT INTO comparison_publication(kind,id,generation,facts) VALUES('live','',0,'{}')")
        admit()
        with self.connect() as db, db.transaction():
            original = offers(db)
            self.assertEqual([(row['venue'], row['state']) for row in original],
                             [('novig', 'available'), ('prophetx', 'available')])
            db.execute("UPDATE current_offer_storage SET facts=jsonb_set(facts,'{state}','\"stopped\"'::jsonb) "
                       "WHERE sgo_quote_id IS NOT NULL")
            db.execute(prior_repair)
            restored = offers(db)
            self.assertEqual([dict(row, revision=None) for row in restored],
                             [dict(row, revision=None) for row in original])
            Store(db).migrate()
            self.assertEqual(restored, offers(db))

        from app.storage.current_pregame import process, read
        with self.connect() as db:
            result=process(db,at=self.at)
            self.assertTrue(result)
            page=read(db,dict(browse='1',lines='all'),at=self.at)
            self.assertEqual(page['state'],'ready')
            self.assertEqual(page['provider_requests'],0)
            self.assertEqual(page['scheduled_calculations'],0)
            # Missing applicable fees stay an internal reason, never a partial ticket.
            for item in page['rows']:
                self.assertIsNotNone(item['fee'])
                self.assertIsNotNone(item['raw']['net_ev'])
            self.at+=timedelta(days=4)
            self.assertEqual(read(db,dict(browse='1'),at=self.at)['rows'],[])


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class SportsGameOddsAtomicIngress(LatestBoardFixture):
    async def test_upgrade_links_exact_legacy_value_and_preserves_each_receipt(self):
        from uuid import uuid4

        from psycopg.errors import CheckViolation

        name = 'prediction_arb_sgo_upgrade_' + uuid4().hex[:8]
        raw = response()
        odd = raw['data'][0]['odds']['points-home-game-sp-home']
        odd['byBookmaker']['novig'] = odd['byBookmaker'].pop('book')
        page = parse(raw)
        reference, = prepare_page(page)
        records, _ = current_rows(page, page.receipt_sha256)
        record, = records
        record['quote']['times']['received_at'] = '2026-11-10T20:00:05Z'
        record['quote']['provenance']['sha256'] = 'a' * 64
        original = prepare(record)
        with self.connect('prediction_arb') as control:
            control.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            try:
                with self.connect(name) as db:
                    Store(db).migrate(through='077_sgo_live_ev_delivery.sql')
                    db.execute('INSERT INTO current_sgo_reference VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                        (*[reference[k] for k in ('id','event_id','bookmaker_id','source_order','received_order','expires_at','revision')],
                         Jsonb(reference['facts'])))
                    db.execute('INSERT INTO current_event VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                        (original['event_id'],'sportsgameodds',record['event']['id'],record['event']['competition'],
                         record['event']['scheduled_start'],original['expires_order'],Jsonb(original['event']),original['event_revision']))
                    source = original['source']
                    db.execute('INSERT INTO current_contract VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                        (original['contract_id'],original['event_id'],original['venue'],source['native_market_id'],
                         source['native_outcome_id'],source['native_side'],Jsonb(original['contract']),original['contract_revision']))
                    q = original['quote']
                    db.execute('INSERT INTO current_offer VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                        (original['contract_id'],q['original']['value'],q['original']['units'],q['original']['quantity_units'],
                         original['source_at'],original['source_order'],original['received_at'],
                         original['received_order'],Jsonb(q),original['revision']))
                    before = db.execute('SELECT * FROM current_offer').fetchone()
                    refs = db.execute('SELECT * FROM current_sgo_reference').fetchall()
                    Store(db).migrate(through='078_sgo_quote_authority.sql')
                    assert db.execute('SELECT * FROM current_offer').fetchone() == before
                    assert db.execute('SELECT * FROM current_sgo_reference').fetchall() == refs
                    physical = db.execute('SELECT price_value,facts,sgo_quote_id,sgo_quote_revision FROM current_offer_storage').fetchone()
                    assert physical['price_value'] is None and 'value' not in physical['facts']['original']
                    assert (physical['sgo_quote_id'],physical['sgo_quote_revision']) == (reference['id'],reference['revision'])
                    assert before['facts']['provenance']['sha256'] != refs[0]['facts']['receipt_sha256']
                    Store(db).migrate(through='095_sgo_quote_state.sql')
                    original_reference = db.execute('SELECT * FROM current_sgo_reference').fetchone()
                    original_offer = db.execute('SELECT * FROM current_offer').fetchone()
                    Store(db).migrate()
                    self.assertEqual(db.execute('SELECT * FROM current_sgo_reference').fetchone(), original_reference)
                    self.assertEqual(db.execute('SELECT * FROM current_offer').fetchone(), original_offer)
                    self.assertIsNone(db.execute('SELECT closure_received_order FROM sgo_quote_revision')
                                      .fetchone()['closure_received_order'])
                    with self.assertRaises(CheckViolation) as raised, db.transaction():
                        db.execute('UPDATE sgo_quote_revision SET closure_received_order=received_order-1')
                    self.assertEqual(raised.exception.diag.constraint_name, 'sgo_closure_receipt_order')
            finally:
                control.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))

    async def test_live_ev_write_clock_requires_fresh_prices_at_seal(self):
        from datetime import timedelta

        from app.storage.delivery_clocks import published, recent, sgo_admitted

        with self.connect() as db, db.transaction(force_rollback=True):
            at = db.execute('SELECT clock_timestamp() at').fetchone()['at']
            received = at.isoformat()
            sgo_admitted(db, {'NHL', 'NBA'}, received)
            published(db, [('sportsgameodds', league, received) for league in ('NHL', 'NBA')],
                      live_sportsbook=[('NHL', received, (at + timedelta(minutes=1)).isoformat()),
                                       ('NBA', received, (at - timedelta(seconds=1)).isoformat())])
            rows = {row['league']: row for row in recent(db) if row['received_at'] == received}
            assert rows['NBA']['first_publication_write_at']
            assert rows['NBA']['first_live_sportsbook_write_at'] is None
            assert rows['NHL']['first_live_sportsbook_write_at']

    async def test_history_rotates_oldest_at_capacity(self):
        from app.storage.sportsgameodds_reference import archive_revisions
        from app.storage.store import encoded
        pregame = dict(phase='pregame', starts_at='2026-11-11T00:00:00Z', received_at='2026-11-10T20:00:00Z')
        def row(n):
            return dict(id=str(n), event_id='rotation-fixture', revision=str(n), facts=dict(pregame, n=n))
        with self.connect() as db, patch('app.storage.sportsgameodds_reference.HISTORY_BYTES', 2 * len(encoded(row(1)['facts']))):
            with db.transaction():
                archive_revisions(db, 'reference', [row(1)])
                archive_revisions(db, 'reference', [row(2)])
                archive_revisions(db, 'reference', [row(3)])
            self.assertEqual([r['identity'] for r in db.execute(
                "SELECT identity FROM current_sgo_history WHERE event_id='rotation-fixture' ORDER BY identity").fetchall()], ['2', '3'])
            self.assertEqual(db.execute('SELECT evicted_capacity FROM current_sgo_history_state').fetchone()['evicted_capacity'], 1)
            with patch('app.collection.current_storage_policy.sql_usage', return_value=2 * 1024**3):
                with db.transaction():
                    archive_revisions(db, 'reference', [row(4)])
            self.assertEqual(db.execute("SELECT count(*) n FROM current_sgo_history WHERE event_id='rotation-fixture'").fetchone()['n'], 2)
            self.assertEqual(db.execute('SELECT skipped_runway FROM current_sgo_history_state').fetchone()['skipped_runway'], 1)
            db.execute("DELETE FROM current_sgo_history WHERE event_id='rotation-fixture'")

    async def test_history_rotation_preserves_oldest_order_across_bounded_batches(self):
        from app.storage.sportsgameodds_reference import archive_revisions
        from app.storage.store import encoded
        facts=dict(phase='pregame',starts_at='2026-11-11T00:00:00Z',received_at='2026-11-10T20:00:00Z',pad='x'*512)
        size=len(encoded(facts))
        incoming=dict(id='new',event_id='bounded-rotation',revision='new',facts=dict(facts,pad='y'*(600*size)))
        expected=(len(encoded(incoming['facts']))+size-1)//size
        self.assertGreater(expected,512)
        with self.connect() as db, db.transaction(force_rollback=True):
            db.execute('SELECT pg_advisory_xact_lock(901095)')
            db.execute('DELETE FROM current_sgo_history')
            with db.cursor() as cursor:
                cursor.executemany("""INSERT INTO current_sgo_history
                    (kind,identity,revision,event_id,archived_at,payload_bytes,facts)
                    VALUES('reference',%s,'old','bounded-rotation','2026-11-10T20:00:00Z',%s,%s)""",
                    [(f'old-{n:04d}',size,Jsonb(facts))for n in range(1200)])
            with patch('app.storage.sportsgameodds_reference.HISTORY_BYTES',1200*size):
                self.assertEqual(archive_revisions(db,'reference',[incoming]),1)
            remaining=[r['identity']for r in db.execute("SELECT identity FROM current_sgo_history WHERE identity<>'new' ORDER BY identity")]
            self.assertEqual(remaining,[f'old-{n:04d}'for n in range(expected,1200)])
            self.assertLessEqual(db.execute('SELECT sum(payload_bytes) n FROM current_sgo_history').fetchone()['n'],1200*size)

    async def test_bounded_history_records_revisions_and_prunes_only_history(self):
        import json
        from datetime import datetime, timedelta, timezone
        from app.collection.sportsgameodds_adapter import parse_page
        from app.storage.sportsgameodds_reference import prune_history, read_history, prune, prune_frames
        first = response()
        old = parse(first)
        second = deepcopy(first)
        book = second['data'][0]['odds']['points-home-game-sp-home']['byBookmaker']['book']
        book.update(odds='+100', lastUpdatedAt='2026-11-10T20:00:30Z')
        new = parse_page(json.dumps(second).encode(), '2026-11-10T20:01:00Z')
        with self.connect() as db:
            upsert_rows(db, prepare_page(old))
            upsert_frames(db, prepare_frames(old, prepare_page(old)))
            with db.transaction():
                upsert_rows(db, prepare_page(new))
                upsert_frames(db, prepare_frames(new, prepare_page(new)))
            history = db.execute('SELECT kind,facts FROM current_sgo_history ORDER BY kind').fetchall()
            self.assertEqual([r['kind'] for r in history], ['frame', 'reference'])
            self.assertEqual(history[1]['facts']['price_american'], '-110')
            self.assertEqual(db.execute('SELECT facts FROM current_sgo_reference').fetchone()['facts']['price_american'], '+100')
            # An undersized budget omits history without damaging the current row.
            book.update(odds='+105', lastUpdatedAt='2026-11-10T20:01:30Z')
            third = parse_page(json.dumps(second).encode(), '2026-11-10T20:02:00Z')
            with patch('app.storage.sportsgameodds_reference.HISTORY_BYTES', 0):
                upsert_rows(db, prepare_page(third))
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_history').fetchone()['n'], 2)
            self.assertEqual(db.execute('SELECT facts FROM current_sgo_reference').fetchone()['facts']['price_american'], '+105')
        with self.connect() as db:
            self.assertEqual(len(read_history(db, 'event')), 2)
            state = db.execute('SELECT * FROM current_sgo_history_state').fetchone()
            self.assertEqual(state['recorded'], 2)
            self.assertEqual(state['skipped_capacity'], 1)
            future = datetime.now(timezone.utc) + timedelta(days=8)
            self.assertEqual(prune_history(db, at=future.isoformat()), 2)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_reference').fetchone()['n'], 1)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_event_frame').fetchone()['n'], 1)
            later = (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()
            self.assertEqual(prune(db, at=later), 1)
            self.assertEqual(prune_frames(db, at=later), 1)
            self.assertEqual(len(read_history(db, 'event')), 2)
            db.execute('DELETE FROM current_sgo_history')

    async def test_restart_restores_live_frame_without_a_projected_event(self):
        from datetime import datetime, timezone
        from app.collection.sportsgameodds_worker import retained_schedule
        raw = response()
        raw['data'][0]['eventID'] = 'recovery-event'
        raw['data'][0]['status'].update(started=True, live=True)
        page = parse(raw)
        with self.connect() as db:
            upsert_frames(db, prepare_frames(page, prepare_page(page)))
            self.assertEqual(db.execute("SELECT count(*) n FROM current_event WHERE provider='sportsgameodds'").fetchone()['n'], 0)
        with patch('app.storage.store.connect', side_effect=self.connect):
            at = datetime(2026, 11, 10, 20, tzinfo=timezone.utc)
            pregame, _ = retained_schedule(['NBA'], at, 10)
            events, truncated = retained_schedule(['NBA'], at, 10, include_live=True)
        self.assertNotIn('recovery-event', pregame)
        self.assertFalse(truncated)
        self.assertEqual(events['recovery-event']['phase'], 'live')
        self.assertEqual(events['recovery-event']['received_at'], page.events[0]['received_at'])

    async def test_restart_limits_only_eligible_retained_events(self):
        from datetime import datetime, timezone
        from app.collection.sportsgameodds_worker import retained_schedule

        at = datetime(2027, 1, 4, 20, tzinfo=timezone.utc)
        template, = response()['data']
        events = []
        for event_id, minute, state in (
                ('kickoff', 0, {}), ('cancelled', 1, {'cancelled': True}),
                ('started', 2, {'started': True}), ('next', 3, {}),
                ('later', 4, {}), ('completed', 5, {'completed': True})):
            status = dict(template['status'], startsAt=f'2027-01-04T20:{minute:02}:00Z') | state
            events.append(dict(template, eventID=event_id, leagueID='NHL', odds={}, status=status))
        page = parse_page(json.dumps(dict(success=True, data=events)).encode(), at.isoformat())
        def cleanup():
            with self.connect() as db:
                db.execute("DELETE FROM sgo_event_evidence WHERE kind='frame' AND event_id=ANY(%s)",
                           ([event['eventID'] for event in events],))
        self.addCleanup(cleanup)
        with self.connect() as db:
            upsert_frames(db, prepare_frames(page, []))
        with patch('app.storage.store.connect', side_effect=self.connect):
            pregame, truncated = retained_schedule(['NHL'], at, 2)
            self.assertEqual(list(pregame), ['next', 'later'])
            self.assertFalse(truncated)
            pregame, truncated = retained_schedule(['NHL'], at, 1)
            self.assertEqual(list(pregame), ['next'])
            self.assertTrue(truncated)
            live, truncated = retained_schedule(['NHL'], at, 4, include_live=True)
            self.assertEqual(list(live), ['kickoff', 'started', 'next', 'later'])
            self.assertFalse(truncated)

    async def test_old_provider_hold_does_not_mark_sgo_venues_held(self):
        from app.storage import ordinary_publication as live
        from app.collection.runtime_status import read_runtime
        with self.connect() as db:
            owner = read_runtime(db)
            owner['config']['aggregate_provider'] = 'sportsgameodds'
            owner['paused_sources'] = ['the_odds_api']
            owner.setdefault('status', {})['quota'] = {'blocking_reason': 'recovery_credential_changed'}
            with patch('app.collection.runtime_status.read_runtime', return_value=owner):
                _, states = live.authority(db)
            self.assertEqual(states['novig']['state'], 'available')
            self.assertNotEqual(states['novig'].get('reason_code'), 'recovery_credential_changed')
            self.assertNotEqual(states['pinnacle'].get('reason_code'), 'native_available')

    async def test_page_atomicity_unchanged_rows_and_controls(self):
        raw = response()
        book = raw['data'][0]['odds']['points-home-game-sp-home']['byBookmaker'].pop('book')
        raw['data'][0]['odds']['points-home-game-sp-home']['byBookmaker']['novig'] = book
        raw['data'].append(dict(deepcopy(raw['data'][0]), eventID='college-event', leagueID='NCAAB'))
        page = parse(raw)
        records, _ = current_rows(page, page.receipt_sha256)
        references = prepare_page(page)
        self.assertTrue(records and references)
        row = dict(type='current_aggregate_records',source='sportsgameodds',sport='NBA',
                   records=records,sgo_reference_rows=references,sgo_event_frames=prepare_frames(page,references),receipt_sha256=page.receipt_sha256,
                   event_scopes={event['event_id']:event['league'] for event in page.events},
                   complete_venues=[],received_at=page.events[0]['received_at'])
        sink = DatabaseIngressSink(SimpleNamespace(provider=self.service), DEFAULT)
        from app.collection.current_database import validate_sgo_page
        validate_sgo_page(row)
        missing_reference = dict(row)
        del missing_reference['sgo_reference_rows']
        with patch('app.collection.current_database.connect', side_effect=AssertionError('invalid page opened SQL')):
            with self.assertRaisesRegex(ValueError, 'sgo_page_identity_mismatch'):
                sink.prepare(missing_reference, self.service.states, Event())
            with self.assertRaisesRegex(ValueError, 'sgo_reference_scope_invalid'):
                sink.prepare(dict(row, raw_payload=[]), self.service.states, Event())
        mismatch = deepcopy(row)
        mismatch['sgo_reference_rows'][0]['facts']['receipt_sha256'] = 'f'*64
        with self.assertRaises(ValueError): validate_sgo_page(mismatch)
        mismatch = deepcopy(row)
        mismatch['sgo_reference_rows'][0]['facts']['received_at'] = '2026-11-10T21:00:00Z'
        with self.assertRaises(ValueError): validate_sgo_page(mismatch)
        mismatch = deepcopy(row)
        mismatch['sgo_event_frames'][0]['facts']['members'] = []
        with self.assertRaises(ValueError): validate_sgo_page(mismatch)
        mismatch = deepcopy(row)
        mismatch['records'][0]['quote']['source']['native_event_id'] = 'other'
        with self.assertRaises(ValueError): validate_sgo_page(mismatch)
        mismatch = deepcopy(row)
        mismatch['records'][0]['quote']['original']['value'] = '+125'
        with self.assertRaisesRegex(ValueError, 'sgo_offer_source_quote_mismatch'): validate_sgo_page(mismatch)
        with self.connect() as db:
            db.execute('CREATE TABLE protected_test_hold (amount integer)')
            db.execute('INSERT INTO protected_test_hold VALUES (34)')
            before = db.execute('SELECT count(*) n FROM current_offer').fetchone()['n']
        def fail_after_frame(db, frames):
            upsert_frames(db, frames)
            raise RuntimeError('fixture failure after frame insert')
        with patch('app.collection.current_database.connect',side_effect=self.connect), \
             patch('app.collection.current_database.utc',return_value=AT), \
             patch('app.storage.sportsgameodds_reference.upsert_frames',side_effect=fail_after_frame):
            with self.assertRaises(RuntimeError):
                sink.prepare(row,self.service.states,Event())
        self.assertNotIn('recent_sgo_preparations', sink.metrics)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_reference').fetchone()['n'], 0)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_event_frame').fetchone()['n'], 0)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_delivery_clock').fetchone()['n'], 0)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_offer').fetchone()['n'], before)
        with patch('app.collection.current_database.connect',side_effect=self.connect), \
             patch('app.collection.current_database.utc',return_value=AT):
            sink.prepare(row,self.service.states,Event())
            sample, = sink.metrics['recent_sgo_preparations']
            self.assertEqual(sample['received_at'], row['received_at'])
            self.assertEqual(sample['leagues'], ['NBA', 'NCAAB'])
            self.assertEqual(sample['reference_rows'], len(references))
            self.assertEqual(sample['event_frames'], 2)
            for key in ('sgo_reference', 'sgo_frames', 'sql_admission'):
                self.assertGreaterEqual(sample['timings'][key], 0)
            with self.connect() as db:
                first = db.execute('SELECT id,xmin::text AS version FROM sgo_quote_revision ORDER BY id,revision').fetchall()
                self.assertEqual(db.execute("SELECT state FROM current_source_status WHERE venue='sportsgameodds'").fetchone()['state']['state'], 'available')
                native_before = db.execute("SELECT venue,state FROM current_source_status WHERE venue IN ('kalshi','polymarket_us') ORDER BY venue").fetchall()
                offers = db.execute('SELECT count(*) n FROM current_offer').fetchone()['n']
                self.assertGreater(offers,before)
                self.assertEqual(len(first),len(references))
                self.assertEqual(db.execute('SELECT count(*) n FROM current_sgo_event_frame').fetchone()['n'],2)
                clocks = db.execute('SELECT * FROM current_sgo_delivery_clock ORDER BY league').fetchall()
                self.assertEqual([clock['league'] for clock in clocks], ['NBA', 'NCAAB'])
                admitted_at = clocks[0]['admitted_at']
                self.assertIsNotNone(admitted_at)
                self.assertEqual(clocks[1]['admitted_at'], admitted_at)
                self.assertTrue(all(clock['first_publication_write_at'] is None for clock in clocks))
                from app.storage.delivery_clocks import captured, published, receipts
                offers_at = [dict(league=r['event']['competition'], source=r['quote']['source'], times=r['quote']['times']) for r in records]
                captured(db, offers_at, admitted_at)
                published(db, receipts(offers_at))
                for delivered in db.execute('SELECT * FROM current_sgo_delivery_clock').fetchall():
                    self.assertEqual(delivered['first_recorded_capture_at'], admitted_at)
                    self.assertGreaterEqual(delivered['first_publication_write_at'], admitted_at)
            sink.prepare(row,self.service.states,Event())
            with self.connect() as db:
                self.assertEqual(db.execute('SELECT id,xmin::text AS version FROM sgo_quote_revision ORDER BY id,revision').fetchall(),first)
                self.assertEqual(db.execute('SELECT count(*) n FROM current_offer').fetchone()['n'],offers)
                links = db.execute('''SELECT o.price_value,o.facts#>>'{original,value}' AS inline_value,
                    o.sgo_quote_id,q.facts->>'price_american' AS source_price
                    FROM current_offer_storage o JOIN sgo_quote_revision q
                    ON (q.id,q.revision)=(o.sgo_quote_id,o.sgo_quote_revision) ORDER BY q.id''').fetchall()
                self.assertEqual(len(links), len(records))
                self.assertTrue(all(r['price_value'] is None and r['inline_value'] is None for r in links))
                self.assertEqual({r['source_price'] for r in links}, {'-110'})
                self.assertEqual(db.execute('SELECT amount FROM protected_test_hold').fetchone()['amount'],34)
                db.execute('UPDATE data_runtime SET paused_sources=%s WHERE singleton=true',(Jsonb(['sportsgameodds']),))
            with self.assertRaises(asyncio.CancelledError):
                sink.prepare(row,self.service.states,Event())
            stopped=dict(type='sgo_status',source='sportsgameodds',state='stopped',reason_code='sgo_paused',reason='Paused')
            sink.prepare(stopped,self.service.states,Event())
            self.assertEqual(len(sink.metrics['recent_sgo_preparations']), 2)
            with self.connect() as db:
                self.assertEqual(db.execute("SELECT state FROM current_source_status WHERE venue='sportsgameodds'").fetchone()['state']['state'], 'stopped')
                self.assertEqual(db.execute("SELECT venue,state FROM current_source_status WHERE venue IN ('kalshi','polymarket_us') ORDER BY venue").fetchall(),native_before)
                db.execute('UPDATE data_runtime SET paused_sources=%s,global_stopped=true WHERE singleton=true',(Jsonb([]),))
            with self.assertRaises(asyncio.CancelledError):
                sink.prepare(row,self.service.states,Event())
            revoked=Event();revoked.set()
            with self.assertRaises(asyncio.CancelledError):
                sink.prepare(row,self.service.states,revoked)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT id,xmin::text AS version FROM sgo_quote_revision ORDER BY id,revision').fetchall(),first)
            self.assertEqual(db.execute('SELECT amount FROM protected_test_hold').fetchone()['amount'],34)

    async def test_offer_and_reference_can_keep_different_revisions_without_duplicating_price(self):
        raw = response()
        event_id = 'divergent-source-offer'
        raw['data'][0]['eventID'] = event_id
        odd = raw['data'][0]['odds']['points-home-game-sp-home']
        book = odd['byBookmaker'].pop('book')
        odd['byBookmaker']['novig'] = book
        sink = DatabaseIngressSink(SimpleNamespace(provider=self.service), DEFAULT)

        def admit(received):
            page = parse_page(json.dumps(raw).encode(), received)
            records, _ = current_rows(page, page.receipt_sha256)
            references = prepare_page(page)
            sink.prepare(dict(type='current_aggregate_records',source='sportsgameodds',sport='NBA',
                records=records,sgo_reference_rows=references,sgo_event_frames=prepare_frames(page,references),
                receipt_sha256=page.receipt_sha256,event_scopes={event_id:'NBA'},complete_venues=[],received_at=received),
                self.service.states, Event())
            return page.receipt_sha256

        with self.connect() as db, db.transaction(force_rollback=True):
            # Run both pages through the real nested ingress transaction and
            # roll the fixture back as a unit, including delivery counters.
            from contextlib import nullcontext
            with (
                patch('app.collection.current_database.connect', side_effect=lambda: nullcontext(db)),
                patch('app.collection.current_database.utc', return_value=AT),
            ):
                reference_receipt = admit('2026-11-10T20:00:00Z')
                # The offer owner accepts a later receipt with the same known source
                # time. The reference owner conservatively keeps the earlier value.
                book['odds'] = '+105'
                offer_receipt = admit('2026-11-10T20:01:00Z')
            state = db.execute('''SELECT o.price_value,q.price_value AS displayed,
                q.facts#>>'{provenance,sha256}' AS offer_receipt,
                r.facts->>'price_american' AS reference,r.facts->>'receipt_sha256' AS reference_receipt
                FROM current_offer_storage o JOIN current_offer q USING (contract_id)
                JOIN current_sgo_reference r ON r.id=o.sgo_quote_id WHERE r.event_id=%s''',(event_id,)).fetchone()
            self.assertEqual(state,dict(price_value=None,displayed='+105',offer_receipt=offer_receipt,
                                        reference='-110',reference_receipt=reference_receipt))
            from app.storage.sportsgameodds_reference import prune
            prune(db, at='2026-11-11T12:00:00Z')
            self.assertEqual(db.execute("SELECT count(*) n FROM sgo_quote_revision WHERE NOT is_current AND event_id=%s",
                                        (event_id,)).fetchone()['n'], 1)

    async def test_sql_timeout_after_frame_retries_the_settled_page_without_another_request(self):
        from datetime import timedelta
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import AsyncMock

        from app.collection.current_ingress import Ingress
        from app.collection.sportsgameodds_collector import GuardedPageCollector
        from app.collection.sportsgameodds_ledger import ObjectLedger
        from app.collection.sportsgameodds_transport import PageResponse
        from app.collection.sportsgameodds_worker import SportsGameOddsWorker
        from app.storage.store import stamp
        from tests.test_sportsgameodds_adapter import AT as received_at

        self.at = stamp(received_at)
        raw = response()
        event, = raw['data']
        event_id = event['eventID'] = 'retried-sgo-page'
        odd, = event['odds'].values()
        odd['byBookmaker']['novig'] = odd['byBookmaker'].pop('book')
        body = json.dumps(raw).encode()
        socket = SimpleNamespace(fetch=AsyncMock(return_value=PageResponse(200, body, received_at, None)))
        service = self.service
        service.config.update(aggregate_provider='sportsgameodds', sports=['NBA'])
        service.database_mode = True
        service.globally_stopped = False
        service.paused_sources = set()
        service.sink = DatabaseIngressSink(SimpleNamespace(provider=service), service.config)
        service.sink.finish = lambda prepared, states: dict(current_rows_changed=prepared[2])
        service.ingress = Ingress(service)
        self.state.write(service)
        frames_attempted = []

        def timeout_after_first_frame(db, frames):
            frames_attempted.append(frames)
            if len(frames_attempted) == 2:
                with self.connect() as observer:
                    self.assertIsNone(observer.execute(
                        'SELECT event_id FROM current_sgo_event_frame WHERE event_id=%s', (event_id,)).fetchone())
                    self.assertIsNone(observer.execute(
                        'SELECT id FROM sgo_quote_revision WHERE event_id=%s', (event_id,)).fetchone())
            result = upsert_frames(db, frames)
            if len(frames_attempted) == 1:
                # Force a real PostgreSQL statement timeout after both inputs
                # have been staged in the production admission transaction.
                db.execute("SET LOCAL statement_timeout='1ms'")
                db.execute('SELECT pg_sleep(0.02)')
            return result

        with TemporaryDirectory(prefix='predict-sgo-ledger-') as folder:
            ledger = ObjectLedger(Path(folder) / 'ledger.sqlite')
            reset = self.at + timedelta(days=1)
            ledger.create_window('fixture', limit=100, initial_used=4, reserve=10,
                                 reset_at=reset, requests_per_minute=10)
            usage = AsyncMock(return_value=dict(used=4, limit=100, reset_at=reset,
                                               requests_per_minute=10, at=self.at))
            worker = SportsGameOddsWorker(service, transport=socket, now=lambda: self.at)
            worker.state = AsyncMock()
            collector = GuardedPageCollector(ledger, 'fixture', socket, controls=worker.controls, account_usage=usage)
            worker.collector = SimpleNamespace(fetch=lambda params, key: collector.fetch(params, key, now=self.at))
            params = worker.params(league='NBA', starts_after=received_at)
            with patch('app.collection.current_database.connect', side_effect=self.connect), \
                    patch('app.collection.current_database.utc', return_value=received_at), \
                    patch('app.storage.sportsgameodds_reference.upsert_frames', side_effect=timeout_after_first_frame):
                admitted = await worker._fetch(params)
            socket.fetch.assert_awaited_once()
            usage.assert_awaited_once()
            account = ledger.status('fixture')
            self.assertEqual((account['charged'], account['held'], account['interrupted']), (1, 0, 0))

        self.assertEqual(len(frames_attempted), 2)
        self.assertEqual(frames_attempted[0], frames_attempted[1])
        self.assertEqual(service.sink.metrics['transaction_retries'], 1)
        self.assertEqual(service.sink.metrics['rejected_observations'], 0)
        self.assertEqual(worker.events[event_id]['received_at'], received_at)
        with self.connect() as db:
            offer = db.execute('''SELECT o.source_at,o.received_at,q.facts->>'receipt_sha256' AS digest
                FROM current_offer_storage o JOIN sgo_quote_revision q ON (q.id,q.revision)=(o.sgo_quote_id,o.sgo_quote_revision)
                WHERE q.event_id=%s''', (event_id,)).fetchone()
            self.assertEqual(stamp(offer['source_at']), stamp(odd['byBookmaker']['novig']['lastUpdatedAt']))
            self.assertEqual(stamp(offer['received_at']), stamp(received_at))
            self.assertEqual(offer['digest'], admitted.receipt_sha256)

    async def test_repeated_exact_closure_orders_offers_after_newer_partial_frame_and_replay(self):
        from datetime import timedelta

        from app.storage.store import exact_time, stamp
        from tests.test_sportsgameodds_adapter import AT as receipt_at

        self.at = stamp(receipt_at)
        raw = response()
        event, = raw['data']
        event_id = event['eventID'] = 'repeated-sgo-closure'
        odd, = event['odds'].values()
        open_book = odd['byBookmaker'].pop('book')
        closed_book = {key: value for key, value in open_book.items() if key != 'odds'}
        closed_book['available'] = False
        self.service.config.update(aggregate_provider='sportsgameodds', sports=['NBA'])
        self.state.write(self.service)
        sink = DatabaseIngressSink(SimpleNamespace(provider=self.service), self.service.config)

        def receipt(seconds):
            return (stamp(receipt_at) + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')

        def admit(book, received):
            odd['byBookmaker'] = {'novig': book} if book is not None else {}
            page = parse_page(json.dumps(raw).encode(), received)
            records, _ = current_rows(page, page.receipt_sha256)
            refs = prepare_page(page)
            with patch('app.collection.current_database.connect', side_effect=self.connect), \
                    patch('app.collection.current_database.utc', return_value=self.at.isoformat()):
                sink.prepare(dict(type='current_aggregate_records', source='sportsgameodds', sport='NBA',
                    records=records, sgo_reference_rows=refs, sgo_event_frames=prepare_frames(page, refs),
                    receipt_sha256=page.receipt_sha256, event_scopes={event_id:'NBA'},
                    complete_venues=[], received_at=received), self.service.states, Event())
            with self.connect() as db:
                quote = db.execute('''SELECT o.facts->>'state' state,o.source_at,o.received_at,q.facts->>'price_american' price
                    FROM current_offer_storage o JOIN sgo_quote_revision q ON (q.id,q.revision)=(o.sgo_quote_id,o.sgo_quote_revision)
                    WHERE q.event_id=%s''', (event_id,)).fetchone()
                reference = db.execute('''SELECT id,revision,source_order,received_order,facts,closure_received_order
                    FROM sgo_quote_revision WHERE event_id=%s AND is_current''', (event_id,)).fetchone()
            return quote, reference

        self.assertEqual(admit(open_book, receipt(0))[0]['state'], 'available')
        closed, original = admit(closed_book, receipt(1))
        self.assertEqual(closed['state'], 'unavailable')
        self.assertIsNone(original['closure_received_order'])
        reopened, _ = admit(open_book, receipt(2))
        self.assertEqual(reopened['state'], 'available')
        closed, renewed = admit(closed_book, receipt(3))
        self.assertEqual(closed, dict(reopened, state='unavailable'))
        self.assertEqual(renewed, dict(original, closure_received_order=exact_time(receipt(3))))
        # Frame membership may rotate even while the exact quote's last
        # closure remains authoritative over an older, delayed replay.
        admit(None, receipt(4))
        with self.connect() as db:
            frame = db.execute('SELECT facts FROM current_sgo_event_frame WHERE event_id=%s', (event_id,)).fetchone()['facts']
            self.assertEqual(frame['members'], [])
            self.assertEqual(frame['received_at'], receipt(4))
        self.assertEqual(admit(open_book, receipt(2)), (closed, renewed))
        self.assertEqual(admit(closed_book, receipt(1)), (closed, renewed))
        latest, ref = admit(dict(open_book, lastUpdatedAt=receipt(5)), receipt(5))
        self.assertEqual(latest['state'], 'available')
        self.assertEqual(latest['source_at'], receipt(5))
        self.assertIsNone(ref['closure_received_order'])

    async def test_switch_marks_old_aggregate_historical_but_preserves_native(self):
        from copy import deepcopy
        from app.storage import ordinary_publication as live
        from app.collection.runtime_status import read_runtime
        with self.connect() as db, \
             patch('app.collection.current_policy.load', return_value=DEFAULT), \
             patch('app.storage.ordinary_publication.utc', return_value=self.at.isoformat()), \
             patch('app.storage.comparison_snapshot.utc', return_value=self.at.isoformat()):
            publication = live.turn(db)
            self.assertTrue(publication['published'], publication)
            from app.storage import comparison_snapshot as snapshots
            head = live.status(db)
            result = snapshots.unpack(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s', (head['result_id'],)).fetchone()['result'],db=db)
            current = live.dependencies(db)
            owner = read_runtime(db)
            states = {v: {'state':'available'} for v in ('novig','prophetx','kalshi','polymarket_us','pinnacle','sportsgameodds')}
            policy = live.policy_identity(live.committed_aggregate_provider(db))
            old = live.project(result,current,owner,states,at=self.at,policy=policy,epoch=result['publication']['epoch'])
            changed = deepcopy(owner)
            changed['config']['aggregate_provider'] = 'sportsgameodds'
            switched = live.project(result,current,changed,states,at=self.at,policy=policy,epoch=result['publication']['epoch'])
            before = {r['id']:r for r in old['rows']}
            aggregate = [r for r in switched['rows'] if r.get('source',{}).get('provider') == 'the_odds_api']
            native = [r for r in switched['rows'] if r.get('source',{}).get('provider') in ('kalshi','polymarket_us')]
            self.assertTrue(aggregate and native)
            self.assertTrue(all(not r['price_current'] and 'aggregate_provider_replaced' in r['price_reasons'] for r in aggregate))
            self.assertTrue(all(r['price_current'] == before[r['id']]['price_current'] for r in native))
            self.assertTrue(all(r['original'] == before[r['id']]['original'] and r['current_authority']['references'] == before[r['id']]['current_authority']['references'] for r in switched['rows']))
            from app.storage import latest_board, raw_prices
            context = latest_board.read_context(db, at=self.at.isoformat(), owner=changed)
            latest_records = [r for group in context.prepared['groups'] for r in group]
            providers = {r['quote']['source']['provider'] for r in latest_records}
            self.assertNotIn('the_odds_api', providers)
            self.assertTrue({'kalshi','polymarket_us'} & providers)
            self.assertEqual(raw_prices.status({'kind':'featured','venue':'novig'}, changed), 'last_known')
            self.assertTrue(any(r['quote']['source']['provider']=='the_odds_api' for r in self.records))
            # Native offers remain available; a legacy reference may no longer
            # make a financial result current after changing providers.
            for row in native:
                refs = row['current_authority']['references']
                if refs and any(r.get('provider','the_odds_api') == 'the_odds_api' for r in refs):
                    self.assertFalse((row.get('reference_calculation') or {}).get('available',False))
