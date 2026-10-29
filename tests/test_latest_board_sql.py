"""Bounded latest-board proof on explicitly disposable SQL; zero providers.

Original retained quote/contract facts exercise the real financial owners. Price
and status mutations below are authored fixture evidence, never live authority.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import os
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch, MagicMock

import psycopg
from psycopg import sql
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.collection.current_policy import DEFAULT
from app.collection.runtime_status import read_runtime
from app.collection.runtime_client import RuntimeClient
from app.storage.store import stamp
from app.storage.current_rows import CurrentRowStore, LOCK
from app.storage import latest_board as latest
from app.storage.comparison_board import discover, calculate_current, context_identity
from app.dashboard.comparison_board import response, entries
from app.comparison.estimated_policy import DEFAULT_POLICY
from tests.test_ev09_n01 import retained

from tests.latest_board_fixture import (
    LatestBoardFixture, SOCKET as SOCKET, two_games as two_games, native_key as native_key,
)


def decoded_board(*args,**kwargs):
    from app.dashboard.comparison_board import expand_price_fields
    return expand_price_fields(latest.board(*args,**kwargs))


@skipUnless(SOCKET,'Explicit maintained disposable DA PostgreSQL lane required')
class LatestBoardSQL(LatestBoardFixture):
    async def test_generated_publication_accounting_tracks_every_fact_update(self):
        from psycopg.types.json import Jsonb
        self.reconcile()
        with self.connect() as db:
            def check():
                rows=db.execute("""SELECT retained_bytes=octet_length(facts::text) bytes_exact,
                    publication_events IS NOT DISTINCT FROM facts#>'{publication_dependencies,selector,events}' events_exact,
                    observation_as_of IS NOT DISTINCT FROM facts#>>'{boards,odds,as_of}' clock_exact
                    FROM latest_board""").fetchall()
                self.assertTrue(rows)
                self.assertTrue(all(all(r.values()) for r in rows))
            check()
            db.execute("UPDATE latest_board SET facts=facts || %s",(Jsonb(dict(authored_extra='x'*10000)),))
            check()

    async def test_scoped_marker_ignores_other_prices_but_detects_membership(self):
        from app.storage.store import hashed
        scope=[hashed(member) for member in self.first['members']]
        with self.connect() as db:
            before=latest.marker(db,scope);whole=latest.marker(db)
            other=db.execute('SELECT o.contract_id FROM current_offer o JOIN current_contract c ON c.id=o.contract_id WHERE NOT(c.event_id=ANY(%s)) LIMIT 1',(scope,)).fetchone()
            self.assertIsNotNone(other)
            db.execute("UPDATE current_offer SET revision='authored-unrelated-update' WHERE contract_id=%s",(other['contract_id'],))
            self.assertEqual(latest.marker(db,scope),before)
            self.assertNotEqual(latest.marker(db),whole)
            db.execute('DELETE FROM current_offer USING current_contract c WHERE current_offer.contract_id=c.id AND NOT(c.event_id=ANY(%s))',(scope,))
            self.assertNotEqual(latest.marker(db,scope),before)

    async def test_comparison_enrichment_preserves_native_image_and_real_material_withdraws(self):
        from datetime import datetime,timezone
        self.at=datetime.now(timezone.utc)
        self.state.write(self.service)
        from app.collection.current_database import DatabaseIngressSink
        from app.dashboard.current_state import unavailable
        from tests.multisport_fixtures import source_case, fake_discovery, current_book
        from tests.test_current_multisport_ingress import worker
        from app.collection.v1_comparison import annotate
        case=source_case('NFL','moneyline','native-enrichment-continuity',clock=self.at)
        event=case['events']['polymarket_us'];event.pop('season');event.pop('stage')
        w,published=worker('polymarket_us',['NFL'],['moneyline'])
        fake_discovery(w,[case]);await w.discover()
        cat=published[-1];book=current_book(case,'polymarket_us',clock=self.at)
        store=SimpleNamespace(_state=unavailable())
        store.commit=lambda value:setattr(store,'_state',value)
        sink=DatabaseIngressSink(store,deepcopy(DEFAULT))
        states=dict(polymarket_us=dict(state='available'))
        def catalog(value):
            sink.commit(dict(type='coverage_inventory',source='polymarket_us',observed_at=self.at.isoformat(),
                inventory={'polymarket_us':value},generation=(sink.reducer.generation or 0)+1,
                previous_generation=sink.reducer.generation),states)
        with patch('app.collection.current_database.connect',side_effect=self.connect):
            catalog(cat)
            sink.commit(dict(type='prediction_book',source='polymarket_us',observed_at=self.at.isoformat(),book=book),states)
            key=('polymarket_us',event['id'],case['markets']['polymarket_us']['id'])
            before=deepcopy(sink.reducer.books[key]);old_membership=sink.reducer.memberships()[key]
            enriched=deepcopy(cat)
            enriched['events'][0].update(season='2026',stage='regular_season')
            annotate(enriched,'polymarket_us',policy='manual-comparison-2')
            catalog(enriched)
            self.assertNotEqual(sink.reducer.memberships()[key],old_membership)
            self.assertEqual(sink.reducer.books[key],before)
            with self.connect() as db:
                rows=db.execute('''SELECT o.source_at,o.received_at,o.facts FROM current_offer o
                    JOIN current_contract c ON c.id=o.contract_id WHERE c.native_market_id=%s''',(key[2],)).fetchall()
            self.assertEqual(len(rows),2)
            for row in rows:
                self.assertEqual(row['source_at'],book['raw']['exchange_at'])
                self.assertEqual(row['received_at'],book['raw']['received_at'])
            changed=deepcopy(enriched)
            changed['markets'][0]['terms']['description']+=' Changed actual source wording.'
            catalog(changed)
            self.assertNotIn(key,sink.reducer.books)
            with self.connect() as db:
                self.assertFalse(db.execute('SELECT 1 FROM current_native_book WHERE native_market_id=%s',(key[2],)).fetchone())

    async def test_busy_publication_defers_heartbeat_without_clearing_controls(self):
        import asyncio
        value=self.state.snapshot(self.service)
        with self.connect() as holder,holder.transaction():
            holder.execute('SELECT singleton FROM data_runtime FOR SHARE')
            # Real PostgreSQL lock conflict; the runtime remains alive and the
            # ordinary next heartbeat can succeed after the publisher releases.
            self.assertFalse(await asyncio.to_thread(self.state.write_snapshot,value,heartbeat=True))
        self.assertTrue(await asyncio.to_thread(self.state.write_snapshot,value,heartbeat=True))
        for update in ("global_stopped=true", "paused_sources='[\"kalshi\"]'::jsonb", "state='stopping'", "runtime_id='replacement-owner'"):
            with self.subTest(update=update),self.connect() as db:
                self.state.write(self.service)
                db.execute('UPDATE data_runtime SET '+update)
                before=db.execute('SELECT * FROM data_runtime').fetchone()
                self.assertFalse(await asyncio.to_thread(self.state.write_snapshot,value,heartbeat=True))
                self.assertEqual(db.execute('SELECT * FROM data_runtime').fetchone(),before)




    async def test_refused_wide_spread_sql_projection_and_complete_read_boundary(self):
        import gzip,json
        from pathlib import Path
        from psycopg.types.json import Jsonb
        from app.dashboard.comparison_board import compact_price_fields, expand_price_fields
        from app.storage.coverage_latest import _PUBLICATION_SQL
        from app.storage.store import encoded
        old=json.loads(gzip.decompress(Path('tests/fixtures/wide-spread-board-20261022.json.gz').read_bytes()))
        self.reconcile()
        with self.connect() as db:
            key=db.execute('SELECT game_key FROM latest_board ORDER BY game_key LIMIT 1').fetchone()['game_key']
            def project(board):
                db.execute("UPDATE latest_board SET facts=jsonb_set(facts,'{boards,odds}',%s) WHERE game_key=%s",(Jsonb(board),key))
                return db.execute(_PUBLICATION_SQL+' ORDER BY game_key').fetchall()
            before=project(old)
            wire=compact_price_fields(deepcopy(old))
            self.assertIn('price_object_keys',wire)
            self.assertEqual(project(wire),before)
            for malformed in (['duplicate','duplicate'],['__proto__'],[True],None,{}):
                bad=deepcopy(wire);bad['price_object_keys']=malformed
                with self.assertRaises(psycopg.Error),db.transaction():project(bad)
        # Exercise the actual complete read constructor, including read metadata
        # and source aging; the retained game is a disposable frame here.
        frame=dict(status=dict(games=[]),rows={},at=old['read_at'],reasons=[],owner=dict(states={}))
        frame['rows'][old['game_key']]=dict(facts=dict(boards=dict(odds=wire)),economic_revision='retained-test',calculated_at=None)
        result=latest.board(deepcopy(frame),old['game_key'],view='odds',filter='all')
        size=len(encoded(result));self.assertLess(size,524288)
        self.assertEqual(len(expand_price_fields(deepcopy(result))['prices']),114)
        with patch('app.storage.board_view.MAX_RESPONSE',size):
            self.assertEqual(latest.board(deepcopy(frame),old['game_key'],view='odds',filter='all'),result)
        with patch('app.storage.board_view.MAX_RESPONSE',size-1):
            with self.assertRaisesRegex(ValueError,'board_compact_response_capacity'):
                latest.board(deepcopy(frame),old['game_key'],view='odds',filter='all')

    async def test_selected_view_admission_measures_actual_projection(self):
        self.reconcile()
        def reservation(view):
            calls = []
            with self.connect() as db:
                latest.snapshot(db, at=self.at.isoformat(), view=view, resource_guard=calls.append)
            return calls[0]
        before = {view:reservation(view) for view in (None, 'ev', 'arbs')}
        # Grow only an unselected view. It must not consume EV/Arbs admission,
        # while a full capture still charges every byte at the unchanged 8x rate.
        with self.connect() as db:
            db.execute("UPDATE latest_board SET facts=jsonb_set(facts,'{boards,odds,authored_padding}',to_jsonb(%s::text))", ('x'*65536,))
        after = {view:reservation(view) for view in (None, 'ev', 'arbs')}
        self.assertGreater(after[None],before[None]+65536*8)
        self.assertEqual(after['ev'],before['ev'])
        self.assertEqual(after['arbs'],before['arbs'])
        self.assertLess(after['ev'],after[None])

    async def test_streamed_slate_proof_retains_all_selection_and_dependency_checks(self):
        from app.storage import observation_publication as publication
        from app.storage.store import encoded
        self.reconcile();rows=self.rows();reservations=[]
        with self.connect() as db,db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            full=publication.capture(db,{})
            compact=publication.capture(db,{},compact=True,resource_guard=reservations.append)
        self.assertEqual(set(full['offers']),set(compact['offers']))
        self.assertTrue(reservations)
        for cid,row in full['offers'].items():
            self.assertEqual(publication.own(full,cid),publication.own(compact,cid))
            self.assertEqual(publication.selection(full,row),publication.selection(compact,compact['offers'][cid]))
            self.assertEqual(compact['offers'][cid]['contract'],{})
        for row in rows.values():
            saved=row['facts']['publication_dependencies']
            self.assertEqual(publication.reasons(full,saved),publication.reasons(compact,saved))
        self.assertLess(len(encoded(dict(offers=compact['offers'],selections=compact['selection_identities']))),
            len(encoded(dict(offers=full['offers'],selections=full['selection_identities']))))

    async def test_selected_admission_excludes_unrelated_contracts_but_keeps_peers(self):
        from app.storage import observation_publication as publication
        self.reconcile();rows=self.rows();game=next(iter(rows))
        selector=rows[game]['facts']['publication_dependencies']['selector']
        with self.connect() as db:
            ids=[r[0] for r in publication.neighborhood(publication.identity_index(db),selector)]
        def capture(selected):
            calls=[]
            with self.connect() as db:
                value=latest.snapshot(db,at=self.at.isoformat(),game=selected,resource_guard=calls.append)
            return max(calls),value
        before,value=capture(game);whole,_=capture(None)
        with self.connect() as db:
            changed=db.execute("UPDATE current_contract SET facts=jsonb_set(facts,'{authored_padding}',to_jsonb(%s::text)) WHERE NOT event_id=ANY(%s)",('x'*65536,ids)).rowcount
        self.assertGreater(changed,0)
        after,result=capture(game);grown,_=capture(None)
        self.assertEqual(before,after)
        self.assertGreater(grown,whole)
        self.assertEqual(result['rows'],value['rows'])
        self.assertEqual(result['dependency_reasons'],value['dependency_reasons'])
        with self.connect() as db:
            db.execute("UPDATE current_contract SET facts=jsonb_set(facts,'{authored_padding}',to_jsonb(%s::text)) WHERE event_id=ANY(%s)",('x'*65536,ids))
        peer_growth,_=capture(game)
        self.assertGreater(peer_growth,after)

    async def test_partial_rejection_cannot_restore_a_retired_catalog_row(self):
        from psycopg.types.json import Jsonb
        self.reconcile();rows=self.rows()
        with self.connect() as db:
            status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
            captured_marker=latest.marker(db);owner=latest.runtime(db)
            obsolete=deepcopy(next(g for g in status['games'] if g['game_key']==self.second['game_key']))
            obsolete['game_key']='combined:event:authored-retired-occurrence'
            prior=deepcopy(status);prior['games'].append(obsolete)
            db.execute('UPDATE latest_board_status SET facts=%s',(Jsonb(prior),))
            db.execute('INSERT INTO latest_board SELECT %s,dependency_revision,economic_revision,calculated_at,facts FROM latest_board WHERE game_key=%s',
                (obsolete['game_key'],self.second['game_key']))
        self.changed_first()
        with self.connect() as db:
            self.assertFalse(latest.publish(db,captured_marker=captured_marker,captured_runtime=owner,status=status,rows=list(rows.values())))
            keys={r['game_key'] for r in db.execute('SELECT game_key FROM latest_board').fetchall()}
            catalog={g['game_key'] for g in db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']['games']}
        self.assertNotIn(obsolete['game_key'],keys)
        self.assertNotIn(obsolete['game_key'],catalog)
        self.assertEqual(catalog,keys)






    async def test_changed_game_does_not_renormalize_stable_evaluated_neighbor(self):
        self.fresh_sources();self.reconcile()
        stable=self.rows()[self.second['game_key']]
        self.changed_first()
        with patch.object(latest,'discover',wraps=latest.discover) as prepare:
            result=self.reconcile()
        self.assertGreaterEqual(result['reused'],1)
        self.assertNotIn(self.second['game_key'],[call.kwargs.get('game') for call in prepare.call_args_list])
        self.assertEqual(self.rows()[self.second['game_key']]['calculated_at'],stable['calculated_at'])
        self.assertEqual(self.rows()[self.second['game_key']]['facts']['context'],stable['facts']['context'])

    async def test_source_pass_with_new_policy_cannot_reuse_old_game_estimate(self):
        self.fresh_sources();self.reconcile()
        alternate=replace(DEFAULT_POLICY,buffer_rate='0.01')
        with patch.object(latest,'load',return_value=alternate):
            with self.connect() as db:
                latest.reconcile(db,at=self.at.isoformat(),observations_only=True)
            self.reconcile()
        self.assertTrue(all(row['facts']['context']['policy_revision']==alternate.revision
                            for row in self.rows().values()))




    async def test_optional_calculation_stage_failures_publish_source_frames(self):
        self.fresh_sources()
        for stage in ('discover','context_identity','calculate_current'):
            with self.subTest(stage=stage):
                with self.connect() as db:db.execute('TRUNCATE latest_board,latest_board_status')
                with patch.object(latest,stage,side_effect=ValueError('authored_optional_calculation_failure')):
                    result=self.reconcile()
                self.assertTrue(result['published'],result)
                self.assertEqual(set(self.rows()),{self.first['game_key'],self.second['game_key']})
                for game,row in self.rows().items():
                    self.assertIsNone(row['calculated_at'])
                    self.assertIsNone(row['facts']['context'])
                    self.assertEqual(row['facts']['estimate_availability']['state'],'unavailable')
                    self.assertTrue(row['facts']['estimate_availability']['reason_codes'])
                    odds=decoded_board(self.snapshot(),game,view='odds',filter='all')
                    self.assert_source_frame(odds)
                    self.assertEqual([row['price_ref'] for row in odds['rows']],[row['quote_id'] for row in odds['prices']])
                    self.assertTrue(all(q.get('observed_depth') is not None for q in odds['prices']))
                    ev=decoded_board(self.snapshot(),game,view='ev',filter='all')
                    self.assert_source_frame(ev)
                    self.assertFalse(any(r.get('ranking_eligible') for r in ev['rows']))

    async def test_absent_and_malformed_optional_benchmark_leave_source_prices(self):
        # Delete only optional benchmark fixtures, leaving exact execution data.
        with self.connect() as db:
            db.execute("DELETE FROM current_contract WHERE venue='pinnacle'")
        self.fresh_sources([r for r in self.records if r['quote']['venue']!='pinnacle'])
        self.assertTrue(self.reconcile()['published'])
        for game in self.rows():
            odds=decoded_board(self.snapshot(),game,view='odds',filter='all')
            self.assert_source_frame(odds)
            self.assertFalse(odds['benchmark']['available'])
        # A malformed optional producer output cannot become a source-fact gate.
        with self.connect() as db:db.execute('TRUNCATE latest_board,latest_board_status')
        with patch('app.comparison.combined_inputs._benchmark',return_value=({'authored_malformed':True},None)):
            self.assertTrue(self.reconcile()['published'])
        for game in self.rows():
            odds=decoded_board(self.snapshot(),game,view='odds',filter='all')
            self.assert_source_frame(odds)
            self.assertFalse(odds['benchmark']['available'])
            self.assertTrue(odds['benchmark']['reason'])

    async def test_missing_or_expired_optional_fee_preserves_source_facts(self):
        from app.comparison.current_dependencies import digest
        self.fresh_sources();real_discover=latest.discover
        for mode in ('missing','expired'):
            with self.subTest(mode=mode):
                with self.connect() as db:db.execute('TRUNCATE latest_board,latest_board_status')
                def decorated(*args,**kwargs):
                    bundles=real_discover(*args,**kwargs)
                    for bundle in bundles:
                        for _,_,q in entries(bundle['state_inputs']):
                            fee=q['comparison_input_status']['fee']
                            if mode=='missing':
                                q['comparison_input_refs']['refs']['fee']=None
                                fee.clear();fee.update(status='absent',reason='fee_inputs_absent')
                            else:
                                recipe=fee.get('estimate_content')
                                if recipe:
                                    recipe['expires_at']=(self.at-timedelta(seconds=1)).isoformat()
                                    recipe['id']=digest({k:v for k,v in recipe.items() if k!='id'})
                    return bundles
                with patch.object(latest,'discover',side_effect=decorated):
                    self.assertTrue(self.reconcile()['published'])
                for game in self.rows():
                    odds=decoded_board(self.snapshot(),game,view='odds',filter='all')
                    self.assert_source_frame(odds)
                    ev=decoded_board(self.snapshot(),game,view='ev',filter='all')
                    self.assert_source_frame(ev)
                    self.assertEqual(ev['availability']['numeric_results'],0,ev['availability'])
                    self.assertFalse(any(r.get('ranking_eligible') for r in ev['rows']))
                    self.assertTrue(ev['rows'] or ev['estimate_availability']['reason_codes'])

    async def test_policy_worker_and_estimate_deadlines_do_not_age_source(self):
        self.fresh_sources();self.reconcile();key=self.first['game_key']
        original=decoded_board(self.snapshot(),key,view='odds',filter='all')['prices']
        alternate=replace(DEFAULT_POLICY,buffer_rate='0.01')
        with patch.object(latest,'load',return_value=alternate):
            frame=self.snapshot();self.assertIn('policy_changed',frame['calculation_reasons'])
            odds=decoded_board(frame,key,view='odds',filter='all')
            self.assert_source_frame(odds)
            self.assertEqual(odds['prices'],original)
            self.assertNotIn('policy_changed',odds.get('observation_reasons',[]))
        self.service.background_calculations=dict(board='unavailable');self.state.write(self.service)
        frame=self.snapshot();self.assertIn('background_calculations_unavailable',frame['calculation_reasons'])
        self.assert_source_frame(decoded_board(frame,key,view='odds',filter='all'))
        self.service.background_calculations=dict(board='running');self.state.write(self.service)
        with self.connect() as db:
            db.execute("UPDATE latest_board SET facts=jsonb_set(facts,'{valid_until}',to_jsonb(%s::text)) WHERE game_key=%s",
                ((self.at+timedelta(seconds=1)).isoformat(),key))
        self.at+=timedelta(seconds=2);self.state.write(self.service)
        frame=self.snapshot();odds=decoded_board(frame,key,view='odds',filter='all');ev=decoded_board(frame,key,view='ev',filter='all')
        self.assert_source_frame(odds)
        # Read-relative age metadata advances; captured source facts do not.
        self.assertEqual([(q['original'],q['times'],q['observation_revision']) for q in odds['prices']],
            [(q['original'],q['times'],q['observation_revision']) for q in original])
        self.assertIn('calculation_authority_boundary',ev['background_reasons'])
        self.assertFalse(any(r.get('ranking_eligible') for r in ev['rows']))
        self.at+=timedelta(minutes=31);self.state.write(self.service)
        stale=decoded_board(self.snapshot(),key,view='odds',filter='all')
        self.assert_source_frame(stale,current=False)
        self.assertTrue(all(q['freshness']['status']=='historical' for q in stale['prices']))
        self.assertEqual([q['times'] for q in stale['prices']],[q['times'] for q in original])

    async def test_read_ages_captured_peer_and_separates_pending_without_dispatch(self):
        # Author one compatible sportsbook peer with a finite source lifetime;
        # retained native tie payouts are a different outcome identity.
        records=deepcopy(self.records)
        for record in records:
            if record['quote']['venue']=='prophetx':record['quote']['freshness_policy']=dict(version='predict-source-freshness-1',maximum_age_seconds=30)
        self.fresh_sources(records);self.reconcile();key=self.first['game_key']
        original=decoded_board(self.snapshot(),key,view='odds',filter='all')
        def selected(board):
            from app.dashboard.comparison_board import expand_odds
            expand_odds(board)
            return next(q for q in board['prices'] if q['venue']=='novig' and q['gross_comparison']['available']
                and q['gross_comparison']['comparison_venue']=='prophetx')
        before=selected(original);captured=deepcopy(before['gross_comparison'])
        self.assertEqual(captured['display_status'],'current')
        self.changed_first()
        pending=selected(decoded_board(self.snapshot(),key,view='odds',filter='all'))
        self.assertEqual(pending['observation_display']['state'],'pending')
        self.assertEqual(pending['gross_comparison']['display_status'],'pending')
        self.assertNotIn('source_expired',pending['freshness']['reasons'])
        self.at+=timedelta(seconds=31);self.state.write(self.service)
        with patch.object(latest,'calculate_current',side_effect=AssertionError('read cannot calculate')), \
             patch.object(latest,'read_context',side_effect=AssertionError('read cannot capture new peer prices')):
            read=decoded_board(self.snapshot(),key,view='odds',filter='all');aged=selected(read)
        gross=aged['gross_comparison'];self.assertEqual(gross['display_status'],'last_known')
        self.assertEqual(gross['exact'],captured['exact']);self.assertEqual(gross['comparison_quote_id'],captured['comparison_quote_id'])
        self.assertEqual([(q['original'],q['times']) for q in gross['inputs']],[(q['original'],q['times']) for q in captured['inputs']])
        peer=gross['inputs'][1]['observation_display']
        self.assertIn('source_expired',peer['source_reason_codes']);self.assertIn('current_dependencies_changed',peer['publication_reason_codes'])
        self.assertEqual([(q['original'],q['times']) for q in original['prices']],
            [(q['original'],q['times']) for q in self.rows()[key]['facts']['boards']['odds']['prices']])
        self.assertEqual(read['provider_requests'],0)

    async def test_source_failure_and_stop_keep_last_known_original_clocks(self):
        self.fresh_sources();self.reconcile();key=self.first['game_key']
        before=decoded_board(self.snapshot(),key,view='odds',filter='all')
        clocks={native_key(q):q['times'] for q in before['prices']}
        self.service.states['kalshi']=dict(state='unavailable',reason_code='fixture_source_failure')
        self.state.write(self.service);self.reconcile()
        unhealthy=decoded_board(self.snapshot(),key,view='odds',filter='all')
        self.assert_source_frame(unhealthy,current=False)
        for q in unhealthy['prices']:
            self.assertEqual(q['times'],clocks[native_key(q)])
            self.assertEqual(q['freshness']['status'],'historical' if q['venue']=='kalshi' else 'current')
            if q['venue']=='kalshi':self.assertIn('source_unavailable',q['freshness']['reasons'])
        self.service.dispatch=False;self.state.write(self.service);self.reconcile()
        stopped=decoded_board(self.snapshot(),key,view='odds',filter='all')
        self.assert_source_frame(stopped,current=False)
        self.assertIn('updates_stopped',stopped['observation_reasons'])
        self.assertTrue(all(q['freshness']['status']=='historical' for q in stopped['prices']))
        self.assertEqual({native_key(q):q['times'] for q in stopped['prices']},clocks)

    async def test_committed_source_failure_beats_delayed_available_heartbeat(self):
        self.fresh_sources();self.reconcile();key=self.first['game_key']
        before=decoded_board(self.snapshot(),key,view='odds',filter='all')
        originals={native_key(q):(q['original'],q['times']) for q in before['prices']}
        failure=dict(state='unavailable',reason_code='fixture_committed_source_failure',
            reason='Fixture ingress failure committed before the next runtime heartbeat.')
        with self.connect() as db:
            CurrentRowStore(db).upsert_records([],now=self.at.isoformat(),source_status=dict(kalshi=failure))
        # Leave the persisted heartbeat available to reproduce the actual race.
        self.assertEqual(self.state.read()['states']['kalshi']['state'],'available')
        immediate=decoded_board(self.snapshot(),key,view='odds',filter='all')
        self.assertIn('current_dependencies_changed',immediate['observation_reasons'])
        def check(value):
            self.assert_source_frame(value,current=False)
            self.assertTrue(value['collection']['healthy']);self.assertTrue(value['collection']['active'])
            self.assertFalse(value['collection']['stopped'])
            self.assertEqual(value['collection']['sources']['kalshi'],failure)
            for q in value['prices']:
                self.assertEqual((q['original'],q['times']),originals[native_key(q)])
                if q['venue']=='kalshi':
                    self.assertEqual(q['source_state'],'unavailable')
                    self.assertEqual(q['source_health'],failure)
                    self.assertEqual(q['freshness']['status'],'historical')
                    self.assertIn('source_unavailable',q['freshness']['reasons'])
                else:self.assertEqual(q['source_state'],'available')
        check(immediate)
        self.assertTrue(self.reconcile()['published'])
        after=decoded_board(self.snapshot(),key,view='odds',filter='all');check(after)
        self.assertNotIn('current_dependencies_changed',after['observation_reasons'])
        self.assertTrue(all(q['freshness']['status']=='current' for q in after['prices'] if q['venue']!='kalshi'))
        self.assertEqual(self.state.read()['states']['kalshi']['state'],'available')

    async def test_sql_only_publication_affected_reuse_restart_and_authoritative_economics(self):
        result=self.reconcile();self.assertTrue(result['published'],result);self.assertEqual(result['computed'],2)
        before=self.rows();self.assertEqual(len(before),2)
        from app.dashboard.comparison_board import expand_financial
        first=expand_financial(deepcopy(before[self.first['game_key']]['facts']['boards']['ev']))
        original={native_key(q):q for _,_,q in entries(retained()[1])}
        self.assertEqual({native_key(q) for q in first['rows']},set(original))
        for row in first['rows']:
            expected=original[native_key(row)]['calculations']['funded_estimate']
            for key,value in expected['financial_metrics'].items():self.assertEqual(row['financial_metrics'][key],value)
            self.assertEqual(row['funding'],expected['funding'])
        self.changed_first();result=self.reconcile();self.assertTrue(result['published'],result)
        self.assertEqual(result['computed'],1);self.assertEqual(result['reused'],1)
        after=self.rows();a=self.first['game_key'];b=self.second['game_key']
        self.assertNotEqual(before[a]['economic_revision'],after[a]['economic_revision'])
        self.assertNotEqual(before[a]['calculated_at'],after[a]['calculated_at'])
        self.assertEqual(before[b],after[b])
        with self.connect() as db:
            c=latest.read_context(db,at=self.at.isoformat());bundle=discover(c.store,context=c,game=a)[0]
        bundle['calculation_context']=context_identity(bundle,DEFAULT_POLICY,c)
        expected=response(bundle,calculate_current(bundle,DEFAULT_POLICY,context=c),DEFAULT_POLICY,view='ev',filter='all',at=self.at.isoformat())
        from app.dashboard.comparison_board import expand_price_fields
        self.assertEqual(after[a]['facts']['boards']['ev']['rows'],expand_price_fields(expected)['rows'])
        # A new owner reconciles current SQL without invoking any financial owner.
        with patch.object(latest,'calculate_current',side_effect=AssertionError('unchanged finance forbidden')):
            for _ in range(3):self.assertTrue(self.reconcile()['unchanged'])
        self.assertEqual(self.rows(),after)
        with self.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM latest_board_status').fetchone()['n'],1)
            for table in ('current_envelope','current_game_snapshot','current_game_result','current_calculation_attempt'):
                self.assertEqual(db.execute(sql.SQL('SELECT count(*) n FROM {}').format(sql.Identifier(table))).fetchone()['n'],0)

    async def test_temporal_only_expiry_stop_failure_and_no_ready_revival(self):
        self.assertTrue(self.reconcile()['published']);before=self.rows()
        self.assertTrue(any(r['ranking_eligible'] for r in before[self.first['game_key']]['facts']['boards']['ev']['rows']))
        self.at+=timedelta(minutes=31);self.state.write(self.service)
        expired=decoded_board(self.snapshot(),self.first['game_key'],view='ev',filter='all')
        self.assertIn('calculation_authority_boundary',expired['background_reasons'])
        self.assertTrue(all(not r['ranking_eligible'] for r in expired['rows']))
        self.assertTrue(self.reconcile()['published']);self.assertNotEqual(self.rows()[self.first['game_key']]['economic_revision'],before[self.first['game_key']]['economic_revision'])
        self.service.dispatch=False;self.state.write(self.service)
        for _ in range(2):
            self.reconcile();value=decoded_board(self.snapshot(),self.first['game_key'],view='ev',filter='all')
            self.assertIn('updates_stopped',value['background_reasons'])
            self.assertTrue(all(not r['ranking_eligible'] for r in value['rows']))
        self.service.dispatch=True;self.service.background_calculations=dict(board='unavailable');self.state.write(self.service)
        self.reconcile();value=decoded_board(self.snapshot(),self.first['game_key'],view='ev',filter='all')
        self.assertIn('background_calculations_unavailable',value['background_reasons'])
        self.assertTrue(all(not r['ranking_eligible'] for r in value['rows']))
        self.service.background_calculations=dict(board='running');self.state.write(self.service);self.reconcile()
        self.at+=timedelta(seconds=9)
        value=decoded_board(self.snapshot(),self.first['game_key'],view='ev',filter='all')
        self.assertIn('data_runtime_unhealthy',value['background_reasons'])
        self.assertTrue(all(not r['ranking_eligible'] for r in value['rows']))

    async def test_policy_engine_epoch_change_and_removal_withdraw_without_quotes(self):
        self.reconcile();before=self.rows()
        alternate=replace(DEFAULT_POLICY,buffer_rate='0.01')
        with patch.object(latest,'load',return_value=alternate):
            self.assertIn('policy_changed',self.snapshot()['reasons'])
            self.assertTrue(self.reconcile()['published'])
            self.assertTrue(all(r['facts']['boards']['ev']['policy']['revision']==alternate.revision for r in self.rows().values()))
        with patch.object(latest,'engine_binding',return_value='authored-engine-change'),patch('app.storage.comparison_board.engine_binding',return_value='authored-engine-change'):
            self.assertIn('engine_binding_changed',self.snapshot()['reasons'])
            self.assertTrue(self.reconcile()['published'])
        self.reconcile()
        with self.connect() as db:
            with db.transaction():
                db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
                db.execute('UPDATE current_row_epoch SET epoch=%s WHERE singleton=true',('authored-new-epoch',))
        self.assertIn('current_dependencies_changed',self.snapshot()['reasons']);self.reconcile()
        self.assertTrue(all(r['facts']['context']['epoch']=='authored-new-epoch' for r in self.rows().values()))
        preserved=self.rows()[self.second['game_key']]
        with self.connect() as db:
            with db.transaction():
                db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
                db.execute('DELETE FROM current_event WHERE native_event_id=ANY(%s)',([m[1] for m in self.first['members']],))
        frame=self.snapshot();self.assertIn('current_dependencies_changed',frame['reasons'])
        withdrawn=decoded_board(frame,self.first['game_key'],view='ev',filter='all')
        self.assertTrue(all(not r['ranking_eligible'] for r in withdrawn['rows']))
        self.reconcile();self.assertEqual(set(self.rows()),{self.second['game_key']})
        self.assertEqual(self.rows()[self.second['game_key']],preserved)
        self.assertNotEqual(before[self.second['game_key']]['facts']['context']['epoch'],preserved['facts']['context']['epoch'])

    async def test_model_expiry_without_new_quote_withdraws_and_recomputes(self):
        # Authored clock mutation crosses the real retained model end date;
        # production model dates and definitions remain untouched.
        self.at=stamp('2026-10-16T03:59:59Z');self.state.write(self.service)
        records=deepcopy([r for r in self.records if [r['quote']['source']['provider'],r['quote']['source']['native_event_id']] in self.second['members']])
        for record in records:
            record['quote']['times'].update(source_at=self.at.isoformat(),received_at=self.at.isoformat())
            record['quote']['provider_clocks'].update(book=self.at.isoformat(),market=self.at.isoformat())
        self.admit(records);self.assertTrue(self.reconcile()['published'])
        before=self.rows()[self.second['game_key']]
        self.assertGreater(before['facts']['boards']['ev']['availability']['numeric_results'],0)
        with self.connect() as db:proof=latest.marker(db)
        self.at+=timedelta(seconds=2);self.state.write(self.service)
        frame=self.snapshot()
        self.assertIn('calculation_authority_boundary',decoded_board(frame,self.second['game_key'],view='ev',filter='all')['background_reasons'])
        with self.connect() as db:self.assertEqual(latest.marker(db),proof)
        self.assertTrue(self.reconcile()['published'])
        after=self.rows()[self.second['game_key']]
        self.assertNotEqual(after['economic_revision'],before['economic_revision'])
        self.assertEqual(after['facts']['boards']['ev']['availability']['numeric_results'],0)
        self.assertTrue(all(not row['ranking_eligible'] for row in after['facts']['boards']['ev']['rows']))

    async def test_conservative_boundary_refresh_keeps_original_economics(self):
        self.reconcile();before=self.rows();key=self.first['game_key']
        # Authored conservative deadline models a selected schedule boundary
        # whose passage does not change this row's economic applicability.
        with self.connect() as db:
            db.execute("UPDATE latest_board SET facts=jsonb_set(facts,'{valid_until}',to_jsonb(%s::text)) WHERE game_key=%s",
                ((self.at+timedelta(seconds=1)).isoformat(),key))
        self.at+=timedelta(seconds=2);self.state.write(self.service)
        self.assertIn('calculation_authority_boundary',decoded_board(self.snapshot(),key,view='ev',filter='all')['background_reasons'])
        with patch.object(latest,'calculate_current',side_effect=AssertionError('unchanged financial work forbidden')):
            result=self.reconcile()
        self.assertTrue(result['published']);self.assertEqual(result['computed'],0)
        after=self.rows()[key]
        self.assertEqual(after['economic_revision'],before[key]['economic_revision'])
        self.assertEqual(after['calculated_at'],before[key]['calculated_at'])
        self.assertGreater(stamp(after['facts']['valid_until']),self.at)
        self.assertNotIn('calculation_authority_boundary',decoded_board(self.snapshot(),key,view='ev',filter='all')['background_reasons'])

    async def test_superseded_and_stopped_work_cannot_publish(self):
        self.reconcile();old=self.rows()
        with self.connect() as db:
            proof=latest.marker(db);runtime=read_runtime(db);status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
        self.changed_first()
        with self.connect() as db:
            self.assertFalse(latest.publish(db,captured_marker=proof,captured_runtime=runtime,status=status,rows=deepcopy(list(old.values()))))
        self.assertEqual(self.rows(),old)
        self.reconcile();old=self.rows()
        with self.connect() as db:
            proof=latest.marker(db);runtime=read_runtime(db);status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
        self.service.dispatch=False;self.state.write(self.service)
        with self.connect() as db:
            self.assertFalse(latest.publish(db,captured_marker=proof,captured_runtime=runtime,status=status,rows=deepcopy(list(old.values()))))
        self.assertEqual(self.rows(),old)

    async def test_price_change_during_new_calculation_retains_only_captured_finance(self):
        from app.storage import selected_frame
        original=latest.calculate_current
        captured={}
        def changing(bundle,*args,**kwargs):
            value=original(bundle,*args,**kwargs)
            if bundle['game_key']==self.first['game_key']:
                captured['bundle']=deepcopy(bundle)
                self.changed_first()
            return value
        with patch.object(latest,'calculate_current',side_effect=changing):
            self.reconcile()
        saved=self.rows()[self.first['game_key']]
        self.assertTrue(saved['facts']['retained_financial_only'])
        frame=self.snapshot()
        # Even if a later read has no local differences, retained-only finance
        # must not silently become a current opportunity.
        frame['dependency_reasons'][self.first['game_key']]=dict(all=[],observations={},comparisons={})
        board=decoded_board(frame,self.first['game_key'],view='ev',filter='all')
        self.assertIn('captured_inputs_changed_before_publication',board['background_reasons'])
        self.assertTrue(board['rows'])
        self.assertTrue(all(not r['ranking_eligible'] for r in board['rows']))
        self.assertTrue(all(not r.get('classification',{}).get('main_positive_eligible') for r in board['rows']))
        selected=board['rows'][0]['details']
        query=dict(game=self.first['game_key'],view='details',context_id=selected['context_id'],quote=selected['quote_id'])
        with self.connect() as db,db.transaction():
            detail=selected_frame.read(db,saved,query,DEFAULT_POLICY)
        self.assertEqual(detail['selection_status'],'captured')
        price=next(p for p in saved['facts']['boards']['ev']['prices'] if p['quote_id']==selected['quote_id'])
        self.assertEqual(detail['quote']['original'],price['original'])
        self.assertEqual(detail['quote']['times'],price['times'])

    async def test_actual_http_page_filter_poll_and_selected_amount_use_database_only(self):
        self.reconcile();published=self.rows();selected=published[self.first['game_key']]['facts']['boards']['ev']['rows'][0]['details']
        source=published[self.first['game_key']]['facts']['boards']['odds']['prices'][0]
        from app.dashboard.comparison_board_api import mount
        provider=RuntimeClient(connector=self.connect);provider.acquire=MagicMock(side_effect=AssertionError('provider forbidden'))
        app=web.Application();mount(app,provider)
        with patch('app.dashboard.comparison_board_api.connect',side_effect=self.connect),patch('app.dashboard.scanner_api.connect',side_effect=self.connect):
            async with TestClient(TestServer(app)) as client:
                with patch('app.dashboard.comparison_board_api.calculate_current',side_effect=AssertionError('request finance forbidden')),patch.object(latest,'calculate_current',side_effect=AssertionError('request finance forbidden')):
                    for _ in range(2):
                        for view in ('games','odds','ev','arbs','slate'):
                            params={} if view=='games' else dict(view='ev',filter='all',limit='50',amount='500') if view=='slate' else dict(game=self.first['game_key'],filter='all')
                            result=await client.get('/api/boards/'+view,params=params)
                            self.assertEqual(result.status,200,await result.text())
                            value=await result.json();self.assertEqual(value['provider_requests'],0)
                            if view=='slate':
                                self.assertEqual(value['policy']['requested_amount_usd'],'1000')
                                self.assertEqual(value['requested_policy']['requested_amount_usd'],'500')
                    for selected_filter in ('positive','all','hedges'):
                        result=await client.get('/api/boards/slate',params=dict(view='arbs',filter=selected_filter,limit='1'))
                        self.assertEqual(result.status,200,await result.text())
                        self.assertEqual((await result.json())['filter'],selected_filter)
                    pages=[];read_identity={}
                    for offset in (0,1):
                        result=await client.get('/api/boards/slate',params=dict(view='odds',filter='all',offset=str(offset),limit='1',**read_identity))
                        self.assertEqual(result.status,200,await result.text());page=await result.json()
                        read_identity=dict(read_token=page['read_token'],expected_revision=page['read_revision'])
                        self.assertEqual(page['coverage']['total_games'],2)
                        self.assertEqual(page['coverage']['returned_games'],1)
                        self.assertEqual(len(page['boards']),1)
                        pages.extend(b['game_key'] for b in page['boards'])
                    self.assertEqual(set(pages),set(published))
                    with patch('app.dashboard.comparison_board_api.discover',side_effect=AssertionError('optional finance discovery forbidden')):
                        inputs=dict(game=self.first['game_key'],context_id=source['inputs_identity']['context_id'],quote=source['quote_id'])
                        result=await client.get('/api/boards/inputs',params=inputs);value=await result.json()
                        self.assertEqual(result.status,200,value)
                        self.assertEqual(value['provider_requests'],0)
                        self.assertEqual(value['evidence']['source'],source['source'])
                        self.assertEqual(value['evidence']['original'],source['original'])
                        self.assertEqual(value['evidence']['times'],source['times'])
                amount=dict(game=self.first['game_key'],context_id=selected['context_id'],quote=selected['quote_id'],amount='500')
                result=await client.get('/api/boards/details',params=amount);value=await result.json()
                self.assertEqual(result.status,200,value);self.assertEqual(value['policy']['requested_amount_usd'],'500')
                self.assertEqual(value['selection_context']['context_id'],selected['context_id'])
                self.assertNotEqual(value['calculation_context']['context_id'],selected['context_id'])
                # Details hands off its financial identity, whereas Odds hands
                # off the independent source identity. Both must inspect exactly
                # their selected originals without treating the two as equal.
                original=value['quote']
                result=await client.get('/api/boards/inputs',params=dict(game=self.first['game_key'],
                    context_id=value['original_inputs_identity']['context_id'],quote=selected['quote_id']))
                inputs=await result.json()
                self.assertEqual(result.status,200,inputs)
                self.assertEqual(inputs['evidence']['original'],original['original'])
                self.assertEqual(inputs['evidence']['times'],original['times'])
                self.service.dispatch=False;self.state.write(self.service)
                result=await client.get('/api/boards/details',params=amount)
                self.assertEqual(result.status,409)
                self.assertEqual((await result.json())['reason'],'background_runtime_authority_unavailable')
                self.service.dispatch=True;self.state.write(self.service);self.at+=timedelta(seconds=9)
                result=await client.get('/api/boards/details',params=amount)
                self.assertEqual(result.status,409)
        provider.acquire.assert_not_called();self.assertEqual(self.rows(),published)

    async def test_retained_publication_budget_accounts_replacements_without_eviction(self):
        self.reconcile();rows=self.rows()
        with self.connect() as db:
            status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
            status.pop('capture_events',None);status.pop('capture_membership',None)
            proof=latest.marker(db);owner=latest.runtime(db)
            total=int(db.execute('SELECT sum(retained_bytes) n FROM latest_board').fetchone()['n'])
            selected=db.execute('SELECT game_key,dependency_revision,economic_revision,calculated_at,facts FROM latest_board ORDER BY game_key LIMIT 1').fetchall()
            with patch.object(latest,'MAX_BYTES',total):
                self.assertTrue(latest.publish(db,captured_marker=proof,captured_runtime=owner,status=status,rows=deepcopy(selected)))
            with patch.object(latest,'MAX_BYTES',total-1),self.assertRaisesRegex(ValueError,'latest_board_capacity'):
                latest.publish(db,captured_marker=proof,captured_runtime=owner,status=status,rows=deepcopy(selected))
        self.assertEqual(self.rows(),rows)

    async def test_slow_estimate_completes_identical_newer_pending_observations(self):
        from psycopg.types.json import Jsonb
        self.reconcile();evaluated=self.rows()
        with self.connect() as db:
            status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
            # Author this delayed completion across the whole fixture snapshot;
            # the ordinary worker now publishes one complete component at a time.
            status.pop('capture_events',None);status.pop('capture_membership',None)
            proof=latest.marker(db);owner=latest.runtime(db)
            for row in evaluated.values():
                source=deepcopy(row['facts'])
                source['boards']['odds']['as_of']=(self.at+timedelta(seconds=1)).isoformat()
                source['context']=None
                source['estimate_availability']=dict(state='pending',reason_codes=['background_estimates_pending'])
                db.execute('UPDATE latest_board SET calculated_at=NULL,facts=%s WHERE game_key=%s',
                    (Jsonb(source),row['game_key']))
            self.assertTrue(latest.publish(db,captured_marker=proof,captured_runtime=owner,
                status=status,rows=list(deepcopy(evaluated).values())))
        for key,row in self.rows().items():
            self.assertEqual(row['calculated_at'],evaluated[key]['calculated_at'])
            self.assertEqual(row['facts']['boards']['odds']['as_of'],(self.at+timedelta(seconds=1)).isoformat())
            self.assertEqual(row['facts']['boards']['odds']['prices'],evaluated[key]['facts']['boards']['odds']['prices'])

    async def test_completed_failure_upgrades_identical_pending_frame_and_is_reused(self):
        from psycopg.types.json import Jsonb
        with patch.object(latest,'calculate_current',side_effect=ValueError('authored calculation failure')):
            self.reconcile()
        failed=self.rows()
        self.assertTrue(all(row['facts']['calculation_error']=='calculation_failed' for row in failed.values()))
        with self.connect() as db:
            status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
            status.pop('capture_events',None);status.pop('capture_membership',None)
            proof=latest.marker(db);owner=latest.runtime(db)
            for row in failed.values():
                source=deepcopy(row['facts'])
                source['boards']['odds']['as_of']=(self.at+timedelta(seconds=1)).isoformat()
                source['estimate_availability']=dict(state='pending',reason_codes=['background_estimates_pending'])
                db.execute('UPDATE latest_board SET facts=%s WHERE game_key=%s',(Jsonb(source),row['game_key']))
            self.assertTrue(latest.publish(db,captured_marker=proof,captured_runtime=owner,status=status,
                                          rows=list(deepcopy(failed).values())))
        self.assertTrue(all(row['facts']['estimate_availability']['state']=='unavailable' for row in self.rows().values()))
        with patch.object(latest,'calculate_current',side_effect=AssertionError('identical failed work repeated')) as calculate:
            result=self.reconcile()
        calculate.assert_not_called()
        self.assertEqual(result['computed'],0)
        self.assertEqual(result['reused'],len(failed))

    async def test_publication_authority_does_not_block_heartbeat_but_serializes_controls(self):
        from app.collection.runtime_status import AUTHORITY_LOCK
        from psycopg.errors import LockNotAvailable
        with self.connect() as publication,publication.transaction():
            publication.execute('SELECT pg_advisory_xact_lock_shared(%s)',(AUTHORITY_LOCK,))
            self.at+=timedelta(seconds=9)
            self.assertTrue(self.state.write_snapshot(self.state.snapshot(self.service),heartbeat=True))
            self.assertTrue(self.state.read()['healthy'])
            with self.connect() as control:
                control.execute("SET lock_timeout='100ms'")
                with self.assertRaises(LockNotAvailable),control.transaction():
                    control.execute('SELECT pg_advisory_xact_lock(%s)',(AUTHORITY_LOCK,))
        self.service.dispatch=False;self.state.write(self.service)
        self.assertFalse(self.state.read()['active'])

    async def test_source_snapshot_survives_busy_sibling_without_currentness_revival(self):
        from app.storage.current_rows import contract_id
        self.fresh_sources();self.reconcile();rows=self.rows()
        with self.connect() as db:
            status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
            marker=latest.marker(db);owner=latest.runtime(db)
            selected=next(r for r in self.records if r['quote']['venue']=='kalshi')
            db.execute("UPDATE current_offer SET revision=revision||'-changed' WHERE contract_id=%s",(contract_id(selected),))
        status['observation_only']=True
        with self.connect() as db:
            self.assertTrue(latest.publish(db,captured_marker=marker,captured_runtime=owner,status=status,rows=list(rows.values())))
        frame=self.snapshot()
        changed=[];unchanged=[]
        for key in rows:
            b=latest.board(frame,key,view='odds',filter='all')
            from app.dashboard.comparison_board import expand_odds,expand_price_fields
            for q in expand_odds(expand_price_fields(b))['prices']:
                (changed if contract_id(dict(quote=q))==contract_id(selected) else unchanged).append(q)
        self.assertTrue(changed)
        self.assertTrue(all(q['observation_display']['state']!='current' for q in changed))
        self.assertTrue(any(q['observation_display']['state']=='current' for q in unchanged))

    async def test_captured_selected_chain_keeps_exact_inputs_across_publication(self):
        from app.dashboard.comparison_board_api import mount
        from app.dashboard.comparison_board import expand_price_fields
        from app.storage.current_rows import contract_id
        self.reconcile()
        app=web.Application();mount(app,RuntimeClient(connector=self.connect))
        with patch('app.dashboard.comparison_board_api.connect',side_effect=self.connect):
            async with TestClient(TestServer(app)) as client:
                response=await client.get('/api/boards/slate',params=dict(view='ev',filter='all',limit='50'))
                self.assertEqual(response.status,200,await response.text())
                slate=await response.json()
                board=expand_price_fields(next(b for b in slate['boards'] if b['game_key']==self.second['game_key']))
                selected=board['rows'][0]['details']
                query=dict(game=board['game_key'],quote=selected['quote_id'],context_id=selected['context_id'],read_token=selected['read_token'])
                async def details():
                    reply=await client.get('/api/boards/details',params=query)
                    value=await reply.json();self.assertEqual(reply.status,200,value)
                    query['read_token']=value['read_token']
                    return value
                before=await details()
                self.assertEqual(before['selection_status'],'unchanged')
                self.changed_first();self.reconcile()
                self.assertEqual((await details())['selection_status'],'unchanged')
                record=next(r for r in self.records if [r['quote']['source']['provider'],r['quote']['source']['native_event_id']] in self.second['members'])
                with self.connect() as db:db.execute('DELETE FROM current_offer WHERE contract_id=%s',(contract_id(record),))
                after=await details()
                self.assertEqual(after['selection_status'],'captured')
                self.assertFalse(after['quote']['calculations']['funded_estimate']['ranking_eligible'])
                self.assertEqual(after['quote']['original'],before['quote']['original'])
                self.assertEqual(after['quote']['times'],before['quote']['times'])
                reply=await client.get('/api/boards/inputs',params=query);inputs=await reply.json()
                self.assertEqual(reply.status,200,inputs)
                self.assertEqual(inputs['evidence']['original'],before['quote']['original'])
                self.assertEqual(inputs['evidence']['times'],before['quote']['times'])
                reply=await client.get('/api/boards/details',params=dict(query,context_id='mismatched'))
                self.assertEqual(reply.status,409)
                self.service.dispatch=False;self.state.write(self.service)
                self.assertEqual((await details())['selection_status'],'captured')

    async def test_selected_chain_survives_unrelated_publication_and_withdraws_changed_inputs(self):
        self.reconcile()
        selected=self.rows()[self.second['game_key']]['facts']['boards']['ev']['rows'][0]['details']
        from app.dashboard.comparison_board_api import mount
        app=web.Application();mount(app,RuntimeClient(connector=self.connect))
        query=dict(game=self.second['game_key'],context_id=selected['context_id'],quote=selected['quote_id'])
        with patch('app.dashboard.comparison_board_api.connect',side_effect=self.connect):
            async with TestClient(TestServer(app)) as client:
                reply=await client.get('/api/boards/details',params=query)
                before=await reply.json();self.assertEqual(reply.status,200,before)
                self.changed_first();self.reconcile()
                for endpoint in ('details','inputs'):
                    reply=await client.get('/api/boards/'+endpoint,params=query)
                    value=await reply.json();self.assertEqual(reply.status,200,value)
                    quote=value['quote'] if endpoint=='details' else value['evidence']
                    self.assertEqual(quote['original'],before['quote']['original'])
                    self.assertEqual(quote['times'],before['quote']['times'])
                # An actual removal from the selected neighborhood invalidates
                # both routes even before a replacement board is published.
                from app.storage.current_rows import contract_id
                record=next(r for r in self.records if
                    [r['quote']['source']['provider'],r['quote']['source']['native_event_id']] in self.second['members'])
                with self.connect() as db:db.execute('DELETE FROM current_offer WHERE contract_id=%s',(contract_id(record),))
                for endpoint in ('details','inputs'):
                    reply=await client.get('/api/boards/'+endpoint,params=query)
                    self.assertEqual(reply.status,409,await reply.json())
