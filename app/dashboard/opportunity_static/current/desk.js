import './ui-common.js';
import {markPinned, tradeInspection, pairInspection} from './desk-inspection.js';
import {arbCard, evCard, gameMatrix, quoteFreshness, selectedReference, updateMatrixCues} from './opportunity-cards.js';
import {pinLatestSelection, selectionCurrent, selectionIdentity} from './desk-evidence.js';
import {evidenceReason} from './desk-reasons.js';
import {DiagnosticSession} from './session-history.js';
import {clock as savedClock, readPreference, savePreference, timezone} from './desk-preferences.js';

const {el, num, fmt, name, odd, link, button} = window.PredictUI;
const $ = id => document.getElementById(id);
const replay = location.pathname === '/replay';
const route = new URLSearchParams(location.search);
const arb = location.pathname === '/arbs' || replay && route.get('view') === 'arbs';
const gameView = location.pathname === '/game' || replay && route.get('view') === 'game';
const gameKey = gameView ? route.get('game_key') : null;
const requestedLine = gameKey ? route.get('line') : null;
const linkedTitle = gameKey ? route.get('matchup')?.slice(0, 160) : null;
const linkedLine = requestedLine ? route.get('line_label')?.slice(0, 120) : null;
const browse = ['/browse-odds', '/game'].includes(location.pathname) || replay && ['odds', 'game'].includes(route.get('view'));
const opportunityView = !browse && !replay;
const comparable = !replay && !arb;
let phase = !replay && (route.get('phase') === 'live' ? 'live' : 'pregame');
let liveEnabled = false;
const phaseURL = (path, value = phase) => path + (value === 'live' ? '?phase=live' : '');
const back = window.PredictUI.localURL(route.get('back'));
let safeBack = back && ['/','/ev','/arbs','/browse-odds','/game','/replay'].includes(back.pathname)
  ? back.pathname + back.search : null;
const browseCacheKey = 'predict-desk-return';
const dataset = ['frozen','preview','retained'].includes(route.get('dataset')) ? route.get('dataset') : 'frozen';
const retainedResult = replay && dataset === 'retained' ? route.get('result_id') : null;
const endpoint = replay ? '/api/odds-replay' : '/api/comparison-current';
const replayURL = (view, chosen = dataset === 'retained' ? 'frozen' : dataset) => '/replay?' + new URLSearchParams({view, dataset:chosen});
const replayMode = () => replay ? 'Saved odds · prices at capture' : null;
const pageSize = 25;
const gamesPerPage = 12;
const pageLimit = gameKey ? 100 : replay ? (browse ? 5 : pageSize) : arb ? pageSize : gamesPerPage;
const filters = $('filters');
const browseFilterFields = ['league','family','venue','search','day','period','timezone','time_from','time_to','game_state'];
const defaultZone = timezone();
const selectedZone = () => filters.elements.timezone.value || defaultZone;
const clock = at => savedClock(at, selectedZone());
const stake = filters.elements.stake;
const dialog = $('trade');
const state = {offset: 0, page: null, request: null, selected: null, renderedStake: null};
const history = new DiagnosticSession();
const siteName = offer => name(offer.venue);
function collectionIssue(runtime) {
  if (runtime?.stopped) return ['Price updates are stopped', 'Collection was stopped in Admin.'];
  switch (runtime?.reason) {
    case 'data_runtime_absent': return ['Price collection has not started', 'This desk has no collector heartbeat.'];
    case 'data_runtime_not_dispatching': return ['The collector is not gathering prices', 'The collector reports in but is not requesting prices.'];
    case 'data_runtime_unhealthy': return ['Price collection is unavailable', 'The collector has not reported a healthy heartbeat.'];
    case 'ordinary_publication_failed': return ['Price publication is delayed', 'The latest price update could not be published to the desk.'];
    default: return runtime?.healthy === false ? ['Price collection is unavailable', 'The desk cannot confirm the collector is running.'] : null;
  }
}

function sourceNotices(publication) {
  const notices = [];
  const paused = publication.data_runtime?.paused_sources || [];
  if (paused.length) notices.push(`Updates paused for ${paused.map(name).join(', ')}.`);
  for (const site of ['sportsgameodds', 'novig', 'prophetx', 'kalshi', 'polymarket_us']) {
    const source = publication.sources?.[site];
    if (!source || paused.includes(site)) continue;
    if (source.reason_code === 'sgo_charge_unresolved' || source.reason_code === 'ambiguous_dispatch_unresolved') {
      notices.push(`${name(site)} updates are on hold pending provider reconciliation.`);
    } else if (source.reason_code === 'sgo_usage_unreconciled') {
      notices.push('SportsGameOdds updates are waiting for a confirmed provider balance.');
    } else if (source.state === 'resyncing') {
      notices.push(`${name(site)} is rebuilding its price feed.`);
    }
  }
  return notices;
}

function restoreFocus(target) {
  // The native dialog restores focus before the queued close event. Only supply
  // a fallback when its opener is gone and focus is still on the document.
  if (document.activeElement === document.body) target.focus({preventScroll:true});
}

