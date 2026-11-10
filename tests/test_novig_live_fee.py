from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

from app.comparison.current_dependencies import instant
from app.comparison.snapshot_fee_outcome import outcome
from app.comparison.snapshot_novig_live import live_fee
from app.fees.engine import calculate
from app.fees.public_bindings import bind
from tests.test_trade_desk import quote

AT = instant('2026-11-09T20:00:10Z')


def sample():
    row = quote('native', 'novig')
    row['source'] = dict(provider='novig', native_event_id='event', native_market_id='market', native_outcome_id='outcome', native_side='buy')
    row['original'] = dict(value='0.5', units='usd_per_contract')
    evidence = dict(identity=dict(event_id='event', market_id='market', outcome_id='outcome', side='buy', period='full_game', line='2.5'),
        fill_count=1, price_levels=1, available_native_contracts=100, price='0.5', event_status='OPEN_INGAME',
        market_fee=dict(coefficient='0.06', makerCredit='0.25', charged='WHEN_LIVE'),
        native_event=dict(eventId='event', status='OPEN_INGAME'),
        native_market=dict(eventId='event', marketId='market', marketType='SPREAD', status='OPEN', strike='2.5', fee=dict(coefficient='0.06', makerCredit='0.25', charged='WHEN_LIVE'), outcomes=[dict(outcomeId='outcome'),dict(outcomeId='other')]),
        quote_at='2026-11-09T20:00:09Z', phase_at='2026-11-09T20:00:08Z',
        terms_at='2026-11-09T20:00:08Z', last_book_reset_at='2026-11-09T20:00:07Z',
        reset_proof=dict(transport='novig_v3_signed_stream',continuous=True,generation='fixture-stream',
            event_id='event',market_id='market', source_book=dict(marketId='market',seq=11,orders={'other':[dict(orderId='order',price='0.5',qty=100)]}),
            frames=[dict(position=1,market_id='market',lifecycle=dict(seq=8,deltas=[dict(kind='GOLIVE',status='OPEN')])),
                    dict(position=2,market_id='market',book=dict(marketId='market',seq=11,orders={'other':[dict(orderId='order',price='0.5',qty=100)]}))],
            transition=dict(kind='GOLIVE',status='OPEN',seq=8,position=1,received_at='2026-11-09T20:00:07Z'),
            book=dict(kind='snapshot',seq=11,position=2,received_at='2026-11-09T20:00:09Z')))
    return row, evidence


def test_single_native_fill_and_explicit_units():
    row, evidence = sample()
    result = live_fee(row, AT, evidence)
    assert result['available'] and result['trade_fee_usd'] == '0.01500'
    assert result['quantity'] == '100' and result['fee_cashflows']['at_fill_usd'] == '0.01500'
    assert result['evidence']['native'] == evidence
    evidence['market_fee']['coefficient'] = '0.07'
    assert result['evidence']['native']['market_fee']['coefficient'] == '0.06'


def test_engine_10000_native_contract_example():
    c = dict(venue='novig', environment='production', market_id='market', product='v3_market',
        trade_time=AT.isoformat(), calculation_time=AT.isoformat(), api_regime='v3',
        complete_order_history=True, fills=[dict(fill_id='f', order_id='o', role='taker',
            price='0.50', quantity='10000', unit='novig_v3_contracts', event_status_at_match='OPEN_INGAME')])
    c = bind(c, market=dict(marketId='market', fee=dict(coefficient='0.06', makerCredit='0.25', charged='WHEN_LIVE')))
    result = calculate(c)
    assert Decimal(result['entry_fees']) == Decimal('1.50')


def test_boundaries_conflicts_and_reset_fail_closed():
    row, evidence = sample()
    assert live_fee(row, AT + timedelta(seconds=20), evidence)['reason'] == 'novig_live_evidence_stale_or_future'
    for key in ('event_id', 'market_id', 'outcome_id', 'side', 'period', 'line'):
        bad = deepcopy(evidence); bad['identity'][key] = 'other'
        assert live_fee(row, AT, bad)['reason'] == 'novig_exact_offer_identity_conflict'
    for state in ('OPEN_PREGAME', 'DELAYED'):
        bad = deepcopy(evidence); bad['event_status'] = state; bad['native_event']['status'] = state
        assert live_fee(row, AT, bad)['reason'] == 'novig_event_phase_conflicts_with_live_offer'
    bad = deepcopy(evidence); bad['last_book_reset_at'] = bad['quote_at']
    bad['reset_proof']['transition']['received_at'] = bad['quote_at']
    assert live_fee(row, AT, bad)['reason'] == 'novig_fresh_quote_required_after_book_reset'
    bad['quote_at'] = '2026-11-09T20:00:10Z'
    bad['reset_proof']['book']['received_at'] = bad['quote_at']
    bad['phase_at'] = '2026-11-09T20:00:09Z'
    assert live_fee(row, AT, bad)['available']
    bad['price_levels'] = 2
    assert live_fee(row, AT, bad)['reason'] == 'novig_single_price_fill_evidence_missing'
    assert outcome(row, at=AT, phase='live', review=None)['reason'] == 'novig_native_market_phase_and_book_missing'


