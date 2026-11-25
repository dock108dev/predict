"""Owner can configure a week, compare EV screens and revise it without a CLI."""
import os
import re
from urllib.parse import urlsplit
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from app.research.paper_campaigns import analysis, configuration
from browser_tests.test_research_workspace import research_http_fixture
from browser_tests.test_pregame_current import ASSETS
from tests.test_paper_campaigns import config, ticket


def test_schedule_week_ev_comparisons_and_revision_form():
    identity, revision, older = 'a'*64, 'c'*64, 'd'*64
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
            route.fulfill(json=dict(id=revision if len(saved)>1 else identity,**cfg))
        elif path in {f'/api/research/workspace/campaigns/{campaign}' for campaign in (identity, revision)}:
            selected=path.rsplit('/',1)[-1]
            route.fulfill(json=dict(id=selected,config=dict(cfg,supersedes=identity) if selected==revision else cfg,weekly=results,reported_days=1,
                days=[dict(date='2026-11-23',state='published',result_state='graded',run_id='b'*64,
                           retrospective=True,captures=dict(captured=1),analysis=results,
                           snapshots=[dict(id=older,recorded_at='2026-11-23T22:40:00Z')]),
                      dict(date='2026-11-29',state='scheduled')]))
        else:
            route.fulfill(status=404)

    with research_http_fixture(serve) as base,sync_playwright() as runtime:
        browser=runtime.chromium.launch(executable_path=os.getenv('PREDICT_CI_CHROMIUM'))
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
        expect(page.get_by_role('navigation',name='Report period').get_by_role('link',name='Weekly')).to_have_attribute('aria-current','page')
        assert saved[0]['kelly_multiplier']=='0.025'
        assert saved[0]['bucket_edges']==['0.04','0.08','0.15','0.25']
        expect(page.get_by_role('heading',name='EV buckets',exact=True)).to_be_visible()
        expect(page.get_by_role('heading',name='What if the minimum EV changed?',exact=True)).to_be_visible()
        expect(page.get_by_role('link',name='2026-11-23',exact=True)).to_have_attribute('href',re.compile('run='))
        expect(page.get_by_role('row').filter(has_text='2026-11-29')).to_contain_text('Awaiting evidence')
        page.get_by_role('link',name='2026-11-29',exact=True).click()
        expect(page.get_by_role('navigation',name='Report period').get_by_role('link',name='Daily')).to_have_attribute('aria-current','page')
        expect(page.get_by_role('status').filter(has_text='Awaiting retained capture evidence')).to_be_visible()
        expect(page.get_by_label('Game date (Eastern)')).to_have_value('2026-11-29')
        page.reload()
        expect(page.get_by_label('Game date (Eastern)')).to_have_value('2026-11-29')
        page.get_by_role('link',name='Weekly',exact=True).click()
        expect(page.get_by_role('heading',name='Daily results',exact=True)).to_be_visible()
        expect(page.get_by_role('link',name='Daily',exact=True)).to_have_attribute('href',re.compile('date=2026-11-29'))
        page.get_by_text('Previous snapshots (1)',exact=True).click()
        expect(page.get_by_role('link',name=re.compile(older[:12]))).to_have_attribute('href',re.compile(f'run={older}'))
        page.get_by_role('link',name='All qualifying venues',exact=True).click()
        expect(page.get_by_role('link',name='All qualifying venues',exact=True)).to_have_attribute('aria-current','true')
        page.get_by_role('button',name='Edit as a new version').click()
        expect(page.get_by_label('Full Kelly used (%)')).to_have_value('2.5')
        page.reload()
        expect(page.get_by_label('Full Kelly used (%)')).to_have_value('2.5')
        page.get_by_label('Minimum EV (%)').fill('4.19')
        page.get_by_label('EV bucket boundaries (%)').fill('4.19, 8, 15, 25')
        page.get_by_role('button',name='Save and schedule experiment').click()
        expect(page.get_by_role('link',name='Open previous experiment version')).to_have_attribute('href',re.compile(f'campaign={identity}.*variant=all_venues'))
        assert saved[1]['supersedes']==identity
        assert saved[1]['minimum_ev']==saved[1]['bucket_edges'][0]=='0.0419'
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
        browser.close()
