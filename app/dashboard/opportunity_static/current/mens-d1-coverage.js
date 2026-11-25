import {count, details, label, link, node, pairs, pct, readJSON, stack, table, time} from './workspace-ui.js';
import {issueLedger} from './research-issues.js';

const endpoint = '/api/workspace/mens-d1';
const easternDay = new Intl.DateTimeFormat('en-CA', {timeZone:'America/New_York', year:'numeric', month:'2-digit', day:'2-digit'});
const shortDay = new Intl.DateTimeFormat('en-US', {timeZone:'UTC', month:'short', day:'numeric'});
const facets = {
  source_mens:'Men’s games returned', expected:'Eligible source games', excluded:'Excluded source rows',
  membership_unresolved:'Unverified membership', matched:'Matched to odds', source_only:'Source only',
  provider_only:'Odds provider only', provider_conflict:'Provider identity or schedule conflict',
  result_only:'Result without schedule', no_market:'No matched provider market evidence', identity_conflict:'Identity conflict',
  schedule_conflict:'Schedule conflict', site_conflict:'Site conflict', retained_eligible:'Eligible in saved scope',
  retained_excluded:'Excluded in saved scope', retained_unresolved:'Unresolved in saved scope',
  provider_scope_eligible:'Provider games with D1 membership', provider_scope_excluded:'Provider games excluded by membership',
  provider_scope_unresolved:'Provider games with unverified membership',
  upcoming:'Upcoming T−10', due:'Due T−10', claimed:'Capture underway', frozen:'Original frozen capture',
  other_date:'Assigned another Eastern date', schedule_corroborated:'Corroborated schedule disagreements', audit_all:'All retained occurrence audit rows',
  reconstructed:'Retrospective reconstruction', no_task:'No T−10 task', missed:'Missed T−10', failed:'Failed capture',
  refused:'Refused capture', cancelled:'Cancelled capture', superseded_by_reschedule:'Capture superseded',
  evaluated:'Offers evaluated for EV', qualifying_best_venue:'Best venue tickets', qualifying_all_venues:'All venues tickets',
  observed_offers:'Games with a saved offer census', reference_gaps:'Games with reference exclusions',
  current_market_evidence:'Games with current frozen market evidence',
  zero_offers:'Measured games with zero observed offers',
  zero_qualifiers:'Evaluated games with zero qualifying tickets',
  result_ledger:'Sporting results for eligible occurrences',
  final:'Verified source final', provider_final:'Provider final evidence', result_pending:'Result pending',
  result_unresolved:'Result unresolved', provider_pending:'Provider result pending',
  provider_result_unresolved:'Provider result unresolved', conflicting:'Conflicting results',
};
const sourceFacets = new Set(['source_mens','expected','excluded','membership_unresolved','matched','source_only',
  'no_market','identity_conflict','schedule_conflict','site_conflict','final','result_pending','result_unresolved','conflicting']);
const offerFacets = new Set(['evaluated','qualifying_best_venue','qualifying_all_venues']);
const paperFacets = new Set([...offerFacets, 'reconstructed']);
const resultStates = {final:'Final', pending:'Pending', disputed:'Disputed', missing:'Missing'};
const captureStates = {upcoming:'upcoming', due:'due', claimed:'in progress', missed:'missed', refused:'refused',
  failed:'failed', no_task:'without a task', cancelled:'cancelled', superseded_by_reschedule:'superseded'};
const gapClasses = {recoverable_engineering:'Recoverable engineering', external_source_limitation:'External source limitation',
  irrecoverable_historical_loss:'Irrecoverable historical loss', future_event:'Future event'};
const marketStates = {
  explicitly_unavailable:'Explicitly unavailable', price_withdrawn:'Withdrawn', no_provider_odds_observed:'No odds observed in this provider response',
  requested_but_unreturned:'Requested but unreturned · Offering unknown', not_requested:'Not requested', unsupported:'Unsupported',
  return_unverified:'Return unverified', screen_passed:'Qualified at the selected EV minimum', below_minimum_ev:'Evaluated below the EV minimum',
};

export function coverageContext(query, fallbackDate) {
  return Object.fromEntries(Object.entries({
    scope:'mens-d1', date:query.get('date') || fallbackDate || easternDay.format(new Date()),
    coverage_game:query.get('coverage_game'), coverage_filter:query.get('coverage_filter'),
    run:query.get('run'), variant:query.get('variant'),
  }).filter(([,value]) => value));
}

export const ledgerKeys = ['game', 'trade', 'sizing_quote', 'sizing_bet', 'filter', 'trade_filter', 'trade_ev', 'trade_sort', 'trade_page', 'ledger_view'];
const reviewKeys = ['result', ...ledgerKeys];
export function workbenchContext(query, keys = [...reviewKeys, 'campaign', 'view', 'mode']) {
  return Object.fromEntries(keys.filter(key => query.has(key)).map(key => [key, query.get(key)]));
}

export function coverageURL(query, extra = {}) {
  const sameRun = extra.run == null || extra.run === query.get('run');
  const sameDate = extra.date == null || extra.date === query.get('date');
  return '/data?' + new URLSearchParams({
    evidence:'mens-d1', ...coverageContext(query), ...(sameRun && sameDate ? workbenchContext(query) : {}), ...extra,
  });
}

function researchURL(query, extra = {}) {
  return '/experiments?' + new URLSearchParams({...coverageContext(query), ...extra});
}

