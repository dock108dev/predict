import {evidenceReason} from './desk-reasons.js';

const count = n => n == null ? 'Unavailable' : n.toLocaleString();

export function feeCensusLines(report) {
  const t = report.total;
  const time = report.read_at ? new Date(report.read_at).toLocaleString() : 'time unavailable';
  const published = report.published_at ? new Date(report.published_at).toLocaleString() : 'Time unavailable';
  const rate = t.posted_fee_coverage_percent != null ? `${t.posted_fee_coverage_percent.toFixed(2)}%` : 'No posted offers';
  return [
    ['Trading fees', `${count(t.posted_fee)} of ${count(t.posted)} posted offers · ${rate}`],
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
