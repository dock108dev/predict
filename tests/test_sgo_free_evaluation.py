from datetime import datetime, timezone
from fractions import Fraction
from scripts.sgo_free_evaluation import american, eligible_pair, estimate, pair_probability, compatible_sides

NOW = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)
def quote(odds, line='2.5', clock='2026-11-10T19:59:00Z'):
    return {'available': True, 'odds': odds, 'overUnder': line, 'lastUpdatedAt': clock}

def test_proportional_arithmetic():
    assert american('+100') == Fraction(1, 2)
    assert pair_probability('-110', '-110') == Fraction(1, 2)
    assert pair_probability('+150', '-170') == Fraction(54, 139)

def test_mismatched_missing_and_stale_sides_are_not_used():
    a=quote('-110'); b=quote('-110')
    assert eligible_pair(a,b,NOW,market='ou',line='2.5')[0] == Fraction(1,2)
    assert eligible_pair(a,quote('-110','3.5'),NOW,market='ou',line='2.5')[1] == 'different line'
    assert eligible_pair(a,None,NOW)[0] is None
    assert eligible_pair(a,quote('-110',clock='2026-11-10T19:00:00Z'),NOW)[1] == 'stale or future side'
    assert eligible_pair(a,quote('-110',clock='2026-11-10T20:01:00Z'),NOW)[0] is None

def test_median_limits_outlier_and_leave_one_out():
    a={'byBookmaker': {'a':quote('-110'), 'b':quote('-110'), 'c':quote('-900')}}
    b={'byBookmaker': {'a':quote('-110'), 'b':quote('-110'), 'c':quote('+500')}}
    books, _, med=estimate(a,b,NOW)
    assert len(books)==3 and med==0.5
    books, excluded, _=estimate(a,b,NOW,exclude='c')
    assert len(books)==2 and excluded['c']=='evaluated venue excluded'


def test_incompatible_period_and_opposing_market_rejected():
    a={'oddID':'a', 'opposingOddID':'b', 'statID':'points', 'periodID':'game', 'betTypeID':'ml'}
    b={'oddID':'b', 'opposingOddID':'a', 'statID':'points', 'periodID':'game', 'betTypeID':'ml'}
    assert compatible_sides(a,b,'ml')
    assert not compatible_sides(a,{**b,'periodID':'reg'},'ml')
    assert not compatible_sides(a,{**b,'opposingOddID':'wrong'},'ml')

def test_spread_opposing_lines_must_be_exact_negatives():
    a={**quote('-110'), 'spread':'-3.5'}
    b={**quote('-110'), 'spread':'+3.5'}
    assert eligible_pair(a,b,NOW,market='sp',line='-3.5')[0] == Fraction(1,2)
    assert eligible_pair(a,{**b,'spread':'+4'},NOW,market='sp',line='-3.5')[0] is None
