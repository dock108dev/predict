import {coverageNames, coverageFamilies, coverageWords, coverageCount, coverageSport, coverageSource, coverageFamily, coveragePeriod, coverageRatio, cellRatio, coveragePercent, coverageRatioText, coverageCellState, filterCoverageCells, filteredCoverageTotals, coverageRows, coverageOddsHref} from './coverage-model.js';

export const coverageElement = (tag, text, cls) => {const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node;};
export function coverageTime(value) {
  const at = Date.parse(value);
  return Number.isFinite(at) ? new Date(at).toLocaleString('en-US', {timeZone:'America/New_York', month:'short', day:'numeric', hour:'numeric', minute:'2-digit', second:'2-digit', timeZoneName:'short'}) : 'Unknown';
}
const sourceName = value => coverageNames[value] || coverageWords(value);
const familyName = cell => coverageFamilies[coverageFamily(cell)] || coverageWords(coverageFamily(cell));
const cellTitle = cell => [coverageSport(cell), sourceName(coverageSource(cell)), familyName(cell), coverageWords(coveragePeriod(cell))].join(' · ');
const categories = {source:'Source offering', source_omission:'Source offering', implementation:'Implementation limit', capability:'Implementation limit', operational:'Collection or publication limit', operation:'Collection or publication limit', display:'Display filter', identity:'Identity or comparison facts', comparison:'Comparison facts', freshness:'Original price clocks', meaning:'Contract meaning', matching:'Cross-source matching', publication:'Background publication', measurement:'Query measurement', configuration:'Configuration', reference:'Reference data'};
const mainCause = cell => (cell.reasons || []).slice().sort((a, b) => (b.primary_count || 0) - (a.primary_count || 0) || (b.count || 0) - (a.count || 0))[0];
function ratioForCounts(counts, kind, scope) {
  const key = {supported_peer:'supported_comparison_observations', current_peer:'current_comparison_observations', current:'current_observations'}[kind];
  return coverageRatio(counts[key], kind === 'current' ? counts.retained_observations : counts.retained_comparison_observations, scope);
}
export function renderCoverageTotals(root, counts) {
  root.replaceChildren();
  const retained = coverageElement('article', undefined, 'total-card');
  retained.append(coverageElement('small', 'Global retained observations'), coverageElement('strong', coverageCount(counts.retained_observations)), coverageElement('small', coverageCount(counts.retained_comparison_observations) + ' comparison-source + ' + coverageCount(counts.retained_reference_observations) + ' reference observations · all captured cells', 'ratio-detail'));
  root.append(retained);
  for (const [kind, title, label] of [['supported_peer', 'Global supported comparisons', 'observations with a supported peer / retained comparison-source observations'], ['current_peer', 'Global current comparisons', 'observations with a current peer / retained comparison-source observations'], ['current', 'Global current prices', 'current observations / retained observations']]) {
    const ratio = ratioForCounts(counts, kind, 'all retained observations in this captured publication'), box = coverageElement('article', undefined, 'total-card');
    box.append(coverageElement('small', title), coverageElement('strong', coveragePercent(ratio)), coverageElement('small', coverageCount(ratio.numerator) + ' / ' + coverageCount(ratio.denominator) + ' ' + label + ' · all captured cells', 'ratio-detail'));
    root.append(box);
  }
}
export function renderFilteredCoverage(root, data, cells) {
  const counts = filteredCoverageTotals(data, cells), retained = counts.retained_observations, total = data.global_totals?.retained_observations;
  root.replaceChildren(coverageElement('strong', 'Filtered: ' + coverageCount(cells.length) + ' / ' + coverageCount(data.cells.length) + ' cells · ' + coverageCount(retained) + ' retained observations · Global: ' + coverageCount(total) + ' retained observations'));
  root.append(coverageElement('p', coverageRatioText(ratioForCounts(counts, 'supported_peer', 'captured comparison-source observations in these filtered cells; reference data excluded'), 'supported-peer observations / retained comparison-source observations')));
  root.append(coverageElement('p', coverageCount(counts.current_observations) + ' current · ' + coverageCount(counts.last_known_observations) + ' last-known · ' + coverageCount(counts.unknown_age_observations) + ' unknown-age observations · ' + coverageCount(counts.gap_observations) + ' observations with gaps'));
  root.append(coverageElement('p', coverageCount(counts.comparable_outcomes) + ' unique comparable outcomes · ' + coverageCount(counts.underlying_pairs) + ' underlying cross-source pairs touching this scope · ' + coverageCount(counts.signed_comparison_directions) + ' signed directions from this scope. Pair and outcome counts are deduplicated; source-cell counts overlap.'));
  root.append(coverageElement('p', coverageCount(counts.displayed_comparison_directions) + ' displayed comparison directions · ' + coverageCount(counts.displayed_current_comparison_directions) + ' displayed current comparison directions. These selected Odds comparisons are separate from all eligible signed peer directions.'));
  if (counts.eligible_current_pairs !== undefined) root.append(coverageElement('p', coverageCount(counts.eligible_current_pairs) + ' current compatible input pairs · ' + coverageCount(counts.supported_noncurrent_pairs) + ' supported pairs with old or unknown inputs · ' + coverageCount(counts.published_current_pairs) + ' published current pairs. ' + coverageCount(counts.publication_pending_directions) + ' selected current directions await publication; ' + coverageCount(counts.display_disagreement_directions) + ' reporting disagreements. All use this captured retained cohort.'));
  if (cells.length !== data.cells.length) root.append(coverageElement('p', (data.cells.length - cells.length) + ' cells are hidden by these display filters. Their retained data remains in global totals.'));
}
export function renderCoverageMatrix(root, data, filters, onOpen) {
  const cells = filterCoverageCells(data.cells, filters), families = ['winner', 'spread', 'total'];
  root.replaceChildren();
  for (const row of coverageRows(cells, filters.sort)) {
    const section = coverageElement('section', undefined, 'coverage-row'), heading = coverageElement('div', undefined, 'coverage-row-heading'), grid = coverageElement('div', undefined, 'coverage-cells');
    heading.append(coverageElement('strong', row.sport), coverageElement('span', sourceName(row.source)));
    if (row.cells.some(cell => cell.role === 'reference')) heading.append(coverageElement('span', 'Reference', 'role-label'));
    else if (row.cells.some(cell => cell.provider && cell.provider !== row.source)) heading.append(coverageElement('span', 'Aggregate supplied', 'role-label'));
    else heading.append(coverageElement('span', 'Native acquisition', 'role-label'));
    row.cells.sort((a, b) => (families.indexOf(coverageFamily(a)) < 0 ? 3 : families.indexOf(coverageFamily(a))) - (families.indexOf(coverageFamily(b)) < 0 ? 3 : families.indexOf(coverageFamily(b))) || coverageFamily(a).localeCompare(coverageFamily(b)) || coveragePeriod(a).localeCompare(coveragePeriod(b)));
    for (const cell of row.cells) {
      const button = coverageElement('button', undefined, 'coverage-cell'), ratio = cellRatio(cell), state = coverageCellState(cell), cause = mainCause(cell);
      button.type = 'button'; button.dataset.cellId = cell.id;
      button.dataset.state = ['Implemented', 'Current supported comparisons', 'Reference only'].includes(state) ? ratio.value !== null && ratio.value < 0.5 ? 'gap' : 'measured' : 'inactive';
      button.setAttribute('aria-label', 'Inspect ' + cellTitle(cell) + ' · ' + state + ' · ' + coveragePercent(ratio) + ' supported comparison coverage');
      const arrow = coverageElement('span', '↗', 'cell-open'); arrow.setAttribute('aria-hidden', 'true');
      button.append(coverageElement('span', familyName(cell), 'cell-family'), coverageElement('span', coverageWords(coveragePeriod(cell)), 'cell-period'), coverageElement('strong', coveragePercent(ratio), 'cell-ratio'), coverageElement('span', coverageCount(ratio.numerator) + ' with a supported peer / ' + coverageCount(ratio.denominator) + ' retained comparison-source observations', 'cell-denominator'), coverageElement('span', state, 'cell-status'));
      if (cell.capability?.state === 'unsupported' && state !== 'Unsupported capability') button.append(coverageElement('span', 'Comparison capability unsupported', 'cell-cause'));
      if (cause) button.append(coverageElement('span', cause.label || 'Missing comparison facts', 'cell-cause'));
      else button.append(coverageElement('span', coverageCount(cell.counts?.last_known_observations) + ' last-known · ' + coverageCount(cell.counts?.current_observations) + ' current', 'cell-cause'));
      button.append(arrow); button.onclick = () => onOpen(cell, button); grid.append(button);
    }
    section.append(heading, grid); root.append(section);
  }
  if (!cells.length) root.append(coverageElement('p', 'No cells match these filters. Clear filters to inspect the full configured matrix.', 'empty'));
  return cells;
}
const detailCountLabels = {retained_observations:'Retained native observations', displayed_observations:'Displayed observations', displayed_comparison_directions:'Displayed comparison directions', displayed_current_comparison_directions:'Displayed current comparison directions', current_observations:'Current observations', last_known_observations:'Last-known observations', unknown_age_observations:'Unknown-age observations', matched_occurrences:'Matched sporting occurrences', supported_comparison_observations:'Observations with a supported peer', current_comparison_observations:'Observations with a current peer', comparable_outcomes:'Unique comparable outcomes', underlying_pairs:'Underlying cross-source pairs', signed_comparison_directions:'Signed comparison directions', gap_observations:'Observations with a gap'};
function countGrid(values, labels) {
  const grid = coverageElement('div', undefined, 'detail-counts');
  for (const [key, label] of Object.entries(labels)) {const line = coverageElement('div', undefined, 'detail-count'); line.append(coverageElement('span', label), coverageElement('strong', coverageCount(values?.[key]))); grid.append(line);}
  return grid;
}
function diagnostic(root, title, value) {
  const details = coverageElement('details'); details.append(coverageElement('summary', title), coverageElement('pre', JSON.stringify(value, null, 2))); root.append(details);
}
export function renderCoverageExample(example) {
  const box = coverageElement('article', undefined, 'source-example'), original = example.original || example.price?.original || {}, times = example.times || {};
  const event = typeof example.event === 'string' ? example.event : example.event?.title || example.event?.name;
  box.append(coverageElement('strong', event || example.title || 'Retained original input'));
  const amount = original.value ?? original.price;
  box.append(coverageElement('div', amount === undefined || amount === null ? 'Original price unknown' : String(amount) + ' ' + coverageWords(original.units || original.unit || 'source units'), 'original-price'));
  const side = example.native_side || example.source?.native_side;
  box.append(coverageElement('small', sourceName(example.venue || example.source) + (side ? ' · ' + coverageWords(side) : '')));
  box.append(coverageElement('small', 'Source: ' + coverageTime(times.source_at || example.source_at) + ' · Received: ' + coverageTime(times.received_at || example.received_at)));
  if (example.book_confirmation) box.append(coverageElement('small', 'Book confirmed: ' + coverageTime(example.book_confirmation.confirmed_at) + ' · Expires: ' + coverageTime(example.clock_evidence?.current_until) + '. Original source clock is preserved.'));
  if (example.condition) box.append(coverageElement('p', example.condition));
  for (const failed of (example.failed_conditions || []).slice(0, 8)) {
    const explanation = typeof failed === 'string' ? failed : failed.condition || failed.explanation || failed.message;
    if (explanation) box.append(coverageElement('p', explanation));
    if (failed && typeof failed === 'object' && failed.missing_fact) box.append(coverageElement('p', 'Missing fact: ' + failed.missing_fact));
    if (failed && typeof failed === 'object' && (failed.event_start || failed.market_start)) box.append(coverageElement('p', 'Captured game start: ' + coverageTime(failed.event_start) + ' · Captured market start: ' + coverageTime(failed.market_start) + '. These schedules require agreement or a verified ordered revision.'));
  }
  if (example.missing_fields?.length) box.append(coverageElement('p', 'Missing fields: ' + example.missing_fields.map(coverageWords).join(', ')));
  diagnostic(box, 'Native identifiers & captured inputs', example);
  return box;
}
export function renderCoverageDetails(root, cell, data) {
  root.replaceChildren(coverageElement('p', coverageCellState(cell) + ' · Capability: ' + coverageWords(cell.capability?.state) + ' · ' + (cell.role === 'reference' ? 'Reference data' : 'Comparison source'), 'detail-badges'));
  root.append(coverageElement('p', 'Frozen at coverage capture ' + coverageTime(data.captured_at) + '. Closing and reopening reads the latest local publication.', 'bounded-note'));
  const link = coverageElement('a', 'Open this sport, source and market scope in Odds ↗', 'odds-link'); link.href = coverageOddsHref(cell); root.append(link);
  if (typeof cell.capability?.reason === 'string' && /\s/.test(cell.capability.reason)) root.append(coverageElement('p', cell.capability.reason));
  const ratios = coverageElement('div', undefined, 'detail-ratios');
  for (const [kind, label] of [['supported_peer','observations with a supported peer / retained comparison-source observations'], ['current_peer','observations with a current peer / retained comparison-source observations'], ['current','current observations / retained observations']]) ratios.append(coverageElement('p', coverageRatioText(cellRatio(cell, kind), label)));
  root.append(ratios, countGrid(cell.counts, detailCountLabels));
  if (cell.counts?.eligible_current_pairs !== undefined) root.append(countGrid(cell.counts, {retained_peer_candidate_observations:'Observations with retained other-source candidates', no_retained_peer_observations:'Resolved observations with no retained other-source input', identity_matched_observations:'Observations with resolved occurrence identity', meaning_supported_observations:'Observations with compatible comparison meaning', input_supported_observations:'Retained inputs with a supported peer', input_current_peer_observations:'Retained inputs with a current peer', eligible_current_pairs:'Current compatible input pairs', supported_noncurrent_pairs:'Supported pairs with noncurrent inputs', published_current_pairs:'Published current pairs', publication_pending_directions:'Current selected directions awaiting publication', display_disagreement_directions:'Reporting disagreements'}));
  root.append(coverageElement('p', 'These observation counts share this captured cell. Underlying pairs count once here, but can also appear in their peer source cell. Return estimates do not control these counts.', 'bounded-note'));
  root.append(coverageElement('h3', 'Latest discovery / exact query'));
  const discovery = cell.discovery || {};
  root.append(coverageElement('p', 'Checked: ' + coverageTime(discovery.checked_at) + ' · ' + coverageWords(discovery.status || 'not_checked') + ' · Listing: ' + coverageWords(discovery.completeness || 'unknown'), 'discovery-note'));
  root.append(countGrid(discovery, {games:'Unique discovered games', markets:'Discovered markets', native_outcomes:'Native outcomes'}));
  root.append(coverageElement('p', 'Discovery measures the exact captured query, not the provider’s full market universe. Its query window may differ from retained price history. Failed or incomplete checks do not prove that the source has no offerings.', 'discovery-note'));
  diagnostic(root, 'Exact query & listing evidence', discovery);
  root.append(coverageElement('h3', 'Main causes'));
  if (!cell.reasons?.length) root.append(coverageElement('p', 'No recorded gap cause for this captured cell.', 'bounded-note'));
  else {
    root.append(coverageElement('p', 'Affected counts can overlap. Primary counts assign one deterministic cause per affected observation; configuration and query causes can have no retained-observation count.', 'bounded-note'));
    for (const reason of cell.reasons) {
      const section = coverageElement('section', undefined, 'reason');
      section.append(coverageElement('p', reason.label || 'Missing comparison facts', 'reason-title'), coverageElement('p', (categories[reason.category] || 'Processing condition') + ' · ' + coverageCount(reason.count) + ' affected observations · ' + coverageCount(reason.primary_count) + ' primary', 'reason-meta'));
      if (reason.explanation || reason.condition) section.append(coverageElement('p', reason.explanation || reason.condition));
      for (const example of (reason.examples || []).slice(0, 3)) section.append(renderCoverageExample(example));
      diagnostic(section, 'Diagnostic reason code & evidence', {code:reason.code, category:reason.category, overlapping:reason.overlapping, count:reason.count, primary_count:reason.primary_count}); root.append(section);
    }
  }
  root.append(coverageElement('h3', 'Representative original prices'));
  const examples = (cell.examples || []).slice(0, 3);
  if (!examples.length) root.append(coverageElement('p', 'No representative retained original price is available in this captured cell.', 'bounded-note'));
  for (const example of examples) root.append(renderCoverageExample(example));
  root.append(coverageElement('p', 'Examples are bounded representative records, not an exhaustive listing. Prices and source/receipt clocks are shown as captured.', 'bounded-note'));
  diagnostic(root, 'Configuration, capability & publication diagnostics', {id:cell.id, configured:cell.configured, configuration_state:cell.configuration_state, capability:cell.capability, provider:cell.provider, role:cell.role, captured_at:data.captured_at, publication_at:data.publication_at, publication_state:data.publication_state});
}
export {cellTitle};

