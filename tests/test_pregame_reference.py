from fractions import Fraction

from app.comparison.pregame_reference import assess, selection
from app.storage.store import stamp

AT = stamp('2026-11-16T20:04:00Z')
START = stamp('2026-11-17T00:00:00Z')
KEY = 'NCAAF', START, 'home-id', 'away-id'


def rule(*, outcomes=('home', 'away'), equality='not_possible', overtime='included', **extra):
    return dict(dict(available=True, scope='completed_full_game', overtime=overtime,
        extra_innings='not_applicable', shootout='not_applicable', shootout_count=None,
        outcomes=list(outcomes), equality=equality, equality_cashflow='full_outlay',
        void='full_outlay', cancellation='full_outlay', shortened_game='void', forfeit='void',
        refund_charges='none', evidence={'version': 'authored-rules-1'}), **extra)


def frame(*, family='moneyline', line=None, book='fanduel', prices=('-110', '-110'),
          frame_at='2026-11-16T20:03:00Z', id_='coherent', source_at='2026-11-16T20:02:00Z'):
    outcomes = ('over', 'under') if family == 'total' else ('home', 'draw', 'away') if len(prices) == 3 else ('home', 'away')
    quotes = {}
    for side, odds in zip(outcomes, prices, strict=True):
        strike = -line if family == 'spread' and side == 'away' else line
        if odds is not None:
            leg = dict(price_american=odds, source_at=source_at, received_at=frame_at, side=side,
                       line=None if strike is None else str(strike), odd_id=side)
            if len(outcomes) == 3:
                leg['partition'] = 'three_way'
            quotes[family, side, strike] = {book: [leg]}
    return dict(source='fixture', event_id='book-event', frame_id=id_,
                frame_received_at=frame_at, scheduled=True, quotes=quotes)


def choose(observations, *, rule_=None, family='moneyline', side='home', line=None, previous=(), at=AT,
           occurrence=KEY, outcomes=None):
    return selection(occurrence, family, side, line, observations, at=at, previous=previous,
                     rules_for=lambda *_: rule_ or rule(), outcomes=outcomes)


def test_priority_applies_to_opposing_outcomes_and_falls_through():
    fan = frame()
    draft = frame(book='draftkings', prices=('+120', '-125'))
    first, second = (choose([fan, draft], side=side) for side in ('home', 'away'))
    assert first['book'] == second['book'] == 'fanduel'
    assert first['snapshot_id'] == second['snapshot_id']
    assert first['probability'] == second['probability'] == '0.5'
    assert first['fair_decimal_odds'] == '2'
    assert first['prices'][0]['price_american'] == '-110'
    result = choose([frame(prices=('-110', None)), draft])
    assert result['book'] == 'draftkings'
    assert result['exclusions'] == {'fanduel': ['reference_exact_partition_incomplete']}


def test_draw_is_a_third_outcome_with_exact_rational_math():
    outcomes = ('home', 'draw', 'away')
    three_way = rule(outcomes=outcomes, equality='draw_loses', overtime='excluded')
    values = frame(prices=('+100', '+200', '+300'))
    result = choose([values], rule_=three_way, outcomes=outcomes)
    assert result['available']
    assert result['probabilities'] == {'home': '6/13', 'draw': '4/13', 'away': '3/13'}
    assert assess(result, three_way)['state_probabilities'] == {'win': '6/13', 'loss': '7/13'}
    assert not choose([values])['available']
    wrong = rule(outcomes=outcomes, equality='draw_loses', overtime='included')
    assert assess(result, wrong)['reason'] == 'settlement_scoring_mismatch'


