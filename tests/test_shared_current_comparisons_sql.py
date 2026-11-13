"""Exact shared current/zero matrix on disposable PostgreSQL; no providers."""
from copy import deepcopy
from datetime import timedelta
from app.collection.current_confirmation import Confirmations
from app.storage.coverage_latest import reconcile,read
from app.storage.current_rows import CurrentRowStore
from tests.test_broad_native_matrix_sql import NativeMatrixFixture
from tests.broad_pipeline_fixtures import captured_core_matrix
from unittest.mock import patch
import json


def confirmed(book,at,sequence=1):
    book=deepcopy(book);v=book['raw']['ref']['venue'];ref=book['raw']['ref']
    book['raw']['received_at']=(at+timedelta(milliseconds=5)).isoformat()
    if v=='kalshi':
        book['raw']['exchange_at']=None
        data=dict(type='orderbook_snapshot',sending_ts_ms=int(at.timestamp()*1000),sid=2,seq=sequence,msg=dict(market_ticker=ref['market_id']))
    else:
        book['raw']['exchange_at']=at.isoformat()
        data=dict(requestId='authored',subscriptionType='SUBSCRIPTION_TYPE_MARKET_DATA',marketData=dict(bids=[],offers=[],transactTime=at.isoformat()))
    tracker=Confirmations(v);tracker.begin(1)
    proof=tracker.observe(book,data,json.dumps(data).encode(),generation=1,request_id='authored',
        requested_at=(at-timedelta(seconds=1)).isoformat() if v=='kalshi' else None,
        sid=2 if v=='kalshi' else None,sequence=sequence if v=='kalshi' else None)
    book['book_confirmation']=proof
    return book


