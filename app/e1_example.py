"""One wholly synthetic ATL/PIT NFL pregame event. No provider or strategy IO."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import json

from app.arbitrage_example import synthetic_inputs, NOW
from app.storage.replay import detector_audit, replay as replay_detector
from app.edge_contracts import (MarketTerms, ReferenceQuote, FairPrice, Economics,
    Arbitrage, Mispricing, LeadLag, MakerValue, Status, reference_decisions, dumps, loads)
from app.models.core import (Venue, MarketType, Probability, Quantity, OrderBook,
    OutcomeBook, Ladder, BookLevel, Depth)


def fixture():
    parents, matcher, observations, contexts, rows = synthetic_inputs()
    event_id = next(iter(parents.envelope()['data']['canonicals']))
    market_id = next(iter(matcher.envelope()['data']['decisions'].values()))['canonical_market_id']
    terms = MarketTerms(canonical_event_id=event_id, canonical_market_id=market_id,
        league='NFL', scheduled_start=datetime.fromisoformat(next(iter(parents.envelope()['data']['observations'].values()))['start']), market_type=MarketType.MONEYLINE,
        period='full_game', phase='pregame', outcomes=('NFL:ATL', 'NFL:PIT'), line=None,
        rules_profile_json=json.dumps(rows[0]['profile'], sort_keys=True))
    q = ReferenceQuote(receipt_id='ref-001', provider='synthetic-aggregator',
        underlying_source='invented-book-A', source_family='invented-family-A', copied_from=(),
        identity_evidence=('synthetic:declared-independent-source',), native_event_id='atl-pit',
        native_market_id='full-game-ml', native_outcome_ids=('atl', 'pit'), terms=terms,
        decimal_odds=(Decimal('1.90000000000000000001'), Decimal('2.1000')),
        source_at=NOW - timedelta(seconds=2), received_at=NOW - timedelta(seconds=1),
        source_time_semantics='snapshot', raw_source='synthetic:e1/paired-snapshot',
        raw_json='{"atl":"1.90000000000000000001", "pit":"2.1000", "sequence":"00001"}',
        mode='synthetic', coverage='one invented paired receipt; upstream cadence/history unknown',
        permitted_use_evidence=None, limits=None,
        unknowns=('provider access/use not assessed', 'limits unknown', 'clock accuracy unknown'))
    quotes = (q,
        replace(q, receipt_id='late-arrival', received_at=NOW + timedelta(seconds=1),
                source_at=NOW - timedelta(minutes=10)),
        replace(q, receipt_id='duplicate-family', provider='other-aggregator', received_at=NOW - timedelta(seconds=3)),
        replace(q, receipt_id='target-price', underlying_source='kalshi', source_family='kalshi'),
        replace(q, receipt_id='known-copy', source_family='copy-family', copied_from=('kalshi',)),
        replace(q, receipt_id='wrong-period', terms=replace(terms, period='first_half')),
        replace(q, receipt_id='missing-side', decimal_odds=(q.decimal_odds[0], None)),
        replace(q, receipt_id='unknown-family', source_family=None),
        replace(q, receipt_id='stale', received_at=NOW - timedelta(minutes=1)))
    decisions = reference_decisions(quotes, target=Venue.KALSHI, terms=terms,
        cutoff=NOW, max_receipt_age=timedelta(seconds=30), mode='synthetic')
    fair = FairPrice(estimate_id='fixture-price-kalshi-001', target_venue=Venue.KALSHI,
        terms=terms, outcome_id='NFL:ATL', estimated_at=NOW, as_of=NOW, mode='synthetic',
        decisions=decisions, method='fixture-assigned; not calculated from odds', version='e1-fixture-1',
        probability=Probability(value=Decimal('0.5200')), status=Status.DEGRADED,
        max_receipt_age_seconds=30, freshness='1-second local receipt age; fixture bound 30 seconds',
        uncertainty=('one invented family', 'probability is an assigned illustration, not an E3 estimate',
                     'clock accuracy and real provider pairing cadence unverified'))
    # Native book shapes: Kalshi binary bid representation; PMUS supplied ask.
    books = []
    for o in observations:
        qside = o.quote.ask
        if o.quote.raw.ref.venue == Venue.KALSHI:
            ob = OutcomeBook(outcome_id='no', bids=Ladder(depth=Depth.PARTIAL,
                levels=(BookLevel(price=Probability(value=Decimal('0.60')), quantity=qside.quantity),)))
        else:
            ob = OutcomeBook(outcome_id=o.quote.outcome_id, asks=Ladder(depth=Depth.PARTIAL,
                levels=(BookLevel(price=qside.price, quantity=qside.quantity),)))
        outcomes = (OutcomeBook(outcome_id='yes', bids=Ladder(levels=(), depth=Depth.PARTIAL)), ob) if o.quote.raw.ref.venue == Venue.KALSHI else (ob,)
        books.append(OrderBook(raw=o.quote.raw, quantity_unit='contracts', outcomes=outcomes,
            state=o.quote.state))
    # Deliberately unresolved fee input; existing engine propagates unknown totals.
    next(c for c in contexts.values() if c['venue'] == 'polymarket_us').pop('assume_no_settlement_fee')
    audit = detector_audit(parents, matcher, observations, contexts,
        evaluation_time=NOW, fill_grouping='single_fill_per_leg')
    replay_detector(audit)
    unknown = Economics(quantity=Quantity(value=Decimal('100'), unit='contracts'),
        dollars_per_contract=None, total_dollars=None, roi=None, capital_denominator=None,
        denominator_basis='USD cash required including material fees/reserves; unresolved',
        unknowns=('PMUS settlement fee unknown', 'reference probability omits exceptional-outcome probabilities'))
    common = dict(canonical_market_id=market_id, as_of=NOW, mode='synthetic',
        status=Status.UNAVAILABLE, evidence_ids=('ref-001', 'synthetic:slice-10', audit['input_hash']),
        settlement_profiles_json=(terms.rules_profile_json,),
        settlement_assumptions=('invented common rules and exceptional payouts; not venue evidence',),
        fee_inputs_json=tuple(json.dumps(c, sort_keys=True) for c in contexts.values()),
        economics=unknown, limitations=('hypothetical specified fills only',))
    signals = (
        Arbitrage(signal_id='arb-001', engine_audit_json=json.dumps(audit, sort_keys=True), **common),
        Mispricing(signal_id='mispricing-001', fair_price_id=fair.estimate_id, target_venue=Venue.KALSHI,
            probability_gap=Decimal('0.1200'), **common),
        LeadLag(signal_id='leadlag-001', target_venue=Venue.KALSHI, movement_receipt_ids=(),
            window_start=NOW-timedelta(seconds=10), window_end=NOW, lag_seconds=None,
            clock_cadence_uncertainty='no movement series or qualified clocks', trade_value_model=None,
            **{**common, 'status':Status.RESEARCH_ONLY}),
        MakerValue(signal_id='maker-001', fair_price_id=fair.estimate_id, target_venue=Venue.KALSHI,
            limit_price=Probability(value=Decimal('0.39')), fill_probability=None,
            fill_assumptions=('unsubmitted hypothetical order; tick/passivity not assessed',),
            adverse_selection='unknown', inventory_exposure='unknown', **common))
    return quotes, fair, tuple(books), signals


def walkthrough():
    payload = fixture()
    encoded = dumps(payload)
    restored = loads(encoded)
    assert restored == payload and dumps(restored) == encoded
    replay_detector(json.loads(restored[3][0].engine_audit_json))
    return encoded


if __name__ == '__main__':
    print(walkthrough())
