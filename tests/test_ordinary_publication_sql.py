"""Ordinary publication against disposable source rows; no provider traffic."""
from copy import deepcopy
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_ev09_n01 import SELECTED
from app.storage import ordinary_publication as live, comparison_snapshot as snapshots
from app.storage.current_rows import contract_id
from app.storage.store import stamp
from app.dashboard.snapshot_api import mount


@skipUnless(SOCKET, 'Disposable PostgreSQL required')
class OrdinarySQL(LatestBoardFixture):
    async def test_current_native_quote_expires_and_rotation_preserves_only_the_stored_price(self):
        from app.storage.current_native_desk import overlay
        from app.storage.current_rows import CurrentRowStore
        from tests.broad_pipeline_fixtures import captured_partial
        from tests.multisport_fixtures import source_case

        case = dict(source_case('NBA', 'spread', 'posted-preview', clock=self.at), period='full_game')
        records, exclusions, book, _ = await captured_partial(case, 'kalshi')
        self.assertFalse(exclusions)
        ref = book['raw']['ref']
        key = (ref['venue'], ref['event_id'], ref['market_id'])
        selection = contract_id(records[0])
        empty = dict(rows=[], games=[], publication={})
        owner = dict(healthy=True, active=True, paused_sources=[], config=self.service.config)
        states = {'kalshi': {'state': 'available'}}
        with self.connect() as db:
            store = CurrentRowStore(db)
            store.upsert_records(records, now=self.at.isoformat())
            store.replace_native_books([book])
            fresh, = overlay(db, empty, owner, states, at=self.at, contract=selection)['rows']
            self.assertTrue(fresh['price_current'])
            self.assertTrue(fresh['posted_price'])
            self.assertTrue(fresh['book_size'])
            later = self.at + timedelta(minutes=2)
            self.assertFalse(overlay(db, empty, owner, states, at=later, contract=selection)['rows'])
            store.withdraw_native_markets([key], reimaging=True)
            stored = db.execute('SELECT native_book_id, price_value FROM current_offer_storage WHERE contract_id=%s',
                                (selection,)).fetchone()
            self.assertIsNone(stored['native_book_id'])
            self.assertEqual(stored['price_value'], fresh['original']['value'])
            self.assertFalse(overlay(db, empty, owner, states, at=later, contract=selection)['rows'])
            self.assertFalse(overlay(db, empty, owner, states, at=stamp(fresh['start_at']),
                                     contract=selection)['rows'])
            store.withdraw_native_markets([key])
            self.assertFalse(overlay(db, empty, owner, states, at=later, contract=selection)['rows'])

    async def test_background_publication_records_each_net_positive_arb_appearance(self):
        from fractions import Fraction
        from app.storage.current_rows import CurrentRowStore
        from tests.broad_pipeline_fixtures import captured_partial
        from tests.multisport_fixtures import current_book, source_case

        case = dict(source_case('NBA', 'spread', 'arb-appearance', clock=self.at), period='full_game')

        async def publish_price(db, ask):
            self.at += timedelta(seconds=1)
            case['clock'] = self.at
            self.state.write(self.service)

            def paired_book(case, venue, *, clock):
                book = current_book(case, venue, clock=clock, price='0.60')
                book['sequence'] = str(int(clock.timestamp()))
                side = book['outcomes'][0 if venue == 'kalshi' else 1]
                side['asks']['levels'][0]['price']['value'] = ask
                return book

            store = CurrentRowStore(db)
            for venue in ('kalshi', 'polymarket_us'):
                with patch('tests.broad_pipeline_fixtures.current_book', side_effect=paired_book):
                    records, exclusions, book, _ = await captured_partial(case, venue)
                self.assertEqual(exclusions, [])
                store.upsert_records(records, now=self.at.isoformat())
                store.replace_native_books([book])
            turn = live.turn(db)
            self.assertTrue(turn['published'], turn)
            self.assertEqual(turn['errors'], [])
            return self.result(db)

        def appearances(db):
            return db.execute('SELECT pair_id, appeared_at, disappeared_at, generation, facts '
                              'FROM arb_appearance ORDER BY id').fetchall()

        fixture_fee = dict(available=True, classification='exact_public', fee_cashflows={'at_fill_usd': '0'},
                           evidence=dict(reviewed_at=self.at.isoformat(), standing_public_terms=True))

        def waived_trade_fee(row, *, stake, price, quantity, receipts):
            return dict(available=True, at_fill_usd='0', settlement_usd=dict.fromkeys(receipts, '0'))

        with self.connect() as db:
            db.execute('TRUNCATE arb_appearance')
            before = await publish_price(db, '0.40')
            self.assertTrue(any(Fraction(pair['before_fees']['value']) > 0 for pair in before['pairs']))
            self.assertEqual(appearances(db), [])

            # Use authored zero-fee terms while the production worker matches and prices both legs.
            with patch('app.comparison.snapshot_fee_outcome.outcome', return_value=fixture_fee), \
                    patch('app.comparison.snapshot_pair_fees._leg_fee', side_effect=waived_trade_fee):
                result = await publish_price(db, '0.40')
                positive, = [p for p in result['pairs'] if Fraction(p['default_funding_result']['score'] or '0') > 0]
                current = self.project(db, result)
                current_legs = {r['id']: (r['price_reasons'], r['trade_fee']) for r in current['rows'] if r['id'] in positive['legs']}
                self.assertIn(positive, current['pairs'], current_legs)
                first, = appearances(db)
                self.assertEqual(first['pair_id'], positive['id'])
                self.assertEqual(first['appeared_at'], self.at)
                self.assertLessEqual(first['generation'], live.status(db)['generation'])
                self.assertIsNone(first['disappeared_at'])
                facts = first['facts']
                self.assertEqual(facts['period'], 'full_game')
                self.assertEqual(facts['return_percent'], positive['default_funding_result']['score'])
                # Both legs buy a $1 claim at $0.40 with zero modeled
                # fees in this fixture. 125 units per leg cost $100 and pay $125.
                self.assertEqual(Fraction(facts['return_percent']), 25)
                app = web.Application()
                mount(app)
                with patch('app.dashboard.snapshot_api.connect', self.connect):
                    async with TestClient(TestServer(app)) as client:
                        query = dict(layout='desk', phase='pregame', view='arbs', summary='1', refresh='1')
                        response = await client.get('/api/comparison-current', params=query)
                        self.assertEqual(response.status, 200)
                        arb_page = await response.json()
                        pair, = [p for group in arb_page['rows'] for p in group['pairs']
                                 if p['id'] == positive['id']]
                        self.assertEqual(Fraction(pair['score']), 25)
                        self.assertEqual(pair['retail_payoff']['minimum_net_profit_usd'], '25')
                self.assertEqual({leg['venue'] for leg in facts['legs']}, {'kalshi', 'polymarket_us'})
                self.assertEqual({leg['source_at'] for leg in facts['legs']}, {self.at.isoformat()})

                await publish_price(db, '0.41')
                self.assertEqual(appearances(db), [first])
                await publish_price(db, '0.55')
                self.assertEqual(appearances(db), [dict(first, disappeared_at=self.at)])
                await publish_price(db, '0.40')
                closed, reopened = appearances(db)
                self.assertLess(closed['appeared_at'], closed['disappeared_at'])
                self.assertEqual(reopened['pair_id'], positive['id'])
                self.assertEqual(reopened['appeared_at'], self.at)
                self.assertIsNone(reopened['disappeared_at'])

    async def test_capture_uses_fee_authority_for_newly_seen_venue(self):
        from app.fees import product_schedules

        key = 'kalshi:exchange'
        terms = {'last_verified': {'approval_id': 'fixture', 'revision': 'fee-revision',
                                   'verified_at': (self.at + timedelta(hours=1)).isoformat(), 'review_before': None}}
        with self.connect() as db:
            product_schedules.write(db, key, terms)
            self.addCleanup(lambda: self.clear_fixture_fee(key))
            execute = db.execute

            def lagged_inventory(query, *args, **kwargs):
                result = execute(query, *args, **kwargs)
                if query.startswith('SELECT DISTINCT event_id, venue FROM current_contract'):
                    rows = [dict(row, venue='not_yet_observed') if row['venue'] == 'kalshi' else row
                            for row in result]
                    return iter(rows)
                return result

            with patch.object(db, 'execute', side_effect=lagged_inventory):
                self.assertTrue(live.turn(db)['published'])
            kalshi = [row for row in self.result(db)['rows'] if row['venue'] == 'kalshi']
            self.assertTrue(kalshi)
            expected = product_schedules.revision(terms)
            self.assertTrue(all(row['current_authority']['public_fee_revision'] == expected for row in kalshi))

    def clear_fixture_fee(self, key):
        with self.connect() as db:
            db.execute('DELETE FROM public_fee_schedule WHERE venue=%s', (key,))

    async def test_owned_refresh_preserves_prices_but_failure_and_controls_withdraw(self):
        from app.collection.runtime_status import read_runtime
        with self.connect() as db:
            live.turn(db);result=self.result(db);deps=live.dependencies(db)
            original=read_runtime(db)
            pending=dict(id='request',runtime_id=original['runtime_id'],candidate_digest='code',state='uncertain')
            owner=dict(original,status=dict(quota=dict(blocking_reason='ambiguous_dispatch_unresolved',pause=None,
                publication_pending=pending),sources=[dict(provider='the_odds_api',worker_done=False,
                publication_progress=dict(pending,stage='transport'))]))
            def projected(o):
                with patch('app.collection.runtime_status.read_runtime',return_value=o):
                    actual,states=live.authority(db)
                return live.project(result,deps,actual,states,at=self.at,policy=live.policy_identity(live.committed_aggregate_provider(db)),
                    epoch=result['publication']['epoch'])
            before=projected(original)
            failed_successor=projected(dict(original,calculations={'board':'unavailable'}))
            self.assertEqual(failed_successor['publication']['data_runtime']['reason'],'ordinary_publication_failed')
            self.assertEqual([r['id'] for r in failed_successor['rows'] if r['price_current']],
                [r['id'] for r in before['rows'] if r['price_current']])
            current=projected(owner)
            self.assertEqual([(r['id'],r['price_current']) for r in before['rows']],
                [(r['id'],r['price_current']) for r in current['rows']])
            self.assertTrue(any(r['price_current'] for r in current['rows'] if r['venue']=='novig'))
            for change in ('failure','ownership','pause','stop'):
                o=deepcopy(owner)
                if change=='failure':o['status']['sources'][0]['publication_progress']=None
                if change=='ownership':o['healthy']=False
                if change=='pause':o['paused_sources']=['the_odds_api']
                if change=='stop':o['global_stopped']=True;o['active']=False
                with self.subTest(change=change):
                    rows=projected(o)['rows']
                    self.assertTrue(all(not r['price_current'] for r in rows if r['venue']=='novig'))

    async def test_new_root_reuses_only_present_exact_members_and_rechecks_authority(self):
        from time import monotonic
        from app.storage.store import hashed
        with self.connect() as db:
            live.turn(db)
            def blob():
                return db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',
                    (live.status(db)['result_id'],)).fetchone()['result']
            previous=snapshots.unpack(blob(),lazy=True,db=db)
            selected=previous['rows'][0]['evidence_result_id'];lease=snapshots.retain_evidence(db,selected)
            original=hashed(previous)
            scope={r['id']:[] for r in db.execute("SELECT id FROM comparison_publication WHERE kind='component'")}
            live.compose(db,live.current_settings(db),scope=scope,policy=live.policy_identity(live.committed_aggregate_provider(db)),
                epoch=previous['publication']['epoch'],started=monotonic())
            content=blob();decode=snapshots._decode
            with patch.object(snapshots,'_decode',wraps=decode) as called:
                current=snapshots.unpack(content,lazy=True,db=db,previous=previous)
            self.assertEqual(called.call_count,1)  # Only the new manifest.
            self.assertEqual(current,snapshots.unpack(content,lazy=True,db=db))
            self.assertIs(current['rows'][0],previous['rows'][0])
            self.changed_first();live.turn(db);content=blob()
            replaced=snapshots.unpack(content,lazy=True,db=db,previous=current)
            self.assertEqual(replaced,snapshots.unpack(content,lazy=True,db=db))
            self.assertEqual(hashed(previous),original)
            owner,states=live.authority(db)
            projected=live.project(replaced,live.dependencies(db),dict(owner,global_stopped=True),states,
                at=self.at,policy=live.policy_identity(live.committed_aggregate_provider(db)),epoch=replaced['publication']['epoch'])
            self.assertTrue(all(not r['price_current'] for r in projected['rows']))
            self.assertEqual(replaced,snapshots.unpack(content,lazy=True,db=db))
            db.execute("DELETE FROM comparison_result_reference WHERE kind='lease' AND holder=%s",(lease['lease_id'],))
            # A cached member never hides a missing row in the coherent view.
            member=next(iter(replaced['component_slices']))
            db.execute('UPDATE comparison_snapshot_result SET read_summary=NULL,read_fragment=NULL WHERE id=%s',(member,))
            with self.assertRaisesRegex(snapshots.SnapshotOperationError,'ordinary_fragment_unavailable'):
                snapshots.unpack(content,lazy=True,db=db,previous=replaced)

    async def test_manifest_reuses_exact_projection_and_lease_owns_fragment_cleanup(self):
        from app.storage.store import hashed
        from time import monotonic
        with self.connect() as db:
            live.turn(db);original=self.result(db)
            member=original['rows'][0]['evidence_result_id'];token=snapshots.retain_evidence(db,member)
            head=live.status(db)
            manifest=snapshots._decode(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(head['result_id'],)).fetchone()['result'])
            self.assertEqual(manifest['rows'],[])
            self.assertEqual(manifest['_read_fragments'],'publication-members-v1')
            self.assertIsNotNone(db.execute("SELECT position FROM comparison_result_reference WHERE kind='member' AND holder=%s AND result_id=%s",
                (head['result_id'],member)).fetchone())
            before=db.execute('SELECT id,read_fragment FROM comparison_snapshot_result WHERE read_fragment IS NOT NULL ORDER BY id').fetchall()
            scope={r['id']:[] for r in db.execute("SELECT id FROM comparison_publication WHERE kind='component'")}
            live.compose(db,live.current_settings(db),scope=scope,policy=live.policy_identity(live.committed_aggregate_provider(db)),epoch=original['publication']['epoch'],started=monotonic())
            self.assertEqual(live.status(db)['facts']['new_fragments'],0)
            self.assertEqual(db.execute('SELECT id,read_fragment FROM comparison_snapshot_result WHERE read_fragment IS NOT NULL ORDER BY id').fetchall(),before)
            self.assertEqual(self.result(db)['rows'],original['rows'])
            immutable=hashed(db.execute('SELECT read_fragment AS content FROM comparison_snapshot_result WHERE id=%s AND read_fragment IS NOT NULL',(member,)).fetchone()['content'].hex())
            for _ in range(3):self.changed_first();live.turn(db)
            db.execute("UPDATE comparison_snapshot_result SET lease_until=now()-interval '1 second'")
            db.execute("UPDATE comparison_snapshot SET lease_until=now()-interval '1 second'")
            snapshots.prune(db)
            self.assertEqual(hashed(db.execute('SELECT read_fragment AS content FROM comparison_snapshot_result WHERE id=%s AND read_fragment IS NOT NULL',(member,)).fetchone()['content'].hex()),immutable)
            db.execute("DELETE FROM comparison_result_reference WHERE kind='lease' AND holder=%s",(token['lease_id'],))
            snapshots.prune(db)
            self.assertIsNone(db.execute('SELECT id FROM comparison_snapshot_result WHERE id=%s AND read_fragment IS NOT NULL',(member,)).fetchone())

    async def test_inactive_legacy_reference_does_not_defer_fee_and_pair_work(self):
        with self.connect() as db:
            self.state.write(self.service,paused_sources=['the_odds_api'])
            first=live.turn(db)
            self.assertTrue(first['published'])
            self.assertGreater(first['computed'], 0)
            retained=self.result(db)
            self.assertTrue(retained['rows'])
            self.assertEqual(retained['publication']['finance'],'ready')
            self.assertTrue(all(row.get('gross_return_percent') is None for row in retained['rows']))
            boundary=min(v for row in retained['rows'] for v in
                (row['current_authority']['price'].get('current_until'),row['start_at']) if v)
            self.assertEqual(live.status(db)['facts']['next_boundary'],boundary)
            self.assertTrue(live.turn(db)['unchanged'])
            self.state.write(self.service)
            live.turn(db)
            self.assertEqual(self.result(db)['publication']['finance'],'ready')

    async def test_reused_root_fragments_equal_full_member_composition(self):
        from time import monotonic
        with self.connect() as db:
            live.turn(db)
            before=self.result(db)
            scope={r['id']:[] for r in db.execute("SELECT id FROM comparison_publication WHERE kind='component'")}
            args=dict(scope=scope,settings=before['assumptions'],policy=before['publication']['policy'],
                      epoch=before['publication']['epoch'],started=monotonic())
            # Second seal reuses compact fragments without reading full proofs.
            live.compose(db,**args)
            reused=self.result(db)
            unpack=snapshots.unpack
            def without_index(*a,**kw):
                result=unpack(*a,**kw)
                result.pop('component_slices',None)
                return result
            with patch.object(snapshots,'unpack',side_effect=without_index):
                live.compose(db,**args)
            rebuilt=self.result(db)
            for field in ('rows','pairs','references','games','sources','issues','counts','component_slices'):
                self.assertEqual(reused[field],rebuilt[field],field)
            self.assertEqual(before['rows'],reused['rows'])
            # Repeated deferral is exact, including arbitrary-size proof integers.
            sample=dict(rows=[dict(id='exact',proof=2**100,price='0.12345678901234567890')])
            deferred=snapshots.defer_details(sample)
            self.assertEqual(snapshots.defer_details(deferred),deferred)
            self.assertEqual(snapshots.expand_row(deferred['rows'][0]),sample['rows'][0])

    async def test_recent_native_slots_keep_oldest_api_waiter(self):
        scope={'api':['a'],'quiet':['q'],'kalshi':['k'],'poly':['p']}
        evidence=[dict(event_id='k',venue='kalshi',at=self.at.isoformat()),
                  dict(event_id='p',venue='polymarket_us',at=self.at.isoformat()),
                  dict(event_id='q',venue='kalshi',at=(self.at-timedelta(seconds=31)).isoformat())]
        self.assertEqual(live.prioritize_current(list(scope),scope,evidence,self.at),
                         ['api','kalshi','poly','quiet'])
        scope={str(i):[str(i)] for i in range(12)}
        evidence=[dict(event_id=str(i),venue='kalshi',at=self.at.isoformat()) for i in range(6,12)]
        order=live.prioritize_current(list(scope),scope,evidence,self.at)
        self.assertEqual(order[:6],['0','6','1','7','2','8'])
        self.assertEqual(set(order),set(scope))
        self.assertEqual(len(order),len(scope))
        # A newer unchanged confirmation cannot monopolize the source slot.
        scope={'old':['o'],'confirmation':['c'],'changed':['m']}
        evidence=[dict(event_id='c',venue='kalshi',at=self.at.isoformat()),
                  dict(event_id='m',venue='kalshi',at=(self.at-timedelta(seconds=2)).isoformat())]
        self.assertEqual(live.prioritize_current(list(scope),scope,evidence,self.at,material={'changed'}),
                         ['old','changed','confirmation'])

    def test_current_desk_match_prioritizes_native_sport_without_claiming_freshness(self):
        scope={'old':['o'],'native':['n'],'paired':['k','p']}
        evidence=[dict(event_id='n',venue='kalshi',at=self.at.isoformat()),
            dict(event_id='k',venue='kalshi',at=(self.at-timedelta(seconds=2)).isoformat()),
            dict(event_id='p',venue='pinnacle',at=(self.at-timedelta(seconds=30)).isoformat())]
        self.assertEqual(live.prioritize_current(list(scope),scope,evidence,self.at),['old','native','paired'])
        self.assertEqual(live.prioritize_current(list(scope),scope,evidence,self.at,
                                                 desk_matches={'paired'}),['old','paired','native'])
        state=dict(state='budget_delayed',reason_code='aggregate_scope_observed',
            observed_sports={'NBA':'aggregate_observed','NFL':'aggregate_response_invalid'})
        self.assertTrue(live.source_allowed(state,'NBA'))
        self.assertFalse(live.source_allowed(state,'NFL'))
        self.assertFalse(live.source_allowed(state,'NHL'))

    def test_first_delivery_keeps_fair_and_native_work(self):
        scope={k:[k] for k in ('old','quiet','api','kalshi','poly')}
        evidence=[dict(event_id=k,venue=v,at=self.at.isoformat())
            for k,v in [('kalshi','kalshi'),('poly','polymarket_us')]]
        order=live.prioritize_current(list(scope),scope,evidence,self.at,undelivered={'api'})
        self.assertEqual(order,['old','api','kalshi','poly','quiet'])
        self.assertEqual(len(order),len(set(order)))

    async def asyncSetUp(self):
        await super().asyncSetUp()
        for target in ('app.storage.comparison_snapshot.utc','app.storage.ordinary_publication.utc'):
            p=patch(target,side_effect=lambda:self.at.isoformat());p.start();self.addCleanup(p.stop)
        with self.connect() as db:
            db.execute('TRUNCATE comparison_policy_revision,comparison_snapshot_result,comparison_snapshot CASCADE')
            db.execute("INSERT INTO comparison_publication(kind,id,generation,facts) VALUES('live','',0,'{}')")

    def test_reference_only_sport_respects_transport_controls(self):
        from app.storage.current_row_state import source_status
        state=dict(state='not_offered',reason_code='aggregate_offering_unobserved',
            observed_sports={'NBA':'aggregate_offering_unobserved'},reference_sports={'NBA':'aggregate_observed'})
        with self.connect() as db:
            source_status(db.execute, 'novig', state, self.at)
            owner=dict(healthy=True,active=True,paused_sources=[],status={})
            with patch('app.collection.runtime_status.read_runtime',return_value=owner):
                _,states=live.authority(db)
                self.assertFalse(live.source_allowed(states['novig'],'NBA'))
                self.assertTrue(live.source_allowed(states['pinnacle'],'NBA'))
                self.assertFalse(live.source_allowed(states['pinnacle'],'NFL'))
                owner['paused_sources']=['the_odds_api']
                self.assertFalse(live.source_allowed(live.authority(db)[1]['pinnacle'],'NBA'))
                owner.update(paused_sources=[],status={'quota':{'blocking_reason':'held'}})
                self.assertFalse(live.source_allowed(live.authority(db)[1]['pinnacle'],'NBA'))

    def result(self, db):
        h=live.status(db)
        return snapshots.unpack(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(h['result_id'],)).fetchone()['result'],db=db)

    def project(self, db, result):
        owner,states=live.authority(db,at=self.at)
        return live.project(result,live.dependencies(db),owner,states,at=self.at,
            policy=live.policy_identity(live.committed_aggregate_provider(db)),epoch=result['publication']['epoch'])

    def prepare_component_isolation(self):
        # The shared board fixture's second game is outside the ordinary
        # publisher's 72-hour window at its default read clock.
        self.at = stamp(self.first['start_at']) - timedelta(hours=1)
        self.state.write(self.service)
        self.fresh_sources()

    async def test_replace_confirmation_evidence_and_exclude_legacy_reference(self):
        with self.connect() as db:
            first=live.turn(db);self.assertTrue(first['published'])
            old=self.result(db);self.assertGreater(len(old['rows']),0)
            self.assertTrue(live.turn(db)['unchanged'])
            snapshots.renew_result_lease(db,old['id'])
            # New receipt for identical source economics must not prompt adoption.
            r=deepcopy(next(r for r in self.records if r['quote']['venue']=='novig'))
            r['quote']['times']['received_at']=(self.at+timedelta(seconds=1)).isoformat()
            self.at+=timedelta(seconds=1);self.state.write(self.service);self.admit([r])
            # A new confirmation schedules work but does not withdraw identical
            # economics before the original captured proof actually expires.
            unchanged=self.project(db,old)
            previous=next(q for q in old['rows'] if q['source']==r['quote']['source'])
            still=next(q for q in unchanged['rows'] if q['id']==previous['id'])
            self.assertTrue(still['price_current'])
            self.assertEqual(still['times'],previous['times'])
            live.turn(db);confirmed=self.result(db)
            by_source=lambda result: next(row for row in result['rows'] if row['source']==r['quote']['source'])
            self.assertEqual(by_source(old)['economic_revision'],by_source(confirmed)['economic_revision'])
            changed=self.changed_first();live.turn(db);new=self.result(db)
            updated=next(row for row in new['rows'] if row['source']==changed['quote']['source'])
            self.assertEqual(updated['original']['value'],'2.91')
            self.assertNotEqual(old['id'],new['id'])
            self.assertEqual(snapshots.current(db,old['id']),old)
            # Preserved legacy input cannot determine price visibility or EV.
            ref=db.execute("SELECT id FROM current_contract WHERE venue='pinnacle' LIMIT 1").fetchone()['id']
            db.execute("UPDATE current_offer SET revision='reference-only-change',facts=jsonb_set(facts,'{original,value}','\"2.99\"') WHERE contract_id=%s",(ref,))
            gated=self.project(db,new)
            row=next(r for r in gated['rows'] if r['id']==updated['id'])
            self.assertTrue(row['price_current'])
            self.assertIsNone(row['gross_return_percent'])
            self.assertNotIn('input_replaced_or_removed',row['current_reasons'])

    async def test_prices_survive_finance_failure_and_retry(self):
        with self.connect() as db:
            with patch.object(snapshots,'calculate',side_effect=RuntimeError('fixture finance failure')):
                self.assertTrue(live.turn(db)['errors'])
            current=self.result(db)
            self.assertTrue(current['rows'])
            self.assertTrue(all(r['gross_return_percent'] is None for r in current['rows']))
            self.assertEqual(live.status(db)['facts']['finance'],'failed')
            self.assertTrue(live.turn(db)['published'])
            self.assertEqual(self.result(db)['publication']['finance'],'ready')

    async def test_price_capture_failure_keeps_other_components_and_pinned_evidence(self):
        def affected(row):
            source=row['source']
            return (source['provider'],source['native_event_id']) == SELECTED

        peer_sources = {tuple(member) for member in self.second['members']}

        def peer_members(result):
            return {r['evidence_result_id'] for r in result['rows']
                    if (r['source']['provider'], r['source']['native_event_id']) in peer_sources}

        self.prepare_component_isolation()
        with self.connect() as db:
            live.turn(db)
            before=self.result(db)
            prior={r['evidence_result_id'] for r in before['rows'] if affected(r)}
            self.assertEqual(len(prior),1)
            self.assertTrue(peer_members(before) - prior)
            member=next(iter(prior));token=snapshots.retain_evidence(db,member)
            self.at+=timedelta(seconds=1);self.state.write(self.service);self.fresh_sources()
            prices=live.prices

            def price_failure(inputs, settings, **kwargs):
                if any(affected(r) for r in inputs['quotes']):
                    raise ValueError('fixture component capture failure')
                return prices(inputs,settings,**kwargs)

            with patch.object(live,'prices',side_effect=price_failure):
                turn=live.turn(db)
            self.assertTrue(turn['published'])
            self.assertEqual([error['reason'] for error in turn['errors']],['ordinary_price_capture_failed'])
            after=self.result(db)
            self.assertEqual(after['_failed_price_members'],[member])
            projected=self.project(db,after)
            failed=[r for r in projected['rows'] if r['evidence_result_id']==member]
            self.assertTrue(failed)
            self.assertTrue(all(r['gross_return_percent'] is None for r in failed))
            self.assertTrue(all('ordinary_price_capture_failed' in r['current_reasons'] for r in failed))
            self.assertTrue(peer_members(projected) - peer_members(before))
            self.assertFalse(any(p['evidence_result_id']==member for p in projected['pairs']))
            self.assertIsNotNone(snapshots.current(db,member))
            self.assertTrue(live.turn(db)['published'])
            self.assertNotIn('_failed_price_members',self.result(db))
            db.execute("DELETE FROM comparison_result_reference WHERE kind='lease' AND holder=%s",(token['lease_id'],))

    async def test_finance_seal_failure_rolls_back_only_its_component(self):
        self.prepare_component_isolation()
        with self.connect() as db:
            seal=live.seal

            def seal_failure(db, inputs, result, facts, **kw):
                generation=seal(db,inputs,result,facts,**kw)
                if kw.get('component') and facts['finance']=='ready' and any(
                    (r['source']['provider'],r['source']['native_event_id'])==SELECTED for r in inputs['quotes']):
                    raise RuntimeError('fixture failure after component writes')
                return generation

            with patch.object(live,'seal',side_effect=seal_failure):
                turn=live.turn(db)
            self.assertTrue(turn['computed'])
            self.assertEqual([error['reason'] for error in turn['errors']],['ordinary_finance_failed'])
            states={r['facts']['finance'] for r in db.execute("SELECT facts FROM comparison_publication WHERE kind='component'")}
            self.assertTrue({'ready','failed'} <= states)
            after=self.result(db)
            failed=[r for r in after['rows'] if (r['source']['provider'],r['source']['native_event_id'])==SELECTED]
            self.assertTrue(failed)
            self.assertTrue(all(r['gross_return_percent'] is None for r in failed))
            self.assertTrue(live.turn(db)['published'])
            self.assertEqual(self.result(db)['publication']['finance'],'ready')

    async def test_stop_pause_reconnect_expiry_and_policy_do_not_renew_prices(self):
        with self.connect() as db:
            live.turn(db);result=self.result(db)
            before=self.project(db,result)
            current=[r for r in before['rows'] if r['price_current']]
            self.assertTrue(current)
            self.state.write(self.service,global_stopped=True)
            # Runtime active can still be True in an authored contradictory frame;
            # the explicit Stop must always win.
            held=self.project(db,result)
            self.assertEqual(held['publication']['state'],'held')
            self.assertTrue(all(r['gross_return_percent'] is None for r in held['rows']))
            self.state.write(self.service,paused_sources=['the_odds_api'])
            paused=self.project(db,result)
            self.assertTrue(all(r['gross_return_percent'] is None for r in paused['rows']))
            self.state.write(self.service)
            restored=self.project(db,result)
            self.assertEqual([r['times'] for r in restored['rows']],[r['times'] for r in before['rows']])
            owner,states=live.authority(db,at=self.at)
            changed=live.project(result,live.dependencies(db),owner,states,at=self.at,
                policy='changed',epoch=result['publication']['epoch'])
            self.assertTrue(all(r['gross_return_percent'] is None for r in changed['rows']))
            self.at+=timedelta(hours=2);self.state.write(self.service)
            retained=self.project(db,result)
            self.assertTrue(any(r['price_current'] for r in retained['rows']))
            self.assertTrue(all(stamp(r['start_at']) > self.at for r in retained['rows'] if r['price_current']))

    async def test_http_reads_notify_without_collection_or_recalculation(self):
        with self.connect() as db:live.turn(db)
        app=web.Application();mount(app)
        with patch('app.dashboard.snapshot_api.connect',self.connect),patch.object(snapshots,'calculate',side_effect=AssertionError('read cannot calculate')),patch.object(snapshots,'capture',side_effect=AssertionError('read cannot capture')):
            async with TestClient(TestServer(app)) as client:
                response=await client.get('/api/comparison-current?group=outcome')
                first=await response.json();self.assertEqual(response.status,200)
                self.assertTrue(first['rows']);self.assertEqual(first['provider_requests'],0)
                selected=await (await client.get('/api/comparison-current/selection',params={'id':first['rows'][0]['quotes'][0]['id']})).json()
                self.assertEqual(selected['row']['id'],first['rows'][0]['quotes'][0]['id'])
                self.assertEqual(selected['result_id'],first['id'])
                removed=await (await client.get('/api/comparison-current/selection',params={'id':'absent-exact-selection'})).json()
                self.assertEqual(removed['state'],'removed')
                self.assertIsNone(removed['row'])
                update=await (await client.get('/api/comparison-current/updates',params={'after':first['cursor']})).json()
                self.assertFalse(update['changed'])
                seen=[];prices=[]
                for offset in range(first['total']):
                    part=await (await client.get('/api/comparison-current',params={
                        'offset':str(offset),'limit':'1','expected_cursor':first['cursor']})).json()
                    self.assertEqual(part['cursor'],first['cursor'])
                    seen.extend(g['id'] for g in part['rows'])
                    prices.extend(r['id'] for g in part['rows'] for r in g['quotes'])
                self.assertEqual(len(set(seen)),first['total'])
                self.assertEqual(len(set(prices)),first['source_price_count'])
                confirmed=deepcopy(next(r for r in self.records if r['quote']['venue']=='novig'))
                self.at+=timedelta(seconds=1);self.state.write(self.service)
                confirmed['quote']['times']['received_at']=self.at.isoformat();self.admit([confirmed])
                confirmation=await (await client.get('/api/comparison-current/updates',params={'after':first['cursor']})).json()
                self.assertFalse(confirmation['changed'],'same economics cannot invalidate a frozen source proof')
                continuation=await (await client.get('/api/comparison-current',params={'offset':'1','limit':'1','expected_cursor':first['cursor']})).json()
                self.assertEqual(continuation['cursor'],first['cursor'])
                self.assertEqual(continuation['metric'],'conditional_return_percent')
                self.assertEqual(continuation['grouping'],'outcome')
                self.changed_first()
                conflict=await (await client.get('/api/comparison-current',params={'offset':'1','expected_cursor':first['cursor']})).json()
                self.assertEqual(conflict['state'],'page_changed')
                self.assertEqual(conflict['rows'],[])
                self.assertEqual(conflict['generation'],first['generation'])
                update=await (await client.get('/api/comparison-current/updates',params={'after':first['cursor']})).json()
                self.assertTrue(update['changed'])
                self.assertEqual(update['generation'],first['generation'])
                lease=await client.post('/api/comparison-current/lease',json={'result_id':first['id']})
                self.assertEqual(lease.status,200)
                self.state.write(self.service,global_stopped=True)
                stopped=await (await client.get('/api/comparison-current/updates',params={'after':update['cursor']})).json()
                self.assertTrue(stopped['changed']);self.assertEqual(stopped['generation'],first['generation'])
                selected=await (await client.get('/api/comparison-current/selection',params={'id':prices[0]})).json()
                self.assertEqual(selected['state'],'unavailable')
                self.assertIn('updates_stopped',selected['row']['current_reasons'])

    async def test_pregame_desk_updates_bypass_projection_and_watch_committed_prices(self):
        with self.connect() as db:
            self.assertTrue(live.turn(db)['published'])
        app = web.Application()
        mount(app)
        query = dict(layout='desk', view='ev', summary='1', browse_odds='1',
                     lines='all', phase='live', basis='sportsbooks')
        with patch('app.dashboard.snapshot_api.connect', self.connect):
            async with TestClient(TestServer(app)) as client:
                response = await client.get('/api/comparison-current', params=query)
                page = await response.json()
                self.assertEqual(response.status, 200)
                self.assertEqual(page['features'], {'live_enabled': False, 'auto_update': True})
                self.assertEqual(page['phase'], 'pregame')
                self.assertTrue(page['rows'])
                phase_query = dict(layout='desk', phase='pregame', after=page['update_cursor'])
                with patch.object(live, 'published_dependencies', side_effect=AssertionError('update decoded slate')):
                    same = await client.get('/api/comparison-current/updates', params=phase_query)
                    self.assertFalse((await same.json())['changed'])
                    self.assertNotIn('dependencies;', same.headers['Server-Timing'])
                    self.changed_first()
                    pending = await client.get('/api/comparison-current/updates', params=phase_query)
                    self.assertFalse((await pending.json())['changed'])
                with self.connect() as db:
                    self.assertTrue(live.turn(db)['published'])
                changed = await client.get('/api/comparison-current/updates', params=phase_query)
                signal = await changed.json()
                self.assertTrue(signal['changed'])
                self.assertGreater(signal['generation'], page['generation'])
                self.assertEqual(signal['provider_requests'], 0)
                self.assertEqual(stamp(page['refresh_at']), min(stamp(row['start_at']) for row in page['rows']))
                self.at = max(stamp(row['start_at']) for row in page['rows'])
                self.state.write(self.service)
                after_kickoff = await (await client.get('/api/comparison-current', params=query)).json()
                self.assertEqual(after_kickoff['phase'], 'pregame')
                self.assertTrue(all(stamp(row['start_at']) > self.at for row in after_kickoff['rows']))

    async def test_oversized_component_does_not_block_unrelated_publication_or_desk_reads(self):
        self.prepare_component_isolation()
        with self.connect() as db:
            db.execute('''INSERT INTO current_contract_storage
                (id,event_id,venue,native_market_id,native_outcome_id,native_side,facts,revision)
                SELECT encode(sha256(convert_to('overload-'||i,'UTF8')),'hex'), c.event_id,
                    c.venue, 'overload-'||i,c.native_outcome_id,c.native_side,c.facts,c.revision
                FROM (SELECT c.* FROM current_contract c JOIN current_event e ON e.id=c.event_id
                    WHERE (e.provider,e.native_event_id)=(%s,%s) LIMIT 1) c
                CROSS JOIN generate_series(1,32769) i''', SELECTED)
            db.execute('''INSERT INTO current_offer_storage
                (contract_id,price_value,price_units,quantity_units,received_at,received_order,facts,revision)
                SELECT id,'1.91','decimal','contracts',%s,0,'{}','fixture-overload'
                FROM current_contract WHERE native_market_id LIKE 'overload-%%' ''', (self.at.isoformat(),))
            turn = live.turn(db)
            self.assertTrue(turn['published'])
            self.assertEqual([error['reason'] for error in turn['errors']], ['ordinary_price_capture_failed'])
            self.assertTrue(self.result(db)['rows'])

        app = web.Application()
        mount(app)
        with patch('app.dashboard.snapshot_api.connect', self.connect), \
             patch.object(live, 'dependencies', side_effect=AssertionError('desk must use published evidence')):
            async with TestClient(TestServer(app)) as client:
                for filters in ('browse_odds=1', 'ranked=1', 'ranked=1&view=arbs'):
                    response = await client.get(f'/api/comparison-current?layout=desk&lines=main&{filters}')
                    self.assertEqual(response.status, 200)
                    page = await response.json()
                    self.assertIsInstance(page['rows'], list)
                    self.assertEqual(page['provider_requests'], 0)
                update = await client.get('/api/comparison-current/updates')
                self.assertEqual(update.status, 200)

    async def test_current_desk_projection_matches_full_projection_after_price_withdrawal(self):
        from app.dashboard.trade_desk import page

        with self.connect() as db:
            live.turn(db)
            result = self.result(db)
            self.changed_first()
            owner, states = live.authority(db, at=self.at)
            deps = live.dependencies(db)
            options = dict(at=self.at, policy=live.policy_identity(live.committed_aggregate_provider(db)), epoch=result['publication']['epoch'])
            full = live.project(result, deps, owner, states, **options)
            desk = live.project(result, deps, owner, states, current_desk=True, **options)
        self.assertTrue(any(row['price_current'] for row in full['rows']))
        self.assertTrue(any(not row['price_current'] for row in full['rows']))
        for options in (dict(browse_odds='1'), dict(ranked='1')):
            query = dict(layout='desk', lines='all', **options)
            self.assertEqual(page(full, query, ('ev', None, 0, 20)),
                             page(desk, query, ('ev', None, 0, 20)))

    async def test_prune_automatic_history_preserves_selected_only(self):
        with self.connect() as db:
            for i in range(3):
                self.changed_first();live.turn(db)
                if i==0: selected=self.result(db);snapshots.renew_result_lease(db,selected['id'])
            db.execute("UPDATE comparison_snapshot_result SET lease_until=now()-interval '1 hour' WHERE id<>%s",(selected['id'],))
            db.execute("UPDATE comparison_snapshot SET lease_until=now()-interval '1 hour' WHERE id<>%s",(selected['snapshot_id'],))
            snapshots.prune(db)
            self.assertEqual(db.execute("SELECT count(*) n FROM comparison_snapshot_result r WHERE r.automatic AND NOT EXISTS(SELECT 1 FROM comparison_publication c WHERE c.kind='component' AND c.result_id=r.id) AND NOT EXISTS(SELECT 1 FROM comparison_result_reference m WHERE m.kind='member' AND m.result_id=r.id)").fetchone()['n'],2)
            self.assertEqual(snapshots.current(db,selected['id']),selected)

    async def test_legacy_lease_reserves_result_before_concurrent_prune(self):
        with self.connect() as db:
            live.turn(db)
            selected = self.result(db)
            self.changed_first()
            live.turn(db)
            self.assertNotEqual(live.status(db)['result_id'], selected['id'])
            db.execute("""UPDATE comparison_snapshot_result SET lease_until=now()-interval '1 hour'
                WHERE id=%s""", (selected['id'],))
            db.execute("""UPDATE comparison_snapshot SET lease_until=now()-interval '1 hour'
                WHERE id=%s""", (selected['snapshot_id'],))
            execute = db.execute
            ran_prune = False

            def competing_prune(query, *params):
                nonlocal ran_prune
                rows = execute(query, *params)
                if query.lstrip().startswith('SELECT automatic,lease_until'):
                    with self.connect() as pruning:
                        snapshots.prune(pruning)
                    ran_prune = True
                return rows

            with patch.object(db, 'execute', side_effect=competing_prune):
                self.assertTrue(snapshots.renew_result_lease(db, selected['id']))
            self.assertTrue(ran_prune)
            self.assertEqual(snapshots.current(db, selected['id']), selected)
            self.assertTrue(db.execute('''SELECT lease_until>now() retained FROM comparison_snapshot
                WHERE id=%s''', (selected['snapshot_id'],)).fetchone()['retained'])

    async def test_automatic_churn_does_not_evict_latest_two_manual_captures(self):
        with self.connect() as db:
            manual=[]
            for _ in range(3):
                self.at+=timedelta(seconds=1);self.state.write(self.service)
                manual.append(snapshots.replace(db,action='refresh'))
            db.execute("UPDATE comparison_snapshot_result SET lease_until=now()-interval '1 hour'")
            db.execute("UPDATE comparison_snapshot SET lease_until=now()-interval '1 hour'")
            live.turn(db);snapshots.prune(db)
            kept={r['id'] for r in db.execute('SELECT id FROM comparison_snapshot WHERE NOT automatic')}
            self.assertEqual(kept,{r['snapshot_id'] for r in manual[1:]})

    async def test_superseded_head_grace_starts_at_replacement(self):
        with self.connect() as db:
            live.turn(db);old=live.status(db)['result_id']
            db.execute("UPDATE comparison_snapshot_result SET lease_until=now()-interval '1 hour' WHERE id=%s",(old,))
            self.changed_first();live.turn(db)
            self.assertNotEqual(live.status(db)['result_id'],old)
            self.assertTrue(db.execute('SELECT lease_until>now() retained FROM comparison_snapshot_result WHERE id=%s',(old,)).fetchone()['retained'])
            self.assertEqual(snapshots.retain_evidence(db,old)['result_id'],old)

    async def test_settings_withdraw_finance_and_token_lease_releases_exact_members(self):
        from app.comparison.display_identity import canonical_key
        from app.dashboard.snapshot_display import outcome_key

        with self.connect() as db:
            live.turn(db)
            published = self.result(db)
            self.assertTrue(published['rows'])
            for row in published['rows']:
                self.assertEqual(outcome_key(row), canonical_key(row) or ('unresolved', row['id']))
                self.assertIn('display_outcome_key', row)
        app=web.Application();mount(app)
        with patch('app.dashboard.snapshot_api.connect',self.connect):
            async with TestClient(TestServer(app)) as client:
                first=await (await client.get('/api/comparison-current')).json()
                token=await (await client.post('/api/comparison-current/lease',json={'result_id':first['id']})).json()
                self.assertIn('lease_id',token)
                row=first['rows'][0]['quotes'][0]
                evidence=await (await client.get('/api/comparison-snapshot/details',params=dict(result_id=first['id'],id=row['id'],lease_id=token['lease_id']))).json()
                self.assertEqual(evidence['originals'][0]['original'],row['original'])
                self.assertEqual(evidence['row']['display_outcome_key'], row['display_outcome_key'])
                # A member/details read cannot evict the decoded ordinary root.
                # Authority is nevertheless checked again, below, after settings.
                with patch.object(snapshots,'unpack',side_effect=AssertionError('ordinary root evicted by inspection')):
                    warm=await client.get('/api/comparison-current')
                    self.assertEqual(warm.status,200)
                    self.assertEqual((await warm.json())['id'],first['id'])
                opts=dict(first['assumptions'],amount='1234')
                with patch.object(snapshots,'calculate',side_effect=AssertionError('settings handler cannot calculate')):
                    response=await client.post('/api/comparison-current/settings',json=dict(expected=first['assumptions']['revision'],assumptions=opts))
                    self.assertEqual(response.status,200)
                    changed=await (await client.get('/api/comparison-current')).json()
                self.assertEqual(changed['assumptions']['amount'],'1234')
                self.assertTrue(all(r['gross_return_percent'] is None for g in changed['rows'] for r in g['quotes']))
                self.assertTrue(any(r['price_current'] for g in changed['rows'] for r in g['quotes']))
                again=await (await client.get('/api/comparison-snapshot/details',params=dict(result_id=first['id'],id=row['id'],lease_id=token['lease_id']))).json()
                self.assertEqual(again['assumptions'],evidence['assumptions'])
                response=await client.delete('/api/comparison-current/lease',params={'lease_id':token['lease_id']})
                self.assertEqual(response.status,200)
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) n FROM comparison_result_reference WHERE kind='lease'").fetchone()['n'],0)
            self.assertTrue(live.turn(db)['published'])

    async def test_fee_expiry_does_not_withdraw_gross_or_renew_source_clock(self):
        with self.connect() as db:
            live.turn(db);result=self.result(db)
            projected=self.project(db,result)
            chosen=next(r for r in projected['rows'] if r['price_current'])
            row=next(r for r in result['rows'] if r['id']==chosen['id'])
            row['gross_return_percent']='2'
            row['conditional_return_percent']='1'
            row['current_authority']['fee_until']=(self.at+timedelta(seconds=1)).isoformat()
            original=deepcopy(row['times']);self.at+=timedelta(seconds=2);self.state.write(self.service)
            expired=next(r for r in self.project(db,result)['rows'] if r['id']==row['id'])
            self.assertEqual(expired['gross_return_percent'], '2')
            self.assertIsNone(expired['conditional_return_percent'])
            self.assertEqual(expired['times'],original)

    async def test_failed_successor_rolls_back_staged_components(self):
        with self.connect() as db:
            live.turn(db)
            head=live.status(db)
            members=db.execute("SELECT id,result_id,facts FROM comparison_publication WHERE kind='component' ORDER BY id").fetchall()
            inputs=db.execute('SELECT id FROM comparison_snapshot ORDER BY id').fetchall()
            self.changed_first()
            with patch.object(live,'compose',side_effect=snapshots.SnapshotOperationError('ordinary_retention_capacity')):
                with self.assertRaises(snapshots.SnapshotOperationError):
                    live.turn(db)
            self.assertEqual(live.status(db),head)
            self.assertEqual(db.execute("SELECT id,result_id,facts FROM comparison_publication WHERE kind='component' ORDER BY id").fetchall(),members)
            self.assertEqual(db.execute('SELECT id FROM comparison_snapshot ORDER BY id').fetchall(),inputs)
            self.assertTrue(live.turn(db)['published'])

    async def test_lazy_reads_match_eager_reference_fee_and_withdrawal_projection(self):
        from app.dashboard.snapshot_api import page
        with self.connect() as db:
            live.turn(db)
            blob=db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',
                (live.status(db)['result_id'],)).fetchone()['result']
            eager=snapshots.unpack(blob,db=db)
            lazy=snapshots.unpack(blob,lazy=True,db=db)
            self.assertIn('_detail_json',lazy['rows'][0])
            before=deepcopy(lazy)
            for expired in (False,True):
                if expired:
                    self.at+=timedelta(hours=1);self.state.write(self.service)
                for metric in ('gross_return_percent','conditional_return_percent','conservative_return_percent'):
                    query=dict(group='outcome',metric=metric,limit='100')
                    self.assertEqual(page(self.project(db,eager),query),page(self.project(db,lazy),query))
            self.assertEqual(lazy,before)

    async def test_concurrent_current_readers_share_one_cold_decode(self):
        import asyncio
        import time
        with self.connect() as db:live.turn(db)
        app=web.Application();mount(app)
        original=snapshots.unpack
        def delayed(*args,**kwargs):
            time.sleep(.05)
            return original(*args,**kwargs)
        with patch('app.dashboard.snapshot_api.connect',self.connect),patch.object(snapshots,'unpack',side_effect=delayed) as decode:
            async with TestClient(TestServer(app)) as client:
                responses=await asyncio.gather(*(client.get('/api/comparison-current') for _ in range(2)))
                results=[await r.json() for r in responses]
                self.assertEqual(results[0]['id'],results[1]['id'])
                self.assertEqual(decode.call_count,1)
                selected=results[0]['rows'][0]['quotes'][0]
                response=await client.get('/api/comparison-current/selection',params={'id':selected['id']})
                exact=await response.json()
                self.assertEqual(exact['publication']['count_scope'],'selected_inputs')
                self.assertEqual(exact['row'],{k:v for k,v in selected.items() if k!='ranking'})

    async def test_concurrent_pregame_summary_shares_projection_body_and_browse_order(self):
        import asyncio

        with self.connect() as db:
            self.assertTrue(live.turn(db)['published'])
        app = web.Application()
        mount(app)
        query = dict(layout='desk', view='ev', summary='1', browse_odds='1',
                     lines='all', phase='pregame', basis='sportsbooks', limit='12')
        with patch('app.dashboard.snapshot_api.connect', self.connect), \
                patch.object(live, 'published_dependencies', wraps=live.published_dependencies) as dependencies:
            async with TestClient(TestServer(app)) as client:
                responses = await asyncio.gather(*(client.get('/api/comparison-current', params=query,
                    headers={'Accept-Encoding': 'gzip' if index else 'identity'}) for index in range(12)))
                self.assertTrue(all(response.status == 200 for response in responses))
                self.assertNotIn('Content-Encoding', responses[0].headers)
                self.assertTrue(all(response.headers.get('Content-Encoding') == 'gzip' for response in responses[1:]))
                pages = [await response.json() for response in responses]
                self.assertTrue(pages[0]['rows'])
                self.assertTrue(pages[0]['browse_id'])
                self.assertTrue(all(page == pages[0] for page in pages))
                self.assertEqual(dependencies.call_count, 0)

    async def test_current_read_overload_refuses_extra_work_and_recovers(self):
        import asyncio
        from threading import Event

        with self.connect() as db:
            self.assertTrue(live.turn(db)['published'])
        app = web.Application()
        mount(app)
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = Event()

        def held_connect():
            loop.call_soon_threadsafe(started.set)
            if not release.wait(5):
                raise AssertionError('HTTP fixture never released the admitted read')
            return self.connect()

        query = dict(layout='desk', summary='1', browse_odds='1', lines='all', phase='pregame', limit='12')
        with patch('app.dashboard.snapshot_api.connect', side_effect=held_connect) as connect, \
                patch('app.dashboard.desk_delivery.MAX_DESK_READS', 1):
            async with TestClient(TestServer(app)) as client:
                reading = asyncio.create_task(client.get('/api/comparison-current', params=query))
                try:
                    await asyncio.wait_for(started.wait(), 5)
                    response = await client.get('/api/comparison-current', params=dict(query, search='fixture'))
                    self.assertEqual(response.status, 503, await response.text())
                    selected = await client.get('/api/comparison-current/selection', params={'id': 'absent'})
                    self.assertEqual(selected.status, 503, await selected.text())
                    self.assertEqual(connect.call_count, 1)
                finally:
                    release.set()
                self.assertEqual((await reading).status, 200)
                retried = await client.get('/api/comparison-current/selection', params={'id': 'absent'})
                self.assertEqual(retried.status, 200, await retried.text())
                self.assertEqual((await retried.json())['state'], 'removed')
                self.assertEqual(connect.call_count, 2)

    async def test_lossless_headroom_preserves_selected_bytes_and_reclaims_cycles(self):
        import gzip
        import json
        with self.connect() as db:
            live.turn(db)
            selected=self.result(db)
            member=selected['rows'][0]['evidence_result_id']
            token=snapshots.retain_evidence(db,member)
            original=db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(member,)).fetchone()['result']
            # Reproduce legacy low-density storage without altering logical data.
            blob=gzip.compress(json.dumps(snapshots.unpack(original)).encode(),compresslevel=1)
            db.execute('UPDATE comparison_snapshot_result SET result=%s WHERE id=%s',(blob,member))
            before=live.retained_bytes(db)
            with db.transaction(force_rollback=True):
                db.execute("INSERT INTO comparison_result_reference(kind,holder,result_id) VALUES('review',%s,%s)",
                           (member,member))
                with patch.object(live,'MAX_BYTES',1):
                    live.compact_retention(db,0)
                self.assertEqual(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',
                    (member,)).fetchone()['result'],blob)
            with patch.object(live,'MAX_BYTES',before-1):
                live.compact_retention(db,0)
            self.assertLess(live.retained_bytes(db),before)
            for _ in range(5):
                self.changed_first();live.turn(db)
                db.execute("UPDATE comparison_snapshot_result SET lease_until=now()-interval '1 second' WHERE automatic")
                db.execute("UPDATE comparison_snapshot SET lease_until=now()-interval '1 second' WHERE automatic")
                snapshots.prune(db)
                self.assertLessEqual(live.retained_bytes(db),live.MAX_BYTES)
                retained=db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(member,)).fetchone()
                self.assertEqual(snapshots.unpack(retained['result']),snapshots.unpack(original))
                self.assertEqual(db.execute("SELECT result_id FROM comparison_result_reference WHERE kind='lease' AND holder=%s",(token['lease_id'],)).fetchone()['result_id'],member)
            self.assertEqual(db.execute("SELECT count(DISTINCT holder) n FROM comparison_result_reference WHERE kind='member'").fetchone()['n'],1)

    async def test_early_structural_rejections_keep_complete_inputs_money_and_selection(self):
        from psycopg.types.json import Jsonb
        from app.storage.store import hashed
        ignored={'id','capture_seconds','_price_basis','_price_capture'}
        with self.connect() as db:
            live.turn(db)
            original=self.result(db)['rows'][0]['evidence_result_id'];lease=snapshots.retain_evidence(db,original)
            pinned=db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(original,)).fetchone()['result']
            contract=db.execute('SELECT c.id,c.event_id,c.facts FROM current_contract c JOIN current_offer o ON o.contract_id=c.id ORDER BY c.id LIMIT 1').fetchone()
            for kind in ('contract_revision','event_revision','offer_membership','governing_binding_changed_before_decode'):
                if kind=='contract_revision':
                    facts=deepcopy(contract['facts'])
                    facts.setdefault('comparison_source_metadata',{})['observed_at']=self.at.isoformat()
                    db.execute('UPDATE current_contract SET facts=%s,revision=%s WHERE id=%s',(Jsonb(facts),hashed(facts),contract['id']))
                elif kind=='event_revision':
                    event=db.execute('SELECT facts FROM current_event WHERE id=%s',(contract['event_id'],)).fetchone()['facts']
                    event['title']=str(event.get('title',''))+' revised'
                    db.execute('UPDATE current_event SET facts=%s,revision=%s WHERE id=%s',(Jsonb(event),hashed(event),contract['event_id']))
                elif kind=='offer_membership':
                    db.execute('DELETE FROM current_offer WHERE contract_id=%s',(contract['id'],))
                else:
                    opts=dict(live.current_settings(db),amount='1234')
                    opts.pop('revision',None)
                    from app.storage.comparison_policy import activate
                    activate(db, opts, expected=live.current_settings(db)['revision'])
                turn=live.turn(db)
                traced=[c for c in turn.get('component_trace',[]) if c['price_capture'].get('fallback')==kind]
                self.assertTrue(traced,kind)
                for c in traced:
                    self.assertTrue(c['member_costs']['input_decode_skipped'])
                    saved=db.execute("SELECT s.inputs,r.result FROM comparison_publication c JOIN comparison_snapshot_result r ON r.id=c.result_id JOIN comparison_snapshot s ON s.id=r.snapshot_id WHERE c.kind='component' AND c.id=%s",(c['component'],)).fetchone()
                    actual=snapshots.unpack(saved['inputs'])
                    self.assertEqual(len(c['event_ids']),c['event_count'])
                    complete=snapshots.capture(db,ordinary=True,event_ids=c['event_ids'],at=actual['captured_at'])
                    self.assertEqual({k:v for k,v in actual.items() if k not in ignored},{k:v for k,v in complete.items() if k not in ignored})
                    money=snapshots.unpack(saved['result']);complete.update(id=actual['id'],capture_seconds=actual['capture_seconds'])
                    with patch.object(snapshots,'utc',return_value=money['calculated_at']):
                        expected=live.bind(snapshots.calculate(complete,money['assumptions'],product=True),complete,'ready')
                    expected['id']=money['id']
                    self.assertEqual(money,expected)
                self.assertEqual(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',(original,)).fetchone()['result'],pinned)
            db.execute("DELETE FROM comparison_result_reference WHERE kind='lease' AND holder=%s",(lease['lease_id'],))
