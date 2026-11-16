"""Price and rank contracts for the installed EV and arbitrage lists."""
import asyncio
import json
from fractions import Fraction
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from app.comparison.ordinary_arb import DEFAULT_FUNDING, evaluate as evaluate_arb
from app.comparison.snapshot_math import before_fee_pair
from app.dashboard.snapshot_api import mount
from app.dashboard.desk_sportsbooks import add_sgo_prices
from app.dashboard.trade_desk import game_source_key, page
from app.storage.store import hashed, stamp
from app.storage.comparison_snapshot import ORDINARY_ARB_POLICY, before_fee_pairs, pack
from app.storage.ordinary_projection import project


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


def with_verified_model(row, value):
    from app.comparison.sgo_reference import BEST_VERSION
    from app.comparison.snapshot_fee_scope import RANKING_BASIS

    row['reference'] = None
    row['reference_calculation'] = dict(available=True, method=BEST_VERSION, venue='fanduel',
                                        full_state_probability=True)
    row['conditional_return_percent'] = value
    row['metric_status']['after_trade_fee_ev'] = {'state': 'available'}
    row['conditional_trade_benchmark'] = dict(available=True, ranking_eligible=True, calibrated=True,
        execution_qualified=True, full_state_net_ev=True, verified_confidence='0.99', ranking_basis=RANKING_BASIS)
    row['trade_fee'] = dict(available=True, classification='account_reviewed', execution_qualified=True,
        funding_usd='1', winning_net_receipt_usd='2.2', quantity='1', quantity_unit='USD payout contracts',
        liquidity_role='taker', fill_count=1)
    return row