def test_pregame_delayed_and_resumed_phase_engine():
    base = dict(venue='novig', environment='production', market_id='market', product='v3_market',
        trade_time=AT.isoformat(), calculation_time=AT.isoformat(), api_regime='v3', complete_order_history=True,
        fills=[dict(fill_id='f', order_id='o', role='taker', price='0.50', quantity='10000',
                    unit='novig_v3_contracts', event_status_at_match='OPEN_PREGAME')])
    c = bind(base, market=dict(marketId='market', fee=dict(coefficient='0.06', makerCredit='0.25', charged='WHEN_LIVE')))
    for status, expected in [('OPEN_PREGAME', '0'), ('OPEN_INGAME', '1.50'), ('DELAYED', '0'), ('OPEN_INGAME', '1.50')]:
        c['fills'][0]['event_status_at_match'] = status
        assert Decimal(calculate(c)['entry_fees']) == Decimal(expected)


def test_captured_fee_survives_later_evidence_changes():
    row, evidence = sample()
    row['novig_v3_evidence'] = evidence
    captured = outcome(row, at=AT, phase='live', review=None)
    replay = deepcopy(captured)
    evidence['market_fee']['coefficient'] = '0.09'
    assert replay['trade_fee_usd'] == '0.01500'
    assert replay['evidence']['native']['market_fee']['coefficient'] == '0.06'


def test_ordinary_live_metric_requires_exact_reference_and_preserves_replay():
    from fractions import Fraction
    from app.comparison.snapshot_novig_live import live_metric
    from app.storage.comparison_snapshot import pack, unpack, defer_details, expand_row
    from app.dashboard.snapshot_display import ranking_value
    row, evidence = sample()
    fee = live_fee(row, AT, evidence)
    row.update(probability='3/5', cost_per_normal_claim='1/2', gross_return_percent='20',
        reference_calculation=dict(available=True, venue='pinnacle'),
        snapshot_benchmark=dict(selected_identity={'occurrence':'game'}, selected_predicate={'operator':'gt'}))
    witnesses = [dict(dependency=key,reasons=[],lifecycle={'state':'live'}) for key in ('p1','p2')]
    model = live_metric(row, fee, witnesses)
    assert model['available'] and Fraction(model['return_percent']) == Fraction(1700,103)
    assert Fraction(model['trade_fee_usd']) == Fraction(3,200)
    assert not live_metric(row, fee, witnesses[:1])['available']
    assert not live_metric(row, fee, [witnesses[0],dict(witnesses[1], lifecycle={'state':'scheduled'})])['available']
    row['snapshot_benchmark']['selected_identity'] = None
    assert not live_metric(row, fee, witnesses)['available']
    row['snapshot_benchmark']['selected_identity'] = {'occurrence':'game'}
    row.update(trade_fee=fee, conditional_trade_benchmark=model, conditional_return_percent=model['return_percent'],
        novig_live_financial_qualified=True, metric_status={'after_trade_fee_ev':{'state':'available'}}, current_reasons=[])
    frozen = unpack(pack(defer_details(dict(rows=[row]))))
    original = frozen['rows'][0]
    assert ranking_value(original, 'conditional_return_percent', current=True) == Fraction(1700,103)
    evidence['market_fee']['coefficient'] = '0.09'
    assert expand_row(original)['trade_fee']['evidence']['native']['market_fee']['coefficient'] == '0.06'
    assert Fraction(expand_row(original)['conditional_trade_benchmark']['trade_fee_usd']) == Fraction(3,200)