$('title').textContent = gameKey ? linkedTitle || 'Game odds' : browse ? 'Browse odds' : replay ? (arb ? 'Arbitrage' : 'Expected value') : 'Opportunities';
document.title = `Predict · ${$('title').textContent}`;
$('stake-field').hidden = !arb || !replay;
$('profit-field').hidden = !arb;
$('basis-field').hidden = arb;
$('group-field').hidden = arb || !replay;
$('opportunity-tabs').hidden = !opportunityView;
function updatePhaseView() {
  if (replay) return;
  $('phase-tabs').hidden = !liveEnabled;
  for (const value of ['pregame','live']) $(`phase-${value}`).removeAttribute('aria-current');
  $(phase === 'live' ? 'phase-live' : 'phase-pregame').setAttribute('aria-current', 'page');
  if (browse) updateBrowsePhaseLinks();
  else {
    $('phase-pregame').href = phaseURL(arb ? '/arbs' : '/ev', 'pregame');
    $('phase-live').href = phaseURL(arb ? '/arbs' : '/ev', 'live');
    $('opportunity-ev').href = phaseURL('/ev');
    $('opportunity-arb').href = phaseURL('/arbs');
  }
  $('period-field').hidden = phase === 'pregame';
  if (browse) {
    if (safeBack && $('desk-path').firstElementChild) $('desk-path').firstElementChild.href = safeBack;
    $('browse-link').href = gameKey ? phaseURL('/browse-odds') : phaseURL('/');
  }
}
updatePhaseView();
$('game-state-field').hidden = !!phase;
if (replay) $('period-field').hidden = false;
$(arb ? 'opportunity-arb' : 'opportunity-ev').setAttribute('aria-current', 'page');
$('positive-field').hidden = browse;
$('return-filters').hidden = browse;
$('sort-field').hidden = !replay;
if (replay) $('return-title').textContent = 'Sorting and return thresholds';
$('last-known-field').hidden = !browse || !replay;
$('alternates-field').hidden = !browse && !comparable;
$('filters').querySelector('.desk-search').hidden = !!gameKey;
$('replay-controls').hidden = !replay || dataset === 'retained';
$('browse-link').hidden = replay && !browse;
if (browse) {
  $('browse-link').href = replay ? replayURL(gameKey ? 'odds' : 'ev')
    : gameKey ? phaseURL('/browse-odds') : phaseURL('/');
  $('browse-link').textContent = gameKey ? 'All games' : 'Opportunities';
  if (dataset === 'retained') {
    $('browse-link').href = '/browse-odds';
    $('browse-link').textContent = 'Current games';
  }
  $('desk-path').hidden = false;
  const previousView = link('Back', safeBack || (replay ? replayURL('ev') : '/'));
  previousView.addEventListener('click', event => {
    if (!safeBack || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const previousURL = new URL(safeBack, location.origin).href;
    const entry = window.navigation?.currentEntry;
    const previousEntry = entry && window.navigation.entries()[entry.index - 1];
    if (previousEntry?.url === previousURL || document.referrer === previousURL) {
      event.preventDefault();
      window.history.back();
      return;
    }
    // Some browsers hide the referrer and have no Navigation API. Carry the
    // return state through a normal link in that case.
    const cached = readBrowseReturn();
    if (cached?.url === previousURL) {
      try { sessionStorage.setItem(browseCacheKey, JSON.stringify({...cached, restoreOnArrival:true})); } catch {}
    }
  });
  $('desk-path').append(previousView);
}
$('replay-link').href = replayURL(arb ? 'arbs' : 'ev', 'frozen');
filters.elements.timezone.options[0].textContent = `Default (${defaultZone.replaceAll('_', ' ')})`;
if (replay) {
  $('desk-mode').hidden = false;
  $('desk-mode').textContent = replayMode();
  $('replay-link').textContent = 'Return to opportunities';
  $('replay-link').href = arb ? '/arbs' : '/ev';
  $('replay-dataset').value = dataset;
  $('replay-ev').href = replayURL('ev');
  $('replay-arbs').href = replayURL('arbs');
  $(arb ? 'replay-arbs' : 'replay-ev').setAttribute('aria-current','page');
  $('replay-dataset').onchange = event => {
    const next = new URL(location.href);
    next.searchParams.set('dataset', event.target.value);
    if (gameKey) {
      if (marketFamily) next.searchParams.set('family', marketFamily);
      else next.searchParams.delete('family');
      if (safeBack) {
        const previous = new URL(safeBack, location.origin);
        if (previous.pathname === '/replay') previous.searchParams.set('dataset', event.target.value);
        next.searchParams.set('back', previous.pathname + previous.search);
      }
    }
    location.assign(next);
  };
}
stake.value = readPreference('stake', '100');
if (!stake.checkValidity() || !stake.value) stake.value = '100';
const evFilterKey = 'ev-filters';
const filterKey = () => replay ? `replay-${dataset}-${browse ? 'odds' : arb ? 'arb' : 'ev'}-filters`
  : browse ? 'browse-filters' : phase === 'live' ? (arb ? 'live-arb-filters' : 'live-ev-filters')
    : arb ? 'arb-filters' : evFilterKey;
const cachedReturn = !gameKey ? readBrowseReturn() : null;
const returning = cachedReturn?.url === location.href && cachedReturn.restoreOnArrival;
const restored = window.history.state?.predictDesk || (returning ? cachedReturn.navigation : null);
if (returning) {
  window.history.replaceState({...window.history.state, predictDesk:restored}, '');
  try { sessionStorage.setItem(browseCacheKey, JSON.stringify({...cachedReturn, restoreOnArrival:false})); } catch {}
}
let saved;
try { saved = JSON.parse(readPreference(filterKey(), '{}')); } catch { saved = {}; }
saved ||= {};
if (!gameKey && restored?.filters) Object.assign(saved, restored.filters);
if (browse) {
  let ordinary = {};
  try { ordinary = JSON.parse(readPreference(evFilterKey, '{}')) || {}; } catch {}
  if (!replay) saved.basis ||= phase === 'live' ? 'reviewed' : ordinary.basis;
  for (const key of [...browseFilterFields, 'basis','last_known','alternates']) {
    if (route.has(key)) saved[key] = route.get(key);
  }
  if (gameKey) {
    for (const key of ['league','family','venue','search','day','period','time_from','time_to','game_state']) delete saved[key];
  }
}
if (phase) delete saved.game_state;
if (phase === 'pregame') delete saved.period;
if (phase === 'live' && !saved.basis) saved.basis = 'reviewed';
if (replay) {
  filters.elements.basis.querySelector('option[value="sportsbooks"]').remove();
  if (saved.basis === 'sportsbooks') saved.basis = dataset === 'retained' ? 'reviewed' : 'before';
  saved.group ||= 'offer'; saved.basis ||= 'before';
}
for (const key of ['search', 'day', 'sort', 'group', 'period', 'minimum', 'profit','basis','timezone','time_from','time_to','game_state']) {
  if (saved[key]) filters.elements[key].value = saved[key];
}
filters.elements.positive.checked = !browse && saved.positive === 'on';
filters.elements.last_known.checked = replay && browse && (route.get('last_known') || saved.last_known) === '1';
if (comparable) {
  // Old browse preferences stored the former default (all lines) even when
  // nobody touched the toggle. Start the new public default on main lines.
  $('alternates').checked = route.has('alternates') ? route.get('alternates') === '1' : saved.lines === 'all';
} else if (browse) {
  $('alternates').defaultChecked = true;
  $('alternates').checked = saved.alternates !== '0';
}
let marketFamily = gameKey && ['winner','spread','total'].includes(route.get('family')) ? route.get('family') : '';
let focusSelectedLine = Boolean(requestedLine);
function marketTabs() {
  if (!browse || !gameKey) return;
  const tabs = $('market-tabs');
  tabs.hidden = false;
  tabs.replaceChildren(...[['','All markets'],['winner','Winners'],['spread','Spreads'],['total','Totals']].map(([family, label]) => {
    const tab = button(label, () => {
      marketFamily = family;
      focusSelectedLine = false;
      marketTabs();
      const current = [...tabs.children].find(item => item.getAttribute('aria-pressed') === 'true');
      current?.focus({preventScroll:true});
      if (state.page) render(state.page);
    });
    tab.setAttribute('aria-pressed', String(marketFamily === family));
    return tab;
  }));
}
marketTabs();
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
  if (!replay) delete query.last_known;
  if (!arb) delete query.profit;
  if (!replay || browse) query.group = 'outcome';
  if (browse) {
    for (const key of ['positive','minimum','profit','sort']) delete query[key];
    query.browse_odds = '1';
    if (gameKey) {
      query.game_key = gameKey;
      if (route.get('game_source')) query.game_source = route.get('game_source');
      if (route.get('source_event')) query.source_event = route.get('source_event');
      if (!replay && route.get('game_capture')) query.game_capture = route.get('game_capture');
      if (requestedLine) query.line = requestedLine;
    }
  } else if (opportunityView) {
    if (!arb) query.ranked = '1';
    delete query.sort;
  }
  if (phase) {
    query.phase = phase;
    delete query.game_state;
    if (phase === 'pregame') delete query.period;
  }
  if (comparable) query.lines = $('alternates').checked ? 'all' : 'main';
  query.timezone = selectedZone();
  return query;
}

function position(offer, game) {
  const selection = offer.selection || {};
  const participant = game?.participants?.find(p => p.id === selection.participant)?.name || offer.participant || selection.label;
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
  const {offer, group, game, evidence, pairContext} = state.selected;
  const label = position(offer, game);
  $('trade-title').textContent = `${siteName(offer)} · ${label}`;
  const mode = state.selected.historical ? 'Saved capture · prices at inspection time' : replayMode();
  const leg = pairContext?.pair.legs.indexOf(offer.id);
  const pairFee = pairContext?.pair.retail_payoff?.legs?.[leg];
  const pairAcquisition = pairFee?.acquisition_usd ?? pairContext?.pair.inspection?.legs[leg]?.allocation_usd;
  $('trade-body').replaceChildren(tradeInspection(offer, group, evidence, {mode, position:label, basis:state.selected.basis,
    checkedAt:state.selected.checkedAt, pinned:state.selected.pinned, publication:state.selected.publication,
    pairLeg:!!pairContext, pairFee, pairAcquisition}));
  $('latest').hidden = replay;
  $('back-to-pair').hidden = !state.selected.pairContext;
}

let inspection;
function pushInspection(depth) {
  if (depth === 1) inspection = {id:crypto.randomUUID(), scrollY:window.scrollY, tableScrolls:matrixPositions(),
    scrollRestoration:window.history.scrollRestoration};
  window.history.scrollRestoration = 'manual';
  window.history.pushState({...window.history.state, predictInspection:{id:inspection.id, depth}}, '');
}

async function openTrade(offer, group, game, pairContext = null, opener = document.activeElement) {
  if (!dialog.open) releaseEvidence(state.selected?.lease);
  const parent = pairContext && {
    nodes:[...$('trade-body').childNodes], scrollTop:dialog.scrollTop,
    title:$('trade-title').textContent, note:$('trade-note').textContent, latestHidden:$('latest').hidden, opener
  };
  const previous = Boolean(state.previousReason || opener?.hasAttribute('data-expired-quote'));
  state.selected = {offer, group, game, opener, pairContext,
    basis:state.page?.basis || filters.elements.basis.value,
    checkedAt:previous ? Date.parse(state.page?.publication?.read_at) || Date.now() : Date.now(),
    pinned:previous, publication:pairContext?.publication ?? state.page?.publication};
  if (parent) {
    state.selected.parent = parent;
    if (inspection) pushInspection(2);
  } else if (!dialog.open) pushInspection(1);
  $('trade-note').textContent = '';
  tradeDetails();
  if (!dialog.open) dialog.showModal();
  else dialog.querySelector('form button').focus();
  dialog.scrollTop=0;
  const selected=state.selected;
  try {
    const pinned=await pinEvidence(offer, selected.basis);
    if(state.selected!==selected||!dialog.open){releaseEvidence(pinned.lease);return;}
    Object.assign(selected,pinned);
    const detail = pinned.evidence.desk_offer;
    if (detail) {
      selected.offer = {...detail, ...offer};
      if (offer.trade_fee_available === false && detail.trade_fee?.available) {
        selected.offer.trade_fee = {available:false, reason:'fee_outcome_not_published'};
      }
      if (selected.basis === 'sportsbooks' && offer.fair_odds === null) selected.offer.sportsbook = null;
    }
    tradeDetails();
  } catch {
    if(state.selected===selected&&dialog.open){
      selected.retentionError='Full evidence could not be loaded. Displayed prices and returns remain pinned.';
      $('trade-note').textContent=selected.retentionError;
      $('trade-body').querySelector('.inspection-loading')?.remove();
    }
  }
}

