import json
from datetime import datetime

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
    assert page.payload_bytes == len(json.dumps(response()).encode())
    q, = page.quotes
    assert (q['price_american'], q['line'], q['source_at'], q['received_at']) == ('-110', '-1.5', '2026-11-10T19:59:00Z', AT)
    assert q['available'] and q['settlement'] == 'unverified'
    assert q['fair'] == {'available': True, 'price_american': '+101', 'line': '-2', 'source_at': None}


def test_live_clock_sample_requires_both_exact_post_start_reference_sides():
    from app.collection.sportsgameodds_adapter import clock_sample
    data = response()
    event = data['data'][0]
    event['status'].update(startsAt='2026-11-10T19:59:55Z', started=True, live=True)
    home = event['odds']['points-home-game-sp-home']
    book = dict(available=True, odds='-110', spread='-1.5', lastUpdatedAt=AT)
    home.update(bookOdds='-106', bookOddsAvailable=True, bookSpread='-2.5',
                byBookmaker={'pinnacle':book, 'novig':book})
    away = dict(home, oddID=home['opposingOddID'], opposingOddID=home['oddID'],
                statEntityID='away', sideID='away', byBookmaker={'pinnacle':dict(book, spread='1.5')})
    event['odds'][away['oddID']] = away
    cohort = ('NBA','live','spread','novig')
    page = parse(data)
    assert page.quotes[0]['consensus'] == dict(available=True, price_american='-106', line='-2.5', source_at=None)
    assert clock_sample(page)[cohort]['live_with_pinnacle_clocks'] == 1
    assert clock_sample(page)[cohort]['live_with_pinnacle_clocks_at_admission'] == 0
    at_deadline = datetime.fromisoformat('2026-11-10T20:00:15Z')
    after_deadline = datetime.fromisoformat('2026-11-10T20:00:15.001Z')
    assert clock_sample(page, admitted_at=at_deadline)[cohort]['live_with_pinnacle_clocks_at_admission'] == 1
    late = clock_sample(page, admitted_at=after_deadline)[cohort]
    assert late['live_fresh'] == late['live_with_pinnacle_clocks'] == 1
    assert late['live_fresh_at_admission'] == late['live_with_pinnacle_clocks_at_admission'] == 0
    away['byBookmaker']['pinnacle']['lastUpdatedAt'] = '2026-11-10T19:59:54Z'
    old = clock_sample(parse(data))[cohort]
    assert old['live_available'] == old['live_post_start'] == old['live_with_exact_pinnacle_pair'] == 1
    assert old['live_with_post_start_pinnacle_pair'] == old['live_with_pinnacle_clocks'] == 0
    home['byBookmaker']['novig'] = dict(book, lastUpdatedAt='2026-11-10T19:59:30Z')
    stale_offer = clock_sample(parse(data))[cohort]
    assert stale_offer['live_with_exact_pinnacle_pair'] == stale_offer['within_900_seconds'] == 1
    assert stale_offer['within_15_seconds'] == stale_offer['live_post_start'] == stale_offer['live_with_pinnacle_clocks'] == 0
    away['byBookmaker']['pinnacle']['spread'] = '2.5'
    assert clock_sample(parse(data))[cohort]['live_with_exact_pinnacle_pair'] == 0
    event['status']['live'] = False
    assert clock_sample(parse(data))[('NBA','started','spread','novig')]['live_fresh'] == 0


def test_unavailable_vendor_baseline_retains_reported_value_as_context():
    data = response()
    odd = data['data'][0]['odds']['points-home-game-sp-home']
    odd['fairOddsAvailable'] = False
    quote, = parse(data).quotes
    assert quote['fair'] == {'available': False, 'price_american': '+101', 'line': '-2', 'source_at': None}
    odd['fairOddsAvailable'] = True
    del odd['fairSpread']
    quote, = parse(data).quotes
    assert not quote['fair']['available']


def test_unavailable_and_missing_source_are_not_offers():
    data = response()
    books = data['data'][0]['odds']['points-home-game-sp-home']['byBookmaker']
    books['book']['available'] = False
    books['old'] = {'available': True, 'odds': '+150', 'spread': '-1.5'}
    first, second = parse(data).quotes
    assert not first['available'] and first['price_american'] == '-110'
    assert not second['available'] and second['source_at'] is None


def test_completed_event_does_not_leave_book_offer_available():
    data = response()
    data['data'][0]['status']['completed'] = True
    quote, = parse(data).quotes
    assert not quote['available']
    assert quote['unavailable_reason'] == 'event or market ended'


