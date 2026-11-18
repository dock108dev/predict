import './ui-common.js';
import {createDeskPolling} from './desk-polling.js';
import {createDeskDrawer, position} from './desk-drawer.js';
import {arbCard, evCard, gameMatrix, updateMatrixCues} from './opportunity-cards.js';
import {displayRows, expirePage, holdDeskPage, nextDeskDeadline} from './desk-stability.js';
import {evidenceReason} from './desk-reasons.js';
import {DiagnosticSession} from './session-history.js';
import {clock as savedClock, readPreference, savePreference, timezone} from './desk-preferences.js';
import {ticketCard} from './desk-ticketboard.js';

const {el, fmt, name, odd, link, button} = window.PredictUI;
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
const afterFeeView = opportunityView && !arb;
const comparable = !replay && !arb;
let phase = !replay && (route.get('phase') === 'live' ? 'live' : 'pregame');
let liveEnabled = false;
const autoUpdateKey = 'pregame-auto-update';
const autoUpdateToggle = $('auto-update');
let autoUpdate = readPreference(autoUpdateKey, 'on') !== 'off';
autoUpdateToggle.checked = autoUpdate;
const supportsAutoUpdate = (page = state.page) => !replay && phase === 'pregame' && page?.features?.auto_update === true;
const receivingUpdates = () => !supportsAutoUpdate() || autoUpdate;
const phaseURL = (path, value = phase) => path + (value === 'live' ? '?phase=live' : '');
const back = window.PredictUI.localURL(route.get('back'));
let safeBack = back && ['/','/ev','/arbs','/browse-odds','/game','/replay'].includes(back.pathname)
  ? back.pathname + back.search : null;
const browseCacheKey = 'predict-desk-return';
// Referrer-Policy can hide even same-origin URLs from the Navigation API.
// A same-tab launch records its origin once; copied links have no launch record.
if (browse && safeBack) {
  const cached = readBrowseReturn();
  if (cached?.pending === location.href && cached.url === new URL(safeBack, location.origin).href) {
    window.history.replaceState({...window.history.state, predictDeskFrom:{url:cached.url, key:cached.navigation.entryKey}}, '');
    try { sessionStorage.setItem(browseCacheKey, JSON.stringify({...cached, pending:null})); } catch {}
  }
}
const dataset = ['frozen','preview','retained','practice'].includes(route.get('dataset')) ? route.get('dataset') : 'frozen';
const practice = replay && dataset === 'practice';
const retainedResult = replay && dataset === 'retained' ? route.get('result_id') : null;
const endpoint = replay ? '/api/odds-replay' : '/api/comparison-current';
const replayURL = (view, chosen = dataset === 'retained' ? 'frozen' : dataset) => '/replay?' + new URLSearchParams({view, dataset:chosen});
const replayMode = () => practice ? 'Practice example · simulated odds' : replay ? 'Saved odds · prices at capture' : null;
const pageSize = 25;
const gamesPerPage = 12;
const pageLimit = gameKey ? 100 : replay ? (browse ? 5 : pageSize) : arb ? pageSize : gamesPerPage;
const filters = $('filters');
const browseFilterFields = ['league','family','venue','search','day','period','timezone','time_from','time_to','game_state'];
const defaultZone = timezone();
const selectedZone = () => filters.elements.timezone.value || defaultZone;
const clock = at => savedClock(at, selectedZone());
const state = {offset: 0, page: null, request: null};
const history = new DiagnosticSession();
function collectionIssue(runtime) {
  if (runtime?.stopped) return 'Price updates are stopped';
  switch (runtime?.reason) {
    case 'data_runtime_absent': return 'Price collection has not started';
    case 'data_runtime_not_dispatching': return 'Price collection is off';
    case 'data_runtime_unhealthy': return 'Price feed unavailable';
    case 'ordinary_publication_failed': return 'Prices are delayed';
    default: return runtime?.healthy === false ? 'Price feed unavailable' : null;
  }
}

function sourceNotices(publication) {
  const notices = [];
  const reconnecting = [];
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
      reconnecting.push(name(site));
    }
  }
  if (reconnecting.length) notices.push(`Reconnecting to ${reconnecting.join(', ')}.`);
  return notices;
}

function restoreFocus(target) {
  // The native dialog restores focus before the queued close event. Only supply
  // a fallback when its opener is gone and focus is still on the document.
  if (document.activeElement === document.body) target.focus({preventScroll:true});
}