function openPair(pair, offers, group, game, opener = document.activeElement) {
  releaseEvidence(state.selected?.lease);
  releaseEvidence(state.selected?.pairContext?.lease);
  const context = {pair, publishedPair:pair, offers, group, game, opener, publication:state.page?.publication};
  renderPair(context);
  if (!dialog.open) {
    pushInspection(1);
    dialog.showModal();
  }
  dialog.scrollTop = 0;
  if (!replay && pair.evidence_result_id && !['pair_leg_stale_or_replaced', 'pair_settlement_unverified'].includes(pair.retail_payoff?.reason)) {
    context.reservation = reserveEvidence(pair.evidence_result_id).then(lease => {
      if (dialog.open && (state.selected === context || state.selected?.pairContext === context)) {
        context.lease = lease;
        return lease;
      }
      releaseEvidence(lease);
      return null;
    }).catch(() => null);
    if (!pair.inspection) loadPairDetails(context);
  }
  return context;
}

async function loadPairDetails(context) {
  const {publishedPair:pair} = context;
  try {
    const lease = await context.reservation;
    if (!lease || !dialog.open || state.selected !== context) throw Error('Evidence unavailable');
    const query = new URLSearchParams({layout:'desk', id:pair.id, result_id:pair.evidence_result_id, lease_id:lease.lease_id});
    const response = await fetch(`/api/comparison-snapshot/details?${query}`);
    if (!response.ok) throw Error('Evidence unavailable');
    const detail = await response.json();
    if (detail.id !== pair.id || detail.evidence_result_id !== pair.evidence_result_id || !detail.inspection) {
      throw Error('Evidence changed');
    }
    if (!dialog.open || state.selected !== context) return;
    const retail = pair.retail_payoff;
    const hydrated = {...pair, inspection:detail.inspection, settlement_payouts:detail.settlement_payouts,
      retail_payoff:retail.available || retail.reason === detail.retail_payoff?.reason
        ? detail.retail_payoff : {...retail, legs:[]}};
    for (const offer of detail.offers || []) {
      if (context.offers.has(offer.id)) {
        context.offers.set(offer.id, {...offer, ...context.offers.get(offer.id)});
      }
    }
    context.pair = context.publishedPair = hydrated;
    renderPair(context);
  } catch {
    if (dialog.open && state.selected === context) {
      $('trade-body').replaceChildren(el('p', 'This calculation could not be loaded.'));
      $('latest').hidden = false;
    }
  }
}

function renderPair(context) {
  const {pair, offers, group, game} = context;
  state.selected = context;
  $('trade-title').textContent = 'Pair payoff';
  $('trade-note').textContent = '';
  $('latest').hidden = replay || !pair.inspection;
  $('back-to-pair').hidden = true;
  const customSizing = !replay && pair.inspection && pair.evidence_result_id
    && pair.retail_payoff?.reason !== 'pair_fee_publication_pending';
  const mode = context.requestedStake ? 'Sized from the captured prices and fees' : replayMode();
  const body = $('trade-body');
  if (!pair.inspection && !replay && pair.evidence_result_id
      && !['pair_leg_stale_or_replaced', 'pair_settlement_unverified'].includes(pair.retail_payoff?.reason)) {
    body.replaceChildren(el('p', 'Loading the calculation…', 'desk-meta'));
    return;
  }
  body.replaceChildren(pairInspection(pair, offers, {group, game, position, mode,
    inspect: (offer, opener) => openTrade(offer, group, game, context, opener)}));
  if (customSizing) {
    const form = el('form', null, 'pair-sizing');
    const label = el('label', 'Total stake before fees ($) ');
    const amount = Object.assign(el('input'), {type:'number', min:'0.01', max:'1000000', step:'0.01',
      required:true, value:context.requestedStake ?? '100'});
    const calculate = el('button', 'Size this pair');
    const status = el('p');
    status.setAttribute('role', 'status');
    label.append(amount);
    form.append(label, calculate, status);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      calculate.disabled = true;
      status.textContent = 'Sizing the captured pair…';
      try {
        await sizePair(context, amount.value);
        if (dialog.open && state.selected === context) $('trade-body').querySelector('form input')?.focus();
      } catch {
        status.textContent = 'Could not size this capture. The previous calculation is still displayed.';
      } finally { calculate.disabled = false; }
    });
    body.prepend(form);
  }
}

async function sizePair(context, requestedStake) {
  const lease = await context.reservation;
  if (!lease) throw Error('Pair evidence unavailable');
  const {id, evidence_result_id} = context.pair;
  const query = new URLSearchParams({id, result_id:evidence_result_id, lease_id:lease.lease_id, stake:requestedStake});
  const response = await fetch(`/api/comparison-snapshot/details?${query}`);
  if (!response.ok) throw Error('Pair evidence unavailable');
  const {id:pairID, evidence_result_id:resultID, inspection, retail_payoff, score} = await response.json();
  if (pairID !== id || resultID !== evidence_result_id) throw Error('Pair evidence changed');
  if (dialog.open && state.selected === context) {
    context.requestedStake = requestedStake;
    context.pair = {...context.pair, inspection, retail_payoff, score};
    renderPair(context);
  }
}

async function openHistorical() {
  const capture = route.get('result_id');
  const id = route.get('selection');
  if (replay || !capture || !id) return;
  const basis = filters.elements.basis.value;
  let lease;
  try {
    const reservation = await fetch('/api/comparison-current/lease', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({result_id:capture})
    });
    if (!reservation.ok) throw Error('Capture unavailable');
    lease = await reservation.json();
    const query = new URLSearchParams({id, result_id:capture, layout:'desk', basis, lease_id:lease.lease_id});
    const detail = await fetch(`/api/comparison-snapshot/details?${query}`);
    if (!detail.ok) throw Error('Capture unavailable');
    const evidence = await detail.json();
    if (!evidence.desk_offer || evidence.row.id !== id) throw Error('Saved offer unavailable');
    if (dialog.open) { releaseEvidence(lease); return; }
    const {game_key, game_title, league, start_at, market} = evidence.row;
    state.selected = {offer:evidence.desk_offer, group:{game_key, game_title, league, start_at, market},
      basis, lease, evidence, historical:true, checkedAt:evidence.captured_at || evidence.desk_offer.captured_at};
    $('trade-note').textContent = '';
    tradeDetails();
    dialog.showModal();
  } catch {
    releaseEvidence(lease);
    $('notice').textContent = 'The saved offer could not be opened.';
  }
}

function returnToPair() {
  const {pairContext, lease, parent} = state.selected;
  releaseEvidence(lease);
  state.selected = pairContext;
  $('trade-title').textContent = parent.title;
  $('trade-note').textContent = parent.note;
  $('latest').hidden = parent.latestHidden;
  $('back-to-pair').hidden = true;
  $('trade-body').replaceChildren(...parent.nodes);
  parent.opener.focus({preventScroll:true});
  dialog.scrollTop = parent.scrollTop;
}

function dismissInspection() {
  const current = window.history.state?.predictInspection;
  if (inspection && current?.id === inspection.id) {
    if (!inspection.closing) {
      inspection.closing = true;
      window.history.back();
    }
  } else if (state.selected?.parent) returnToPair();
  else closeInspection();
}

dialog.querySelector('form[method="dialog"]').addEventListener('submit', event => {
  event.preventDefault();
  dismissInspection();
});
dialog.addEventListener('cancel', event => {
  event.preventDefault();
  dismissInspection();
});
$('back-to-pair').onclick = dismissInspection;

function clearInspectionEntry() {
  const {predictInspection, ...entry} = window.history.state || {};
  if (predictInspection) window.history.replaceState(entry, '');
}
// A reload can open directly at a modal entry whose in-memory capture is gone.
clearInspectionEntry();
window.addEventListener('popstate', event => {
  const marker = event.state?.predictInspection;
  if (!dialog.open || !inspection) {
    clearInspectionEntry();
    return;
  }
  inspection.closing = false;
  if (marker?.id !== inspection.id) closeInspection();
  else if (marker.depth === 1 && state.selected?.parent) returnToPair();
  else if (marker.depth === 2 && !state.selected?.parent) clearInspectionEntry();
});
async function releaseEvidence(lease){
  if(!lease)return;
  try{
    await fetch('/api/comparison-current/lease?'+new URLSearchParams({lease_id:lease.lease_id}), {
      method:'DELETE',
      headers:{'Content-Type':'application/json'},
      keepalive:true
    });
  }catch{}
}
async function reserveEvidence(result_id) {
  const response=await fetch('/api/comparison-current/lease',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({result_id})});
  if (!response.ok) throw Error('Evidence expired');
  return response.json();
}
async function pinEvidence(offer, basis){
  if (offer.live_native_desk || offer.live_aggregate_desk) {
    const query = new URLSearchParams({id:offer.id, layout:'desk', basis, phase:offer.game_state === 'live' ? 'live' : 'pregame'});
    const response = await fetch(`/api/comparison-current/selection?${query}`);
    if (!response.ok) throw Error('Price evidence unavailable');
    const {row, evidence} = await response.json();
    if (!evidence || row?.price_revision !== offer.price_revision ||
        row?.economic_revision !== offer.economic_revision) throw Error('Price or evidence changed');
    return {evidence:{...evidence, desk_offer:row}};
  }
  if(!offer.evidence_result_id)throw Error('Missing exact evidence');
  if (replay) {
    const query = new URLSearchParams({dataset, result_id:offer.evidence_result_id, id:offer.id});
    if (retainedResult) query.set('game_key', gameKey);
    const detail = await fetch(`/api/odds-replay/details?${query}`);
    if (!detail.ok) throw Error('Replay evidence unavailable');
    const evidence = await detail.json();
    if (evidence.row.id !== offer.id || evidence.row.price_revision !== offer.price_revision ||
        evidence.row.economic_revision !== offer.economic_revision) throw Error('Replay revision changed');
    return {evidence};
  }
  const lease=await reserveEvidence(offer.evidence_result_id);
  try{const detail=await fetch('/api/comparison-snapshot/details?'+new URLSearchParams({layout:'desk',basis,
    result_id:offer.evidence_result_id,id:offer.id,lease_id:lease.lease_id}));if(!detail.ok)throw Error();const evidence=await detail.json();
    if(evidence.row.id!==offer.id||evidence.row.price_revision!==offer.price_revision||evidence.row.economic_revision!==offer.economic_revision)throw Error();return {lease,evidence};
  }catch(error){releaseEvidence(lease);throw error;}
}

