"""Pinned exact evidence survives replacement without whole-slate hydration."""
from unittest.mock import patch
from tests.latest_board_fixture import LatestBoardFixture
from app.storage.grid_packet_store import PacketStore,cleanup
from app.storage.slate_reads import CapturedReads


class PacketLeaseSQL(LatestBoardFixture):
    async def test_lazy_packet_and_selected_lease_survive_projection_replacement(self):
        self.reconcile()
        with self.connect() as db:
            row=db.execute('SELECT game_key,blob_id FROM current_grid_projection ORDER BY game_key LIMIT 1').fetchone()
            store=PacketStore.from_connection(db)
            source=db.execute('SELECT facts FROM latest_board WHERE game_key=%s',(row['game_key'],)).fetchone()['facts']
        reads=CapturedReads(resource_bytes=lambda:0)
        record=reads.join_record(row['game_key'],b'PB1'+row['blob_id'].encode(),None)
        with patch.object(store,'load',side_effect=AssertionError('capture hydrated Originals')):
            frame=reads.capture({'games':[{'game_key':row['game_key']}]},[record],context='ordinary',authority='a',packet_store=store)
        self.addCleanup(reads.clear)
        self.assertLess(frame.size,8192)
        selected,token=reads.selection(frame.token,row['game_key'])
        self.assertEqual(selected['facts']['selected_frame'],source['selected_frame'])
        with self.connect() as db:
            db.execute('DELETE FROM current_grid_projection WHERE game_key=%s',(row['game_key'],))
            db.execute("UPDATE current_grid_blob SET unreferenced_at=now()-interval '10 minutes' WHERE id=%s",(row['blob_id'],))
            reads.discard(frame.token);cleanup(db)
            self.assertIsNotNone(db.execute('SELECT id FROM current_grid_blob WHERE id=%s',(row['blob_id'],)).fetchone())
            again,_=reads.selection(token,row['game_key'])
            self.assertEqual(again['facts']['selected_frame'],source['selected_frame'])
            reads.discard(token);cleanup(db)
            self.assertIsNone(db.execute('SELECT id FROM current_grid_blob WHERE id=%s',(row['blob_id'],)).fetchone())
            self.assertEqual(db.execute('SELECT facts FROM latest_board WHERE game_key=%s',(row['game_key'],)).fetchone()['facts'],source)

    async def test_expired_sql_lease_cannot_be_renewed(self):
        self.reconcile()
        with self.connect() as db:
            row=db.execute('SELECT game_key,blob_id FROM current_grid_projection LIMIT 1').fetchone()
            store=PacketStore.from_connection(db)
            reads=CapturedReads(resource_bytes=lambda:0)
            record=reads.join_record(row['game_key'],b'PB1'+row['blob_id'].encode(),None)
            frame=reads.capture({'games':[{'game_key':row['game_key']}]},[record],context='completed',authority='a',packet_store=store)
            self.addCleanup(reads.clear)
            db.execute("UPDATE current_grid_read_lease SET expires_at=now()-interval '1 second' WHERE token=%s",(frame.token,))
            with self.assertRaisesRegex(ValueError,'current_slate_read_expired'):reads.lease(frame.token)

    async def test_result_original_reference_survives_replacement_and_selected_lease(self):
        import json
        from app.storage.result_publication import attach
        from app.storage.store import encoded
        self.reconcile()
        with self.connect() as db:
            row=db.execute('SELECT * FROM latest_board ORDER BY game_key LIMIT 1').fetchone()
            units=db.execute('SELECT unit_id,facts,original_blob_id FROM current_result_unit WHERE game_key=%s',(row['game_key'],)).fetchall()
            self.assertTrue(units)
            self.assertTrue(all(u['original_blob_id'] for u in units))
            originals={u['original_blob_id']:u['facts']['selected_frame'] for u in units}
            store=PacketStore.from_connection(db)
            attach(db,row,view='ev',lazy_originals=True)
            for unit in row['facts']['result_units'].values():
                payload=unit['facts']['selected_frame']
                self.assertEqual(json.loads(store.load(payload['original_packet'])),originals[payload['original_packet']])
            row['_facts_text']=encoded(row.pop('facts')).decode()
            reads=CapturedReads(resource_bytes=lambda:0)
            self.addCleanup(reads.clear)
            record=reads.join_record(row['game_key'],reads.freeze(encoded(row)),None)
            frame=reads.capture({'games':[{'game_key':row['game_key']}]},[record],context='ordinary',authority='a',packet_store=store)
            _,token=reads.selection(frame.token,row['game_key'])
            db.execute('DELETE FROM current_result_unit WHERE game_key=%s',(row['game_key'],))
            db.execute("UPDATE current_grid_blob SET unreferenced_at=now()-interval '10 minutes' WHERE id=ANY(%s)",(list(originals),))
            reads.discard(frame.token);cleanup(db)
            for key,payload in originals.items():self.assertEqual(json.loads(store.load(key)),payload)
            reads.lease(token)
            reads.discard(token);cleanup(db)
            # The parent fallback independently owns these exact Originals.
            self.assertEqual(db.execute('SELECT count(*) n FROM current_grid_blob WHERE id=ANY(%s)',(list(originals),)).fetchone()['n'],len(originals))
            db.execute('DELETE FROM latest_board WHERE game_key=%s',(row['game_key'],))
            db.execute("UPDATE current_grid_blob SET unreferenced_at=now()-interval '10 minutes' WHERE id=ANY(%s)",(list(originals),))
            cleanup(db)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_grid_blob WHERE id=ANY(%s)',(list(originals),)).fetchone()['n'],0)
