from copy import deepcopy
from fractions import Fraction
import json

import pytest

from app.comparison.sgo_reference import calculate, capture_witness, validate_witness, ContributorFrameWitness
from app.comparison.snapshot_benchmark import withhold_unqualified_sgo
from app.comparison.sgo_reference_publication import evaluate
from app.storage.comparison_snapshot import probability
from app.comparison.sgo_fair_display import comparison as fair_comparison


AT = '2026-11-10T20:00:00Z'
CONTRACT = dict(event_id='event', league='NBA', phase='pregame', period='game',
                market='spread', side='home', line='-6.5', settlement='full-game-ot',
                settlement_evidence='reviewed-rule-1', occurrence_evidence='verified-occurrence-1', frame_id='frame-1', frame_received_at=AT)


def pair(venue, selected='-110', opposite='-110'):
    common = dict(event_id='event', league='NBA', phase='pregame', period='game',
                  market='spread', venue=venue, available=True, source_at=AT, received_at=AT,
                  settlement='full-game-ot', settlement_evidence='reviewed-rule-1', frame_id='frame-1', frame_received_at=AT)
    return [dict(common, side='home', line='-6.5', price_american=selected,
                 odd_id='home', opposing_odd_id='away'),
            dict(common, side='away', line='6.5', price_american=opposite,
                 odd_id='away', opposing_odd_id='home')]


def calc(quotes, **kwargs):
    return calculate(quotes, CONTRACT, at=AT, evaluated_venue='novig', **kwargs)


def test_median_excludes_venue_and_outlier_with_auditable_exact_basis():
    quotes = pair('a') + pair('b', '-120', '+110') + pair('c', '+500', '-600') + pair('novig')
    result = calc(quotes)
    assert result['available']
    assert Fraction(result['probability']) == Fraction(1, 2)
    assert result['exclusions']['novig'] == 'evaluated_venue_excluded'
    assert {c['venue'] for c in result['contributors']} == {'a', 'b', 'c'}
    assert len(result['basis_sha256']) == 64
    changed = deepcopy(quotes)
    changed[0]['source_at'] = '2026-11-10T19:59:59Z'
    assert calc(changed)['basis_sha256'] != result['basis_sha256']


@pytest.mark.parametrize(('edit', 'reason'), [
    (lambda q: q[1].update(line='6'), 'exact_opposing_pair_missing'),
    (lambda q: q[1].update(available=False), 'quote_unavailable'),
    (lambda q: q[1].update(source_at='2026-11-10T19:29:59Z'), 'source_stale'),
    (lambda q: q[1].update(source_at='2026-11-10T20:00:01Z'), 'clock_future'),
    (lambda q: q[1].update(source_at=None), 'source_clock_unknown'),
    (lambda q: q[1].update(settlement='unknown'), 'settlement_unverified_or_incompatible'),
    (lambda q: q[1].update(opposing_odd_id='other'), 'opposing_identity_unverified'),
    (lambda q: q[1].update(frame_id='other'), 'pair_frame_unverified'),
    (lambda q: q[1].update(frame_id=None), 'pair_frame_unverified'),
    (lambda q: q.append(deepcopy(q[0])), 'duplicate_side'),
])
def test_invalid_or_ambiguous_pair_is_excluded(edit, reason):
    quotes = pair('a')
    edit(quotes)
    result = calc(quotes, named_venue='a')
    assert not result['available']
    assert result['exclusions']['a'] == reason


def test_named_pair_and_minimum_and_self_reference():
    quotes = pair('a') + pair('b')
    assert not calc(quotes)['available']
    assert calc(quotes, named_venue='a')['available']
    assert calc(quotes, named_venue='novig')['reason'] == 'evaluated_venue_excluded'


def test_shared_frame_does_not_refresh_unchanged_original_clocks():
    quotes=pair('a')
    quotes[0]['source_at']='2026-11-10T19:55:00Z'
    quotes[0]['received_at']='2026-11-10T19:55:01Z'
    result=calc(quotes,named_venue='a')
    assert result['available']
    inputs=result['contributors'][0]['inputs']
    assert inputs[0]['source_at']=='2026-11-10T19:55:00Z'
    assert inputs[0]['received_at']=='2026-11-10T19:55:01Z'
    assert inputs[0]['frame_received_at']==AT
    quotes[0]['source_at']='2026-11-10T19:29:59Z'
    assert not calc(quotes,named_venue='a')['available']


