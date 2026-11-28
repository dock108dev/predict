from contextlib import closing
from fractions import Fraction
import sqlite3
from unittest.mock import patch

import pytest

from app.dashboard.local_security import PublicRequestError
from app.dashboard.replay_api import load
from app.fees.public_reasons import UNAVAILABLE
from app.storage import odds_replay
from app.storage.comparison_snapshot import pack, unpack
from app.comparison.inspection_math import starting_fee_terms
from app.comparison.inspection_settlement import settlement_terms
from tests.replay_fixture import write_archives


VETTED_REPLAY_REASON = 'synthetic_account_terms_unavailable'
RAW_REPLAY_REASON = 'Legacy failure reading /private/synthetic-fee-evidence.json'


@pytest.fixture
def saved_archives(tmp_path, monkeypatch):
    write_archives(tmp_path)
    monkeypatch.setattr(odds_replay, 'DIRECTORY', tmp_path)


def test_saved_prices_show_prefee_payoff_and_withhold_after_fee_payoff(saved_archives):
    query = dict(dataset='frozen', view='arbs', stake='100')
    assert load(dict(query, positive='on'))['total'] == 0
    result = load(dict(query, dataset='preview'))
    (group,) = result['rows']
    (pair,) = group['pairs']
    math = pair['inspection']
    assert [leg['allocation_usd'] for leg in math['legs']] == ['48.84', '51.16']
    assert [leg['win_receipt_usd'] for leg in math['legs']] == ['107.448', '107.436']
    assert math['minimum_profit_usd'] == '7.436'
    assert pair['score'] is None
    assert pair['retail_payoff']['available'] is False
    assert pair['retail_payoff']['reason'] == 'pair_missing_leg_fees'
    assert Fraction(math['ideal_profit_usd']) > Fraction(math['minimum_profit_usd'])
    assert load(dict(query, dataset='preview', positive='on'))['total'] == 0
    assert load(dict(query, dataset='preview', profit='7.44'))['total'] == 0


@pytest.mark.parametrize(
    ('stored_reason', 'expected_reason'),
    [(VETTED_REPLAY_REASON, VETTED_REPLAY_REASON), (RAW_REPLAY_REASON, UNAVAILABLE)],
    ids=['vetted-reason-preserved', 'unknown-reason-redacted'],
)
def test_replay_detail_is_revision_bound_and_never_reads_live_data(saved_archives, stored_reason, expected_reason):
    query = dict(dataset='frozen', view='ev', basis='before', group='offer')
    path = odds_replay.DIRECTORY / 'frozen.sqlite3'
    offer_id = 'practice-offer-0'
    if stored_reason != VETTED_REPLAY_REASON:
        with closing(sqlite3.connect(path)) as db, db:
            (payload,) = db.execute('SELECT payload FROM detail WHERE id=?', (offer_id,)).fetchone()
            saved = unpack(payload)
            saved['row']['trade_fee']['reason'] = stored_reason
            db.execute('UPDATE detail SET payload=? WHERE id=?', (pack(saved), offer_id))
    before = path.read_bytes()
    with (
            patch('app.dashboard.replay_api.connect', side_effect=AssertionError('live replay connection')),
            patch('app.storage.odds_replay.connect', side_effect=AssertionError('live data connection'))):
        page = load(query)
        assert page['replay']['synthetic'] is False
        assert page['coverage'] == dict(offers=6, current=6, before=6, reviewed=0, conservative=0, sportsbooks=6,
                                        after_fees=0)
        sportsbook_view = load(dict(query, basis='sportsbooks'))
        assert all(group['offers'][0]['value_basis'] == 'before' for group in sportsbook_view['rows'])
        modeled = load(dict(query, basis='conservative'))
        assert all(group['score'] is None for group in modeled['rows'])
        assert all(group['offers'][0]['value'] is None for group in modeled['rows'])
        reviewed = load(dict(query, basis='reviewed'))
        assert all(group['score'] is None for group in reviewed['rows'])
        offer = next(group['offers'][0] for group in page['rows'] if group['offers'][0]['id'] == offer_id)
        assert offer['value'] == '10'
        assert offer['fair_reference'] == dict(books=['fanduel'], method='single')
        selection = dict(query, id=offer['id'], result_id=offer['evidence_result_id'])
        detail = load(selection, details=True)
        assert detail['inspection']['reviewed']['available'] is False
        assert detail['inspection']['starting_fee_terms']['scope']
        assert 'fictional' not in str(detail['inspection']['starting_fee_terms']).lower()
        assert detail['inspection']['assumed_scenario']['available'] is False
        assert detail['row']['trade_fee']['reason'] == expected_reason
        assert detail['inspection']['trade_fee']['reason'] == expected_reason
        assert RAW_REPLAY_REASON not in str(detail)
        with odds_replay.open_archive(path) as db:
            payload = db.execute('SELECT payload FROM detail WHERE id=?', (offer['id'],)).fetchone()[0]
        assert unpack(payload)['row']['trade_fee']['reason'] == stored_reason
        assert path.read_bytes() == before
        with pytest.raises(PublicRequestError, match='revision changed'):
            load(dict(selection, dataset='preview'), details=True)


