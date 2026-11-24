import {count, details, label, link, node, pairs, readJSON, stack, table, time} from './workspace-ui.js';

const endpoint = '/api/workspace/mens-d1';
const easternDay = new Intl.DateTimeFormat('en-CA', {timeZone:'America/New_York', year:'numeric', month:'2-digit', day:'2-digit'});
const dates = [['2026-11-23', 'Nov 23'], ['2026-11-24', 'Nov 24']];
const facets = {
  source_mens:'Men’s games returned', expected:'Expected D1 games', excluded:'Excluded source rows',
  membership_unresolved:'Unverified membership', matched:'Matched to odds', source_only:'Source only',
  provider_only:'Odds provider only', provider_conflict:'Provider identity or schedule conflict',
  result_only:'Result without schedule', no_market:'No market observed', identity_conflict:'Identity conflict',
  schedule_conflict:'Schedule conflict', site_conflict:'Site conflict', retained_eligible:'Eligible in saved scope',
  retained_excluded:'Excluded in saved scope', retained_unresolved:'Unresolved in saved scope',
  provider_scope_eligible:'Provider games with D1 membership', provider_scope_excluded:'Provider games excluded by membership',
  provider_scope_unresolved:'Provider games with unverified membership',
  upcoming:'Upcoming T−10', due:'Due T−10', claimed:'Capture underway', frozen:'Original frozen capture',
  reconstructed:'Retrospective reconstruction', no_task:'No T−10 task', missed:'Missed T−10', failed:'Failed capture',
  refused:'Refused capture', cancelled:'Cancelled capture', superseded_by_reschedule:'Capture superseded',
  evaluated:'Offers evaluated for EV', qualifying_best_venue:'Best venue tickets', qualifying_all_venues:'All venues tickets',
  final:'Verified source final', provider_final:'Provider final evidence', result_pending:'Result pending',
  result_unresolved:'Result unresolved', provider_pending:'Provider result pending',
  provider_result_unresolved:'Provider result unresolved', conflicting:'Conflicting results',
};
const sourceFacets = new Set(['source_mens','expected','excluded','membership_unresolved','matched','source_only',
  'no_market','identity_conflict','schedule_conflict','site_conflict','final','result_pending','result_unresolved','conflicting']);
const offerFacets = new Set(['evaluated','qualifying_best_venue','qualifying_all_venues']);
const paperFacets = new Set([...offerFacets, 'reconstructed']);

export function coverageContext(query, fallbackDate) {
  return Object.fromEntries(Object.entries({
    scope:'mens-d1', date:query.get('date') || fallbackDate || easternDay.format(new Date()),
    coverage_game:query.get('coverage_game'), coverage_filter:query.get('coverage_filter'),
    run:query.get('run'), variant:query.get('variant'),
  }).filter(([,value]) => value));
}

export function coverageURL(query, extra = {}) {
  return '/data?' + new URLSearchParams({evidence:'mens-d1', ...coverageContext(query), ...extra});
}

function researchURL(query, extra = {}) {
  return '/research?' + new URLSearchParams({section:'experiments', ...coverageContext(query), ...extra});
}

export function readDailyCoverage(query) {
  const request = new URLSearchParams({date:query.get('date')});
  if (query.has('run')) request.set('run', query.get('run'));
  if (query.has('coverage_game')) request.set('game', query.get('coverage_game'));
  return readJSON(endpoint + '?' + request);
}

function dateLinks(query, to = coverageURL) {
  const group = node('div', undefined, 'workspace-links');
  for (const [date, title] of dates) {
    const params = date === query.get('date') ? query : new URLSearchParams({date});
    const action = link(title, to(params), 'research-button');
    if (date === query.get('date')) action.setAttribute('aria-current', 'date');
    group.append(action);
  }
  return group;
}

