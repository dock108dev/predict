import './experiment-populations.js';
import {mountDatabase} from './admin-database.js';
import {byId, count, details, label, link, node, pairs, readJSON, stack, table, time} from './workspace-ui.js';
import {odds, percent, selection, venue} from './workspace-format.js';
import {coverageURL, renderCoverage} from './mens-d1-coverage.js';

const views = ['observations', 'pulls', 'checkpoints', 'populations', 'mens-d1', 'tables'];
const filters = ['date', 'sport', 'search', 'event_id', 'provider', 'original_bookmaker_id', 'family'];
const pullForm = byId('pull-workbench-form');
const resultForm = byId('data-result-filters');
const checkpointForm = byId('checkpoint-filters');
const pullDetail = byId('pull-detail');
const pullStatus = byId('pull-status');
const pullRows = byId('pull-rows');
const currentQuery = () => new URLSearchParams(location.search);
const displaySource = id => ({sportsgameodds:'SportsGameOdds', college_basketball_data:'CollegeBasketballData', sports_reference:'Sports Reference'})[id] || label(id);
let revision = 0;
let databaseMounted = false;

function select(query, keys) {
  return new URLSearchParams(keys.filter(key => query.get(key)).map(key => [key, query.get(key)]));
}

function dataHref(query) {
  return '/data' + (query.size ? '?' + query : '');
}

function optionLink(title, query, values = {}, cleared = []) {
  const next = new URLSearchParams(query);
  for (const name of cleared) next.delete(name);
  for (const [name, value] of Object.entries(values)) next.set(name, value);
  return link(title, dataHref(next), 'research-button');
}

function formQuery(form) {
  return new URLSearchParams([...new FormData(form)]
    .filter(([, value]) => value.trim())
    .map(([key, value]) => [key, value.trim()]));
}

function syncForm(form, query) {
  for (const field of form.elements) if (field.name) field.value = query.get(field.name) || '';
}

function createFromFilters(query) {
  const result = select(query, ['date', 'date_from', 'date_to', 'sport', 'provider', 'scope',
    'search', 'original_bookmaker_id', 'family', 'calculation_status', 'pull', 'receipt', 'include_alternates', 'max_age_minutes']);
  if (query.get('reference_scope') === 'all') result.set('reference_scope', 'all');
  const game = query.get('event_id') || query.get('game') || query.get('game_key');
  if (game) result.set('game', game);
  result.set('view', 'create');
  result.set('from', 'data');
  return '/experiments?' + result;
}

function updateCreateLink(query) {
  const action = byId('data-create-experiment');
  action.href = createFromFilters(query);
}

function pagination(query, value, size, name = 'offset', title = 'pages') {
  const nav = node('nav', undefined, 'catalog-pagination');
  nav.setAttribute('aria-label', title);
  if (value.offset > 0) nav.append(optionLink('Previous', query, {[name]:Math.max(0, value.offset - size)}));
  if (value.rows.length) nav.append(node('span', `${count(value.offset + 1)}–${count(value.offset + value.rows.length)}`));
  if (value.next_offset != null) nav.append(optionLink('Next', query, {[name]:value.next_offset}));
  return nav;
}

function collectionLinks(receipt, query, exact, eventId) {
  const row = node('div', undefined, 'data-browser-links');
  if (receipt) {
    row.append(optionLink('Inspect original response', query, {receipt}, ['offset']),
      link('Download original response', '/api/research/data/original?' + new URLSearchParams({id:receipt, download:'1'}), 'research-button'));
  }
  if (eventId) row.append(link('Find sporting result', dataHref(new URLSearchParams({evidence:'populations', event_id:eventId})), 'research-button'));
  if (exact) row.append(link('Find game observations', dataHref(new URLSearchParams({view:'history', event_id:eventId})), 'research-button'));
  return row;
}