def test_game_score_and_result_are_bounded_receipt_context():
    from app.storage.sportsgameodds_reference import prepare_frames, prepare_page
    data = response()
    event = data['data'][0]
    event['teams']['home']['score'] = 107
    event['teams']['away']['score'] = 101
    event['results'] = {'game': {'home': {'points': 107, 'assists': 24}, 'away': {'points': 101}},
                        '1q': {'home': {'points': 28}}}
    event['status']['finalized'] = True
    event['links'] = {'bookmakers': {
        'novig': 'https://novig.com/event-markets/event-1/sportsgameodds?tracking=discarded#discarded',
        'polymarket': 'https://polymarket.com/event/nba-away-home',
        'kalshi': 'https://user:secret@kalshi.com/event/example',
        'prophetexchange': 'http://example.test/market/12',
        'matchbook': 'https://example.test//bad-path',
        'betfairexchange': 'https://example.test/' + 'x' * 385,
        'other': 'https://example.test/market/42',
    }}
    page = parse(data)
    frame, = prepare_frames(page, prepare_page(page))
    context = frame['facts']['event_context']
    assert context['bookmaker_event_links'] == {
        'novig': {'host': 'novig.com', 'path': '/event-markets/event-1/sportsgameodds'},
        'polymarket': {'host': 'polymarket.com', 'path': '/event/nba-away-home'},
    }
    assert context['scores'] == {'home': '107', 'away': '101'}
    assert context['game_results'] == {'home': '107', 'away': '101'}
    assert context['status']['finalized'] is True
    assert context['teams']['home']['id'] == 'home'
    assert 'assists' not in str(context)


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


def test_unmatched_sgo_event_survives_occurrence_resolution_and_display():
    from app.collection.sportsgameodds_current_rows import current_rows
    from app.comparison.occurrence_matching import OccurrenceResolver
    from app.dashboard.current_contract import serialize
    from app.dashboard.current_normalized import catalog_from_normalized
    from tests.current_fixture import fixture

    data = response()
    odd = data['data'][0]['odds']['points-home-game-sp-home']
    odd['byBookmaker'] = {'novig': odd['byBookmaker']['book']}
    page = parse(data)
    rows, _ = current_rows(page, page.receipt_sha256)
    for row in rows:
        row.pop('_instrument')
        row.pop('_fingerprint')
    resolved = OccurrenceResolver(links=None).resolve(rows, clock=AT)
    assert resolved[0]['quote']['occurrence_match']['status'] == 'unresolved'
    assert resolved[0]['event_scope']['policy'] == 'sgo-provider-event-unverified-1'
    envelope = fixture()
    envelope['mode'] = 'current'
    envelope['clock_at'] = envelope['projected_at'] = AT
    snapshot = serialize(catalog_from_normalized(envelope, resolved, include_profiles=False), allow_synthetic=True)
    quotes = [q for event in snapshot['events'] for group in event['groups']
              for outcome in group['outcomes'] for q in outcome['quotes'].values()]
    assert len(quotes) == 1 and quotes[0]['original']['value'] == '-110'


def test_official_venue_event_link_binds_occurrence_only_with_matching_native_evidence():
    from copy import deepcopy
    from app.collection.sportsgameodds_current_rows import current_rows
    from app.comparison.occurrence_matching import OccurrenceResolver

    data = response()
    raw = data['data'][0]
    raw['links'] = {'bookmakers': {
        'kalshi': 'https://kalshi.com/markets/kxnbagame/nba-game/kxnbagame-26nov11wasind',
        'novig': 'https://novig.com.example/event-markets/01a1c05e-def4-7573-bba4-b4e2ff3b3e2b/sportsgameodds',
    }}
    odd = raw['odds']['points-home-game-sp-home']
    odd['byBookmaker'] = {'kalshi': odd['byBookmaker']['book']}
    page = parse(data)
    sgo = current_rows(page, page.receipt_sha256)[0][0]
    assert sgo['event']['shared_provider_ids'] == {'kalshi_event': 'KXNBAGAME-26NOV11WASIND'}
    assert not sgo['verified']
    native = deepcopy(sgo)
    native['event'].pop('shared_provider_ids')
    native['event'].update(id='KXNBASPREAD-26NOV11WASIND', season='2026', stage='regular',
                           related_game_event_id='KXNBAGAME-26NOV11WASIND')
    native['quote']['source'].update(provider='kalshi', native_event_id=native['event']['id'])
    native['quote']['provenance']['sha256'] = 'a' * 64

    def matches(*rows):
        return [r['quote']['occurrence_match'] for r in OccurrenceResolver().resolve(list(rows), clock=AT)]

    assert matches(sgo)[0]['status'] == 'unresolved'
    a, b = matches(sgo, native)
    assert a['method'] == b['method'] == 'shared_provider_id'
    assert a['occurrence_id'] == b['occurrence_id'] and not a['estimated']
    assert a['original_market_identity']['rules'] == 'sportsgameodds-unverified-1'

    changed = deepcopy(native)
    changed['event']['scheduled_start'] = '2026-11-10T22:01:00Z'
    assert all('shared_id_metadata_conflict' in item['conflicts'] for item in matches(sgo, changed))
    duplicate = deepcopy(sgo)
    duplicate['event']['id'] = duplicate['quote']['source']['native_event_id'] = 'duplicate-event'
    assert all('duplicate_venue_event_link' in item['conflicts'] for item in matches(sgo, duplicate, native))


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
