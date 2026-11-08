"""Price and rank contracts for the installed EV and arbitrage lists."""
from fractions import Fraction
from unittest import TestCase

from app.comparison.snapshot_math import before_fee_pair
from app.dashboard.trade_desk import page
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
    def test_ev_groups_exact_lines_and_keeps_unknowns_out_of_rank(self):
        first = quote('first', 'kalshi', value='8')
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
        self.assertEqual(offers[0]['reference']['american'], '+110')
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
        pairs = [dict(left, id=f'pair-{left["id"]}', legs=[left['id'], right['id']],
                      before_fees=before_fee_pair(left, right, 'spread')) for left, right in ((c, d), (a, b))]
        options = ('arbs', 'gross_return_percent', 0, 25)
        view = page(result(a, b, c, d), {'positive': 'on', 'stake': '100', 'profit': '10'}, options,
                    captured_pairs=pairs, policy='policy')
        self.assertEqual([p['value'] for p in view['rows'][0]['pairs']], ['10', '-10'])
        a['price_current'] = False
        self.assertEqual(page(result(a, b, c, d), {'positive': 'on'}, options,
                              captured_pairs=pairs, policy='policy')['total'], 0)

    def test_price_only_opposites_do_not_need_a_reference_or_fee_settings(self):
        a = quote('a', 'kalshi', threshold=3)
        b = quote('b', 'polymarket_us', threshold=2, operator='le')
        for row, operator in ((a, 'gt'), (b, 'lt')):
            row.pop('reference')
            row['binding'] = {'verified': True}
            row['common_odds'] = {'supported': True}
            row['native_contract'] = {'same_outcome': {'predicate': {
                'domain': 'home_margin', 'operator': operator, 'threshold': '5/2', 'subject_id': None}}}
        (pair,) = before_fee_pairs([a, b])
        self.assertEqual(pair['before_fees']['value'], '10')
        self.assertFalse(pair['math']['available'])
        b['binding']['verified'] = False
        self.assertEqual(before_fee_pairs([a, b]), [])
