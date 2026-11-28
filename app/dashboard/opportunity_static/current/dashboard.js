import {ageNode, updateRelativeAges} from './board-elements.js';
import {payoutExample, quoteFeeAssumption} from './pregame-evidence.js';
import {explanation} from './pregame-explanation.js';
import {bookName} from './pregame-labels.js';
import {coverageRows, liquidityBadge, liquidityDetails} from './pregame-liquidity.js';
import {priceDisplay} from './pregame-prices.js';
import {amountResearch} from './research-tools.js';
import {dateTime, number, percent, readable, selection} from './workspace-format.js';

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
const filterNames = ['sport', 'family', 'venue', 'view'];
const defaultPageSize = '50';
const initialUpdatesDelay = 2000;
const maxUpdatesDelay = 15000;
const updateBatchDelay = 200;
const field = name => filters.elements.namedItem(name);
const pageSize = () => Number(field('rows').value);
let offset = 0;
let snapshot;
let read;
let refreshTimer;
let updates;
let updatesRetryTimer;
let updateBatchTimer;
let updatesDelay = initialUpdatesDelay;
let refreshAfterRead = false;
let closed = false;
let selectedQuote;
let evidenceRead;
let coverageRead;
let serverOffset;
let earliestServerOffset = -Infinity;
let latestRead = -Infinity;
const dashboardClock = Object.assign(new EventTarget(), {
  now() {
    return serverOffset === undefined ? Date.now() : serverOffset + performance.now();
  },
  observe(readAt, requestStarted) {
    const observed = Date.parse(readAt);
    if (!Number.isFinite(observed) || !Number.isFinite(requestStarted) || observed <= latestRead) return false;
    latestRead = observed;
    // The SQL read happened between sending the request and receiving its body.
    // Use the earliest possible read instant to account for time spent in transit.
    const upper = observed - requestStarted;
    const lower = observed - performance.now();
    if (upper < earliestServerOffset) return false;
    earliestServerOffset = Math.max(earliestServerOffset, lower);
    const offset = serverOffset === undefined || lower > serverOffset ? upper : Math.min(upper, serverOffset);
    if (offset === serverOffset) return false;
    serverOffset = offset;
    this.dispatchEvent(new Event('change'));
    return true;
  },
});

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
  updateHeading();
  clear.hidden = !filterNames.some(name => field(name).value);
}