// Display ages from original capture clocks; reads and filters never reset them.
export function coverageAge(value, now = Date.now()) {
  const at = Date.parse(value);
  if (!Number.isFinite(at)) return 'Unknown';
  if (at > now) return 'Clock is in the future';
  const seconds = Math.floor((now - at) / 1000);
  if (seconds < 60) return seconds + 's ago';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
  if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ' + Math.floor(seconds % 3600 / 60) + 'm ago';
  return Math.floor(seconds / 86400) + 'd ago';
}
export function renderCoverageOutcome(root, data, filters, readError = '') {
  if (!root) return;
  const cells = filterCoverageCells(data?.cells || [], filters), counts = data ? filteredCoverageTotals(data, cells) : {};
  const scope = [filters.league || 'All sports', filters.venue ? sourceName(filters.venue) : 'All sources', filters.market ? coverageFamilies[filters.market] || filters.market : 'All families', filters.period ? coverageWords(filters.period) : 'All periods'];
  if (filters.attention) scope.push('Investigate: ' + coverageWords(filters.attention));
  root.replaceChildren(coverageElement('strong', scope.join(' · ')));
  const failure = data?.publication_error;
  const stale = data?.publication_state === 'stale' || (data?.captured_at && Date.now() - Date.parse(data.captured_at) > 15000);
  const title = readError ? 'Coverage read failed' : failure ? 'Coverage publication failed' : !data || !data.captured_at ? 'Coverage pending · counts unmeasured' : stale ? 'Last-known coverage capture' : 'Captured comparison availability';
  root.append(coverageElement('h2', title));
  root.append(coverageElement('p', 'Capture ' + coverageAge(data?.captured_at) + ' · Publication ' + coverageAge(data?.publication_at), 'capture-age'));
  if (readError || failure) root.append(coverageElement('p', (data?.captured_at ? 'Prior captured measurements remain inspectable; freshness is unverified. ' : 'Current coverage cannot be established. ') + (failure || readError)));
  else if (stale) root.append(coverageElement('p', 'These measurements describe the older capture. A successful page read does not verify current comparisons.'));
  else if (!data?.captured_at) root.append(coverageElement('p', 'No measured capture is available. Pending publication is not zero coverage.'));
  if (data?.captured_at) root.append(coverageElement('p', coverageCount(counts.current_comparison_observations) + ' observations with current supported peers at capture · ' + coverageCount(counts.retained_comparison_observations) + ' retained purchase-source observations. Reference observations excluded.'));
  const states = new Map();
  for (const cell of cells) {const state = coverageCellState(cell); states.set(state, (states.get(state) || 0) + 1);}
  if (states.size) root.append(coverageElement('p', [...states].map(([state,n]) => n + ' ' + state.toLowerCase() + ' cells').join(' · '), 'scope-states'));
  const link = coverageElement('a', 'Browse captured prices →'); link.href = '/odds'; root.append(link);
}