def test_contract_evidence_and_exact_total_and_phase_required():
    contract = dict(CONTRACT, settlement='unverified')
    assert calculate(pair('a'), contract, at=AT, evaluated_venue='novig')['reason'] == 'contract_settlement_unverified'
    quotes = pair('a')
    quotes[0]['phase'] = 'live'
    assert not calc(quotes, named_venue='a')['available']


def test_witness_revalidates_captured_evidence_and_current_age():
    result, witness = capture_witness(pair('a') + pair('b') + pair('c'), CONTRACT,
                                      at=AT, evaluated_venue='novig')
    assert result['available'] and witness is not None
    assert validate_witness(witness, at=AT)['probability'] == '1/2'
    assert not validate_witness(witness, at='2026-11-10T20:30:01Z')['available']
    assert not validate_witness(witness, at='2026-11-10T19:59:59Z')['available']
    tampered = json.loads(witness.wire)
    tampered['basis']['contributors'][0]['inputs'][0]['price_american'] = '+900'
    assert not validate_witness(ContributorFrameWitness(json.dumps(tampered)), at=AT)['available']
    tampered = json.loads(witness.wire)
    tampered['probability'] = '3/4'
    assert not validate_witness(ContributorFrameWitness(json.dumps(tampered)), at=AT)['available']


def test_unverified_inputs_never_capture_witness():
    result, witness = capture_witness(pair('a'), dict(CONTRACT, settlement='unverified'),
                                      at=AT, evaluated_venue='novig', named_venue='a')
    assert not result['available'] and witness is None
    result, witness = capture_witness(pair('a'), dict(CONTRACT, occurrence_evidence=None),
                                      at=AT, evaluated_venue='novig', named_venue='a')
    assert not result['available'] and witness is None


@pytest.mark.parametrize(('family', 'selected', 'opposite', 'line'), [
    ('moneyline', 'home', 'away', None),
    ('total', 'over', 'under', '224.5'),
])
def test_moneyline_and_total_exact_pairs(family, selected, opposite, line):
    contract = dict(CONTRACT, market=family, side=selected, line=line)
    quotes = pair('a')
    quotes[0].update(market=family, side=selected, line=line)
    quotes[1].update(market=family, side=opposite, line=line)
    result = calculate(quotes, contract, at=AT, evaluated_venue='novig', named_venue='a')
    assert result['available'] and result['probability'] == '1/2'
    if line is not None:
        quotes[1]['line'] = '225.5'
        assert not calculate(quotes, contract, at=AT, evaluated_venue='novig', named_venue='a')['available']


def test_sgo_source_cannot_borrow_legacy_reference_in_snapshot():
    row = {'league': 'NBA', 'venue': 'novig', 'source': {'provider': 'sportsgameodds'},
           'original': {'value': '-110'}, 'snapshot_benchmark': {'probability': '1/2'},
           'reference': {'bookmaker': 'pinnacle'}, 'benchmark_quote': {'sharp_reference': {}}}
    assert withhold_unqualified_sgo(row)
    assert row['snapshot_benchmark'] is None and row['reference'] is None and row['benchmark_quote'] is None
    value, reason = probability(row, {'benchmark_venue': 'pinnacle'}, AT)
    assert value is None and 'verified occurrence' in reason
    assert row['original']['value'] == '-110'


def test_non_sgo_snapshot_reference_is_unchanged():
    row = {'source': {'provider': 'kalshi'}, 'reference': {'bookmaker': 'pinnacle'}}
    assert not withhold_unqualified_sgo(row)
    assert row['reference']['bookmaker'] == 'pinnacle'


