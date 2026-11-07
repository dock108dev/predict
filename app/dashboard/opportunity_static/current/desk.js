import './ui-common.js';
import {clock, readPreference, savePreference, timezone} from './desk-preferences.js';

const {el, num, fmt, name, odd, link, button} = window.PredictUI;
const $ = id => document.getElementById(id);
const arb = location.pathname === '/arbs';
const pageSize = 25;
const filters = $('filters');
const stake = filters.elements.stake;
const dialog = $('trade');
const state = {offset: 0, page: null, request: null, selected: null, lastChecked: null};
const cash = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'});
const pct = value => value == null ? '—' : `${num(value) > 0 ? '+' : ''}${fmt(value)}%`;
const tone = value => num(value) > 0 ? 'positive' : num(value) < 0 ? 'negative' : '';

$('title').textContent = arb ? 'Arbitrage' : 'Expected value';
document.title = `Prediction Arb · ${$('title').textContent}`;
$('stake-field').hidden = $('profit-field').hidden = !arb;
stake.value = readPreference('stake', '100');
if (!stake.checkValidity() || !stake.value) stake.value = '100';
const filterKey = arb ? 'arb-filters' : 'ev-filters';
let saved;
try { saved = JSON.parse(readPreference(filterKey, '{}')); } catch { saved = {}; }
saved ||= {};
for (const key of ['search', 'day', 'sort', 'period', 'minimum', 'profit']) {
  if (saved[key]) filters.elements[key].value = saved[key];
}
filters.elements.positive.checked = saved.positive === 'on';
for (const [id, key, values] of [
  ['leagues', 'league', ['NBA', 'NFL', 'MLB', 'NHL', 'NCAAB', 'NCAAF']],
  ['families', 'family', ['winner', 'spread', 'total']],
  ['venues', 'venue', ['kalshi', 'polymarket_us', 'novig', 'prophetx']]
]) {
  for (const value of values) {
    const item = el('input'); item.type = 'checkbox'; item.name = key; item.value = value;
    item.checked = !saved[key] || saved[key].split(',').includes(value);
    const label = el('label'); label.append(item, name(value)); $(id).append(label);
  }
}

function selections() {
  const data = new FormData(filters);
  const query = Object.fromEntries(data);
  for (const key of ['league', 'family', 'venue']) {
    const chosen = data.getAll(key);
    query[key] = chosen.length ? chosen.join(',') : 'none';
  }
  delete query.stake;
  if (!arb) delete query.profit;
  return query;
}

function position(offer, game) {
  const selection = offer.selection || {};
  const participant = offer.participant || game?.participants?.find(p => p.id === selection.participant)?.name || selection.label;
  const line = selection.signed_line ?? offer.market.line;
  const signed = line == null ? '' : `${num(line) > 0 ? '+' : ''}${num(line)}`;
  switch (selection.predicate) {
    case 'win': return `${participant || 'Outcome'} to win`;
    case 'not_win': return `${participant || 'Outcome'} not to win`;
    case 'cover': return `${participant || 'Outcome'} to cover ${signed}`;
    case 'not_cover': return `${participant || 'Outcome'} not to cover ${signed}`;
    case 'over': return `Over ${num(line) ?? ''}`.trim();
    case 'under': return `Under ${num(line) ?? ''}`.trim();
    default: return [participant, selection.predicate?.replaceAll('_', ' '), signed].filter(Boolean).join(' ') || 'Outcome unavailable';
  }
}

function tradeDetails() {
  const {offer, group, game} = state.selected;
  $('trade-title').textContent = `${name(offer.venue)} · ${position(offer, game)}`;
  const body = $('trade-body');
  const price = el('p', 'Offered odds '); price.append(odd(offer.odds));
  const ref = el('p', 'Pinnacle '); ref.append(offer.reference ? odd(offer.reference) : 'Unavailable');
  if (offer.reference && !offer.reference_current) ref.append(' · Saved');
  body.replaceChildren(el('p', group.game_title, 'desk-meta'), price, ref,
    el('p', offer.value == null ? offer.reason : `${pct(offer.value)} EV before fees`, tone(offer.value)),
    el('p', `${offer.current ? 'Source time' : 'Saved price'} · ${clock(offer.source_at || offer.received_at)}`, 'desk-meta'));
  if (offer.probability != null) {
    const math = el('details');
    math.append(el('summary', 'Calculation'), el('p', `Fair probability ${fmt(num(offer.probability) * 100)}%. The model removes Pinnacle’s margin proportionally. EV divides expected profit by the acquisition cost, assuming a decisive result.`));
    body.append(math);
  }
}

function openTrade(offer, group, game) {
  state.selected = {offer, group, game};
  $('trade-note').textContent = '';
  tradeDetails();
  dialog.showModal();
}

