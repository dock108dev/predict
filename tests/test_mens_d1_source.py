from datetime import UTC, date, datetime
import json

import httpx
import pytest

from app.collection import mens_d1_source as source
from app.normalization.mens_d1_membership import load_membership, membership_for_provider_team


DAY = date(2026, 11, 23)
OBSERVED = datetime(2026, 11, 24, 13, tzinfo=UTC)
DETAIL = f'{source.SOURCE_ORIGIN}/cbb/boxscores/2026-11-23-21-providence.html'


def receipt(html, kind='schedule', *, day=DAY, url=None, error=None):
    url = url or source.source_url(day, kind)
    return source.SourceReceipt(url, OBSERVED, OBSERVED, url, 200, 200, html.encode(), html, error=error)


def schedule(rows, day=DAY):
    return f'<h1>College Basketball Games on {day:%A, %B %d, %Y}</h1><h3>{day:%b %d, %Y} Games</h3>{rows}'


def school(slug, label, gender='men'):
    return f'<a href="/cbb/schools/{slug}/{gender}/2027.html">{label}</a>'


def game_card(status='F <span>inal</span>', overtime='OT', scores=(66, 72)):
    return f'''<h1>College Basketball Box Scores on Monday, November 23, 2026</h1>
    <h2>Men's Games</h2><div class="game_summary"><table class="teams">
    <tr><td>{school('virginia-commonwealth', 'VCU')}</td><td class="right">{scores[0]}</td><td>{status}</td></tr>
    <tr><td>{school('providence', 'Providence')}</td><td class="right">{scores[1]}</td><td>{overtime}</td></tr>
    </table><a href="{DETAIL}">Box Score</a></div>'''


def test_named_non_d1_source_and_provider_teams_share_occurrence_identity():
    from app.storage.mens_d1_occurrences import _pair

    membership = load_membership(DAY)
    college = dict(name='Arkansas Baptist', membership=dict(division='non_d1', season='2026-2027', source_team_id='539'))
    provider = [dict(name=name, membership=membership.lookup(name=name))
                for name in ('Arkansas Baptist Buffaloes', 'Arkansas Little Rock Trojans')]
    assert _pair([college, dict(name='Little Rock', canonical_id='NCAAB:M:D1:NCAA32')]) == _pair(provider) == {
        'NAIA:arkansas-baptist', 'NCAAB:M:D1:NCAA32'}
    assert college['membership']['source_team_id'] == '539'


def test_mixed_schedule_membership_dates_and_cancelled_rows():
    page = schedule(f'''
    <ul><li>{school('virginia-commonwealth', 'VCU')} (4) @ {school('providence', 'Providence')} 9:00pm ET (m)</li>
    <li>Ecclesia @ Grambling 1:00pm (m)</li><li>Unverified State @ Providence 12:00am (m)</li>
    <li>{school('virginia-commonwealth', 'VCU', 'women')} @ Providence 7:00pm (w)</li>
    <li data-neutral-site="true" data-site="Neutral Arena" data-game-id="upstream-123">Army @ Navy Postponed (m)</li>
    <li>Florida @ Ohio Cancelled (m)</li><li>Arkansas @ Florida 4:00pm</li></ul>''')
    rows = source.parse_page(receipt(page), day=DAY, kind='schedule')
    assert [item['membership_status'] for item in rows] == [
        'eligible', 'excluded', 'unresolved', 'excluded', 'eligible', 'eligible', 'unresolved',
    ]
    assert rows[0]['teams'][0]['source_team_id'] == 'virginia-commonwealth'
    assert rows[0]['scheduled_start'] == '2026-11-24T02:00:00+00:00'
    assert rows[1]['teams'][0]['membership']['classification'] == 'NCCAA Division I'
    assert rows[2]['scheduled_start'] == '2026-11-23T05:00:00+00:00'
    assert rows[2]['source_date'] == '2026-11-23'
    assert rows[3]['membership_reason'] == 'womens_game'
    assert rows[4]['status'] == 'postponed'
    assert rows[4]['neutral_site'] is True and rows[4]['site'] == 'Neutral Arena'
    assert rows[4]['native_game_id'] == 'upstream-123'
    assert rows[5]['status'] == 'cancelled'
    assert rows[6]['membership_reason'] == 'gender_unverified'
    assert all(not item['published_at'] for item in rows)


