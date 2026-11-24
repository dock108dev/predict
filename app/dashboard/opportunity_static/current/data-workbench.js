import './experiment-populations.js';
import {inspectExperiment, closeExperiment} from './experiment.js';
import {byId, count, details, label, link, node, pairs, pct, readJSON, stack, table, time} from './workspace-ui.js';
import {number, selection, venue} from './workspace-format.js';

const viewNames = ['observations', 'pulls', 'checkpoints', 'populations'];
const currentQuery = () => new URLSearchParams(location.search);
const pullForm = byId('pull-workbench-form'), day = byId('pull-day'), choice = byId('pull-choice'), filter = byId('pull-filter');
const pullDetail = byId('pull-detail'), pullStatus = byId('pull-status'), pullRows = byId('pull-rows');
let lastRequest = 0, saved;
let lastResultRequest = 0;

function dateInEastern() {
  return new Intl.DateTimeFormat('en-CA', {timeZone:'America/New_York', year:'numeric', month:'2-digit', day:'2-digit'}).format(new Date());
}
function age(at, observed) {
  if (!at || !observed) return 'Age unknown';
  const minutes = Math.floor((Date.parse(at) - Date.parse(observed)) / 60000);
  if (!Number.isFinite(minutes) || minutes < 0) return 'Age unknown';
  if (minutes < 1) return 'Under 1 minute old';
  if (minutes < 60) return `${minutes} min old`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} hr old`;
  return `${Math.floor(minutes / 1440)} days old`;
}
function phase(row) {
  if (!row.starts_at || !row.received_at) return 'Phase unknown';
  return Date.parse(row.received_at) < Date.parse(row.starts_at) ? 'Pre-start at receipt' : 'At or after scheduled start at receipt';
}
function renderRows() {
  if (!saved) return;
  const rows = (saved.observations || []).filter(row => {
    if (filter.value === 'all') return true;
    if (filter.value === 'experiment') return row.meets_pilot_screen === true;
    const ev = number(row.screen_ev);
    return ev != null && ev > 0;
  });
  if (!rows.length) {
    pullRows.replaceChildren(node('p', saved.incomplete_reason || 'No recorded observations match this filter.'));
    return;
  }
  pullRows.replaceChildren(table(['Selection', 'Venue / odds', 'Screening EV', 'Quote clock / phase', 'Evidence'], rows.map(row => {
    const quote = details('Technical details', row);
    const status = row.available === false ? 'Source observation unavailable'
      : row.reason ? label(row.reason) : row.probability == null ? 'Probability unavailable' : pct(row.probability) + ' probability';
    return [
      stack(selection({ ...row, selection_label:row.label }), label(row.family)),
      stack(venue(row.venue), row.posted_odds),
      stack(pct(row.screen_ev), status),
      stack(`Received ${time(row.received_at)}`, `${age(saved.as_of, row.source_at || row.received_at)} · ${phase(row)}${row.source_at ? ' · Source clock ' + time(row.source_at) : ' · Age based on receipt'}`),
      quote,
    ];
  })));
}
async function loadPull(selected = '') {
  const version = ++lastRequest;
  saved = null;
  pullRows.replaceChildren();
  pullDetail.replaceChildren();
  pullStatus.textContent = 'Reading the stored acquisition attempt…';
  const query = new URLSearchParams({date:day.value});
  if (selected) query.set('pull', selected);
  try {
    const value = await readJSON('/api/research/paper/latest?' + query);
    if (version !== lastRequest) return;
    saved = value;
    const pulls = value.recent_pulls || [];
    choice.replaceChildren(new Option('Newest covering attempt', ''), ...pulls.map(item => new Option(
      `${time(item.requested_at)} · ${label(item.state)}${item.title ? ' · ' + item.title : ''}`, item.pull_id,
    )));
    if (selected && !pulls.some(item => item.pull_id === selected)) choice.add(new Option('Bookmarked acquisition attempt', selected));
    choice.value = selected;
    const pull = value.pull;
    if (!pull) {
      pullStatus.textContent = 'No acquisition attempt is recorded for this selection.';
      return;
    }
    const complete = pull.state === 'complete' && !value.incomplete_reason;
    pullStatus.textContent = value.incomplete_reason || (complete ? 'Stored acquisition attempt available.' : 'This attempt is incomplete or unavailable.');
    const panel = node('div', undefined, 'workspace-notice');
    panel.dataset.state = complete ? 'screened' : 'incomplete';
    panel.append(node('h3', pull.title || pull.details?.event?.title || 'Acquisition attempt'), pairs({
      'Capture type':'Single odds pull',
      'Experiment eligibility':'Preview only · frozen T−10 capture required',
      State:label(pull.state),
      ...(pull.details?.reason ? {Reason:label(pull.details.reason)} : {}),
      Requested:time(pull.requested_at),
      'Attempt age':age(value.as_of, pull.requested_at),
      'Recorded observations':count(value.observations?.length),
    }));
    if (['complete', 'failed', 'refused', 'cancelled', 'partial'].includes(pull.state)) {
      panel.append(link('Export exact pull and original evidence', '/api/research/paper/latest?' + new URLSearchParams({
        date:day.value, pull:pull.pull_id, export:'1',
      }), 'research-button'));
    }
    panel.append(details('Acquisition scope, identity and recorded gaps', {
      pull, scopes:value.scopes, evidence_identity:value.evidence_identity, exclusions:value.exclusions,
    }));
    pullDetail.replaceChildren(panel);
    renderRows();
  } catch (error) {
    if (version === lastRequest) pullStatus.textContent = error.message;
  }
}
function saveSelection(selected) {
  const query = currentQuery();
  query.set('evidence', 'pulls');
  query.set('date', day.value);
  if (selected) query.set('pull', selected); else query.delete('pull');
  history.replaceState(null, '', '/data?' + query);
  loadPull(selected);
}
pullForm.onsubmit = event => { event.preventDefault(); saveSelection(choice.value); };
choice.onchange = () => saveSelection(choice.value);
day.onchange = () => { if (day.validity.valid) saveSelection(''); };
filter.onchange = renderRows;
async function loadResults(query) {
  const revision = ++lastResultRequest, root = byId('data-sporting-results');
  const offset = Math.max(0, Number(query.get('offset')) || 0);
  root.replaceChildren(node('p', 'Reading retained sporting results…'));
  if (query.get('id') && query.get('revision')) inspectExperiment(query.get('id'), query.get('revision'), null, null, {updateURL:false});
  else closeExperiment();
  try {
    const value = await readJSON('/api/research/experiment?' + new URLSearchParams({outcomes_only:'1', limit:'10', offset}));
    if (revision !== lastResultRequest) return;
    root.replaceChildren(node('h3', 'Games with recorded sporting results'));
    if (!value.games?.length) root.append(node('p', 'No tracked game with a retained sporting result is available on this page.'));
    else root.append(table(['Tracked game', 'League', 'Sporting evidence'], value.games.map(game => {
      const selected = new URLSearchParams({evidence:'populations', offset, id:game.id, revision:game.revision});
      const action = link('Inspect sporting result', '/data?' + selected, 'research-button');
      action.onclick = event => {
        if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        history.pushState(null, '', action.href);
        inspectExperiment(game.id, game.revision, null, action, {updateURL:false});
      };
      return [stack(game.title, time(game.starts_at)), game.league, action];
    })));
    const pages = node('div', undefined, 'workspace-links');
    if (offset) pages.append(link('Previous sporting results', '/data?evidence=populations&offset=' + Math.max(0, offset - 10)));
    if (value.next_offset != null) pages.append(link('Next sporting results', '/data?evidence=populations&offset=' + value.next_offset));
    if (pages.children.length) root.append(pages);
  } catch (error) {
    if (revision === lastResultRequest) root.replaceChildren(node('p', error.message));
  }
}
function screen() {
  const query = currentQuery(), requested = query.get('evidence');
  const active = viewNames.includes(requested) ? requested : 'observations';
  for (const name of viewNames) byId('data-' + name).hidden = name !== active;
  for (const anchor of document.querySelectorAll('[data-evidence-view]')) {
    if (anchor.dataset.evidenceView === active) anchor.setAttribute('aria-current','page');
    else anchor.removeAttribute('aria-current');
  }
  if (active === 'pulls') {
    day.value = query.get('date') || dateInEastern();
    loadPull(query.get('pull') || '');
  } else ++lastRequest;
  if (active === 'populations') loadResults(query);
  else ++lastResultRequest;
}
window.addEventListener('popstate', screen);
screen();
