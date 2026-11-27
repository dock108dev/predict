import {ageNode, updateRelativeAges} from './board-elements.js';
import {payoutExample} from './pregame-evidence.js';
import {explanation} from './pregame-explanation.js';
import {bookName} from './pregame-labels.js';
import {coverageRows, liquidityBadge, liquidityDetails} from './pregame-liquidity.js';
import {amountResearch} from './research-tools.js';
import {dateTime, percent, readable, selection} from './workspace-format.js';

const byId = id => document.getElementById(id);
const rows = byId('dashboard-rows');
const status = byId('dashboard-status');
const reload = byId('dashboard-reload');
const previous = byId('dashboard-previous');
const next = byId('dashboard-next');
const filters = byId('dashboard-filters');
const clear = byId('dashboard-clear');
const inspector = byId('dashboard-inspector');
const content = byId('dashboard-inspector-content');
const coverage = byId('dashboard-liquidity-coverage');
const coverageContent = byId('dashboard-liquidity-content');
const filterNames = ['sport', 'family', 'venue'];
const defaultPageSize = '50';
const field = name => filters.elements.namedItem(name);
const pageSize = () => Number(field('rows').value);
let offset = 0;
let snapshot;
let read;
let refreshTimer;
let closed = false;
let selectedQuote;
let evidenceRead;
let coverageRead;

function readLocation() {
  const query = new URLSearchParams(location.search);
  for (const name of [...filterNames, 'rows']) {
    const control = field(name);
    const value = query.get('board_' + name);
    control.value = [...control.options].some(option => option.value === value)
      ? value : name === 'rows' ? defaultPageSize : '';
  }
  const savedOffset = Number(query.get('board_offset'));
  offset = Number.isInteger(savedOffset) && savedOffset > 0 && savedOffset <= 2147483647 ? savedOffset : 0;
  clear.hidden = !filterNames.some(name => field(name).value);
}

