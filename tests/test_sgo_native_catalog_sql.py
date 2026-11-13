"""Official Novig authority stays separate from current offers and SGO spend."""
from unittest import skipUnless

from psycopg.types.json import Jsonb

from app.storage import sgo_native_catalog as catalog
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_sgo_native_binding import AT, EVENT, HOME, SGO, START, fixture, witness


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class SGONativeCatalogSQL(LatestBoardFixture):
    async def test_targets_exact_members_and_expires_finance_dependency(self):
        row, event, market = fixture()
        facts = dict(event_context=dict(phase='pregame',bookmaker_event_links=dict(novig=dict(
            host='novig.com',path='/event-markets/'+EVENT+'/sportsgameodds'))), starts_at=START,
            members=[['quote','observed']],receipt_sha256='2'*64)
        anchor = dict(odd_id='points-home-game-sp-home',opposing_odd_id='points-away-game-sp-away',
                      side='home',line='1.5',market='spread',period='game')
        quote = dict(anchor,available=True,bookmaker_market_link=row['comparison_source_metadata']['bookmaker_market_link'])
        with self.connect() as db:
            db.execute("INSERT INTO current_event VALUES ('canonical','sportsgameodds',%s,'NHL',%s,0,'{}','event')", (SGO,START))
            db.execute('INSERT INTO current_sgo_event_frame VALUES (%s,0,%s,0,%s)', (SGO,START,Jsonb(facts)))
            db.execute("INSERT INTO current_sgo_reference VALUES ('quote',%s,'novig',0,0,%s,'replaced',%s)",
                       (SGO,START,Jsonb(quote)))
            assert catalog.targets(db,at=AT) == []
            db.execute("UPDATE current_sgo_reference SET revision='observed'")
            assert catalog.targets(db,at=AT) == [(SGO,EVENT,{HOME:[anchor]},'2'*64)]
            assert catalog.targets(db,at=AT,exclude=(SGO,)) == []

            proof = witness(event,market)
            catalog.write(db,SGO,proof)
            saved = catalog.read(db,[SGO])[SGO]
            assert saved['markets'] == proof['markets']
            assert catalog.targets(db,at=AT) == []
            deps = catalog.dependencies(db,['canonical'],at=AT)
            revision = saved['revision']
            assert deps == [dict(id=catalog.dependency_id(SGO),event_id='canonical',price=revision,
                                 contract=revision,event=revision,receipt=revision)]
            assert catalog.dependencies(db,['other'],at=AT) == []
            assert catalog.dependencies(db,at=AT) == deps
            assert catalog.dependencies(db,at='2026-11-12T17:09:00+00:00') == []
            catalog.write(db,SGO,witness(event,market,'2026-11-12T16:53:00+00:00'))
            assert catalog.read(db,[SGO])[SGO] == saved
