import {evidenceReason} from './desk-reasons.js';

const count = n => n == null ? 'Unavailable' : n.toLocaleString();

const names = {kalshi:'Kalshi', polymarket_us:'Polymarket US', sportsgameodds:'SportsGameOdds',
  novig:'Novig', prophetx:'ProphetX', the_odds_api:'The Odds API'};
const label = value => names[value] || (value ? value[0].toUpperCase() + value.slice(1).replaceAll('_',' ') : 'Unknown');

function renderFunnel(parent, report) {
  const table = document.createElement('table');
  const header = table.createTHead().insertRow();
  for (const name of ['Venue / route', 'Market', 'Offers listed', 'Received', 'Admitted', 'Published', 'In exact Browse', 'With fee']) {
    const cell = document.createElement('th'); cell.scope = 'col'; cell.textContent = name; header.append(cell);
  }
  const body = table.createTBody();
  for (const c of report.cohorts) {
    const source = c.source_originals, working = c.sql_working, desk = c.desk_access;
    const row = body.insertRow();
    const offered = c.provider_universe_complete ? count(c.offered_price_units) : 'Unknown';
    const published = desk?.published ?? c.ordinary_publication?.published;
    for (const value of [`${label(c.venue)} / ${label(c.provider)}`, `${c.league || 'Unknown'} ${label(c.family)}`,
      offered, count(source?.received_frame_members), count(working?.retained_available_prices), count(published),
      desk?.excluded_aggregate_relay ? `${count(desk.available_in_exact_browse)} · ${count(desk.excluded_aggregate_relay)} relay excluded`
        : count(desk?.available_in_exact_browse), count(c.ordinary_publication?.posted_fee)]) row.insertCell().textContent = value;
  }
  const note = document.createElement('p');
  note.textContent = 'Counts describe retained evidence at each stage. Exact Browse includes alternates. Provider totals remain unknown without complete inventory.';
  const native = document.createElement('details');
  const title = document.createElement('summary'); title.textContent = 'Native discovery and book receipts'; native.append(title);
  const list = document.createElement('ul');
  for (const c of report.native_query_observations) {
    const item = document.createElement('li');
    item.textContent = `${label(c.venue)} · ${c.league} ${label(c.family)}: ${count(c.pages)} pages, ` +
      `${c.continuation ? 'more pages available' : c.exhausted ? 'query exhausted' : 'end unverified'}; ` +
      `${count(c.received)} received, ${count(c.admitted)} accepted as book observations, ` +
      `${count(c.rejected)} rejected, ${count(c.pending)} pending. These are query counts across phases.`;
    list.append(item);
  }
  native.append(list);
  const scroller = document.createElement('div'); scroller.className = 'fee-funnel-table'; scroller.append(table);
  parent.replaceChildren(note, scroller, native);
}

export function mountCoverageFunnel(details) {
  if (!details) return;
  const parent = details.querySelector('[data-coverage-funnel]');
  let pending = false;
  details.addEventListener('toggle', async () => {
    if (!details.open || pending) return;
    pending = true;
    parent.textContent = 'Reading the stored coverage stages…';
    try {
      const response = await fetch('/api/comparison-current/fee-coverage?phase=pregame&funnel=1', {
        cache:'no-store', signal:AbortSignal.timeout(10000)
      });
      if (!response.ok) throw Error('Unavailable');
      const result = (await response.json()).synchronized_funnel;
      if (!result) throw Error('Unavailable');
      renderFunnel(parent, result);
    } catch {
      parent.textContent = 'Stage counts are unavailable. Close and reopen to retry.';
    } finally {
      pending = false;
    }
  });
}

export function feeCensusLines(report) {
  const t = report.total;
  const time = report.read_at ? new Date(report.read_at).toLocaleString() : 'time unavailable';
  const published = report.published_at ? new Date(report.published_at).toLocaleString() : 'Time unavailable';
  const rate = t.posted_fee_coverage_percent != null ? `${t.posted_fee_coverage_percent.toFixed(2)}%` : 'No posted offers';
  return [
    ['Trading fees', `${count(t.posted_fee)} of ${count(t.posted)} posted offers · ${rate}`],
    ['Named sportsbook references', count(t.posted_named_reference)],
    ['Offers with qualified settlement', count(t.posted_settlement_qualified)],
    ...[['Reference gaps', report.posted_reference_missing_reasons],
      ['Settlement gaps', report.posted_settlement_missing_reasons]].flatMap(([label, gaps]) =>
        Object.keys(gaps || {}).length ? [[label, Object.entries(gaps)
          .map(([reason, n]) => `${count(n)} · ${evidenceReason(reason)}`).join(' ')]] : []),
    ['Indicative sportsbook estimates', count(t.sportsbook_ev)],
    ['Modeled returns after fees', count(t.posted_modeled_after_fee)],
    ['Verified after-fee EV', count(t.reviewed_after_fee_ev)],
    ['Scoped scenarios', `${count(t.before_fee_ev)} before fees · ${count(t.conservative_after_fee_ev)} conservative after fees`],
    ['Source prices', `${count(report.published_working_prices)} working prices published · ${count(report.unpublished_working_prices)} working prices unpublished · ${count(t.retained_unavailable)} retained unavailable offers`],
    ['Posted price freshness', `${count(t.fresh_confirmations)} recently confirmed · ${count(t.retained_posted)} retained · ${count(t.source_time_unknown)} without a source time`],
    ['Fee gaps among posted offers', Object.entries(report.posted_fee_missing_reasons || {})
      .map(([reason, n]) => `${count(n)} · ${evidenceReason(reason)}`).join(' ') || 'None observed'],
    ['Latest publication', published],
    ['Local census read', time]
  ];
}

export function mountFeeCensus(root, exportButton) {
  let report = null, pending = false;
  if (exportButton) exportButton.onclick = () => {
    if (!report) return;
    const link = document.createElement('a');
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2) + '\n'], {type:'application/json'}));
    link.href = url;
    link.download = 'predict-fee-coverage.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return async function refresh(isActive = () => true) {
    if (pending) return;
    pending = true;
    try {
      const response = await fetch('/api/comparison-current/fee-coverage?phase=pregame', {
        cache:'no-store', signal:AbortSignal.timeout(5000)
      });
      if (!response.ok) throw Error('Unavailable');
      const next = await response.json();
      if (!isActive()) return;
      if (!next.total) throw Error('Unavailable');
      const facts = document.createElement('dl');
      facts.className = 'fee-census-facts';
      for (const [label, value] of feeCensusLines(next)) {
        const term = document.createElement('dt'), detail = document.createElement('dd');
        term.textContent = label;
        detail.textContent = value;
        facts.append(term, detail);
      }
      root.replaceChildren(facts);
      if (next.coverage_complete === false) {
        const note = document.createElement('p');
        const sources = document.createElement('a');
        sources.href = '/admin?section=sources';
        sources.textContent = 'Check source status';
        note.append('The full provider offer count is unknown. These counts cover the local observations and offers. ', sources, ' to see gaps.');
        root.append(note);
      }
      report = next;
      if (exportButton) exportButton.disabled = false;
    } catch {
      if (!isActive()) return;
      report = null;
      if (exportButton) exportButton.disabled = true;
      root.textContent = 'The local fee census is unavailable.';
    } finally {
      pending = false;
    }
  };
}
