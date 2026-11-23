"""Shared migrated templates preserve independent disposable database owners."""

from hashlib import sha256
from pathlib import Path
from unittest import skipUnless

import app.storage.store as storage
from tests.latest_board_fixture import LatestBoardFixture, SOCKET


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class SchemaTemplateSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        # This test exercises schema setup itself, before source fixtures write.
        pass

    async def test_each_clone_has_all_migrations_unique_epoch_and_independent_data(self):
        with self.connect() as first:
            first.execute('CREATE TABLE fixture_isolation_sentinel(value text)')
            first.execute("INSERT INTO fixture_isolation_sentinel VALUES('first only')")
            first.execute("UPDATE activity_mode SET reason='first database only'")
            first_epoch = first.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch']

        class Sibling(LatestBoardFixture):
            pass

        Sibling.setUpClass()
        try:
            self.assertEqual(self.schema_template,Sibling.schema_template)
            migrations = sorted((Path(storage.__file__).parent/'migrations').glob('*.sql'))
            expected = [(path.name,sha256(path.read_bytes()).hexdigest()) for path in migrations]
            with Sibling.connect() as second:
                applied = [(row['version'],row['sha256']) for row in second.execute(
                    'SELECT version,sha256 FROM public.schema_migration ORDER BY version')]
                self.assertEqual(applied,expected)
                self.assertIsNone(second.execute("SELECT to_regclass('fixture_isolation_sentinel') relation").fetchone()['relation'])
                self.assertEqual(second.execute('SELECT reason FROM activity_mode').fetchone()['reason'],'default')
                second_epoch = second.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch']
                self.assertNotEqual(first_epoch,second_epoch)
                second.execute("UPDATE activity_mode SET reason='second database only'")
            with self.connect() as first:
                self.assertEqual(first.execute('SELECT reason FROM activity_mode').fetchone()['reason'],'first database only')
            with self.connect('prediction_arb') as admin:
                template = admin.execute('SELECT datistemplate,datallowconn FROM pg_database WHERE datname=%s',
                    (self.schema_template,)).fetchone()
                self.assertTrue(template['datistemplate'])
                self.assertFalse(template['datallowconn'])
        finally:
            Sibling.tearDownClass()