def test_vendor_fair_is_attributed_separately_and_never_freshened():
    record={'quote':{'venue':'novig','source':{'provider':'sportsgameodds','native_event_id':'e',
        'native_outcome_id':'over','native_line':'224.5'},'original':{'value':'-110'},
        'times':{'received_at':AT},'provenance':{'sha256':'a'*64}}}
    facts={'event_id':'e','odd_id':'over','venue':'novig','line':'224.50','price_american':'-110',
        'receipt_sha256':'a'*64,'received_at':AT,'fair':{'available':True,'price_american':'-105','line':'224.50','source_at':None}}
    result=fair_comparison(record,[{'facts':facts}])
    assert result['line']=='224.50' and result['same_line'] and result['source_at'] is None and result['provider']=='sportsgameodds'
    assert 'unknown' in result['meaning']
    different=fair_comparison(record,[{'facts':dict(facts,fair={'available':True,'price_american':'-105','line':'225'})}])
    assert different['line']=='225' and different['same_line'] is False
    unavailable=fair_comparison(record,[{'facts':dict(facts,fair={'available':False,'price_american':'-105','line':'225'})}])
    assert unavailable['available'] is False and unavailable['line'] == '225'
    for change in ({'receipt_sha256':'b'*64},{'received_at':'2026-11-10T20:00:01Z'}):
        assert fair_comparison(record,[{'facts':dict(facts,**change)}]) is None
    new_at = '2026-11-10T20:00:01Z'
    refreshed = dict(id='q', revision='r', facts=dict(facts, receipt_sha256='b'*64, received_at=new_at,
        phase='pregame', available=True, source_at=AT, opposing_odd_id='under',
        consensus=dict(available=True, price_american='-110', line='225', source_at=None)))
    record['quote']['times']['source_at'] = AT
    record['quote']['state'] = 'available'
    record['comparison_source_metadata'] = dict(provider_phase='pregame', provider_opposing_odd_id='under')
    frame = {'facts': {'provider':'sportsgameodds','event_id':'e','members':[['q','r']]}}
    display = fair_comparison(record, [refreshed], frame)
    assert display['received_at'] == new_at and not display['consensus']['same_line']
    assert display['consensus']['source_at'] is None
    refreshed['facts']['source_at'] = new_at
    assert fair_comparison(record, [refreshed], frame) is None


def test_best_payout_selects_one_book_then_devigs_its_opposite():
    from app.collection.sportsgameodds_current_rows import current_rows
    from app.comparison.sgo_sportsbook_baseline import current, select
    from app.storage.sportsgameodds_reference import prepare_frames, prepare_page
    from app.storage.store import stamp
    from tests.test_sportsgameodds_adapter import parse, response

    data = response()
    event = data['data'][0]
    event['status'].update(startsAt='2026-11-10T19:59:55Z', started=True, live=True)
    home = event['odds']['points-home-game-sp-home']
    offer = dict(available=True, odds='+140', spread='-1.5', lastUpdatedAt=AT)
    home['byBookmaker'] = {
        'novig': offer,
        'fanduel': dict(offer, odds='+120'),
        'draftkings': dict(offer, odds='+110'),
        'betmgm': dict(offer, odds='-105'),
        'caesars': dict(offer, odds='+200', spread='-2.5'),
    }
    away = dict(home, oddID=home['opposingOddID'], opposingOddID=home['oddID'], statEntityID='away', sideID='away',
                byBookmaker={'fanduel':dict(offer, odds='-150', spread='1.5'),
                             'draftkings':dict(offer, odds='-115', spread='1.5'),
                             'betmgm':dict(offer, odds='-110', spread='1.5'),
                             'caesars':dict(offer, odds='-230', spread='2.5')})
    event['odds'][away['oddID']] = away

    def captured():
        page = parse(data)
        offered, _ = current_rows(page, page.receipt_sha256)
        rows = prepare_page(page)
        return offered[0], rows, prepare_frames(page, rows)[0]

    record, rows, frame = captured()
    value = select(record, rows, frame, at=AT)
    assert value['book'] == 'fanduel' and value['candidate_books'] == 3
    assert [leg['price_american'] for leg in value['prices']] == ['+120', '-150']
    assert Fraction(value['probability']) == Fraction(25, 58)
    assert Fraction(value['return_percent']) == Fraction(100, 29)
    assert current(value, ['quote', 'contract', 'event', 'receipt:'+value['frame_id']], at=stamp(AT))
    assert not current(value, ['quote', 'contract', 'event', 'receipt:changed'], at=stamp(AT))
    assert select(record, rows, frame, at='2026-11-10T20:00:16Z') is None
    away['byBookmaker']['fanduel']['available'] = False
    record, rows, frame = captured()
    assert select(record, rows, frame, at=AT)['book'] == 'draftkings'


