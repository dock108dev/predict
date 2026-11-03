"""Storage attribution against the normal disposable PostgreSQL fixture."""
from psycopg.errors import ReadOnlySqlTransaction
from tests.latest_board_fixture import LatestBoardFixture
from scripts.pipeline_storage_report import snapshot


class StorageReportSQL(LatestBoardFixture):
    async def test_report_attributes_physical_relations_and_forbids_writes(self):
        self.reconcile()
        with self.connect() as db:
            report=snapshot(db)
            self.assertEqual(report['evidence_class'],'live_read_only_sql')
            self.assertGreater(report['database']['physical_bytes'],0)
            rows={r['relation']:r for r in report['relations'] if r['schema']=='public'}
            self.assertIn('current_grid_blob',rows)
            row=rows['current_grid_blob']
            self.assertEqual(row['total_bytes'],row['table_bytes_including_toast']+row['index_bytes'])
            self.assertLessEqual(row['toast_bytes'],row['table_bytes_including_toast'])
            self.assertGreater(report['original_packets']['packets'],0)
            self.assertGreater(report['original_packets']['logical_packet_bytes'],0)
            with self.assertRaises(ReadOnlySqlTransaction):
                db.execute('DELETE FROM current_grid_blob')