function updateHeading() {
  const labels = {all: 'All venue offers', unavailable: 'Offers with EV unavailable'};
  byId('dashboard-opportunities').textContent = labels[field('view').value] || 'Current +EV opportunities';
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

function venuePrice(row) {
  if (!row.native_source) return row.display.posted_odds || exactPrice(row);
  const price = row.posted?.native_price_probability;
  if (price == null) return 'Unavailable';
  if (row.venue === 'prophetx') return row.display.posted_odds;
  const shown = priceDisplay({...row, posted: {value: price, units: 'probability'}});
  return [shown.primary, shown.secondary].filter(Boolean).join(' ');
}

function bet(row) {
  return selection(row);
}

const quoteKey = row => `${row.pull_id}:${row.id}`;
const current = row => Date.parse(row.eligible_until) > dashboardClock.now();
const ev = row => row.display.net_ev || (row.calculation.net_ev_percent == null ? 'EV unavailable' : percent(row.calculation.net_ev_percent));
const cash = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'});

function visibleQuote(row) {
  if (!row.native_source) return current(row) ? row : null;
  const view = field('view').value;
  const fresh = current(row);
  if (!fresh && view !== 'all') return null;
  const refExpired = Date.parse(row.liquidity?.reference_valid_until) <= dashboardClock.now();
  if (fresh && !refExpired) return row;
  if (!view) return null;
  const liquidity = fresh ? {...row.liquidity, modeled_net_ev: null, reason: 'reference_stale'}
    : unknownLiquidity(row.liquidity, row.book_status === 'unobserved' ? row.liquidity?.reason : 'stale_book');
  const posted = fresh ? row.posted : {...row.posted, value: null, native_price_probability: null};
  const display = {posted_odds: fresh ? row.display.posted_odds : null, fair_odds: null, net_ev: null};
  return {...row, posted, display, liquidity,
    calculation: {...row.calculation, status: 'unavailable', net_ev_ratio: null, net_ev_percent: null}};
}

function quoteAge(row) {
  if (row.native_source && !row.times?.source_at && row.times?.received_at) {
    return ageNode(row.times.received_at, 'Received ', dashboardClock.now());
  }
  return ageNode(row.times?.source_at, '', dashboardClock.now());
}

function unknownLiquidity(liquidity, reason) {
  return {status: 'unknown', reason: reason || 'stale_book', intended_stake_usd: liquidity?.intended_stake_usd,
    book_received_at: liquidity?.book_received_at, published_at: liquidity?.published_at};
}

function availableLiquidity(row) {
  const liquidity = row.liquidity;
  if (liquidity?.valid_until && Date.parse(liquidity.valid_until) <= dashboardClock.now()) {
    return unknownLiquidity(liquidity, 'stale_book');
  }
  return liquidity;
}

function dashboardBadge(row) {
  let liquidity = availableLiquidity(row);
  if (row.native_source && liquidity && row.calculation.status === 'unavailable') {
    liquidity = {...liquidity, modeled_net_ev: null};
  }
  const badge = liquidityBadge({liquidity});
  if (!badge || !row.native_source) return badge;
  const expiresAt = row.liquidity?.valid_until || row.eligible_until;
  const expired = row.book_status === 'stale' ||
    (row.book_status !== 'unobserved' && liquidity.reason === 'stale_book');
  if (expired) {
    badge.dataset.depthStatus = 'unknown';
    badge.replaceChildren('Book expired');
    if (Number.isFinite(Date.parse(expiresAt))) badge.append(node('span', dateTime(expiresAt)));
    return badge;
  }
  if (Date.parse(expiresAt) > dashboardClock.now() && row.book_status !== 'unobserved') {
    const supported = number(liquidity.modeled_stake_usd);
    if (supported > 0 && liquidity.reason !== 'fee_mode_changed' &&
        ['full_size', 'partial_size'].includes(liquidity.size_status || liquidity.status)) {
      badge.append(node('span', `Fresh book · ${cash.format(supported)} supported`));
    } else if (row.book_status === 'fresh' || ['empty', 'confirmed_empty'].includes(liquidity.status)) {
      badge.append(node('span', 'Fresh book'));
    }
  }
  return badge;
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
  const quotes = row.other_quotes || [];
  if (!quotes.length) return '';
  const list = node('ul');
  for (const quote of quotes) {
    const item = node('li');
    const price = venuePrice(quote);
    const label = quote.native_source ? price : `${price} · ${ev(quote)} quote EV`;
    item.append(evidenceButton(quote, bookName(quote.venue)), node('span', label),
      node('small', `Fair ${quote.display.fair_odds || 'odds unavailable'} · `));
    item.lastChild.append(quoteAge(quote));
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
  cell(tr, 'Posted odds', venuePrice(row));
  cell(tr, 'Fair odds', row.display.fair_odds || 'Unavailable');
  const quoted = row.native_source && ev(row) !== 'EV unavailable' ? null
    : node('span', !row.native_source && row.liquidity ? `Quote ${ev(row)}` : ev(row), 'dashboard-quoted-ev');
  if (quoted && (ev(row).startsWith('-') || ev(row) === 'EV unavailable')) quoted.dataset.sign = 'neutral';
  const badge = dashboardBadge(row);
  cell(tr, 'EV', ...[quoted, badge].filter(Boolean));
  cell(tr, 'Quote age', quoteAge(row));
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
  if (evidence.native_offer) {
    const native = evidence.native_offer;
    const book = {liquidity: evidence.liquidity || row.liquidity, liquidity_evidence: evidence.liquidity_evidence};
    const size = amountResearch('dashboard', {...row, ...book}, (output, modeled) => {
      const details = liquidityDetails(modeled);
      const price = modeled.preview_offer ? facts([['Venue price used for preview', venuePrice(modeled.preview_offer)]]) : null;
      output.replaceChildren(...[price, details].filter(Boolean));
    }, {signal, savedLiquidity: native.row?.liquidity, clock: dashboardClock});
    const sources = facts([
      ['Saved venue price', venuePrice(native.row || row)],
      ['Venue event', native.book.event_id],
      ['Native market', native.book.market_id], ['Native outcome', native.book.outcome_id],
      ['Native side', native.book.native_side], ['Source timestamp', native.book.source_at],
      ['Book received', native.book.received_at], ['Book expires', native.book.valid_until],
      ['Calculation time', native.calculated_at], ['Shared game', native.game_link.canonical_game_id],
      ['Game match', native.game_link.method || native.game_link.reason],
      ['SportsGameOdds event', native.game_link.sgo_event_id],
      ...(native.fee_mode?.enabled === false ? [['Modeled fees', 'Disabled in saved calculation']] : []),
    ]);
    const reference = node('section');
    const prices = node('ul');
    for (const price of native.reference?.prices || []) {
      const side = readable(price.side) + (price.side === native.reference.selected_outcome ? ' (this bet)' : '');
      prices.append(node('li', `${side} · ${price.price_american} · ${dateTime(price.source_at)}`));
    }
    reference.append(node('h3', 'Reference prices'));
    if (prices.childElementCount) {
      const fair = native.reference.fair_odds ? ` · Fair odds ${native.reference.fair_odds}` : '';
      reference.append(node('p', `${bookName(native.reference.book)}${fair}`), prices);
    } else {
      reference.append(node('p', 'Exact sportsbook reference unavailable.'));
    }
    const exact = node('details');
    exact.append(node('summary', 'Native book, fees, game match and SGO audit'), node('pre', JSON.stringify(native, null, 2)));
    const actions = node('div', undefined, 'dashboard-evidence-actions');
    actions.append(link('Export saved evidence', '/api/research/market-export?' + query));
    content.replaceChildren(node('p', `${row.game} · ${dateTime(row.kickoff)}`), size, sources, reference, actions, exact);
    return;
  }
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
    ['Net EV', row.display.net_ev == null ? null : `${row.display.net_ev} · ${quoteFeeAssumption(stored)}`],
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

  const book = {liquidity: evidence.liquidity || row.liquidity,
    liquidity_evidence: evidence.liquidity_evidence};
  const size = book.liquidity ? amountResearch('dashboard', {...row, ...book}, (output, modeled) => {
    const currentBook = liquidityDetails(modeled);
    output.replaceChildren(...[currentBook].filter(Boolean));
  }, {signal, clock: dashboardClock}) : null;

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
    const requestStarted = performance.now();
    const evidence = await get('/api/research/market', params, signal);
    if (evidenceRead === controller && inspector.open) {
      dashboardClock.observe(evidence.read_at, requestStarted);
      renderEvidence(row, evidence, query, controller.signal);
    }
  } catch {
    if (evidenceRead !== controller || !inspector.open) return;
    progress.textContent = 'The exact saved quote could not be loaded.';
    const retry = node('button', 'Retry evidence');
    retry.type = 'button';
    retry.onclick = () => inspect(row);
    content.replaceChildren(progress, retry);
    if (!row.native_source) content.append(link('Open original odds pull in Data', '/data?' + new URLSearchParams({evidence: 'pulls', pull: row.pull_id})));
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
  if (packet.source_authority === 'official_venue_apis' && field('view').value) {
    if (hasRows) return '';
    return field('view').value === 'unavailable' ? 'No fresh venue prices with EV unavailable match these filters.'
      : 'No stored venue offers match these filters.';
  }
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
  const currentRows = packet.rows.flatMap(group => {
    const quotes = [group, ...(group.other_quotes || [])].map(visibleQuote).filter(Boolean);
    if (!quotes.length) return [];
    const [first, ...other_quotes] = quotes.sort((a, b) => Number(current(b)) - Number(current(a)));
    return [{...first, other_quotes}];
  });
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
  const now = dashboardClock.now();
  const deadline = Math.min(...(snapshot?.rows || []).flatMap(row => [row, ...(row.other_quotes || [])])
    .flatMap(row => [row.eligible_until, row.liquidity?.valid_until, row.liquidity?.reference_valid_until])
    .map(Date.parse).filter(at => at > now));
  const delay = Math.min(30000, Math.ceil(deadline - now));
  refreshTimer = setTimeout(() => {
    if (deadline <= dashboardClock.now() && snapshot) render(snapshot);
    requestRefresh();
  }, delay);
}

function requestRefresh() {
  if (closed || document.hidden) return;
  if (read) refreshAfterRead = true;
  else refresh();
}

function cancelUpdateBatch() {
  clearTimeout(updateBatchTimer);
  updateBatchTimer = undefined;
}

function stopUpdates() {
  clearTimeout(updatesRetryTimer);
  cancelUpdateBatch();
  updatesDelay = initialUpdatesDelay;
  updates?.close();
  updates = undefined;
  refreshAfterRead = false;
}

function watchUpdates() {
  stopUpdates();
  connectUpdates();
}

function connectUpdates() {
  if (closed || document.hidden || typeof EventSource === 'undefined') return;
  const query = new URLSearchParams();
  for (const name of ['sport', 'family', 'venue']) if (field(name).value) query.set(name, field(name).value);
  const stream = new EventSource('/api/research/dashboard-updates?' + query);
  updates = stream;
  stream.onmessage = () => {
    if (updates !== stream) return;
    updatesDelay = initialUpdatesDelay;
    // Start a fixed window so sustained notices cannot postpone the next read.
    if (updateBatchTimer === undefined) updateBatchTimer = setTimeout(requestRefresh, updateBatchDelay);
  };
  stream.onerror = () => {
    if (updates !== stream) return;
    // HTTP errors can close EventSource permanently. Own one retry path also for network errors.
    stream.close();
    updates = undefined;
    if (closed || document.hidden) return;
    updatesRetryTimer = setTimeout(connectUpdates, updatesDelay);
    updatesDelay = Math.min(updatesDelay * 2, maxUpdatesDelay);
  };
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
  for (const name of ['sport', 'family', 'venue']) if (field(name).value) query[name] = field(name).value;
  coverageContent.replaceChildren(node('p', 'Reading stored coverage…'));
  try {
    const packet = await get('/api/research/dashboard-coverage', query, AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]));
    if (coverageRead !== controller || !coverage.open) return;
    const gaps = Object.entries(packet.access || {}).flatMap(([venue, state]) => {
      const name = bookName(venue);
      return [state.collection, state.reason].filter(Boolean).map(reason => `${name} · ${readable(reason)}`)
        .concat(Object.entries(state.leagues || {}).map(([league, reason]) => `${name} · ${league} · ${readable(reason)}`));
    });
    const issues = gaps.map(gap => node('p', gap));
    coverageContent.replaceChildren(...issues, packet.coverage?.length
      ? coverageRows(packet.coverage, bookName, packet.liquidity_stake_usd)
      : node('p', 'No stored pregame offers for these filters.'));
  } catch {
    if (coverageRead === controller && coverage.open) coverageContent.replaceChildren(node('p', 'Coverage could not be read. Refresh coverage to retry.'));
  }
}