def test_saved_list_and_detail_use_the_same_per_offer_pregame_cutoff(saved_archives):
    path = odds_replay.DIRECTORY / 'frozen.sqlite3'
    offer_id = 'practice-offer-0'
    with closing(sqlite3.connect(path)) as db, db:
        board = unpack(db.execute("SELECT payload FROM archive WHERE kind='board'").fetchone()[0])
        offer = next(row for row in board['rows'] if row['id'] == offer_id)
        offer['captured_at'] = offer['start_at']
        db.execute("UPDATE archive SET payload=? WHERE kind='board'", (pack(board),))
        (payload,) = db.execute('SELECT payload FROM detail WHERE id=?', (offer_id,)).fetchone()
        detail = unpack(payload)
        detail['row']['captured_at'] = offer['captured_at']
        db.execute('UPDATE detail SET payload=? WHERE id=?', (pack(detail), offer_id))

    query = dict(dataset='frozen', view='ev', basis='before', group='offer')
    default = load(query)
    assert default['archive_counts']['observations'] == 5
    assert default['archive_counts']['pairs'] == 0
    assert offer_id not in {offer['id'] for group in default['rows'] for offer in group['offers']}
    selection = dict(query, id=offer_id, result_id=board['id'])
    with pytest.raises(PublicRequestError, match='Offer unavailable'):
        load(selection, details=True)
    opted_in = load(query, allow_live=True)
    assert opted_in['archive_counts']['observations'] == 6
    assert opted_in['archive_counts']['pairs'] == 1
    assert load(selection, details=True, allow_live=True)['row']['id'] == offer_id


@pytest.mark.parametrize('dataset', ['practice', 'synthetic', 'demo', 'unknown'])
@pytest.mark.parametrize('details', [False, True])
def test_replay_rejects_unknown_datasets_without_archive_or_provider_reads(dataset, details, tmp_path, monkeypatch):
    monkeypatch.setattr(odds_replay, 'DIRECTORY', tmp_path)
    with patch('app.dashboard.replay_api.connect', side_effect=AssertionError('live read')):
        with pytest.raises(PublicRequestError, match='Unknown replay dataset'):
            load(dict(dataset=dataset), details=details)
    assert list(tmp_path.iterdir()) == []