def publication_fixture():
    quotes = pair('a') + pair('b') + pair('c')
    _, witness = capture_witness(quotes, CONTRACT, at=AT, evaluated_venue='kalshi')
    row = {'id': 'native-1', 'revision': 3, 'venue': 'kalshi', 'cost_per_normal_claim': '2/5',
           'start_at': '2026-11-10T22:00:00Z', 'market': {'market': 'spread', 'period': 'full_game'},
           'original': {'value': '0.4'}, 'source': {'provider': 'kalshi'}}
    binding = {'verified': True, 'row_id': row['id'], 'row_revision': row['revision'],
               'contract': CONTRACT, 'occurrence_evidence': CONTRACT['occurrence_evidence'],
               'settlement_evidence': CONTRACT['settlement_evidence']}
    dependencies = [dict(q, dependency=q['venue'] + ':' + q['odd_id'], expected_revision='1',
                         current_revision='1', state='available') for q in quotes]
    price_authority = {'eligible': True, 'dependency': 'native', 'expected_revision': '1',
                       'current_revision': '1', 'row_id': row['id'], 'row_revision': row['revision']}
    return row, witness, binding, dependencies, price_authority


def test_publication_revalidates_every_contributor_and_preserves_fee_boundaries():
    row, witness, binding, dependencies, authority = publication_fixture()
    result = evaluate(row, witness, binding, dependencies, at=AT, price_authority=authority)
    assert result['available'] and result['probability'] == '1/2'
    assert result['gross_return_percent'] == '25'
    assert result['reference_calculation']['venue'] == 'sportsgameodds_books'
    assert len(result['dependency_ids']) == 6
    assert not result['conditional_trade_benchmark']['available']
    dependencies[0]['current_revision'] = '2'
    changed = evaluate(row, witness, binding, dependencies, at=AT, price_authority=authority)
    assert not changed['available'] and changed['reason'] == 'sgo_contributor_changed_or_unavailable'
    assert changed['gross_return_percent'] is None


def test_publication_rejects_removed_input_unverified_binding_and_stale_frame():
    row, witness, binding, dependencies, authority = publication_fixture()
    assert not evaluate(row, witness, binding, dependencies[:-1], at=AT, price_authority=authority)['available']
    assert not evaluate(row, witness, dict(binding, verified=False), dependencies, at=AT, price_authority=authority)['available']
    assert not evaluate(dict(row, revision=4), witness, binding, dependencies, at=AT, price_authority=authority)['available']
    assert not evaluate(row, witness, binding, dependencies, at=AT, price_authority=dict(authority, eligible=False))['available']
    assert not evaluate(row, witness, binding, dependencies, at='2026-11-10T20:30:01Z', price_authority=authority)['available']