export function readDailyCoverage(query, {summary = false} = {}) {
  const request = new URLSearchParams({date:query.get('date')});
  if (query.has('run')) request.set('run', query.get('run'));
  if (summary) request.set('summary', '1');
  else if (query.has('coverage_game')) request.set('game', query.get('coverage_game'));
  return readJSON(endpoint + '?' + request);
}

function dateLinks(query, to = coverageURL) {
  const group = node('div', undefined, 'workspace-links');
  const today = Date.parse(`${query.get('date')}T00:00:00Z`);
  if (!Number.isFinite(today)) return group;
  for (const offset of [-1, 0, 1]) {
    const adjacent = new Date(today + offset * 86400000);
    const date = adjacent.toISOString().slice(0, 10);
    const params = date === query.get('date') ? query : new URLSearchParams({date});
    if (params !== query && query.get('variant')) params.set('variant', query.get('variant'));
    const action = link(shortDay.format(adjacent), to(params), 'research-button');
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

function versionsPicker(value, query, to) {
  const root = node('div', undefined, 'workspace-panel');
  const selected = query.get('run');
  const context = new URLSearchParams(query);
  context.delete('run');
  context.delete('coverage_filter');
  const actions = node('div', undefined, 'workspace-links workspace-variant');
  const current = link('Current evidence', to(context), 'research-button');
  if (!selected) current.setAttribute('aria-current', 'true');
  actions.append(current);
  const active = value.run?.id === selected ? value.run : null;
  if (active) {
    const saved = link(`Saved ${time(active.observed_at)}`, to(context, {run:active.id}), 'research-button');
    saved.setAttribute('aria-current', 'true');
    actions.append(saved);
  }
  root.append(actions);
  if (value.runs?.length) {
    const versions = node('details');
    versions.append(node('summary', 'Saved experiment versions for this date'));
    const list = node('ul');
    for (const run of value.runs) {
      const item = node('li');
      const name = run.summary?.title || 'Paper run';
      const action = link(`${name} · ${time(run.observed_at)} · ${run.id.slice(0, 12)}`, to(context, {run:run.id}));
      if (run.id === selected) action.setAttribute('aria-current', 'true');
      item.append(action);
      list.append(item);
    }
    versions.append(list);
    root.append(versions);
  }
  return root;
}

export function experimentCoverage(query, fallbackDate, run, isCurrent = () => true, summaryRead) {
  const context = new URLSearchParams({...coverageContext(query, fallbackDate), ...(run ? {date:run.date, run:run.id} : {})});
  const panel = node('section', undefined, 'workspace-panel workspace-card');
  panel.append(node('h2', 'Men’s Division I daily coverage'), dateLinks(context, researchURL));
  if (!run) panel.append(dateForm(context, '/research', 'section', 'experiments'));
  panel.append(link(`Open ${context.get('date')} coverage in Data`, coverageURL(context)));
  if (run || query.get('scope') === 'mens-d1') {
    const status = node('p', 'Reading coverage denominators…');
    panel.append(status);
    (summaryRead || readDailyCoverage(context, {summary:true})).then(value => {
      if (isCurrent() && value.coverage_summary) status.replaceWith(versionsPicker(value, context, researchURL),
        ...reconciliationSummary(value.coverage_summary.reconciliation, context),
        coverageSummary(value.coverage_summary, context, value.analysis_run),
        link('Open the missing-item ledger in Data', coverageURL(context) + '#mens-d1-missing'));
      else if (isCurrent()) status.remove();
    }).catch(error => { if (isCurrent()) status.textContent = error.message; });
  }
  return panel;
}

export function reconciliationSummary(summary, query) {
  if (!summary) return [];
  const panel = node('section', undefined, 'workspace-card workspace-panel');
  const usable = `${count(summary.usable_games)} usable T−10 games (${count(summary.frozen_games)} frozen / ${count(summary.reconstructed_games)} reconstructed)`;
  const gaps = summary.accepted_historical_gaps == null ? `${count(summary.historical_gaps)} historical T−10 gaps`
    : `${count(summary.historical_gaps)} historical T−10 gaps (${count(summary.accepted_historical_gaps)} accepted)`;
  panel.append(node('h3', 'Reconciled paper cohort'), node('p', summary.cohort_name, 'workspace-caption'),
    node('p', `${count(summary.reviewed_games)} reviewed games → ${usable} → ${count(summary.games_with_trades)} with trades / ${count(summary.games_without_qualifiers)} without qualifiers`),
    node('p', `${gaps} · ${count(summary.finals)} retained sporting finals · ${count(summary.excluded_games)} scope exclusions · ${count(summary.other_date_games)} assigned another date`),
    link('Open evidence issues and decisions', coverageURL(query) + '#mens-d1-issues'));
  const original = summary.original_capture_states;
  if (original) panel.append(node('p', `Original T−10 task history · ${count(original.captured || 0)} successful · ${count(original.refused || 0)} refused · ${count(original.missed || 0)} missed`));
  if (summary.corroborated_schedule_disagreements) panel.append(link(`${count(summary.corroborated_schedule_disagreements)} corroborated schedule disagreements`,
    coverageURL(query, {coverage_filter:'schedule_corroborated'})));
  if (!summary.exhaustive_slate) panel.append(node('p', 'The reviewed cohort is the pilot denominator. An independently exhaustive slate has not been established.', 'workspace-caption'));
  return [panel];
}

function coverageSummary(value, query, analysisRun) {
  const {population, capture, markets, reference, trade, results} = value;
  const variant = query.get('variant') === 'all_venues' ? 'all_venues' : 'best_venue';
  const tickets = trade.variants[variant];
  const denom = (n, d) => `${count(n)} of ${count(d)}`;
  const scope = capture.population_basis === 'source' ? 'eligible source-slate games'
    : capture.population_basis === 'provider_known' ? 'eligible provider-known games' : 'reconciled eligible occurrences';
  const sourceName = population.source_identity === 'college_basketball_data' ? 'CollegeBasketballData'
    : population.source_identity === 'sports_reference' ? 'Sports Reference' : 'Independent source';
  const retainedSlate = population.source_eligible_games == null ? '' :
    ` ${sourceName} returned ${count(population.source_returned_mens_games)} games, including ${count(population.source_eligible_games)} verified D1 matchups. ${count(population.source_eligible_known_before_tminus10)} were retained before T−10.`;
  const additional = population.source_corroborated_additional_eligible
    ? ` Official sources identify ${count(population.source_corroborated_additional_eligible)} additional D1 matchups with an unresolved participant in the dated receipt.` : '';
  const dateConflicts = population.source_official_eastern_date_conflicts
    ? ` Official starts cross the Eastern date boundary for ${count(population.source_official_eastern_date_conflicts)} ${population.source_official_eastern_date_conflicts === 1 ? 'source row' : 'source rows'}.` : '';
  const populationGaps = [[population.source_only_games, 'source only'], [population.provider_only_games, 'provider only'],
    [population.unresolved_membership_games, 'membership unresolved'], [population.schedule_disputes, 'schedule disputes'],
    [population.date_disputes, 'Eastern date disputes']]
    .filter(([n]) => n != null).map(([n, name]) => `${count(n)} ${name}`).join(' · ');
  const currentCaptures = Object.entries(captureStates).filter(([key]) => capture.current_states?.[key])
    .map(([key, name]) => `${count(capture.current_states[key])} ${name}`).join(' · ');
  const noOffers = [[capture.zero_offer_games, 'with zero observed offers'], [capture.zero_qualifier_games, 'with zero qualifying tickets']]
    .filter(([n]) => n != null).map(([n, name]) => `${count(n)} ${name}`).join(' · ');
  const responseStates = Object.entries(markets.saved_retrieval_states || {}).filter(([,n]) => n > 0)
    .map(([key,n]) => `${count(n)} ${label(key)}`).join(' · ');
  const traversal = Object.entries(markets.traversal_states || {}).filter(([,n]) => n > 0)
    .map(([key,n]) => `${count(n)} ${label(key)}`).join(' · ');
  const cells = markets.requested_cells == null || markets.returned_cells == null ? '' :
    `${count(markets.requested_cells)} requested · ${count(markets.returned_cells)} returned` +
    (markets.unreturned_cells == null ? '' : ` · ${count(markets.unreturned_cells)} unreturned (offering unknown)`) +
    (markets.no_provider_odds_cells ? ` · ${count(markets.no_provider_odds_cells)} with affirmative no-odds evidence in the provider response` : '') +
    (markets.cell_counts_games == null ? '' : ` across ${count(markets.cell_counts_games)} measured games`);
  const currentMarkets = markets.current_evidence_games == null ? ''
    : `${count(markets.current_evidence_games)} current frozen games with market evidence`;
  const accounting = markets.offer_accounting;
  const offerTotals = accounting && `${count(Object.values(accounting).reduce((sum, n) => sum + n, 0))} original census offers · ${count(accounting.unavailable)} unavailable · ${count(accounting.reference_ineligible)} reference-ineligible · ${count(accounting.below_minimum)} below ${pct(markets.offer_accounting_minimum_ev)} · ${count(accounting.screen_passed)} qualifiers` +
    (accounting.other ? ` · ${count(accounting.other)} other decisions` : '');
  const referenceCauses = Object.entries(reference.reference_exclusions || {}).filter(([,n]) => n > 0)
    .map(([key,n]) => `${count(n)} ${label(key.replace(/^reference_/, ''))}`).join(' · ');
  const referenceAccounting = reference.verified_method_accounting;
  const exact = referenceAccounting && `${count(referenceAccounting.exact_pair_missing)} exact-pair gaps · ${count(referenceAccounting.insufficient_trusted_books)} insufficient trusted-book cases`;
  const analysis = analysisRun && !query.has('run') ? `Latest saved analysis · ${time(analysisRun.observed_at)}` : undefined;
  const savedCaptureClock = capture.saved_at && `Saved captures as of ${time(capture.saved_at)}`;
  const rawCounts = population.raw_source_unresolved_membership == null ? '' :
    `Raw source audit · ${count(population.raw_source_provider_matches)} provider matches · ${count(population.raw_source_unresolved_membership)} unresolved source identities`;
  const entries = [
    ['Population coverage', (population.expected_games == null ? `${count(population.provider_known_games)} provider-known · complete expected slate unknown.`
      : `${denom(population.matched_games, population.expected_games)} source-declared eligible games linked to the odds provider.`) + retainedSlate + additional + dateConflicts,
      population.observed_at || population.as_of, population.revision ? 'Source games' : 'Provider-known games',
      population.revision ? 'expected' : 'provider_scope_eligible', [populationGaps, rawCounts].filter(Boolean).join(' · ')],
    ['Capture coverage', `${denom(capture.current_frozen, capture.current_denominator)} ${scope} frozen in the current ledger. ` +
      (capture.known_before_target == null ? '' : `${count(capture.known_before_target)} were known before their target. `) +
      (capture.saved_denominator == null ? '' : `Saved analysis has ${denom(capture.saved_frozen + capture.saved_reconstructed, capture.saved_denominator)} with evidence (${count(capture.saved_frozen)} frozen, ${count(capture.saved_reconstructed)} reconstructed).`),
      capture.as_of, 'Original capture tasks', 'frozen', [currentCaptures && `Original task history · ${currentCaptures}`, noOffers, savedCaptureClock].filter(Boolean).join(' · ')],
    ['Returned-market coverage', (markets.evidence_games == null ? '' :
      `${denom(markets.observed_offer_games, markets.evidence_games)} saved evidence-bearing games have a normalized offer count (${count(markets.observed_offers)} offers). `) +
      'Venue-wide market denominator is unknown.',
      markets.as_of || markets.current_as_of, 'Game market census', 'observed_offers',
      [responseStates && `Event response · ${responseStates}`, traversal && `Event pagination · ${traversal}`, cells, offerTotals, currentMarkets, analysis].filter(Boolean).join(' · ')],
    ['Reference coverage', reference.observed_offers == null ? 'No saved offer denominator.' :
      `${denom(reference.evaluated_offers, reference.observed_offers)} observed offers evaluated. ${count(reference.reference_gaps)} lacked required reference evidence.`,
      reference.as_of, 'Reference exclusions', 'reference_gaps', exact || referenceCauses],
    ['Trade-evidence quality', tickets ? `${denom(tickets.quote_ages_known, tickets.tickets)} ${variant === 'all_venues' ? 'All venues' : 'Best venue'} tickets have a known quote age. ` +
      `${count(tickets.verified_actual_fees)} have verified actual fees and ${count(tickets.verified_executable_size)} have verified executable size. Venue-native identity is shown per ticket when available. Paper turnover uses modeled size.` : 'No saved ticket denominator.',
      trade.as_of, 'Saved paper tickets', variant === 'all_venues' ? 'qualifying_all_venues' : 'qualifying_best_venue', analysis],
  ];
  if (results) entries.push(['Sporting results', `${count(results.denominator)} eligible occurrences. ` +
    Object.entries(resultStates).map(([key, name]) => `${count(results.states?.[key] ?? 0)} ${name.toLowerCase()}`).join(' · '),
    results.as_of, 'Sporting result evidence', 'result_ledger']);
  const grid = node('div', undefined, 'workspace-grid mens-d1-summary');
  const context = new URLSearchParams(query);
  context.delete('coverage_game');
  for (const [title, amount, asOf, action, filter, subtitle] of entries) {
    const card = node('section', undefined, 'workspace-card');
    card.append(node('h3', title), node('p', amount), node('p', `Evidence as of ${time(asOf)}`, 'workspace-clocks'),
      link(action, coverageURL(context, {coverage_filter:filter})));
    if (subtitle) card.append(node('p', subtitle, 'workspace-clocks'));
    grid.append(card);
  }
  return grid;
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

function beforeTarget(known) {
  return known === true ? 'Recorded before the T−10 target' : known === false ? 'No retained observation before T−10' : 'Unknown';
}

function teams(row) {
  const sides = Array.isArray(row.teams) ? row.teams : Object.values(row.teams || {});
  return sides.map(team => team.name || team.label || team.id || team).filter(team => typeof team === 'string');
}

function title(row) {
  return row.title || teams(row).join(' vs ') || row.provider_event_id || row.source_game_id;
}

function startLabel(row) {
  return row.occurrence_schedule ? time(row.occurrence_schedule.starts_at) : time(row.schedule?.starts_at || row.starts_at);
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

function missingLedger(items, query, summary) {
  const section = node('details', undefined, 'workspace-panel');
  if (summary) {
    section.id = 'mens-d1-missing';
    section.open = location.hash === '#mens-d1-missing';
  }
  section.append(node('summary', `${summary ? 'Missing-item ledger' : 'Market and offer evidence gaps'} · ${count(items.length)} items`));
  if (!items.length) {
    section.append(node('p', 'No gaps were recorded for this evidence selection. Unobserved inventory remains unknown.'));
    return section;
  }
  const searchLabel = node('label', 'Filter gaps by game, venue, market, line or cause ');
  const search = node('input');
  search.type = 'search';
  searchLabel.append(search);
  const status = node('p', undefined, 'workspace-clocks');
  status.setAttribute('role', 'status');
  const results = node('div');
  const previous = node('button', 'Previous gaps'), next = node('button', 'Next gaps');
  const pageSize = 25;
  let offset = 0;
  section.append(searchLabel, status, results, previous, next);
  function render() {
    const term = search.value.trim().toLowerCase();
    const rows = items.filter(row => !term || Object.values(row)
      .some(value => value != null && label(value).toLowerCase().includes(term)));
    const page = rows.slice(offset, offset + pageSize);
    status.textContent = rows.length ? `${count(offset + 1)}–${count(offset + page.length)} of ${count(rows.length)} gaps` : 'No matching gaps.';
    previous.disabled = offset === 0;
    next.disabled = offset + pageSize >= rows.length;
    results.replaceChildren();
    if (!page.length) return;
    results.append(table(['Affected evidence', 'What is missing', 'Consequence', 'Cause and classification', 'Next remedy'], page.map(row => {
      const target = [row.venue, row.market, row.outcome, row.line].filter(value => value != null).map(label).join(' · ');
      const affected = row.game_title || row.game_id || (target ? 'Market' : 'Dated slate');
      const scope = stack(affected, target);
      if (summary && row.game_id) scope.firstChild.replaceChildren(link(affected, coverageURL(query, {coverage_game:row.game_id})));
      return [scope, row.evidence, row.consequence, stack(row.cause || 'Unknown', gapClasses[row.classification] || state(row.classification)), row.remedy];
    })));
  }
  search.oninput = () => { offset = 0; render(); };
  previous.onclick = () => { offset = Math.max(0, offset - pageSize); render(); };
  next.onclick = () => { offset += pageSize; render(); };
  render();
  return section;
}

function censusRows(value) {
  const section = node('div');
  const choice = node('label', 'Rows to inspect '), select = node('select');
  for (const [key, title] of Object.entries({offers:'Paper offer decisions', reference:'Exact-line reference exclusions',
    request_cells:'Requested bookmaker and market outcomes', original_rows:'Original returned rows', normalized_rows:'Normalized quotation rows'})) {
    const option = node('option', title);
    option.value = key;
    select.append(option);
  }
  choice.append(select);
  const filter = node('label', 'Filter by venue, market, line or reason '), search = node('input');
  search.type = 'search';
  filter.append(search);
  const results = node('div'), previous = node('button', 'Previous rows'), next = node('button', 'Next rows');
  const range = node('p', undefined, 'workspace-clocks');
  range.setAttribute('role', 'status');
  section.append(choice, filter, range, results, previous, next);
  const pageSize = 30;
  let offset = 0;
  function render() {
    const key = select.value;
    const rows = key === 'reference' ? value.offers.filter(row => row.reference_gap) : value[key];
    const query = search.value.trim().toLowerCase();
    const matching = rows.filter(row => !query || [row.venue, row.bookmaker_id, row.family, row.outcome, row.line,
      row.original_line, row.state, row.disposition, row.price_reason, row.reason, ...(row.reference_gap?.causes || [])]
      .some(detail => detail != null && label(detail).toLowerCase().includes(query)));
    const shown = matching.slice(offset, offset + pageSize);
    range.textContent = matching.length ? `${count(offset + 1)}–${count(offset + shown.length)} of ${count(matching.length)} rows` : 'No rows match.';
    previous.disabled = offset === 0;
    next.disabled = offset + pageSize >= matching.length;
    results.replaceChildren();
    if (!shown.length) return;
    results.append(table(['Venue / bookmaker', 'Market and outcome', 'Exact line', 'Price / count', 'Disposition and evidence'], shown.map(row => {
      const code = row.disposition || row.state;
      const reason = marketStates[code] || label(code);
      const evidence = node('div');
      evidence.append(stack(reason, row.price_reason || row.reason || (row.evaluated ? `${pct(row.screen_ev)} EV` : '')));
      if (row.reference_gap) evidence.append(stack(`Method-ineligible · ${count(row.reference_gap.qualifying_trusted_books)} of ${count(row.reference_gap.required_trusted_books)} trusted books`,
        (row.reference_gap.causes || []).map(label).join(' · ')), details('Required exact book, side and line', row.reference_gap));
      evidence.append(details('Original IDs and evidence', row));
      return [row.venue || row.bookmaker_id, stack(label(row.family), label(row.outcome)),
        row.original_line ?? row.line ?? 'No line', row.price_american ?? row.rows ?? 'Unavailable', evidence];
    })));
  }
  select.onchange = search.oninput = () => { offset = 0; render(); };
  previous.onclick = () => { offset = Math.max(0, offset - pageSize); render(); };
  next.onclick = () => { offset += pageSize; render(); };
  render();
  return section;
}

function marketCensus(row, value) {
  const saved = row.saved?.checkpoint_id, current = row.capture?.frozen_id;
  if (!saved && !current) return node('p', 'No retained T−10 market census for this game.');
  const panel = node('section', undefined, 'workspace-panel');
  panel.append(node('h4', 'Returned markets and reference gaps'));
  const actions = node('div', undefined, 'workspace-links'), result = node('div');
  panel.append(actions, result);
  const variants = [];
  if (saved) variants.push(['saved', saved === current ? 'Inspect saved and current market census' : 'Inspect saved market census']);
  if (current && current !== saved) variants.push(['current', 'Inspect current frozen market census']);
  let sequence = 0;
  for (const [version, title] of variants) {
    const request = new URLSearchParams({date:value.date, game:row.id, version});
    const run = version === 'saved' ? value.analysis_run || value.run : value.run;
    if (run) request.set('run', run.id);
    const url = `${endpoint}/market-census?${request}`;
    const inspect = node('button', title);
    inspect.onclick = async () => {
      const selected = ++sequence;
      const status = node('p', 'Reading retained market rows…');
      status.setAttribute('role', 'status');
      result.replaceChildren(status);
      try {
        const census = await readJSON(url);
        if (selected !== sequence) return;
        const {summary, retrieval} = census;
        result.replaceChildren(pairs({
          'Response received':time(census.as_of), 'Requested provider events':count(retrieval.requested_event_ids?.length),
          'Selected event response':label(summary.retrieval_state), 'Request coverage':label(retrieval.request_state),
          'Event pagination':label(summary.traversal),
          'Venue-wide line inventory':'Unknown', 'Requested bookmaker / outcome combinations':count(summary.requested_cells),
          'Returned bookmaker / outcome combinations':count(summary.returned_cells),
          'Requested but unreturned combinations':count(summary.unreturned_cells),
          ...(summary.no_provider_odds_cells ? {'Cells with explicit provider no-odds evidence':count(summary.no_provider_odds_cells)} : {}),
          ...(census.version ? {'Derived census version':census.version} : {}),
          'Original returned rows':count(summary.original_rows), 'Normalized rows':count(summary.normalized_rows),
          'Paper offer rows observed':count(summary.observed_offers), 'Offers with EV':count(summary.evaluated_offers),
          'Offers missing required reference':count(summary.reference_exclusions), 'Offers passing EV screen':count(summary.screen_passed_offers),
          ...(census.saved_disposition?.qualifying ? {'Saved Best tickets':census.saved_disposition.qualifying.best_venue,
            'Saved All tickets':census.saved_disposition.qualifying.all_venues} : {}),
        }), node('p', 'SportsGameOdds cursors advance through events. Alternate lines appear inside a returned event. A requested but unreturned cell leaves its venue availability unknown.'),
          details('Requested scope, retained response hash and page cursors', {scope:census.requested_scope, ...retrieval,
            original_response:census.original_response, event_odds:census.event_odds, evidence_revision:census.evidence_revision}), censusRows(census));
        if (census.original_response?.state === 'retained')
          result.append(link('Download original market response', url + '&raw=1'));
        if (census.missing_items) result.append(missingLedger(census.missing_items));
      } catch (error) {
        if (selected === sequence) status.textContent = error.message;
      }
    };
    actions.append(inspect, link(`Download ${version} market census`, url + '&export=1', 'research-button'));
  }
  return panel;
}

function gameDetail(row, value, query) {
  const schedule = row.schedule || {}, result = row.result || {}, capture = row.capture || {}, saved = row.saved || {};
  const occurrence = row.occurrence_schedule, records = row.source_records || [];
  const observation = row.observation || {};
  const root = node('section', undefined, 'workspace-card workspace-panel');
  root.append(node('h3', title(row)), pairs({
    ...(row.occurrence_id ? {'Occurrence ID':row.occurrence_id, 'Reconciled Eastern game date':row.eastern_game_date,
      'Date applicability':state(row.day_applicability),
      'Occurrence schedule disposition':state(occurrence?.state), 'Reconciled start':startLabel(row)} : {}),
    'Source game':row.source_game_id, 'Odds provider game':row.provider_event_id,
    'Source scope':state(row.scope_state), 'Scope reason':row.scope_reason,
    'Provider population membership':row.provider_membership?.state, 'Provider membership reason':row.provider_membership?.reason,
    'Saved scope':row.retained_scope?.state, 'Saved scope reason':row.retained_scope?.reason,
    'Operational schedule decision':row.operational_schedule_state && state(row.operational_schedule_state),
    'Raw source match':state(row.raw_occurrence_match_state || row.match_state), 'Raw match reason':row.raw_occurrence_match_reason || row.match_reason,
    'Retained source start':time(schedule.starts_at), 'Source date':schedule.source_date,
    'Source time':schedule.source_time, 'Source timezone':schedule.source_timezone, 'Venue/site':schedule.site,
    'Schedule status':state(schedule.status), 'Schedule observed':observed(schedule.observed_at, value.as_of),
    'First source observation':time(observation.first_source_observed_at),
    'First odds-provider observation':time(observation.first_provider_observed_at || capture.first_provider_observed_at),
    'Retained source clock before T−10':beforeTarget(observation.source_known_before_tminus10 ?? row.known_before_tminus10),
    'Source participant identities before T−10':beforeTarget(observation.source_identity_known_before_tminus10),
    'Retained odds-provider observation before T−10':beforeTarget(observation.provider_known_before_tminus10),
    'Retained official corroboration before T−10':beforeTarget(observation.official_known_before_tminus10),
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
  if (row.official_source_evidence?.length) {
    root.append(node('h4', 'Official school or conference evidence'));
    for (const evidence of row.official_source_evidence) {
      const participants = (evidence.teams || []).map(team => team.score == null ? team.name : `${team.name} ${team.score}`).join(' · ');
      const status = evidence.status === 'final' ? 'Sporting final' : 'Scheduled';
      const start = evidence.scheduled_start ? ` · ${time(evidence.scheduled_start)}` : '';
      const dateConflict = evidence.eastern_date_disagreement ? ` · Eastern game date ${evidence.eastern_game_date} differs from this receipt` : '';
      const description = `${participants} · ${status}${start}${dateConflict}`;
      root.append(node('p', description), link(evidence.publisher, evidence.source_url),
        node('p', `Observed ${time(evidence.observed_at)} · Recorded ${time(evidence.recorded_at)}`, 'workspace-clocks'));
    }
  }
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
  if (records.length) {
    const history = node('details');
    history.append(node('summary', `Source records across revisions · ${count(records.length)}`),
      table(['Source record', 'Original clock and revision date', 'Normalized start', 'Observed', 'Receipt'], records.map(record => {
        const clock = record.schedule || {};
        return [
          stack(state(record.source), [state(record.kind), record.source_game_id].filter(Boolean).join(' · ')),
          [clock.source_date, clock.source_time, clock.source_timezone,
            record.revision_eastern_date && `${record.revision_eastern_date} Eastern`].filter(Boolean).join(' · '),
          time(clock.starts_at), time(record.observed_at), record.receipt_id
            ? link('Download receipt', endpoint + '/receipts/' + encodeURIComponent(record.receipt_id)) : 'Unavailable',
        ];
      })), details('Original source fields and participants', records));
    root.append(history);
  }
  if (row.provider_evidence || occurrence) root.append(details('Schedule reconciliation, original clocks and odds-provider revisions', {
    occurrence_schedule:occurrence, odds_provider:row.provider_evidence,
  }));
  if (row.research_scope === 'other_date' && row.eastern_game_date) root.append(link(`Open ${row.eastern_game_date} Eastern coverage`,
    coverageURL(new URLSearchParams({date:row.eastern_game_date}))));
  if (row.teams || row.retained_scope?.teams) root.append(details('Participant IDs and membership evidence', {
    source:row.teams, saved:row.retained_scope?.teams,
  }));
  if (row.source_game_id) root.append(details('Cross-source binding and schedule changes', {
    source_game_id:row.native_game_id, upstream_game_id:row.upstream_game_id, odds_provider_game:row.provider_event_id,
    match_state:row.match_state, match_reason:row.match_reason, provider_candidates:row.provider_candidates,
    schedule_changes:row.schedule_changes, persisted_binding_revision:value.population?.binding_revision_id,
  }));
  if (row.schedule || row.result || row.provider_results?.length) root.append(details('Exact schedule and sporting-result revisions', {
    schedule:row.schedule, source_results:row.result_revisions?.length ? row.result_revisions : row.result,
    competing_provider_results:row.provider_results,
  }));
  root.append(node('h4', 'T−10 capture and paper evidence'), pairs({
    'Original task':state(capture.state), 'Task reason':capture.reason, 'Task target':time(capture.target_at),
    'Task deadline':time(capture.deadline_at), Attempts:capture.attempts, Refusals:capture.refusals,
    'First discovered by odds collector':time(capture.first_provider_observed_at),
    'Schedule receipt':time(capture.schedule_source_received_at), 'Last retained claim':time(capture.claimed_at),
    'Last refusal':time(capture.last_refused_at), 'Task last updated':time(capture.task_updated_at),
    'Frozen capture ID':capture.frozen_id, 'Frozen request':time(capture.frozen_requested_at),
    'Frozen receipt':observed(capture.frozen_received_at, value.as_of), 'Frozen known':time(capture.frozen_known_at),
    'Frozen persistence':time(capture.frozen_persisted_at),
    'Paper evidence usability':state(row.paper_usability || saved.status), 'Saved run reason':saved.reason,
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
  if (saved.original_response_export) captureLinks.append(link('Original odds response, if retained', saved.original_response_export));
  root.append(captureLinks);
  const variant = query.get('variant') === 'all_venues' ? 'all_venues' : 'best_venue';
  const tickets = row.ticket_clocks?.[variant] || [];
  const analysis = value.analysis_run || value.run;
  if (tickets.length && analysis) {
    const context = new URLSearchParams({...coverageContext(query), run:analysis.id, variant});
    const dataContext = new URLSearchParams(query);
    const other = variant === 'all_venues' ? 'best_venue' : 'all_venues';
    root.append(node('h4', variant === 'all_venues' ? 'All venues quote clocks' : 'Best venue quote clocks'),
      link(other === 'all_venues' ? 'Show all venues' : 'Show best venue', coverageURL(dataContext, {variant:other})),
      table(['Saved ticket', 'Quote source at receipt', 'Quote receipt'], tickets.map(ticket => [
        link(`${ticket.label} · ${state(ticket.venue)}`, researchURL(context, {ticket:ticket.id})),
        observed(ticket.times?.source_at, ticket.times?.received_at), time(ticket.times?.received_at),
      ])));
  }
  if (saved.exclusions) root.append(details('Why offers did not qualify', saved.exclusions));
  root.append(marketCensus(row, value));
  return root;
}

function coverageCounters(value, query, filter, keys) {
  const grid = node('dl', undefined, 'workspace-stats mens-d1-counts');
  for (const key of keys) {
    const title = facets[key];
    const fromSource = sourceFacets.has(key), fromRun = paperFacets.has(key);
    if (key.startsWith('retained_') && !value.run_population) continue;
    const measured = !(fromSource && !value.population_revision || fromRun && !(value.analysis_run || value.run));
    const group = node('div'), term = node('dt', title), total = node('dd');
    const selection = new URLSearchParams(query);
    selection.delete('coverage_game');
    const number = key === 'audit_all' ? value.games.length : offerFacets.has(key) ? value.offer_counts[key] : value.facets[key] || 0;
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
    const canonical = coverageURL(incoming);
    if (location.pathname + location.search !== canonical) {
      history.replaceState(null, '', canonical + location.hash);
      window.dispatchEvent(new Event('workspace-context'));
    }
    status.textContent = `As of ${time(value.as_of)} · Schedule source ${state(value.source_state)}`;
    const message = value.source_state_reason || value.source_reason;
    if (message) root.append(node('p', state(message), 'workspace-notice'));
    root.append(versionsPicker(value, query, coverageURL));
    if (value.coverage_summary) root.append(...reconciliationSummary(value.coverage_summary.reconciliation, query),
      coverageSummary(value.coverage_summary, query, value.analysis_run));
    if (!value.population_revision) root.append(node('p', 'The source-declared D1 slate is unverified. Retained odds-provider games and earlier saved runs provide partial coverage.'));
    else root.append(node('p', `${value.source_mode === 'retrospective_public_export' ? 'Retrospective source schedule' : 'Retained source schedule'} for ${value.date}, observed ${observed(value.source_observed_at, value.as_of)}. Membership, timing and provider disagreements are listed by game.`));
    if (value.run_population?.kind === 'retained_original_run') root.append(node('p', 'This retrospective scope correction uses membership evidence for games in the original saved run. Source-declared counts depend on the daily schedule receipt.', 'workspace-notice'));
    if (value.run_population?.kind === 'retained_provider_snapshot') root.append(node('p', 'This saved provider snapshot uses the odds-provider games and season membership known when it was saved. Its saved expected-slate denominator is unknown.', 'workspace-notice'));
    if (!value.population_revision && !value.run_population) root.append(node('p', 'Capture counts use retained provider games with evidence of D1 membership for both teams.'));
    const actions = node('div', undefined, 'workspace-links');
    actions.append(link(value.run ? 'Open selected experiment' : 'Open Experiments for this date',
      researchURL(query, workbenchContext(incoming)), 'research-button'));
    request.set('export', '1');
    actions.append(link('Export dated game and coverage ledger', endpoint + '?' + request, 'research-button'));
    const analysis = value.analysis_run || value.run;
    if (analysis) actions.append(link('Export dated offer ledger', '/api/research/workspace/runs/' + encodeURIComponent(analysis.id) + '/offers', 'research-button'));
    addReceipt(actions, value.source_mode === 'retrospective_public_export' ? 'Source schedule receipt metadata'
      : 'Original daily schedule receipt', value.source_receipt_id);
    if (value.last_source_attempt?.id !== value.source_receipt_id) addReceipt(actions, 'Latest source attempt receipt', value.last_source_attempt?.id);
    root.append(actions);
    if (value.source_revisions?.length > 1) {
      const revisions = node('details');
      revisions.append(node('summary', 'Previous schedule receipts'));
      for (const revision of value.source_revisions.slice(1)) addReceipt(revisions, `Schedule read ${time(revision.observed_at)}`, revision.receipt_id);
      root.append(revisions);
    }
    if (value.missing_items) root.append(missingLedger(value.missing_items, query, true));
    const explicitFilter = query.get('coverage_filter');
    const cohort = value.coverage_summary?.reconciliation;
    const filter = explicitFilter || (cohort ? 'result_ledger' : null);
    const primary = [cohort ? 'result_ledger' : 'expected', 'matched', value.population_revision ? 'source_only' : 'provider_scope_eligible',
      'frozen', 'reconstructed', 'missed', value.population_revision ? 'final' : 'provider_final'];
    const more = node('details');
    more.open = Boolean(filter && !primary.includes(filter));
    more.append(node('summary', 'More coverage counts'), coverageCounters(value, query, filter,
      Object.keys(facets).filter(key => !primary.includes(key))));
    root.append(coverageCounters(value, query, filter, primary), more);
    const selection = query.get('coverage_game');
    const row = selection && value.games.find(row => row.id === selection || row.legacy_ids?.includes(selection));
    if (row) root.append(gameDetail(row, value, query));
    else if (selection) root.append(node('p', 'The selected game is unavailable in this retained view.', 'workspace-notice'));
    if (Array.isArray(value.issues)) root.append(issueLedger(value, query, coverageURL, row?.id));
    const visible = filter !== 'audit_all' && Object.hasOwn(facets, filter) ? value.games.filter(row => row.facets.includes(filter)) : value.games;
    root.append(node('h3', Object.hasOwn(facets, filter) ? facets[filter] : 'Games and reconciliation'));
    if (cohort && filter !== 'audit_all') root.append(link('Show all retained occurrence audit rows', coverageURL(query, {coverage_filter:'audit_all'})));
    if (explicitFilter) {
      const all = new URLSearchParams(query);
      all.delete('coverage_filter');
      root.append(link(cohort ? 'Return to reconciled paper cohort' : 'Show all game rows', coverageURL(all)));
    }
    if (!visible.length) root.append(node('p', 'No retained game rows for this selection.'));
    else root.append(table(['Game/start', 'Scope', 'Odds match', 'T−10 task and evidence', 'Saved EV / paper tickets', 'Sporting result'], visible.map(row => [
      link(`${title(row)} · ${startLabel(row)}`, coverageURL(query, {coverage_game:row.id})),
      stack(state(row.research_scope || row.scope_state || row.retained_scope?.state || row.provider_membership?.state),
        state(row.scope_reason || row.retained_scope?.reason || row.provider_membership?.reason)),
      stack(state(row.operational_schedule_state || row.match_state), row.raw_occurrence_match_state
        ? `Raw match · ${state(row.raw_occurrence_match_state)}` : row.match_reason && state(row.match_reason)),
      stack(facets[row.capture.state] || state(row.capture.state), row.saved?.status === 'reconstructed' ? 'Retrospective reconstruction retained' : row.capture.reason),
      row.saved?.qualifying ? `${count(row.saved.evaluated_offers)} EV evaluated · ${count(row.saved.qualifying.best_venue)} best, ${count(row.saved.qualifying.all_venues)} all` : 'Unavailable',
      stack(resultLabel(row), row.result_reason && state(row.result_reason)),
    ])));
    if (['#mens-d1-missing', '#mens-d1-issues'].includes(location.hash)) root.querySelector(location.hash)?.scrollIntoView();
  } catch (error) {
    if (isCurrent()) status.textContent = error.message;
  }
}