function writeLocation(replace = false) {
  const url = new URL(location.href);
  for (const [name, value] of [...filterNames.map(name => [name, field(name).value]),
    ['rows', field('rows').value === defaultPageSize ? '' : field('rows').value], ['offset', offset]]) {
    if (value) url.searchParams.set('board_' + name, value);
    else url.searchParams.delete('board_' + name);
  }
  if (url.href !== location.href) history[replace ? 'replaceState' : 'pushState'](null, '', url);
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function cell(tr, heading, ...values) {
  const td = node('td');
  td.dataset.label = heading;
  td.setAttribute('role', 'cell');
  td.append(...values);
  tr.append(td);
}

function exactPrice(row) {
  const posted = row.posted || {};
  return posted.value == null ? 'Not recorded' : `${posted.value} ${readable(posted.units)}`;
}

function bet(row) {
  return selection(row);
}

const quoteKey = row => `${row.pull_id}:${row.id}`;
const current = row => Date.parse(row.eligible_until) > Date.now();
const ev = row => row.display.net_ev || percent(row.calculation.net_ev_percent);

function availableLiquidity(row) {
  const liquidity = row.liquidity;
  if (liquidity?.valid_until && Date.parse(liquidity.valid_until) <= Date.now()) {
    return {status: 'unknown', reason: 'stale_book', intended_stake_usd: liquidity.intended_stake_usd,
      book_received_at: liquidity.book_received_at, published_at: liquidity.published_at};
  }
  return liquidity;
}

function dashboardBadge(row) {
  return liquidityBadge({liquidity: availableLiquidity(row)});
}

function evidenceButton(row, label) {
  const button = node('button', label, 'dashboard-bet');
  button.type = 'button';
  button.dataset.quote = quoteKey(row);
  button.setAttribute('aria-haspopup', 'dialog');
  button.setAttribute('aria-label', `${bet(row)} · ${row.game} · ${bookName(row.venue)} · View evidence`);
  button.onclick = () => inspect(row);
  return button;
}

function otherVenues(row, expanded) {
  const quotes = (row.other_quotes || []).filter(current);
  if (!quotes.length) return '';
  const list = node('ul');
  for (const quote of quotes) {
    const item = node('li');
    const price = quote.display.posted_odds || exactPrice(quote);
    item.append(evidenceButton(quote, bookName(quote.venue)), node('span', `${price} · ${ev(quote)} quote EV`),
      node('small', `Fair ${quote.display.fair_odds || 'odds unavailable'} · `));
    item.lastChild.append(ageNode(quote.times?.source_at));
    const badge = dashboardBadge(quote);
    if (badge) item.append(badge);
    list.append(item);
  }
  const details = node('details', undefined, 'dashboard-other-venues');
  details.open = expanded;
  details.append(node('summary', `${quotes.length} other ${quotes.length === 1 ? 'quote' : 'quotes'}`), list);
  return details;
}

function offerRow(row, expanded) {
  const tr = node('tr');
  tr.dataset.bet = row.bet_id || row.id;
  tr.setAttribute('role', 'row');
  tr.onclick = event => {
    if (!event.target.closest('button,a,details')) inspect(row);
  };
  cell(tr, 'Game', node('strong', row.game), node('small', `${row.league} · ${dateTime(row.kickoff)}`));
  const period = row.period && row.period !== 'full_game' ? ` · ${readable(row.period)}` : '';
  const line = row.line_role === 'alternate' ? ' · Alternate' : '';
  cell(tr, 'Bet', evidenceButton(row, bet(row)), node('small', readable(row.family) + period + line));
  cell(tr, 'Best venue', node('strong', bookName(row.venue)), otherVenues(row, expanded));
  cell(tr, 'Posted odds', row.display.posted_odds || exactPrice(row));
  cell(tr, 'Fair odds', row.display.fair_odds || 'Unavailable');
  const quoted = node('span', row.liquidity ? `Quote ${ev(row)}` : ev(row), 'dashboard-quoted-ev');
  if (ev(row).startsWith('-')) quoted.dataset.sign = 'negative';
  const badge = dashboardBadge(row);
  cell(tr, 'EV', ...[quoted, badge].filter(Boolean));
  cell(tr, 'Quote age', ageNode(row.times?.source_at));
  return tr;
}

function facts(entries) {
  const dl = node('dl', undefined, 'dashboard-facts');
  for (const [key, value] of entries) dl.append(node('dt', key), node('dd', value ?? 'Not recorded'));
  return dl;
}

function mathSection(row, kind) {
  const [heading, ...lines] = explanation(row, kind);
  const detail = node('details');
  detail.append(node('summary', heading), ...lines.map(line => node('p', line)));
  return detail;
}

function link(text, href) {
  const a = node('a', text);
  a.href = href;
  return a;
}

function renderEvidence(row, evidence, query, signal) {
  const offer = evidence.selected_offer;
  const stored = offer?.calculation_payload;
  if (!stored || !['positive', 'negative', 'zero'].includes(offer.calculation?.status)) {
    throw Error('Exact calculation evidence unavailable.');
  }
  const quote = node('section');
  quote.append(node('h3', 'Exact quote'), facts([
    ['Posted odds', row.display.posted_odds],
    ['Original source value', exactPrice(row)],
    ['Fair odds', row.display.fair_odds],
    ['Net EV', row.display.net_ev],
    ['Source', stored.source?.provider === 'sportsgameodds' ? 'SportsGameOdds' : bookName(stored.source?.provider)],
    ['Source timestamp', row.times?.source_at],
    ['Received', row.times?.received_at],
    ['Calculated', stored.calculated_at],
    ['Period', readable(offer.period || row.period)],
    ['Settlement rules', offer.normalized_record?.market_identity?.rules],
    ['Fee assumption', stored.fee_mode?.enabled === false ? '$0 modeled fees · fees disabled when calculated' : readable(stored.fee?.classification)],
  ]));

  const reference = node('section');
  const used = stored.reference;
  reference.append(node('h3', 'Reference prices'), node('p', `${bookName(used.book)} sets the fair odds for the exact line.`));
  const prices = node('ul');
  for (const price of used.prices || []) {
    const side = readable(price.side) + (price.side === used.selected_outcome ? ' (this bet)' : '');
    prices.append(node('li', `${side} · ${price.price_american} · ${dateTime(price.source_at)}`));
  }
  reference.append(prices, mathSection(stored, 'fair'));

  const calculation = node('section');
  calculation.append(node('h3', 'Calculation evidence'), node('p', 'EV is expected net profit divided by committed cash. This estimate uses the stored no-vig probability and models win and loss cashflows.'), mathSection(stored, 'ev'), mathSection(stored, 'after'));
  const exact = node('details');
  exact.append(node('summary', 'Exact inputs, cashflows and calculation record'), node('pre', JSON.stringify(evidence.selected_offer, null, 2)));
  const actions = node('div', undefined, 'dashboard-evidence-actions');
  actions.append(link('Open original odds pull in Data', '/data?' + new URLSearchParams({evidence: 'pulls', pull: row.pull_id, sport: row.league, family: row.family})),
    link('Export this calculation', '/api/research/market-export?' + query));

  const book = {liquidity: availableLiquidity({...row, liquidity: evidence.liquidity || row.liquidity}),
    liquidity_evidence: evidence.liquidity_evidence};
  const size = book.liquidity ? amountResearch('dashboard', {...row, ...book}, (output, modeled) => {
    const currentBook = liquidityDetails(modeled);
    output.replaceChildren(...[currentBook].filter(Boolean));
  }, {signal}) : null;

  content.replaceChildren(...[node('p', `${row.game} · ${dateTime(row.kickoff)}`),
    node('p', 'Snapshot from the Dashboard read. The original source time is shown below.', 'research-muted'),
    size, quote, reference, payoutExample(stored), calculation, actions, exact].filter(Boolean));
}

async function inspect(row) {
  selectedQuote = quoteKey(row);
  byId('dashboard-inspector-title').textContent = `${bet(row)} · ${bookName(row.venue)}`;
  const progress = node('p', 'Reading this exact saved quote…');
  progress.setAttribute('role', 'status');
  content.replaceChildren(progress);
  if (!inspector.open) inspector.showModal();
  inspector.scrollTop = 0;
  evidenceRead?.abort();
  const controller = new AbortController();
  evidenceRead = controller;
  const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]);
  const query = new URLSearchParams({market_id: row.market_id, pull_id: row.pull_id, offer_id: row.id, revision: row.revision});
  try {
    const params = new URLSearchParams(query);
    params.set('liquidity', '1');
    const evidence = await get('/api/research/market', params, signal);
    if (evidenceRead === controller && inspector.open) renderEvidence(row, evidence, query, controller.signal);
  } catch {
    if (evidenceRead !== controller || !inspector.open) return;
    progress.textContent = 'The exact saved quote could not be loaded.';
    const retry = node('button', 'Retry evidence');
    retry.type = 'button';
    retry.onclick = () => inspect(row);
    content.replaceChildren(progress, retry, link('Open original odds pull in Data', '/data?' + new URLSearchParams({evidence: 'pulls', pull: row.pull_id})));
  }
}

