import { numeric, percent } from "./board-client.js";
import { el, side, venue, words, time, price, metric, americanDecimal, labelsFor } from "./board-elements.js";

const comparisonStates = ["numeric_current", "numeric_last_known", "missing_reference", "unsupported_inputs", "calculation_failed", "not_evaluated"];
const comparisonMetrics = {
  buffered_ev_usd: ["buffered_return_percent", "Estimated return", 0],
  conditional_buffered_ev_usd: ["conditional_buffered_return_percent", "Return · decisive outcomes only", 1],
  buffered_complete_modeled_minimum_usd: ["buffered_complete_minimum_return_percent", "Minimum margin · modeled outcomes", 0],
  buffered_decisive_opposing_margin_usd: ["buffered_decisive_return_percent", "Margin · decisive outcomes only", 1],
};
// Financial category decides the field. Never pick the most favorable number.
export function primaryComparisonMetric(row, view) {
  const fields = view === "arbs" ? (row.classification?.category === "positive_complete_modeled_pair" ? ["buffered_complete_modeled_minimum_usd"] : ["buffered_decisive_opposing_margin_usd"]) : ["buffered_ev_usd", "conditional_buffered_ev_usd"];
  for (const field of fields) {
    const [percentField, label, category] = comparisonMetrics[field], state = row.availability?.metrics?.[field]?.state;
    if (row.availability?.numeric_metrics?.includes(field) && ["numeric_current", "numeric_last_known"].includes(state) && numeric(row.financial_metrics?.[field]) !== null && numeric(row.financial_metrics?.[percentField]) !== null)
      return {field, percentField, label, category, state, value: row.financial_metrics[percentField]};
  }
  return null;
}
export function compareComparisonMetrics(a, b, view) {
  const x = primaryComparisonMetric(a, view), y = primaryComparisonMetric(b, view);
  if (!x || !y) return Number(!x) - Number(!y);
  return x.category - y.category || numeric(y.value) - numeric(x.value);
}
const comparisonCauseLabels = {
  selected_reference_missing: "Selected reference missing",
  short_collateral_unresolved: "Short collateral unsupported",
  source_unavailable: "Source status unavailable",
  execution_source_unavailable: "Execution source paused or unavailable",
  source_expired: "Execution prices are older",
  reference_expired: "Reference prices are older",
  reference_stale_or_unknown: "Reference freshness is stale or unknown",
  source_price_expired: "Source price freshness has expired",
  calculation_read_failed: "Calculation read failed",
  calculation_failed: "Calculation failed",
  complete_probability_partition_unsupported: "Complete outcome probabilities unsupported",
  unsupported_model_or_contract: "Model or contract unsupported",
  invalid_inputs: "Inputs invalid or conflicting",
};
function causeLabel(code) { return comparisonCauseLabels[code] || "Unsupported input (" + words(code) + ")"; }
function unavailableLabel(a, shared) {
  if (!a || a.state === "not_evaluated") return "Not evaluated";
  const local = a.reason_codes.filter(c => !shared.has(c));
  if (local.length) return causeLabel(local[0]);
  return "Unavailable · see availability";
}
export function comparisonWarning(row, view, chosen) {
  if (!chosen) return "";
  const c = row.classification || {};
  if (Object.entries(c.adverse_outcomes || {}).some(([state, v]) => !["a_wins", "b_wins"].includes(state) && numeric(v) < 0)) return "Can lose on tie or exceptional settlement · Details";
  if (c.unknown_outcomes?.length) return "Some settlement payouts unknown · Details";
  if (view === "arbs" && chosen.field === "buffered_decisive_opposing_margin_usd") return "Ties and cancellations are outside this margin";
  return "";
}
export function scopedComparisonAvailability(boards, errors, games) {
  const counts = Object.fromEntries(comparisonStates.map(s => [s, 0])), causes = new Map();
  let positive = 0, evaluated = false;
  function addCause(c) {
    const entry = causes.get(c.code) || {code: c.code, affected_results: 0, affected_games: 0, venues: []};
    entry.affected_results += c.affected_results; entry.affected_games += c.affected_games;
    entry.venues = [...new Set([...entry.venues, ...c.venues])]; causes.set(c.code, entry);
  }
  for (const b of boards) {
    const a = b.availability;
    if (!a) continue;
    evaluated ||= a.outcome !== "not_evaluated";
    for (const state of comparisonStates) counts[state] += a.counts[state];
    positive += a.positive_results;
    a.causes.forEach(addCause);
  }
  for (const e of errors) {
    const a = e.availability;
    if (!a) continue;
    evaluated ||= a.state !== "not_evaluated"; counts[a.state]++;
    a.reason_codes.forEach(code => addCause({code, affected_results: 1, affected_games: 1, venues: []}));
  }
  const total = Object.values(counts).reduce((a, b) => a + b, 0), numericResults = counts.numeric_current + counts.numeric_last_known;
  return {counts, total_results: total, numeric_results: numericResults, current_results: counts.numeric_current, positive_results: positive, games,
    outcome: !evaluated ? "not_evaluated" : !numericResults && total ? "unavailable" : positive ? "positive" : numericResults < total ? "partial" : !counts.numeric_current && numericResults ? "last_known_only" : "evaluated_no_positive", causes: [...causes.values()]};
}