class SharedCurrentComparisonsSQL(NativeMatrixFixture):
    async def test_complete_metadata_replaces_source_local_groups_without_losing_display(self):
        from app.storage import latest_board as archived

        def archive_group_count():
            with self.connect() as db:
                result=archived.reconcile(db,at=self.at.isoformat(),observations_only=True)
                self.assertTrue(result['published'],result)
                return db.execute('SELECT count(*) n FROM latest_board').fetchone()['n']

        rows,books=await captured_core_matrix(self.at);incomplete=deepcopy(rows)
        for row in incomplete:
            # A complete peer can now supply the occurrence context for an
            # exact-time join. Start with both sources missing that evidence.
            for field in ('season','stage'):
                row['event'][field]=None
                row['market_identity'][field]=None
            row['comparison_source_metadata']['comparison_admission']=dict(supported=False,reason='comparison_context_missing',missing_fields=['season','stage'])
        self.admit(incomplete,books);self.publish()
        with patch.object(archived,'utc',return_value=self.at.isoformat()):
            self.assertGreater(archive_group_count(),18)
        incomplete_counts=(await self.coherent())['global_totals']
        self.assertEqual(incomplete_counts['displayed_observations'],72)
        self.admit(rows,books)
        result=self.publish()
        self.assertTrue(result['published'],result)
        marker=archived.marker;calls=[0]
        def unrelated_noise(db,event_ids=None):
            calls[0]+=1;return marker(db,event_ids)+str(calls[0])
        with patch.object(archived,'utc',return_value=self.at.isoformat()), \
                patch.object(archived,'marker',unrelated_noise):
            self.assertEqual(archive_group_count(),18)
        value=await self.coherent()
        self.assertEqual(value['global_totals']['displayed_observations'],72)
        self.assertEqual(value['global_totals']['displayed_current_comparison_directions'],60)
        self.assertEqual(value['global_totals']['eligible_current_pairs'],30)

    async def test_changed_six_league_inputs_do_not_rehydrate_quiet_slate(self):
        rows,books=await captured_core_matrix(self.at);self.admit(rows,books)
        self.publish()
        def components():
            with self.connect() as db:
                return {r['id']: r['result_id'] for r in db.execute("SELECT id,result_id FROM comparison_publication WHERE kind='component'")}
        before=components()
        self.at+=timedelta(seconds=1);self.state.write(self.service)
        changed=[]
        for sport in ('NFL','NCAAF','NBA','NCAAB','MLB','NHL'):
            row=deepcopy(next(r for r in rows if r['event']['competition']==sport and r['market_identity']['family']=='moneyline'))
            row['quote']['times'].update(source_at=self.at.isoformat(),received_at=self.at.isoformat());changed.append(row)
        with self.connect() as db:CurrentRowStore(db).upsert_records(changed,now=self.at.isoformat())
        with patch.object(CurrentRowStore,'hydrate_records',side_effect=AssertionError('ordinary prices rehydrated depth')):
            result=self.publish()
        self.assertTrue(result['published'],result)
        after=components()
        self.assertEqual(before.keys(),after.keys())
        self.assertEqual(sum(value == before[key] for key,value in after.items()),12)
        value=await self.coherent()
        self.assertEqual(value['global_totals']['displayed_current_comparison_directions'],60)

    async def test_source_continuity_loss_cannot_revive_an_old_confirmation(self):
        rows,books=await captured_core_matrix(self.at);self.admit(rows,books)
        self.publish()
        with self.connect() as db:
            store=CurrentRowStore(db)
            store.upsert_records([],source_status={'kalshi':dict(state='resyncing')},now=self.at.isoformat())
            store.upsert_records([],source_status={'kalshi':dict(state='available')},now=self.at.isoformat())
        self.publish()
        value=await self.coherent()
        self.assertEqual(value['global_totals']['eligible_current_pairs'],0)
        self.assertEqual(value['global_totals']['displayed_current_comparison_directions'],0)
        self.at+=timedelta(seconds=2);self.state.write(self.service)
        rows,books=await captured_core_matrix(self.at);self.admit(rows,books)
        self.publish()
        value=await self.coherent()
        self.assertEqual(value['global_totals']['eligible_current_pairs'],30)
    async def coherent(self):
        with self.connect() as db:
            reconcile(db,at=self.at.isoformat());return read(db,at=self.at.isoformat())

    async def test_complete_matrix_current_publication_pending_recovery_and_expiry(self):
        rows,books=await captured_core_matrix(self.at)
        self.admit(rows,books)
        pending=await self.coherent()
        counts=pending['global_totals']
        self.assertEqual(counts['retained_observations'],72)
        self.assertEqual(counts['eligible_current_pairs'],30)
        self.assertEqual(counts['input_current_peer_observations'],60)
        self.assertEqual(counts['publication_pending_directions'],60)
        self.assertEqual(counts['displayed_current_comparison_directions'],0)
        result=self.publish();self.assertTrue(result['published'],result)
        value=await self.coherent();counts=value['global_totals']
        self.assertEqual(counts['eligible_current_pairs'],30)
        self.assertEqual(counts['published_current_pairs'],30)
        self.assertEqual(counts['displayed_current_comparison_directions'],60)
        self.assertEqual(counts['publication_pending_directions'],0)
        self.assertEqual(counts['display_disagreement_directions'],0)
        # Ordinary status revisions cannot make an unchanged measured cohort stale.
        self.state.write(self.service)
        with self.connect() as db:
            still=read(db,at=self.at.isoformat())
            self.assertEqual(still['publication_state'],'published',still['publication_reasons'])
        self.at+=timedelta(seconds=31);self.state.write(self.service)
        expired=await self.coherent();counts=expired['global_totals']
        self.assertEqual(counts['eligible_current_pairs'],0)
        self.assertEqual(counts['supported_noncurrent_pairs'],30)
        self.assertEqual(counts['displayed_current_comparison_directions'],0)
        self.assertEqual(counts['input_supported_observations'],60)
        self.service.runtime_id+='-replacement';self.state.write(self.service)
        with self.connect() as db:self.assertIn('runtime_changed_since_capture',read(db,at=self.at.isoformat())['publication_reasons'])

    async def test_confirmed_snapshot_after_delta_is_retained_without_price_clock_rewrite(self):
        rows,books=await captured_core_matrix(self.at)
        self.admit(rows,books)
        first=self.at;self.at+=timedelta(seconds=10)
        refreshed=[confirmed(b,self.at-timedelta(milliseconds=10)) for b in books]
        indexed={(b['raw']['ref']['venue'],b['raw']['ref']['market_id']):b for b in refreshed}
        updated=deepcopy(rows)
        for row in updated:
            q=row['quote'];b=indexed[(q['venue'],q['source']['native_market_id'])]
            q['book_confirmation']=deepcopy(b['book_confirmation'])
            if q['venue']=='kalshi':q['times'].update(source_at=None,source_time_kind='unknown')
            q['times']['received_at']=b['raw']['received_at']
        self.admit(updated,refreshed)
        with self.connect() as db:
            saved=CurrentRowStore(db).capture(include_depth=False)['records']
            self.assertEqual(sum(r['quote'].get('book_confirmation') is not None for r in saved),72)
            self.assertEqual(sum(r['quote']['times']['source_at'] is None for r in saved),36)
            self.assertEqual(db.execute('SELECT count(*) n FROM current_native_book WHERE confirmation IS NOT NULL').fetchone()['n'],36)
        # The old priced book clock would now be expired. Its exact confirmed
        # replacement remains current through its own independent expiry.
        self.at=first+timedelta(seconds=35);self.state.write(self.service)
        result=self.publish();self.assertTrue(result['published'],result)
        value=await self.coherent();self.assertEqual(value['global_totals']['displayed_current_comparison_directions'],60)
        # A late old delta cannot replace that confirmed snapshot.
        self.admit(rows,books)
        with self.connect() as db:
            saved=CurrentRowStore(db).capture(include_depth=False)['records']
            self.assertEqual(sum(r['quote'].get('book_confirmation') is not None for r in saved),72)
        self.at=first+timedelta(seconds=41);self.state.write(self.service)
        value=await self.coherent();self.assertEqual(value['global_totals']['eligible_current_pairs'],0)
        self.assertEqual(value['global_totals']['supported_noncurrent_pairs'],30)