function rowButton(key) {
  return [...rows.querySelectorAll('button[data-quote]')].find(button => button.dataset.quote === key);
}

inspector.addEventListener('close', () => {
  evidenceRead?.abort();
  evidenceRead = undefined;
  (rowButton(selectedQuote) || reload).focus({preventScroll: true});
  selectedQuote = undefined;
});

function dashboardState(packet, hasRows, expiring) {
  const state = packet.availability || {};
  if (expiring) return 'Quotes expired. Reading saved prices…';
  if (hasRows) {
    if (state.pull_incomplete) return 'Some odds pulls are incomplete.';
    if (state.expired_positive) return 'Stale or withdrawn quotes are excluded.';
    if (state.inputs_unavailable) return 'Some bets are missing prices or reference odds.';
    return '';
  }
  if (state.expired_positive) return 'No current +EV opportunities. Earlier estimates have stale or withdrawn inputs.';
  if (state.pull_incomplete) return 'No current +EV opportunities. Some odds pulls are incomplete.';
  if (state.inputs_unavailable) return 'Some calculations are unavailable. Stored prices or references did not pass the current evidence checks.';
  if (filterNames.some(name => field(name).value)) return 'No opportunities match these filters.';
  if (!state.price_available) return 'No current quotes are available in the collection window.';
  return 'No current +EV opportunities in the evaluated prices.';
}

function render(packet) {
  const currentRows = packet.rows.filter(current);
  const focused = document.activeElement;
  const focusedBet = focused?.closest('[data-bet]')?.dataset.bet;
  const expanded = new Set([...rows.querySelectorAll('details[open]')].map(details => details.closest('tr').dataset.bet));
  rows.replaceChildren(...currentRows.map(row => offerRow(row, expanded.has(row.bet_id || row.id))));
  byId('dashboard-table').hidden = currentRows.length === 0;
  if (focusedBet) {
    const refreshed = [...rows.children].find(row => row.dataset.bet === focusedBet);
    const control = focused.dataset.quote ? rowButton(focused.dataset.quote) : refreshed?.querySelector('summary');
    (control || refreshed?.querySelector('button') || reload).focus({preventScroll: true});
  }
  const expiring = currentRows.length !== packet.rows.length;
  status.textContent = dashboardState(packet, currentRows.length, expiring);
  byId('dashboard-pages').hidden = expiring || !currentRows.length;
  previous.hidden = next.hidden = packet.total <= pageSize();
  byId('dashboard-page').textContent = `${packet.offset + 1}–${packet.offset + packet.rows.length} of ${packet.total} bets`;
  previous.disabled = Boolean(read) || offset === 0;
  next.disabled = Boolean(read) || offset + pageSize() >= packet.total;
}