async function refresh() {
  cancelUpdateBatch();
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
    let requestStarted = performance.now();
    let packet = await get('/api/research/dashboard', params, signal);
    if (read !== controller || closed) return;
    if (offset && offset >= packet.total) {
      offset = 0;
      writeLocation(true);
      requestStarted = performance.now();
      packet = await get('/api/research/dashboard', {...params, offset}, signal);
    }
    if (read !== controller || closed) return;
    snapshot = packet;
    if (!dashboardClock.observe(packet.read_at, requestStarted)) render(packet);
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
      if (refreshAfterRead && !document.hidden) {
        refreshAfterRead = false;
        refresh();
      } else schedule();
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
  updateHeading();
  clear.hidden = !filterNames.some(name => field(name).value);
  watchUpdates();
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
const ageTimer = setInterval(() => updateRelativeAges(rows, dashboardClock.now()), 1000);
dashboardClock.addEventListener('change', () => {
  if (snapshot) render(snapshot);
  schedule();
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    stopUpdates();
    clearTimeout(refreshTimer);
  }
  else if (!closed) {
    if (snapshot) render(snapshot);
    watchUpdates();
    refresh();
  }
});
window.addEventListener('pagehide', event => {
  stopUpdates();
  if (event.persisted) return;
  closed = true;
  read?.abort();
  evidenceRead?.abort();
  coverageRead?.abort();
  clearTimeout(refreshTimer);
  clearInterval(ageTimer);
});
window.addEventListener('pageshow', event => {
  if (event.persisted) {
    if (snapshot) render(snapshot);
    watchUpdates();
    refresh();
  }
});
readLocation();
if (location.hash === '#diagnostics') byId('diagnostics').open = true;
watchUpdates();
refresh();
