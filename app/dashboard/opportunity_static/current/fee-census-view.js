import {evidenceReason} from './desk-reasons.js';

const count = n => n == null ? 'Unavailable' : n.toLocaleString();

export function feeCensusLines(report) {
  const t = report.total;
  const time = report.read_at ? new Date(report.read_at).toLocaleString() : 'time unavailable';
  const rate = t.current ? `${t.fee_coverage_percent.toFixed(2)}%` : 'No current offers';
  return [
    ['Trading fees', `${count(t.covered)} of ${count(t.current)} current offers · ${rate}`],
    ['Exact Pinnacle references', count(t.exact_pinnacle_reference)],
    ['EV results', `${count(t.before_fee_ev)} before fees · ${count(t.reviewed_after_fee_ev)} reviewed fees · ${count(t.conservative_after_fee_ev)} conservative · ${count(t.any_after_fee_ev)} with either after-fee result`],
    ['Source prices', `${count(report.published_working_prices)} working prices published · ${count(report.unpublished_working_prices)} working prices unpublished · ${count(t.retained_unavailable)} retained unavailable offers`],
    ['Fee gaps among current offers', Object.entries(report.missing_reasons || {})
      .map(([reason, n]) => `${count(n)} · ${evidenceReason(reason)}`).join(' ') || 'None observed'],
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
      const response = await fetch('/api/comparison-current/fee-coverage', {
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