function trade(group, title) {
  const box = el('div', null, 'desk-trade');
  if (title !== group.game_title) box.append(el('small', group.game_title, 'desk-matchup'));
  box.append(el('h2', title, 'desk-outcome'));
  const market = group.market;
  const period = market.period === 'full_game' ? 'Full game' : market.period?.replaceAll('_', ' ');
  box.append(el('small', [group.league, name(market.market), period].filter(Boolean).join(' · ')), el('small', clock(group.start_at)));
  return box;
}

function evRow(group, game) {
  const row = el('article', null, 'desk-row');
  const best = group.offers[0];
  const ref = group.offers.find(offer => offer.reference);
  const reference = el('div', null, 'desk-reference');
  reference.append(el('small', 'Pinnacle', 'desk-reference-label'),
    ref ? odd(ref.reference, 'desk-reference-odds') : el('span', '—', 'desk-reference-odds'));
  if (ref && !ref.reference_current) reference.append(el('small', 'Saved'));
  const offers = el('div', null, 'desk-ev-offers');
  for (const offer of group.offers) {
    const item = button('', () => openTrade(offer, group, game), 'desk-offer');
    item.setAttribute('aria-label', `${name(offer.venue)}, ${position(offer, game)}, ${offer.value == null ? offer.reason : pct(offer.value) + ' EV'}`);
    if (offer === best && num(offer.value) > 0) item.classList.add('desk-best');
    item.append(el('span', name(offer.venue), 'desk-site'), el('strong', pct(offer.value), tone(offer.value)), odd(offer.odds));
    if (offer.reason) item.append(el('small', offer.reason));
    offers.append(item);
  }
  row.append(trade(group, position(best, game)), reference, offers);
  return row;
}

function arbRow(group, game, expanded) {
  const row = el('article', null, 'desk-row desk-arb');
  const offers = new Map(group.offers.map(offer => [offer.id, offer]));
  const best = group.pairs[0];
  const [siteA, siteB] = best.legs.map(id => offers.get(id).venue);
  const reverse = group.pairs.find(pair => offers.get(pair.legs[0]).venue === siteB && offers.get(pair.legs[1]).venue === siteA);
  function pairing(pair, label) {
    const box = el('section', null, pair === best ? 'desk-pair desk-best' : 'desk-pair');
    box.append(el('small', label));
    if (!pair) { box.append(el('p', 'No matching reverse prices')); return box; }
    const amount = Number(stake.value);
    const first = Math.round(amount * num(pair.weights[0]) * 100) / 100;
    const profit = el('p', cash.format(amount * num(pair.value) / 100), `desk-return ${tone(pair.value)}`);
    profit.append(el('small', ` ${pct(pair.value)}`)); box.append(profit);
    pair.legs.forEach((id, index) => {
      const offer = offers.get(id);
      const leg = el('div', null, 'desk-leg'), text = el('span', `${position(offer, game)} · ${name(offer.venue)} · `);
      text.append(odd(offer.odds)); leg.append(text, el('span', cash.format(index ? amount - first : first))); box.append(leg);
    });
    return box;
  }
  const header = trade(group, group.game_title);
  header.querySelector('h2').after(el('small', best.legs.map(id => position(offers.get(id), game)).join(' / '), 'desk-matchup'));
  const detail = el('details', null, 'desk-expand'); detail.dataset.id = group.id; detail.open = expanded;
  const list = el('div', null, 'desk-pair-list');
  detail.append(el('summary', `Compare all sites (${group.pairs.length} ${group.pairs.length === 1 ? 'pairing' : 'pairings'})`), list);
  // Build the long pairing list only when the row is expanded.
  function expand() { if (detail.open && !list.hasChildNodes()) group.pairs.forEach(pair => list.append(pairing(pair, 'Completed-game profit'))); }
  detail.addEventListener('toggle', expand); expand();
  row.append(header, pairing(best, 'Best pairing · profit'), pairing(reverse, 'Reverse pairing · profit'), detail);
  return row;
}

function refreshStatus() {
  const checked = state.lastChecked ? `Last checked ${new Intl.DateTimeFormat('en-US', {hour:'numeric', minute:'2-digit', second:'2-digit', timeZoneName:'short', timeZone:timezone()}).format(state.lastChecked)}.` : 'No successful check yet.';
  const mode = state.request ? 'Checking for updates…' : state.offset ? 'Auto-refresh paused on this page. Refresh returns to page one.' : $('results').contains(document.activeElement) ? 'Auto-refresh paused while a result has keyboard focus.' : 'Auto-refresh on.';
  $('refresh-status').textContent = `${mode} ${checked}`;
  $('refresh-list').disabled = !!state.request;
}

