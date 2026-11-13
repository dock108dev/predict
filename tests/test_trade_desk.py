"""Price and rank contracts for the installed EV and arbitrage lists."""
from fractions import Fraction
from unittest import TestCase
from unittest.mock import Mock, patch

from app.comparison.ordinary_arb import DEFAULT_FUNDING, evaluate as evaluate_arb
from app.comparison.snapshot_math import before_fee_pair
from app.dashboard.trade_desk import add_sgo_prices, game_source_key, page
from app.storage.store import hashed, stamp
from app.storage.comparison_snapshot import before_fee_pairs


def quote(id_, venue, *, value=None, current=True, threshold=0, operator='ge', equality=None):
    return dict(id=id_, venue=venue, kind='single', game_key='game', game_title='Away at Home', league='NBA',
                start_at='2026-11-08T01:00:00+00:00', market=dict(market='spread', period='full_game', line='2.5'),
                selection=dict(participant='home', predicate='cover', signed_line='-2.5'),
                original=dict(value='2.2', units='decimal_odds', payout='1'),
                cost_per_normal_claim='5/11', gross_return_percent=value, price_current=current,
                current_authority={'price': {}}, current_reasons=[] if current else ['source_expired'],
                metric_status={'before_fee_ev': {'state': 'available'}}, publication_policy='policy',
                reference=dict(bookmaker='pinnacle', odds=['2.1', '1.8'], selected=0),
                same_outcome={'supported': True, 'key': ['version', 'occurrence', 'NBA', 'home', 'away', 'spread', 'full_game',
                                      None, 'score', ['home_margin', operator, [threshold, 1], None],
                                      equality or ['predicate'], ['included'], ['USD', 'contracts', [1, 1]]]})


def result(*rows):
    return dict(rows=rows, publication={}, assumptions={'benchmark_venue': 'pinnacle'})