class TradeDesk(TestCase):
    def test_pregame_pages_indicative_results_by_distinct_ranked_games(self):
        first = with_verified_model(quote('first', 'novig'), '2')
        first.update(game_state='scheduled', sportsbook_return_percent='10',
                     sportsbook_baseline=dict(book='fanduel', fair_decimal_odds='2', return_percent='10'),
                     gross_return_percent='6', conservative_return_percent='1',
                     conservative_trade_benchmark=dict(first['conditional_trade_benchmark']))
        first['metric_status']['conservative_trade_fee_ev'] = {'state': 'available'}
        winner = dict(first, id='winner', market=dict(market='winner', period='full_game', line=None),
                      selection=dict(participant='home', predicate='win'), sportsbook_return_percent='4')
        second = dict(first, id='second', game_key='second', start_at='2026-11-08T02:00:00Z',
                      sportsbook_return_percent='8')
        third = dict(first, id='third', game_key='third', start_at='2026-11-08T03:00:00Z',
                     sportsbook_return_percent='-2')
        data = result(first, winner, second, third)
        data['publication']['read_at'] = '2026-11-08T00:00:00Z'
        query = dict(layout='desk', ranked='1', basis='sportsbooks', lines='main', summary='1', positive='on')
        first_page = page(data, query, ('ev', None, 0, 1))
        self.assertEqual((first_page['row_kind'], first_page['page_count'], first_page['total']), ('games', 1, 2))
        self.assertEqual([row['score'] for row in first_page['rows']], ['10', '4'])
        self.assertIsNone(first_page['calculation_reason'])
        self.assertEqual(page(data, query, ('ev', None, 1, 1))['rows'][0]['game_key'], 'second')
        for scenario, score in (('before', '6'), ('conservative', '1')):
            with self.subTest(scenario=scenario):
                scenario_page = page(data, dict(query, basis=scenario), ('ev', None, 0, 1))
                self.assertEqual(scenario_page['rows'][0]['score'], score)
        self.assertEqual(page(data, dict(query, basis='reviewed'), ('ev', None, 0, 1))['rows'], [])
        empty = page(data, dict(query, basis='reviewed', positive=''), ('ev', None, 1, 1))
        self.assertEqual((empty['page_count'], empty['total'], empty['rows']), (0, 0, []))
        self.assertNotIn('price_preview', empty)

    def test_pregame_keeps_last_known_venue_prices_after_the_entire_market_expires(self):
        venues = ('kalshi', 'polymarket_us', 'novig', 'prophetx')
        stale = [dict(quote(venue, venue, current=False), game_state='scheduled',
                      times={'received_at': '2026-11-07T23:58:00Z'},
                      sportsbook_return_percent='5',
                      sportsbook_baseline=dict(book='fanduel', fair_decimal_odds='2'),
                      trade_fee=dict(available=False))
                 for venue in venues]
        older = dict(stale[-1], id='older', times={'received_at': '2026-11-07T23:57:00Z'})
        closed = dict(stale[-1], id='closed', game_key='closed', game_state='cancelled')
        data = result(*stale, older, closed)
        data['publication']['read_at'] = '2026-11-08T00:00:00Z'
        query = dict(layout='desk', basis='sportsbooks', lines='main', summary='1')
        options = ('ev', None, 0, 12)

        browse = page(data, dict(query, browse_odds='1'), options)
        group, = browse['rows']
        self.assertEqual({offer['id'] for offer in group['offers']}, set(venues))
        self.assertTrue(all(not offer['current'] and offer['value'] is None for offer in group['offers']))
        ranked = page(data, dict(query, ranked='1'), options)
        self.assertEqual(ranked['rows'], [])
        self.assertEqual(ranked['total'], 0)
        self.assertEqual(ranked['ranked_group_count'], 0)
        self.assertEqual(ranked['calculation_reason'], 'Fresh prices are required to calculate expected value.')

        replacement = dict(stale[-1], id='new', price_current=True, current_reasons=[])
        renewed = page(dict(data, rows=[*data['rows'], replacement]), dict(query, ranked='1'), options)
        self.assertEqual(renewed['rows'][0]['id'], group['id'])
        self.assertEqual([(offer['id'], offer['value']) for offer in renewed['rows'][0]['offers']][:1],
                         [('new', '5')])
        self.assertNotIn('prophetx', {offer['id'] for offer in renewed['rows'][0]['offers']})

    def test_mlb_display_aliases_require_matching_game_numbers(self):
        from app.dashboard.snapshot_display import desk_game_aliases

        roles = {'home': 'MLB:NYY', 'away': 'MLB:BOS'}
        start = '2026-11-08T01:00:00Z'
        event = dict(competition='MLB', scheduled_start=start,
                     participants={'New York Yankees': roles['home'], 'Boston Red Sox': roles['away']},
                     source_participant_roles=roles, game_number=1, **roles)
        first, second = 'kalshi-game', 'polymarket-game'
        rows = [dict(game_key=first, source=dict(provider='kalshi', native_event_id=first)),
                dict(game_key=second, source=dict(provider='polymarket_us', native_event_id=second))]
        games = {key: dict(league='MLB', start_at=start,
                           participants=[dict(id=team, role=role) for role, team in roles.items()])
                 for key in (first, second)}
        facts = {('kalshi', first): event, ('polymarket_us', second): dict(event)}
        self.assertEqual(desk_game_aliases(rows, games, facts), {second: first})
        facts['polymarket_us', second]['game_number'] = 2
        self.assertEqual(desk_game_aliases(rows, games, facts), {})
        facts['polymarket_us', second].pop('game_number')
        self.assertEqual(desk_game_aliases(rows, games, facts), {})

    def test_pregame_display_joins_witnessed_occurrence_without_changing_offer_identity(self):
        from app.storage.schedule_metadata import VERSION

        roles = {'home': 'NFL:BUF', 'away': 'NFL:NYJ'}
        teams = ['Buffalo Bills', 'New York Jets']
        start = '2026-11-08T01:00:00Z'
        event = dict(competition='NFL', scheduled_start=start, participants=dict(zip(teams, roles.values())),
                     source_participant_roles=roles, **roles)
        first = dict(quote('native', 'kalshi'), game_key='native-current:game', league='NFL', start_at=start,
                     game_state='scheduled', selection=dict(participant=roles['home'], predicate='cover',
                     signed_line='-2.5'), source=dict(provider='kalshi', native_event_id='native',
                     native_market_id='spread', native_outcome_id='home'), _desk_event=event)
        received = '2026-11-08T00:00:00Z'
        schedule = dict(version=VERSION, native_event_id='retained', authority=['sportsgameodds', 'event', 'retained'],
                        start=start, received_at=received,
                        proofs=[dict(body_sha256='a'*64, path='sportsgameodds/receipt', received_at=received)])
        aggregate_event = dict(event, id='retained', schedule_metadata=dict(schedule, revision=hashed(schedule)))
        del aggregate_event['source_participant_roles']
        other = dict(first, id='aggregate', venue='novig', game_key='sealed', source=dict(first['source'],
                     provider='sportsgameodds', native_event_id='retained'), _desk_event=aggregate_event)
        away = dict(other, id='away', selection=dict(participant=roles['away'], predicate='cover', signed_line='2.5'))
        alternate = dict(other, id='alternate', selection=dict(other['selection'], signed_line='-7.5'))
        data = result(first, other, away, alternate)
        data['publication']['read_at'] = received
        data['games'] = [dict(game_key=key, league='NFL', start_at=start, title='Matchup', participants=[
            dict(id=team, name=name, role=role) for (role, team), name in zip(roles.items(), teams)])
            for key in (first['game_key'], other['game_key'])]
        query = dict(layout='desk', browse_odds='1', lines='main', summary='1')
        first_page = page(data, query, ('ev', None, 0, 10))
        self.assertEqual(first_page['total'], 1)
        self.assertEqual({row['game_key'] for row in first_page['rows']}, {'sealed'})
        by_line = {row['offers'][0]['selection']['signed_line']: row for row in first_page['rows']}
        self.assertEqual(set(by_line), {'-2.5', '2.5'})
        self.assertEqual({item['id'] for item in by_line['-2.5']['offers']}, {'native', 'aggregate'})
        self.assertEqual(first['game_key'], 'native-current:game')
        from app.dashboard.snapshot_display import outcome_id, outcome_key
        linked = page(data, dict(query, game_key=first['game_key'], line=outcome_id(outcome_key(first))),
                      ('ev', None, 0, 10))
        self.assertEqual(linked['selected_game_key'], 'sealed')
        self.assertEqual(linked['selected_line_id'], by_line['-2.5']['id'])
        for row in (other, away, alternate):
            row['_desk_event'] = dict(aggregate_event, source_participant_roles={'home': roles['away'], 'away': roles['home']})
        self.assertEqual(page(data, query, ('ev', None, 0, 10))['total'], 2)

    def test_empty_opportunities_explain_unavailable_ranking_without_listing_prices(self):
        current = quote('current', 'kalshi', value='12')
        expired = quote('expired', 'polymarket_us', current=False)
        data = result(current, expired)
        query = {'layout': 'desk', 'ranked': '1', 'phase': '', 'basis': 'before', 'lines': 'main', 'summary': '1'}
        view = page(data, query, ('ev', None, 0, 25))
        self.assertEqual(view['rows'], [])
        self.assertEqual(view['total'], 0)
        self.assertNotIn('price_preview', view)
        self.assertIsNotNone(view['calculation_reason'])
        self.assertEqual(page(data, dict(query, positive='on'), ('ev', None, 0, 25))['rows'], [])

    def test_three_current_sites_per_exact_outcome_before_rank_and_pagination(self):
        def spread(id_, venue, line, value, *, away=False, current=True):
            row = quote(id_, venue, value=value, current=current)
            row['market']['line'] = str(abs(Fraction(line)))
            row['selection'].update(participant='away' if away else 'home', signed_line=line)
            return with_verified_model(row, value)

        data = result(
            spread('thin-high', 'novig', '-7.5', '99'),
            spread('thin-stale', 'polymarket_us', '-7.5', None, current=False),
            spread('main-home', 'novig', '-2.5', '0'),
            spread('main-away', 'novig', '2.5', '-3', away=True),
            spread('main-away-kalshi', 'kalshi', '2.5', '-4', away=True),
            spread('alt-home', 'novig', '-3.5', '10'),
            spread('alt-other-side', 'novig', '3.5', '12', away=True),
            spread('reversed-favorite', 'novig', '2.5', '11'),
        )
        data['games'] = [dict(game_key='game', participants=[dict(id='home', role='home'), dict(id='away', role='away')])]
        def enrich(out, *, include_retained):
            prices = dict(
                fanduel=[dict(price_american='-110', current=True), dict(price_american='-105', current=True)],
                draftkings=[dict(price_american='-110', current=True)],
            )
            for group in out['rows']:
                lead = group['offers'][0]['id']
                chosen = dict(prices)
                if lead in ('thin-high', 'alt-other-side'):
                    chosen['draftkings'] = [dict(price_american='-110', current=False)]
                elif lead == 'main-home':
                    chosen['betmgm'] = prices['draftkings']
                group['sportsbook_quotes'].update(chosen)

        query = {'layout':'desk', 'ranked':'1', 'phase':'', 'basis':'reviewed', 'lines':'main', 'last_known':'1'}
        def read(**changes):
            return page(data, dict(query, **changes), ('ev', None, 0, 10), enrich=enrich)
        first = page(data, query, ('ev', None, 0, 1), enrich=enrich)
        self.assertEqual((first['total'], first['rows'][0]['score']), (2, '0'))
        self.assertEqual(set(first['rows'][0]['sportsbook_quotes']), {'fanduel', 'draftkings', 'betmgm'})
        self.assertEqual([g['score'] for g in read()['rows']], ['0', '-3'])
        self.assertEqual([g['score'] for g in read(lines='all')['rows']], ['11', '10', '0', '-3'])
        self.assertEqual(read(positive='on')['total'], 0)
        alternate = read(lines='all')['rows'][1]['id']
        game = read(browse_odds='1', ranked='0', game_key='game', line=alternate)
        self.assertEqual(game['selected_line_id'], alternate)
        self.assertIn(alternate, {row['id'] for row in game['rows']})

    def test_browse_retains_quotes_when_runtime_authority_is_lost(self):
        live = quote('live', 'novig', value='20')
        saved = quote('saved', 'prophetx', current=False)
        data = result(live, saved)
        options = ('ev', None, 0, 10)
        query = {'layout':'desk', 'browse_odds':'1', 'basis':'before', 'lines':'main', 'phase':''}
        thin = page(data, query, options)
        self.assertTrue(thin['limited_coverage'])
        self.assertEqual([offer['id'] for offer in thin['rows'][0]['offers']], ['live'])
        self.assertEqual(thin['rows'][0]['retained_venues'], ['prophetx'])
        live.update(probability='1/2', evidence_result_id='capture', reference=None,
                    reference_calculation=dict(available=True, method='sgo-best-payout-proportional-1', venue='fanduel'),
                    trade_fee=dict(available=True, evidence={'version':'fee-review'}))
        overview = page(data, dict(query, summary='1', last_known='1'), options)
        group = overview['rows'][0]
        self.assertNotIn('retained_venues', group)
        self.assertEqual([item['id'] for item in group['offers']], ['live'])
        brief = group['offers'][0]
        self.assertEqual(brief['fair_odds']['american'], '+100')
        self.assertEqual(brief['evidence_result_id'], 'capture')
        for field in ('trade_fee', 'sportsbook', 'reference_calculation', 'source_at', 'last_known_ev'):
            self.assertNotIn(field, brief)
        def enrich(out, *, include_retained):
            self.assertFalse(include_retained)
            out['rows'][0]['sportsbook_quotes'] = dict(
                fanduel=[dict(price_american='-110', current=True, proof='full evidence')],
                draftkings=[dict(price_american='-105', current=False)])
        legacy_query = {key: value for key, value in query.items() if key != 'lines'}
        public = page(data, dict(legacy_query, summary='1', last_known='1'), options, enrich=enrich)
        self.assertEqual(public['rows'][0]['sportsbook_quotes'],
                         {'fanduel': [dict(current=True, price_american='-110', source_at=None)],
                          'draftkings': [dict(current=False, price_american='-105', source_at=None)]})
        explicit = page(data, dict(query, last_known='1'), options)
        self.assertEqual({offer['id'] for offer in explicit['rows'][0]['offers']}, {'live', 'saved'})
        data['rows'] = [dict(live, price_current=False, current_reasons=['data_runtime_unhealthy']), saved]
        for runtime in ({'healthy':False}, {'healthy':True, 'active':False, 'reason':'data_runtime_not_dispatching'}):
            with self.subTest(runtime=runtime):
                data['publication']['data_runtime'] = runtime
                fallback = page(data, query, options)
                self.assertTrue(fallback['retained_fallback'])
                self.assertEqual({offer['id'] for offer in fallback['rows'][0]['offers']}, {'live', 'saved'})
                self.assertIsNone(fallback['rows'][0]['score'])
                self.assertTrue(all(not offer['current'] and offer['value'] is None for offer in fallback['rows'][0]['offers']))
                ranked = page(data, {'layout':'desk', 'ranked':'1', 'phase':'', 'basis':'before', 'lines':'main'}, options)
                self.assertEqual(ranked['rows'], [])
                self.assertEqual(page(data, dict(query, summary='1', last_known='1'), options)['rows'], [])

    def test_live_desk_prefers_direct_exchange_sources_even_with_retained_prices(self):
        direct = dict(quote('direct', 'kalshi'), source={'provider': 'kalshi'})
        aggregate = dict(quote('aggregate', 'kalshi'), source={'provider': 'sportsgameodds'})
        other = dict(quote('novig', 'novig'), source={'provider': 'sportsgameodds'})
        out = page(result(direct, aggregate, other), {'layout':'desk', 'last_known':'1'}, ('ev', None, 0, 10))
        self.assertEqual({q['id'] for g in out['rows'] for q in g['offers']}, {'direct', 'novig'})

    def test_public_odds_show_fair_reference_and_exact_last_known_native_prices(self):
        live = dict(quote('novig', 'novig'), sportsbook_return_percent='4',
                    sportsbook_baseline=dict(book='draftkings', fair_decimal_odds='2.1',
                                             prices=[dict(price_american='+104')]))
        saved = dict(quote('poly', 'polymarket_us', current=False), source={'provider': 'polymarket_us'})
        other = dict(quote('other', 'kalshi', current=False), source={'provider': 'kalshi'}, alternate=True)
        other['market']['line'] = '3.5'
        other['selection']['signed_line'] = '-3.5'
        alias = dict(quote('alias', 'kalshi'), source={'provider': 'sportsgameodds'})
        data = result(live, saved, other, alias)
        query = dict(layout='desk', browse_odds='1', basis='sportsbooks', lines='main', summary='1')

        groups = page(data, query, ('ev', None, 0, 10))['rows']
        self.assertEqual(len(groups), 1)
        offers = {offer['id']: offer for offer in groups[0]['offers']}
        self.assertEqual(set(offers), {'novig', 'poly'})
        self.assertEqual(offers['novig']['fair_odds']['american'], '+110')
        self.assertEqual(offers['novig']['fair_reference'], {'books': ['draftkings'], 'method': 'single',
            'indicative': True, 'selected_prices': {'draftkings': '+104'}})
        self.assertFalse(offers['poly']['current'])
        self.assertIsNone(offers['poly']['value'])
        self.assertIsNone(offers['poly']['fair_reference'])
        all_lines = page(data, dict(query, lines='all'), ('ev', None, 0, 10))['rows']
        self.assertEqual({offer['id'] for group in all_lines for offer in group['offers']}, {'novig', 'poly', 'other'})

    def test_browse_keeps_current_native_games_on_a_mixed_coverage_slate(self):
        covered = [quote(venue, venue, value='1') for venue in ('novig', 'prophetx', 'kalshi')]
        native = [dict(quote(f'native-{venue}', venue, value='1'), game_key=venue,
                       source={'provider': venue}) for venue in ('kalshi', 'polymarket_us')]
        data = result(*covered, *native)
        options = ('ev', None, 0, 10)
        query = {'layout': 'desk', 'basis': 'before', 'lines': 'main', 'phase': ''}

        browse = page(data, dict(query, browse_odds='1'), options)
        self.assertEqual(browse['total'], 3)
        self.assertTrue(browse['limited_coverage'])
        self.assertEqual({offer['id'] for group in browse['rows'] for offer in group['offers'] if offer['current']},
                         {row['id'] for row in (*covered, *native)})
        ranked = page(data, dict(query, ranked='1'), options)
        self.assertEqual(ranked['rows'], [])
        self.assertEqual(ranked['total'], 0)

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
        occurrence = ('NBA', stamp(start), 'home', 'away')
        candidate = dict(valid=True, occurrence=occurrence)
        fact = dict(venue='fanduel', period='game', price_american='-132', starts_at=start,
                    source_at=source_at, received_at=source_at, league='NBA', market='moneyline',
                    phase='pregame', side='home', line=None, odd_id='sgo-moneyline', available=True)
        book = dict(id='book-row', revision='revision', facts=fact)
        frame = dict(facts=dict(starts_at=start, members=[['book-row', 'revision']], received_at=source_at))
        options = ('ev', None, 0, 10)
        inputs = Mock()
        inputs.frames.side_effect = lambda event_ids: {key: frame for key in event_ids}
        inputs.quotes.side_effect = lambda event_ids, **kwargs: {key: [book] for key in event_ids}
        db = Mock()
        for state, retained, duplicates, expected_current in [
            ({'state':'available'}, False, False, True),
            ({'state':'budget_delayed', 'reason_code':'sgo_charge_unresolved'}, True, False, False),
            ({'state':'budget_delayed', 'reason_code':'sgo_charge_unresolved'}, False, False, None),
            ({'state':'available'}, False, True, None),
        ]:
            with self.subTest(state=state, retained=retained, duplicates=duplicates):
                matches = {'sgo-game': candidate}
                if duplicates:
                    matches['another-event'] = candidate
                inputs.occurrences.return_value = {occurrence: matches}
                out = page(data, {'browse_odds':'1'}, options)
                add_sgo_prices(db, out, data['rows'], {'sportsgameodds':state}, at=at, include_retained=retained,
                               sgo_inputs=inputs)
                groups = {g['offers'][0]['id']:g for g in out['rows']}
                prices = groups['native-home']['sportsbook_quotes'].get('fanduel', [])
                self.assertEqual([p['current'] for p in prices], [] if expected_current is None else [expected_current])
                self.assertEqual(groups['native-no']['sportsbook_quotes'], {})
                self.assertIsNone(groups['native-home']['offers'][0]['value'])
                self.assertIsNone(groups['native-home']['score'])

        source = dict(provider='sportsgameodds', native_event_id='sgo-game', native_outcome_id='retail-alt-id')
        mixed = dict(data, rows=[*data['rows'], dict(home, id='sgo-home', venue='novig', source=source)])
        inputs.occurrences.return_value = {occurrence: {'sgo-game': candidate}}
        out = page(mixed, {'browse_odds':'1'}, options)
        add_sgo_prices(db, out, mixed['rows'], {'sportsgameodds':{'state':'available'}}, at=at,
                       include_retained=False, sgo_inputs=inputs)
        group = next(group for group in out['rows'] if len(group['offers']) == 2)
        self.assertEqual(group['sportsbook_quotes']['fanduel'][0]['match'], 'schedule_and_teams')

        shifted = '2026-11-08T01:01:00Z'
        moved_fact = dict(fact, starts_at=shifted)
        moved_frame = dict(facts=dict(frame['facts'], starts_at=shifted))
        inputs.occurrences.return_value = {}
        inputs.frames.side_effect = lambda event_ids: {key: moved_frame for key in event_ids}
        inputs.quotes.side_effect = lambda event_ids, **kwargs: {key: [dict(book, facts=moved_fact)] for key in event_ids}
        mixed['rows'][-1]['source'] = dict(source, native_outcome_id=moved_fact['odd_id'])
        out = page(mixed, {'browse_odds':'1'}, options)
        add_sgo_prices(db, out, mixed['rows'], {'sportsgameodds':{'state':'available'}}, at=at,
                       include_retained=True, sgo_inputs=inputs)
        group = next(group for group in out['rows'] if len(group['offers']) == 2)
        self.assertEqual(group['sportsbook_quotes'], {})

    def test_native_short_names_are_searchable_by_canonical_team_names(self):
        row = quote('current', 'polymarket_us')
        row.update(league='NHL', game_title='Hurricanes at Kraken')
        data = result(row)
        data['games'] = [dict(game_key='game', league='NHL', title=row['game_title'], participants=[
            dict(id='NHL:CAR', name='Hurricanes'), dict(id='NHL:SEA', name='Kraken'),
        ])]
        options = ('ev', None, 0, 25)
        for search in ('Carolina Seattle', 'Hurricanes Kraken', 'Hurricanes vs Kraken',
                       'Carolina Hurricanes vs. Seattle Kraken', 'Kraken@Hurricanes'):
            self.assertEqual(page(data, {'search': search}, options)['matched_offer_count'], 1)
        for search in ('Boston Seattle', 'Boston vs Seattle', 'Carolina vs Hurricanes'):
            self.assertEqual(page(data, {'search': search}, options)['matched_offer_count'], 0)

    def test_browse_site_filter_keeps_main_and_linked_exact_outcomes(self):
        main = [dict(quote(venue, venue), game_state='scheduled')
                for venue in ('novig', 'prophetx')]
        alternate = dict(quote('alt', 'kalshi'), game_state='scheduled', alternate=True,
                         market=dict(market='spread', period='full_game', line='9.5'),
                         selection=dict(participant='home', predicate='cover', signed_line='9.5'))
        data = result(*main, alternate)
        data['publication']['read_at'] = '2026-11-08T00:00:00Z'
        query = dict(layout='desk', browse_odds='1', summary='1', lines='main')
        options = ('ev', None, 0, 12)

        original, = page(data, query, options)['rows']
        filtered = page(data, dict(query, venue='kalshi,polymarket_us'), options)
        same, = filtered['rows']
        self.assertEqual(same['id'], original['id'])
        self.assertEqual(same['offers'][0]['selection']['signed_line'], '-2.5')
        self.assertEqual(filtered['selected_venues'], ['kalshi', 'polymarket_us'])
        self.assertTrue(set(filtered['selected_venues']).isdisjoint(offer['venue'] for offer in same['offers']))
        alternates = page(data, dict(query, venue='kalshi', lines='all', game_key='game'), options)
        exact, = alternates['rows']
        self.assertEqual(exact['offers'][0]['selection']['signed_line'], '9.5')
        linked = page(data, dict(query, venue='polymarket_us', game_key='game', line=exact['id']), options)
        self.assertEqual(linked['selected_line_id'], exact['id'])
        self.assertEqual({row['id'] for row in linked['rows']}, {original['id'], exact['id']})

    def test_empty_filter_and_unavailable_rank_have_distinct_pre_threshold_counts(self):
        options = ('ev', 'gross_return_percent', 0, 25)
        negative = with_verified_model(quote('negative', 'kalshi'), '-2')
        unranked = quote('unranked', 'polymarket_us')
        for query, expected in [({'search': 'unknown'}, (0, 0)), ({'venue': 'kalshi'}, (1, 1)),
                                ({'venue': 'polymarket_us'}, (1, 0))]:
            view = page(result(negative, unranked), dict(query, basis='reviewed', positive='on'), options)
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
        view = page(result(other, first), {'basis':'sportsbooks'}, options)
        self.assertEqual(view['coverage']['sportsbooks'], 1)
        self.assertEqual(view['coverage']['before'], 0)
        self.assertIsNone(view['rows'][0]['score'])
        self.assertEqual(view['rows'][0]['offers'][0]['value'], '10')
        self.assertEqual(view['rows'][0]['offers'][0]['sportsbook']['book'], 'fanduel')
        self.assertIsNone(view['rows'][0]['offers'][1]['value'])

    def test_browse_shows_published_sportsbook_ev_after_its_authority_expires(self):
        captured_at = '2026-11-08T00:00:00+00:00'
        deadline = '2026-11-08T00:15:00+00:00'
        dependency = ['price', 'contract', 'event', 'aggregate:frame']
        saved = quote('saved', 'novig')
        saved.update(captured_at=captured_at, settings_revision='settings', evidence_result_id='member',
            current_authority=dict(price=dict(dependency='quote', expected=dependency, current_until=deadline,
                                               lifecycle={'state':'scheduled'}),
                                   references=[], reference_required=False, fee_until=None, conservative_fee_until=None),
            sportsbook_baseline=dict(book='fanduel', frame_id='frame', fair_decimal_odds='2',
                                     return_percent='0', current_until=deadline,
                                     prices=[dict(source_at=captured_at), dict(source_at=captured_at)]))
        data = dict(result(saved), captured_at=captured_at, pairs=[], assumptions={'revision':'settings'},
                    publication={'epoch':'epoch', 'policy':'policy', 'finance':'ready'})
        owner = {'active':True, 'healthy':True}
        sources = {'novig':{'state':'available'}}
        query = {'layout':'desk', 'browse_odds':'1', 'basis':'sportsbooks', 'lines':'main', 'last_known':'1'}
        options = ('ev', None, 0, 10)

        def read(at, runtime=owner, **changes):
            return project(dict(data, **changes), {'quote':dependency}, runtime, sources, at=stamp(at),
                           policy='policy', epoch='epoch', retain_sportsbook_ev=True)

        current = page(read(captured_at), query, options)['rows'][0]
        self.assertIsNone(current['score'])
        self.assertEqual(current['offers'][0]['value'], '0')
        self.assertNotIn('last_known_ev', current['offers'][0])
        expired = read('2026-11-08T00:16:00+00:00')
        fallback = page(expired, query, options)['rows'][0]
        self.assertIsNone(fallback['score'])
        self.assertIsNone(fallback['offers'][0]['value'])
        self.assertEqual(fallback['offers'][0]['last_known_ev'], '0')
        outage = read('2026-11-08T00:16:00+00:00', {'active':False, 'healthy':False})
        automatic = page(outage, dict(query, last_known='0'), options)
        self.assertTrue(automatic['retained_fallback'])
        self.assertEqual(automatic['rows'][0]['offers'][0]['last_known_ev'], '0')
        self.assertNotIn('last_known_ev', page(expired, dict(query, basis='reviewed'), options)['rows'][0]['offers'][0])
        ranked = page(expired, dict(query, browse_odds='0', ranked='1'), options)
        self.assertFalse(ranked['rows'])
        failed = read('2026-11-08T00:16:00+00:00', _failed_price_members=['member'])
        self.assertNotIn('last_known_ev', page(failed, query, options)['rows'][0]['offers'][0])

    def test_qualified_sgo_rank_is_independent_of_historical_reference_setting(self):
        from app.comparison.sgo_reference import BEST_VERSION

        row = with_verified_model(quote('current', 'kalshi'), '8')
        row['current_authority']['reference_method'] = BEST_VERSION
        published = dict(result(row), assumptions={'benchmark_venue':'novig'})
        view = page(published, {'basis':'reviewed','positive':'on'}, ('ev',None,0,25))
        self.assertEqual(view['rows'][0]['score'], '8')
        row['conditional_trade_benchmark']['verified_confidence'] = '0.989'
        quotes = page(published, {'basis':'reviewed'}, ('ev',None,0,25))
        self.assertIsNone(quotes['rows'][0]['score'])
        self.assertEqual(quotes['rows'][0]['offers'][0]['effective_quote']['decimal_odds'], '2.2')

    def test_aggregate_venue_keeps_provider_attribution(self):
        row = quote('sgo', 'kalshi')
        row['source'] = {'provider': 'sportsgameodds'}
        view = page(result(row), {}, ('ev', 'gross_return_percent', 0, 25))
        self.assertEqual(view['rows'][0]['offers'][0]['source_provider'], 'sportsgameodds')

    def test_ev_groups_exact_lines_and_keeps_unknowns_out_of_rank(self):
        first = dict(with_verified_model(quote('first', 'kalshi'), '8'), probability='100/223')
        second = with_verified_model(quote('second', 'polymarket_us'), '0')
        retained = quote('retained', 'novig', value='99', current=False)
        other = with_verified_model(quote('other', 'kalshi'), '-2')
        other['selection']['signed_line'] = '-3.5'
        data = result(retained, other, second, first)
        options = ('ev', 'gross_return_percent', 0, 25)
        view = page(data, {'day': '2026-11-07', 'timezone': 'America/New_York','basis':'reviewed'}, options)
        self.assertEqual([g['score'] for g in view['rows']], ['8', '-2'])
        offers = view['rows'][0]['offers']
        self.assertEqual([q['value'] for q in offers], ['8', '0', None])
        self.assertEqual(offers[0]['reference']['american'], '+123')
        self.assertEqual(offers[2]['reason'], 'Price expired')
        self.assertEqual(page(data, {'positive': 'on','basis':'reviewed'}, options)['total'], 1)

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

    def test_pair_uses_exact_funding_and_reports_insufficient_top_of_book_depth(self):
        left = quote('left', 'kalshi', threshold=3)
        right = quote('right', 'polymarket_us', threshold=2, operator='le')
        at = '2026-11-07T23:00:00+00:00'
        for row in (left, right):
            row.update(times={'received_at':at}, source={'provider':'practice'}, trade_fee=dict(
                available=True, classification='synthetic',
                fee_cashflows={'at_fill_usd':'0'}, evidence={'fictional_rate':'0'}))
        proof = before_fee_pair(left, right, 'spread')
        proof['depth_evidence'] = [
            dict(price='5/11', quantity='25', received_at=at),
            dict(price='5/11', quantity='120', received_at=at),
        ]
        payoff = evaluate_arb(proof, [left, right], DEFAULT_FUNDING)['retail_payoff']
        self.assertEqual(payoff['execution_reason'], 'pair_execution_depth_insufficient')
        self.assertEqual([leg['depth_status'] for leg in payoff['legs']], ['insufficient', 'available'])
        self.assertEqual(Fraction(payoff['minimum_net_payout_usd']) - Fraction(payoff['funding_usd']), 10)
        self.assertFalse(payoff['full_arbitrage_qualified'])
        # Half of a one-cent stake rounds half-even to zero, so there is no two-leg trade.
        unavailable = evaluate_arb(proof, [left, right], Fraction(1,100))['retail_payoff']
        self.assertEqual(unavailable['reason'], 'pair_stake_rounds_to_zero')

    def test_positive_filter_hides_negative_reverse_and_counts_blocked_legs(self):
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
        self.assertEqual([p['value'] for p in view['rows'][0]['pairs']], ['10'])
        self.assertEqual(Fraction(view['rows'][0]['score']), Fraction(900, 101))
        excluded = page(result(a, b, c, d), {'positive': 'on', 'profit': '10'}, options,
                        captured_pairs=pairs, policy='policy')
        self.assertEqual(excluded['total'], 0)
        self.assertEqual(excluded['eligible_pair_count'], 2)
        a['price_current'] = False
        filtered = page(result(a, b, c, d), {'positive': 'on'}, options,
                        captured_pairs=pairs, policy='policy')
        self.assertEqual(filtered['total'], 0)
        self.assertEqual(filtered['pair_status']['withheld'], 1)
        all_pairs = page(result(a, b, c, d), {'ranked': '1'}, options,
                         captured_pairs=pairs, policy='policy')
        payoff, blocked = all_pairs['rows'][0]['pairs']
        self.assertLess(Fraction(payoff['score']), 0)
        self.assertEqual(blocked['retail_payoff']['reason'], 'pair_leg_stale_or_replaced')
        self.assertIsNone(blocked['score'])

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

    def test_live_arb_lists_read_published_payoff_and_withdraw_replaced_fees(self):
        left = quote('left', 'novig', threshold=3)
        right = quote('right', 'prophetx', threshold=2, operator='le')
        for row in (left, right):
            row.update(game_state='scheduled', source={'provider': 'practice'}, trade_fee=dict(available=True,
                classification='synthetic', evidence={'fictional_rate': '0.01'}, fee_cashflows={'at_fill_usd': '0'}))
        proof = before_fee_pair(left, right, 'spread')
        payoff = evaluate_arb(proof, (left, right), DEFAULT_FUNDING)
        pair = dict(left, id='pair', legs=['left', 'right'], before_fees=proof, default_funding_result=payoff,
                    evidence_result_id='immutable-member',
                    default_funding_fee_identity=[hashed(row['trade_fee']) for row in (left, right)])
        data, options = dict(result(left, right), captured_at='2026-11-08T00:00:00+00:00'), ('arbs', None, 0, 25)
        with patch('app.comparison.ordinary_arb.evaluate', side_effect=AssertionError('live list must read published payoff')):
            published = page(data, {'stake': '50'}, options, captured_pairs=[pair], policy='policy', published_only=True)
            shown = published['rows'][0]['pairs'][0]
            self.assertEqual(published['ranking_stake'], '100')
            self.assertEqual(shown['score'], payoff['score'])
            self.assertEqual(shown['retail_payoff'], payoff['retail_payoff'])
            self.assertEqual(shown['evidence_result_id'], 'immutable-member')
            overview = page(data, {'summary':'1'}, options, captured_pairs=[pair], policy='policy', published_only=True)
            short_pair = overview['rows'][0]['pairs'][0]
            self.assertEqual({k:v for k,v in short_pair.items() if k != 'retail_payoff'},
                dict(id='pair', evidence_result_id='immutable-member', legs=['left', 'right'], score=payoff['score']))
            net = short_pair['retail_payoff']
            self.assertTrue(net['available'])
            self.assertEqual(Fraction(net['minimum_net_payout_usd']) - Fraction(net['funding_usd']),
                             Fraction(net['minimum_net_profit_usd']))
            self.assertFalse(net['full_arbitrage_qualified'])
            self.assertIn('cancellation', net['states_unverified'])
            left['trade_fee'] = dict(left['trade_fee'], evidence={'fictional_rate': '0.05'})
            changed = page(data, {}, options, captured_pairs=[pair], policy='policy', published_only=True)
            withdrawn = changed['rows'][0]['pairs'][0]
            self.assertIsNone(withdrawn['score'])
            self.assertEqual(withdrawn['retail_payoff'], dict(available=False, reason='pair_fee_publication_pending', legs=[]))

    def test_selected_stake_reuses_exact_pair_member_and_existing_evaluator(self):
        at = '2026-11-07T23:00:00+00:00'
        left = quote('left', 'novig', threshold=3)
        right = quote('right', 'prophetx', threshold=2, operator='le')
        for row in (left, right):
            row.update(source={'provider':'practice'}, trade_fee=dict(available=True, classification='synthetic',
                evidence={'fictional_rate':'0.01'}), current_authority={'price': {'lifecycle': {'state':'scheduled'}}})
        proof = dict(before_fee_pair(left, right, 'spread'), authority={'policy':ORDINARY_ARB_POLICY})
        pair = dict(id='pair', kind='pair', legs=['left', 'right'], before_fees=proof,
                    default_funding_result=evaluate_arb(proof, [left, right], DEFAULT_FUNDING))
        data = dict(id='member', captured_at=at, rows=[left, right], pairs=[pair])
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = {'result': pack(data)}
        app = web.Application()
        mount(app)
        route = next(item for item in app.router.routes() if item.method == 'GET'
                     and item.resource.canonical == '/api/comparison-snapshot/details')
        request = make_mocked_request('GET', '/api/comparison-snapshot/details?id=pair&result_id=member'
                                     '&lease_id=lease&stake=150', app=app)
        with patch('app.dashboard.snapshot_api.connect') as connect, \
                patch('app.storage.comparison_snapshot.retain_evidence') as retain, \
                patch('app.comparison.ordinary_arb.evaluate', wraps=evaluate_arb) as evaluate:
            connect.return_value.__enter__.return_value = db
            response = asyncio.run(route.handler(request))
            retain.assert_called_once_with(db, 'member', 'lease')
            evaluate.assert_called_once()
            self.assertEqual(evaluate.call_args.args[2], 150)
            self.assertEqual([leg['id'] for leg in evaluate.call_args.args[1]], ['left', 'right'])
            expected = evaluate_arb(proof, [left, right], Fraction(150))
            self.assertEqual(json.loads(response.body), dict(id='pair', evidence_result_id='member',
                **expected, provider_requests=0))
            evaluate.reset_mock()
            detail = make_mocked_request('GET', '/api/comparison-snapshot/details?layout=desk&id=pair'
                                         '&result_id=member&lease_id=lease', app=app)
            opened = json.loads(asyncio.run(route.handler(detail)).body)
            evaluate.assert_not_called()
            self.assertEqual(opened['inspection'], pair['default_funding_result']['inspection'])
            self.assertEqual(opened['retail_payoff'], pair['default_funding_result']['retail_payoff'])
            self.assertEqual([leg['id'] for leg in opened['offers']], ['left', 'right'])

    def test_failed_component_withdraws_economics_but_keeps_valid_prices_and_peers(self):
        rows = [quote('failed', 'novig', value='6'), quote('healthy', 'prophetx', value='3')]
        for row in rows:
            row.update(settings_revision='settings', evidence_result_id=row['id'] + '-member',
                current_authority=dict(price=dict(dependency=row['id'], expected=['price', 'contract', 'event'],
                    current_until='2026-11-08T00:30:00+00:00', lifecycle={'state':'scheduled'}),
                    references=[], reference_required=False, fee_until=None, conservative_fee_until=None))
        state = dict(rows=rows, pairs=[], assumptions={'revision':'settings'},
            publication={'epoch':'epoch', 'policy':'policy', 'finance':'failed'},
            _failed_price_members=['failed-member'])
        projected = project(state, {row['id']:row['current_authority']['price']['expected'] for row in rows},
            {'active':True, 'healthy':True}, {row['venue']:{'state':'available'} for row in rows},
            at=stamp('2026-11-08T00:00:00+00:00'), policy='policy', epoch='epoch')
        failed, healthy = projected['rows']
        self.assertEqual(projected['publication']['current_prices'], 2)
        self.assertTrue(failed['price_current'] and healthy['price_current'])
        self.assertIsNone(failed['gross_return_percent'])
        self.assertEqual(failed['current_reasons'], ['ordinary_price_capture_failed'])
        self.assertEqual(healthy['gross_return_percent'], '3')
        self.assertEqual(healthy['current_reasons'], [])

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
        b['same_outcome']['key'][-2] = ['excluded']
        blocked, = before_fee_pairs([a, b])
        self.assertEqual(blocked['before_fees']['blocker'], 'pair_settlement_unverified')
        self.assertEqual(blocked['before_fees']['scoring_scopes'],
                         [dict(overtime='included'),dict(overtime='excluded')])
        desk = page(result(a, b), {'ranked':'1'}, ('arbs', None, 0, 25),
                    captured_pairs=[blocked], policy='policy')
        self.assertEqual(desk['rows'][0]['pairs'][0]['retail_payoff']['reason'], 'pair_settlement_unverified')
        b['binding']['verified'] = False
        self.assertEqual(before_fee_pairs([a, b]), [])
