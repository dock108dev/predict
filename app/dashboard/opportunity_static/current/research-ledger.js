import {rational} from './comparison-board.js';

export const ledgerPageSize = 8;
export const resolvedGrade = grade => ['win', 'loss', 'push', 'void'].includes(grade?.state);
export const gradeFilters = [['all', 'All grades'], ['win', 'Wins'], ['loss', 'Losses'],
  ['push', 'Pushes'], ['void', 'Voids'], ['unresolved', 'Unresolved']];
export const tradeSorts = [['ev_desc', 'EV, highest first'], ['ev_asc', 'EV, lowest first'],
  ['stake_desc', 'Stake, highest first'], ['pnl_desc', 'Modeled P/L, highest first']];

function exact(value) {
  if (value == null) return null;
  try { return rational(String(value)); } catch { return null; }
}

function compare(left, right) {
  const difference = left[0] * right[1] - right[0] * left[1];
  return difference < 0n ? -1 : difference > 0n ? 1 : 0;
}

function compareAmount(left, right, direction) {
  if (!left || !right) return Number(!left) - Number(!right);
  return direction * compare(left, right);
}

function gcd(left, right) {
  while (right) [left, right] = [right, left % right];
  return left < 0n ? -left : left;
}

function total(tickets, field) {
  let numerator = 0n, denominator = 1n;
  for (const ticket of tickets) {
    const amount = exact(ticket[field]);
    if (!amount) return null;
    numerator = numerator * amount[1] + amount[0] * denominator;
    denominator *= amount[1];
    const divisor = gcd(numerator, denominator);
    numerator /= divisor;
    denominator /= divisor;
  }
  // Match the stored result formatter by rounding the sum to cents, half away from zero.
  const magnitude = numerator < 0n ? -numerator : numerator;
  const cents = (200n * magnitude + denominator) / (2n * denominator);
  const sign = numerator < 0n && cents ? '-' : '';
  return `${sign}${cents / 100n}.${String(cents % 100n).padStart(2, '0')}`;
}

function subsetSummary(tickets) {
  const resolved = tickets.filter(ticket => resolvedGrade(ticket.grade));
  return {
    tickets: tickets.length,
    resolved: resolved.length,
    stake: tickets.length ? total(tickets, 'stake_exact_usd') : null,
    resolvedStake: resolved.length ? total(resolved, 'stake_exact_usd') : null,
    pnl: resolved.length ? total(resolved, 'pnl_exact_usd') : null,
  };
}

export function ledgerViewModel(tickets, originals, buckets, params) {
  const sort = tradeSorts.some(([value]) => value === params.trade_sort) ? params.trade_sort : 'ev_desc';
  const grade = gradeFilters.some(([value]) => value === params.trade_filter) ? params.trade_filter : 'all';
  const bucket = buckets.find(({minimum}) => minimum === params.trade_ev);
  const minimum = exact(bucket?.minimum), maximum = exact(bucket?.maximum);
  const screening = minimum ? new Map(originals.map(ticket => [ticket.id, exact(ticket.screen_ev)])) : null;
  const filtered = tickets.filter(ticket => {
    if (grade === 'unresolved' && resolvedGrade(ticket.grade)) return false;
    if (grade !== 'all' && grade !== 'unresolved' && grade !== ticket.grade?.state) return false;
    if (!screening) return true;
    const ev = screening.get(ticket.id);
    return ev && compare(ev, minimum) >= 0 && (!maximum || compare(ev, maximum) < 0);
  });
  const sortField = sort === 'stake_desc' ? 'stake_exact_usd' : sort === 'pnl_desc' ? 'pnl_exact_usd' : 'ev';
  const direction = sort === 'ev_asc' ? 1 : -1;
  const ranked = filtered.map(ticket => ({ticket, amount:exact(ticket[sortField])})).sort((left, right) =>
    compareAmount(left.amount, right.amount, direction) ||
    (left.ticket.id < right.ticket.id ? -1 : left.ticket.id > right.ticket.id ? 1 : 0));
  const selectedIndex = ranked.findIndex(({ticket}) => ticket.id === params.trade);
  const selectionPage = selectedIndex < 0 ? null : Math.floor(selectedIndex / ledgerPageSize) + 1;
  const pageCount = Math.max(1, Math.ceil(ranked.length / ledgerPageSize));
  const requestedPage = /^[1-9]\d*$/.test(params.trade_page || '') ? Number(params.trade_page) : null;
  const page = Math.min(pageCount, requestedPage || selectionPage || 1);
  const offset = (page - 1) * ledgerPageSize;
  const rows = ranked.slice(offset, offset + ledgerPageSize).map(({ticket}) => ticket);
  return {
    sort, grade, bucket, page, pageCount, offset, rows, selectionPage,
    total: ranked.length,
    selected: ranked[selectedIndex]?.ticket || rows[0] || null,
    missingSelection: Boolean(params.trade && selectedIndex < 0),
    subset: grade !== 'all' || bucket ? subsetSummary(filtered) : null,
  };
}
