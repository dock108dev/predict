import json

import pytest

from app.collection.sportsgameodds_adapter import Page, Traversal, parse_page

AT = '2026-11-10T20:00:00Z'


def response():
    books = {'book': {'available': True, 'odds': '-110', 'spread': '-1.5', 'lastUpdatedAt': '2026-11-10T19:59:00Z'}}
    return {'success': True, 'data': [{'eventID': 'event', 'leagueID': 'NBA',
        'teams': {role: {'teamID': role, 'names': {'long': role.title()}} for role in ('home', 'away')},
        'status': {'startsAt': '2026-11-10T21:00:00Z', 'started': False, 'live': False},
        'odds': {'points-home-game-sp-home': {'oddID': 'points-home-game-sp-home',
            'opposingOddID': 'points-away-game-sp-away', 'periodID': 'game', 'statID': 'points',
            'statEntityID': 'home', 'betTypeID': 'sp', 'sideID': 'home', 'byBookmaker': books,
            'fairOddsAvailable': True, 'fairOdds': '+101', 'fairSpread': '-2'}}}]}


def parse(data):
    return parse_page(json.dumps(data).encode(), AT)


def test_exact_source_and_receipt_clocks_and_fair_line():
    page = parse(response())
    q, = page.quotes
    assert (q['price_american'], q['line'], q['source_at'], q['received_at']) == ('-110', '-1.5', '2026-11-10T19:59:00Z', AT)
    assert q['available'] and q['settlement'] == 'unverified'
    assert q['fair'] == {'available': True, 'price_american': '+101', 'line': '-2', 'source_at': None}


def test_unavailable_and_missing_source_are_not_offers():
    data = response()
    books = data['data'][0]['odds']['points-home-game-sp-home']['byBookmaker']
    books['book']['available'] = False
    books['old'] = {'available': True, 'odds': '+150', 'spread': '-1.5'}
    first, second = parse(data).quotes
    assert not first['available'] and first['price_american'] == '-110'
    assert not second['available'] and second['source_at'] is None


def test_unsupported_team_total_and_invalid_response_fail_safely():
    data = response()
    odd = data['data'][0]['odds']['points-home-game-sp-home']
    odd.update(betTypeID='ou', sideID='over', statEntityID='home')
    assert not parse(data).quotes
    data['success'] = False
    with pytest.raises(ValueError):
        parse(data)
    with pytest.raises(ValueError):
        parse_page(b'{"success":true,"success":false}', AT)


def test_traversal_never_authorizes_withdrawal_and_rejects_partial_cycles():
    t = Traversal()
    t.add(None, Page(({'event_id': 'a'},), (), 'next'))
    assert not t.complete and not t.authoritative_absence
    t.add('next', Page(({'event_id': 'b'},), (), None))
    assert t.complete and not t.authoritative_absence
    t = Traversal()
    t.add(None, Page(({'event_id': 'a'},), (), 'next'))
    with pytest.raises(ValueError):
        t.add('next', Page(({'event_id': 'a'},), (), None))
    assert not t.complete


def test_current_row_projection_is_exact_unverified_and_not_native():
    from app.collection.sportsgameodds_current_rows import current_rows
    from app.dashboard.u0_display import quote_display
    from app.storage.current_rows import prepare

    data = response()
    event = data['data'][0]
    home = event['odds']['points-home-game-sp-home']
    home['byBookmaker'] = {'novig': home['byBookmaker']['book']}
    home['byBookmaker']['novig']['available'] = False
    away = dict(home, oddID='points-away-game-sp-away', opposingOddID=home['oddID'],
                statEntityID='away', sideID='away',
                byBookmaker={'novig': dict(home['byBookmaker']['novig'], spread='1.5', odds='+100')})
    event['odds'][away['oddID']] = away
    page = parse(data)
    rows, exclusions = current_rows(page, page.receipt_sha256)
    assert not exclusions and len(rows) == 2
    for row in rows:
        assert row['quote']['source']['provider'] == 'sportsgameodds'
        assert row['quote']['original']['units'] == 'american_odds'
        assert not row['verified']
        display = quote_display(row['quote']['original']['value'], 'american_odds')
        assert display['supported'] and display['american'] == row['quote']['original']['value']
        assert prepare(row)
    assert {r['quote']['original']['value'] for r in rows} == {'-110', '+100'}
    assert all(r['quote']['state'] == 'unavailable' for r in rows)
    with pytest.raises(ValueError, match='digest mismatch'):
        current_rows(page, 'a' * 64)


def test_current_rows_reject_mismatches_and_unestablished_polymarket():
    from app.collection.sportsgameodds_current_rows import current_rows
    data = response()
    odd = data['data'][0]['odds']['points-home-game-sp-home']
    odd['byBookmaker'] = {'polymarket': odd['byBookmaker']['book']}
    page = parse(data)
    rows, exclusions = current_rows(page, page.receipt_sha256)
    assert not rows and exclusions[0][2] == 'unsupported current-row venue'