def test_exact_line_partition_occurrence_and_withdrawal():
    short = frame(family='spread', line=Fraction(-7, 2))
    original = choose([short], family='spread', line='-3.5')
    assert original['available']
    opposite = choose([short], family='spread', side='away', line='3.5')
    assert opposite['snapshot_id'] == original['snapshot_id']
    assert not choose([short], family='spread', side='away', line='-3.5')['available']
    assert not choose([], family='spread', line='-3.5', previous=[original],
                      occurrence=('NCAAF', START, 'other-home', 'away-id'))['available']
    assert not choose([], family='spread', line='-3.5', previous=[original], at=START)['available']
    partial = dict(short, quotes={}, frame_id='partial', frame_received_at=AT.isoformat())
    clone = dict(short, frame_id='repeat', frame_received_at=AT.isoformat())
    for observations in ([partial], [clone]):
        retained = choose(observations, family='spread', line='-3.5', previous=[original])
        assert retained['snapshot_id'] == original['snapshot_id']
        assert retained['prices'] == original['prices']
    withdrawn = dict(partial, retired={('fanduel', 'home', '-7/2'): AT.isoformat()})
    assert choose([withdrawn], family='spread', line='-3.5', previous=[original])['reason'] == 'reference_quote_withdrawn'


def test_push_and_incompatible_refund_terms():
    push_rule = rule(outcomes=('over', 'under'), equality='push_refund')
    ref = choose([frame(family='total', line=45)], rule_=push_rule, family='total', side='over', line='45')
    assert ref['conditioning'] == 'if_no_push'
    blocked = assess(ref, push_rule)
    assert blocked['comparable'] and blocked['reason'] == 'push_probability_missing'
    model = dict(market=ref['market'], source='authored-same-total', version='1', probability='1/10')
    qualified = assess(ref, push_rule, refund_model=model)
    assert qualified['available']
    assert qualified['state_probabilities'] == {'win': '0.45', 'loss': '0.45', 'refund': '0.1'}
    assert assess(ref, dict(push_rule, equality_cashflow='stake_excluding_entry_charge'),
                  refund_model=model)['reason'] == 'settlement_refund_cashflows_differ'
    assert assess(ref, dict(push_rule, void='fair_market_value'),
                  refund_model=model)['reason'] == 'settlement_exceptional_cashflows_unverified_or_different'
    assert assess(ref, dict(push_rule, scope='first_half'))['reason'] == 'settlement_scoring_mismatch'


def test_invalid_duplicated_and_incoherent_inputs_cannot_become_a_reference():
    duplicate = frame()
    duplicate['quotes']['moneyline', 'away', None]['fanduel'] *= 2
    for observations in ([duplicate], [frame(prices=('-99', '-110'))],
                         [frame(prices=('-110', None)), frame(prices=(None, '-110'), id_='another')],
                         [frame(source_at='2026-11-16T19:30:00Z')]):
        assert not choose(observations)['available']


def test_publication_attaches_same_reference_to_two_placement_venues(monkeypatch):
    from app.storage.pregame_reference_publication import publish

    event = dict(id='fixture-event', competition='NCAAF', scheduled_start=START.isoformat(),
                 home='home-id', away='away-id', status={'live': False})
    market = dict(family='moneyline', period='full_game', scheduled_start=START.isoformat())

    def placement(venue, value):
        source = dict(provider=venue, native_event_id=venue + '-game')
        original = dict(value=value, units='usd_per_contract', payout='1', payout_units='USD')
        quote = dict(venue=venue, source=source, state='available', original=original,
                     times=dict(source_at=AT.isoformat(), received_at=AT.isoformat()))
        record = dict(event=event, quote=quote, market_identity=market,
                      selection=dict(predicate='win', participant='home-id', signed_line=None))
        return dict(venue=venue, source=source, start_at=START.isoformat(), league='NCAAF',
                    original=original, original_record=record)

    rows = [placement('kalshi', '0.40'), placement('polymarket_us', '0.45')]
    monkeypatch.setattr('app.storage.pregame_reference_publication.venue_rules', lambda row: (rule(), None))
    observations = {KEY: [frame(), frame(book='draftkings', prices=('+120', '-130'))]}
    publish(dict(captured_at=AT.isoformat(), quotes=rows), observations, {}, rules_for=lambda *_: rule())
    assert rows[0]['pregame_reference'] == rows[1]['pregame_reference']
    assert rows[0]['settlement_assessment']['state_probabilities'] == {'win': '0.5', 'loss': '0.5'}
    assert [Fraction(row['sportsbook_baseline']['return_percent']) for row in rows] == [25, Fraction(100, 9)]