$('title').textContent = gameKey ? linkedTitle || 'Game odds' : browse ? 'Browse odds' : replay ? (arb ? 'Arbitrage' : 'Expected value') : 'Opportunities';
document.body.classList.toggle('game-odds-view', !!gameKey);
document.title = `Predict · ${$('title').textContent}`;
$('basis-field').hidden = arb || afterFeeView || practice || !replay && phase === 'pregame';
$('group-field').hidden = arb || !replay || practice;
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
  $('opportunity-tabs').hidden = !opportunityView;
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
$('browse-link').hidden = replay ? !browse : browse && !gameKey;
if (browse) {
  $('browse-link').href = replay ? replayURL(gameKey ? 'odds' : 'ev')
    : gameKey ? phaseURL('/browse-odds') : phaseURL('/');
  $('browse-link').textContent = gameKey ? 'All games' : 'Opportunities';
  if (dataset === 'retained') {
    $('browse-link').href = '/browse-odds';
    $('browse-link').textContent = 'Current games';
  }
  $('desk-path').hidden = !safeBack && !replay && !gameKey;
  const previousView = link('Back', safeBack || (replay ? replayURL(gameKey ? 'odds' : 'ev') : phaseURL(gameKey ? '/browse-odds' : '/')));
  previousView.addEventListener('click', event => {
    if (!safeBack || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const previousURL = new URL(safeBack, location.origin).href;
    const entry = window.navigation?.currentEntry;
    const previousEntry = entry && window.navigation.entries()[entry.index - 1];
    const from = window.history.state?.predictDeskFrom;
    if (previousEntry?.url === previousURL
        || previousEntry?.key && from?.url === previousURL && previousEntry.key === from.key
        || !window.navigation && window.history.length > 1 && (from?.url === previousURL || document.referrer === previousURL)) {
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
  if (gameKey) $('desk-path').append($('browse-link'));
}
$('replay-link').href = replayURL(arb ? 'arbs' : 'ev', 'frozen');
$('practice-link').hidden = replay || browse;
$('practice-link').href = replayURL(arb ? 'arbs' : 'ev', 'practice');
filters.elements.timezone.options[0].textContent = `Default (${defaultZone.replaceAll('_', ' ')})`;
if (replay) {
  $('desk-mode').hidden = false;
  $('desk-mode').textContent = replayMode();
  $('replay-link').textContent = arb ? 'Return to Arbitrage' : 'Return to Opportunities';
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
    for (const key of ['league','family','search','day','period','time_from','time_to','game_state']) delete saved[key];
    if (!route.has('venue')) delete saved.venue;
  }
}
if (phase) delete saved.game_state;
if (phase === 'pregame') delete saved.period;
if (phase === 'live' && !saved.basis) saved.basis = 'reviewed';
if (afterFeeView || !replay && browse && phase === 'pregame') saved.basis = 'after_fees';
if (replay) {
  filters.elements.basis.querySelector('option[value="sportsbooks"]').remove();
  if (saved.basis === 'sportsbooks') saved.basis = dataset === 'retained' ? 'reviewed' : 'before';
  saved.group ||= 'offer'; saved.basis ||= 'before';
}
for (const key of ['search', 'day', 'sort', 'group', 'period', 'minimum','basis','timezone','time_from','time_to','game_state']) {
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
let revealMarket = false;
function marketTabs() {
  if (!browse) return;
  const tabs = $('market-tabs');
  const checked = [...$('families').querySelectorAll('input:checked')];
  const active = gameKey ? marketFamily : checked.length === 1 ? checked[0].value : checked.length === 3 ? '' : null;
  tabs.hidden = false;
  const options = [['','All markets'], ...(gameKey ? [['winner','Winners']] : []), ['spread','Spreads'],['total','Totals']];
  tabs.replaceChildren(...options.map(([family, label]) => {
    const tab = button(label, () => {
      if (gameKey) {
        marketFamily = family;
        focusSelectedLine = false;
        revealMarket = true;
        restoreLocation = null;
        marketTabs();
        if (state.page) render(state.page);
      } else {
        for (const field of $('families').querySelectorAll('input')) field.checked = !family || field.value === family;
        applyFilters();
      }
      [...tabs.children].find(item => item.getAttribute('aria-pressed') === 'true')?.focus({preventScroll:true});
    });
    tab.setAttribute('aria-pressed', String(active === family));
    return tab;
  }));
}
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
  if (!replay) delete query.last_known;
  if (!replay || browse) query.group = 'outcome';
  if (browse) {
    for (const key of ['positive','minimum','sort']) delete query[key];
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

const drawer = createDeskDrawer({
  replay, dataset, retainedResult, gameKey, pageSize, captureMode:replayMode(), clock,
  viewContext: () => ({phase, page:state.page, previousReason:state.previousReason, autoUpdate}),
  fetchPage, matrixPositions, restoreMatrices, restoreFocus, refreshDesk,
});

const deskLinks = new WeakMap();
function browsingLink(label, group, className, pinned = !browse) {
  const destination = () => browseDestination(group, pinned);
  const action = link(label, destination(), className);
  deskLinks.set(action, destination);
  if (group) action.dataset[pinned && browse ? 'lineLauncher' : 'gameLauncher'] = '';
  action.addEventListener('click', event => {
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

function browseDestination(group, pinned) {
  const query = new URLSearchParams();
  const selected = selections();
  if (phase) query.set('phase', phase);
  if (comparable) query.set('alternates', $('alternates').checked ? '1' : '0');
  if (filters.elements.last_known.checked) query.set('last_known', '1');
  if (group) {
    query.set('game_key', group.game_key);
    query.set('matchup', group.game_title);
    if (pinned && group.game_source) query.set('game_source', group.game_source);
    if (group.source_event) query.set('source_event', group.source_event);
    if (!replay) {
      const sealed = group.offers.find(offer => offer.evidence_result_id && !offer.live_native_desk);
      if (sealed) query.set('game_capture', sealed.evidence_result_id);
    }
    query.set('basis', selected.basis);
    // An omitted venue means all are selected. Matrix scroll belongs to return state.
    if ($('venues').querySelector('input:not(:checked)')) query.set('venue', selected.venue);
    query.set('timezone', filters.elements.timezone.value);
    if (pinned && (group.game_line_id || group.id)) {
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
  const byCard = new Map(positions || []);
  for (const card of $('results').querySelectorAll('.odds-card')) {
    const table = card.querySelector('.odds-scroll');
    const key = card.dataset.gameKey;
    if (table && byCard.has(key)) table.scrollLeft = byCard.get(key);
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
    entryKey:window.navigation?.currentEntry?.key,
    openerTop:action.getBoundingClientRect().top, scrollY:window.scrollY,
    filters:browsePreferences(), oddsFormat:window.PredictUI.oddsFormat(),
    tableScrolls:matrixPositions(), disclosures:[...disclosureStates()]};
  window.history.scrollRestoration = 'manual';
  window.history.replaceState({...window.history.state, predictDesk:navigation}, '', returnRoute?.href || location.href);
  const venues = new Set(navigation.filters.venue.split(','));
  const offers = browse && group ? displayRows(state.page).filter(row => row.game_key === group.game_key && !row.withdrawn)
    .flatMap(row => row.offers.filter(offer => venues.has(offer.venue)).map(offer => offer.desk_quote_key || offer.id)) : [];
  try { sessionStorage.setItem(browseCacheKey, JSON.stringify({url:location.href, navigation, offers, pending:target.href})); } catch {}
}

function rememberGameInspection(offer) {
  if (!gameKey || !safeBack) return;
  const cached = readBrowseReturn();
  const key = offer.desk_quote_key || offer.id;
  if (cached?.url !== new URL(safeBack, location.origin).href || cached.navigation?.gameKey !== gameKey) return;
  const inspectedQuote = cached.offers?.includes(key) ? key : null;
  try { sessionStorage.setItem(browseCacheKey, JSON.stringify({...cached, inspectedQuote})); } catch {}
}

function gameIdentityNote(group) {
  return ({schedule_conflict:'Source listing · kickoff records conflict. Game unconfirmed.',
    source_listing_unverified:'Source listing · occurrence could not be confirmed across sources.'})[group?.game_identity_status];
}

function occurrenceLabel(game, group) {
  const league = game?.league || group?.league;
  const start = game?.start_at || group?.start_at;
  const unverified = game?.game_identity_status || group?.game_identity_status;
  return [league, unverified && start ? `Reported kickoff: ${clock(start)}` : clock(start)].filter(Boolean).join(' · ');
}

function explainQuoteGap(venue, outcome, detail, opener) {
  const dialog = $('quote-gap');
  $('quote-gap-title').textContent = venue;
  $('quote-gap-outcome').textContent = outcome;
  $('quote-gap-detail').textContent = detail;
  dialog.addEventListener('close', () => restoreFocus(opener), {once:true});
  dialog.showModal();
}

function cardContext(games, gameTitle = null) {
  return {
    basis:pageBasis(), clock, phase,
    checkedAt:state.page?.replay?.captured_at ?? state.page?.publication?.read_at, gameTitle, mode:replayMode(),
    compact:comparable, summary:!replay, showGameLink:!gameKey, stableVenues:!replay,
    selectedVenues:state.page?.selected_venues,
    position:offer => position(offer),
    gameLink:group => browsingLink('Open game ↗', group, 'opportunity-link'),
    lineLink:browse && !gameKey && !replay ? group => {
      const action = browsingLink('Open line ↗', group, 'opportunity-link matrix-line-link', true);
      action.setAttribute('aria-label', `Open line: ${position(group.offers[0], games.get(group.game_key))}`);
      return action;
    } : null,
    explainQuoteGap,
    inspectOffer:(offer, group, opener) => {
      if (offer.practice_ticket) {
        return drawer.openTrade(offer, group, games.get(group.game_key), null, opener);
      }
      const shown = displayRows(state.page).find(row => row.id === group.id && row.game_key === group.game_key) || group;
      const exact = shown.offers.find(quote => quote.id === offer.id) || offer;
      rememberGameInspection(exact);
      return drawer.openTrade(exact, shown, games.get(group.game_key), null, opener);
    },
    inspectPair:(pair, offers, group, opener) => {
      const shown = displayRows(state.page).find(row => row.id === group.id && row.game_key === group.game_key) || group;
      const exact = shown.pairs?.find(candidate => candidate.id === pair.id) || pair;
      drawer.openPair(exact, shown === group ? offers : new Map(shown.offers.map(quote => [quote.id, quote])),
        shown, games.get(group.game_key), opener);
    }
  };
}

const pageBasis = () => state.page?.basis || filters.elements.basis.value;

function refreshStatus() {
  const invalidWindow = !filters.elements.time_to.validity.valid;
  const mode = invalidWindow ? 'Correct the time window to refresh.'
    : replay ? (state.request ? 'Loading replay…' : 'Replay clock is fixed.')
    : state.request ? 'Checking for updates…'
      : supportsAutoUpdate() && !autoUpdate ? 'Auto-update paused.' : '';
  $('refresh-status').textContent = mode;
  $('refresh-status').classList.toggle('sr-only', !invalidWindow);
  const refresh = $('refresh-list');
  const label = state.loadFailed ? 'Retry' : 'Refresh list';
  if (refresh.textContent !== label) refresh.textContent = label;
  if (state.loadFailed) refresh.setAttribute('aria-describedby', 'notice');
  else refresh.removeAttribute('aria-describedby');
  refresh.disabled = invalidWindow;
  refresh.setAttribute('aria-disabled', String(!!state.request && !state.backgroundRequest || invalidWindow));
}

function emptyResults(page, publication, issue) {
  const empty = el('section', null, 'desk-empty');
  const actions = el('div', null, 'desk-empty-actions');
  const {positive, minimum} = filters.elements;
  const search = filters.elements.search.value.trim();
  const thresholds = minimum.value;
  const clearReturns = button('Clear return filters', () => {
    positive.checked = false;
    minimum.value = '';
    applyFilters();
    $('open-filters').focus();
  });
  const alternates = $('alternates');
  const showAlternates = () => {
    if (alternates.checked) return;
    actions.append(button('Show alternate lines', () => {
      alternates.checked = true;
      applyFilters();
      alternates.focus();
    }));
  };
  let title, detail;
  if (replay && page.state === 'initializing') {
    title = 'This saved capture is unavailable';
    actions.append(link('Browse current odds', '/browse-odds'));
  } else if (issue || (page.state === 'initializing' && !publication.retained_prices)) {
    title = issue || 'Waiting for the first prices';
    if (opportunityView && page.state === 'initializing' && !publication.retained_prices) {
      actions.append(link('Saved odds', $('replay-link').href, 'desk-action desk-primary'));
    }
    if (issue) actions.append(link('Source status', '/admin?section=sources', 'desk-action'));
  } else if (search && !page.matched_offer_count && page.state !== 'initializing') {
    title = `No results for “${search}”`;
    actions.append(button('Clear search', () => {
      filters.elements.search.value = '';
      applyFilters();
      filters.elements.search.focus();
    }));
  } else if (comparable && browse && !gameKey) {
    title = 'No matching odds';
    showAlternates();
  } else if (browse) {
    title = gameKey ? 'No prices available for this matchup' : 'No prices match these filters';
    if (!replay && page.retained_game?.lifecycle) {
      detail = evidenceReason(page.retained_game.lifecycle, 'The matchup is outside this phase of the current slate.');
    }
  } else if ((page.ranked_group_count || page.eligible_pair_count || page.pair_status?.withheld)
      && (positive.checked || thresholds)) {
    title = thresholds ? 'No results meet the return filters' : 'No positive results';
    actions.append(clearReturns);
  } else if (!page.calculation_reason && page.matched_offer_count === 0 && publication.current_prices
      && (replay || filters.elements.search.value || $('filter-count').textContent !== '0')) {
    title = 'No offers match these filters';
    actions.append(button('Edit filters', () => $('open-filters').click()));
  } else if (arb) {
    title = 'No arbitrage calculations available';
    const reason = page.pair_status || {};
    detail = page.calculation_missing?.length ? evidenceReason(page.calculation_missing, page.calculation_reason)
      : page.calculation_reason || (reason.finance_pending ? 'An opposing pair is waiting for calculation publication.'
      : page.eligible_pair_count ? 'Current pairs are missing applicable fees or settlement evidence.'
      : page.matched_offer_count ? 'The current prices have no verified opposing pair.'
        : `No current prices are available${phase === 'live' ? ' for live games' : phase === 'pregame' ? ' for pregame markets' : ''}.`);
  } else {
    title = afterFeeView ? 'No after-fee EV estimates available' : 'No EV estimates available';
    if (page.data_incident) actions.append(link('Source status', '/admin?section=sources', 'desk-action'));
    detail = page.calculation_missing?.length ? evidenceReason(page.calculation_missing, page.calculation_reason)
      : page.calculation_reason || 'No current offers have the inputs required for the selected calculation.';
    if (opportunityView && page.calculation_reason && (!afterFeeView || page.coverage?.after_fees)) showAlternates();
  }
  if (opportunityView && (page.state !== 'initializing' || publication.retained_prices)) {
    actions.append(browsingLink('Browse odds ↗'));
  }
  if (arb && !replay) {
    actions.append(link('Try a practice example', $('practice-link').href, 'desk-action desk-primary'));
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

function marketGroupKey(row) {
  return JSON.stringify([row.game_key, row.market.period, row.market.market]);
}

function groupRows(rows, keyFor) {
  const groups = new Map();
  for (const row of rows) {
    if (row.withdrawn) continue;
    const key = keyFor(row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  return groups;
}

function rankedCard(group, games, nested = false) {
  const context = cardContext(games);
  context.nested = nested;
  context.game = games.get(group.game_key);
  context.position = offer => position(offer, context.game);
  return evCard(group, context);
}

function rankedGroup(key, marketRows, games, disclosures) {
  const [first, ...rest] = marketRows;
  const card = rankedCard(first, games);
  card.dataset.gameKey = first.game_key;
  if (!rest.length) return card;
  const details = el('details', null, 'ranked-outcomes');
  details.dataset.id = `ev:${key}`;
  details.append(el('summary', `${rest.length} more ${rest.length === 1 ? 'outcome' : 'outcomes'}`));
  const addCards = () => {
    if (details.open && details.childElementCount === 1) details.append(...rest.map(row => rankedCard(row, games, true)));
  };
  details.open = disclosures.get(details.dataset.id) || rest.some(row => row.id === restoreLocation?.groupId);
  addCards();
  details.addEventListener('toggle', addCards);
  card.append(details);
  return card;
}

function render(page, keepNodes = false) {
  $('positive-field').hidden = browse;
  const results = $('results');
  const focus = keepNodes && captureResultsFocus(results);
  const content = document.createDocumentFragment();
  const disclosures = new Map([...disclosureStates(), ...restoreLocation?.disclosures || []]);
  const tableScrolls = matrixPositions();
  const games = new Map((page.games || []).map(game => [game.game_key, game]));
  const rows = displayRows(page);
  const total = page.total || 0;
  const selectedLine = page.selected_line_id || requestedLine;
  if (gameKey) {
    const resolved = page.selected_game_key || gameKey;
    const matchup = games.get(resolved);
    const first = rows.find(row => !row.withdrawn && row.game_key === resolved);
    const title = first?.game_title || matchup?.title || linkedTitle;
    if (title) {
      $('title').textContent = title;
      $('desk-subtitle').textContent = matchup || first ? occurrenceLabel(matchup, first) : '';
      $('desk-subtitle').hidden = !matchup && !first;
      const identity = gameIdentityNote(matchup?.game_identity_status ? matchup : first);
      $('game-identity').textContent = identity || '';
      $('game-identity').hidden = !identity;
      document.title = `Predict · ${title}`;
    }
  }
  const publication = page.publication || {};
  const issue = replay ? null : collectionIssue(publication.data_runtime)
    || (publication.state === 'failed' ? 'Price publication is delayed' : null);
  const hasQuotedOffers = publication.current_prices || publication.posted_prices
    || afterFeeView && page.matched_offer_count;
  const emptyIssue = !rows.length && !hasQuotedOffers ? issue : null;
  const awaitingPrices = opportunityView && page.state === 'initializing'
    && !rows.length && !publication.retained_prices;
  const readiness = $('desk-readiness');
  readiness.hidden = !awaitingPrices;
  if (awaitingPrices) {
    const start = emptyResults(page, publication, emptyIssue);
    if (!readiness.firstElementChild?.isEqualNode(start)) readiness.replaceChildren(start);
  } else if (readiness.hasChildNodes()) readiness.replaceChildren();
  $('replay-link').hidden = awaitingPrices;
  $('practice-link').hidden = replay || browse || arb && !rows.length;
  if (opportunityView) $('browse-link').classList.toggle('desk-primary', !awaitingPrices);
  const notice = [];
  if (replay && page.replay?.captured_at) notice.push(`Captured ${clock(page.replay.captured_at)}.`);
  if (!replay) {
    if (!emptyIssue) {
      notice.push('Odds may be delayed.');
      if (issue) notice.push(`${issue}.`);
    }
    if (!publication.data_runtime?.stopped) notice.push(...sourceNotices(publication));
  }
  if (state.resetReason) notice.push(state.resetReason);
  $('notice').textContent = notice.join(' ');
  if (arb && page.pair_status?.withheld) {
    const withheld = el('p', `${page.pair_status.withheld} pairing(s) lack a payoff under these filters. `, 'desk-note');
    withheld.append(button('Show unavailable pairings', () => {
      for (const key of ['positive', 'minimum']) {
        if (key === 'positive') filters.elements[key].checked = false;
        else filters.elements[key].value = '';
      }
      applyFilters();
    }));
    content.append(withheld);
  }
  const pinnedRow = selectedLine && rows.find(row => row.id === selectedLine && !row.withdrawn);
  const pinnedAvailable = pinnedRow && (replay || pinnedRow.offers.some(offer =>
    offer.odds?.american && (!page.selected_venues || page.selected_venues.includes(offer.venue))));
  if (focusSelectedLine && page.state === 'ready' && !pinnedAvailable) {
    content.append(el('p', `${linkedLine || 'The selected line'} is unavailable for this matchup in the selected view.`, 'desk-note selected-line-unavailable'));
  }
  if (practice && page.practice_ticket && rows.length) {
    for (const group of rows) content.append(ticketCard(group, cardContext(games)));
  } else if (browse && rows.length) {
    const groups = groupRows(rows, row => row.game_key);
    const compactGames = !replay && !gameKey && page.row_kind === 'games' && total > 3;
    for (const [key, matrixGroup] of groups) {
      const first = matrixGroup[0];
      const context = cardContext(games, !gameKey && first.game_title);
      const occurrence = games.get(key);
      context.occurrenceLabel = occurrenceLabel(occurrence, first);
      context.identityNote = gameIdentityNote(occurrence?.game_identity_status ? occurrence : first);
      context.selectedVenues = page.selected_venues;
      context.position = offer => position(offer, games.get(first.game_key));
      const id = `odds:${key}`;
      const disclosure = compactGames ? {id, open:disclosures.get(id) ?? key === groups.keys().next().value} : null;
      content.append(gameMatrix(matrixGroup, context, {includeAlternates:$('alternates').checked, market:marketFamily,
        selectedLine:pinnedAvailable ? selectedLine : null, disclosure}));
    }
    if (!groups.size) content.append(emptyResults(page, publication));
  } else if (!arb && page.row_kind === 'games' && rows.length) {
    const groupKey = opportunityView ? marketGroupKey : row => row.game_key;
    for (const [key, marketRows] of groupRows(rows, groupKey)) content.append(rankedGroup(key, marketRows, games, disclosures));
    if (!content.firstChild) content.append(emptyResults(page, publication));
  } else if (rows.length) {
    for (const group of rows) {
      if (group.withdrawn) {
        content.append(el('p', `${group.game_title}: ${group.reason}`, 'desk-note'));
        continue;
      }
      const context = cardContext(games);
      context.game = games.get(group.game_key);
      context.position = offer => position(offer, context.game);
      content.append(arb ? arbCard(group, context, disclosures.get(group.id)) : evCard(group, context));
    }
  } else if (!awaitingPrices) {
    content.append(emptyResults(page, publication, emptyIssue));
  }
  if (keepNodes) {
    const previous = [...results.children];
    const next = [...content.children];
    for (const [index, node] of next.entries()) {
      const old = previous[index];
      if (!old) results.append(node);
      else if (!old.isEqualNode(node)) old.replaceWith(node);
    }
    for (const node of previous.slice(next.length)) node.remove();
  } else results.replaceChildren(content);
  restoreMatrices(tableScrolls);
  if (focus && !focus.node.isConnected) {
    const area = [...results.querySelectorAll(focus.selector)].find(focus.matchesArea);
    const replacement = area && focus.controls(area)[focus.index];
    if (replacement) restoreFocus(replacement);
  }
  updateMatrixCues(results);
  scheduleResultExpiry();
  const shown = page.page_count ?? rows.length;
  const unit = page.row_kind === 'games' ? 'games' : 'results';
  $('page-range').textContent = shown ? `${state.offset + 1}–${state.offset + shown} of ${total} ${unit}` : '';
  $('previous').disabled = state.offset === 0;
  $('next').disabled = state.offset + shown >= total;
  const singlePage = $('previous').disabled && $('next').disabled;
  $('previous').hidden = $('next').hidden = singlePage;
  $('previous').parentElement.hidden = !!gameKey || !total || singlePage;
  if (revealMarket && page.state !== 'initializing') {
    const first = results.querySelector('.odds-matrix tbody tr, .matrix-empty, .desk-empty');
    const bottom = first?.getBoundingClientRect().bottom;
    if (bottom > innerHeight - 12) window.scrollBy({top:bottom - innerHeight + 12, behavior:'instant'});
    revealMarket = false;
  }
}

if (opportunityView) {
  const action = browsingLink('Find my game ↗', null, 'desk-action desk-primary');
  action.id = 'browse-link';
  $('browse-link').replaceWith(action);
}

let restoreLocation = restored || (gameKey && requestedLine ? {groupId:requestedLine} : null);

function restoreLocationAfterLoad() {
  if (!restoreLocation) return;
  const {openerTop, groupId, gameKey:anchorGame, openerHref, sourceEvent, scrollY, tableScrolls, oddsFormat} = restoreLocation;
  restoreLocation = null;
  if (window.history.state?.predictDesk) {
    const {predictDesk, ...entry} = window.history.state;
    window.history.replaceState(entry, '');
  }
  restoreMatrices(tableScrolls);
  if (oddsFormat) window.PredictUI.setOddsFormat(oddsFormat);
  const targetId = (gameKey && state.page?.selected_line_id) || groupId;
  const row = targetId && [...$('results').querySelectorAll('[data-group-id]')]
    .find(item => item.dataset.groupId === targetId);
  const card = [...$('results').querySelectorAll('.odds-card')].find(item =>
    item.dataset.gameKey === anchorGame || sourceEvent && item.dataset.sourceEvent === sourceEvent);
  const opener = openerHref && [...document.querySelectorAll('main a')]
    .find(item => item.href === openerHref && item.getClientRects().length);
  const target = opener || (openerHref && row?.querySelector('[data-line-launcher]'))
    || (row?.closest('.odds-card') || card || row)?.querySelector('[data-game-launcher]')
    || row?.querySelector('a,button');
  if (target && openerTop != null && state.page?.anchor_state !== 'removed') {
    window.scrollBy(0, target.getBoundingClientRect().top - openerTop);
  }
  else if (scrollY != null) window.scrollTo(0, scrollY);
  else if (!gameKey || row?.matches('[aria-current=true]')) row?.scrollIntoView({block:'nearest'});
  if (target && state.page?.anchor_state !== 'removed') target.focus({preventScroll:true});
  else if (openerHref) {
    const results = $('results');
    const nearby = [...results.querySelectorAll('[data-game-launcher], .opportunity-card a')]
      .sort((a, b) => Math.abs(a.getBoundingClientRect().top - (openerTop ?? 0))
                    - Math.abs(b.getBoundingClientRect().top - (openerTop ?? 0)))[0];
    const heading = results.querySelector('h2');
    if (heading) heading.tabIndex = -1;
    const fallback = nearby || heading || $('refresh-list');
    fallback.focus({preventScroll:true});
    fallback.scrollIntoView({block:'nearest'});
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
      signal?.addEventListener('abort', () => landing.controller.abort(), {once:true});
      const initial = await landing.promise;
      if (initial) return initial;
    } else landing.controller.abort();
  }
  const response = await fetch(url, {signal});
  if (!response.ok) {
    throw Error('Unavailable');
  }
  return response.json();
}

function matchesInputs(signature) {
  return signature === JSON.stringify(selections());
}

function captureResultsFocus(results) {
  const node = document.activeElement;
  if (!results.contains(node)) return null;
  const selector = '[data-group-id], [data-game-key]';
  const area = node.closest(selector);
  if (!area) return null;
  const groupId = area.dataset.groupId;
  const game = area.closest('[data-game-key]')?.dataset.gameKey;
  const matchesArea = candidate => candidate.dataset.groupId === groupId
    && candidate.closest('[data-game-key]')?.dataset.gameKey === game;
  const key = ['data-desk-quote-key', 'data-offer-id', 'data-pair-id', 'data-calculation-id', 'aria-controls', 'href', 'aria-label']
    .find(attribute => node.hasAttribute(attribute));
  const controls = scope => [...scope.querySelectorAll(node.localName)]
    .filter(candidate => candidate.closest(selector) === scope
      && (!key || candidate.getAttribute(key) === node.getAttribute(key)));
  return {node, selector, matchesArea, controls, index:controls(area).indexOf(node)};
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
const usingResults = () => resultPointer != null || $('quote-gap').open
  || !!$('results').querySelector('.matrix-sportsbook-popout[open]');

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
  $('auto-update-field').hidden = !supportsAutoUpdate(page);
}

function previousResults(message = '') {
  if (state.previousReason === message) return;
  const anchor = scrollY ? visibleAnchor() : null;
  state.previousReason = message;
  const notice = $('previous-results');
  notice.textContent = message;
  notice.hidden = !message;
  restoreAnchor(anchor);
}

function expireResultValues() {
  if (replay || !state.page) return;
  const current = expirePage(state.page, Date.now(), expiryOptions());
  if (current === state.page) return;
  const anchor = scrollY ? visibleAnchor() : null;
  state.page = current;
  state.renderSignature = resultSignature(current);
  render(current, true);
  restoreAnchor(anchor);
}
function expiryOptions() {
  const fields = filters.elements;
  return {ranked:opportunityView && !arb, live:phase === 'live',
    netFilter:arb && Boolean(fields.positive.checked || fields.minimum.value || fields.profit?.value)};
}
let resultExpiryTimer;
function scheduleResultExpiry() {
  clearTimeout(resultExpiryTimer);
  if (replay || !state.page) return;
  const now = Date.now();
  const due = nextDeskDeadline(state.page, now, {live:phase === 'live'});
  if (!Number.isFinite(due)) return;
  resultExpiryTimer = setTimeout(() => {
    drawer.expireInspection();
    expireResultValues();
    scheduleResultExpiry();
  }, Math.max(1, due - now));
}
$('results').addEventListener('toggle', () => queueMicrotask(() => {
  expireResultValues();
  scheduleResultExpiry();
}), true);

function anchorTarget(row) {
  return row.querySelector('h2, h3, th[scope=row]') || row;
}

function visibleAnchor() {
  const scrollY = window.scrollY;
  const results = $('results');
  const rows = [...results.querySelectorAll('[data-group-id]')];
  const candidates = [...rows, ...[...results.children].filter(item => item.dataset.gameKey && !item.dataset.groupId)];
  const visible = candidates.map(item => ({item, rect:anchorTarget(item).getBoundingClientRect()}))
    .filter(({rect}) => rect.height && rect.bottom > 0 && rect.top < window.innerHeight)
    .sort((a, b) => a.rect.top - b.rect.top)[0];
  const item = visible?.item || candidates[0];
  return {scrollY, top:visible?.rect.top, gameKey:item?.closest('[data-game-key]')?.dataset.gameKey,
    groupId:item?.dataset.groupId};
}

function restoreAnchor(anchor) {
  if (!anchor) return;
  const results = $('results');
  const exact = anchor.groupId && [...results.querySelectorAll('[data-group-id]')]
    .find(row => row.dataset.groupId === anchor.groupId && anchorTarget(row).getClientRects().length);
  const item = exact || [...results.children].find(child => anchor.gameKey && child.dataset.gameKey === anchor.gameKey);
  if (item && anchor.top != null) window.scrollBy(0, anchorTarget(item).getBoundingClientRect().top - anchor.top);
  else window.scrollTo(0, anchor.scrollY);
}

function updatesReady(value) {
  $('updates-ready').hidden = !value;
  $('refresh-list').classList.toggle('has-update', value);
}

function resultSignature(page) {
  const stripReadClock = rows => rows?.map(row => ({...row, offers:row.offers?.map(offer => {
    if (!offer.live_native_desk && !offer.live_aggregate_desk) return offer;
    const {captured_at, ...stable} = offer;
    return stable;
  })}));
  const {data_runtime:runtime = {}, sources} = page.publication || {};
  return JSON.stringify([stripReadClock(page.rows), page.games, page.retained_game,
    page.total, page.page_count, page.offset, page.pair_status, page.calculation_reason, page.calculation_missing,
    page.state, page.basis, page.phase, page.anchor_state, page.selected_line_id, page.selected_game_key,
    page.selected_venues, page.qualified_offer_count,
    page.qualified_board_offer_count, page.blocker_counts,
    page.ranked_group_count, page.matched_offer_count, runtime.stopped, runtime.healthy, runtime.reason, runtime.paused_sources,
    Object.values(sources || {}).map(source => [source.state, source.reason_code])]);
}

async function load(offset = state.offset, {background = false, freshMembership = false, anchor = null, refresh = false} = {}) {
  if (!filters.checkValidity()) return;
  if (background && state.request) return;
  state.request?.abort();
  const controller = new AbortController();
  state.request = controller;
  state.backgroundRequest = background;
  refreshStatus();
  const selected = selections();
  const requestFilters = JSON.stringify(selected);
  const readMember = (background && state.backgroundPage) || state.page;
  const query = new URLSearchParams({...selected, layout: 'desk', view: arb ? 'arbs' : 'ev',
    offset:freshMembership ? 0 : background ? readMember?.offset ?? offset : offset, limit:pageLimit});
  if (!replay) {
    query.set('summary', '1');
    if (refresh) query.set('refresh', '1');
  }
  if (replay) query.set('dataset', dataset);
  if (retainedResult) query.set('result_id', retainedResult);
  const browseId = (state.query === requestFilters ? readMember?.browse_id : null) ?? restoreLocation?.browseId;
  if (!replay && !freshMembership && browseId && (offset || restoreLocation?.browseId)) query.set('browse_id', browseId);
  const locator = restoreLocation || (freshMembership && anchor);
  if (!gameKey && locator && (locator.groupId || locator.gameKey)) {
    query.set('locate', locator.groupId || locator.gameKey);
    if (locator.gameKey) query.set('locate_game', locator.gameKey);
    if (freshMembership && restoreLocation) query.set('offset', restoreLocation.offset || 0);
  }
  if (!state.page && !state.loadFailed) $('notice').textContent = 'Loading prices…';
  const backgroundBlocked = () => background && (!receivingUpdates() || usingResults()
    || !supportsAutoUpdate() && drawer.isOpen());
  try {
    let page = await fetchPage(query, controller.signal);
    if (controller.signal.aborted || !matchesInputs(requestFilters) || backgroundBlocked()) return;
    const emptyPage = !displayRows(page).length;
    if (page.state === 'page_changed' || query.has('browse_id') && emptyPage && (page.total || page.anchor_state === 'removed')) {
      if (freshMembership) throw Error('Browsing order unavailable');
      const reason = page.reason || 'The comparison order changed.';
      history.record('browsing_reset', {reason});
      if (!background) state.resetReason = reason;
      if (restoreLocation) {
        restoreLocation.browseId = null;
      }
      state.request = null;
      return load(0, {background, freshMembership:true, anchor:anchor || visibleAnchor()});
    }
    if (!background && page.anchor_state === 'removed') {
      state.resetReason = 'The previous game or line is no longer in these results.';
    } else if (!background && page.anchor_state === 'game') {
      state.resetReason = 'The previous line left these results. Other prices for the game are shown.';
    } else if (!background && restoreLocation && browse && !gameKey && page.state === 'ready') {
      const cached = readBrowseReturn();
      if (cached?.url === location.href && cached.navigation?.openerHref === restoreLocation.openerHref
          && cached.inspectedQuote && !displayRows(page).some(row => row.offers.some(offer =>
            (offer.desk_quote_key || offer.id) === cached.inspectedQuote))) {
        state.resetReason = 'The inspected quote is no longer in these results.';
      }
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
    if (controller.signal.aborted || !matchesInputs(requestFilters) || backgroundBlocked()) return;
    if (!replay) page = expirePage(page, Date.now(), expiryOptions());
    applyDeskFeatures(page);
    const held = background && displayRows(state.page).length && state.page.phase === page.phase;
    const prior = background && !restoreLocation && scrollY ? anchor || visibleAnchor() : anchor;
    if (held) {
      state.backgroundPage = {offset:page.offset, browse_id:page.browse_id};
      const result = holdDeskPage(state.page, page);
      page = result.page;
      updatesReady(result.changed);
    } else {
      state.backgroundPage = null;
      updatesReady(false);
    }
    const signature = resultSignature(page);
    const repaint = !background || !state.page || state.renderSignature !== signature || state.resetReason;
    state.page = page;
    state.loadFailed = false;
    state.query = JSON.stringify(selections());
    state.renderSignature = signature;
    state.offset = page.offset ?? (freshMembership ? 0 : offset);
    previousResults();
    if (repaint) {
      render(page, held);
      restoreAnchor(prior);
    }
    expireResultValues();
    state.resetReason = null;
    restoreLocationAfterLoad();
    history.observe(page, selections());
    drawer.checkSelection(refresh);
  } catch (error) {
    if (!controller.signal.aborted && error.name !== 'AbortError' && matchesInputs(requestFilters)) {
      if (state.page && !replay) {
        state.loadFailed = true;
        previousResults('Price update failed. Showing previous results.');
      }
      else {
        state.loadFailed = true;
        $('notice').textContent = replay ? 'Saved odds could not be loaded.' : 'Prices could not be loaded.';
      }
      history.record('display_gap',{reason:'local_read_failed'});
    }
  } finally {
    if (state.request === controller) {
      state.request = null;
      state.backgroundRequest = false;
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
  for (const [key, prefix] of [['day',''], ['game_state',''], ['period',''], ['minimum','Min return ']]) {
    const field = filters.elements[key];
    if (field.value) {
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
  if (!gameKey) marketTabs();
  validateTimeWindow();
  refreshStatus();
  clearTimeout(debounce);
  state.request?.abort();
  if (!filters.checkValidity()) return;
  if (browse && !gameKey) saveBrowsePreferences();
  else if (!gameKey) {
    const savedFilters = selections();
    savePreference(filterKey(), JSON.stringify({...savedFilters, timezone:filters.elements.timezone.value}));
  }
  if (browse && !replay) {
    let ordinary = {};
    try { ordinary = JSON.parse(readPreference(evFilterKey, '{}')) || {}; } catch {}
    savePreference(evFilterKey, JSON.stringify({...ordinary, basis:filters.elements.basis.value}));
  }
  for (const action of document.querySelectorAll('main a')) {
    const destination = deskLinks.get(action);
    if (destination) action.href = destination();
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
filters.addEventListener('input', event => {
  if (event.target !== autoUpdateToggle) applyFilters();
});
filters.elements.basis.disabled = false;
$('reset').onclick = () => {
  const {value: basis} = filters.elements.basis;
  const {value: group} = filters.elements.group;
  filters.reset();
  filters.elements.basis.value = basis;
  filters.elements.group.value = group;
  for (const field of filters.querySelectorAll('fieldset input')) field.checked = true;
  applyFilters();
};
activeFilters();
marketTabs();
validateTimeWindow();
function refreshDesk() {
  if ($('refresh-list').getAttribute('aria-disabled') === 'true') return;
  const sameFilters = state.query === JSON.stringify(selections());
  const anchor = sameFilters && (state.offset || scrollY) ? visibleAnchor() : null;
  load(sameFilters ? state.offset : 0, {freshMembership:!!state.page?.browse_id && (!state.offset || !!anchor), anchor, refresh:true});
}
$('refresh-list').onclick = refreshDesk;
autoUpdateToggle.onchange = () => {
  autoUpdate = autoUpdateToggle.checked;
  savePreference(autoUpdateKey, autoUpdate ? 'on' : 'off');
  if (autoUpdate) refreshDesk();
  else {
    if (state.backgroundRequest) state.request?.abort();
    updatesReady(false);
    drawer.checkSelection();
  }
  refreshStatus();
  scheduleUpdates();
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
document.addEventListener('visibilitychange', () => {
  if (document.hidden) return;
  expireResultValues();
  scheduleResultExpiry();
});
const scheduleUpdates = createDeskPolling({state, replay, arb, currentPhase:() => phase, drawer, expireResultValues,
  receivingUpdates, supportsAutoUpdate, usingResults, visibleAnchor, load, selections, previousResults});

load(restored?.offset ?? 0);
drawer.openHistorical(route.get('result_id'), route.get('selection'));
scheduleUpdates();