def test_dst_loss_and_overlap_need_actual_timezone_evidence():
    spring = date(2027, 3, 14)
    spring_page = schedule('<p>VCU @ Providence 2:30am ET (m)</p>', spring)
    assert source.parse_page(receipt(spring_page, day=spring), day=spring, kind='schedule')[0]['scheduled_start'] is None
    fall = date(2026, 11, 1)
    fall_page = schedule('<p>VCU @ Providence 1:30am ET (m)</p><p>Florida @ Ohio 1:30am EST (m)</p>', fall)
    rows = source.parse_page(receipt(fall_page, day=fall), day=fall, kind='schedule')
    assert rows[0]['scheduled_start'] is None
    assert rows[1]['scheduled_start'] == '2026-11-01T06:30:00+00:00'
    assert rows[1]['source_timezone'] == 'EST'


def test_rendered_sports_reference_schedule_and_upcoming_index_shapes():
    slate = '''<div id="content"><h1>College Basketball Games on Tuesday, November 24, 2026</h1>
    <div><h3>Nov 24, 2026 Games</h3>
    <span><a href="/cbb/schools/south-carolina/women/2027.html">South Carolina</a> (1) @ UConn (7)
    <span class="note">8:00pm ET (w)</span></span><br>
    <span><a href="/cbb/schools/texas-tech/men/2027.html">Texas Tech</a> (9) @ Louisville (23)
    <span class="note">8:00pm (m)</span></span><br>
    <span>VTSU Randolph @ <a href="/cbb/schools/stonehill/men/2027.html">Stonehill</a>
    <span class="note">1:00pm (m)</span></span></div></div>'''
    day = date(2026, 11, 24)
    women, eligible, excluded = source.parse_page(receipt(slate, day=day), day=day, kind='schedule')
    assert women['membership_reason'] == 'womens_game'
    assert eligible['teams'][0]['source_team_id'] == 'texas-tech'
    assert eligible['scheduled_start'] == '2026-11-25T01:00:00+00:00'
    assert excluded['teams'][0]['source_team_id'] is None
    assert excluded['membership_reason'] == 'participant_not_ncaa_division_i'
    scores = '''<h1>College Basketball Scores on Tuesday, November 24, 2026</h1>
    <div id="div_other_scores"><div class="game_summaries">
    <div class="game_summary nohover gender-m"><table class="teams">
    <tr class="loser"><td><a href="/cbb/schools/milwaukee/men/2027.html">Milwaukee</a></td>
      <td class="right"></td><td class="right gamelink"></td></tr>
    <tr class="loser"><td><a href="/cbb/schools/florida/men/2027.html">Florida</a></td>
      <td class="right"></td><td class="right">7:00p</td></tr>
    <tr><td class="desc" colspan="3">Men's</td></tr>
    </table></div>
    <div class="game_summary nohover gender-m"><table class="teams">
    <tr class="winner"><td><a href="/cbb/schools/san-jose-state/men/2027.html">San Jose State</a></td>
      <td class="right">88</td><td class="right gamelink">F<span class="no_mobile">inal</span></td></tr>
    <tr class="loser"><td><a href="/cbb/schools/california-san-diego/men/2027.html">UC San Diego</a></td>
      <td class="right">79</td><td class="right">&nbsp;</td></tr>
    <tr><td class="desc" colspan="3">Men's</td></tr>
    </table></div></div></div>'''
    upcoming, final = source.parse_page(receipt(scores, 'results', day=day), day=day, kind='results')
    assert upcoming['status'] == 'scheduled'
    assert upcoming['gender'] == 'men'
    assert upcoming['source_time'] == '7:00p'
    assert upcoming['scheduled_start'] is None
    assert final['status'] == 'final' and final['detail_url'] is None
    assert [(team['source_team_id'], team['score'], team.get('role')) for team in final['teams']] == [
        ('san-jose-state', 88, None), ('california-san-diego', 79, None),
    ]


