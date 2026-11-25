import {ageNode, updateRelativeAges} from './board-elements.js';
import {payoutExample} from './pregame-evidence.js';
import {explanation} from './pregame-explanation.js';
import {bookName} from './pregame-labels.js';
import {dateTime, percent, readable, selection} from './workspace-format.js';

const byId = id => document.getElementById(id);
const rows = byId('dashboard-rows');
const status = byId('dashboard-status');
const notice = byId('dashboard-notice');
const reload = byId('dashboard-reload');
const previous = byId('dashboard-previous');
const next = byId('dashboard-next');
const inspector = byId('dashboard-inspector');
const content = byId('dashboard-inspector-content');
const pageSize = 30;
let offset = 0;
let snapshot;
let read;
let refreshTimer;
let closed = false;
let selectedId;
let evidenceRead;

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

function offerRow(row) {
  const tr = node('tr');
  tr.dataset.quote = row.id;
  tr.setAttribute('role', 'row');
  const button = node('button', bet(row), 'dashboard-bet');
  button.type = 'button';
  button.setAttribute('aria-haspopup', 'dialog');
  button.setAttribute('aria-label', `${bet(row)} · ${row.game} · ${bookName(row.venue)} · View evidence`);
  button.onclick = () => inspect(row);
  tr.onclick = event => {
    if (!event.target.closest('button,a')) inspect(row);
  };
  cell(tr, 'Game', node('strong', row.game), node('small', `${row.league} · ${dateTime(row.kickoff)}`));
  cell(tr, 'Bet', button, node('small', readable(row.family)));
  cell(tr, 'Venue', bookName(row.venue));
  cell(tr, 'Posted odds', row.display.posted_odds || exactPrice(row));
  cell(tr, 'Fair odds', row.display.fair_odds || 'Unavailable');
  cell(tr, 'EV', row.display.net_ev || percent(row.calculation.net_ev_percent));
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

function renderEvidence(row, evidence, query) {
  const stored = evidence.selected_offer?.calculation_payload;
  if (!stored || evidence.selected_offer.calculation?.status !== 'positive') {
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

  content.replaceChildren(node('p', `${row.game} · ${dateTime(row.kickoff)}`), node('p', 'Snapshot from the Dashboard read. The original source time is shown below.', 'research-muted'),
    quote, reference, payoutExample(stored), calculation, actions, exact);
}

async function inspect(row) {
  selectedId = row.id;
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
    const evidence = await get('/api/research/market', query, signal);
    if (evidenceRead === controller && inspector.open) renderEvidence(row, evidence, query);
  } catch {
    if (evidenceRead !== controller || !inspector.open) return;
    progress.textContent = 'The exact saved quote could not be loaded.';
    const retry = node('button', 'Retry evidence');
    retry.type = 'button';
    retry.onclick = () => inspect(row);
    content.replaceChildren(progress, retry, link('Open original odds pull in Data', '/data?' + new URLSearchParams({evidence: 'pulls', pull: row.pull_id})));
  }
}

function rowButton(id) {
  return [...rows.querySelectorAll('tr')].find(row => row.dataset.quote === id)?.querySelector('button');
}

inspector.addEventListener('close', () => {
  evidenceRead?.abort();
  evidenceRead = undefined;
  (rowButton(selectedId) || reload).focus({preventScroll: true});
  selectedId = undefined;
});

function dashboardState(packet) {
  const state = packet.availability || {};
  if (state.expired_positive) return 'No current +EV opportunities. Earlier estimates have stale or withdrawn inputs.';
  if (state.inputs_unavailable) return 'Some calculations are unavailable. Stored prices or references did not pass the current evidence checks.';
  if (!state.price_available) return 'No current quotes are available in the collection window.';
  return 'No current +EV opportunities in the evaluated prices.';
}

function render(packet) {
  const currentRows = packet.rows.filter(row => Date.parse(row.eligible_until) > Date.now());
  const focused = document.activeElement?.closest('[data-quote]')?.dataset.quote;
  rows.replaceChildren(...currentRows.map(offerRow));
  byId('dashboard-table').hidden = currentRows.length === 0;
  if (focused) (rowButton(focused) || reload).focus({preventScroll: true});

  const expiring = currentRows.length !== packet.rows.length;
  const label = currentRows.length === 1 ? 'opportunity' : 'opportunities';
  status.textContent = currentRows.length
    ? `${currentRows.length} current ${label} on this page · highest EV first`
    : expiring ? 'Quotes expired. Reading saved prices…' : dashboardState(packet);
  const stale = packet.availability?.expired_positive;
  const unavailable = packet.availability?.inputs_unavailable;
  const notes = [];
  if (currentRows.length && stale) notes.push('Older estimates with expired or withdrawn inputs are excluded.');
  if ((currentRows.length || stale) && unavailable) notes.push('Some markets have missing or incomplete calculations.');
  if (currentRows.length && expiring) notes.push('An expired quote was removed while the board updates.');
  notice.hidden = !notes.length;
  notice.textContent = notes.join(' ');

  byId('dashboard-pages').hidden = packet.total <= pageSize;
  byId('dashboard-page').textContent = `${packet.offset + 1}–${packet.offset + packet.rows.length} of ${packet.total}`;
  previous.disabled = Boolean(read) || offset === 0;
  next.disabled = Boolean(read) || offset + pageSize >= packet.total;
}

function schedule() {
  clearTimeout(refreshTimer);
  if (closed || document.hidden) return;
  const now = Date.now();
  const deadline = Math.min(...(snapshot?.rows || []).map(row => Date.parse(row.eligible_until)));
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

async function refresh() {
  read?.abort();
  const controller = new AbortController();
  read = controller;
  const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(12000)]);
  reload.disabled = true;
  previous.disabled = next.disabled = true;
  if (!snapshot) status.textContent = 'Reading stored calculations…';
  try {
    const params = {limit: pageSize, offset};
    let packet = await get('/api/research/dashboard', params, signal);
    if (offset && offset >= packet.total) {
      offset = 0;
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
    notice.hidden = true;
    status.textContent = 'Current opportunities are unavailable. Reload saved prices to try again.';
  } finally {
    if (read === controller && !closed) {
      read = undefined;
      reload.disabled = false;
      previous.disabled = !snapshot || offset === 0;
      next.disabled = !snapshot || offset + pageSize >= snapshot.total;
      schedule();
    }
  }
}

reload.onclick = () => refresh();
previous.onclick = () => { offset -= pageSize; refresh(); };
next.onclick = () => { offset += pageSize; refresh(); };
const ageTimer = setInterval(() => updateRelativeAges(rows), 1000);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) clearTimeout(refreshTimer);
  else if (!closed) {
    if (snapshot?.rows.some(row => Date.parse(row.eligible_until) <= Date.now())) render(snapshot);
    refresh();
  }
});
window.addEventListener('pagehide', event => {
  if (event.persisted) return;
  closed = true;
  read?.abort();
  evidenceRead?.abort();
  clearTimeout(refreshTimer);
  clearInterval(ageTimer);
});
window.addEventListener('pageshow', event => {
  if (event.persisted) refresh();
});
refresh();