function browsingLink(label, group, className) {
  const destination = () => browseDestination(group);
  const action = link(label, destination(), className);
  if (group) action.dataset.gameLauncher = '';
  action.addEventListener('focus', () => { action.href = destination(); });
  action.addEventListener('click', event => {
    action.href = destination();
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    rememberView(group, action);
  });
  return action;
}

function browsePreferences() {
  return {...selections(), timezone:filters.elements.timezone.value,
    ...(replay ? {last_known:filters.elements.last_known.checked ? '1' : '0'} : {}),
    alternates:$('alternates').checked ? '1' : '0'};
}

function browseReturnRoute(selected) {
  const url = new URL(location.href);
  if (!replay) url.searchParams.delete('last_known');
  for (const key of [...browseFilterFields, 'basis','alternates', ...(replay ? ['last_known'] : [])]) {
    url.searchParams.set(key, selected[key] ?? '');
  }
  return url;
}

function updateBrowsePhaseLinks() {
  for (const value of ['pregame', 'live']) {
    const url = new URL(location.href);
    url.searchParams.set('phase', value);
    if (gameKey && safeBack) {
      const previous = new URL(safeBack, location.origin);
      previous.searchParams.set('phase', value);
      url.searchParams.set('back', previous.pathname + previous.search);
    }
    $(`phase-${value}`).href = url;
  }
}

function browseDestination(group) {
  const query = new URLSearchParams();
  const selected = selections();
  if (phase) query.set('phase', phase);
  if (comparable) query.set('alternates', $('alternates').checked ? '1' : '0');
  if (filters.elements.last_known.checked) query.set('last_known', '1');
  if (group) {
    query.set('game_key', group.game_key);
    query.set('matchup', group.game_title);
    if (group.game_source) query.set('game_source', group.game_source);
    if (group.source_event) query.set('source_event', group.source_event);
    if (!replay) {
      const sealed = group.offers.find(offer => offer.evidence_result_id && !offer.live_native_desk);
      if (sealed) query.set('game_capture', sealed.evidence_result_id);
    }
    query.set('basis', selected.basis);
    query.set('timezone', filters.elements.timezone.value);
    if (!browse && (group.game_line_id || group.id)) {
      query.set('line', group.game_line_id || group.id);
      const offer = group.pairs ? group.offers.find(item => item.id === group.pairs[0].legs[0]) : group.offers[0];
      if (offer) {
        query.set('family', offer.market.market);
        query.set('line_label', position(offer));
      }
    } else if (selected.family && selected.family.split(',').length === 1) {
      query.set('family', selected.family);
    }
    if (browse) {
      query.set('alternates', $('alternates').checked ? '1' : '0');
      if (replay) query.set('last_known', filters.elements.last_known.checked ? '1' : '0');
    }
  } else {
    for (const key of browseFilterFields) {
      if (selected[key]) query.set(key, selected[key]);
    }
  }
  const returnRoute = browse && !gameKey ? browseReturnRoute(browsePreferences()) : new URL(location.href);
  query.set('back', returnRoute.pathname + returnRoute.search);
  return replay ? replayURL(group ? 'game' : 'odds') + '&' + query : `${group ? '/game' : '/browse-odds'}?${query}`;
}

function readBrowseReturn() {
  try { return JSON.parse(sessionStorage.getItem(browseCacheKey)); } catch { return null; }
}

function matrixPositions() {
  return [...$('results').querySelectorAll('.odds-card')].map(card =>
    [card.dataset.gameKey, card.querySelector('.odds-scroll')?.scrollLeft || 0]);
}

function restoreMatrices(positions) {
  const byGame = new Map(positions || []);
  for (const card of $('results').querySelectorAll('.odds-card')) {
    const table = card.querySelector('.odds-scroll');
    if (table && byGame.has(card.dataset.gameKey)) table.scrollLeft = byGame.get(card.dataset.gameKey);
  }
}

function disclosureStates() {
  return new Map([...$('results').querySelectorAll('details[data-id]')].map(item => [item.dataset.id, item.open]));
}

function rememberView(group, action) {
  const target = new URL(action.href);
  const returnRoute = window.PredictUI.localURL(target.searchParams.get('back'));
  const navigation = {offset:state.offset, groupId:group?.id, gameKey:group?.game_key,
    browseId:state.page?.browse_id, openerHref:action.href, sourceEvent:target.searchParams.get('source_event'),
    openerTop:action.getBoundingClientRect().top, scrollY:window.scrollY,
    filters:browsePreferences(), tableScrolls:matrixPositions(), disclosures:[...disclosureStates()]};
  window.history.scrollRestoration = 'manual';
  window.history.replaceState({...window.history.state, predictDesk:navigation}, '', returnRoute?.href || location.href);
  try { sessionStorage.setItem(browseCacheKey, JSON.stringify({url:location.href, navigation})); } catch {}
}

function cardContext(games, gameTitle = null) {
  return {
    basis:pageBasis(), clock, phase,
    checkedAt:state.page?.replay?.captured_at ?? state.page?.publication?.read_at, gameTitle, mode:replayMode(),
    compact:comparable, summary:!replay, showGameLink:!gameKey, stableVenues:!replay,
    position:offer => position(offer),
    gameLink:group => browsingLink('Open game ↗', group, 'opportunity-link'),
    inspectOffer:(offer, group, opener) => openTrade(offer, group, games.get(group.game_key), null, opener),
    inspectPair:(pair, offers, group, opener) => {
      if (pairResultsReady()) openPair(pair, offers, group, games.get(group.game_key), opener);
    }
  };
}

const pageBasis = () => state.page?.basis || filters.elements.basis.value;

function pairResultsReady() {
  return !replay || stake.validity.valid && !!stake.value && Number(stake.value) === state.renderedStake;
}

function refreshStatus() {
  const mode = !filters.elements.time_to.validity.valid ? 'Correct the time window to refresh.'
    : arb && state.page && !pairResultsReady()
      ? (stake.validity.valid && stake.value ? 'Updating payoff for the entered stake…' : 'Enter a valid stake to calculate the payoff.')
    : replay ? (state.request ? 'Loading replay…' : 'Replay clock is fixed.')
    : state.request ? 'Checking for updates…' : '';
  $('refresh-status').textContent = mode;
  $('refresh-status').classList.toggle('sr-only', !(arb && state.page && !pairResultsReady()));
  $('refresh-list').disabled = !!state.request || !filters.elements.time_to.validity.valid;
  if (arb) for (const button of $('results').querySelectorAll('[data-pair-id]')) button.disabled = !pairResultsReady();
}