def test_fixture_publication_projects_and_withdraws_after_replacement(monkeypatch, tmp_path):
    from app.storage import ordinary_publication as publication, comparison_snapshot as snapshots
    from app.dashboard.snapshot_display import ranking_value
    from fractions import Fraction
    row, raw = sample()
    from tests.test_novig_v3_stream import ready, T2
    producer = ready()
    evidence = producer.evidence(raw['native_event'], raw['native_market'], 'outcome', at=T2)
    assert evidence is not None
    row.update(probability='3/5', cost_per_normal_claim='1/2', gross_return_percent='20',
        reference_calculation=dict(available=True, venue='pinnacle', pair=[{'original': {'value':'2'}}, {'original': {'value':'3'}}]),
        snapshot_benchmark=dict(bookmaker='pinnacle', odds=['2','3'], selected=0, selected_odds='2', selected_identity={'occurrence':'game'}, selected_predicate={'operator':'gt'}),
        fee_applicability={'fixture': True}, conservative_trade_benchmark={}, conditional_trade_benchmark={})
    original = deepcopy(row)
    original['original_record'] = dict(event={'status': {'live': True}}, quote=dict(novig_v3_evidence=evidence))
    selected = [dict(id='a',source={},original={}),dict(id='b',source={},original={})]
    def authority(q, inputs, reference=False):
        dep = q['id'] if reference else 'execution'
        return dict(dependency=dep,expected=['p','c','e'],venue='pinnacle' if reference else 'novig',
                    reasons=[],current_until='2026-11-09T20:00:22Z',lifecycle={'state':'live'})
    monkeypatch.setattr(publication,'quote_authority',authority)
    monkeypatch.setattr('app.comparison.snapshot_fee_outcome.reviews',lambda at: {'novig':None})
    monkeypatch.setattr('app.comparison.snapshot_named_benchmark.references',lambda *args: selected)
    monkeypatch.setattr('app.comparison.snapshot_named_benchmark.selected_references',lambda *args: selected)
    inputs=dict(quotes=[original],references=[],captured_at=AT.isoformat(),policy_identity='policy',epoch='epoch')
    result=dict(rows=[row],pairs=[], assumptions={'revision':'settings', 'benchmark_venue':'pinnacle'})
    sealed=publication.bind(result,inputs,'ready')
    sealed=snapshots.unpack(snapshots.pack(snapshots.defer_details(sealed)))
    dependencies={key:['p','c','e'] for key in ('execution','a','b')}
    states={key:{'state':'available'} for key in ('kalshi','polymarket_us','novig','prophetx','pinnacle')}
    def project(deps, at=AT):
        return publication.project(sealed,deps,{'healthy':True,'active':True},states,at=at,policy='policy',epoch='epoch')['rows'][0]
    current=project(dependencies)
    assert current['trade_fee']['available'] and current['exact_pinnacle_reference_current']
    assert ranking_value(current,'conditional_return_percent',current=True)==Fraction(1700,103)
    changed=deepcopy(dependencies);changed['execution']=['new-price','c','e']
    assert not project(changed)['trade_fee']['available']
    assert ranking_value(project(changed),'conditional_return_percent',current=True) is None
    assert snapshots.expand_row(sealed['rows'][0])['trade_fee']['evidence']['native']['market_fee']['coefficient']=='0.06'
    reference_changed=deepcopy(dependencies); reference_changed['a']=['new','c','e']
    assert project(reference_changed)['trade_fee']['available']
    assert not project(reference_changed)['exact_pinnacle_reference_current']
    # Exercise the real archive writer and frozen detail reader in a disposable
    # directory. The calculation input is the authored fixture above.
    from app.storage import odds_replay
    from app.dashboard.replay_api import load, board
    inputs.update(dependencies=dependencies, issues=[])
    result.update(id='fixture-capture', captured_at=AT.isoformat(), games=[], references=[], issues=[], replay={})
    monkeypatch.setattr(snapshots, 'calculate', lambda *args: deepcopy(result))
    monkeypatch.setattr(odds_replay, 'DIRECTORY', tmp_path)
    odds_replay.compile_archive('frozen', (inputs, {'revision':'settings', 'benchmark_venue':'pinnacle'},
        {'healthy':True,'active':True}, states), directory=tmp_path)
    board.cache_clear()
    evidence['market_fee']['coefficient'] = '0.09'
    detail=load(dict(dataset='frozen', id=row['id'], result_id='fixture-capture'), details=True)
    assert detail['inspection']['trade_fee']['evidence']['native']['market_fee']['coefficient']=='0.06'
    assert Fraction(detail['inspection']['reviewed']['return_percent'])==Fraction(1700,103)