function quoteRows(rows, title) {
  const grid = table(['Game', 'Bet', 'Venue / odds', 'Status', 'Evidence'], rows.map(row => {
    const status = percent(row.calculation?.net_ev_percent) ||
      (row.available === false ? 'Unavailable' : row.calculation ? 'EV unavailable' : 'Source price');
    const evidence = node('details');
    const summary = node('summary', row.calculation ? 'Normalized record and calculation' : 'Received record');
    evidence.append(summary);
    evidence.addEventListener('toggle', () => {
      if (evidence.open && evidence.childElementCount === 1) evidence.append(node('pre', JSON.stringify(row.record, null, 2)));
    });
    return [
      stack(row.game || 'Game title unavailable', time(row.starts_at)),
      stack(selection({...row, selection_label:row.selection}), [label(row.family), row.alternate && 'Alternate'].filter(Boolean).join(' · ')),
      stack(venue(row.original_bookmaker_id), odds(row.price, row.price_units)),
      stack(status, row.reason || row.calculation?.reason ? label(row.reason || row.calculation.reason) : time(row.received_at)),
      evidence,
    ];
  }));
  grid.querySelector('table').setAttribute('aria-label', title);
  return grid;
}

function renderReceipts(value, query) {
  if (!value.receipts.length) return node('p', 'No accepted physical response is recorded for this attempt.');
  const proof = node('section');
  proof.append(node('h3', 'Original responses'));
  const records = value.receipts.map(receipt => {
    const evidence = details('Receipt identity and returned events', receipt);
    const related = collectionLinks(receipt.original?.id, query);
    const box = node('div');
    box.append(evidence);
    if (related.childElementCount) box.append(related);
    return [
      time(receipt.received_at),
      stack(receipt.original ? 'Exact response retained' : 'Original bytes unavailable', receipt.retention_reason ? label(receipt.retention_reason) : ''),
      box,
    ];
  });
  proof.append(table(['Received', 'Original response', 'Evidence'], records), pagination(query, {
    offset:value.receipt_offset, rows:records, next_offset:value.next_receipt_offset,
  }, 25, 'receipt_offset', 'Original response pages'));
  return proof;
}

function renderPull(value, query) {
  const pull = value.pull;
  const event = pull.details?.event;
  pullStatus.textContent = pull.state === 'complete' ? 'Recorded odds pull available.' : `Recorded pull is ${label(pull.state)}.`;
  pullDetail.append(optionLink('Back to odds pulls', query, {}, ['pull', 'receipt', 'offset', 'receipt_offset']),
    node('h3', event?.title || (pull.request_scope?.leagueID ? 'League discovery pull' : 'Game odds pull')),
    pairs({
      'Source':displaySource('sportsgameodds'), 'Requested':time(pull.requested_at), 'State':label(pull.state),
      'Coverage':event?.league || pull.request_scope?.leagueID || pull.request_scope?.eventIDs,
      ...pull.details?.reason && {'Recorded reason':label(pull.details.reason)},
    }),
    details('Pull identity, request scope and snapshot hash', pull),
    renderReceipts(value, query));
  const eventId = event?.source_event_id || (pull.request_scope?.eventIDs?.includes(',') ? null : pull.request_scope?.eventIDs);
  if (eventId) pullDetail.append(collectionLinks(null, query, true, eventId));
  if (query.get('receipt')) return;
  pullRows.append(node('h3', 'Records in this pull'));
  if (!value.rows.length) {
    pullRows.append(node('p', pull.sha256 ? 'No records match these filters.' : 'Open an original response above to inspect received records.'));
    return;
  }
  pullRows.append(node('p', `${count(value.total_records)} matching records`),
    quoteRows(value.rows, 'Odds pull records'), pagination(query, value, 50, 'offset', 'Odds pull record pages'));
}