// Pure selection/presentation. Every callback keeps the original row and game;
// grouping never combines instrument identities, financial values or clocks.
export function crossVenue(row) {
  return row.legs?.length === 2 && row.legs.every(l => typeof l.venue === "string" && l.venue.length) && row.legs[0].venue !== row.legs[1].venue;
}
export function createComparisonSlate({ content, onDetails, onOriginal }) {
  function action(root, label, key, callback) {
    const button = el("button", label, "slate-action");
    button.dataset.key = key;
    button.onclick = () => callback(button);
    root.append(button);
    return button;
  }
  function heading(root, g) {
    const h = el("div", undefined, "slate-game-heading");
    h.append(el("h2", g.title), el("small", "Kickoff " + time(g.start_at)));
    root.append(h);
  }
  function delivery(b, paused) {
    return b.delivery_state === "pending" ? paused ? "Current updates paused" : "Calculation pending · prices available" : b.delivery_state === "stopped" ? "Collection stopped" : "";
  }
  function referenceEvidence(root, g, b) {
    const d = el("details", undefined, "reference-evidence");
    d.dataset.key = g.game_key + ":reference";
    d.append(el("summary", "Reference originals & method"));
    const { participant } = labelsFor(g.participants);
    d.append(el("p", words(b.benchmark.method) + " · " + words(b.benchmark.conditioning) + " · " + (b.benchmark.freshness === "current" ? "Current benchmark inputs" : "As-of benchmark")));
    for (const f of b.benchmark.fair || []) d.append(el("p", participant(f.participant) + " · fair decimal " + f.fair_decimal_odds + " · decisive probability " + f.decisive_probability));
    for (const o of b.benchmark.originals || []) d.append(el("p", participant(o.selection?.participant_id) + " · offered decimal " + o.decimal_odds + " · Source " + (o.book_at || o.market_at || "Unknown") + " · Received " + (o.received_at || "Unknown")));
    if (!b.benchmark.available) d.append(el("p", "Selected benchmark unavailable · " + words(b.benchmark.reason)));
    root.append(d);
  }
  function odds(g, b, paused) {
    const root = el("article", undefined, "slate-game slate-odds");
    root.dataset.key = g.game_key;
    heading(root, g);
    if (delivery(b, paused)) root.append(el("small", delivery(b, paused), "pending-label"));
    const table = el("div", undefined, "slate-prices");
    const books = ["novig", "prophetx", "kalshi", "polymarket_us"];
    for (const team of g.participants) {
      const row = el("div", undefined, "slate-price-row team");
      row.append(el("strong", team.name, "slate-team-name"));
      for (const book of books) {
        const cell = el("div", undefined, "slate-price-cell");
        cell.append(el("small", venue(book), "mobile-price-label"));
        // Use the supplied participant/predicate. Short is NOT opponent YES.
        const quotes = b.prices.filter(q => q.selection.participant === team.id && q.venue === book && q.selection.predicate === "win");
        if (!quotes.length) {
          const absent = el("span", "—", "unavailable-price");
          absent.title = venue(book) + " price unavailable for " + team.name;
          absent.setAttribute("aria-label", absent.title);
          cell.append(absent);
        }
        for (const q of quotes) {
          const native = q.native_side.toLowerCase() !== "bookmaker_outcome";
          const label = price(q) + (native ? " · " + side(q.native_side) : "");
          const button = action(cell, label, g.game_key + ":" + q.quote_id, button => onOriginal(q, button, g));
          const meaning = labelsFor(g.participants).selection(q) + " · " + venue(book) + " · original " + q.original.value + " " + words(q.original.units) + " · " + (q.freshness?.status === "current" ? "Current inputs" : "As-of inputs") + " · Source " + (q.freshness?.source_at || "Unknown") + " · Received " + (q.freshness?.received_at || "Unknown");
          button.title = meaning;
          button.setAttribute("aria-label", meaning + " · Open original price");
          const age = el("small", q.freshness?.status === "current" ? "Current" : "Last-known", "compact-source-clock");
          age.title = meaning;
          cell.append(age);
        }
        row.append(cell);
      }
      const fair = el("div", undefined, "slate-price-cell slate-fair");
      const f = b.benchmark.fair?.find(f => f.participant === team.id);
      fair.append(el("strong", f ? "Fair " + americanDecimal(f.fair_decimal_odds) : "Fair unavailable"));
      if (b.benchmark.available && b.benchmark.freshness !== "current") fair.append(el("small", "Last-known"));
      row.append(fair);
      table.append(row);
    }
    root.append(table);
    const alternatives = b.prices.filter(q => q.selection.predicate !== "win" || !g.participants.some(p => p.id === q.selection.participant));
    if (alternatives.length) {
      const d = el("details", undefined, "slate-alternatives");
      d.dataset.key = g.game_key + ":alternatives";
      d.append(el("summary", "Other native instruments · " + alternatives.length));
      for (const q of alternatives) action(d, labelsFor(g.participants).selection(q) + " · " + venue(q.venue) + " " + price(q), g.game_key + ":" + q.quote_id, button => onOriginal(q, button, g));
      root.append(d);
    }
    referenceEvidence(root, g, b);
    content.append(root);
  }
  function financial(root, g, b, row, view, paused, shared) {
    const item = el("div", undefined, "slate-result " + (view === "arbs" ? "slate-arb" : "slate-ev"));
    item.dataset.key = g.game_key + ":" + (row.quote_id || row.pair_id);
    item.setAttribute("aria-label", g.title + " · " + labelsFor(g.participants).selection(view === "ev" ? row : row.legs[0]));
    const identity = el("div", undefined, "slate-result-identity"), { selection } = labelsFor(g.participants);
    if (view === "ev") identity.append(el("strong", venue(row.venue)), el("span", price(row), "execution-price"));
    else for (const leg of row.legs) {
      const line = el("p", undefined, "slate-leg");
      line.append(el("strong", selection(leg)), el("span", venue(leg.venue) + " · " + price(leg)));
      identity.append(line);
    }
    item.append(identity);
    const chosen = primaryComparisonMetric(row, view), values = el("div", undefined, "slate-result-values");
    if (chosen) {
      const prefix = chosen.state === "numeric_last_known" ? "Last-known · " : "";
      metric(values, prefix + chosen.label, chosen.value, v => (numeric(v) > 0 ? "+" : "") + percent(v));
      item.dataset.metric = chosen.field;
      item.dataset.availability = chosen.state;
    } else {
      const status = el("div", undefined, "comparison-unavailable");
      status.append(el("strong", unavailableLabel(row.availability, shared)));
      values.append(status);
      item.dataset.availability = row.availability?.state || "not_evaluated";
    }
    item.append(values);
    const warning = comparisonWarning(row, view, chosen);
    if (warning) {
      const note = el("small", warning, "slate-result-note");
      note.dataset.caution = "true";
      item.append(note);
    }
    action(item, "Details", item.dataset.key, button => onDetails(row, button, g));
    root.append(item);
  }
  function gameReference(root, g, b) {
    const line = el("p", undefined, "game-reference");
    line.append(el("span", venue(b.benchmark.venue) + " fair American · "));
    line.append(el("span", g.participants.map(p => {
      const f = b.benchmark.fair?.find(f => f.participant === p.id);
      return p.name + " " + (f ? americanDecimal(f.fair_decimal_odds) : "unavailable");
    }).join(" · ")));
    if (b.benchmark.freshness !== "current" && b.benchmark.available) line.append(el("small", "Last-known reference"));
    root.append(line);
  }
  function availabilityNotice(scope, filter, onShowAll) {
    const notice = el("aside", undefined, "availability-notice");
    notice.setAttribute("aria-label", "Calculation availability");
    const lastKnown = scope.counts.numeric_last_known > 0 && !scope.current_results;
    const title = lastKnown ? "Last-known estimates available" : ({
      partial: "Some calculations are unavailable", unavailable: "Calculations unavailable",
      not_evaluated: "Calculations not evaluated", evaluated_no_positive: "No current positive result",
      positive: "Current estimates available", last_known_only: "Last-known estimates available",
    })[scope.outcome];
    notice.append(el("strong", title));
    if (lastKnown) notice.append(el("p", "Older prices or references support inspection, but are excluded from current Positive and Hedges."));
    else if (scope.outcome === "unavailable") notice.append(el("p", "This scope could not supply a supported estimate. Prices remain inspectable in Odds."));
    else if (scope.outcome === "not_evaluated") notice.append(el("p", "No financial evaluation is available for this scope."));
    const counts = [];
    if (scope.current_results) counts.push(scope.current_results + " current numeric");
    if (scope.counts.numeric_last_known) counts.push(scope.counts.numeric_last_known + " last-known numeric");
    const unavailable = scope.total_results - scope.numeric_results;
    if (unavailable) counts.push(unavailable + " unavailable or not evaluated");
    notice.append(el("small", counts.join(" · ") + (counts.length ? " · " : "") + scope.total_results + " inspected results/candidates before filtering"));
    if (lastKnown && filter !== "all") action(notice, "View last-known estimates", "last-known-estimates", onShowAll);
    if (scope.causes.length) {
      const d = el("details", undefined, "availability-causes"); d.dataset.key = "availability-causes";
      d.append(el("summary", "Why these results are last-known or unavailable"));
      for (const cause of scope.causes) d.append(el("p", causeLabel(cause.code) + " · " + cause.affected_results + " inspected results/candidates in " + cause.affected_games + " games" + (cause.venues.length ? " · " + cause.venues.map(venue).join(", ") : "")));
      if (scope.causes.length > 1) d.append(el("small", "Causes can overlap; their counts are not added."));
      const link = el("a", "Check source status in Admin"); link.href = "/admin"; d.append(link); notice.append(d);
    }
    content.append(notice);
  }
  function advancedHistory(boards, visible) {
    const saved = boards.flatMap(b => b.rows.filter(r => r.legs?.length === 2 && r.legs[0].venue === r.legs[1].venue).map(row => ({ b, row, g: visible.get(b.game_key) })));
    if (!saved.length) return;
    const d = el("details", undefined, "same-venue-history");
    d.dataset.key = "advanced-same-venue";
    d.append(el("summary", "Advanced current portfolios · same venue"));
    d.append(el("p", "Outside ordinary cross-venue Arbs. Original calculations remain unchanged. Use All comparisons to inspect all available current portfolios here."));
    for (const { row, g } of saved) action(d, g.title + " · " + row.legs.map(l => labelsFor(g.participants).selection(l) + " / " + venue(l.venue)).join(" + ") + " · Details", g.game_key + ":" + row.pair_id, button => onDetails(row, button, g));
    content.append(d);
  }
  function draw(v, { view, filter, game = "", search = "", sort = "best", onShowAll }) {
    content.replaceChildren();
    content.classList.toggle("compact-odds", view === "odds");
    content.classList.toggle("compact-comparisons", view !== "odds");
    const visible = new Map(v.games.filter(g => (!game || g.game_key === game) && g.title.toLowerCase().includes(search.toLowerCase())).map(g => [g.game_key, g]));
    const boards = v.boards.filter(b => visible.has(b.game_key)), paused = v.storage?.state === "unavailable";
    const rows = boards.flatMap(b => b.rows.filter(row => view !== "arbs" || crossVenue(row)).map(row => ({ g: visible.get(b.game_key), b, row })));
    rows.sort((a, b) => compareComparisonMetrics(a.row, b.row, view) || (a.g.start_at || "").localeCompare(b.g.start_at || "") || a.g.game_key.localeCompare(b.g.game_key) || String(a.row.quote_id || a.row.pair_id).localeCompare(String(b.row.quote_id || b.row.pair_id)));
    const scope = scopedComparisonAvailability(boards, (v.errors || []).filter(e => visible.has(e.game_key)), visible.size);
    const shared = new Set(scope.causes.filter(c => c.affected_results > 1).map(c => c.code));
    const summary = el("div", undefined, "slate-summary");
    summary.append(el("strong", visible.size + " matching games · " + v.games.length + " in covered catalog"));
    if (view !== "odds") summary.append(el("span", rows.length + (view === "arbs" ? " cross-venue comparisons" : " comparisons") + " · " + (filter === "all" ? "all returned results" : filter === "hedges" ? "positive rule-sensitive hedges" : "eligible positive results")));
    const overview = el("div", undefined, "slate-overview");
    overview.append(summary);
    const coverage = el("div", undefined, "slate-coverage");
    coverage.append(el("small", "Observed coverage"));
    for (const book of ["novig", "prophetx", "kalshi", "polymarket_us", "pinnacle"]) coverage.append(el("span", venue(book) + " " + boards.filter(b => b.prices.some(q => q.venue === book) || (b.benchmark.venue === book && b.benchmark.available)).length + "/" + visible.size));
    overview.append(coverage);
    if (v.games.length) content.append(overview);
    if (!visible.size) {
      const empty = el("div", undefined, "empty");
      empty.append(el("h2", v.games.length ? "No games match this filter" : "No current games yet"), el("p", v.games.length ? "Clear the team search or choose All games." : "Check source status in Admin. Available games appear here after an observation is received."));
      if (!v.games.length) { const a = el("a", "Check sources in Admin"); a.href = "/admin"; empty.append(a); }
      content.append(empty);
      return;
    }
    if (view === "odds") {
      if (boards.some(b => b.prices.some(q => q.native_side.toLowerCase() !== "bookmaker_outcome"))) content.append(el("small", "Native sides have their own tie and refund terms. Open a price to inspect its contract.", "native-meaning"));
      const h = el("div", undefined, "slate-price-headings slate-shared-headings");
      h.append(el("span", "Game / team"), ...["novig", "prophetx", "kalshi", "polymarket_us"].map(book => el("span", venue(book))), el("span", venue(v.policy.benchmark_venue) + " reference"));
      content.append(h);
      for (const g of visible.values()) {
        const b = boards.find(b => b.game_key === g.game_key);
        if (b) odds(g, b, paused);
        else content.append(el("p", g.title + " · Current prices unavailable"));
      }
      return;
    }
    availabilityNotice(scope, filter, onShowAll);
    if (!rows.length) {
      const empty = el("div", undefined, "empty");
      const heading = scope.outcome === "evaluated_no_positive" || scope.outcome === "positive"
        ? filter === "all" ? "No returned comparisons" : filter === "hedges" ? "No positive rule-sensitive hedges" : "No current positive result"
        : scope.outcome === "not_evaluated" ? "Not evaluated" : scope.numeric_results ? "No current positive result" : "No supported estimates in this scope";
      empty.append(el("h2", heading));
      if (filter !== "all" && !(scope.counts.numeric_last_known && !scope.current_results)) {
        empty.append(el("p", "Inspect signed and conditional results in All comparisons."));
        action(empty, "Show all comparisons", "show-all-comparisons", onShowAll);
      }
      content.append(empty);
    }
    const groups = new Map();
    for (const entry of rows) {
      if (!groups.has(entry.g.game_key)) groups.set(entry.g.game_key, []);
      groups.get(entry.g.game_key).push(entry);
    }
    const ordered = [...groups.values()];
    if (sort === "start") ordered.sort((a, b) => (a[0].g.start_at || "").localeCompare(b[0].g.start_at || ""));

    for (const entries of ordered) {
      const { g, b } = entries[0], root = el("article", undefined, "slate-comparison-game");
      root.dataset.key = g.game_key;
      heading(root, g);
      gameReference(root, g, b);
      if (view === "ev") {
        const instruments = new Map();
        for (const entry of entries) {
          // All economically identifying fields are retained, including native
          // side, period and outcome ID; no values are aggregated.
          const key = JSON.stringify([Object.entries(entry.row.selection).sort(([a], [b]) => a.localeCompare(b)), entry.row.native_side]);
          if (!instruments.has(key)) instruments.set(key, []);
          instruments.get(key).push(entry);
        }
        for (const instrument of instruments.values()) {
          const section = el("section", undefined, "slate-instrument"), row = instrument[0].row;
          section.append(el("h3", labelsFor(g.participants).selection(row)));
          for (const e of instrument) financial(section, g, b, e.row, view, paused, shared);
          root.append(section);
        }
        referenceEvidence(root, g, b);
      } else for (const e of entries) financial(root, g, b, e.row, view, paused, shared);
      content.append(root);
    }
    const missing = boards.filter(b => !b.rows.length && (b.delivery_state === "pending" || filter === "all"));
    const errors = (v.errors || []).filter(e => visible.has(e.game_key));
    if (missing.length || errors.length) {
      const d = el("details", undefined, "slate-pending");
      d.dataset.key = "pending-games";
      d.append(el("summary", missing.length + errors.length + " games with no current calculations"));
      for (const b of missing) d.append(el("p", visible.get(b.game_key).title + " · " + (delivery(b, paused) || words(b.empty_reason)) + " · Original prices in Odds"));
      for (const e of errors) d.append(el("p", visible.get(e.game_key).title + " · " + words(e.reason)));
      content.append(d);
    }
    if (view === "arbs") advancedHistory(boards, visible);
  }
  return { draw };
}