def test_ordinary_publication_sgo_mode_uses_all_dependencies_and_never_legacy(monkeypatch):
    from app.storage import ordinary_publication as ordinary
    from app.comparison import snapshot_fee_outcome
    from app.comparison import sgo_reference_publication
    row, witness, binding, deps, authority = publication_fixture()
    row.update(kind='single', league='NBA', original={'value': '0.4'}, same_outcome={'supported': True},
               snapshot_benchmark={'bookmaker': 'pinnacle', 'probability': '3/4'},
               reference={'bookmaker': 'pinnacle'}, probability='3/4')
    current = {d['dependency']: ['revision-1', 'contract-1', 'event-1'] for d in deps}
    for dep in deps:
        dep['expected_revision'] = current[dep['dependency']]
    candidate = {'witness': witness.wire, 'binding': binding, 'dependencies': deps}
    inputs = {'captured_at': AT, 'quotes': [dict(row)], 'references': [], 'dependencies': current,
              'reference_provider': 'sportsgameodds', 'sgo_reference_inputs': {row['id']: candidate},
              'policy_identity': 'policy', 'epoch': 'epoch'}
    result = {'rows': [row], 'pairs': [], 'assumptions': {'revision': 'settings', 'benchmark_venue': 'pinnacle'}}
    monkeypatch.setattr(snapshot_fee_outcome, 'reviews', lambda at: {})
    monkeypatch.setattr(sgo_reference_publication, 'owned_reference_evidence', lambda row, inputs, source, **kwargs: (inputs.get('sgo_reference_inputs') or {}).get(row['id']))
    monkeypatch.setattr(ordinary, 'quote_authority', lambda *args, **kwargs: {
        'dependency': 'native', 'expected': ['r', 'c', 'e'], 'reasons': [],
        'current_until': '2026-11-10T20:30:00Z', 'lifecycle': {'state': 'scheduled'}})
    output = ordinary.bind(result, inputs, 'ready')['rows'][0]
    assert output['probability'] == '1/2'
    assert output['reference_calculation']['venue'] == 'sportsgameodds_books'
    assert len(output['current_authority']['references']) == 6
    assert not output['current_authority']['exact_pinnacle_reference']
    changed = dict(current)
    changed[deps[0]['dependency']] = ['revision-2', 'contract-1', 'event-1']
    assert ordinary.validity(output['current_authority']['references'][0], changed, ordinary.stamp(AT)) == ['input_replaced_or_removed']
    inputs['sgo_reference_inputs'] = {}
    again = ordinary.bind({'rows': [deepcopy(row)], 'pairs': [], 'assumptions': result['assumptions']}, inputs, 'ready')['rows'][0]
    assert again['probability'] is None and again['reference'] is None


def test_live_sgo_reference_and_native_kalshi_fee_reach_current_desk(monkeypatch):
    from app.comparison import sgo_reference_publication, snapshot_fee_scope
    from app.comparison.inspection_math import offer_math
    from app.dashboard.trade_desk import offer
    from app.storage import ordinary_publication as ordinary

    row, _, binding, _, _ = publication_fixture()
    start = '2026-11-10T19:00:00Z'
    series = 'KXNBASPREAD'
    event = series + '-26NOV10BOSNYK'
    source = dict(provider='kalshi', native_event_id=event, native_market_id=event+'-BOS7',
                  native_side='yes', native_outcome_id='yes')
    row.update(league='NBA', kind='single', start_at=start, source=source, cost_per_normal_claim=None,
               original=dict(value='0.4', units='usd_per_contract', quantity_units='contracts', payout_units='USD', payout='1'),
               times={'source_at': AT, 'received_at': AT}, same_outcome={'supported': True})
    scope = dict(series_id=series, phase='live', native_key=['kalshi', event, source['native_market_id'], 'yes', 'yes'])
    original = dict(row, original_record={'event': {'status': {'live': True}}, 'quote': {'source': source},
                                         'comparison_source_metadata': scope})
    quotes = [dict(q, phase='live') for q in pair('pinnacle')]
    contract = dict(CONTRACT, phase='live', starts_at=start)
    _, witness = capture_witness(quotes, contract, at=AT, evaluated_venue='kalshi', named_venue='pinnacle')
    deps = [dict(q, dependency=q['odd_id'], expected_revision=['r','c','e'], state='available') for q in quotes]
    candidate = dict(witness=witness.wire, binding=dict(binding, contract=contract), dependencies=deps)
    current = {key: ['r','c','e'] for key in ('home','away','native')}
    inputs = dict(captured_at=AT, quotes=[original], references=[], dependencies=current,
                  reference_provider='sportsgameodds', policy_identity='policy', epoch='epoch')
    settings = dict(revision='settings', benchmark_venue='pinnacle')
    monkeypatch.setattr(sgo_reference_publication, 'owned_reference_evidence', lambda *args, **kwargs: candidate)
    monkeypatch.setattr(ordinary, 'quote_authority', lambda *args, **kwargs: dict(
        dependency='native', expected=current['native'], provider='kalshi', reasons=[],
        current_until='2026-11-10T20:00:15Z', lifecycle={'state':'live'}))
    monkeypatch.setattr(snapshot_fee_scope, 'kalshi_account', lambda at: dict(
        membership='direct', review_before='2026-11-10T20:00:10Z'))

    result = ordinary.bind(dict(rows=[row], pairs=[], assumptions=settings), inputs, 'ready')
    owner = dict(healthy=True, active=True, config={'aggregate_provider':'sportsgameodds'})
    states = {k: dict(state='available') for k in ('kalshi','polymarket_us','sportsgameodds')}
    def read(at):
        return ordinary.project(result, current, owner, states, at=ordinary.stamp(at), policy='policy', epoch='epoch')['rows'][0]

    current_row = read(AT)
    assert current_row['gross_profit_per_claim'] == '0.1'
    assert current_row['gross_return_percent'] == '25'
    assert current_row['conditional_trade_benchmark']['trade_fee_usd'] == '0.0168'
    assert Fraction(current_row['conditional_return_percent']) == Fraction(10400, 521)
    assert Fraction(current_row['conservative_return_percent']) == Fraction(400, 21)
    assert offer(current_row, 'gross_return_percent')['reference']['american'] == '+100'
    assert offer_math(current_row)['fair_reference']['contributors'][0]['venue'] == 'pinnacle'
    after_fee_expiry = read('2026-11-10T20:00:11Z')
    assert after_fee_expiry['gross_return_percent'] == '25' and after_fee_expiry['conditional_return_percent'] is None
    assert read('2026-11-10T20:00:16Z')['gross_return_percent'] is None