function renderOriginal(value, query) {
  const actions = node('div', undefined, 'data-browser-links');
  actions.append(optionLink('Close original response', query, {}, ['receipt', 'offset']),
    link('Download original response', '/api/research/data/original?' + new URLSearchParams({id:value.receipt.id, download:'1'}), 'research-button'));
  pullRows.append(node('h3', 'Original response records'), actions, pairs({
    'Received':time(value.receipt.received_at), 'Provider':displaySource(value.receipt.provider),
    'Returned games':value.events, 'Matching records':count(value.total_records),
  }), details('Response hash, physical request and retention', value.receipt));
  if (!value.rows.length) pullRows.append(node('p', value.reason || 'No received records match these filters.'));
  else pullRows.append(quoteRows(value.rows, 'Records in the original response'), pagination(query, value, 50, 'offset', 'Original record pages'));
}

async function loadPull(query, version) {
  pullStatus.textContent = 'Reading stored odds pulls…';
  pullDetail.replaceChildren();
  pullRows.replaceChildren();
  const params = select(query, [...filters, 'offset', 'receipt_offset', 'pull']);
  try {
    if (query.get('pull')) {
      if (query.get('receipt')) params.delete('offset');
      const result = await readJSON('/api/research/data/pull?' + params);
      if (version !== revision) return;
      renderPull(result, query);
      if (query.get('receipt')) {
        const original = select(query, [...filters, 'offset']);
        original.set('id', query.get('receipt'));
        const value = await readJSON('/api/research/data/original?' + original);
        if (version === revision) renderOriginal(value, query);
      }
      return;
    }
    if (query.get('receipt')) {
      const original = select(query, [...filters, 'offset']);
      original.set('id', query.get('receipt'));
      const value = await readJSON('/api/research/data/original?' + original);
      if (version === revision) {
        pullStatus.textContent = 'Stored original response available.';
        renderOriginal(value, query);
      }
      return;
    }
    params.delete('receipt_offset');
    const value = await readJSON('/api/research/data/pulls?' + params);
    if (version !== revision) return;
    pullStatus.textContent = value.rows.length ? 'Select a recorded pull.' : 'No odds pulls match these filters.';
    if (!value.rows.length) return;
    pullRows.append(table(['Game or scope', 'Requested', 'Source', 'State', 'Evidence'], value.rows.map(row => [
      stack(row.event?.title || row.league || row.event_ids || 'Discovery pull', row.event?.starts_at ? time(row.event.starts_at) : ''),
      time(row.requested_at), displaySource('sportsgameodds'), stack(label(row.state), row.reason ? label(row.reason) : ''),
      optionLink('Open odds pull', query, {pull:row.pull_id}, ['offset', 'receipt', 'receipt_offset']),
    ])), pagination(query, value, 25, 'offset', 'Odds pull pages'));
  } catch (error) {
    if (version === revision) pullStatus.textContent = error.message;
  }
}

async function loadResults(query, version) {
  const root = byId('data-sporting-results');
  root.replaceChildren(node('p', 'Reading retained sporting results…'));
  const params = select(query, ['date', 'sport', 'search', 'event_id', 'provider', 'offset', 'id']);
  try {
    const value = await readJSON('/api/research/data/results?' + params);
    if (version !== revision) return;
    if (!value.rows.length) {
      root.replaceChildren(node('p', 'No recorded sporting results match these filters.'));
      return;
    }
    root.replaceChildren(table(['Game', 'Result', 'Source / receipt', 'Evidence'], value.rows.map(game => {
      const result = game.outcome.data || {};
      const score = result.home_score != null && result.away_score != null
        ? `${result.away_score}–${result.home_score} (away–home)` :
        result.teams?.filter(team => team.score != null).map(team => team.name + " " + team.score).join(' · ') || 'Score unavailable';
      const evidence = details('Sporting result and source record', {game:game.event, result:game.outcome});
      if (query.get('id') === game.id) evidence.open = true;
      const box = node('div');
      box.append(evidence);
      const actions = node('div', undefined, 'data-browser-links');
      if (game.original) actions.append(link('Download original response',
        '/api/research/data/original?' + new URLSearchParams({id:game.original, download:'1'}), 'research-button'));
      if (game.receipt_id) actions.append(link('Download source receipt', '/api/workspace/mens-d1/receipts/' + game.receipt_id, 'research-button'));
      if (game.outcome_id) actions.append(link('Game observations',
        dataHref(new URLSearchParams({view:'history', event_id:game.source_event_id})), 'research-button'));
      box.append(actions);
      return [stack(game.title, `${game.league} · ${time(game.starts_at)}`),
        stack(result.final ? 'Final' : label(result.result), score),
        stack(displaySource(result.source), time(result.observed_at)), box];
    })), pagination(query, value, 25, 'offset', 'Sporting result pages'));
  } catch (error) {
    if (version === revision) root.replaceChildren(node('p', error.message));
  }
}