function emptyResults(page, publication) {
  const empty = el('section', null, 'desk-empty');
  const actions = el('div', null, 'desk-empty-actions');
  const runtime = publication.data_runtime;
  const issue = !replay && collectionIssue(runtime);
  const {positive, minimum, profit} = filters.elements;
  const thresholds = minimum.value || (arb && profit.value);
  const clearReturns = button('Clear return filters', () => {
    positive.checked = false;
    minimum.value = profit.value = '';
    applyFilters();
    $('open-filters').focus();
  });
  let title, detail;
  if (replay && page.state === 'initializing') {
    title = 'This saved capture is unavailable';
    actions.append(link('Browse current odds', '/browse-odds'));
  } else if (issue && !page.price_preview?.length) {
    [title, detail] = issue;
    if (!browse) actions.append(browsingLink('Browse odds ↗'));
  } else if (!replay && page.price_preview?.length) {
    title = page.price_preview.some(group => group.offers?.some(offer => offer.current))
      ? 'Current prices' : 'Last known prices';
    detail = page.calculation_reason || 'No EV comparisons qualify for these filters yet.';
    actions.append(browsingLink('Browse odds ↗'));
  } else if (page.state === 'initializing' && !publication.retained_prices) {
    title = 'No prices have loaded yet';
    detail = 'The desk will update after the data service publishes its first prices.';
  } else if (comparable && (browse || !positive.checked && !thresholds) && !(browse && gameKey)) {
    title = browse ? 'No matching odds' : 'No matching EV comparisons';
    detail = browse ? 'Try another matchup, market, or time window.'
      : page.calculation_reason || 'No verified after-fee EV matches these filters.';
    if (!$('alternates').checked) actions.append(button('Show alternate lines', () => {
      $('alternates').checked = true;
      applyFilters();
      $('alternates').focus();
    }));
  } else if (browse) {
    title = gameKey ? 'No prices available for this matchup' : 'No prices match these filters';
    if (!replay && page.retained_game?.lifecycle) {
      detail = evidenceReason(page.retained_game.lifecycle, 'The matchup is outside this phase of the current slate.');
    }
  } else if (page.ranked_group_count && (positive.checked || thresholds)) {
    title = thresholds ? 'No results meet the return filters' : 'No positive results';
    detail = 'Clear the return filters to see evaluated results.';
    actions.append(clearReturns);
  } else if (!page.calculation_reason && page.matched_offer_count === 0 && publication.current_prices
      && (replay || filters.elements.search.value || $('filter-count').textContent !== '0')) {
    title = 'No offers match these filters';
    detail = 'Try another matchup or broaden your selection.';
    actions.append(button('Edit filters', () => $('open-filters').click()));
  } else if (arb) {
    title = 'No arbitrage calculations available';
    const reason = page.pair_status || {};
    detail = page.calculation_reason || (reason.finance_pending ? 'An opposing pair is waiting for calculation publication.'
      : page.eligible_pair_count ? 'Current pairs are missing applicable fees or settlement evidence.'
      : page.matched_offer_count ? 'The current prices have no verified opposing pair.'
        : `No current prices are available${phase === 'live' ? ' for live games' : phase === 'pregame' ? ' for pregame markets' : ''}.`);
  } else {
    title = 'No EV estimates available';
    detail = page.calculation_missing?.length ? evidenceReason(page.calculation_missing, page.calculation_reason) :
      page.calculation_reason || (page.matched_offer_count ? 'Current prices are missing an eligible sportsbook reference for the selected basis.'
        : `No current prices are available${phase === 'live' ? ' for live games' : phase === 'pregame' ? ' for pregame markets' : ''}.`);
  }
  if (!replay && page.retained_game) {
    const capture = page.retained_game;
    const query = new URLSearchParams({view:'game', dataset:'retained', game_key:capture.game_key,
      result_id:capture.result_id, matchup:linkedTitle || $('title').textContent,
      basis:filters.elements.basis.value, family:marketFamily, last_known:'1', return_phase:phase,
      back:location.pathname + location.search});
    if (requestedLine) query.set('line', requestedLine);
    actions.append(link('Open saved game', `/replay?${query}`));
  }
  empty.append(el('h2', title));
  if (detail) empty.append(el('p', detail, 'desk-note'));
  if (actions.hasChildNodes()) empty.append(actions);
  return empty;
}

function groupsByGame(rows) {
  const groups = new Map();
  for (const row of rows) {
    if (row.withdrawn) continue;
    if (!groups.has(row.game_key)) groups.set(row.game_key, []);
    groups.get(row.game_key).push(row);
  }
  return groups;
}

function rankedCard(group, games) {
  const context = cardContext(games);
  context.game = games.get(group.game_key);
  context.position = offer => position(offer, context.game);
  return evCard(group, context);
}

function rankedGame(gameRows, games, disclosures) {
  const [first, ...rest] = gameRows;
  const card = rankedCard(first, games);
  card.dataset.gameKey = first.game_key;
  if (!rest.length) return card;
  const details = el('details', null, 'ranked-outcomes');
  details.dataset.id = `ev:${first.game_key}`;
  details.append(el('summary', `${rest.length} more ${rest.length === 1 ? 'outcome' : 'outcomes'}`));
  const addCards = () => {
    if (details.open && details.childElementCount === 1) details.append(...rest.map(row => rankedCard(row, games)));
  };
  details.open = disclosures.get(details.dataset.id) || rest.some(row => row.id === restoreLocation?.groupId);
  addCards();
  details.addEventListener('toggle', addCards);
  card.append(details);
  return card;
}

function render(page) {
  const results = $('results');
  const disclosures = new Map([...disclosureStates(), ...restoreLocation?.disclosures || []]);
  const tableScrolls = matrixPositions();
  const games = new Map((page.games || []).map(game => [game.game_key, game]));
  const rows = page.rows || [];
  const total = page.total || 0;
  const selectedLine = focusSelectedLine ? page.selected_line_id || requestedLine : null;
  if (gameKey) {
    const resolved = page.selected_game_key || gameKey;
    const matchup = games.get(resolved);
    const first = rows.find(row => !row.withdrawn && row.game_key === resolved);
    const title = first?.game_title || linkedTitle || matchup?.title;
    if (title) {
      $('title').textContent = title;
      const start = first?.start_at || matchup?.start_at;
      $('desk-subtitle').textContent = start ? `${first?.league || matchup?.league} · ${clock(start)}` : '';
      $('desk-subtitle').hidden = !start;
      document.title = `Predict · ${title}`;
    }
  }
  const publication = page.publication || {};
  const notice = [];
  if (replay && page.replay?.captured_at) notice.push(`Captured ${clock(page.replay.captured_at)}.`);
  if (!replay) {
    if (rows.some(row => !row.withdrawn) || page.price_preview?.length) {
      const issue = collectionIssue(publication.data_runtime);
      if (issue) notice.push(`${issue[0]}. ${issue[1]}`);
    }
    if (!publication.data_runtime?.stopped) notice.push(...sourceNotices(publication));
  }
  if (state.resetReason) notice.push(state.resetReason);
  $('notice').textContent = notice.join(' ');
  results.replaceChildren();
  if (arb && page.pair_status?.withheld) {
    const withheld = el('p', `${page.pair_status.withheld} pairing(s) lack a payoff under these filters. `, 'desk-note');
    withheld.append(button('Show unavailable pairings', () => {
      for (const key of ['positive', 'minimum', 'profit']) {
        if (key === 'positive') filters.elements[key].checked = false;
        else filters.elements[key].value = '';
      }
      applyFilters();
    }));
    results.append(withheld);
  }
  if (selectedLine && !page.selected_line_id && !rows.some(row => row.id === selectedLine && !row.withdrawn)) {
    results.append(el('p', `${linkedLine || 'The selected line'} is unavailable for this matchup in the selected view.`, 'desk-note selected-line-unavailable'));
  }
  const preview = rows.length ? [] : (page.price_preview || []);
  const matrixRows = browse ? rows : preview;
  if (matrixRows.length) {
    if (preview.length) results.append(emptyResults(page, publication));
    const groups = groupsByGame(matrixRows);
    const compactGames = !replay && !gameKey && page.row_kind === 'games' && total > 3;
    for (const [key, gameRows] of groups) {
      const first = gameRows[0];
      const context = cardContext(games, !gameKey && first.game_title);
      context.position = offer => position(offer, games.get(key));
      const id = `odds:${key}`;
      const disclosure = compactGames ? {id, open:disclosures.get(id) ?? key === groups.keys().next().value} : null;
      results.append(gameMatrix(gameRows, context, {includeAlternates:$('alternates').checked, market:marketFamily,
        selectedLine, disclosure}));
    }
    if (!groups.size) results.append(emptyResults(page, publication));
  } else if (!arb && page.row_kind === 'games' && rows.length) {
    for (const gameRows of groupsByGame(rows).values()) results.append(rankedGame(gameRows, games, disclosures));
    if (!results.firstChild) results.append(emptyResults(page, publication));
  } else if (rows.length) {
    for (const group of rows) {
      if (group.withdrawn) {
        results.append(el('p', `${group.game_title}: ${group.reason}`, 'desk-note'));
        continue;
      }
      const context = cardContext(games);
      context.game = games.get(group.game_key);
      context.position = offer => position(offer, context.game);
      results.append(arb ? arbCard(group, context, disclosures.get(group.id)) : evCard(group, context));
    }
  } else {
    results.append(emptyResults(page, publication));
  }
  restoreMatrices(tableScrolls);
  updateMatrixCues(results);
  const shown = page.page_count ?? rows.length;
  const unit = page.row_kind === 'games' ? 'games' : 'results';
  $('page-range').textContent = shown ? `${state.offset + 1}–${state.offset + shown} of ${total} ${unit}` : '';
  $('previous').disabled = state.offset === 0;
  $('next').disabled = state.offset + shown >= total;
  $('previous').parentElement.hidden = !!gameKey || !total;
}

if (opportunityView) {
  const action = browsingLink('Find my game ↗', null, 'desk-action');
  action.id = 'browse-link';
  $('browse-link').replaceWith(action);
}

let restoreLocation = restored || (gameKey && requestedLine ? {groupId:requestedLine} : null);

