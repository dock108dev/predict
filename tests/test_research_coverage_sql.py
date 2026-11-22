"""Honest retained coverage through the same read-only operator query."""
from copy import deepcopy
from types import SimpleNamespace

from app.collection.current_policy import DEFAULT
from app.collection.runtime_status import RuntimeState
from app.storage.research_coverage import report
from tests.latest_board_fixture import LatestBoardFixture


class ResearchCoverageSQL(LatestBoardFixture):
    async def test_same_source_event_across_retained_representations_counts_once(self):
        with self.connect()as db:
            db.execute('TRUNCATE current_sgo_history')
            db.execute("DELETE FROM sgo_event_evidence WHERE kind='frame'")
            db.execute("""INSERT INTO current_sgo_history VALUES
                ('reference','coverage-one','revision-one','coverage-event',now(),80,jsonb_build_object('received_at',%s::text)),
                ('frame','coverage-one','revision-one','coverage-event',now(),80,jsonb_build_object('received_at',%s::text))""",
                (self.at.isoformat(),self.at.isoformat()))
            db.execute("""INSERT INTO sgo_event_evidence(kind,event_id,received_order,expires_at,payload_bytes,facts)
                VALUES('frame','coverage-event',extract(epoch FROM %s::timestamptz),now()+interval '1 day',80,'{}')""",(self.at,))
            with db.transaction():
                db.execute('SET TRANSACTION READ ONLY')
                value=report(db,self.at)
            source=next(r for r in value['sources']if r['provider']=='sportsgameodds')
            self.assertEqual(source['received']['records'],3)
            self.assertEqual(source['received']['events'],1)
            self.assertEqual(source['received']['count_unit'],'retained_representation_rows')

    async def test_liveness_does_not_renew_receipts_or_claim_unsupported_archive(self):
        service=SimpleNamespace(runtime_id='coverage-fixture',config=deepcopy(DEFAULT),
            states={},dispatch=True,status=lambda:dict(sources=[],issues=[],exclusions=[]))
        RuntimeState(self.connect).write(service)
        with self.connect() as db:
            before=db.execute('SELECT source,max(received_at) last FROM current_acquisition_image_parts GROUP BY source ORDER BY source').fetchall()
            now=self.at
            with db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                value=report(db,now)
            self.assertTrue(value['runtime']['healthy'])
            self.assertEqual(value['provider_requests'],0)
            sources={r['provider']:r for r in value['sources']}
            self.assertTrue(sources['kalshi']['archive_supported'])
            for provider in ('novig','oddslink_public_board','the_odds_api'):
                self.assertFalse(sources[provider]['archive_supported'])
                self.assertIsNone(sources[provider]['archive'])
                self.assertEqual(sources[provider]['archive_reason'],'unsupported_archive_route')
            for row in before:
                source=sources[row['source']]
                self.assertGreaterEqual(source['receipt_age_seconds'],0)
                self.assertLessEqual(source['received']['last_received_at'],now)
                self.assertNotEqual(source['received']['last_received_at'].isoformat(),value['runtime']['heartbeat_at'])
            self.assertEqual(before,db.execute('SELECT source,max(received_at) last FROM current_acquisition_image_parts GROUP BY source ORDER BY source').fetchall())
            # No backlog and a healthy runtime still establish neither a
            # historical first receipt nor a complete history.
            self.assertTrue(all(r['archive_first_received_at'] is None for r in value['sources']))
            self.assertIn('Recorded archive skips do not count observations missed during a collection outage.',value['limitations'])

    async def test_recorded_archive_gaps_and_current_calc_counts_remain_distinct(self):
        with self.connect()as db:
            db.execute("""INSERT INTO odds_archive_feed_status(feed,verified,skipped,first_gap_at,last_gap_at,gap_reason)
                VALUES('sportsgameodds',12,3,%s,%s,'staging_or_disk_capacity')
                ON CONFLICT(feed)DO UPDATE SET verified=12,skipped=3,first_gap_at=excluded.first_gap_at,
                last_gap_at=excluded.last_gap_at,gap_reason=excluded.gap_reason""",(self.at,self.at))
            with db.transaction():
                db.execute('SET TRANSACTION READ ONLY')
                value=report(db)
            source=next(r for r in value['sources']if r['provider']=='sportsgameodds')
            self.assertEqual(source['archive']['verified'],12)
            self.assertEqual(source['archive']['skipped'],3)
            self.assertIsNone(source['archive_first_received_at'])
            # Counts are labeled per retained representation, not converted
            # into fictitious acquisition or independent prediction totals.
            for source in value['sources']:
                if source['calculated']:
                    counts=source['calculated']
                    self.assertEqual(counts['records'],sum(counts[k]for k in('positive','negative','zero','unavailable')))