def test_owned_reference_requires_retained_pinnacle_and_native_evidence():
    from tests.test_snapshot_benchmark import execution, references
    from app.comparison.line_reference import scoring
    from app.comparison.sgo_reference_publication import owned_reference_evidence, bind_captured
    from app.storage.current_rows import contract_id
    from app.storage.store import hashed
    native = execution(); native.update(quote_revision=3, binding={'verified': True}, start_at='2026-11-10T22:00:00Z')
    nr=native['original_record']; nr.update(verified=True,orientation_evidence=[])
    nr['event'].update(season='2026', stage='regular', scheduled_start=native['start_at'], shared_provider_ids={'sportradar':'game'})
    nr['quote']['source']['native_market_id']='native-market'
    nr['quote']['provenance']['sha256']='b'*64
    nr['comparison_source_metadata'].pop('comparison_admission', None)
    nr['comparison_source_metadata']['scoring_scope']['scoring']=scoring('NCAAB')
    refs=references()
    deps={}
    for i, ref in enumerate(refs):
        r=ref['original_record']; q=r['quote']; src=q['source']
        r.update(verified=False,orientation_evidence=[])
        r['event'].update(season='unverified',stage='unverified',scheduled_start=native['start_at'],shared_provider_ids={'sportradar':'game'})
        src.update(provider='sportsgameodds',native_market_id='sgo-'+str(i))
        q['original'].update(units='american_odds',value='-110')
        q['times'].update(source_at=AT,received_at=AT)
        q['state']='available'
        r['comparison_source_metadata'].update(provider_phase='pregame',provider_opposing_odd_id=('no' if i==0 else 'yes'))
        r['comparison_source_metadata'].pop('comparison_admission',None)
        r['comparison_source_metadata'].pop('scoring_scope',None)
        ref.update(id=hashed(src),source=src)
        deps[contract_id(r)]=['price','contract','event','receipt']
    data={'quotes':[native], 'references':refs, 'dependencies':deps, 'captured_at':AT}
    source={'dependency':'native', 'expected':['r','c','e'], 'reasons':[], 'current_until':'2026-11-10T20:30:00Z', 'lifecycle':{'state':'scheduled'}}
    candidate=owned_reference_evidence(native,data,source)
    assert candidate is not None
    assert candidate['binding']['contract']['settlement'].startswith('pinnacle')
    native.update(cost_per_normal_claim='2/5', source=nr['quote']['source'])
    published, authorities=bind_captured(native,source,data)
    assert published['available'] and published['probability'] == '1/2' and len(authorities)==2
    assert not bind_captured(native,source,data,selected_venue='novig')[0]['available']
    assert published['reference_calculation']['venue'] == 'pinnacle'
    # One original row was unchanged, so current-row storage retains its old
    # receipt. The latest frame proves both exact revisions appeared together.
    unchanged=refs[0]['original_record']['quote']
    unchanged['times'].update(source_at='2026-11-10T19:55:00Z',received_at='2026-11-10T19:55:01Z')
    unchanged['provenance']['sha256']='d'*64
    refs[1]['original_record']['quote']['provenance']['sha256']='c'*64
    frame_rows=[]
    for i, ref in enumerate(refs):
        r=ref['original_record'];q=r['quote'];s=q['source']
        frame_rows.append({'id':f'ref-{i}', 'revision':f'revision-{i}', 'facts':{
            'event_id':'ref','venue':'pinnacle','odd_id':s['native_outcome_id'],
            'opposing_odd_id':r['comparison_source_metadata']['provider_opposing_odd_id'],
            'line':r['selection']['signed_line'],'price_american':q['original']['value'],
            'source_at':q['times']['source_at'],'phase':'pregame','available':True}})
    frame={'facts':{'provider':'sportsgameodds','event_id':'ref','receipt_sha256':'c'*64,
                    'received_at':AT,'members':[[r['id'],r['revision']] for r in frame_rows]}}
    data['sgo_reference_events']={'ref':{'frame':frame,'rows':frame_rows}}
    published, authorities=bind_captured(native,source,data)
    assert published['available']
    parts=published['reference_calculation']['contributors'][0]['inputs']
    earlier=next(x for x in parts if x['source_at']=='2026-11-10T19:55:00Z')
    assert earlier['received_at']=='2026-11-10T19:55:01Z' and earlier['frame_received_at']==AT
    frame_rows[0]['revision']='changed-without-frame'
    assert not bind_captured(native,source,data)[0]['available']
    frame_rows[0]['revision']='revision-0'
    for key,value in [('price_american','+200'),('line','136'),('source_at','2026-11-10T19:56:00Z'),('available',False)]:
        original=frame_rows[0]['facts'][key]
        frame_rows[0]['facts'][key]=value
        assert not bind_captured(native,source,data)[0]['available']
        frame_rows[0]['facts'][key]=original
    data.pop('sgo_reference_events')
    unchanged['times'].update(source_at=AT,received_at=AT)
    unchanged['provenance']['sha256']='c'*64
    from app.storage.ordinary_publication import validity
    changed=deepcopy(data['dependencies']);changed[authorities[0]['dependency']][0]='changed'
    from app.dashboard.current_contract import stamp
    assert 'input_replaced_or_removed' in validity(authorities[0],changed,stamp(AT))
    saved=deepcopy(nr['event']['shared_provider_ids'])
    nr['event'].pop('shared_provider_ids')
    missing, _ = bind_captured(native,source,data)
    assert missing['reason'] == 'sgo_reference_occurrence_unverified'
    nr['event']['shared_provider_ids']=saved
    nr['event']['shared_provider_ids']={'sportradar':'different'}
    assert owned_reference_evidence(native,data,source) is None
    nr['event']['shared_provider_ids']=saved
    refs[1]['original_record']['comparison_source_metadata']['provider_opposing_odd_id']='wrong'
    assert owned_reference_evidence(native,data,source) is None
    refs[1]['original_record']['comparison_source_metadata']['provider_opposing_odd_id']='yes'
    native['start_at']='2026-11-10T19:00:00Z'
    nr['event']['scheduled_start']=native['start_at']
    for ref in refs:
        ref['original_record']['event']['scheduled_start']=native['start_at']
        ref['original_record']['comparison_source_metadata'].update(provider_phase='live',
            provider_event_status={'started':True,'live':True})
    source['lifecycle']['state']='live'
    assert owned_reference_evidence(native,data,source) is not None
    live, authority = bind_captured(native, source, data)
    assert live['available'] and live['reference_calculation']['maximum_age_seconds'] == 15
    assert all(a['lifecycle']['state'] == 'live' for a in authority)
    assert all(stamp(a['current_until']) == stamp('2026-11-10T20:00:15Z') for a in authority)
    data['captured_at']='2026-11-10T20:00:15.001Z'
    stale, authority = bind_captured(native, source, data)
    assert not stale['available'] and stale['reason'] == 'sgo_reference_pair_timing_unverified' and authority == []
    data['captured_at']=AT
    refs[0]['original_record']['comparison_source_metadata']['provider_phase']='pregame'
    diagnostic = {}
    assert owned_reference_evidence(native,data,source,diagnostics=diagnostic) is None
    assert diagnostic['reason'] == 'sgo_reference_pair_timing_unverified'
