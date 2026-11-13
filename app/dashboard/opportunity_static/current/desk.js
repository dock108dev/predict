import './ui-common.js';
import {tradeInspection, pairInspection} from './desk-inspection.js';
import {arbCard, evCard, gameMatrix} from './opportunity-cards.js';
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
const browse = ['/browse-odds', '/game'].includes(location.pathname) || replay && ['odds', 'game'].includes(route.get('view'));
const opportunityView = !browse && !replay;
const phase = !replay && (route.get('phase') === 'live' ? 'live'
  : opportunityView || route.get('phase') === 'pregame' ? 'pregame' : '');
const phaseURL = (path, value = phase) => path + (value === 'live' ? '?phase=live' : '');
const back = window.PredictUI.localURL(route.get('back'));
const safeBack = back && ['/','/ev','/arbs','/browse-odds','/replay'].includes(back.pathname)
  ? back.pathname + back.search : null;
const dataset = ['frozen','preview','practice'].includes(route.get('dataset')) ? route.get('dataset') : 'practice';
const frame = route.get('frame') === 'changed' ? 'changed' : 'initial';
const endpoint = replay ? '/api/odds-replay' : '/api/comparison-current';
const replayURL = (view, chosen = dataset, step = frame) => '/replay?' + new URLSearchParams({view, dataset:chosen, frame:step});
const replayMode = () => !replay ? null : dataset === 'practice' ? 'Synthetic practice · fictional prices and inputs' : 'Saved capture · frozen observed prices';
const pageSize = 25;
const pageLimit = gameKey ? 100 : browse ? 5 : pageSize;
const filters = $('filters');
const defaultZone = timezone();
const selectedZone = () => filters.elements.timezone.value || defaultZone;
const clock = at => savedClock(at, selectedZone());
const stake = filters.elements.stake;
const dialog = $('trade');
const state = {offset: 0, page: null, request: null, selected: null, lastChecked: null};
const history = new DiagnosticSession();
const siteName = offer => name(offer.venue);

function restoreFocus(target) {
  // The native dialog restores focus before the queued close event. Only supply
  // a fallback when its opener is gone and focus is still on the document.
  if (document.activeElement === document.body) target.focus({preventScroll:true});
}

