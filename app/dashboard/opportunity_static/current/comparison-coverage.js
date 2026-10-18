import { el, clockedText, observationState, comparisonState, words, outcomeDisplayKey } from "./board-elements.js";

const coverageCauseLabels = {
  stale_inputs: "Stale inputs",
  missing_peers: "Missing cross-source peers",
  unsupported_matching: "Unsupported or conflicting matching",
  pending_publication: "Pending publication",
  unknown_inputs: "Unknown or unavailable inputs",
};
const coveragePublicationCodes = new Set(["current_dependencies_changed", "comparison_selection_boundary", "background_results_not_published", "matching_binding_changed"]);
function matchingFailure(code) {
  return code?.startsWith("scoring_") || code?.startsWith("scope_review_") || code?.startsWith("scope_registry_") || code?.startsWith("scope_rules_") ||
    ["comparison_peer_matching_unsupported", "comparison_scope_unsupported", "comparison_scope_conflict",
      "comparison_occurrence_unresolved", "comparison_mapping_unavailable", "comparison_mapping_outside_effective_period",
      "comparison_native_unsupported", "comparison_market_type_unsupported", "comparison_period_unsupported",
      "comparison_participant_roles_missing", "comparison_participant_conflict", "comparison_predicate_missing",
      "comparison_predicate_family_conflict", "comparison_predicate_subject_conflict", "comparison_equality_missing",
      "comparison_predicate_conflict", "comparison_scoring_scope_missing", "comparison_normal_payout_unsupported",
      "comparison_normal_payout_missing"].includes(code);
}
function coverageCountText(count, singular) { return count + " " + singular + (count === 1 ? "" : "s"); }

// Count only authored current pairs. This never finds a new peer or promotes a
// historical comparison. The row and the summary share the same aging helpers.
export function scopedCurrentComparisonCoverage(boards, now = Date.now()) {
  const observations = new Set(), games = new Set(), outcomes = new Set(), pairs = new Set(), directions = new Set();
  const reasons = Object.fromEntries(Object.keys(coverageCauseLabels).map(code => [code, {outcomes: new Set(), observations: new Set(), codes: new Set()}]));
  for (const board of boards) for (const q of board.prices || []) {
    const identity = JSON.stringify([board.game_key, q.quote_id]);
    if (observations.has(identity)) continue;
    observations.add(identity);
    const outcome = JSON.stringify([board.game_key, outcomeDisplayKey(q)]), comparison = q.current_comparison;
    const state = comparisonState(comparison, now), inputState = observationState(q, now);
    const inputs = comparison?.inputs || [], venues = new Set(inputs.map(input => input.venue));
    if (state === "current" && inputs.length === 2 && venues.size === 2 && inputs.every(input => outcomeDisplayKey(input) === outcomeDisplayKey(q))) {
      games.add(board.game_key); outcomes.add(outcome); directions.add(identity);
      pairs.add(JSON.stringify([board.game_key, inputs.map(input => input.quote_id).sort()]));
      continue;
    }
    const codes = new Set([comparison?.reason_code, ...(comparison?.reason_codes || []), ...(q.observation_display?.reason_codes || q.freshness?.reasons || [])].filter(Boolean));
    const cause = new Set();
    const sourceState = q.source_health?.state || q.source_state;
    const agedInput = inputState === "last_known" && ["current", "pending"].includes(q.observation_display?.state);
    if (state === "pending" || inputState === "pending" || [...codes].some(code => coveragePublicationCodes.has(code))) cause.add("pending_publication");
    const unavailable = inputState === "unknown" || state === "unknown" || sourceState && !["available", "budget_delayed"].includes(sourceState) ||
      codes.has("source_unavailable") || codes.has("captured_source_unavailable") || codes.has("data_runtime_unhealthy") || codes.has("updates_stopped");
    if (unavailable) cause.add("unknown_inputs");
    if (codes.has("source_expired") || codes.has("pregame_ended") || (state === "last_known" || agedInput) && !unavailable) cause.add("stale_inputs");
    if ([...codes].some(matchingFailure)) cause.add("unsupported_matching");
    if (codes.has("comparison_peer_missing")) cause.add("missing_peers");
    // Legacy captured frames have no reason code. Keep unknown facts explicit.
    if (!cause.size) cause.add("unknown_inputs");
    for (const code of cause) {
      reasons[code].outcomes.add(outcome); reasons[code].observations.add(identity);
      for (const reason of codes) reasons[code].codes.add(reason);
    }
  }
  return {current_games: games.size, current_outcomes: outcomes.size, current_team_outcomes: outcomes.size, current_pairs: pairs.size, current_directions: directions.size,
    retained_observations: observations.size, reasons};
}

export function appendComparisonCoverage(root, boards, key = "comparison-coverage") {
  const box = el("section", undefined, "comparison-coverage");
  box.setAttribute("aria-label", "Current comparison coverage");
  box.append(clockedText("p", now => {
    const value = scopedCurrentComparisonCoverage(boards, now);
    return coverageCountText(value.current_games, "game") + " with current comparisons · " + coverageCountText(value.current_outcomes, "market outcome") +
      " covered · " + coverageCountText(value.retained_observations, "retained price observation");
  }, "current-comparison-counts"));
  const details = el("details", undefined, "comparison-coverage-reasons");
  details.dataset.key = key;
  details.append(el("summary", "Comparison coverage details"));
  details.append(clockedText("p", now => {
    const value = scopedCurrentComparisonCoverage(boards, now);
    return coverageCountText(value.current_pairs, "underlying current cross-source pair") + " · " + coverageCountText(value.current_directions, "signed comparison direction") + ". Each pair counts once across its signed directions; each exact market outcome counts once per game, including its line, period and scoring rules.";
  }, "current-pair-count"));
  for (const [code, label] of Object.entries(coverageCauseLabels)) details.append(clockedText("p", now => {
    const value = scopedCurrentComparisonCoverage(boards, now).reasons[code];
    return label + ": " + coverageCountText(value.outcomes.size, "market outcome") + " · " + coverageCountText(value.observations.size, "retained observation") +
      (value.codes.size ? " · " + [...value.codes].sort().map(words).join(", ") : "");
  }, "comparison-coverage-cause"));
  details.append(el("small", "Reasons can overlap and describe observations lacking a current captured pair. Counts follow the displayed games and original freshness limits."));
  box.append(details); root.append(box);
  return box;
}
