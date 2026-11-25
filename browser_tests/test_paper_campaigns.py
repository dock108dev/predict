"""Owner can configure a week, compare EV screens and revise it without a CLI."""
from urllib.parse import urlsplit
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from app.research.paper_campaigns import analysis, configuration
from browser_tests.test_research_workspace import research_http_fixture
from browser_tests.test_pregame_current import ASSETS
from tests.test_paper_campaigns import config, ticket


def test_schedule_week_ev_comparisons_and_revision_form():
    identity='a'*64
    cfg=configuration(config())
    results=analysis([ticket('trade','.08')],cfg['bucket_edges'],'best_venue')
    saved=[]
    errors=[]

    def serve(route):
        path=urlsplit(route.request.url).path
        if path=='/research':
            route.fulfill(path=ASSETS/'research-workspace.html')
        elif path.startswith('/view/current/'):
            route.fulfill(path=ASSETS/Path(path).name)
        elif path=='/api/research/workspace':
            route.fulfill(json=dict(definitions=[],runs=[],campaigns=[]))
        elif path=='/api/workspace/status':
            route.fulfill(json={})
        elif path=='/api/research/workspace/campaigns' and route.request.method=='POST':
            saved.append(route.request.post_data_json)
            route.fulfill(json=dict(id=identity,**cfg))
        elif path=='/api/research/workspace/campaigns/'+identity:
            route.fulfill(json=dict(id=identity,config=cfg,weekly=results,reported_days=1,
                days=[dict(date='2026-11-23',state='published',result_state='graded',run_id='b'*64,
                           retrospective=True,captures=dict(captured=1),analysis=results),
                      dict(date='2026-11-29',state='scheduled')]))
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base,sync_playwright() as runtime:
        browser=runtime.chromium.launch()
        page=browser.new_page(viewport=dict(width=390,height=820))
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(base+'/research?section=experiments&view=schedule')
        page.get_by_label('Experiment name',exact=True).fill('NCAAB week')
        page.get_by_label('First game date').fill('2026-11-23')
        page.get_by_label('Last game date').fill('2026-11-29')
        expect(page.get_by_label('Full Kelly used (%)')).to_have_value('2.5')
        expect(page.locator('form')).to_contain_text('$11.00')
        page.get_by_role('button',name='Save and schedule experiment').click()
        expect(page.get_by_role('heading',name='Daily results',exact=True)).to_be_visible()
        assert saved[0]['kelly_multiplier']=='0.025'
        assert saved[0]['bucket_edges']==['0.04','0.08','0.15','0.25']
        expect(page.get_by_role('heading',name='EV buckets',exact=True)).to_be_visible()
        expect(page.get_by_role('heading',name='What if the minimum EV changed?',exact=True)).to_be_visible()
        expect(page.get_by_role('link',name='2026-11-23',exact=True)).to_have_attribute('href',__import__('re').compile('run='))
        page.get_by_role('link',name='All qualifying venues',exact=True).click()
        expect(page.get_by_role('link',name='All qualifying venues',exact=True)).to_have_attribute('aria-current','true')
        page.get_by_role('button',name='Edit as a new version').click()
        expect(page.get_by_label('Full Kelly used (%)')).to_have_value('2.5')
        assert not errors
        browser.close()
