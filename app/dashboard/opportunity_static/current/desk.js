import './ui-common.js';
import {tradeInspection, pairInspection} from './desk-inspection.js';
import {DiagnosticSession} from './session-history.js';
import {clock as savedClock, readPreference, savePreference, timezone} from './desk-preferences.js';

const {el, num, fmt, name, odd, link, button} = window.PredictUI;
const $ = id => document.getElementById(id);
const replay = location.pathname === '/replay';
const route = new URLSearchParams(location.search);
const arb = location.pathname === '/arbs' || replay && route.get('view') === 'arbs';
const dataset = ['frozen','preview','practice'].includes(route.get('dataset')) ? route.get('dataset') : 'frozen';
const frame = route.get('frame') === 'changed' ? 'changed' : 'initial';
const endpoint = replay ? '/api/odds-replay' : '/api/comparison-current';
const replayURL = (view, chosen = dataset, step = frame) => '/replay?' + new URLSearchParams({view, dataset:chosen, frame:step});
const replayMode = () => !replay ? null : dataset === 'practice' ? 'Synthetic practice · fictional prices and inputs' : 'Mock live · frozen observed prices';
const pageSize = 25;
const filters = $('filters');
const clock=at=>savedClock(at,filters.elements.timezone.value);
const stake = filters.elements.stake;
const dialog = $('trade');
const state = {offset: 0, page: null, request: null, selected: null, lastChecked: null};
const history = new DiagnosticSession();
const cash = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'});
const payoffCash = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: 6});
const payoffReturn = new Intl.NumberFormat('en-US', {maximumFractionDigits: 4, signDisplay:'exceptZero'});
const pct = value => value == null ? '—' : `${num(value) > 0 ? '+' : ''}${fmt(value)}%`;
const tone = value => num(value) > 0 ? 'positive' : num(value) < 0 ? 'negative' : '';

$('title').textContent = arb ? 'Arbitrage' : 'Expected value';
document.title = `Prediction Arb · ${$('title').textContent}`;
$('stake-field').hidden = $('profit-field').hidden = !arb;
$('basis-field').hidden = $('group-field').hidden = arb;
$('replay-controls').hidden = !replay;
if (replay) {
  $('desk-mode').textContent = replayMode();
  $('replay-link').textContent = 'Return to live board';
  $('replay-link').href = arb ? '/arbs' : '/ev';
  $('replay-dataset').value = dataset;
  $('replay-frame').value = frame;
  $('replay-frame-field').hidden = dataset !== 'practice';
  $('replay-ev').href = replayURL('ev');
  $('replay-arbs').href = replayURL('arbs');
  $(arb ? 'replay-arbs' : 'replay-ev').setAttribute('aria-current','page');
  $('replay-dataset').onchange = event => location.assign(replayURL(arb ? 'arbs' : 'ev', event.target.value, 'initial'));
  $('replay-frame').onchange = event => location.assign(replayURL(arb ? 'arbs' : 'ev', dataset, event.target.value));
}
stake.value = readPreference('stake', '100');
if (!stake.checkValidity() || !stake.value) stake.value = '100';
const filterKey = `${replay ? 'replay-' + dataset + '-' : ''}${arb ? 'arb' : 'ev'}-filters`;
let saved;
try { saved = JSON.parse(readPreference(filterKey, '{}')); } catch { saved = {}; }
saved ||= {};
if (replay) { saved.group ||= 'offer'; saved.basis ||= 'before'; }
for (const key of ['search', 'day', 'sort', 'group', 'period', 'minimum', 'profit','basis','timezone','time_from','time_to','game_state']) {
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
  const {offer, group, game, evidence} = state.selected;
  const label = position(offer, game);
  $('trade-title').textContent = `${name(offer.venue)} · ${label}`;
  $('trade-body').replaceChildren(tradeInspection(offer, group, evidence, {mode:replayMode(), position:label}));
  $('latest').hidden = replay;
  $('back-to-pair').hidden = !state.selected.pairContext;
}

