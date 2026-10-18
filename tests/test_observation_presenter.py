"""Profile-free observation admission and bounded original-price presentation."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.comparison.estimated_policy import DEFAULT_POLICY
from app.dashboard.comparison_board import entries, freshness, price, response, gross_comparison, quote_key, expand_odds, age_gross_comparison
from app.storage.latest_board import board as read_board
from app.storage.comparison_board import ReadContext, observation_identity
from app.storage.store import encoded, stamp
from tests.test_ev09_n01 import AT, retained


class ObservationPresenter(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records=retained()[0]['records']

    def context(self,records=None,at=AT):
        return ReadContext(SimpleNamespace(db=None),at=at,frame=dict(epoch='authored-observations',
            revision='authored-source-revision',records=deepcopy(self.records if records is None else records)))

    def board(self,context):
        bundle=context.observation_bundles()[0]
        from tests.multisport_fixtures import compatible_winner_equality
        compatible_winner_equality(bundle['state_inputs'])
        bundle['calculation_context']=observation_identity(bundle,context)
        return expand_odds(response(bundle,None,DEFAULT_POLICY,view='odds',filter='all',at=context.at))

    def test_source_admission_ignores_optional_profiles_and_malformed_benchmark(self):
        records=deepcopy(self.records)
        for row in records:
            row['quote'].update(sharp_reference='malformed optional reference',
                comparison_input_refs={'malformed':True},comparison_input_status='malformed optional status')
        with patch('app.comparison.public_retail.registry',side_effect=AssertionError('no financial registry')), \
             patch('app.comparison.source_inputs.produce',side_effect=AssertionError('no financial profiles')), \
             patch('app.comparison.combined_inputs._benchmark',return_value=({'malformed_optional_benchmark':True},None)):
            context=self.context(records);board=self.board(context)
        self.assertEqual(len(board['prices']),sum(r['quote']['venue']!='pinnacle' for r in records))
        self.assertFalse(board['benchmark']['available']);self.assertEqual(board['benchmark']['fair'],[])
        expected={encoded(r['quote']['source']):r['quote'] for r in records}
        for row in board['prices']:
            original=expected[encoded(row['source'])]
            self.assertEqual(row['original'],original['original']);self.assertEqual(row['times'],original['times'])
            self.assertEqual(row['observation_revision'],row['inputs_identity']['observation_revision'])
            self.assertEqual(row['quote_revision'],row['inputs_identity']['quote_revision'])

    def test_depth_is_bounded_and_native_units_and_clocks_are_exact(self):
        records=deepcopy(self.records)
        selected=next(r for r in records if r['quote']['venue']=='kalshi')['quote']
        selected['depth']=[dict(price='0.4',quantity=str(i+1)) for i in range(12)]
        board=self.board(self.context(records))
        actual=next(r for r in board['prices'] if r['source']==selected['source'])
        depth=actual['observed_depth']
        self.assertTrue(depth['available']);self.assertTrue(depth['truncated']);self.assertEqual(depth['total_levels'],12)
        self.assertEqual(depth['levels'],selected['depth'][:8]);self.assertEqual(depth['quantity_units'],selected['original']['quantity_units'])
        self.assertEqual(depth['price_units'],selected['original']['units']);self.assertEqual(depth['source_at'],selected['times']['source_at'])
        self.assertEqual(depth['received_at'],selected['times']['received_at'])
        changed=deepcopy(records);next(r for r in changed if r['quote']['source']==selected['source'])['quote']['depth'][-1]['quantity']='999'
        after=next(r for r in self.board(self.context(changed))['prices'] if r['source']==selected['source'])
        self.assertNotEqual(actual['observation_revision'],after['observation_revision'])

    def test_source_freshness_never_evaluates_optional_financial_inputs(self):
        context=self.context();bundle=context.observation_bundles()[0]
        event,_,quote=entries(bundle['state_inputs'])[0]
        quote['comparison_input_refs']='malformed optional refs'
        with patch('app.dashboard.comparison_board.temporal',side_effect=AssertionError('no model clocks')), \
             patch('app.dashboard.comparison_board.references',side_effect=AssertionError('no profiles')):
            source=freshness(quote,{'malformed':'optional'},event,stamp(AT),financial=False)
        self.assertEqual(source['status'],'current');self.assertEqual(source['source_at'],quote['times']['source_at'])
        self.assertEqual(source['received_at'],quote['times']['received_at'])

    def test_book_clocks_advance_without_renewing_the_original_price_clock(self):
        from app.storage.current_rows import contract_id
        records=deepcopy(self.records)
        original=next(r for r in records if r['quote']['venue']=='kalshi')
        book=dict(contract_id=contract_id(original),source_at='2026-10-14T01:15:02Z',
            received_at='2026-10-14T01:15:03Z',revision='authored-new-book',quantity_units='contracts',
            state='active',sync='synchronized',sequence='8')
        class Database:
            def execute(self,*args):return SimpleNamespace(fetchall=lambda:[dict(book)])
        context=self.context(records);context.store.db=Database()
        with patch('app.storage.current_rows.CurrentRowStore.hydrate_records',side_effect=lambda records,**kwargs:deepcopy(records)):
            bundle=context.observation_bundles()[0]
        quote=next(q for _,_,q in entries(bundle['state_inputs']) if q['source']==original['quote']['source'])
        before=price(quote);identity=observation_identity(bundle,context)
        self.assertEqual(before['times'],original['quote']['times'])
        self.assertEqual(before['observed_depth']['source_at'],book['source_at'])
        self.assertEqual(before['observed_depth']['received_at'],book['received_at'])
        self.assertEqual(before['observed_depth']['clock_basis'],'current_native_book')
        quote['observed_book']['received_at']='2026-10-14T01:15:04Z'
        after=price(quote)
        self.assertEqual(after['times'],before['times'])
        self.assertNotEqual(after['observation_revision'],before['observation_revision'])
        self.assertNotEqual(observation_identity(bundle,context),identity)

    def test_invalid_collected_price_is_still_rejected(self):
        records=deepcopy(self.records)
        next(r for r in records if r['quote']['venue']=='kalshi')['quote']['original']['value']='not-a-price'
        with self.assertRaises(ValueError):self.context(records).observation_bundles()

    def test_gross_comparisons_disclose_exact_input_formula_and_native_sides(self):
        board=self.board(self.context())
        by_id={row['quote_id']:row for row in board['prices']}
        compared=[row for row in board['prices'] if row['gross_comparison']['available']]
        self.assertTrue(compared)
        for row in compared:
            gross=row['gross_comparison'];other=by_id[gross['comparison_quote_id']]
            self.assertEqual(row['selection']['predicate'],other['selection']['predicate'])
            self.assertEqual(row['selection']['participant'],other['selection']['participant'])
            exact=Fraction(int(gross['exact']['numerator']),int(gross['exact']['denominator']))
            self.assertLess(abs(Fraction(gross['value'])-exact),Fraction(1,10**90))
            self.assertRegex(gross['meaning'],r'before (fees|costs)');self.assertEqual(gross['inputs'][0]['times'],row['times'])
        self.assertEqual({r['native_side'] for r in board['prices'] if r['venue']=='kalshi'},{'yes','no'})
        self.assertTrue(all('financial_metrics' not in row for row in board['prices']))

    def read_frame(self,board,*,at=AT,reasons=(),states=None):
        """Only a detached publication: reads cannot consult a newer peer."""
        return dict(rows={board['game_key']:dict(facts=dict(boards=dict(odds=deepcopy(board)),
            estimate_availability=dict(state='unavailable',reason_codes=['fixture_optional_estimate_unavailable'])),
            economic_revision='authored-publication',calculated_at=None)},
            status=dict(games=[dict(game_key=board['game_key'],**board['prices'][0]['event'])]),
            reasons=list(reasons),observation_reasons=list(reasons),calculation_reasons=[],at=at,
            source_states={} if states is None else deepcopy(states),owner=dict(healthy=True,active=True))

    def compared_row(self,board):
        board=expand_odds(board)
        return next(q for q in board['prices'] if q['venue']=='novig'
            and q['gross_comparison']['available'] and q['gross_comparison']['comparison_venue']=='polymarket_us')

    def test_repeated_expansion_preserves_independent_frozen_inputs(self):
        original=self.board(self.context());selected=self.compared_row(original)
        comparison=selected['gross_comparison'];captured=deepcopy(comparison['inputs'])
        self.assertNotIn('input_refs',comparison,'resolved references are consumed by the detached snapshot')
        peer=next(q for q in original['prices'] if q['quote_id']==comparison['comparison_quote_id'])
        peer['original']['value']='0.99';peer['times']['source_at']=AT
        expand_odds(original);expand_odds(original)
        self.assertEqual(comparison['inputs'],captured)
        age_gross_comparison(comparison,AT,captured_rows=original['prices'],publication_reasons=['current_dependencies_changed'])
        for before,after in zip(captured,comparison['inputs']):
            for field in ('original','times','captured_source_state','captured_source_health'):
                self.assertEqual(after[field],before[field])
        self.assertEqual(comparison['display_status'],'pending')

    def test_stale_comparator_ages_exact_captured_difference_without_price_change(self):
        original=self.board(self.context());selected=self.compared_row(original)
        before=deepcopy(selected['gross_comparison']);self.assertEqual(before['display_status'],'current')
        read_at=(stamp(AT)+timedelta(seconds=20)).isoformat()
        frame=self.read_frame(original,at=read_at)
        with patch('app.storage.latest_board.calculate_current',side_effect=AssertionError('read cannot calculate')), \
             patch('app.storage.latest_board.read_context',side_effect=AssertionError('read cannot acquire new inputs')):
            after=self.compared_row(read_board(frame,original['game_key'],view='odds',filter='all'))
        gross=after['gross_comparison']
        self.assertEqual(after['observation_display']['state'],'current')
        self.assertEqual(gross['display_status'],'last_known')
        self.assertEqual([q['observation_display']['state'] for q in gross['inputs']],['current','last_known'])
        self.assertEqual(gross['inputs'][1]['freshness']['reasons'],['source_expired'])
        for field in ('exact','value','comparison_quote_id','comparison_venue','display_value'):
            self.assertEqual(gross[field],before[field])
        for old,new in zip(before['inputs'],gross['inputs']):
            for field in ('original','times','native_side','selection','quote_id','quote_revision','captured_source_state','captured_source_health'):
                self.assertEqual(new[field],old[field])
            self.assertEqual(new['observation_display']['source_age_seconds'],old['observation_display']['source_age_seconds']+20)
        self.assertEqual(gross['source_time_skew_seconds'],before['source_time_skew_seconds'])
        self.assertEqual(selected['gross_comparison'],before)

    def test_pending_source_expiry_stop_and_runtime_failure_remain_separate(self):
        original=self.board(self.context());key=original['game_key']
        pending=self.compared_row(read_board(self.read_frame(original,reasons=['current_dependencies_changed']),key,view='odds',filter='all'))
        self.assertEqual(pending['observation_display']['state'],'pending')
        self.assertEqual(pending['observation_display']['source_reason_codes'],[])
        self.assertEqual(pending['observation_display']['publication_reason_codes'],['current_dependencies_changed'])
        self.assertEqual(pending['gross_comparison']['display_status'],'pending')
        self.assertNotIn('source_expired',pending['freshness']['reasons'])
        for code,state in (('updates_stopped','stopped'),('data_runtime_unhealthy','unavailable')):
            with self.subTest(code=code):
                source_states={v:dict(state=state,reason_code=code) for v in {q['venue'] for q in original['prices']}}
                row=self.compared_row(read_board(self.read_frame(original,reasons=[code],states=source_states),key,view='odds',filter='all'))
                self.assertEqual(row['observation_display']['state'],'last_known')
                self.assertIn(code,row['observation_display']['source_reason_codes'])
                self.assertNotIn(code,row['observation_display']['publication_reason_codes'])
                self.assertNotIn('source_expired',row['observation_display']['source_reason_codes'])
                self.assertEqual(row['gross_comparison']['display_status'],'last_known')
                self.assertEqual(row['gross_comparison']['exact'],pending['gross_comparison']['exact'])
        expired_pending=self.compared_row(read_board(self.read_frame(original,
            at=(stamp(AT)+timedelta(seconds=20)).isoformat(),reasons=['current_dependencies_changed']),key,view='odds',filter='all'))
        peer=expired_pending['gross_comparison']['inputs'][1]['observation_display']
        self.assertEqual(peer['state'],'last_known');self.assertIn('source_expired',peer['source_reason_codes'])
        self.assertIn('current_dependencies_changed',peer['publication_reason_codes'])

    def test_unknown_source_and_receipt_clocks_preserve_known_age_and_skew(self):
        original=self.board(self.context());key=original['game_key']
        for missing in ('source_at','received_at'):
            with self.subTest(missing=missing):
                altered=deepcopy(original);selected=self.compared_row(altered)
                peer=selected['gross_comparison']['inputs'][1]
                peer['times'][missing]=None
                before=deepcopy(peer['times'])
                row=self.compared_row(read_board(self.read_frame(altered),key,view='odds',filter='all'))
                gross=row['gross_comparison'];display=gross['inputs'][1]['observation_display']
                self.assertEqual(gross['display_status'],'unknown');self.assertEqual(display['state'],'unknown')
                self.assertIsNone(display['source_age_seconds'] if missing=='source_at' else display['received_age_seconds'])
                self.assertIsNotNone(display['received_age_seconds'] if missing=='source_at' else display['source_age_seconds'])
                self.assertEqual(gross['source_time_skew_seconds'] is None,missing=='source_at')
                self.assertEqual(gross['inputs'][1]['times'],before)

    def test_available_health_cannot_promote_captured_unavailable_input(self):
        original=self.board(self.context());key=original['game_key']
        selected=self.compared_row(original);peer=selected['gross_comparison']['inputs'][1]
        failure=dict(state='unavailable',reason_code='authored_capture_failure',reason='Unavailable when captured')
        peer.update(source_state='unavailable',source_health=deepcopy(failure),captured_source_state='unavailable',captured_source_health=deepcopy(failure))
        read=self.compared_row(read_board(self.read_frame(original,states={peer['venue']:dict(state='available')}),key,view='odds',filter='all'))
        retained=read['gross_comparison']['inputs'][1]
        self.assertEqual(retained['source_health']['state'],'available')
        self.assertEqual(retained['captured_source_health'],failure)
        self.assertEqual(retained['observation_display']['state'],'last_known')
        self.assertIn('captured_source_unavailable',retained['observation_display']['source_reason_codes'])
        self.assertEqual(read['gross_comparison']['exact'],selected['gross_comparison']['exact'])

    def test_equal_price_peers_keep_quote_identity_tie_and_exact_subtraction(self):
        context=self.context();bundle=context.observation_bundles()[0];state=deepcopy(bundle['state_inputs'])
        from tests.multisport_fixtures import compatible_winner_equality
        compatible_winner_equality(state,venues=('novig','prophetx','polymarket_us','kalshi'))
        event,group,selected=next((e,g,q) for e,g,q in entries(state) if q['venue']=='novig')
        selection=selected['binding']['selection']
        peers=[q for e,g,q in entries(state) if e['id']==event['id'] and g.get('display_group',{}).get('id')==group['display_group']['id']
            and q['venue']!=selected['venue'] and q['binding']['selection']['participant']==selection['participant']
            and q['binding']['selection']['predicate']==selection['predicate']]
        self.assertGreaterEqual(len(peers),2)
        for peer in peers:peer['original'].update(value='0.4',units='usd_per_contract',payout='1',quantity_units='contracts')
        before=gross_comparison(selected,group,event,state,stamp(AT));self.assertTrue(before['available'])
        self.assertEqual(before['comparison_quote_id'],min(map(quote_key,peers)))
        from app.dashboard.current_contract import price as source_price
        expected=(Fraction('0.4')-source_price(selected))*100
        self.assertEqual(Fraction(int(before['exact']['numerator']),int(before['exact']['denominator'])),expected)
        self.assertLess(expected,0)
        for peer in peers:peer['times']['source_at']='2026-10-14T00:00:00Z'
        after=gross_comparison(selected,group,event,state,stamp(AT))
        self.assertEqual(after['comparison_quote_id'],before['comparison_quote_id']);self.assertEqual(after['exact'],before['exact'])
        self.assertEqual(after['display_status'],'last_known')

    def test_legacy_publication_and_changed_peer_never_mix_original_comparison_frames(self):
        original=self.board(self.context());key=original['game_key'];selected=self.compared_row(original)
        captured=deepcopy(selected['gross_comparison'])
        legacy=deepcopy(original)
        for row in legacy['prices']:
            for field in ('captured_source_state','captured_source_health','observation_display'):row.pop(field,None)
            for item in row['gross_comparison']['inputs']:
                for field in ('captured_source_state','captured_source_health','source_state','source_health','observation_display','freshness','freshness_policy','event'):item.pop(field,None)
        read=self.compared_row(read_board(self.read_frame(legacy),key,view='odds',filter='all'))
        self.assertEqual(read['gross_comparison']['display_status'],'current')
        changed=deepcopy(legacy)
        peer=next(q for q in changed['prices'] if q['quote_id']==captured['comparison_quote_id'])
        peer['original']['value']='0.99';peer['times']['source_at']=AT
        retained=self.compared_row(read_board(self.read_frame(changed,reasons=['current_dependencies_changed']),key,view='odds',filter='all'))['gross_comparison']
        self.assertEqual(retained['exact'],captured['exact']);self.assertEqual(retained['inputs'][1]['original'],captured['inputs'][1]['original'])
        self.assertEqual(retained['inputs'][1]['times'],captured['inputs'][1]['times'])
        self.assertEqual(retained['display_status'],'unknown')
        self.assertIn('comparison_input_metadata_unknown',retained['reason_codes'])