function restoreLocationAfterLoad() {
  if (!restoreLocation) return;
  const {openerTop, groupId, gameKey:anchorGame, openerHref, sourceEvent, scrollY, tableScrolls} = restoreLocation;
  restoreLocation = null;
  if (window.history.state?.predictDesk) {
    const {predictDesk, ...entry} = window.history.state;
    window.history.replaceState(entry, '');
  }
  restoreMatrices(tableScrolls);
  const targetId = (gameKey && state.page?.selected_line_id) || groupId;
  const row = targetId && [...$('results').querySelectorAll('[data-group-id]')]
    .find(item => item.dataset.groupId === targetId);
  const card = [...$('results').querySelectorAll('.odds-card')].find(item =>
    item.dataset.gameKey === anchorGame || sourceEvent && item.dataset.sourceEvent === sourceEvent);
  const opener = openerHref && [...document.querySelectorAll('main a')]
    .find(item => item.href === openerHref && !item.hidden);
  const target = opener || (row?.closest('.odds-card') || card || row)?.querySelector('[data-game-launcher]')
    || row?.querySelector('a,button');
  if (target && openerTop != null && state.page?.anchor_state !== 'removed') {
    window.scrollBy(0, target.getBoundingClientRect().top - openerTop);
  }
  else if (scrollY != null) window.scrollTo(0, scrollY);
  else row?.scrollIntoView({block:'nearest'});
  if (target && state.page?.anchor_state !== 'removed') target.focus({preventScroll:true});
  else if (openerHref) {
    const results = $('results');
    const nearby = [...results.querySelectorAll('[data-game-launcher], .opportunity-card a')]
      .sort((a, b) => Math.abs(a.getBoundingClientRect().top - (openerTop ?? 0))
                    - Math.abs(b.getBoundingClientRect().top - (openerTop ?? 0)))[0];
    const heading = results.querySelector('h2');
    if (heading) heading.tabIndex = -1;
    (nearby || heading || $('refresh-list')).focus({preventScroll:true});
  }
}

async function fetchPage(query, signal) {
  window.PredictDeskStarted = true;
  if (!replay) {
    for (const key of [...query.keys()]) if (!query.get(key)) query.delete(key);
    if (!['day', 'time_from', 'time_to'].some(key => query.has(key))) query.delete('timezone');
    query.sort();
  }
  const url = `${endpoint}?${query}`;
  const landing = window.PredictDeskLanding;
  if (landing) {
    delete window.PredictDeskLanding;
    if (landing.url === url) {
      signal.addEventListener('abort', () => landing.controller.abort(), {once:true});
      const initial = await landing.promise;
      if (initial) return initial;
    } else landing.controller.abort();
  }
  const response = await fetch(url, {signal});
  if (!response.ok) throw Error('Unavailable');
  return response.json();
}

function matchesInputs(stakeValue, signature) {
  return (!replay || stakeValue === stake.value) && signature === JSON.stringify(selections());
}

let resultPointer = null;
$('results').addEventListener('pointerdown', event => { resultPointer = event.pointerId; });
for (const type of ['pointerup','pointercancel']) {
  window.addEventListener(type, event => {
    if (event.pointerId === resultPointer) resultPointer = null;
  }, {capture:true});
}
window.addEventListener('blur', () => { resultPointer = null; });
window.addEventListener('resize', () => updateMatrixCues($('results')));
const usingResults = () => resultPointer != null || $('results').contains(document.activeElement)
  || !!$('results').querySelector(':popover-open');

function applyDeskFeatures(page) {
  if (replay || !page.features) return;
  liveEnabled = page.features.live_enabled === true;
  if (!liveEnabled && phase === 'live' && page.phase === 'pregame') {
    phase = 'pregame';
    filters.elements.period.value = '';
    route.delete('phase');
    const url = new URL(location.href);
    url.searchParams.delete('phase');
    if (safeBack) {
      const destination = new URL(safeBack, location.origin);
      if (destination.searchParams.get('phase') === 'live') destination.searchParams.delete('phase');
      safeBack = destination.pathname + destination.search;
      url.searchParams.set('back', safeBack);
    }
    window.history.replaceState(window.history.state, '', url.href);
  }
  updatePhaseView();
}

function previousResults(message = '') {
  state.previousReason = message;
  const notice = $('previous-results');
  if (notice.textContent !== message) notice.textContent = message;
  notice.hidden = !message;
}

function expireResultValues() {
  if (replay) return;
  const now = Date.now();
  for (const value of $('results').querySelectorAll('[data-calculation-deadline]')) {
    if (Number(value.dataset.calculationDeadline) > now || value.hasAttribute('data-expired-calculation')) continue;
    value.setAttribute('data-expired-calculation', '');
    if (value.dataset.quoteCalculation) {
      const price = value.parentElement;
      price.setAttribute('aria-label', `${price.dataset.quoteDescription}, Calculation expired`);
    }
  }
  for (const price of $('results').querySelectorAll('[data-quote-deadline]:not([data-expired-quote])')) {
    if (Number(price.dataset.quoteDeadline) > now) continue;
    price.setAttribute('data-expired-quote', '');
    if (price.dataset.quoteDescription) price.setAttribute('aria-label', `${price.dataset.quoteDescription}, Last known price`);
    price.append(el('small', 'Last known', 'quote-freshness'));
  }
}
$('results').addEventListener('toggle', () => queueMicrotask(expireResultValues), true);

function visibleAnchor() {
  const scrollY = window.scrollY;
  const candidates = [...$('results').children].filter(item => item.dataset.gameKey || item.dataset.groupId);
  const visible = candidates.find(item => {
    const {top, bottom} = item.getBoundingClientRect();
    return bottom > 0 && top < window.innerHeight;
  });
  const item = visible || candidates[0];
  return {scrollY, top:visible?.getBoundingClientRect().top, gameKey:item?.dataset.gameKey,
    groupId:item?.dataset.groupId || item?.querySelector('[data-group-id]')?.dataset.groupId};
}

function restoreAnchor(anchor) {
  if (!anchor) return;
  const item = [...$('results').children].find(child => anchor.gameKey
    ? child.dataset.gameKey === anchor.gameKey : child.dataset.groupId === anchor.groupId);
  if (item && anchor.top != null) window.scrollBy(0, item.getBoundingClientRect().top - anchor.top);
  else window.scrollTo(0, anchor.scrollY);
}

function resultSignature(page) {
  const stripReadClock = rows => rows?.map(row => ({...row, offers:row.offers?.map(offer => {
    if (!offer.live_native_desk && !offer.live_aggregate_desk) return offer;
    const {captured_at, ...stable} = offer;
    return stable;
  })}));
  const {data_runtime:runtime = {}, sources} = page.publication || {};
  return JSON.stringify([stripReadClock(page.rows), stripReadClock(page.price_preview), page.games, page.retained_game,
    page.total, page.page_count, page.offset, page.pair_status, page.calculation_reason, page.calculation_missing,
    page.state, page.basis, page.phase, page.anchor_state, page.selected_line_id, page.selected_game_key,
    page.ranked_group_count, page.matched_offer_count, runtime.stopped, runtime.healthy, runtime.reason, runtime.paused_sources,
    Object.values(sources || {}).map(source => [source.state, source.reason_code])]);
}

async function load(offset = state.offset, {background = false, freshMembership = false, anchor = null} = {}) {
  if (!filters.checkValidity() || !stake.value) return;
  if (background && state.request) return;
  state.request?.abort();
  const controller = new AbortController(); state.request = controller; refreshStatus();
  const requestStake = replay ? stake.value : '100';
  const selected = selections();
  const requestFilters = JSON.stringify(selected);
  const query = new URLSearchParams({...selected, layout: 'desk', view: arb ? 'arbs' : 'ev',
    offset:freshMembership ? 0 : offset, limit:pageLimit});
  if (replay) query.set('stake', requestStake);
  else query.set('summary', '1');
  if (replay) query.set('dataset', dataset);
  if (retainedResult) query.set('result_id', retainedResult);
  const browseId = (state.query === requestFilters ? state.page?.browse_id : null) ?? restoreLocation?.browseId;
  if (!replay && !freshMembership && browseId && (offset || background || restoreLocation?.browseId)) query.set('browse_id', browseId);
  const locator = restoreLocation || (freshMembership && anchor);
  if (!gameKey && locator && (locator.groupId || locator.gameKey)) {
    query.set('locate', locator.groupId || locator.gameKey);
    if (locator.gameKey) query.set('locate_game', locator.gameKey);
  }
  if (!state.page) $('notice').textContent = 'Loading prices…';
  try {
    const page = await fetchPage(query, controller.signal);
    if (controller.signal.aborted || !matchesInputs(requestStake, requestFilters)
        || background && (dialog.open || usingResults())) return;
    const emptyPage = !page.rows?.some(row => !row.withdrawn) && !page.price_preview?.length;
    if (page.state === 'page_changed' || query.has('browse_id') && emptyPage && (page.total || page.anchor_state === 'removed')) {
      if (freshMembership) throw Error('Browsing order unavailable');
      const reason = page.reason || 'The comparison order changed.';
      history.record('browsing_reset', {reason});
      state.resetReason = reason;
      if (restoreLocation) {
        restoreLocation.offset = 0;
        restoreLocation.browseId = null;
      }
      state.request = null;
      return load(0, {background, freshMembership:true, anchor:anchor || visibleAnchor()});
    }
    if (page.anchor_state === 'removed') {
      state.resetReason = 'The previous game or line is no longer in these results.';
    } else if (page.anchor_state === 'game') {
      state.resetReason = 'The previous line left these results. Other prices for the game are shown.';
    }
    if (gameKey && page.rows?.length && page.total > (page.page_count ?? page.rows.length)) {
      const rows = new Map(page.rows.map(row => [row.id, row]));
      let seen = page.page_count ?? page.rows.length;
      while (seen < page.total) {
        query.set('offset', seen);
        if (page.browse_id) query.set('browse_id', page.browse_id);
        const next = await fetchPage(query, controller.signal);
        if (next.state === 'page_changed' || !next.rows?.length) {
          throw Error('Game prices changed during read');
        }
        for (const row of next.rows) rows.set(row.id, row);
        seen += next.page_count ?? next.rows.length;
      }
      page.rows = [...rows.values()];
    }
    if (controller.signal.aborted || !matchesInputs(requestStake, requestFilters)
        || background && (dialog.open || usingResults())) return;
    applyDeskFeatures(page);
    const prior = background && !restoreLocation ? anchor || visibleAnchor() : anchor;
    const signature = resultSignature(page);
    const repaint = !background || !state.page || state.renderSignature !== signature || state.resetReason;
    state.page = page;
    state.query = JSON.stringify(selections());
    state.renderSignature = signature;
    state.renderedStake = Number(requestStake);
    state.offset = page.offset ?? (freshMembership ? 0 : offset);
    previousResults();
    if (repaint) {
      render(page);
      restoreAnchor(prior);
    }
    expireResultValues();
    state.resetReason = null;
    restoreLocationAfterLoad();
    history.observe(page, selections());
    checkSelection();
  } catch (error) {
    if (!controller.signal.aborted && error.name !== 'AbortError') {
      if (state.page && !replay) previousResults('Could not check the latest prices. Showing the previous results.');
      else $('notice').textContent = replay ? 'Replay could not be loaded. Refresh the list to retry.'
        : 'Prices could not be loaded. Refresh the list to retry.';
      history.record('display_gap',{reason:'local_read_failed'});
    }
  } finally {
    if (state.request === controller) {
      state.request = null;
      refreshStatus();
      scheduleUpdates();
    }
  }
}