$('title').textContent = gameKey ? 'Game odds' : browse ? 'Browse odds' : replay ? (arb ? 'Arbitrage' : 'Expected value') : 'Opportunities';
document.title = `Predict · ${$('title').textContent}`;
$('stake-field').hidden = $('profit-field').hidden = !arb;
$('basis-field').hidden = arb;
$('group-field').hidden = arb || !replay;
$('opportunity-tabs').hidden = !opportunityView;
$('phase-tabs').hidden = !opportunityView;
if (opportunityView) {
  $(phase === 'live' ? 'phase-live' : 'phase-pregame').setAttribute('aria-current', 'page');
  $('phase-pregame').href = phaseURL(arb ? '/arbs' : '/ev', 'pregame');
  $('phase-live').href = phaseURL(arb ? '/arbs' : '/ev', 'live');
  $('opportunity-ev').href = phaseURL('/ev');
  $('opportunity-arb').href = phaseURL('/arbs');
}
$('game-state-field').hidden = !!phase;
$('period-field').hidden = phase === 'pregame';
$(arb ? 'opportunity-arb' : 'opportunity-ev').setAttribute('aria-current', 'page');
$('positive-field').hidden = browse;
$('return-filters').hidden = browse;
$('sort-field').hidden = !replay;
if (replay) $('return-title').textContent = 'Sorting and return thresholds';
$('last-known-field').hidden = !browse;
$('alternates-field').hidden = !browse;
$('filters').querySelector('.desk-search').hidden = !!gameKey;
$('replay-controls').hidden = !replay;
$('browse-link').hidden = replay && !browse;
if (browse) {
  $('browse-link').href = replay ? replayURL(gameKey ? 'odds' : 'ev')
    : gameKey ? '/browse-odds' + (phase ? '?phase=' + phase : '') : phaseURL('/');
  $('browse-link').textContent = gameKey ? 'All games' : 'Opportunities';
  $('desk-path').hidden = false;
  const previousView = link('Back', safeBack || (replay ? replayURL('ev') : '/'));
  previousView.addEventListener('click', event => {
    if (safeBack && document.referrer === new URL(safeBack, location.origin).href) {
      event.preventDefault();
      window.history.back();
    }
  });
  $('desk-path').append(previousView);
}
$('replay-link').href = replayURL(arb ? 'arbs' : 'ev', 'practice', 'initial');
filters.elements.timezone.options[0].textContent = `Default (${defaultZone.replaceAll('_', ' ')})`;
if (replay) {
  $('desk-mode').hidden = false;
  $('desk-mode').textContent = replayMode();
  $('replay-link').textContent = 'Return to live board';
  $('replay-link').href = phaseURL(arb ? '/arbs' : '/ev', 'live');
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
const evFilterKey = 'ev-filters';
const filterKey = replay ? `replay-${dataset}-${browse ? 'odds' : arb ? 'arb' : 'ev'}-filters`
  : browse ? 'browse-filters' : phase === 'live' ? (arb ? 'live-arb-filters' : 'live-ev-filters')
    : arb ? 'arb-filters' : evFilterKey;
let saved;
try { saved = JSON.parse(readPreference(filterKey, '{}')); } catch { saved = {}; }
saved ||= {};
if (browse) {
  let ordinary = {};
  try { ordinary = JSON.parse(readPreference(evFilterKey, '{}')) || {}; } catch {}
  if (!replay) saved.basis = (phase === 'live' ? null : ordinary.basis) || saved.basis;
  for (const key of ['league','family','venue','search','day','period','timezone','time_from','time_to','game_state']) {
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
  saved.group ||= 'offer'; saved.basis ||= 'before';
}
for (const key of ['search', 'day', 'sort', 'group', 'period', 'minimum', 'profit','basis','timezone','time_from','time_to','game_state']) {
  if (saved[key]) filters.elements[key].value = saved[key];
}
filters.elements.positive.checked = !browse && saved.positive === 'on';
filters.elements.last_known.checked = browse && (route.get('last_known') || saved.last_known) === '1';
let marketFamily = gameKey && ['winner','spread','total'].includes(route.get('family')) ? route.get('family') : '';
function marketTabs() {
  if (!browse || !gameKey) return;
  const tabs = $('market-tabs');
  tabs.hidden = false;
  tabs.replaceChildren(...[['','All markets'],['winner','Winners'],['spread','Spreads'],['total','Totals']].map(([family, label]) => {
    const tab = button(label, () => {
      marketFamily = family;
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
  if (!arb) delete query.profit;
  if (!replay || browse) query.group = 'outcome';
  if (browse) {
    for (const key of ['positive','minimum','profit','sort']) delete query[key];
    query.browse_odds = '1';
    if (gameKey) query.game_key = gameKey;
  } else if (opportunityView) {
    query.ranked = '1';
    delete query.sort;
  }
  if (phase) {
    query.phase = phase;
    delete query.game_state;
    if (phase === 'pregame') delete query.period;
  }
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
  const {offer, group, game, evidence} = state.selected;
  const label = position(offer, game);
  $('trade-title').textContent = `${siteName(offer)} · ${label}`;
  const mode = state.selected.historical ? 'Saved capture · prices at inspection time' : replayMode();
  $('trade-body').replaceChildren(tradeInspection(offer, group, evidence, {mode, position:label, basis:state.selected.basis, checkedAt:state.selected.checkedAt}));
  $('latest').hidden = replay;
  $('back-to-pair').hidden = !state.selected.pairContext;
}

async function openTrade(offer, group, game, pairContext = null) {
  const opener = pairContext?.opener || document.activeElement;
  if (!dialog.open) releaseEvidence(state.selected?.lease);
  state.selected = {offer, group, game, opener, pairContext, basis:filters.elements.basis.value, checkedAt:Date.now()};
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
  if (!dialog.open) releaseEvidence(state.selected?.lease);
  state.selected = context;
  $('trade-title').textContent = 'Arbitrage calculation';
  $('trade-note').textContent = '';
  $('latest').hidden = replay;
  $('back-to-pair').hidden = true;
  $('trade-body').replaceChildren(pairInspection(pair, offers, {group, game, position, mode:replayMode(),
    inspect: offer => openTrade(offer, group, game, context)}));
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
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

$('back-to-pair').onclick = () => {
  const {pairContext, lease} = state.selected;
  releaseEvidence(lease);
  openPair(pairContext.pair, pairContext.offers, pairContext.group, pairContext.game, pairContext.opener);
  dialog.querySelector('form button').focus();
};
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

function browsingLink(label, group, className) {
  const query = new URLSearchParams();
  const selected = selections();
  if (phase) query.set('phase', phase);
  if (group) {
    if (filters.elements.last_known.checked) query.set('last_known', '1');
    query.set('game_key', group.game_key);
    if (!browse && group.id) query.set('line', group.id);
    if (!browse && !arb && group.market.market) query.set('family', group.market.market);
  } else {
    for (const key of ['league','venue','family','search','day','period','timezone','time_from','time_to','game_state']) {
      if (selected[key]) query.set(key, selected[key]);
    }
  }
  query.set('back', location.pathname + location.search);
  const destination = replay ? replayURL(group ? 'game' : 'odds') + '&' + query : `${group ? '/game' : '/browse-odds'}?${query}`;
  const action = link(label, destination, className);
  action.addEventListener('click', () => rememberView(group?.id, action));
  return action;
}

function rememberView(groupId, action) {
  const navigation = {offset:state.offset, scroll:window.scrollY, groupId, browseId:state.page?.browse_id,
    openerHref:action.href};
  window.history.replaceState({...window.history.state, predictDesk:navigation}, '');
}

function cardContext(games, gameTitle = null) {
  return {
    basis:filters.elements.basis.value, clock, checkedAt:state.page?.publication?.read_at, gameTitle, showWinPayout:browse, showGameLink:!gameKey, stableVenues:!replay,
    position:offer => position(offer),
    gameLink:group => browsingLink('Open game ↗', group, 'opportunity-link'),
    inspectOffer:(offer, group) => openTrade(offer, group, games.get(group.game_key)),
    inspectPair:(pair, offers, group) => openPair(pair, offers, group, games.get(group.game_key))
  };
}

function refreshStatus() {
  const checked = state.lastChecked ? `Last checked ${new Intl.DateTimeFormat('en-US', {hour:'numeric', minute:'2-digit', second:'2-digit', timeZoneName:'short', timeZone:selectedZone()}).format(state.lastChecked)}.` : 'No successful check yet.';
  const mode = !filters.elements.time_to.validity.valid ? 'Correct the time window to refresh.'
    : replay ? (state.request ? 'Loading replay…' : 'Replay clock is fixed.')
    : state.request ? 'Checking for updates…' : '';
  $('refresh-status').textContent = [mode, checked].filter(Boolean).join(' ');
  $('refresh-list').disabled = !!state.request || !filters.elements.time_to.validity.valid;
}

function emptyResults(page, publication) {
  const empty = el('section', null, 'desk-empty');
  const actions = el('div', null, 'desk-empty-actions');
  const runtime = publication.data_runtime;
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
    detail = 'Synthetic practice is included with the app.';
  } else if (!replay && runtime?.stopped) {
    title = 'Price updates are stopped';
    detail = 'Current prices will return after collection resumes.';
  } else if (!replay && runtime?.healthy === false) {
    title = 'The data service is unavailable';
    detail = 'Set up or start the local data service to see live prices.';
  } else if (page.state === 'initializing' && !publication.retained_prices) {
    title = 'No prices have loaded yet';
    detail = 'The desk will update after the data service publishes its first prices.';
  } else if (browse) {
    title = 'No current prices match these filters';
    detail = 'Check last-known prices or broaden the selection.';
  } else if (page.ranked_group_count && (positive.checked || thresholds)) {
    title = thresholds ? 'No results meet the return filters' : 'No positive results';
    detail = 'Clear the return filters to see evaluated results.';
    actions.append(clearReturns);
  } else if (page.matched_offer_count === 0 && publication.current_prices) {
    title = 'No offers match these filters';
    detail = 'Try another matchup or broaden your selection.';
    actions.append(button('Edit filters', () => $('open-filters').click()));
  } else if (arb) {
    title = 'No arbitrage calculations available';
    const reason = page.pair_status || {};
    detail = page.calculation_reason || (reason.finance_pending ? 'An opposing pair is waiting for calculation publication.'
      : page.eligible_pair_count ? 'Current pairs are missing applicable fees or settlement evidence.'
      : 'The current prices have no verified opposing pair.');
  } else {
    title = 'No EV estimates available';
    detail = page.calculation_reason || (publication.state === 'held' ? 'The reference source is on hold.'
      : publication.current_prices ? 'Current prices are missing an eligible sportsbook reference for the selected basis.'
      : 'Current offered prices are unavailable.');
  }
  if (!browse && !replay) actions.prepend(browsingLink('Find my game ↗', null, 'desk-action desk-primary'));
  if (replay || runtime?.healthy === false || runtime?.stopped || page.state === 'initializing') {
    actions.append(link('Try synthetic practice', replayURL(arb ? 'arbs' : 'ev', 'practice', 'initial')));
    if (!replay) actions.append(link('Check data sources', '/admin?section=sources'));
  }
  empty.append(el('h2', title));
  if (!browse && !replay) empty.append(el('p', 'See what each site pays for the same pick.', 'desk-meta'));
  if (detail) empty.append(el('p', detail, 'desk-note'));
  if (actions.hasChildNodes()) empty.append(actions);
  return empty;
}

function render(page) {
  const results = $('results');
  const expanded = new Set([...results.querySelectorAll('details[open]')].map(e => e.dataset.id));
  const tableScrolls = [...results.querySelectorAll('.odds-scroll')].map(table => table.scrollLeft);
  const games = new Map((page.games || []).map(game => [game.game_key, game]));
  const rows = page.rows || [];
  const total = page.total || 0;
  if (gameKey) {
    const matchup = games.get(gameKey);
    const first = rows.find(row => !row.withdrawn);
    const title = first?.game_title || matchup?.title;
    if (title) {
      $('title').textContent = title;
      $('desk-subtitle').textContent = `${first?.league || matchup?.league} · ${clock(first?.start_at || matchup?.start_at)}`;
      $('desk-subtitle').hidden = false;
      document.title = `Predict · ${title}`;
    }
  }
  const publication = page.publication || {};
  const coverage = page.coverage;
  const strip = $('coverage-strip');
  strip.hidden = !coverage?.offers && !page.matched_offer_count;
  if (!strip.hidden) {
    const priced = coverage?.current ?? page.matched_offer_count;
    const calculated = page.ranked_group_count ?? 0;
    const missing = coverage?.missing ?? Math.max(0, (page.matched_outcome_count ?? page.matched_offer_count ?? 0) - calculated);
    strip.textContent = `${priced.toLocaleString()} ${replay ? 'fresh at capture' : 'current prices'} · ${calculated.toLocaleString()} calculated ${arb ? 'pair groups' : 'outcomes'} · ${missing.toLocaleString()} awaiting inputs or publication`;
  }
  const notice = [];
  if (replay && page.replay?.captured_at) notice.push(`Captured ${clock(page.replay.captured_at)}.`);
  if (state.offset && !replay && !browse) notice.push(page.browse_order || 'Browsing order held.');
  if (rows.length && publication.data_runtime?.stopped) notice.push('Price updates are stopped.');
  if (rows.length && publication.data_runtime?.healthy === false) notice.push('The data service is unavailable. Last-known prices are labeled.');
  if (browse && publication.sources?.sportsgameodds?.reason_code === 'sgo_charge_unresolved') {
    notice.push(filters.elements.last_known.checked ? 'Sportsbook updates are paused. Retained prices are labeled Last known.'
      : 'Sportsbook updates are paused. Turn on Last-known prices to see retained quotes.');
  }
  if (state.resetReason) notice.push(state.resetReason);
  $('notice').textContent = notice.join(' ');
  results.replaceChildren();
  if (opportunityView) {
    const action = browsingLink('Find my game ↗', null, 'desk-action');
    action.id = 'browse-link';
    $('browse-link').replaceWith(action);
    action.hidden = !rows.length;
  }
  if (browse && rows.length) {
    const groups = new Map();
    for (const row of rows) {
      if (row.withdrawn) continue;
      if (!groups.has(row.game_key)) groups.set(row.game_key, []);
      groups.get(row.game_key).push(row);
    }
    for (const [key, gameRows] of groups) {
      const first = gameRows[0];
      const context = cardContext(games, !gameKey && first.game_title);
      context.position = offer => position(offer, games.get(key));
      results.append(gameMatrix(gameRows, context, {includeAlternates:$('alternates').checked, market:marketFamily}));
    }
  } else if (rows.length) {
    for (const group of rows) {
      if (group.withdrawn) {
        results.append(el('p', `${group.game_title}: ${group.reason}`, 'desk-note'));
        continue;
      }
      const context = cardContext(games);
      context.game = games.get(group.game_key);
      context.position = offer => position(offer, context.game);
      results.append(arb ? arbCard(group, context, expanded.has(group.id)) : evCard(group, context));
    }
  } else {
    results.append(emptyResults(page, publication));
  }
  [...results.querySelectorAll('.odds-scroll')].forEach((table, index) => table.scrollLeft = tableScrolls[index] || 0);
  const shown = page.page_count ?? rows.length;
  $('count').textContent = total && !gameKey
    ? `${state.offset + 1}–${state.offset + shown} of ${total.toLocaleString()} ${browse ? page.row_kind || 'outcomes' : arb ? 'pair groups' : page.row_kind || 'outcomes'}`
    : gameKey ? '' : '0 results';
  $('previous').disabled = state.offset === 0;
  $('next').disabled = state.offset + shown >= total;
  $('previous').parentElement.hidden = !!gameKey || !total;
}

const restored = window.history.state?.predictDesk;
const requestedLine = route.get('line');
let restoreLocation = restored || (gameKey && requestedLine ? {groupId:requestedLine} : null);

function restoreLocationAfterLoad() {
  if (!restoreLocation) return;
  const {scroll, groupId, openerHref} = restoreLocation;
  restoreLocation = null;
  const row = [...$('results').querySelectorAll('[data-group-id]')].find(item => item.dataset.groupId === groupId);
  if (scroll != null) window.scrollTo(0, scroll);
  else row?.scrollIntoView({block:'nearest'});
  const opener = openerHref && [...document.querySelectorAll('main a')].find(item => item.href === openerHref && !item.hidden);
  const target = opener || row?.querySelector('a,button');
  target?.focus({preventScroll:true});
}

async function fetchPage(query, signal) {
  const response = await fetch(`${endpoint}?${query}`, {signal});
  if (!response.ok) throw Error('Unavailable');
  return response.json();
}

async function load(offset = state.offset) {
  if (!filters.checkValidity() || !stake.value) return;
  state.request?.abort();
  const controller = new AbortController(); state.request = controller; refreshStatus();
  const query = new URLSearchParams({...selections(), layout: 'desk', view: arb ? 'arbs' : 'ev',
    stake: stake.value, offset, limit:pageLimit});
  if (replay) { query.set('dataset', dataset); query.set('frame', frame); }
  const browseId = state.page?.browse_id ?? restoreLocation?.browseId;
  if (!replay && offset && browseId) query.set('browse_id', browseId);
  if (!state.page) $('notice').textContent = 'Loading prices…';
  try {
    const page = await fetchPage(query, controller.signal);
    if (controller.signal.aborted) return;
    if (page.state === 'page_changed') {
      history.record('browsing_reset', {reason:page.reason});
      state.resetReason = page.reason;
      return load(0);
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
    state.page = page;
    state.offset = offset;
    state.lastChecked = new Date();
    render(page);
    state.resetReason = null;
    restoreLocationAfterLoad();
    history.observe(page, selections());
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
  if (!filters.checkValidity() || !stake.value) return;
  if (!gameKey) savePreference(filterKey, JSON.stringify({...selections(), timezone:filters.elements.timezone.value}));
  if (arb) savePreference('stake', stake.value);
  if (browse && !replay) {
    let ordinary = {};
    try { ordinary = JSON.parse(readPreference(evFilterKey, '{}')) || {}; } catch {}
    savePreference(evFilterKey, JSON.stringify({...ordinary, basis:filters.elements.basis.value}));
  }
  clearTimeout(debounce); debounce = setTimeout(() => load(0), 240);
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
$('refresh-list').onclick = () => load(0);
document.addEventListener('focusin', refreshStatus);
document.addEventListener('focusout', () => queueMicrotask(refreshStatus));
$('previous').onclick = () => load(Math.max(0, state.offset - pageLimit));
$('next').onclick = () => load(state.offset + (state.page?.page_count ?? pageLimit));
$('alternates').addEventListener('input', event => {
  event.stopPropagation();
  if (state.page) render(state.page);
});
function pairIdentity(context) {
  const {pair, offers} = context;
  const payoff = pair.retail_payoff;
  const fees = payoff.legs.map(leg => [leg.available, leg.classification, leg.quantity, leg.acquisition_usd,
    leg.at_fill_usd, leg.settlement_usd, leg.receipts_usd]);
  return JSON.stringify([pair.id, pair.legs.map(id => selectionIdentity(offers.get(id))),
    payoff.available, payoff.reason, payoff.funding_usd, payoff.states, payoff.sizing, fees, pair.score]);
}

async function readPair(selection) {
  const query = new URLSearchParams({
    layout:'desk', view:'arbs', stake:selection.pair.inspection.funding_usd, game_key:selection.group.game_key,
    family:selection.group.market.market, period:selection.group.market.period, limit:pageSize
  });
  if (phase) query.set('phase', phase);
  const ids = [...selection.pair.legs].sort().join('\u001f');
  for (let offset = 0; ; offset += pageSize) {
    query.set('offset', offset);
    const page = await fetchPage(query);
    const group = page.rows?.find(row => row.id === selection.group.id);
    const pair = group?.pairs.find(item => [...item.legs].sort().join('\u001f') === ids && item.retail_payoff?.available);
    if (pair) return {pair, group, offers:new Map(group.offers.map(offer => [offer.id, offer])),
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
  openPair(confirmed.pair, confirmed.offers, confirmed.group, confirmed.game, selection.opener);
}

function adoptionNotice(selection, message) {
  selection.adoptionNotice = true;
  $('trade-note').textContent = message;
}

$('latest').onclick = async () => {
  const latest = $('latest');
  const selection = state.selected;
  selection.adoptionNotice = false;
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
      pin: pinEvidence, release: releaseEvidence, isActive
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
    const {sportsbook_quotes: _, settlement_match: _match, ...group} = selection.group;
    state.selected = {...selection, group, offer, evidence, lease, checkedAt:Date.now(), historical:false, retentionError:null};
    releaseEvidence(selection.lease);
    $('trade-note').textContent = '';
    tradeDetails();
  } catch {
    if (isActive()) adoptionNotice(selection, 'Could not check the latest price. The earlier inspection is still pinned.');
  } finally {
    latest.disabled = false;
    if (dialog.open && !latest.hidden && !dialog.contains(document.activeElement)) latest.focus({preventScroll:true});
  }
};
dialog.addEventListener('close', () => {
  if (dialog.open) return; // A keyboard user may have reopened before the queued event.
  const old = state.selected;
  state.selected = null;
  releaseEvidence(old?.lease);
  const pair = old?.pairContext?.pair || old?.pair;
  const current = pair
    ? [...$('results').querySelectorAll('[data-pair-id]')].find(item => item.dataset.pairId === pair.id)
    : [...$('results').querySelectorAll(old?.opener?.dataset.calculationId ? '[data-calculation-id]' : '[data-offer-id]')]
      .find(item => (item.dataset.calculationId ?? item.dataset.offerId) === old?.offer?.id);
  const fallback = $('refresh-list').disabled ? filters.elements.search : $('refresh-list');
  restoreFocus(old?.opener?.isConnected ? old.opener : current || fallback);
});
async function checkSelection() {
  const selected = state.selected;
  if (replay || !dialog.open || !selected || selected.adoptionNotice || $('latest').disabled) return;
  try {
    if (selected.pair) {
      const current = await readPair(selected);
      if (!dialog.open || selected !== state.selected || selected.adoptionNotice || $('latest').disabled) return;
      $('trade-note').textContent = !current && phase === 'pregame' && Date.parse(selected.group.start_at) <= Date.now()
        ? 'Scheduled start passed. The pregame pair remains pinned.'
        : !current ? 'A current modeled payoff is unavailable. The earlier calculation is still pinned.'
        : pairIdentity(current) !== pairIdentity(selected) ? 'Pair inputs changed. Use latest prices to update both legs together.' : '';
      return;
    }
    const query = new URLSearchParams({id:selected.offer.id, layout:'desk', basis:selected.basis});
    if (phase) query.set('phase', phase);
    const response = await fetch(`/api/comparison-current/selection?${query}`);
    if (!response.ok) return;
    const {row} = await response.json();
    if (!dialog.open || selected !== state.selected || selected.adoptionNotice || $('latest').disabled) return;
    if (selected.retentionError) {
      $('trade-note').textContent = selected.retentionError;
      return;
    }
    const previous = selected.offer;
    let note = '';
    if (phase === 'pregame' && (row?.withdrawn_from_phase || Date.parse(selected.group.start_at) <= Date.now())) {
      note = row?.game_state === 'live' ? 'Game is live. The pregame capture remains pinned.'
        : row?.game_state === 'suspended' ? 'Game is suspended. The pregame capture remains pinned.'
        : row?.game_state === 'final' ? 'Game ended. The pregame capture remains pinned.'
        : 'Market left Pregame. The inspected capture remains pinned.';
    } else if (!row?.current) note = 'Latest price is unavailable. Inspected evidence remains pinned.';
    else if (selectionIdentity(row) !== selectionIdentity(previous)) {
      const change = row.odds?.decimal === previous.odds?.decimal ? 'Calculation evidence changed.' : 'Price changed.';
      note = `${change} Use latest prices to update the offer, fee and reference together.`;
    }
    $('trade-note').textContent = note;
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
load(restored?.offset ?? 0);
openHistorical();
setInterval(() => {
  if (!replay && !state.request && !document.hidden && !$('results').contains(document.activeElement)) load();
  refreshStatus();
}, 6500);

setInterval(async()=>{const selected=state.selected;if(!dialog.open||!selected?.lease)return;try{const response=await fetch('/api/comparison-current/lease',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({result_id:selected.offer.evidence_result_id,lease_id:selected.lease.lease_id})});if(!response.ok&&selected===state.selected){selected.retentionError='Evidence retention expired; displayed inspection remains saved.';$('trade-note').textContent=selected.retentionError;}}catch{}},30000);
