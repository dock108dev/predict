/* Small real Chromium + disposable SQL walkthrough; no performance campaign. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const [base, out] = process.argv.slice(2);

(async () => {
  const { chromium } = require(process.env.PREDICT_PLAYWRIGHT_MODULE || 'playwright');
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.PREDICT_CI_CHROMIUM ? { executablePath: process.env.PREDICT_CI_CHROMIUM } : {}) });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce', serviceWorkers: 'block' });
    const page = await context.newPage(), errors = [], external = [];
    page.on('pageerror', error => errors.push(String(error)));
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin !== base) { external.push(route.request().url()); return route.abort(); }
      return route.continue();
    });
    // A test-owned historical clock qualifies only the authored fixture models.
    await page.addInitScript(() => { Date.now = () => Date.parse('2026-10-11T12:00:02Z'); });
    const control = async action => {
      const response = await fetch(base + '/__test/state', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }) });
      const text = await response.text();
      assert(response.ok, action + ': ' + response.status + ' ' + text); return JSON.parse(text);
    };
    const ready = () => page.waitForFunction(() => window.predictTicketObservations?.().ready === true);
    const row = () => page.locator('.scanner-row button').first();
    const noOverflow = async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'horizontal overflow');
    await page.goto(base);
    await page.waitForSelector('.scanner-row');
    assert.equal(await page.locator('#scanner-sound').getAttribute('aria-pressed'), 'false');
    await row().click(); await ready(); await noOverflow();
    assert.equal(await page.locator('.ticket-leg').count(), 2);
    await page.screenshot({ path: path.join(out, 'desktop-ready.png') });
    const selected = await page.evaluate(() => window.predictTicketObservations().selection);
    assert(selected.dependency_revision && selected.economic_revision);
    await page.locator('#ticket-amount').fill('40');
    await page.getByRole('button', { name: 'Check amount', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#scanner-selection-content').textContent.includes('Proposed replacement'));
    assert.equal(await page.evaluate(() => window.predictTicketObservations().ready), false);
    await page.getByRole('button', { name: 'Adopt updated allocations' }).click(); await ready();
    await control('change');
    await page.waitForFunction(() => !window.predictTicketObservations().ready);
    await page.waitForFunction(() => document.querySelector('#scanner-selection-content').textContent.includes('Proposed replacement'));
    await page.screenshot({ path: path.join(out, 'changed-replacement.png') });
    await page.getByRole('button', { name: 'Adopt updated allocations' }).click(); await ready();
    await page.setViewportSize({ width: 390, height: 900 });
    await page.locator('#scanner-selection').evaluate(node => { node.scrollTop = 0; });
    await noOverflow();
    await page.screenshot({ path: path.join(out, 'mobile-390-ready.png') });
    await page.locator('#scanner-close').click();
    await page.locator('#scanner-search').fill('Authored');
    await page.locator('#scanner-search').press('Tab');
    await page.waitForSelector('.scanner-row');
    await row().click(); await ready();
    await page.locator('#scanner-stop').click();
    await page.waitForFunction(() => !window.predictTicketObservations().ready);
    await page.screenshot({ path: path.join(out, 'mobile-stopped.png') });
    await control('reopen'); await page.reload(); await page.waitForSelector('.scanner-row');
    await row().click(); await ready();
    await control('epoch');
    await page.waitForFunction(() => !window.predictTicketObservations().ready);
    await page.screenshot({ path: path.join(out, 'resynchronization.png') });
    await page.reload(); await page.waitForSelector('.scanner-row');
    const arrival = await page.evaluate(() => window.predictArrivalObservations?.());
    assert(!arrival || arrival.sounds === 0, 'reopen/resync invented audible arrival');
    const state = await control('');
    assert.equal(state.provider_requests, 0);assert.deepEqual(errors, []);assert.deepEqual(external, []);
    fs.writeFileSync(path.join(out, 'verification.json'), JSON.stringify({
      evidence_class: 'Fixture only: actual Chromium, real disposable PostgreSQL, real background financial owners and database app reader; authored models and exact destinations. No provider requests or production/customer authority.',
      browser: await browser.version(), events: 2, provider_requests: 0, external_requests: 0,
      desktop: [1440, 900], mobile: [390, 900],
      checks: ['latest SQL visible on open', 'coherent selected ticket', 'Amount and explicit adoption', 'changed SQL replacement', 'mobile no horizontal overflow', 'filter read', 'Stop withdraws authority', 'reopen', 'epoch resynchronization', 'quiet default arrivals'],
      final_runtime_id: state.runtime_id, errors
    }, null, 2) + '\n');
    console.log('PASS DA focused Chromium: two events, desktop/390px, Amount/change/Stop/reopen/resync, zero provider requests');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