async function openTrade(offer, group, game, pairContext = null) {
  const opener = pairContext?.opener || document.activeElement;
  state.selected = {offer, group, game, opener, pairContext};
  $('trade-note').textContent = '';
  tradeDetails();
  if (!dialog.open) dialog.showModal();
  else dialog.querySelector('form button').focus();
  dialog.scrollTop=0;
  const selected=state.selected;
  try {
    const pinned=await pinEvidence(offer);
    if(state.selected!==selected||!dialog.open){releaseEvidence(pinned.lease);return;}
    Object.assign(selected,pinned);tradeDetails();
  } catch {
    if(state.selected===selected&&dialog.open){
      selected.retentionError='Full evidence could not be loaded. Displayed prices and returns remain pinned.';
      $('trade-note').textContent=selected.retentionError;
      $('trade-body').querySelector('.inspection-loading')?.remove();
    }
  }
}

function openPair(pair, offers, group, game, opener = document.activeElement) {
  const context = {pair, offers, group, game, opener};
  state.selected = context;
  $('trade-title').textContent = 'Arbitrage calculation';
  $('trade-note').textContent = '';
  $('latest').hidden = $('back-to-pair').hidden = true;
  $('trade-body').replaceChildren(pairInspection(pair, offers, {group, game, position, mode:replayMode(),
    inspect: offer => openTrade(offer, group, game, context)}));
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
}
$('back-to-pair').onclick = () => {
  const {pairContext, lease} = state.selected;
  releaseEvidence(lease);
  openPair(pairContext.pair, pairContext.offers, pairContext.group, pairContext.game, pairContext.opener);
  dialog.querySelector('form button').focus();
};
async function releaseEvidence(lease){if(lease)try{await fetch('/api/comparison-current/lease?'+new URLSearchParams({lease_id:lease.lease_id}),{method:'DELETE'});}catch{}}
async function pinEvidence(offer){
  if(!offer.evidence_result_id)throw Error('Missing exact evidence');
  if (replay) {
    const query = new URLSearchParams({dataset, frame, result_id:offer.evidence_result_id, id:offer.id});
    const detail = await fetch(`/api/odds-replay/details?${query}`);
    if (!detail.ok) throw Error('Replay evidence unavailable');
    const evidence = await detail.json();
    if (evidence.row.id !== offer.id || evidence.row.price_revision !== offer.price_revision ||
        evidence.row.economic_revision !== offer.economic_revision) throw Error('Replay revision changed');
    return {evidence};
  }
  const response=await fetch('/api/comparison-current/lease',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({result_id:offer.evidence_result_id})});
  if(!response.ok)throw Error('Evidence expired');const lease=await response.json();
  try{const detail=await fetch('/api/comparison-snapshot/details?'+new URLSearchParams({result_id:offer.evidence_result_id,id:offer.id,lease_id:lease.lease_id}));if(!detail.ok)throw Error();const evidence=await detail.json();
    if(evidence.row.id!==offer.id||evidence.row.price_revision!==offer.price_revision||evidence.row.economic_revision!==offer.economic_revision)throw Error();return {lease,evidence};
  }catch(error){releaseEvidence(lease);throw error;}
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

