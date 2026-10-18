// Pure captured-publication helpers. No requests, model estimates or clock edits.
export const coverageNames = {kalshi:"Kalshi", polymarket_us:"Polymarket US", novig:"Novig", prophetx:"ProphetX", pinnacle:"Pinnacle"};
export const coverageFamilies = {winner:"Winner / moneyline", moneyline:"Winner / moneyline", spread:"Spread", total:"Total", team_total:"Team total", futures:"Futures"};
export const coverageWords = value => String(value ?? "Unknown").replaceAll("_", " ");
export const coverageNumber = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
export const coverageCount = value => coverageNumber(value) === null ? "Unknown" : value.toLocaleString("en-US");
export const coverageSource = cell => cell.venue || cell.source;
export const coverageSport = cell => cell.sport || cell.league;
export const coverageFamily = cell => cell.family === "moneyline" ? "winner" : cell.family;
export const coveragePeriod = cell => cell.period || "unknown";
export function coverageRatio(numerator, denominator, scope = "retained observations in this captured cell") {
  const n = coverageNumber(numerator), d = coverageNumber(denominator);
  const value = n !== null && d !== null && d > 0 && n <= d ? n / d : null;
  return {numerator:n, denominator:d, value, scope};
}
export function cellRatio(cell, kind = "supported_peer") {
  const supplied = cell.ratios?.[kind], counts = cell.counts || {};
  const key = {supported_peer:"supported_comparison_observations", current_peer:"current_comparison_observations", current:"current_observations"}[kind];
  return coverageRatio(supplied && Object.hasOwn(supplied, "numerator") ? supplied.numerator : counts[key],
    supplied && Object.hasOwn(supplied, "denominator") ? supplied.denominator : (kind === "current" ? counts.retained_observations : counts.retained_comparison_observations ?? counts.retained_observations),
    supplied?.scope || "retained observations in this captured cell");
}
export function coveragePercent(ratio) {
  return ratio.value === null ? "N/A" : (ratio.value * 100).toLocaleString("en-US", {maximumFractionDigits:1}) + "%";
}
export function coverageRatioText(ratio, label) {
  return coveragePercent(ratio) + " · " + coverageCount(ratio.numerator) + " / " + coverageCount(ratio.denominator) + " " + label + " · " + ratio.scope;
}
export function coverageCellState(cell) {
  const state = cell.configuration_state;
  if (state === "held") return "Source held";
  if (state === "paused") return "Source paused";
  if (state === "disabled") return "Disabled";
  if (state === "not_configured" || cell.configured === false) return "Not configured";
  if (cell.capability?.state === "unsupported") return "Unsupported capability";
  if (cell.role === "reference" || cell.capability?.state === "reference_only") return "Reference only";
  if (coverageNumber(cell.counts?.retained_observations) === null) return "Not measured";
  if (!cell.counts.retained_observations && !cell.discovery?.checked_at) return "Not checked";
  if (!cell.counts.retained_observations) return "No retained prices";
  return "Implemented";
}
export function filterCoverageCells(cells, filters = {}) {
  return cells.filter(cell => {
    if (filters.league && coverageSport(cell) !== filters.league || filters.venue && coverageSource(cell) !== filters.venue ||
      filters.market && coverageFamily(cell) !== filters.market || filters.period && coveragePeriod(cell) !== filters.period) return false;
    const c = cell.counts || {}, ratio = cellRatio(cell);
    if (filters.attention === "low") return ratio.value !== null && ratio.value < 0.5;
    if (filters.attention === "stale") return c.last_known_observations > 0;
    if (filters.attention === "gaps") return c.gap_observations > 0 || coverageCellState(cell) !== "Implemented";
    return true;
  });
}
const observationKeys = ["retained_observations", "retained_comparison_observations", "retained_reference_observations", "displayed_observations", "displayed_comparison_directions", "displayed_current_comparison_directions", "current_observations", "last_known_observations", "unknown_age_observations", "supported_comparison_observations", "current_comparison_observations", "gap_observations", "retained_peer_candidate_observations", "no_retained_peer_observations", "identity_matched_observations", "meaning_supported_observations", "input_supported_observations", "input_current_peer_observations", "eligible_current_directions", "publication_pending_directions", "display_disagreement_directions"];
export function filteredCoverageTotals(data, cells) {
  // A native observation belongs to one cell. Pair and outcome totals do not:
  // use the publication's compact canonical groups or keep those totals unknown.
  // A first publication has no measured cohort. Its empty compact groups are
  // placeholders, so filtering them cannot establish measured zero totals.
  if (data.captured_at === null) return Object.fromEntries([...observationKeys, "comparable_outcomes", "underlying_pairs", "signed_comparison_directions", "matched_occurrences"].map(key => [key, null]));
  const counts = Object.fromEntries(observationKeys.map(key => [key, cells.every(cell => coverageNumber(cell.counts?.[key]) !== null) ? cells.reduce((n, cell) => n + cell.counts[key], 0) : null]));
  if (cells.length === data.cells.length && data.global_totals) return {...counts, ...data.global_totals};
  const groups = data.aggregation?.outcomes;
  if (Array.isArray(groups)) {
    const selected = new Set(cells.map(cell => cell.id)), byId = new Map(data.cells.map(cell => [cell.id, cell]));
    let outcomes = 0, pairs = 0, directions = 0;
    const crossPairs = values => {const total = values.reduce((n, value) => n + value, 0); return (total * total - values.reduce((n, value) => n + value * value, 0)) / 2;};
    for (const group of groups) {
      const entries = Object.entries(group.cells || {}), all = new Map(), outside = new Map();
      if (entries.some(([id, n]) => selected.has(id) && n > 0)) outcomes++;
      for (const [id, n] of entries) {
        const source = coverageSource(byId.get(id) || {source:id});
        all.set(source, (all.get(source) || 0) + n);
        if (!selected.has(id)) outside.set(source, (outside.get(source) || 0) + n);
      }
      pairs += crossPairs([...all.values()]) - crossPairs([...outside.values()]);
      const total = [...all.values()].reduce((n, value) => n + value, 0);
      for (const [id, n] of entries) if (selected.has(id)) directions += n * (total - all.get(coverageSource(byId.get(id) || {source:id})));
    }
    Object.assign(counts, {comparable_outcomes:outcomes, underlying_pairs:pairs, signed_comparison_directions:directions});
  }
  if (Array.isArray(data.aggregation?.occurrences)) {
    const selected = new Set(cells.map(cell => cell.id));
    counts.matched_occurrences = data.aggregation.occurrences.filter(ids => ids.some(id => selected.has(id))).length;
  }
  if (Array.isArray(data.aggregation?.inputs)) {
    const selected = new Set(cells.map(cell => cell.id));
    const pairs = entries => {const values = Object.values(entries), total = values.reduce((n, v) => n + v, 0); return (total * total - values.reduce((n, v) => n + v * v, 0)) / 2;};
    const touching = entries => pairs(entries) - pairs(Object.fromEntries(Object.entries(entries).filter(([id]) => !selected.has(id))));
    counts.eligible_current_pairs = data.aggregation.inputs.reduce((n, g) => n + touching(g.current_cells), 0);
    counts.supported_noncurrent_pairs = data.aggregation.inputs.reduce((n, g) => n + touching(g.cells) - touching(g.current_cells), 0);
    counts.published_current_pairs = (data.aggregation.publications || []).filter(ids => ids.some(id => selected.has(id))).length;
  }
  return counts;
}
export function coverageRows(cells, sort = "scope") {
  const groups = new Map();
  for (const cell of cells) {
    const key = [coverageSport(cell), coverageSource(cell)].join("/");
    if (!groups.has(key)) groups.set(key, {key, sport:coverageSport(cell), source:coverageSource(cell), cells:[]});
    groups.get(key).cells.push(cell);
  }
  const score = row => sort === "low" ? Math.min(...row.cells.map(cell => cellRatio(cell).value ?? Infinity)) :
    row.cells.reduce((n, cell) => n + (cell.counts?.[sort === "stale" ? "last_known_observations" : "gap_observations"] || 0), 0);
  return [...groups.values()].sort((a, b) => (sort === "scope" ? 0 : sort === "low" ? score(a) - score(b) : score(b) - score(a)) || a.sport.localeCompare(b.sport) || a.source.localeCompare(b.source));
}
export function coverageOddsHref(cell) {
  const scope = cell.odds_scope || {}, params = new URLSearchParams();
  for (const [key, value] of Object.entries({league:scope.league || coverageSport(cell), venue:scope.venue || coverageSource(cell), family:scope.market || coverageFamily(cell), period:scope.period || coveragePeriod(cell)})) {
    if (value && value !== "unknown") params.set(key, value === "moneyline" ? "winner" : value);
  }
  return "/odds?" + params;
}