def test_result_status_and_score_evidence_is_conservative():
    row, = source.parse_page(receipt(game_card(), 'results'), day=DAY, kind='results')
    assert row['status'] == 'final'
    assert row['native_game_id'] == '2026-11-23-21-providence'
    assert row['overtime_periods'] == 1
    assert row['detail_reason'] == 'confirm_overtime_period_scores'
    assert [(t['source_team_id'], t['score'], t['period_scores']) for t in row['teams']] == [
        ('virginia-commonwealth', 66, None), ('providence', 72, None),
    ]
    projected, = source.parse_page(receipt(game_card('Prediction', '', (66, 72)), 'results'), day=DAY, kind='results')
    assert projected['status'] == 'unresolved'
    assert all(t['score'] is None for t in projected['teams'])
    incomplete, = source.parse_page(receipt(game_card('Final', '', (66, '')), 'results'), day=DAY, kind='results')
    assert incomplete['status'] == 'incomplete'


def test_detail_joins_reversed_display_order_by_team_and_preserves_corrections():
    row, = source.parse_page(receipt(game_card(), 'results'), day=DAY, kind='results')
    scheduled, = source.parse_page(receipt(schedule('<p>VCU @ Providence 9:00pm ET (m)</p>')),
                                   day=DAY, kind='schedule')
    assert row['source_game_id'] == scheduled['source_game_id']
    html = f'''<h1>Virginia Commonwealth vs. Providence Box Score (Men), November 23, 2026</h1>
    <!--<table id="line-score"><tbody>
    <tr><th>{school('providence', 'Providence')}</th><td data-stat="1">30</td><td data-stat="2">31</td>
    <td data-stat="OT">11</td><td data-stat="T">72</td></tr>
    <tr><th>{school('virginia-commonwealth', 'VCU')}</th><td data-stat="1">32</td><td data-stat="2">29</td>
    <td data-stat="OT">5</td><td data-stat="T">66</td></tr></tbody></table>-->'''
    corrected = source.parse_detail(receipt(html, url=DETAIL), day=DAY, game=row)
    assert corrected['source_game_id'] == row['source_game_id']
    assert corrected['overtime_periods'] == 1
    assert [(t['score'], t['period_scores']) for t in corrected['teams']] == [(66, [32, 29, 5]), (72, [30, 31, 11])]
    changed_result = html.replace('>5</td>', '>6</td>').replace('>66</td>', '>67</td>')
    conflict = source.parse_detail(receipt(changed_result, url=DETAIL), day=DAY, game=row)
    assert conflict['detail_reason'] == 'index_detail_score_conflict'
    assert [t['score'] for t in conflict['teams']] == [67, 72]
    assert [t['score'] for t in row['teams']] == [66, 72]
    with pytest.raises(source.SourcePageError, match='team_identity_unverified'):
        source.parse_detail(receipt(html.replace('virginia-commonwealth', 'richmond'), url=DETAIL), day=DAY, game=row)


@pytest.mark.parametrize('html,reason', [
    ('<title>Just a moment...</title><p>No games today.</p>', 'block_or_login_page'),
    (schedule('<p>Schedule temporarily unavailable.</p>'), 'no_recognized_games_or_empty_marker'),
    (schedule('<p>No games on this date.</p>', date(2026, 11, 24)), 'wrong_date'),
])
def test_wrong_or_unrecognized_page_is_not_empty(html, reason):
    with pytest.raises(source.SourcePageError, match=reason):
        source.parse_page(receipt(html), day=DAY, kind='schedule')


def test_explicit_empty_schedule_and_missing_timezone():
    assert source.parse_page(receipt(schedule('<p>No games on this date.</p>')), day=DAY, kind='schedule') == []
    row, = source.parse_page(receipt(schedule('<p>VCU @ Providence 9:00pm (m)</p>')), day=DAY, kind='schedule')
    assert row['source_time'] == '9:00pm'
    assert row['source_timezone'] is None
    assert row['scheduled_start'] is None