function render(page) {
  const expanded = new Set([...$('results').querySelectorAll('details[open]')].map(e => e.dataset.id));
  const games = new Map((page.games || []).map(game => [game.game_key, game]));
  const rows = page.rows || [];
  const total = page.total || 0;
  const publication = page.publication || {};
  const notice = [];
  if (!publication.current_prices && publication.retained_prices) notice.push('Only saved prices are available right now.');
  else if (publication.state === 'held') notice.push('Current prices are unavailable.');
  else if (publication.state === 'partial') notice.push('Some prices are not current. Check each price’s status.');
  if (arb) notice.push('Returns assume a completed game and equal payouts at the displayed prices. Voids and cancellations may differ.');
  $('notice').textContent = notice.join(' ');
  const results = $('results'); results.replaceChildren();
  if (rows.length) {
    if (!arb) {
      const columns = el('div', null, 'desk-columns');
      columns.append(el('span', 'Trade'), el('span', 'Pinnacle'), el('span', 'Sites · highest EV first')); results.append(columns);
    }
    for (const group of rows) {
      const game = games.get(group.game_key);
      results.append(arb ? arbRow(group, game, expanded.has(group.id)) : evRow(group, game));
    }
  } else {
    const empty = el('div', null, 'desk-empty');
    const message = page.state === 'initializing' ? 'Waiting for the first price update.' :
      arb ? 'No current pairings match these filters.' : 'No trades match these filters.';
    empty.append(el('h2', message), link('Check sources in Admin', '/admin?section=sources'));
    results.append(empty);
  }
  $('count').textContent = total ? `${state.offset + 1}–${state.offset + rows.length} of ${total.toLocaleString()}` : '0 results';
  $('previous').disabled = state.offset === 0;
  $('next').disabled = state.offset + rows.length >= total;
}

async function load(offset = state.offset) {
  state.request?.abort();
  const controller = new AbortController(); state.request = controller; refreshStatus();
  const query = new URLSearchParams({...selections(), layout: 'desk', view: arb ? 'arbs' : 'ev',
    stake: stake.value, timezone: timezone(), offset, limit: pageSize});
  if (offset && state.page?.cursor) query.set('expected_cursor', state.page.cursor);
  if (!state.page) $('notice').textContent = 'Loading prices…';
  try {
    const response = await fetch(`/api/comparison-current?${query}`, {signal: controller.signal});
    if (!response.ok) throw new Error('Unavailable');
    const page = await response.json();
    if (controller.signal.aborted) return;
    if (page.state === 'page_changed') return load(0);
    state.page = page; state.offset = offset; state.lastChecked = new Date(); render(page);
  } catch (error) {
    if (error.name !== 'AbortError') {
      $('notice').textContent = 'Prices could not be loaded. Retrying automatically.';
      $('results').replaceChildren(); $('count').textContent = '';
      $('next').disabled = $('previous').disabled = true;
    }
  } finally { if (state.request === controller) { state.request = null; refreshStatus(); } }
}

let debounce;
filters.addEventListener('submit', event => event.preventDefault());
filters.addEventListener('input', () => {
  if (!filters.checkValidity() || !stake.value) return;
  savePreference(filterKey, JSON.stringify(selections()));
  if (arb) savePreference('stake', stake.value);
  clearTimeout(debounce); debounce = setTimeout(() => load(0), 240);
});
$('reset').onclick = () => {
  const amount = stake.value;
  filters.reset(); stake.value = amount;
  for (const field of filters.querySelectorAll('fieldset input')) field.checked = true;
  savePreference(filterKey, JSON.stringify(selections())); load(0);
};
$('refresh-list').onclick = () => load(0);
document.addEventListener('focusin', refreshStatus);
document.addEventListener('focusout', () => queueMicrotask(refreshStatus));
$('previous').onclick = () => load(Math.max(0, state.offset - pageSize));
$('next').onclick = () => load(state.offset + pageSize);
$('latest').onclick = async () => {
  const selection = state.selected;
  const query = new URLSearchParams({id: selection.offer.id, layout: 'desk'});
  $('latest').disabled = true;
  $('trade-note').textContent = 'Checking latest price…';
  try {
    const response = await fetch(`/api/comparison-current/selection?${query}`);
    if (!response.ok) throw new Error('Unavailable');
    const {row} = await response.json();
    if (!dialog.open || state.selected !== selection) return;
    if (!row?.current) {
      $('trade-note').textContent = 'No current price for this trade. The inspected price is still shown.';
      return;
    }
    state.selected = {...selection, offer: row};
    $('trade-note').textContent = '';
    tradeDetails();
  } catch {
    if (dialog.open && state.selected === selection) $('trade-note').textContent = 'Could not check the latest price.';
  } finally { $('latest').disabled = false; }
};
load();
setInterval(() => {
  if (!state.request && !state.offset && !document.hidden && !$('results').contains(document.activeElement)) load();
  refreshStatus();
}, 6500);