class TradeDesk(TestCase):
    def test_live_desk_prefers_direct_exchange_sources_even_with_retained_prices(self):
        direct = dict(quote('direct', 'kalshi'), source={'provider': 'kalshi'})
        aggregate = dict(quote('aggregate', 'kalshi'), source={'provider': 'sportsgameodds'})
        other = dict(quote('novig', 'novig'), source={'provider': 'sportsgameodds'})
        out = page(result(direct, aggregate, other), {'layout':'desk', 'last_known':'1'}, ('ev', None, 0, 10))
        self.assertEqual({q['id'] for g in out['rows'] for q in g['offers']}, {'direct', 'novig'})

    def test_native_only_sportsbook_quotes_are_displayed_without_qualifying_ev(self):
        home = quote('native-home', 'kalshi')
        home.update(market=dict(market='winner', period='full_game', line=None),
                    selection=dict(participant='home', predicate='win'))
        no = dict(home, id='native-no', selection=dict(participant='home', predicate='not_win'))
        start = home['start_at']
        data = result(home, no)
        data['games'] = [dict(game_key='game', league='NBA', start_at=start, participants=[
            dict(id='home', role='home'), dict(id='away', role='away'),
        ])]
        at = stamp('2026-11-08T00:55:00Z')
        source_at = '2026-11-08T00:54:00Z'
        event = dict(native_event_id='sgo-game', competition='NBA', scheduled_start=start, home='home', away='away')
        fact = dict(venue='fanduel', period='game', price_american='-132', starts_at=start,
                    source_at=source_at, received_at=source_at, league='NBA', market='moneyline',
                    phase='pregame', side='home', line=None, odd_id='sgo-moneyline', available=True)
        book = dict(id='book-row', revision='revision', facts=fact)
        frame = dict(facts=dict(starts_at=start, members=[['book-row', 'revision']], received_at=source_at))
        options = ('ev', None, 0, 10)
        with patch('app.storage.sportsgameodds_reference.read_event_frame', return_value=frame), patch(
                'app.storage.sportsgameodds_reference.read_event', return_value=[book]):
            for state, retained, duplicates, expected_current in [
                ({'state':'available'}, False, False, True),
                ({'state':'budget_delayed', 'reason_code':'sgo_charge_unresolved'}, True, False, False),
                ({'state':'budget_delayed', 'reason_code':'sgo_charge_unresolved'}, False, False, None),
                ({'state':'available'}, False, True, None),
            ]:
                with self.subTest(state=state, retained=retained, duplicates=duplicates):
                    db = Mock()
                    db.execute.return_value.fetchall.return_value = [
                        event, *([dict(event, native_event_id='another-event')] if duplicates else [])]
                    out = page(data, {'browse_odds':'1'}, options)
                    add_sgo_prices(db, out, data['rows'], {'sportsgameodds':state}, at=at, include_retained=retained)
                    groups = {g['offers'][0]['id']:g for g in out['rows']}
                    prices = groups['native-home']['sportsbook_quotes'].get('fanduel', [])
                    self.assertEqual([p['current'] for p in prices], [] if expected_current is None else [expected_current])
                    self.assertEqual(groups['native-no']['sportsbook_quotes'], {})
                    self.assertIsNone(groups['native-home']['offers'][0]['value'])
                    self.assertIsNone(groups['native-home']['score'])

    def test_native_short_names_are_searchable_by_canonical_team_names(self):
        row = quote('current', 'polymarket_us')
        row.update(league='NHL', game_title='Hurricanes at Kraken')
        data = result(row)
        data['games'] = [dict(game_key='game', league='NHL', title=row['game_title'], participants=[
            dict(id='NHL:CAR', name='Hurricanes'), dict(id='NHL:SEA', name='Kraken'),
        ])]
        options = ('ev', None, 0, 25)
        for search in ('Carolina Seattle', 'Hurricanes Kraken'):
            self.assertEqual(page(data, {'search': search}, options)['matched_offer_count'], 1)
        self.assertEqual(page(data, {'search': 'Boston Seattle'}, options)['matched_offer_count'], 0)

    def test_empty_filter_and_unavailable_rank_have_distinct_pre_threshold_counts(self):
        options = ('ev', 'gross_return_percent', 0, 25)
        negative = quote('negative', 'kalshi', value='-2')
        unranked = quote('unranked', 'polymarket_us')
        for query, expected in [({'search': 'unknown'}, (0, 0)), ({'venue': 'kalshi'}, (1, 1)),
                                ({'venue': 'polymarket_us'}, (1, 0))]:
            view = page(result(negative, unranked), dict(query, basis='before', positive='on'), options)
            self.assertEqual((view['matched_offer_count'], view['ranked_group_count']), expected)
            self.assertEqual(view['total'], 0)

    def test_current_unranked_outcome_precedes_retained_unranked_outcome(self):
        expired = quote('expired', 'novig', current=False)
        expired['selection']['signed_line'] = '-3.5'
        expired['start_at'] = '2026-11-07T01:00:00+00:00'
        current = quote('current', 'kalshi')
        options = ('ev', 'gross_return_percent', 0, 25)
        data = result(expired, current)
        ranked = page(data, {'basis':'sportsbooks'}, options)
        self.assertEqual([g['offers'][0]['id'] for g in ranked['rows']], ['current', 'expired'])
        scheduled = page(data, {'basis':'sportsbooks', 'sort':'start'}, options)
        self.assertEqual([g['offers'][0]['id'] for g in scheduled['rows']], ['expired', 'current'])

    def test_browse_pages_keep_the_whole_matchup_and_filter_exact_game(self):
        over = quote('over', 'kalshi')
        under = quote('under', 'polymarket_us')
        other = quote('other', 'kalshi')
        under['selection']['signed_line'] = '2.5'
        other['game_key'] = 'other'
        data = result(over, under, other)
        options = ('ev', None, 0, 1)
        first = page(data, {'browse_odds': '1', 'positive': 'on'}, options)
        self.assertEqual((first['row_kind'], first['total'], first['page_count']), ('games', 2, 1))
        self.assertEqual({row['game_key'] for row in first['rows']}, {'game'})
        self.assertEqual(len(first['rows']), 2)
        selected = page(data, {'browse_odds': '1', 'game_key': 'other'}, options)
        self.assertEqual([row['game_key'] for row in selected['rows']], ['other'])

    def test_game_link_follows_exact_original_contract_through_occurrence_rekey(self):
        selected = dict(quote('original', 'kalshi'), source=dict(provider='kalshi', native_event_id='event',
                        native_market_id='market', native_outcome_id='side', native_side='yes'))
        options = ('ev', None, 0, 10)
        origin = page(result(selected), {'basis': 'before'}, options)['rows'][0]
        self.assertEqual(origin['game_source'], game_source_key(selected))
        revised = dict(selected, id='revised', game_key='replacement')
        same_title = dict(quote('different', 'polymarket_us'), game_key='different-matchup')
        query = dict(browse_odds='1', game_key=origin['game_key'], game_source=origin['game_source'],
                     source_event=origin['source_event'], line=origin['id'])
        replacement = page(result(revised, same_title), query, options)
        self.assertEqual(replacement['selected_game_key'], 'replacement')
        self.assertEqual(replacement['selected_line_id'], replacement['rows'][0]['id'])
        self.assertEqual(replacement['rows'][0]['offers'][0]['id'], 'revised')
        ambiguous = page(result(revised, dict(selected, game_key='also-replacement')), query, options)
        self.assertEqual(ambiguous['rows'], [])
        remaining = dict(revised, id='another-line', source=dict(revised['source'], native_outcome_id='other-side'),
                         selection=dict(revised['selection'], signed_line='-3.5'))
        matchup = page(result(remaining, same_title), query, options)
        self.assertEqual(matchup['selected_game_key'], 'replacement')
        self.assertIsNone(matchup['selected_line_id'])
        self.assertEqual([row['game_key'] for row in matchup['rows']], ['replacement'])

    def test_sportsbook_mode_keeps_rank_separate_from_qualified_ev(self):
        first = quote('sgo', 'novig')
        first.update(sportsbook_baseline=dict(book='fanduel', fair_decimal_odds='2',
                     return_percent='10'), sportsbook_return_percent='10')
        other = quote('expired', 'kalshi', current=False)
        other.update(sportsbook_baseline=first['sportsbook_baseline'], sportsbook_return_percent='15')
        options = ('ev', 'gross_return_percent', 0, 25)
        view = page(result(other, first), {'basis':'sportsbooks', 'positive':'on'}, options)
        self.assertEqual(view['coverage']['sportsbooks'], 1)
        self.assertEqual(view['coverage']['before'], 0)
        self.assertEqual(view['rows'][0]['score'], '10')
        self.assertEqual(view['rows'][0]['offers'][0]['sportsbook']['book'], 'fanduel')
        self.assertIsNone(view['rows'][0]['offers'][1]['value'])

    def test_qualified_sgo_rank_is_independent_of_historical_reference_setting(self):
        from app.comparison.sgo_reference import BEST_VERSION

        row = quote('current', 'kalshi', value='8')
        row['reference_calculation'] = dict(available=True, method=BEST_VERSION, venue='fanduel')
        row['current_authority']['reference_method'] = BEST_VERSION
        published = dict(result(row), assumptions={'benchmark_venue':'novig'})
        view = page(published, {'basis':'before','positive':'on'}, ('ev',None,0,25))
        self.assertEqual(view['rows'][0]['score'], '8')

    def test_aggregate_venue_keeps_provider_attribution(self):
        row = quote('sgo', 'kalshi')
        row['source'] = {'provider': 'sportsgameodds'}
        view = page(result(row), {}, ('ev', 'gross_return_percent', 0, 25))
        self.assertEqual(view['rows'][0]['offers'][0]['source_provider'], 'sportsgameodds')

    def test_ev_groups_exact_lines_and_keeps_unknowns_out_of_rank(self):
        first = dict(quote('first', 'kalshi', value='8'), probability='100/223')
        second = quote('second', 'polymarket_us', value='0')
        retained = quote('retained', 'novig', value='99', current=False)
        other = quote('other', 'kalshi', value='-2')
        other['selection']['signed_line'] = '-3.5'
        data = result(retained, other, second, first)
        options = ('ev', 'gross_return_percent', 0, 25)
        view = page(data, {'day': '2026-11-07', 'timezone': 'America/New_York','basis':'before'}, options)
        self.assertEqual([g['score'] for g in view['rows']], ['8', '-2'])
        offers = view['rows'][0]['offers']
        self.assertEqual([q['value'] for q in offers], ['8', '0', None])
        self.assertEqual(offers[0]['reference']['american'], '+123')
        self.assertEqual(offers[2]['reason'], 'Price expired')
        self.assertEqual(page(data, {'positive': 'on','basis':'before'}, options)['total'], 1)

    def test_pair_requires_exclusive_score_coverage_and_evidenced_equality(self):
        a = quote('a', 'kalshi', threshold=3)
        b = quote('b', 'polymarket_us', threshold=2, operator='le')
        proof = before_fee_pair(a, b, 'spread')
        self.assertEqual(Fraction(proof['value']), 10)
        self.assertEqual(proof['weights'], ['1/2', '1/2'])
        gap = quote('gap', 'polymarket_us', threshold=1, operator='le')
        self.assertIsNone(before_fee_pair(a, gap, 'spread'))
        a['same_outcome']['key'][10] = gap['same_outcome']['key'][10] = ['fraction', [2, 1], [1, 2], 'not_applicable']
        self.assertEqual(before_fee_pair(a, gap, 'spread')['value'], '10')
        gap['same_outcome']['key'][10] = ['refund', [2, 1], None, 'not_applicable']
        self.assertIsNone(before_fee_pair(a, gap, 'spread'))

    def test_positive_filter_keeps_negative_reverse_and_withdraws_stale_legs(self):
        a = quote('a', 'kalshi', threshold=3)
        b = quote('b', 'polymarket_us', threshold=2, operator='le')
        c = quote('c', 'polymarket_us', threshold=3)
        d = quote('d', 'kalshi', threshold=2, operator='le')
        c['cost_per_normal_claim'] = d['cost_per_normal_claim'] = '5/9'
        for row in (a, b, c, d):
            row.update(source={'provider': 'practice'}, trade_fee=dict(available=True,
                classification='synthetic', evidence={'fictional_rate': '0.01'},
                fee_cashflows={'at_fill_usd': '0.01'}))
        pairs = [dict(left, id=f'pair-{left["id"]}', legs=[left['id'], right['id']],
                      before_fees=before_fee_pair(left, right, 'spread')) for left, right in ((c, d), (a, b))]
        options = ('arbs', 'gross_return_percent', 0, 25)
        view = page(result(a, b, c, d), {'positive': 'on', 'stake': '100', 'profit': '9'}, options,
                    captured_pairs=pairs, policy='policy')
        self.assertEqual([p['value'] for p in view['rows'][0]['pairs']], ['10', '-10'])
        self.assertEqual(Fraction(view['rows'][0]['score']), Fraction(900, 101))
        self.assertEqual(page(result(a, b, c, d), {'positive': 'on', 'profit': '10'}, options,
                              captured_pairs=pairs, policy='policy')['total'], 0)
        a['price_current'] = False
        self.assertEqual(page(result(a, b, c, d), {'positive': 'on'}, options,
                              captured_pairs=pairs, policy='policy')['total'], 0)

    def test_arb_does_not_combine_pregame_and_live_legs(self):
        left = quote('a', 'kalshi', threshold=3)
        right = quote('b', 'polymarket_us', threshold=2, operator='le')
        left['game_state'], right['game_state'] = 'live', 'scheduled'
        pair = dict(left, id='pair', legs=['a','b'], before_fees=before_fee_pair(left, right, 'spread'))
        view = page(result(left, right), {}, ('arbs', None, 0, 25), captured_pairs=[pair], policy='policy')
        self.assertEqual(view['eligible_pair_count'], 0)

    def test_ranked_arb_uses_funded_minimum_and_keeps_zero_and_losses(self):
        rows, pairs = [], []
        for key, cost, fee in (
                ('gross-first', '5/11', '0.06'), ('net-first', '25/54', '0'),
                ('even', '1/2', '0'), ('loss', '5/9', '0')):
            left = quote(f'{key}-first', 'novig', threshold=3)
            right = quote(f'{key}-second', 'prophetx', threshold=2, operator='le')
            for row in (left, right):
                row.update(game_key=key, cost_per_normal_claim=cost, source={'provider': 'practice'},
                           trade_fee=dict(available=True, classification='synthetic',
                                          evidence={'fictional_rate': fee}, fee_cashflows={'at_fill_usd': '0'}))
            rows.extend((left, right))
            pairs.append(dict(left, id=f'{key}-pair', legs=[left['id'], right['id']],
                              before_fees=before_fee_pair(left, right, key)))
        options = ('arbs', None, 0, 25)
        data = result(*rows)
        ranked = page(data, {'ranked': '1'}, options, captured_pairs=pairs, policy='policy')
        self.assertEqual([group['id'] for group in ranked['rows']], ['net-first', 'gross-first', 'even', 'loss'])
        self.assertEqual([Fraction(group['score']) for group in ranked['rows']], [8, Fraction(200, 53), 0, -10])
        positive = page(data, {'ranked': '1', 'positive': 'on'}, options, captured_pairs=pairs, policy='policy')
        self.assertEqual(positive['total'], 2)

    def test_arb_reuses_default_result_for_matching_fee_evidence(self):
        left = quote('left', 'novig', threshold=3)
        right = quote('right', 'prophetx', threshold=2, operator='le')
        for row in (left, right):
            row.update(source={'provider': 'practice'}, trade_fee=dict(available=True,
                classification='synthetic', evidence={'fictional_rate': '0.01'}, fee_cashflows={'at_fill_usd': '0'}))
        proof = before_fee_pair(left, right, 'spread')
        payoff = evaluate_arb(proof, (left, right), DEFAULT_FUNDING)
        pair = dict(left, id='pair', legs=['left', 'right'], before_fees=proof, default_funding_result=payoff,
                    default_funding_fee_identity=[hashed(row['trade_fee']) for row in (left, right)])
        data, options = result(left, right), ('arbs', None, 0, 25)
        with patch('app.comparison.ordinary_arb.evaluate', wraps=evaluate_arb) as evaluate:
            published = page(data, {}, options, captured_pairs=[pair], policy='policy')
            self.assertEqual(published['rows'][0]['score'], payoff['score'])
            evaluate.assert_not_called()
            page(data, {'stake': '50'}, options, captured_pairs=[pair], policy='policy')
            self.assertEqual(evaluate.call_args.args[2], 50)
            left['trade_fee'] = dict(left['trade_fee'], evidence={'fictional_rate': '0.05'})
            changed = page(data, {}, options, captured_pairs=[pair], policy='policy')
            self.assertEqual(evaluate.call_args.args[2], DEFAULT_FUNDING)
            self.assertNotEqual(changed['rows'][0]['score'], payoff['score'])

    def test_price_only_opposites_do_not_need_a_reference_or_fee_settings(self):
        a = quote('a', 'kalshi', threshold=3)
        b = quote('b', 'polymarket_us', threshold=2, operator='le')
        for row, operator in ((a, 'gt'), (b, 'lt')):
            row.pop('reference')
            row['binding'] = {'verified': True}
            row['common_odds'] = {'supported': True}
            row['occurrence_match'] = dict(status='matched', estimated=False, method='shared_provider_id')
            row['native_contract'] = {'same_outcome': {'predicate': {
                'domain': 'home_margin', 'operator': operator, 'threshold': '5/2', 'subject_id': None}}}
        (pair,) = before_fee_pairs([a, b])
        self.assertEqual(pair['before_fees']['value'], '10')
        self.assertFalse(pair['math']['available'])
        b['binding']['verified'] = False
        self.assertEqual(before_fee_pairs([a, b]), [])