const panel = $('filter-panel');
$('open-filters').onclick = () => panel.showModal();
$('close-filters').onclick = () => panel.close();
panel.addEventListener('close', () => restoreFocus($('open-filters')));
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
    add(`${filters.elements.time_from.value || '00:00'}–${filters.elements.time_to.value || '24:00'} ${selectedZone().replaceAll('_', ' ')}`,
      () => filters.elements.time_from.value = filters.elements.time_to.value = '');
  }
  if (filters.elements.positive.checked) add('Positive only', () => filters.elements.positive.checked = false);
  if (replay && filters.elements.sort.value === 'start') add('Soonest start', () => filters.elements.sort.value = 'return');
  if (filters.elements.timezone.value && !filters.elements.time_from.value && !filters.elements.time_to.value) {
    add(filters.elements.timezone.selectedOptions[0].textContent, () => filters.elements.timezone.value = '');
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
  clearTimeout(debounce);
  state.request?.abort();
  if (!filters.checkValidity() || !stake.value) return;
  if (browse && !gameKey) saveBrowsePreferences();
  else if (!gameKey) savePreference(filterKey(), JSON.stringify({...selections(), timezone:filters.elements.timezone.value}));
  if (arb && replay) savePreference('stake', stake.value);
  if (browse && !replay) {
    let ordinary = {};
    try { ordinary = JSON.parse(readPreference(evFilterKey, '{}')) || {}; } catch {}
    savePreference(evFilterKey, JSON.stringify({...ordinary, basis:filters.elements.basis.value}));
  }
  debounce = setTimeout(() => load(0), 240);
}

function saveBrowsePreferences() {
  const chosen = browsePreferences();
  savePreference(filterKey(), JSON.stringify(chosen));
  // Keep this history entry current even if the user leaves by a different link.
  const {predictDesk, ...otherState} = window.history.state || {};
  window.history.replaceState(otherState, '', browseReturnRoute(chosen));
  if (!replay) updateBrowsePhaseLinks();
}
filters.addEventListener('submit', event => event.preventDefault());
filters.addEventListener('input', applyFilters);
filters.elements.basis.disabled = false;
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
$('refresh-list').onclick = () => {
  const sameFilters = state.query === JSON.stringify(selections());
  const anchor = sameFilters && state.offset ? visibleAnchor() : null;
  load(sameFilters ? state.offset : 0, {freshMembership:!!state.page?.browse_id && (!state.offset || !!anchor), anchor});
};
document.addEventListener('focusin', refreshStatus);
document.addEventListener('focusout', () => queueMicrotask(refreshStatus));
$('previous').onclick = () => load(Math.max(0, state.offset - pageLimit));
$('next').onclick = () => load(state.offset + (state.page?.page_count ?? pageLimit));
$('alternates').addEventListener('input', event => {
  if (comparable) return; // the form handler reloads server-side membership
  event.stopPropagation();
  if (browse && !gameKey) saveBrowsePreferences();
  if (state.page) render(state.page);
});
function pairIdentity(context) {
  const {publishedPair:pair, offers} = context;
  const payoff = pair.retail_payoff;
  const fees = payoff.legs?.map(leg => [leg.available, leg.classification, leg.quantity, leg.acquisition_usd,
    leg.at_fill_usd, leg.settlement_usd, leg.receipts_usd]);
  return JSON.stringify([pair.id, pair.legs.map(id => {
    const offer = offers.get(id);
    return [offer.id, offer.price_revision, offer.economic_revision, offer.odds, offer.current];
  }),
    payoff.available, payoff.reason, payoff.funding_usd, payoff.states, payoff.sizing, fees, pair.score]);
}

async function readPair(selection) {
  const query = new URLSearchParams({
    layout:'desk', view:'arbs', game_key:selection.group.game_key,
    family:selection.group.market.market, period:selection.group.market.period, limit:pageSize
  });
  if (phase) query.set('phase', phase);
  const ids = [...selection.pair.legs].sort().join('\u001f');
  for (let offset = 0; ; offset += pageSize) {
    query.set('offset', offset);
    const page = await fetchPage(query);
    const group = page.rows?.find(row => row.id === selection.group.id);
    const pair = group?.pairs.find(item => [...item.legs].sort().join('\u001f') === ids && item.retail_payoff?.available);
    if (pair) return {pair, publishedPair:pair, group, offers:new Map(group.offers.map(offer => [offer.id, offer])),
      game:page.games?.find(item => item.game_key === group.game_key)};
    if (group || !page.total || offset + pageSize >= page.total) return null;
    if (page.browse_id) query.set('browse_id', page.browse_id);
  }
}

async function adoptPair(selection, isActive) {
  const next = await readPair(selection);
  if (!isActive()) return;
  if (!next) {
    adoptionNotice(selection, phase === 'pregame' && Date.parse(selection.group.start_at) <= Date.now()
      ? 'Scheduled start passed. The pregame pair remains pinned.'
      : 'These legs no longer have a current modeled payoff. The earlier calculation is still pinned.');
    return;
  }
  const confirmed = await readPair(selection);
  if (!isActive()) return;
  if (!confirmed || pairIdentity(next) !== pairIdentity(confirmed)
      || !confirmed.pair.legs.every(id => selectionCurrent(confirmed.offers.get(id)))) {
    adoptionNotice(selection, 'The pair changed during adoption. The earlier calculation is still pinned.');
    return;
  }
  if (pairIdentity(selection) === pairIdentity(confirmed)) {
    showRefreshResult(selection, 'No newer pair inputs found. The displayed calculation is unchanged.');
    return;
  }
  const replacement = openPair(confirmed.pair, confirmed.offers, confirmed.group, confirmed.game, selection.opener);
  if (selection.requestedStake) {
    try { await sizePair(replacement, selection.requestedStake); }
    catch {
      if (dialog.open && state.selected === replacement) showRefreshResult(replacement, 'Updated both legs. The published payoff is shown while custom sizing is unavailable.');
      return;
    }
  }
  if (dialog.open && state.selected === replacement) showRefreshResult(replacement, 'Updated both legs and the payoff.');
}

function showRefreshResult(selection, message) {
  selection.refreshMessage = message;
  $('trade-note').textContent = message;
}

function adoptionNotice(selection, message) {
  selection.adoptionNotice = true;
  $('trade-note').textContent = message;
  if (selection.offer) pinSelectionStatus(selection);
}

function pinSelectionStatus(selection) {
  selection.pinned = true;
  markPinned($('trade-body'), selection.pinned);
}

function expireInspection() {
  const selected = state.selected;
  if (!replay && dialog.open && selected?.offer && !selected.historical && !selectionCurrent(selected.offer)) {
    pinSelectionStatus(selected);
  }
}

