"""Dashboard board, immutable evidence, and freshness states through the normal UI."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

import pytest

from browser_tests.test_pregame_current import offer

ASSETS = Path(__file__).resolve().parents[1] / 'app/dashboard/opportunity_static/current'


@pytest.mark.parametrize('width', [1360, 390])
def test_dashboard_keeps_board_and_reads_the_exact_offer(width):
    from playwright.sync_api import expect, sync_playwright

    full = offer()
    full['raw'].update(posted_decimal='11/5', after_fee_decimal='272/125')
    full['fee_mode'] = {'enabled': False}
    key = dict(market_id='canonical:fixture|spread|full_game',
               pull_id='covering-pull', offer_id='exact-offer', revision='offer-revision')
    detail = dict(id=key['offer_id'], revision=key['revision'], calculation_payload=full,
                  calculation={'status': 'positive', 'net_ev_percent': '44/5'})
    row = dict(full, **{k: v for k, v in key.items() if k != 'offer_id'},
               eligible_until=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
               calculation=detail['calculation'], line='-1.5')
    row['id'] = key['offer_id']
    listing = {'rows': [row], 'total': 1, 'offset': 0}
    mode = {'state': 'ready'}
    requests = []
    errors = []

    def serve(route):
        url = urlparse(route.request.url)
        if url.hostname != 'predict.fixture' or route.request.method != 'GET':
            errors.append('Unexpected external or mutating request')
            route.abort()
            return
        requests.append(url.path)
        if url.path == '/':
            route.fulfill(path=ASSETS / 'dashboard.html', content_type='text/html')
        elif url.path == '/api/research/dashboard':
            if mode['state'] == 'failed':
                route.fulfill(status=503, json={})
                return
            if mode['state'] == 'ready':
                route.fulfill(json=listing)
                return
            states = {
                'empty': {'price_available': True},
                'missing': {'price_available': True, 'inputs_unavailable': True},
                'expired': {'expired_positive': True},
            }
            route.fulfill(json={'rows': [], 'total': 0, 'offset': 0, 'availability': states[mode['state']]})
        elif url.path in ('/api/research/market', '/api/research/market-export'):
            assert parse_qs(url.query) == {k: [v] for k, v in key.items()}
            route.fulfill(json={'selected_offer': detail}, headers={
                'Content-Disposition': 'attachment; filename="predict-market-evidence.json"'
            } if url.path.endswith('-export') else {})
        elif url.path.startswith('/api/'):
            # The shared status check is read-only and independent of the board.
            route.fulfill(status=503, json={})
        elif (asset := ASSETS / Path(url.path).name).suffix in {'.css', '.js', '.woff2', '.ttf'} and asset.is_file():
            route.fulfill(path=asset)
        else:
            route.fulfill(status=404)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': 850})
        page.route('**/*', serve)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://predict.fixture/')
        table = page.get_by_role('table', name='Current +EV opportunities')
        expect(table).to_be_visible()
        expect(table.get_by_role('columnheader', name='EV', exact=True)).to_have_attribute('aria-sort', 'descending')
        for value in ('+100', '+120', '+8.80%'):
            expect(table.get_by_role('cell', name=re.compile(re.escape(value) + '$'))).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
        trigger = table.get_by_role('button', name='Orlando Magic -1.5 · Milwaukee Bucks at Orlando Magic · ProphetX · View evidence')
        trigger.focus()
        trigger.press('Enter')
        inspector = page.get_by_role('dialog')
        expect(inspector.get_by_role('heading', name='Reference prices')).to_be_visible()
        expect(inspector.get_by_text('$0 modeled fees', exact=False)).to_be_visible()
        expect(inspector.get_by_text('home (this bet) · -110', exact=False)).to_be_visible()
        inspector.get_by_text('Net expected value', exact=True).click()
        expect(inspector.get_by_text('Net EV = p × win return + (1 − p) × loss return.', exact=True)).to_be_visible()
        expect(inspector.get_by_role('link', name='Open original odds pull in Data')).to_have_attribute('href',
            '/data?evidence=pulls&pull=covering-pull&sport=NBA&family=spread')
        with page.expect_download() as transfer:
            inspector.get_by_role('link', name='Export this calculation').click()
        assert 'offer-revision' in transfer.value.path().read_text()
        assert urlparse(page.url).path == '/'
        inspector.get_by_role('button', name='Close', exact=True).click()
        expect(trigger).to_be_focused()
        expect(table).to_be_visible()

        status = page.locator('#dashboard-status')
        for state, text in [('expired', 'stale or withdrawn inputs'), ('missing', 'Some calculations are unavailable.'),
                            ('empty', 'No current +EV opportunities'), ('failed', 'Current opportunities are unavailable.')]:
            mode['state'] = state
            page.get_by_role('button', name='Reload saved prices').click()
            expect(status).to_contain_text(text)
            expect(table).to_be_hidden()
        assert requests.count('/api/research/market') == 1
        assert not errors