function evRow(group, game, individual) {
  const row = el('article', null, individual ? 'desk-row desk-individual' : 'desk-row');
  const best = group.offers[0];
  const ref = group.offers.find(offer => offer.reference);
  const reference = el('div', null, 'desk-reference');
  reference.append(el('small', 'Pinnacle', 'desk-reference-label'),
    ref ? odd(ref.reference, 'desk-reference-odds') : el('span', '—', 'desk-reference-odds'));
  if (ref && !ref.reference_current) reference.append(el('small', 'Saved'));
  const offers = el('div', null, 'desk-ev-offers');
  for (const offer of group.offers) {
    const item = button('', () => openTrade(offer, group, game), 'desk-offer');
    item.dataset.offerId=offer.id;
    item.setAttribute('aria-label', `${name(offer.venue)}, ${position(offer, game)}, ${offer.value == null ? offer.reason : pct(offer.value) + ' EV'}`);
    if (offer === best && num(offer.value) > 0) item.classList.add('desk-best');
    const site = el('span', name(offer.venue), 'desk-site');
    const value = el('strong', pct(offer.value), tone(offer.value));
    const price = odd(offer.odds);
    const breakdown = el('small', `Before ${pct(offer.before_fee)} · Reviewed ${pct(offer.after_fee)}${individual ? ` · Conservative ${pct(offer.conservative)}` : ''}`, 'offer-breakdown');
    item.append(site, value, price, breakdown);
    if (offer.reason) item.append(el('small', offer.reason, 'offer-reason'));
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
    const math = pair.inspection;
    const profit = el('p', payoffCash.format(num(math.minimum_profit_usd)), `desk-return ${tone(math.minimum_profit_usd)}`);
    profit.append(el('small', ` ${payoffReturn.format(num(math.rounded_return_percent))}%`)); box.append(profit);
    pair.legs.forEach((id, index) => {
      const offer = offers.get(id);
      const leg = el('div', null, 'desk-leg'), text = el('span', `${position(offer, game)} · ${name(offer.venue)} · `);
      text.append(odd(offer.odds)); leg.append(text, el('span', cash.format(num(math.legs[index].allocation_usd)))); box.append(leg);
    });
    box.append(button('Inspect pairing', () => openPair(pair, offers, group, game), 'desk-pair-inspect'));
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
  const checked = state.lastChecked ? `Last checked ${new Intl.DateTimeFormat('en-US', {hour:'numeric', minute:'2-digit', second:'2-digit', timeZoneName:'short', timeZone:filters.elements.timezone.value}).format(state.lastChecked)}.` : 'No successful check yet.';
  const mode = !filters.elements.time_to.validity.valid ? 'Correct the time window to refresh.' : replay ? (state.request ? 'Loading replay…' : 'Replay clock is fixed.') : state.request ? 'Checking for updates…' : state.offset ? 'Browsing order held. Prices and authority update; Refresh list starts a new order.' : $('results').contains(document.activeElement) ? 'Auto-refresh paused while a result has keyboard focus.' : 'Auto-refresh on.';
  $('refresh-status').textContent = `${mode} ${checked}`;
  $('refresh-list').disabled = !!state.request || !filters.elements.time_to.validity.valid;
}

function render(page) {
  const expanded = new Set([...$('results').querySelectorAll('details[open]')].map(e => e.dataset.id));
  const games = new Map((page.games || []).map(game => [game.game_key, game]));
  const rows = page.rows || [];
  const total = page.total || 0;
  const publication = page.publication || {};
  const notice = [];
  const coverage = page.coverage;
  const strip = $('coverage-strip');
  strip.hidden = !coverage?.offers;
  if (coverage?.offers) strip.textContent = `${coverage.offers.toLocaleString()} offers · ${coverage.current.toLocaleString()} ${replay ? 'fresh at capture' : 'current'} · ${coverage.before.toLocaleString()} before-fee EV · ${coverage.reviewed.toLocaleString()} reviewed fee EV · ${coverage.conservative.toLocaleString()} conservative EV`;
  if (replay && page.replay?.captured_at) notice.push(`${replayMode()} · ${clock(page.replay.captured_at)}`);
  if(state.offset && !replay)notice.push(page.browse_order||'Browsing order held.');
  if(!replay && publication.data_runtime&&!publication.data_runtime.healthy)notice.push('The data process is unavailable. The app is showing retained evidence; open Admin for its status.');
  else if(publication.data_runtime?.stopped)notice.push('Updates were stopped. Open Admin to inspect the saved Stop choice.');
  if (!publication.current_prices && publication.retained_prices) notice.push(replay ? 'All displayed prices were retained at capture.' : 'Only saved prices are available right now.');
  else if (publication.state === 'held') notice.push('Current prices are unavailable.');
  else if (publication.state === 'partial') notice.push(replay ? 'Some offers lacked fresh prices or complete calculation inputs at capture.' : 'Some prices are not current. Check each price’s status.');
  if (arb) notice.push('Each pair shows its lower decisive profit after cent allocation, before fees. Voids and cancellations can change the payoff.');
  $('notice').textContent = notice.join(' ');
  const results = $('results'); results.replaceChildren();
  if (rows.length) {
    if (!arb) {
      const columns = el('div', null, 'desk-columns');
      columns.append(el('span', 'Trade'), el('span', 'Pinnacle'), el('span', 'Offers · highest EV first')); results.append(columns);
    }
    for (const group of rows) {
      const game = games.get(group.game_key);
      if(group.withdrawn){results.append(el('p',`${group.game_title}: ${group.reason}`,'desk-note'));continue;}
      results.append(arb ? arbRow(group, game, expanded.has(group.id)) : evRow(group, game, page.row_kind === 'offers'));
    }
  } else {
    const empty = el('div', null, 'desk-empty');
    const message = page.state === 'initializing' ? (replay ? 'This capture is not available yet.' : 'Waiting for the first price update.') :
      arb ? 'No current pairings match these filters.' : 'No trades match these filters.';
    empty.append(el('h2', message), replay && page.state === 'initializing' ? link('Open earlier capture', replayURL(arb ? 'arbs' : 'ev', 'preview')) : link('Check sources in Admin', '/admin?section=sources'));
    results.append(empty);
  }
  $('count').textContent = total ? `${state.offset + 1}–${state.offset + rows.length} of ${total.toLocaleString()} ${arb ? 'pair groups' : page.row_kind || 'outcomes'} · ${page.game_count??'—'} games` : '0 results';
  $('previous').disabled = state.offset === 0;
  $('next').disabled = state.offset + rows.length >= total;
}

async function load(offset = state.offset) {
  if (!filters.checkValidity() || !stake.value) return;
  state.request?.abort();
  const controller = new AbortController(); state.request = controller; refreshStatus();
  const query = new URLSearchParams({...selections(), layout: 'desk', view: arb ? 'arbs' : 'ev',
    stake: stake.value, offset, limit: pageSize});
  if (replay) { query.set('dataset', dataset); query.set('frame', frame); }
  if (!replay && offset && state.page?.browse_id) query.set('browse_id', state.page.browse_id);
  if (!state.page) $('notice').textContent = 'Loading prices…';
  try {
    const response = await fetch(`${endpoint}?${query}`, {signal: controller.signal});
    if (!response.ok) throw new Error('Unavailable');
    const page = await response.json();
    if (controller.signal.aborted) return;
    if (page.state === 'page_changed') {history.record('browsing_reset',{reason:page.reason});state.resetReason=page.reason;return load(0);}
    state.page = page; state.offset = offset; state.lastChecked = new Date(); render(page);history.observe(page,selections());if(state.resetReason){$('notice').textContent+=' '+state.resetReason;state.resetReason=null;}
    checkSelection();
  } catch (error) {
    if (error.name !== 'AbortError') {
      $('notice').textContent = replay ? 'Replay could not be loaded. Refresh the list to retry.' : 'Prices could not be loaded. Retrying automatically.';
      history.record('display_gap',{reason:'local_read_failed'});
      $('next').disabled = $('previous').disabled = true;
    }
  } finally { if (state.request === controller) { state.request = null; refreshStatus(); } }
}

const panel = $('filter-panel');
$('open-filters').onclick = () => panel.showModal();
$('close-filters').onclick = () => panel.close();
$('filter-done').onclick = () => {
  if (!validateTimeWindow()) {
    $('timing-filters').open = true;
    filters.elements.time_to.focus();
    return;
  }
  panel.close();
};

function validateTimeWindow() {
  const {time_from: from, time_to: to} = filters.elements;
  const error = from.value && to.value && from.value >= to.value ? 'Choose an end time after the start time.' : '';
  to.setCustomValidity(error);
  $('time-window-error').textContent = error;
  $('time-window-error').hidden = !error;
  return !error;
}

function activeFilters() {
  const active = [];
  const add = (label, clear) => active.push({label, clear});
  for (const [id, title] of [['leagues','Leagues'], ['families','Markets'], ['venues','Sites']]) {
    const fields = [...$(id).querySelectorAll('input')];
    const picked = fields.filter(field => field.checked);
    if (picked.length !== fields.length) {
      const excluded = fields.filter(field => !field.checked);
      const label = picked.length === 1 ? name(picked[0].value) : picked.length > 2 && excluded.length === 1
        ? `Except ${name(excluded[0].value)}` : `${picked.length} ${title.toLowerCase()}`;
      add(label, () => fields.forEach(field => field.checked = true));
    }
  }
  for (const [key, prefix] of [['day',''], ['game_state',''], ['period',''], ['minimum','Min EV '], ['profit','Min profit $']]) {
    const field = filters.elements[key];
    if (field.value && (key !== 'profit' || arb)) {
      const value = field.selectedOptions?.[0]?.textContent || field.value;
      add(`${prefix}${value}${key === 'minimum' ? '%' : ''}`, () => field.value = '');
    }
  }
  if (filters.elements.time_from.value || filters.elements.time_to.value) {
    add(`${filters.elements.time_from.value || '00:00'}–${filters.elements.time_to.value || '24:00'} ${filters.elements.timezone.value === 'UTC' ? 'UTC' : 'ET'}`,
      () => filters.elements.time_from.value = filters.elements.time_to.value = '');
  }
  if (filters.elements.positive.checked) add('Positive only', () => filters.elements.positive.checked = false);
  if (filters.elements.sort.value === 'start') add('Soonest start', () => filters.elements.sort.value = 'return');
  if (filters.elements.timezone.value === 'UTC' && !filters.elements.time_from.value && !filters.elements.time_to.value) {
    add('UTC', () => filters.elements.timezone.value = 'America/New_York');
  }
  $('filter-count').hidden = !active.length;
  $('filter-count').textContent = active.length;
  const chips = $('active-filters');
  chips.hidden = !active.length;
  chips.replaceChildren(...active.map(({label, clear}) => {
    const chip = button(`${label} ×`, () => { clear(); applyFilters(); $('open-filters').focus(); }, 'filter-chip');
    chip.setAttribute('aria-label', `Clear ${label} filter`);
    return chip;
  }));
}

let debounce;
function applyFilters() {
  activeFilters();
  validateTimeWindow();
  refreshStatus();
  if (!filters.checkValidity() || !stake.value) return;
  savePreference(filterKey, JSON.stringify(selections()));
  if (arb) savePreference('stake', stake.value);
  clearTimeout(debounce); debounce = setTimeout(() => load(0), 240);
}
filters.addEventListener('submit', event => event.preventDefault());
filters.addEventListener('input', applyFilters);
$('reset').onclick = () => {
  const amount = stake.value;
  const {value: basis} = filters.elements.basis;
  const {value: group} = filters.elements.group;
  filters.reset(); stake.value = amount;
  filters.elements.basis.value = basis;
  filters.elements.group.value = group;
  for (const field of filters.querySelectorAll('fieldset input')) field.checked = true;
  applyFilters();
};
activeFilters();
validateTimeWindow();
$('refresh-list').onclick = () => load(0);
document.addEventListener('focusin', refreshStatus);
document.addEventListener('focusout', () => queueMicrotask(refreshStatus));
$('previous').onclick = () => load(Math.max(0, state.offset - pageSize));
$('next').onclick = () => load(state.offset + pageSize);
$('latest').onclick = async () => {
  const selection = state.selected;
  const query = new URLSearchParams({id: selection.offer.id, layout: 'desk',basis:filters.elements.basis.value});
  $('latest').disabled = true;
  $('trade-note').textContent = 'Checking latest price…';
  let pendingLease=null;
  try {
    const response = await fetch(`/api/comparison-current/selection?${query}`);
    if (!response.ok) throw new Error('Unavailable');
    const {row} = await response.json();
    if (!dialog.open || state.selected !== selection) return;
    if (!row?.current) {
      $('trade-note').textContent = 'No current price for this trade. The inspected price is still shown.';
      return;
    }
    const pinned=await pinEvidence(row);pendingLease=pinned.lease;
    if(!dialog.open||state.selected!==selection){releaseEvidence(pinned.lease);return;}
    const verify=await fetch(`/api/comparison-current/selection?${query}`);const newest=verify.ok?(await verify.json()).row:null;
    if(!newest?.current||newest.economic_revision!==row.economic_revision||newest.price_revision!==row.price_revision){releaseEvidence(pinned.lease);$('trade-note').textContent='Prices changed during adoption. Inspected inputs remain pinned; check latest again.';return;}
    state.selected = {...selection, offer: row,...pinned,retentionError:null};pendingLease=null;releaseEvidence(selection.lease);
    $('trade-note').textContent = '';
    tradeDetails();
  } catch {
    releaseEvidence(pendingLease);
    if (dialog.open && state.selected === selection) $('trade-note').textContent = 'Could not check the latest price.';
  } finally { $('latest').disabled = false; }
};
dialog.addEventListener('close',()=>{const old=state.selected;releaseEvidence(old?.lease);const current=[...$('results').querySelectorAll('[data-offer-id]')].find(e=>e.dataset.offerId===old?.offer.id);(old?.opener?.isConnected?old.opener:current||$('refresh-list')).focus({preventScroll:true});});
async function checkSelection(){
  const selected=state.selected;if(replay||!dialog.open||!selected?.offer)return;
  try{const response=await fetch('/api/comparison-current/selection?'+new URLSearchParams({id:selected.offer.id,layout:'desk',basis:filters.elements.basis.value}));if(!response.ok)return;const {row}=await response.json();
    if(!dialog.open||selected!==state.selected)return;
    if(selected.retentionError){$('trade-note').textContent=selected.retentionError;return;}
    const economic=o=>JSON.stringify([o?.odds,o?.economic_revision,o?.before_fee,o?.after_fee,o?.conservative,o?.current]);
    $('trade-note').textContent=!row?.current?'Latest price is unavailable; inspected evidence remains pinned.':economic(row)!==economic(selected.offer)?`New prices available: ${pct(selected.offer.after_fee)} → ${pct(row.after_fee)} after fees. Use latest prices to adopt all inputs.`:'';
  }catch{}
}
$('session-export').onclick=()=>history.export();
$('session-clear').onclick=()=>history.clear();
history.mount($('session-summary'),$('session-events'));
document.addEventListener('visibilitychange',()=>history.record(document.hidden?'display_paused':'display_resumed',{reason:'tab_visibility'}));
load();
setInterval(() => {
  if (!replay && !state.request && !document.hidden && !$('results').contains(document.activeElement)) load();
  refreshStatus();
}, 6500);

setInterval(async()=>{const selected=state.selected;if(!dialog.open||!selected?.lease)return;try{const response=await fetch('/api/comparison-current/lease',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({result_id:selected.offer.evidence_result_id,lease_id:selected.lease.lease_id})});if(!response.ok&&selected===state.selected){selected.retentionError='Evidence retention expired; displayed inspection remains saved.';$('trade-note').textContent=selected.retentionError;}}catch{}},30000);
