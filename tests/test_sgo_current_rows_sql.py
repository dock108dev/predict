"""SGO retirement scopes cannot erase another provider's observations."""
from unittest import skipUnless
from copy import deepcopy

from app.collection.current_aggregate_admission import admit
from app.collection.sportsgameodds_current_rows import current_rows
from app.storage.current_rows import CurrentRowStore
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_current_aggregate import body
from tests.test_sportsgameodds_adapter import AT, parse, response


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class SGOScopeSQL(LatestBoardFixture):
    async def test_retirement_is_provider_event_and_venue_scoped(self):
        data = response()
        event = data['data'][0]
        event['eventID'] = 'CONTROLLED-event'
        event['leagueID'] = 'MLB'
        home = event['odds']['points-home-game-sp-home']
        home['byBookmaker'] = {'novig': home['byBookmaker']['book']}
        away = dict(home, oddID='points-away-game-sp-away', opposingOddID=home['oddID'],
                    statEntityID='away', sideID='away',
                    byBookmaker={'novig': dict(home['byBookmaker']['novig'], spread='1.5')})
        event['odds'][away['oddID']] = away
        other = deepcopy(event)
        other['eventID'] = 'OTHER-event'
        data['data'].append(other)
        page = parse(data)
        sgo, _ = current_rows(page, page.receipt_sha256)
        legacy = admit(body(books=('novig',)), 'MLB', '2026-10-03T00:00:00Z')
        with self.connect() as db:
            store = CurrentRowStore(db)
            store.upsert_records([*sgo, *legacy], now='2026-10-03T00:00:00Z')
            scope = dict(venue='novig', competition='MLB', native_event_id='CONTROLLED-event',
                         received_at=AT, aggregate_route='sgo_event')
            store.upsert_records([], now='2026-10-03T00:00:00Z', authoritative=True, scopes=[scope])
            counts = db.execute("""SELECT e.provider,count(*) n FROM current_contract c
                JOIN current_event e ON e.id=c.event_id WHERE c.venue='novig'
                AND e.native_event_id='CONTROLLED-event' GROUP BY e.provider""").fetchall()
            assert {r['provider']: r['n'] for r in counts} == {'the_odds_api': len(legacy)}
            assert db.execute("""SELECT count(*) n FROM current_contract c JOIN current_event e ON e.id=c.event_id
                WHERE e.provider='sportsgameodds' AND e.native_event_id='OTHER-event'""").fetchone()['n'] == 2
            with self.assertRaisesRegex(ValueError, 'aggregate_refresh_route'):
                store.upsert_records([], now='2026-10-03T00:00:00Z', authoritative=True,
                                     scopes=[dict(venue='novig',competition='MLB',received_at=AT,aggregate_route='sgo_event')])