function schedule() {
  clearTimeout(refreshTimer);
  if (closed || document.hidden) return;
  const now = Date.now();
  const deadline = Math.min(...(snapshot?.rows || []).flatMap(row => [row, ...(row.other_quotes || [])])
    .flatMap(row => [row.eligible_until, row.liquidity?.valid_until]).map(Date.parse).filter(at => at > now));
  const delay = deadline > now ? Math.min(30000, deadline - now) : 30000;
  refreshTimer = setTimeout(() => {
    if (deadline <= Date.now()) {
      if (snapshot) render(snapshot);
      if (!read) refresh();
    } else refresh();
  }, delay);
}

async function get(path, params, signal) {
  const response = await fetch(path + '?' + new URLSearchParams(params), {cache: 'no-store', signal});
  if (!response.ok) throw Error('Stored prices unavailable');
  return response.json();
}

async function refreshCoverage() {
  coverageRead?.abort();
  const controller = new AbortController();
  coverageRead = controller;
  const query = {};
  for (const name of filterNames) if (field(name).value) query[name] = field(name).value;
  coverageContent.replaceChildren(node('p', 'Reading stored coverage…'));
  try {
    const packet = await get('/api/research/dashboard-coverage', query, AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]));
    if (coverageRead !== controller || !coverage.open) return;
    coverageContent.replaceChildren(packet.coverage?.length ? coverageRows(packet.coverage, bookName)
      : node('p', 'No stored pregame offers for these filters.'));
  } catch {
    if (coverageRead === controller && coverage.open) coverageContent.replaceChildren(node('p', 'Coverage could not be read. Refresh coverage to retry.'));
  }
}

async function refresh() {
  read?.abort();
  const controller = new AbortController();
  read = controller;
  const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]);
  reload.disabled = true;
  previous.disabled = next.disabled = true;
  if (!snapshot) status.textContent = 'Reading stored calculations…';
  try {
    const params = {limit: pageSize(), offset};
    for (const name of filterNames) if (field(name).value) params[name] = field(name).value;
    let packet = await get('/api/research/dashboard', params, signal);
    if (read !== controller || closed) return;
    if (offset && offset >= packet.total) {
      offset = 0;
      writeLocation(true);
      packet = await get('/api/research/dashboard', {...params, offset}, signal);
    }
    if (read !== controller || closed) return;
    snapshot = packet;
    render(packet);
  } catch {
    if (read !== controller || closed) return;
    snapshot = undefined;
    rows.replaceChildren();
    byId('dashboard-table').hidden = true;
    byId('dashboard-pages').hidden = true;
    status.textContent = 'Current opportunities are unavailable. Reload saved prices to try again.';
  } finally {
    if (read === controller && !closed) {
      read = undefined;
      reload.disabled = false;
      previous.disabled = !snapshot || offset === 0;
      next.disabled = !snapshot || offset + pageSize() >= snapshot.total;
      schedule();
    }
  }
}

reload.onclick = () => refresh();
previous.onclick = () => { offset = Math.max(0, offset - pageSize()); writeLocation(); refresh(); };
next.onclick = () => { offset += pageSize(); writeLocation(); refresh(); };
function refreshSelection() {
  snapshot = undefined;
  rows.replaceChildren();
  byId('dashboard-table').hidden = byId('dashboard-pages').hidden = true;
  clear.hidden = !filterNames.some(name => field(name).value);
  refresh();
  if (coverage.open) refreshCoverage();
}
coverage.addEventListener('toggle', () => {
  if (coverage.open) refreshCoverage();
  else { coverageRead?.abort(); coverageRead = undefined; }
});
byId('dashboard-liquidity-refresh').onclick = refreshCoverage;
filters.addEventListener('submit', event => event.preventDefault());
filters.addEventListener('change', () => {
  offset = 0;
  writeLocation();
  refreshSelection();
});
clear.onclick = () => {
  for (const name of filterNames) field(name).value = '';
  offset = 0;
  writeLocation();
  field('sport').focus({preventScroll: true});
  refreshSelection();
};
window.addEventListener('popstate', () => { readLocation(); refreshSelection(); });
const ageTimer = setInterval(() => updateRelativeAges(rows), 1000);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) clearTimeout(refreshTimer);
  else if (!closed) {
    if (snapshot?.rows.some(row => !current(row) || row.other_quotes?.some(quote => !current(quote)))) render(snapshot);
    refresh();
  }
});
window.addEventListener('pagehide', event => {
  if (event.persisted) return;
  closed = true;
  read?.abort();
  evidenceRead?.abort();
  coverageRead?.abort();
  clearTimeout(refreshTimer);
  clearInterval(ageTimer);
});
window.addEventListener('pageshow', event => {
  if (event.persisted) refresh();
});
readLocation();
if (location.hash === '#diagnostics') byId('diagnostics').open = true;
refresh();