function screen() {
  const version = ++revision;
  const query = currentQuery();
  const active = views.includes(query.get('evidence')) ? query.get('evidence') : 'observations';
  for (const name of views) byId('data-' + name).hidden = name !== active;
  const shared = select(query, filters);
  for (const anchor of document.querySelectorAll('[data-evidence-view]')) {
    const target = anchor.dataset.evidenceView;
    if (target === active) anchor.setAttribute('aria-current', 'page');
    else anchor.removeAttribute('aria-current');
    const next = new URLSearchParams(shared);
    if (target !== 'observations') next.set('evidence', target);
    if (target === 'observations' && (next.get('provider') || next.get('original_bookmaker_id'))) next.set('view', 'history');
    if (target === 'populations') for (const key of ['original_bookmaker_id', 'family']) next.delete(key);
    if (target === 'tables') {
      for (const key of filters) next.delete(key);
    }
    anchor.href = target === 'mens-d1' ? coverageURL(query) : dataHref(next);
  }
  updateCreateLink(query);
  if (active === 'pulls') {
    syncForm(pullForm, query);
    void loadPull(query, version);
  }
  if (active === 'populations') {
    syncForm(resultForm, query);
    void loadResults(query, version);
  }
  if (active === 'checkpoints') syncForm(checkpointForm, query);
  if (active === 'mens-d1') renderCoverage(byId('data-mens-d1'), query, () => version === revision);
  if (active === 'tables' && !databaseMounted) {
    databaseMounted = true;
    mountDatabase();
  }
}

for (const [form, evidence] of [[pullForm, 'pulls'], [resultForm, 'populations'], [checkpointForm, 'checkpoints']]) {
  const apply = (event, clear) => {
    event.preventDefault();
    const previous = currentQuery();
    const query = clear ? new URLSearchParams() : formQuery(form);
    query.set('evidence', evidence);
    if (!clear && previous.get('event_id') && query.get('search') === (previous.get('search') || null)) query.set('event_id', previous.get('event_id'));
    if (evidence === 'checkpoints') {
      if (previous.get('context')) query.set('context', previous.get('context'));
      location.assign(dataHref(query));
      return;
    }
    if (evidence === 'pulls') for (const key of ['pull', 'receipt']) if (previous.has(key)) query.set(key, previous.get(key));
    history.pushState(null, '', dataHref(query));
    screen();
  };
  form.onsubmit = event => apply(event, false);
  form.onreset = event => apply(event, true);
  form.addEventListener('input', () => {
    const query = formQuery(form), previous = currentQuery();
    for (const key of ['event_id', 'pull', 'receipt']) if (previous.has(key)) query.set(key, previous.get(key));
    updateCreateLink(query);
  });
}

byId('catalog-filters').addEventListener('input', () => {
  const query = formQuery(byId('catalog-filters'));
  const previous = currentQuery();
  for (const key of ['game', 'game_key', 'event_id', 'pull']) if (previous.has(key)) query.set(key, previous.get(key));
  updateCreateLink(query);
});
window.addEventListener('predict:data-selection', () => updateCreateLink(currentQuery()));
window.addEventListener('popstate', screen);
screen();
