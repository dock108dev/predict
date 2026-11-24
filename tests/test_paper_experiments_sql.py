"""Disposable SQL proving newest failed pull cannot inherit older positives."""
from unittest import skipUnless

from app.research.paper_latest import latest
from app.storage import acquisition_snapshot as acquisition
from app.storage.store import stamp
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests import test_market_board_sql as fixtures
from tests.test_paper_experiments import priced


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class PaperSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        with self.connect() as db:
            db.execute("TRUNCATE public.market_pull CASCADE")

    def start(self,db):
        return acquisition.start(db,fixtures.SCOPE,at=stamp(fixtures.AT),
            event=dict(title="Away at Home",league="NCAAB",starts_at="2026-11-23T01:00:00Z"))

    async def test_successful_latest_pull_and_newer_failure_never_fall_back(self):
        with self.connect() as db:
            old=self.start(db)
            fixtures.MarketBoardSQL.publish(self,db,old,priced(),priced(venue="polymarket_us"),priced(ev="-.01",line="-5"))
            first=latest(db,"2026-11-22")
            self.assertEqual(first["pull"]["pull_id"],old)
            self.assertEqual(len(first["rows"]),2)
            new=self.start(db)
            acquisition.finish(db,new,"failed",details=dict(reason="authored_failure"))
            second=latest(db,"2026-11-22")
            self.assertEqual(second["pull"]["pull_id"],new)
            self.assertEqual(second["rows"],[])
            self.assertIsNone(second["preview_portfolios"])
            self.assertIn("incomplete",second["incomplete_reason"])
            self.assertIsNone(latest(db,"2026-11-23")["pull"])