function dateForm(query, path, key, value) {
  const form = node('form', undefined, 'workspace-form');
  form.action = path;
  for (const [name, setting] of [[key, value], ['scope', 'mens-d1']]) {
    const input = node('input');
    input.type = 'hidden';
    input.name = name;
    input.value = setting;
    form.append(input);
  }
  const field = node('label', 'Game date (Eastern)'), input = node('input');
  input.name = 'date';
  input.type = 'date';
  input.required = true;
  input.value = query.get('date');
  field.append(input);
  const submit = node('button', 'Open date');
  submit.type = 'submit';
  form.append(field, submit);
  return form;
}

export function experimentCoverage(query, fallbackDate, run) {
  const context = new URLSearchParams({...coverageContext(query, fallbackDate), ...(run ? {date:run.date, run:run.id} : {})});
  const panel = node('section', undefined, 'workspace-panel workspace-card');
  panel.append(node('h2', 'Men’s Division I daily coverage'), dateLinks(context, researchURL));
  if (!run) panel.append(dateForm(context, '/research', 'section', 'experiments'));
  panel.append(link(`Open ${context.get('date')} coverage in Data`, coverageURL(context)));
  return panel;
}

function state(value) {
  return value ? label(value) : 'Unverified';
}

function age(now, at) {
  const minutes = Math.floor((Date.parse(now) - Date.parse(at)) / 60000);
  if (!Number.isFinite(minutes) || minutes < 0) return 'age unavailable';
  if (minutes < 60) return minutes < 1 ? 'under 1 minute old' : `${minutes} min old`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} hr old`;
  return `${Math.floor(minutes / 1440)} days old`;
}

function observed(at, now) {
  return at ? `${time(at)} · ${age(now, at)}` : 'Not recorded';
}

function teams(row) {
  const sides = Array.isArray(row.teams) ? row.teams : Object.values(row.teams || {});
  return sides.map(team => team.name || team.label || team.id || team).filter(team => typeof team === 'string');
}

function title(row) {
  return row.title || teams(row).join(' vs ') || row.provider_event_id || row.source_game_id;
}

function resultLabel(row) {
  const result = row.result;
  const scored = result?.teams?.length && result.teams.every(team => team.score != null);
  if (row.result_state === 'final' && scored) return result.teams.map(team => `${team.name || team.id} ${team.score}`).join(' · ');
  if (row.result_state === 'provider_final') {
    const scores = row.provider_results?.[0]?.teams || [];
    const byRole = Object.fromEntries((row.teams || []).map(team => [team.role, team.name]));
    if (scores.length && scores.every(team => team.score != null)) return 'Provider final · '
      + scores.map(team => `${byRole[team.role] || team.canonical_id || team.role} ${team.score}`).join(' · ');
    return 'Provider final evidence';
  }
  if (row.result_state) return facets[row.result_state] || state(row.result_state);
  return 'Unresolved';
}

function addReceipt(root, name, id) {
  if (id) root.append(link(name, endpoint + '/receipts/' + encodeURIComponent(id), 'research-button'));
}

function gameDetail(row, value, query) {
  const schedule = row.schedule || {}, result = row.result || {}, capture = row.capture || {}, saved = row.saved || {};
  const root = node('section', undefined, 'workspace-card workspace-panel');
  root.append(node('h3', title(row)), pairs({
    'Source game':row.source_game_id, 'Odds provider game':row.provider_event_id,
    'Source scope':state(row.scope_state), 'Scope reason':row.scope_reason,
    'Provider population membership':row.provider_membership?.state, 'Provider membership reason':row.provider_membership?.reason,
    'Saved scope':row.retained_scope?.state, 'Saved scope reason':row.retained_scope?.reason,
    'Match':state(row.match_state), 'Match reason':row.match_reason,
    'Scheduled start':time(schedule.starts_at || row.starts_at), 'Source date':schedule.source_date,
    'Source time':schedule.source_time, 'Source timezone':schedule.source_timezone, 'Venue/site':schedule.site,
    'Schedule status':state(schedule.status), 'Schedule observed':observed(schedule.observed_at, value.as_of),
    'Schedule published/updated':observed(schedule.published_at, value.as_of), 'Schedule recorded':time(schedule.recorded_at),
    'Schedule source':schedule.source_url, 'Sporting result':resultLabel(row), 'Result reason':row.result_reason,
    'Provider result follow-up':time(row.provider_result_target_at),
    'Result published/updated':observed(result.published_at, value.as_of), 'Result observed':observed(result.observed_at, value.as_of),
    'Result recorded':time(result.recorded_at), 'Result source':result.source_url,
    'Overtime periods':result.overtime_periods,
  }));
  if (result.teams?.length) root.append(table(['Participant', 'Final score', 'Period scores'], result.teams.map(team => [
    team.name || team.id, team.score, team.period_scores?.length ? team.period_scores.join(' · ') : 'Not supplied',
  ])));
  const sources = node('div', undefined, 'workspace-links');
  addReceipt(sources, 'Original schedule receipt', schedule.receipt_id || row.receipt_id);
  addReceipt(sources, 'Original result receipt', result.receipt_id);
  for (const revision of row.result_revisions || []) {
    if (revision.receipt_id !== result.receipt_id) addReceipt(sources, `Other result receipt · ${time(revision.observed_at)}`, revision.receipt_id);
  }
  for (const revision of row.provider_results || []) {
    if (revision.receipt_sha256) sources.append(link(`Provider result response, if retained · ${time(revision.observed_at)}`,
      endpoint + '/provider-results/' + encodeURIComponent(revision.id), 'research-button'));
  }
  root.append(sources);
  if (row.teams || row.retained_scope?.teams) root.append(details('Participant IDs and membership evidence', {
    source:row.teams, saved:row.retained_scope?.teams,
  }));
  if (row.schedule || row.result || row.provider_results?.length) root.append(details('Exact schedule and sporting-result revisions', {
    schedule:row.schedule, source_results:row.result_revisions?.length ? row.result_revisions : row.result,
    competing_provider_results:row.provider_results,
  }));
  root.append(node('h4', 'T−10 capture and paper evidence'), pairs({
    'Original task':state(capture.state), 'Task reason':capture.reason, 'Task target':time(capture.target_at),
    'Task deadline':time(capture.deadline_at), Attempts:capture.attempts, Refusals:capture.refusals,
    'Frozen capture ID':capture.frozen_id, 'Frozen request':time(capture.frozen_requested_at),
    'Frozen receipt':observed(capture.frozen_received_at, value.as_of), 'Frozen known':time(capture.frozen_known_at),
    'Frozen persistence':time(capture.frozen_persisted_at),
    'Saved run disposition':state(saved.status), 'Saved run reason':saved.reason,
    'Saved capture target':time(saved.target_at), 'Saved capture deadline':time(saved.deadline_at),
    'Saved request':time(saved.requested_at), 'Saved receipt':observed(saved.received_at, value.as_of),
    'Saved persistence':time(saved.persisted_at),
    'Retrospective reconstruction time':time(saved.reconstructed_at), 'Offers observed':saved.observed_offer_count,
    'Offers evaluated for EV':saved.evaluated_offers, 'Best venue tickets':saved.qualifying?.best_venue,
    'All venues tickets':saved.qualifying?.all_venues,
  }));
  const captureLinks = node('div', undefined, 'workspace-links');
  if (row.checkpoint_inspect) captureLinks.append(link('Inspect frozen checkpoints and quote clocks',
    row.checkpoint_inspect + '&' + new URLSearchParams(coverageContext(query))));
  if (row.checkpoint_export) captureLinks.append(link('Export checkpoint records', row.checkpoint_export));
  if (saved.evidence_export) captureLinks.append(link('Export this game’s saved run evidence', saved.evidence_export));
  if (saved.checkpoint_id) captureLinks.append(link('Original odds response, if retained', saved.original_response_export));
  root.append(captureLinks);
  const variant = query.get('variant') === 'all_venues' ? 'all_venues' : 'best_venue';
  const tickets = row.ticket_clocks?.[variant] || [];
  if (tickets.length) {
    const context = new URLSearchParams({...coverageContext(query), run:value.run.id, variant});
    const other = variant === 'all_venues' ? 'best_venue' : 'all_venues';
    root.append(node('h4', variant === 'all_venues' ? 'All venues quote clocks' : 'Best venue quote clocks'),
      link(other === 'all_venues' ? 'Show all venues' : 'Show best venue', coverageURL(context, {variant:other})),
      table(['Saved ticket', 'Quote source at receipt', 'Quote receipt'], tickets.map(ticket => [
        link(`${ticket.label} · ${state(ticket.venue)}`, researchURL(context, {ticket:ticket.id})),
        observed(ticket.times?.source_at, ticket.times?.received_at), time(ticket.times?.received_at),
      ])));
  }
  if (saved.exclusions) root.append(details('Why offers did not qualify', saved.exclusions));
  return root;
}

function coverageCounters(value, query, filter, keys) {
  const grid = node('dl', undefined, 'workspace-stats mens-d1-counts');
  for (const key of keys) {
    const title = facets[key];
    const fromSource = sourceFacets.has(key), fromRun = paperFacets.has(key);
    if (key.startsWith('retained_') && !value.run_population) continue;
    const measured = !(fromSource && !value.population_revision || fromRun && !value.run);
    const group = node('div'), term = node('dt', title), total = node('dd');
    const selection = new URLSearchParams(query);
    selection.delete('coverage_game');
    const number = offerFacets.has(key) ? value.offer_counts[key] : value.facets[key] || 0;
    const action = link(measured ? count(number) : 'Unknown', coverageURL(selection, {coverage_filter:key}));
    action.setAttribute('aria-label', `${title}, ${action.textContent}`);
    if (filter === key) action.setAttribute('aria-current', 'true');
    total.append(action);
    group.append(term, total);
    grid.append(group);
  }
  return grid;
}

export async function renderCoverage(root, incoming, isCurrent) {
  const query = new URLSearchParams(coverageContext(incoming));
  const status = node('p', 'Reading retained daily coverage…');
  status.setAttribute('role', 'status');
  root.replaceChildren(node('h2', 'Men’s Division I daily coverage'), dateLinks(query),
    dateForm(query, '/data', 'evidence', 'mens-d1'), status);
  const request = new URLSearchParams({date:query.get('date')});
  if (query.has('run')) request.set('run', query.get('run'));
  if (query.has('coverage_game')) request.set('game', query.get('coverage_game'));
  try {
    const value = await readDailyCoverage(query);
    if (!isCurrent()) return;
    if (value.run) {
      request.set('run', value.run.id);
      query.set('run', value.run.id);
    }
    const canonical = coverageURL(query);
    if (location.pathname + location.search !== canonical) {
      history.replaceState(null, '', canonical + location.hash);
      window.dispatchEvent(new Event('workspace-context'));
    }
    status.textContent = `As of ${time(value.as_of)} · Schedule source ${state(value.source_state)}`;
    const message = value.source_state_reason || value.source_reason;
    if (message) root.append(node('p', state(message), 'workspace-notice'));
    if (!value.population_revision) root.append(node('p', 'The source-declared D1 slate is unverified. Retained odds-provider games and earlier saved runs provide partial coverage.'));
    else root.append(node('p', `Expected counts describe the ${value.date} source slate, observed ${observed(value.source_observed_at, value.as_of)}. Membership and provider disagreements stay visible.`));
    if (value.run_population?.kind === 'retained_original_run') root.append(node('p', 'This retrospective scope correction uses membership evidence for games in the original saved run. Source-declared counts depend on the daily schedule receipt.', 'workspace-notice'));
    if (value.run_population?.kind === 'retained_provider_snapshot') root.append(node('p', 'This saved provider snapshot uses the odds-provider games and season membership known when it was saved. The daily source slate remains unverified.', 'workspace-notice'));
    if (!value.population_revision && !value.run_population) root.append(node('p', 'Capture counts use retained provider games with evidence of D1 membership for both teams.'));
    const actions = node('div', undefined, 'workspace-links');
    actions.append(link(value.run ? 'Open selected experiment' : 'Open Experiments', researchURL(query), 'research-button'));
    request.set('export', '1');
    actions.append(link('Export coverage and reconciliation', endpoint + '?' + request, 'research-button'));
    addReceipt(actions, 'Original daily schedule receipt', value.source_receipt_id);
    if (value.last_source_attempt?.id !== value.source_receipt_id) addReceipt(actions, 'Latest source attempt receipt', value.last_source_attempt?.id);
    root.append(actions);
    if (value.source_revisions?.length > 1) {
      const revisions = node('details');
      revisions.append(node('summary', 'Previous schedule receipts'));
      for (const revision of value.source_revisions.slice(1)) addReceipt(revisions, `Schedule read ${time(revision.observed_at)}`, revision.receipt_id);
      root.append(revisions);
    }
    if (value.runs.length) {
      const versions = node('details');
      versions.append(node('summary', 'Saved experiment versions for this date'));
      const links = node('ul');
      for (const run of value.runs) {
        const item = node('li');
        item.append(link(run.summary.title, coverageURL(query, {run:run.id})),
          document.createTextNode(' · '), link('Open run in Research', researchURL(query, {run:run.id})));
        links.append(item);
      }
      versions.append(links);
      root.append(versions);
    }
    const filter = query.get('coverage_filter');
    const primary = ['expected', 'matched', value.population_revision ? 'source_only' : 'provider_scope_eligible',
      'frozen', 'reconstructed', 'missed', value.population_revision ? 'final' : 'provider_final'];
    const more = node('details');
    more.open = Boolean(filter && !primary.includes(filter));
    more.append(node('summary', 'More coverage counts'), coverageCounters(value, query, filter,
      Object.keys(facets).filter(key => !primary.includes(key))));
    root.append(coverageCounters(value, query, filter, primary), more);
    const selection = query.get('coverage_game');
    const row = selection && value.games.find(row => row.id === selection);
    if (row) root.append(gameDetail(row, value, query));
    else if (selection) root.append(node('p', 'The selected game is unavailable in this retained view.', 'workspace-notice'));
    const visible = Object.hasOwn(facets, filter) ? value.games.filter(row => row.facets.includes(filter)) : value.games;
    root.append(node('h3', Object.hasOwn(facets, filter) ? facets[filter] : 'Games and reconciliation'));
    if (filter) {
      const all = new URLSearchParams(query);
      all.delete('coverage_filter');
      root.append(link('Show all game rows', coverageURL(all)));
    }
    if (!visible.length) root.append(node('p', 'No retained game rows for this selection.'));
    else root.append(table(['Game/start', 'Scope', 'Odds match', 'T−10 task and evidence', 'Saved EV / paper tickets', 'Sporting result'], visible.map(row => [
      link(`${title(row)} · ${time(row.schedule?.starts_at || row.starts_at)}`, coverageURL(query, {coverage_game:row.id})),
      stack(state(row.scope_state || row.retained_scope?.state || row.provider_membership?.state),
        state(row.scope_reason || row.retained_scope?.reason || row.provider_membership?.reason)),
      stack(state(row.match_state), row.match_reason && state(row.match_reason)),
      stack(facets[row.capture.state] || state(row.capture.state), row.saved?.status === 'reconstructed' ? 'Retrospective reconstruction retained' : row.capture.reason),
      row.saved?.qualifying ? `${count(row.saved.evaluated_offers)} EV evaluated · ${count(row.saved.qualifying.best_venue)} best, ${count(row.saved.qualifying.all_venues)} all` : 'Unavailable',
      stack(resultLabel(row), row.result_reason && state(row.result_reason)),
    ])));
  } catch (error) {
    if (isCurrent()) status.textContent = error.message;
  }
}