def test_retained_novig_recovers_scoped_zero_without_legacy_reference():
    from app.comparison.conditional_benchmark import reviewed_fee
    from app.dashboard.replay_api import archive_detail, archive_offer
    from app.storage.store import stamp

    at = '2026-11-08T04:00:10Z'
    row = dict(id='novig-selected', venue='novig', kind='single', game_state='scheduled',
        start_at='2026-11-09T01:20:00+00:00', market=dict(market='spread', period='full_game', line='3.5'),
        source=dict(provider='the_odds_api', native_side='bookmaker_outcome'),
        original=dict(value='5', units='decimal_odds', payout='1', payout_units='USD'),
        price_current=True, cost_per_normal_claim='0.2', gross_return_percent='1475/139',
        times=dict(source_at='2026-11-08T03:47:47Z', received_at='2026-11-08T03:47:54Z'),
        reference_calculation=dict(available=True, venue='pinnacle', fair_decimal_odds='4.52'),
        probability='123/556')
    row['conditional_trade_benchmark'] = reviewed_fee(row, at=stamp(at),
        event={'start_at': row['start_at']}, group=row['market'])
    saved = archive_offer(row, at)
    inspected = archive_detail(dict(row=row, captured_at=at), 'capture')['inspection']
    assert saved['trade_fee'] == inspected['trade_fee']
    assert saved['trade_fee']['trade_fee_usd'] == '0'
    assert saved['trade_fee']['classification'] == 'recorded_scope'
    assert saved['gross_return_percent'] is None and inspected['probability'] is None
    assert 'pinnacle' not in str(inspected).casefold()
    changed = archive_offer(dict(row, probability='1/2', gross_return_percent='150'), at)
    assert changed == saved
    forged = dict(row, conditional_trade_benchmark=dict(row['conditional_trade_benchmark'], quantity='2'))
    assert not archive_offer(forged, at).get('trade_fee')


def test_saved_starting_terms_survive_missing_tier_and_expired_review():
    at = '2026-11-08T04:00:10+00:00'
    us = starting_fee_terms({'venue': 'polymarket_us'}, at)
    assert us['values'] == [['Historical assumption', '0.0695 taker coefficient'],
                            ['Recorded taker tiers', '0.095 / 0.085 / 0.075 / 0.0695']]
    nhl = starting_fee_terms({'venue': 'prophetx', 'league': 'NHL'}, at)
    assert nhl['in_review_window'] is False
    assert nhl['values'] == [['Recorded public NHL taker formula', '0.035 × price × (1 − price) per contract']]


@pytest.mark.parametrize(('treatment', 'payout', 'refund_fees', 'expected'), [
    ('fraction', '1/2', 'not_applicable', ('0.5', '0.2')),
    ('stake_refund', None, 'retained', ('0.3', '0')),
    ('predicate', None, 'not_applicable', ('0', '-0.3')),
])
def test_inspection_distinguishes_fractional_settlement_refund_and_loss(treatment, payout, refund_fees, expected):
    row = dict(cost_per_normal_claim='0.30', market={'market': 'winner'})
    original = dict(binding={'verified': True}, native_contract={'same_outcome': {
        'predicate': {'domain': 'home_margin', 'operator': 'lt', 'threshold': '0', 'subject_id': None},
        'equality': dict(treatment=treatment, payout=payout, refund_fees=refund_fees, unknown_reason=None),
        'scoring': {'overtime': 'included', 'score_domain': 'integer'},
    }})
    result = settlement_terms(row, original)
    tie = result['outcomes'][2]
    assert tie['label'] == 'Game ends tied'
    assert (tie['payout_usd'], tie['profit_usd']) == expected
    assert result['outcomes'][3]['payout_usd'] is None
    assert settlement_terms(row)['outcomes'][2]['payout_usd'] is None


