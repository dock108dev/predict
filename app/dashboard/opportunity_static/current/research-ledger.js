import {rational} from './comparison-board.js';

const leagueNames = ['NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL'];
const defaultPageSize = 50;
export const ledgerPageSizes = ['25', '50', '100'];
export const sportFilters = [['all', 'All sports'], ...leagueNames.map(league => [league, league])];
export const familyFilters = [['all', 'All bet types'], ['moneyline', 'Moneyline'], ['spread', 'Spread'], ['total', 'Total']];
export const venueFilters = [['all', 'All venues'], ['kalshi', 'Kalshi'], ['novig', 'Novig'],
  ['polymarket_us', 'Polymarket US'], ['prophetx', 'ProphetX']];
export const resolvedGrade = grade => ['win', 'loss', 'push', 'void'].includes(grade?.state);
export const gradeFilters = [['all', 'All grades'], ['win', 'Wins'], ['loss', 'Losses'],
  ['push', 'Pushes'], ['void', 'Voids'], ['unresolved', 'Unresolved']];
export const tradeSorts = [['ev_desc', 'EV, highest first'], ['ev_asc', 'EV, lowest first'],
  ['stake_desc', 'Stake, highest first'], ['pnl_desc', 'Modeled P/L, highest first']];

const selectedOption = (options, value) => options.some(([option]) => option === value) ? value : options[0][0];
const normalizedVenue = value => ({polymarket:'polymarket_us',prophetexchange:'prophetx'})[value] || value;

export const selectedSport = value => selectedOption(sportFilters, value);

export function gameLeague(game, policy) {
  if (leagueNames.includes(game?.league)) return game.league;
  if (leagueNames.includes(policy?.league)) return policy.league;
  return policy?.scope === 'mens-d1' ? 'NCAAB' : null;
}

export function tradeFilters(params) {
  return {
    sport:selectedSport(params.trade_sport),
    family:selectedOption(familyFilters, params.trade_family),
    venue:selectedOption(venueFilters, normalizedVenue(params.trade_venue)),
    grade:selectedOption(gradeFilters, params.trade_filter),
  };
}

export function matchesTradeFilters(ticket, filters, league = null) {
  return (filters.sport === 'all' || league === filters.sport)
    && (filters.family === 'all' || ticket.family === filters.family)
    && (filters.venue === 'all' || normalizedVenue(ticket.venue) === filters.venue)
    && (filters.grade === 'all' || (filters.grade === 'unresolved' ? !resolvedGrade(ticket.grade) : filters.grade === ticket.grade?.state));
}

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
    pnl: resolved.length ? total(resolved, 'pnl_exact_usd') : null,
  };
}

export function requestedTrade(tickets, params) {
  if (params.trade) return tickets.find(ticket => ticket.id === params.trade);
  return (params.sizing_quote && tickets.find(ticket => ticket.frozen_quote_id === params.sizing_quote))
    || (params.sizing_bet && tickets.find(ticket => ticket.equivalent_bet_id === params.sizing_bet))
    || null;
}

export function ledgerViewModel(tickets, originals, buckets, params, leagueFor = () => null) {
  const sort = selectedOption(tradeSorts, params.trade_sort);
  const filters = tradeFilters(params);
  const pageSize = ledgerPageSizes.includes(String(params.trade_rows)) ? Number(params.trade_rows) : defaultPageSize;
  const bucket = buckets.find(({minimum}) => minimum === params.trade_ev);
  const minimum = exact(bucket?.minimum), maximum = exact(bucket?.maximum);
  const screening = minimum ? new Map(originals.map(ticket => [ticket.id, exact(ticket.screen_ev)])) : null;
  const filtered = tickets.filter(ticket => {
    if (!matchesTradeFilters(ticket, filters, leagueFor(ticket))) return false;
    if (!screening) return true;
    const ev = screening.get(ticket.id);
    return ev && compare(ev, minimum) >= 0 && (!maximum || compare(ev, maximum) < 0);
  });
  const sortField = sort === 'stake_desc' ? 'stake_exact_usd' : sort === 'pnl_desc' ? 'pnl_exact_usd' : 'ev';
  const direction = sort === 'ev_asc' ? 1 : -1;
  const ranked = filtered.map(ticket => ({ticket, amount:exact(ticket[sortField])})).sort((left, right) =>
    compareAmount(left.amount, right.amount, direction) ||
    (left.ticket.id < right.ticket.id ? -1 : left.ticket.id > right.ticket.id ? 1 : 0));
  const requested = requestedTrade(filtered, params);
  const selectedIndex = ranked.findIndex(({ticket}) => ticket.id === requested?.id);
  const selectionPage = selectedIndex < 0 ? null : Math.floor(selectedIndex / pageSize) + 1;
  const pageCount = Math.max(1, Math.ceil(ranked.length / pageSize));
  const requestedPage = /^[1-9]\d{0,8}$/.test(params.trade_page || '') ? Number(params.trade_page) : null;
  const page = Math.min(pageCount, requestedPage || selectionPage || 1);
  const offset = (page - 1) * pageSize;
  const rows = ranked.slice(offset, offset + pageSize).map(({ticket}) => ticket);
  return {
    sort, filters, bucket, pageSize, page, pageCount, offset, rows, selectionPage,
    total: ranked.length,
    selected: ranked[selectedIndex]?.ticket || rows[0] || null,
    missingSelection: Boolean((params.trade || params.sizing_quote || params.sizing_bet) && selectedIndex < 0),
    changedVenue: Boolean(requested && !params.trade && params.sizing_quote && requested.frozen_quote_id !== params.sizing_quote),
    subset: bucket || Object.values(filters).some(value => value !== 'all') ? subsetSummary(filtered) : null,
  };
}
