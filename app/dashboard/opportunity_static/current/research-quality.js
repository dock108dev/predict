import {count, node, pct, table, usd} from './workspace-ui.js';

const ageBands = {
  up_to_60:'0–60 seconds', over_60_to_300:'Over 60 through 300 seconds', over_300:'Over 300 seconds',
  unknown:'Unknown timestamp', future:'Source timestamp after receipt',
};
const origins = {frozen:'Frozen T−10 only', reconstructed:'Retrospective reconstruction only'};
const headers = ['Tickets', 'Staked', 'Expected profit', 'Graded P/L', 'ROI on graded stake', 'Unresolved tickets'];
const money = value => value == null ? '—' : usd(value);
const row = summary => [count(summary.tickets), money(summary.stake_usd), money(summary.expected_profit_usd),
  money(summary.pnl_usd), summary.roi == null ? '—' : pct(summary.roi), count(summary.unresolved)];

function slices(title, group, names) {
  const entries = Object.entries(names).filter(([key]) => group?.[key]);
  if (entries.length) return table([title, ...headers], entries.map(([key,name]) => [name, ...row(group[key].summary || group[key])]));
  return node('p', 'No measured rows for this view.');
}

export function qualityComparison(quality) {
  if (!quality) return null;
  const panel = node('details', undefined, 'workspace-panel workspace-card paper-quality');
  panel.append(node('summary', 'Capture provenance and quote freshness'),
    node('h3', 'Capture provenance'), slices('Evidence origin', quality.provenance, origins),
    node('h3', 'Target quote ages in the saved portfolio'), node('p', quality.target_age_clock),
    slices('Target quote age', quality.target_quote_age, ageBands),
    node('h3', 'Reference quote ages in the saved portfolio'),
    node('p', quality.reference_age_clock || 'Uses the oldest required reference input when all reference quote clocks are recorded.'),
    slices('Reference quote age', quality.reference_quote_age, ageBands));
  const fresh = quality.fresh_target_only;
  if (fresh?.summary) {
    const boundary = quality.target_age_boundary_seconds;
    panel.append(node('h3', `Exploratory target-age screen · ≤${boundary} seconds`),
      node('p', `Eligible target quotes were between 0 and ${boundary} seconds old at receipt, inclusive. Unknown and future clocks are excluded. This screen filters the candidate pool before reselecting the best qualifying venue. The saved portfolio remains the result of the original experiment rules.`),
      table(['Analysis', ...headers], [['Exploratory screen', ...row(fresh.summary)]]));
    if (fresh.thresholds?.length) panel.append(table(['Minimum EV after target-age screen', ...headers],
      fresh.thresholds.map(item => [`≥${pct(item.minimum)}`, ...row(item.summary)])));
  }
  if (quality.version) panel.append(node('p', `Analysis version ${quality.version}`, 'workspace-caption'));
  return panel;
}