def test_unpaired_quote_survives_current_snapshot_without_opposing_price():
    from app.collection.sportsgameodds_current_rows import current_rows
    from app.dashboard.current_contract import serialize
    from app.dashboard.current_normalized import catalog_from_normalized
    from tests.current_fixture import fixture

    data = response()
    odd = data['data'][0]['odds']['points-home-game-sp-home']
    odd['byBookmaker'] = {'novig': odd['byBookmaker']['book']}
    page = parse(data)
    rows, exclusions = current_rows(page, page.receipt_sha256)
    assert not exclusions and len(rows) == 1
    for row in rows:
        row.pop('_instrument')
        row.pop('_fingerprint')
    envelope = fixture()
    envelope['mode'] = 'current'
    envelope['clock_at'] = envelope['projected_at'] = AT
    raw = catalog_from_normalized(envelope, rows, include_profiles=False)
    snapshot = serialize(raw, allow_synthetic=True)
    outcomes = snapshot['events'][0]['groups'][0]['outcomes']
    quotes = [q for outcome in outcomes for q in outcome['quotes'].values()]
    assert len(outcomes) == 2 and len(quotes) == 1
    assert quotes[0]['state'] == 'available'
    assert quotes[0]['original']['value'] == '-110'
    assert quotes[0]['source']['provider'] == 'sportsgameodds'
    assert not quotes[0]['binding']['verified']
    assert not quotes[0]['comparison']['eligible']


def test_synthetic_alternate_lines_keep_separate_clocks_and_unpaired_prices():
    from app.collection.sportsgameodds_current_rows import current_rows
    data = response()
    odd = data['data'][0]['odds']['points-home-game-sp-home']
    book = odd['byBookmaker'].pop('book')
    odd['byBookmaker']['novig'] = book
    book['altLines'] = [
        {'available': True, 'odds': '+135', 'spread': '-2.5', 'lastUpdatedAt': '2026-11-10T19:58:00Z'},
        {'available': False, 'odds': '+170', 'spread': '-3.5'},
    ]
    page = parse(data)
    assert [(q['line'], q['source_at'], q['available']) for q in page.quotes] == [
        ('-1.5', '2026-11-10T19:59:00Z', True),
        ('-2.5', '2026-11-10T19:58:00Z', True),
        ('-3.5', None, False),
    ]
    rows, exclusions = current_rows(page, page.receipt_sha256)
    assert not exclusions and len(rows) == 3
    assert {r['selection']['signed_line'] for r in rows} == {'-1.5', '-2.5', '-3.5'}
    assert len({r['_instrument'] for r in rows}) == 3
    from app.storage.current_rows import prepare
    assert all(prepare(row) for row in rows)
    assert next(r for r in rows if r['selection']['signed_line'] == '-3.5')['quote']['state'] == 'unavailable'


def test_offset_clocks_normalize_to_utc_and_aliases_status_are_retained():
    from app.collection.sportsgameodds_current_rows import current_rows
    from app.storage.current_rows import prepare

    data = response()
    event = data['data'][0]
    event['aliases'] = ['old-event']
    event['status']['startsAt'] = '2026-11-10T16:00:00-05:00'
    event['status']['cancelled'] = True
    book = event['odds']['points-home-game-sp-home']['byBookmaker'].pop('book')
    book['lastUpdatedAt'] = '2026-11-10T14:59:00-05:00'
    event['odds']['points-home-game-sp-home']['byBookmaker']['novig'] = book
    page = parse_page(json.dumps(data).encode(), '2026-11-10T15:00:00-05:00')
    quote, = page.quotes
    assert quote['source_at'] == '2026-11-10T19:59:00+00:00'
    assert quote['source_at_original'] == '2026-11-10T14:59:00-05:00'
    assert quote['received_at'] == '2026-11-10T20:00:00+00:00'
    assert not quote['available']
    rows, exclusions = current_rows(page, page.receipt_sha256)
    assert not exclusions and len(rows) == 1
    assert rows[0]['event']['scheduled_start'] == '2026-11-10T21:00:00+00:00'
    assert rows[0]['comparison_source_metadata']['provider_event_aliases'] == ['old-event']
    assert rows[0]['comparison_source_metadata']['provider_opposing_odd_id'] == 'points-away-game-sp-away'
    assert prepare(rows[0])['contract']['comparison_source_metadata']['provider_opposing_odd_id'] == 'points-away-game-sp-away'
    assert rows[0]['comparison_source_metadata']['provider_event_status']['cancelled'] is True
    assert rows[0]['quote']['state'] == 'unavailable'
    assert prepare(rows[0])
    book['lastUpdatedAt'] = '2026-11-10T19:59:00.1234567Z'
    assert not parse(data).quotes[0]['available']