def test_retired_replay_datasets_fail_at_html_and_api_boundaries_without_sql(tmp_path):
    import asyncio
    from aiohttp.test_utils import TestClient, TestServer
    from app.dashboard.multi_game_server import create_app
    from tests.current_fixture import InjectedTestProvider
    from tests.test_current_state import owner

    async def journey():
        provider = InjectedTestProvider()
        provider.database_mode = True
        from app.dashboard import bet_journal_api
        from app.dashboard.bet_journal import Journal
        original_mount = bet_journal_api.mount
        with patch.object(bet_journal_api, 'mount', side_effect=lambda app: original_mount(
                app, journal=Journal(tmp_path / 'journal.sqlite3'), monitor=False)):
            app = create_app(owner=owner(), sessions={}, current_provider=provider)
        async with TestClient(TestServer(app)) as client:
            with (
                    patch('app.dashboard.replay_api.connect', side_effect=AssertionError('SQL read')),
                    patch.object(odds_replay, 'open_archive', side_effect=AssertionError('archive read'))):
                for dataset in ('practice', 'synthetic', 'demo', 'unknown'):
                    for path in ('/replay', '/data', '/api/odds-replay', '/api/odds-replay/details'):
                        response = await client.get(path, params={'dataset': dataset}, allow_redirects=False)
                        assert response.status == 422, (path, dataset, await response.text())
                        assert await response.json() == {'error': 'Unknown replay dataset'}
                # Supported bookmarks load the current Data shell with their capture identity.
                for dataset in (*odds_replay.DATASETS, 'retained'):
                    selection = dict(dataset=dataset, result_id='saved-capture', game_key='saved-game')
                    response = await client.get('/replay', params=selection)
                    assert response.status == 200
                    assert response.history[0].status == 302
                    assert response.url.path == '/data'
                    assert dict(response.url.query) == selection
                    assert 'data.js' in await response.text()

    asyncio.run(journey())


def test_production_no_longer_recognizes_authored_probability_or_fictional_fee_rates():
    from app.dashboard.product_finance import reference_allowed
    from app.comparison.snapshot_pair_fees import _leg_fee
    assert not reference_allowed(dict(source={'provider': 'practice'}, reference_calculation=dict(
        available=True, method='authored_probability', probability='0.5')))
    row = dict(venue='novig', captured_at='2026-11-18T20:00:00Z', source={'provider': 'practice'}, trade_fee=dict(
        available=True, classification='synthetic', quantity='1',
        evidence={'fictional_rate':'0'}, fee_cashflows={'at_fill_usd':'0'}))
    result = _leg_fee(row, stake=Fraction(50), price=Fraction(2,5), quantity=Fraction(125),
        receipts={'first_wins':Fraction(125), 'second_wins':Fraction(0)})
    assert not result['available']


@pytest.mark.parametrize('allow_synthetic', [False, True])
def test_production_saved_session_bookmark_excludes_mock_history_without_deleting_it(allow_synthetic, tmp_path):
    import asyncio
    import json
    from aiohttp.test_utils import TestClient, TestServer
    from app.collection.transport_session import ObservationJournal
    from app.dashboard.multi_game_server import create_app
    from app.dashboard.current_state import CurrentStateProvider
    from tests.test_current_state import owner

    async def journey():
        provider = CurrentStateProvider()
        provider.database_mode = True
        provider.allow_synthetic = allow_synthetic
        selected_owner = owner()
        paths = {mode: tmp_path / mode for mode in ('real', 'mock')}
        for mode, folder in paths.items():
            (folder / 'session').mkdir(parents=True)
            spec = dict(mode=mode, stale_seconds=30)
            (folder / 'run-spec.json').write_text(json.dumps(spec))
            with closing(ObservationJournal(folder / 'session' / f'{mode}.jsonl')) as journal:
                journal.save(dict(type='session_started', session_id=mode, spec=spec,
                                  observed_at='2026-11-18T20:00:00Z'))
                journal.save(dict(type='session_finished', session_id=mode,
                                  observed_at='2026-11-18T20:00:01Z'))
        selected_owner.history_paths.return_value = paths
        before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}

        app = create_app(owner=selected_owner, sessions={}, current_provider=provider)
        async with TestClient(TestServer(app)) as client:
            legacy = await client.get('/replay?session=real', allow_redirects=False)
            assert legacy.status == 302 and legacy.headers['Location'] == '/data?session=real'
            accepted = await client.get('/api/workspace/session?session=real')
            assert accepted.status == 200, await accepted.text()
            value = await accepted.json()
            assert (value['session_id'], value['data_mode'], value['state']) == ('real', 'real', 'saved')
            assert value['provider_requests'] == value['scheduled_calculations'] == 0
            rejected = await client.get('/api/workspace/session?session=mock')
            assert rejected.status == 422
            assert await rejected.json() == {'error': 'This bookmark does not identify a genuine received-data session.'}

        assert {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()} == before
        selected_owner.close.assert_awaited_once()
    asyncio.run(journey())