$('latest').onclick = async () => {
  const latest = $('latest');
  const selection = state.selected;
  selection.adoptionNotice = false;
  selection.refreshMessage = '';
  latest.disabled = true;
  $('trade-note').textContent = 'Checking latest price…';
  const isActive = () => dialog.open && state.selected === selection;
  try {
    if (selection.pair) {
      await adoptPair(selection, isActive);
      return;
    }
    const query = new URLSearchParams({id:selection.offer.id, layout:'desk', basis:selection.basis});
    if (phase) query.set('phase', phase);
    const next = await pinLatestSelection({
      read: async () => {
        const response = await fetch(`/api/comparison-current/selection?${query}`);
        if (!response.ok) throw Error('Unavailable');
        const {row} = await response.json();
        return selection.offer.value != null && row?.value == null ? null : row;
      },
      pin: offer => pinEvidence(offer, selection.basis), release: releaseEvidence, isActive
    });
    if (!isActive()) { if (next.state === 'ready') releaseEvidence(next.lease); return; }
    if (next.state === 'unavailable') {
      adoptionNotice(selection, phase === 'pregame' && Date.parse(selection.group.start_at) <= Date.now()
        ? 'Scheduled start passed. The pregame capture remains pinned.'
        : 'No current replacement for this inspection. The earlier capture remains pinned.');
      return;
    }
    if (next.state === 'changed') {
      adoptionNotice(selection, 'The price, fee, or reference changed during adoption. The earlier inspection is still pinned.');
      return;
    }
    if (next.state !== 'ready') return;
    const {offer, evidence, lease} = next;
    const unchanged = selectionIdentity(offer) === selectionIdentity(selection.offer);
    if (unchanged && !selection.pinned && !selection.historical) {
      releaseEvidence(lease);
      showRefreshResult(selection, 'No newer quote or calculation inputs found.');
      return;
    }
    const reference = selectedReference(offer, selection.basis);
    const group = {...selection.group, settlement_match:undefined,
      sportsbook_quotes:reference?.prices?.[0] ? {[reference.book]: [{...reference.prices[0], current:true}]} : undefined};
    state.selected = {...selection, group, offer, evidence, lease, checkedAt:Date.now(),
      historical:false, pinned:null, retentionError:null, publication:null};
    releaseEvidence(selection.lease);
    tradeDetails();
    showRefreshResult(state.selected, 'Updated the offer and calculation inputs.');
  } catch {
    if (isActive()) adoptionNotice(selection, 'Could not check the latest price. The earlier inspection is still pinned.');
  } finally {
    latest.disabled = false;
    if (dialog.open && !latest.hidden && !dialog.contains(document.activeElement)) latest.focus({preventScroll:true});
  }
};

function closeInspection() {
  dialog.close();
  finishInspection(true);
}

function finishInspection(restoreOpener = false) {
  if (dialog.open || !state.selected) return;
  const old = state.selected;
  const position = inspection;
  inspection = null;
  state.selected = null;
  releaseEvidence(old?.lease);
  releaseEvidence(old?.pairContext?.lease);
  const pair = old?.pairContext?.pair || old?.pair;
  const current = pair
    ? [...$('results').querySelectorAll('[data-pair-id]')].find(item => item.dataset.pairId === pair.id)
    : [...$('results').querySelectorAll(old?.opener?.dataset.calculationId ? '[data-calculation-id]' : '[data-offer-id]')]
      .find(item => (item.dataset.calculationId ?? item.dataset.offerId) === old?.offer?.id);
  const fallback = $('refresh-list').disabled ? filters.elements.search : $('refresh-list');
  const previousOpener = old?.pairContext?.opener || old?.opener;
  const opener = previousOpener?.isConnected ? previousOpener : current;
  const focused = document.activeElement;
  if (opener && (restoreOpener || focused === document.body || focused === document.documentElement || dialog.contains(focused))) {
    opener.focus({preventScroll:true});
  }
  else restoreFocus(fallback);
  if (position) {
    restoreMatrices(position.tableScrolls);
    window.scrollTo(0, position.scrollY);
    window.history.scrollRestoration = position.scrollRestoration;
  }
}
// A native close event follows later. Clean up external closes without moving
// focus after the user has already reached another control.
dialog.addEventListener('close', () => finishInspection());
async function checkSelection() {
  const selected = state.selected;
  if (replay || !dialog.open || !selected || selected.historical || selected.adoptionNotice || $('latest').disabled) return;
  expireInspection();
  try {
    if (selected.pair) {
      if (!selected.pair.inspection) return;
      const current = await readPair(selected);
      if (!dialog.open || selected !== state.selected || selected.adoptionNotice || $('latest').disabled) return;
      $('trade-note').textContent = !current && phase === 'pregame' && Date.parse(selected.group.start_at) <= Date.now()
        ? 'Scheduled start passed. The pregame pair remains pinned.'
        : !current ? 'A current modeled payoff is unavailable. The earlier calculation is still pinned.'
        : pairIdentity(current) !== pairIdentity(selected) ? 'Pair inputs changed. Use latest prices to update both legs together.'
          : selected.refreshMessage || '';
      return;
    }
    const query = new URLSearchParams({id:selected.offer.id, layout:'desk', basis:selected.basis});
    if (phase) query.set('phase', phase);
    const response = await fetch(`/api/comparison-current/selection?${query}`);
    if (!response.ok) return;
    const {row, withdrawn_from_phase, reason} = await response.json();
    if (!dialog.open || selected !== state.selected || selected.adoptionNotice || $('latest').disabled) return;
    const previous = selected.offer;
    let note = '';
    if (withdrawn_from_phase || row?.withdrawn_from_phase ||
        phase === 'pregame' && Date.parse(selected.group.start_at) <= Date.now()) {
      pinSelectionStatus(selected);
      note = evidenceReason(reason, `This quote is no longer eligible for ${phase === 'live' ? 'Live' : 'Pregame'}.`)
        + ' The inspected price remains pinned.';
    } else if (!row?.current) {
      pinSelectionStatus(selected);
      note = `${row ? quoteFreshness(row) + '.' : 'Latest price is unavailable.'} The inspected price remains pinned.`;
    }
    else if (selectionIdentity(row) !== selectionIdentity(previous)) {
      pinSelectionStatus(selected);
      const change = row.odds?.decimal === previous.odds?.decimal ? 'Calculation evidence changed.' : 'Price changed.';
      note = `${change} Use latest prices to update the offer, fee and reference together.`;
    }
    $('trade-note').textContent = [note || selected.refreshMessage, selected.retentionError].filter(Boolean).join(' ');
  } catch {}
}
$('session-export').onclick=()=>history.export();
$('session-clear').onclick=()=>history.clear();
const session = $('session-history');
$('open-session').onclick = () => {
  history.mount($('session-summary'), $('session-events'));
  session.showModal();
};
session.addEventListener('close', () => {
  if (session.open) return;
  history.unmount();
  restoreFocus($('open-session'));
});
document.addEventListener('visibilitychange',()=>history.record(document.hidden?'display_paused':'display_resumed',{reason:'tab_visibility'}));
window.addEventListener('pageshow', event => {
  if (!event.persisted || gameKey) return;
  const location = window.history.state?.predictDesk;
  if (location) {
    restoreLocation = location;
    load(location.offset);
  }
});
let updateTimer;
let updateDelay = 6500;
let checkedBoundary;

function scheduleUpdates() {
  if (replay) return;
  clearTimeout(updateTimer);
  const deadline = Date.parse(state.page?.refresh_at) - Date.now();
  updateTimer = setTimeout(followUpdates, deadline > 0 ? Math.min(updateDelay, Math.max(deadline, 250)) : updateDelay);
}

async function followUpdates() {
  try {
    if (document.hidden) return;
    expireInspection();
    expireResultValues();
    if (dialog.open) {
      await checkSelection();
      return;
    }
    const page = state.page;
    if (!page?.update_cursor || state.request || state.query !== JSON.stringify(selections())) return;
    const expired = Date.parse(page.refresh_at) <= Date.now();
    if (expired && !state.previousReason) previousResults('Some results have expired.');
    if (usingResults()) return;
    const query = new URLSearchParams({layout:'desk', phase, after:page.update_cursor});
    let change;
    try {
      const response = await fetch(`/api/comparison-current/updates?${query}`);
      if (!response.ok) throw Error('Price status unavailable');
      change = await response.json();
    } catch {
      if (state.page === page && !state.request) previousResults('Could not check the latest prices. Showing the previous results.');
      return;
    }
    if (state.page !== page || state.request || dialog.open || usingResults()) return;
    updateDelay = Math.max(1000, Number(change.poll_after_ms) || 6500);
    const recheckExpiry = expired && checkedBoundary !== page.refresh_at;
    if (change.changed || recheckExpiry || change.phase && change.phase !== phase) {
      checkedBoundary = page.refresh_at;
      await load(state.offset, {background:true});
    } else if (!expired) previousResults();
  } finally {
    scheduleUpdates();
  }
}

load(restored?.offset ?? 0);
openHistorical();
scheduleUpdates();

setInterval(async () => {
  const selected = state.selected;
  if (!dialog.open || !selected) return;
  for (const subject of [selected, selected.pairContext]) {
    if (!subject?.lease) continue;
    const result_id = (subject.offer || subject.pair).evidence_result_id;
    try {
      const response = await fetch('/api/comparison-current/lease', {method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({result_id, lease_id:subject.lease.lease_id})});
      if (!response.ok && selected === state.selected) {
        selected.retentionError = 'Evidence retention expired; displayed inspection remains saved.';
        $('trade-note').textContent = selected.retentionError;
      }
    } catch {}
  }
}, 30000);
