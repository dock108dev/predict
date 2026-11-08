"""Incremental native price path versus complete capture and finance oracle."""
from copy import deepcopy
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from app.storage import comparison_snapshot as snapshots, capture_price
from app.storage.current_rows import CurrentRowStore


@skipUnless(SOCKET,'Disposable PostgreSQL required')
class PriceCaptureSQL(LatestBoardFixture):
    async def test_unrelated_source_reconnect_preserves_exact_incremental_capture(self):
        from psycopg.types.json import Jsonb
        from app.storage.ordinary_publication import component_binding
        with self.connect() as db:
            db.execute("DELETE FROM current_event WHERE provider='polymarket_us'")
            events=[r['id'] for r in db.execute('SELECT id FROM current_event')]
            venues={r['venue'] for r in db.execute('SELECT DISTINCT venue FROM current_contract')}
            binding=component_binding(['policy','settings','epoch',{},dict(kalshi='available',polymarket_us='available',pinnacle='available')],venues)
            previous=snapshots.capture(db,ordinary=True,event_ids=events,at=self.at.isoformat(),capture_binding=binding,price_basis=True)
            db.execute('UPDATE current_source_status SET state=%s WHERE venue=%s',(Jsonb(dict(state='resyncing')),'polymarket_us'))
            self.at+=timedelta(seconds=2)
            actual=capture_price.capture(db,deepcopy(previous),at=self.at.isoformat(),binding=binding,event_ids=events)
            expected=snapshots.capture(db,ordinary=True,event_ids=events,at=self.at.isoformat())
            self.assertIsNotNone(actual)
            for value in (actual,expected):
                for k in ('id','capture_seconds','_price_basis','_price_capture'):value.pop(k,None)
            self.assertEqual(actual,expected)

    async def test_material_receipt_provenance_and_depth_churn_equal_complete(self):
        with self.connect() as db:
            events=[r['id'] for r in db.execute('SELECT id FROM current_event')]
            binding=['fixture-policy','settings','epoch','controls']
            previous=snapshots.capture(db,ordinary=True,event_ids=events,at=self.at.isoformat(),capture_binding=binding,price_basis=True)
            raw=CurrentRowStore(db).capture(include_depth=False)['records']
            native=[r for r in raw if r['quote']['venue'] in ('kalshi','polymarket_us') and r['quote'].get('book_confirmation')]
            self.assertTrue(native)
            for target,kind in [(target,kind) for target in (0,-1) for kind in ('confirmation','material','receipt','audit','depth')]:
                r=deepcopy(native[target]);q=r['quote'];self.at+=timedelta(seconds=2)
                q['times']['received_at']=self.at.isoformat()
                if r.get('comparison_source_metadata',{}).get('observed_at'):
                    r['comparison_source_metadata']['observed_at']=self.at.isoformat()
                if kind=='confirmation':
                    # Authored renewal of the fixture's complete same-content
                    # proof, separate from a new receipt or changed price.
                    from app.dashboard.session_projection import stable
                    proof=q['book_confirmation']
                    proof.update(confirmed_at=self.at.isoformat(),received_at=self.at.isoformat(),
                        payload_sha256=stable(['renewed-fixture',proof['payload_sha256'],self.at.isoformat()]))
                    if q['venue']=='polymarket_us':proof['provider_source_at']=proof['confirmed_at']
                    proof['sha256']=stable({k:v for k,v in proof.items() if k!='sha256'})
                if kind=='material':
                    q.pop('book_confirmation',None);q['times'].update(source_at=self.at.isoformat(),source_time_kind='provider_book')
                    q['original']['value']='0.37'
                    if 'native_value' in q['original']:
                        q['original']['native_value']='0.63' if q['original'].get('transformation')=='one_minus_native_bid' else '0.37'
                    if q.get('provider_clocks'):
                        q['provider_clocks'].update(book=self.at.isoformat(),selected_basis='book')
                if kind=='audit':q['provenance']['sha256']='a'*64
                if kind=='depth':q['depth']=[dict(price='0.37',quantity='9007199254740993.00001')]
                CurrentRowStore(db).upsert_records([r],now=self.at.isoformat());native[target]=r
                with db.transaction():
                    db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                    diagnostics={}
                    actual=capture_price.capture(db,deepcopy(previous),at=self.at.isoformat(),binding=binding,event_ids=events,diagnostics=diagnostics)
                    expected=snapshots.capture(db,ordinary=True,event_ids=events,at=self.at.isoformat())
                self.assertIsNotNone(actual,(kind,diagnostics))
                def content(value):return {k:v for k,v in value.items() if k not in ('id','capture_seconds','_price_basis','_price_capture')}
                def differences(a,b,path=''):
                    if type(a) is not type(b):return [(path,str(a)[:90],str(b)[:90])]
                    if isinstance(a,dict):return [d for k in a.keys()|b.keys() for d in differences(a.get(k),b.get(k),path+'.'+k)][:12]
                    if isinstance(a,list):
                        if len(a)!=len(b):return [(path,len(a),len(b))]
                        return [d for i,(x,y) in enumerate(zip(a,b)) for d in differences(x,y,path+'.'+str(i))][:12]
                    return [] if a==b else [(path,str(a)[:90],str(b)[:90])]
                self.assertEqual(differences(content(actual),content(expected)),[],kind)
                for value in (actual,expected):value.update(id='same-fixture',capture_seconds=0)
                with patch.object(snapshots,'utc',return_value=self.at.isoformat()):
                    a=snapshots.calculate(actual);b=snapshots.calculate(expected)
                a.pop('id');b.pop('id');self.assertEqual(a,b)
                self.assertLess(actual['_price_capture']['read_records'],len(raw))
                previous=actual
            # Expiry changes eligibility, never source evidence clocks. Even
            # with no new receipt, reused groups must match a fresh full owner.
            self.at+=timedelta(seconds=35)
            actual=capture_price.capture(db,deepcopy(previous),at=self.at.isoformat(),binding=binding,event_ids=events)
            expected=snapshots.capture(db,ordinary=True,event_ids=events,at=self.at.isoformat())
            self.assertIsNotNone(actual)
            self.assertEqual(differences(content(actual),content(expected)),[])
            for value in (actual,expected):value.update(id='same-expired-fixture',capture_seconds=0)
            with patch.object(snapshots,'utc',return_value=self.at.isoformat()):
                a=snapshots.calculate(actual);b=snapshots.calculate(expected)
            a.pop('id');b.pop('id');self.assertEqual(a,b)
            previous=actual
            for change in ('controls','contract','membership','reference'):
                with db.transaction(force_rollback=True):
                    changed_binding=binding+['stop'] if change=='controls' else binding
                    if change=='contract':db.execute("UPDATE current_contract SET revision='changed' WHERE id=(SELECT id FROM current_contract LIMIT 1)")
                    if change=='membership':db.execute('DELETE FROM current_offer WHERE contract_id=(SELECT contract_id FROM current_offer LIMIT 1)')
                    if change=='reference':db.execute("UPDATE current_offer SET revision='changed' WHERE contract_id=(SELECT id FROM current_contract WHERE venue='pinnacle' LIMIT 1)")
                    value=capture_price.capture(db,deepcopy(previous),at=self.at.isoformat(),binding=changed_binding,event_ids=events)
                    self.assertIsNone(value,change)
            with patch.object(capture_price,'temporal',return_value=['newly-effective-reviewed-edge']):
                self.assertIsNone(capture_price.capture(db,deepcopy(previous),at=self.at.isoformat(),binding=binding,event_ids=events))

    async def test_unavailable_authority_stays_exact_through_incremental_receipt(self):
        from psycopg.types.json import Jsonb
        with self.connect() as db:
            events=[r['id'] for r in db.execute('SELECT id FROM current_event')]
            for state in ('stopped','resyncing','connecting','available'):
                db.execute('UPDATE current_source_status SET state=%s WHERE venue=%s',(Jsonb(dict(state=state)),'kalshi'))
                previous=snapshots.capture(db,ordinary=True,event_ids=events,at=self.at.isoformat(),capture_binding=state,price_basis=True)
                r=next(r for r in CurrentRowStore(db).capture(include_depth=False)['records'] if r['quote']['venue']=='kalshi')
                self.at+=timedelta(seconds=2);r['quote']['times']['received_at']=self.at.isoformat()
                if r.get('comparison_source_metadata',{}).get('observed_at'):
                    r['comparison_source_metadata']['observed_at']=self.at.isoformat()
                CurrentRowStore(db).upsert_records([r],now=self.at.isoformat())
                # Actual source envelopes also advance their transport clocks
                # while execution authority stays in the same state.
                db.execute('UPDATE current_source_status SET state=%s WHERE venue=%s',
                    (Jsonb(dict(state=state,received_at=self.at.isoformat(),source_at=self.at.isoformat(),reason='Latest image received')),'kalshi'))
                actual=capture_price.capture(db,previous,at=self.at.isoformat(),binding=state,event_ids=events)
                expected=snapshots.capture(db,ordinary=True,event_ids=events,at=self.at.isoformat())
                self.assertIsNotNone(actual,state)
                for value in (actual,expected):
                    for k in ('id','capture_seconds','_price_basis','_price_capture'):value.pop(k,None)
                self.assertEqual(actual,expected,state)