def test_provider_membership_uses_season_record_and_exact_reviewed_aliases():
    lookup = membership_for_provider_team
    assert lookup('sportsgameodds:NCAAB:observed:home', day=DAY, label='IUPUI Jaguars')['canonical_id'] == 'NCAAB:M:D1:NCAA2699'
    assert lookup('sportsgameodds:NCAAB:observed:away', day=DAY, label='Ecclesia Royals')['division'] == 'non_d1'
    assert lookup('NCAAB:M:D1:NCAA556', day=DAY, label='VCU')['reason'] == 'participant_identity_disagreement'
    assert lookup('NCAAB:M:D1:unreviewed', day=DAY, label='Providence College II')['division'] == 'unknown'
    assert lookup('NCAAB:M:D1:NCAA556', day=date(2027, 11, 23), label='Providence')['division'] == 'unknown'
    assert load_membership(DAY).version == load_membership(date(2027, 2, 10)).version


def test_firecrawl_records_exact_response_with_documented_request_and_no_invented_cost():
    url = source.source_url(DAY, 'schedule')
    html = schedule('<p>No games on this date.</p>')
    payload = json.dumps({'success': True, 'data': {'metadata': {'sourceURL': url, 'statusCode': 200},
                                                    'rawHtml': html, 'links': []}}).encode()

    def respond(request):
        assert str(request.url) == source.FIRECRAWL_URL
        assert request.headers['Authorization'] == 'Bearer local-test-key'
        assert json.loads(request.content) == {'url': url, 'maxAge': 0, 'formats': ['rawHtml', 'links'],
                                               'proxy': 'basic', 'timeout': 20000}
        return httpx.Response(200, content=payload)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        capture = source.fetch_firecrawl(url, api_key='local-test-key', client=client)
    assert capture.raw_body == payload
    assert capture.received_at >= capture.requested_at
    assert capture.credits_used is None
    assert source.parse_page(capture, day=DAY, kind='schedule') == []


def test_firecrawl_bound_and_redirect_preserve_failure():
    url = source.source_url(DAY, 'schedule')
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, content=b'x' * (source.MAX_FIRECRAWL_RESPONSE_BYTES + 1),
    ))) as client:
        capture = source.fetch_firecrawl(url, api_key='local-test-key', client=client)
    assert capture.error == 'firecrawl_response_too_large'
    assert capture.credits_used is None
    assert capture.raw_body == b''
    with pytest.raises(source.SourcePageError, match='response_too_large'):
        source.parse_page(capture, day=DAY, kind='schedule')
    redirect = {'success': True, 'data': {'metadata': {'sourceURL': 'https://example.test/login', 'statusCode': 200},
                                         'rawHtml': schedule('<p>No games on this date.</p>'), 'links': []}}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=redirect))) as client:
        capture = source.fetch_firecrawl(url, api_key='local-test-key', client=client)
    assert capture.error == 'sports_reference_unexpected_redirect'
    assert capture.raw_body


def test_firecrawl_discards_credentials_and_exits_elapsed_read(monkeypatch):
    url = source.source_url(DAY, 'schedule')
    payload = br'{"success": false, "error": "local-test-\u006bey"}'
    transport = httpx.MockTransport(lambda request: httpx.Response(401, content=payload))
    with httpx.Client(transport=transport) as client:
        capture = source.fetch_firecrawl(url, api_key='local-test-key', client=client)
        assert capture.error == 'firecrawl_credential_echo_discarded'
        assert capture.raw_body == b'' and capture.raw_html is None
        timeline = iter([0.0, source.FIRECRAWL_READ_DEADLINE_SECONDS + 1])
        monkeypatch.setattr(source, 'monotonic', lambda: next(timeline))
        capture = source.fetch_firecrawl(url, api_key='local-test-key', client=client)
        assert capture.error == 'firecrawl_response_deadline'
        assert capture.raw_body == b''
