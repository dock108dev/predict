import { numeric, money, percent, quantity } from "./board-client.js";

export const $ = (id) => document.getElementById(id),
  el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
const names = {
  pinnacle: "Pinnacle",
  novig: "Novig",
  prophetx: "ProphetX",
  kalshi: "Kalshi",
  polymarket_us: "Polymarket US",
};
const side = (v) =>
  ({
    yes: "YES",
    no: "NO",
    long: "Long",
    short: "Short",
    bookmaker_outcome: "winner",
  })[String(v).toLowerCase()] || v;
const unit = (v) =>
  ({ stake_usd: "USD stake", dollar_face_contracts: "$1 face contracts" })[v] ||
  words(v);
const venue = (v) => names[v] || v,
  words = (v) => String(v || "Unknown").replaceAll("_", " "),
  time = (v) =>
    v
      ? new Date(v).toLocaleString("en-US", {
          timeZone: "America/New_York",
          timeZoneName: "short",
          month: "short",
          day: "numeric",
          year: "numeric",
          hour: "numeric",
          minute: "2-digit",
          second: "2-digit",
        })
      : "Unknown";
const residual = (v) =>
  numeric(v) > 0 && numeric(v) < 0.01
    ? "<$0.01 (" + quantity(v) + " USD)"
    : money(v);
function textLine(root, name, value) {
  const p = el("p");
  p.append(el("strong", name + ": "), document.createTextNode(value));
  root.append(p);
}
function metric(root, label, value, format = money) {
  const n = el("div", undefined, "metric");
  n.append(
    el("small", label),
    el(
      "strong",
      format(value),
      numeric(value) < 0 ? "negative" : numeric(value) > 0 ? "positive" : "",
    ),
  );
  root.append(n);
}
function freshness(root, f) {
  root.append(
    el(
      "span",
      f?.status === "current" ? "Current inputs" : "As-of inputs",
      "tag",
    ),
  );
  if (f?.source_at) root.append(el("small", "Source " + time(f.source_at)));
  if (f?.reasons?.length)
    root.append(el("small", f.reasons.map(words).join(" · ")));
}
function price(q) {
  return q.common_odds?.supported
    ? q.common_odds.american
    : quantity(q.original?.value) + " " + words(q.original?.units);
}
// Observation facts have their own clocks and availability. Estimate status is
// deliberately not consulted when deciding whether a source price is current.
export function observationStatus(q, now = Date.now()) {
  const health = q.source_health || {}, state = health.state || q.source_state;
  return observationStateLabel(observationState(q, now)) + " price" +
    " · Source " + words(state).toLowerCase();
}
export function observationState(q, now = Date.now()) {
  const state = q.observation_display?.state;
  const until = Date.parse(q.observation_display?.current_until);
  if (["current", "pending"].includes(state) && Number.isFinite(until) && now > until) return "last_known";
  if (["current", "pending", "last_known", "unknown"].includes(state)) return state;
  if (q.freshness?.status === "current") return "current";
  return q.times?.source_at || q.freshness?.source_at ? "last_known" : "unknown";
}
export function observationStateLabel(state) {
  return ({current: "Current", pending: "Pending publication", last_known: "Last-known", unknown: "Unknown/unavailable"})[state] || "Unknown/unavailable";
}
export function relativeAge(timestamp, now = Date.now()) {
  const instant = Date.parse(timestamp);
  if (!Number.isFinite(instant)) return "Unknown age";
  const seconds = Math.floor((now - instant) / 1000);
  if (seconds < -1) return "Source clock is ahead";
  if (seconds < 1) return "under 1s old";
  if (seconds < 60) return seconds + "s old";
  if (seconds < 3600) return Math.floor(seconds / 60) + "m " + seconds % 60 + "s old";
  if (seconds < 86400) return Math.floor(seconds / 3600) + "h " + Math.floor(seconds % 3600 / 60) + "m old";
  return Math.floor(seconds / 86400) + "d " + Math.floor(seconds % 86400 / 3600) + "h old";
}
function prefixedAge(timestamp, prefix, now = Date.now()) {
  const age = relativeAge(timestamp, now);
  return prefix === "Source " && age === "Source clock is ahead" ? age : prefix + age;
}
export function ageNode(timestamp, prefix = "") {
  const node = el("span", prefixedAge(timestamp, prefix), "relative-age");
  node.dataset.ageAt = timestamp || "";
  node.dataset.agePrefix = prefix;
  node.title = timestamp ? time(timestamp) + " · " + timestamp : "Original source time unknown";
  return node;
}
export function clockedText(tag, textForTime, cls) {
  const node = el(tag, textForTime(Date.now()), cls);
  node.dataset.clockedText = "true";
  node.clockText = textForTime;
  return node;
}
// Text-only clock updates preserve focus and disclosures; they never read data
// or recompute prices or financial estimates. State can only age past the
// server-supplied deadline; no new freshness threshold is introduced here.
export function updateRelativeAges(root, now = Date.now()) {
  for (const node of root.querySelectorAll("[data-age-at]")) {
    const next = prefixedAge(node.dataset.ageAt, node.dataset.agePrefix || "", now);
    if (node.textContent !== next) node.textContent = next;
  }
  for (const node of root.querySelectorAll("[data-clocked-text]")) {
    const next = node.clockText(now);
    if (node.textContent !== next) node.textContent = next;
  }
}
export function preserveDisclosures(root, draw) {
  const open = [...root.querySelectorAll("details[open]")].map(d => d.dataset.key);
  const active = document.activeElement, key = active?.closest?.("details")?.dataset.key;
  const focusedSummary = root.contains(active) && active?.tagName === "SUMMARY";
  draw();
  for (const d of root.querySelectorAll("details")) if (open.includes(d.dataset.key)) d.open = true;
  if (focusedSummary && key) [...root.querySelectorAll("details")].find(d => d.dataset.key === key)?.querySelector("summary")?.focus({ preventScroll: true });
}
export function comparisonState(comparison, now = Date.now()) {
  if (!comparison?.available) return "unavailable";
  const expired = ["current", "pending"].includes(comparison.display_status) && comparison.inputs?.some(input => observationState(input, now) === "last_known");
  const boundary = Date.parse(comparison.selection_valid_until);
  return expired ? "last_known" : comparison.display_status === "current" && Number.isFinite(boundary) && now >= boundary ? "pending" : comparison.display_status || "unknown";
}
export function comparisonStatusLabel(comparison, now = Date.now()) {
  const state = comparisonState(comparison, now);
  if (state === "unavailable") return "Comparison unavailable";
  return ({current: "Current comparison", pending: "Comparison pending publication", last_known: "Last-known comparison", unknown: "Comparison age unknown"})[state] || "Comparison age unknown";
}
export function comparisonTakeaway(comparison, now = Date.now()) {
  if (!comparison?.available) return "Comparison unavailable: " + (comparison?.reason || "No compatible other-venue observation.");
  const peer = comparison.inputs?.find(input => input.quote_id === comparison.comparison_quote_id);
  if (!peer || !comparison.exact) return "Comparison inputs unavailable.";
  const n = BigInt(comparison.exact.numerator), d = BigInt(comparison.exact.denominator), magnitude = n < 0n ? -n : n;
  const precision = magnitude * 100n >= d ? 2 : 6, scale = 10n ** BigInt(precision);
  const rounded = (2n * magnitude * scale + d) / (2n * d);
  const digits = rounded.toString().padStart(precision + 1, "0");
  const amount = rounded === 0n && magnitude !== 0n ? "less than 0.000001¢" : "about " + (digits.slice(0, -precision) + "." + digits.slice(-precision)).replace(/\.?0+$/, "") + "¢";
  const relation = n === 0n ? "equals" : "is " + amount + (n > 0n ? " lower than" : " higher than");
  return "Selected price " + relation + " the " + venue(peer.venue) + " quote (" + relativeAge(peer.times?.source_at, now) + "; " + comparisonStatusLabel(comparison, now) + ").";
}
export function estimateSummary(root, estimate, key = "estimate-reasons") {
  if (!estimate) return;
  const label = ({available: "Estimates available", current: "Estimates available", pending: "Estimates pending", unavailable: "Estimates unavailable", not_evaluated: "Estimates not evaluated", last_known: "Last-known estimates"})[estimate.state] || "Estimates " + words(estimate.state).toLowerCase();
  const codes = [...new Set(estimate.reason_codes || [])];
  const line = el("div", undefined, "observation-estimate-status");
  line.append(el("span", label));
  if (!["available", "current"].includes(estimate.state)) {
    const reason = estimate.state === "partially_available" ? "Some stored inputs do not support a current return estimate." :
      codes.includes("selected_reference_missing") ? "A required reference is missing." :
      codes.includes("calculation_failed") ? "The last calculation did not complete." :
      estimate.state === "pending" ? "Stored inputs are awaiting a calculation." :
      "These stored inputs do not support a current return estimate.";
    line.append(el("span", reason, "estimate-primary-reason"));
  }
  if (codes.length) {
    const disclosure = el("details", undefined, "estimate-reasons");
    disclosure.dataset.key = key;
    disclosure.append(el("summary", "Why?"));
    for (const code of codes) disclosure.append(el("p", words(code) + " · " + code));
    line.append(disclosure);
  }
  root.append(line);
}
export function depthSummary(q) {
  const depth = q.observed_depth;
  if (!depth?.available || !depth.levels?.length) return "Observed depth unknown";
  const first = depth.levels[0];
  return "Observed " + quantity(first.quantity) + " " + words(depth.quantity_units) +
    " at " + quantity(first.price) + " " + words(depth.price_units) +
    (depth.levels.length > 1 ? " · " + depth.levels.length + " retained levels" : "");
}
export function observationSummary(root, q) {
  root.append(el("small", "Native " + quantity(q.original?.value) + " " + words(q.original?.units), "compact-native-price"));
  root.append(clockedText("small", now => observationStatus(q, now), "compact-source-clock"));
  const clock = el("small", undefined, "compact-observation-age");
  clock.append(ageNode(q.times?.source_at || q.freshness?.source_at, "Source "));
  root.append(clock);
  root.append(el("small", depthSummary(q), "compact-depth"));
  if (q.current_comparison?.available) {
    const current = q.current_comparison;
    root.append(clockedText("small", now => "Current-peer difference " + (numeric(current.value) > 0 ? "+" : "") + quantity(current.value) + " cents vs " + venue(current.comparison_venue) + " · " + comparisonStatusLabel(current, now), "compact-current-comparison"));
  }
  if (q.gross_comparison?.available) {
    const gross = q.gross_comparison;
    const prefix = "Gross difference " + (numeric(gross.value) > 0 ? "+" : "") + quantity(gross.value) + " " + words(gross.unit) + " vs " + venue(gross.comparison_venue) + " · ";
    const comparison = clockedText("small", now => prefix + comparisonStatusLabel(gross, now), "compact-gross-comparison");
    comparison.title = q.gross_comparison.meaning + " · Excludes costs, modeled net returns and EV.";
    root.append(comparison);
    const peer = gross.inputs?.find(input => input.quote_id === gross.comparison_quote_id);
    if (peer) { const age = el("small", undefined, "compact-comparator-age"); age.append(ageNode(peer.times?.source_at, venue(peer.venue) + " source ")); root.append(age); }
  } else if (q.gross_comparison) {
    const absent = el("small", "Comparison unavailable · Details", "compact-gross-comparison");
    absent.title = q.gross_comparison.reason || "No compatible other-venue observation";
    root.append(absent);
  }
}
// Exact display conversion only: signed integer American, half away from zero,
// matching u0_display.py. Never round a decimal/probability before conversion.
export function americanDecimal(value) {
  function decimal(text) {
    const m = /^(\d+)(?:\.(\d+))?$/.exec(text);
    if (!m || text.length > 256) throw Error("Invalid decimal odds");
    return [BigInt(m[1] + (m[2] || "")), 10n ** BigInt((m[2] || "").length)];
  }
  try {
    const parts = String(value).split("/");
    if (parts.length > 2) return "Unavailable";
    const a = decimal(parts[0]), b = parts.length === 2 ? decimal(parts[1]) : [1n, 1n];
    const n = a[0] * b[1], d = a[1] * b[0];
    if (d <= 0n || n <= d) return "Unavailable";
    const positive = n >= 2n * d;
    const numerator = 100n * (positive ? n - d : d), denominator = positive ? d : n - d;
    const rounded = (2n * numerator + denominator) / (2n * denominator);
    return (positive ? "+" : "-") + rounded.toString();
  } catch { return "Unavailable"; }
}
function benchmark(root, b, participantId) {
  const f = b?.fair?.find(f => f.participant === participantId);
  const original = b?.originals?.find(o => o.selection?.participant_id === participantId);
  root.append(el("small", venue(b?.venue) + " decisive win reference"));
  root.append(el("strong", f ? "Fair " + americanDecimal(f.fair_decimal_odds) : "Fair unavailable"));
  root.append(el("small", "Offered " + americanDecimal(original?.decimal_odds)));
  if (b?.freshness) root.append(el("small", b.freshness === "current" ? "Current benchmark" : "As-of benchmark"));
  root.title = "Fair: " + String(f?.fair_decimal_odds ?? "Unknown") + " decimal; decisive probability " + String(f?.decisive_probability ?? "Unknown") +
    "; offered: " + String(original?.decimal_odds ?? "Unknown") + " decimal; " + words(b?.method) + "; " + words(b?.conditioning) +
    "; Source " + time(original?.book_at || original?.market_at) + "; Received " + time(original?.received_at);
}
export function labelsFor(participants = []) {
  function participant(id) {
    return participants.find((p) => p.id === id)?.name || id;
  }
  function selection(q, includeSide = true) {
    const selected = q.selection || q.binding?.selection || {}, nativeSide = q.native_side || q.source?.native_side;
    const family = q.market?.market, predicate = selected.predicate, rawLine = selected.signed_line ?? q.market?.line;
    const number = rawLine == null ? "Unknown line" : String(rawLine);
    const signed = rawLine != null && numeric(rawLine) >= 0 ? "+" + number : number;
    let label;
    if (["over", "under"].includes(predicate)) label = (predicate === "over" ? "Over" : "Under") + " " + number;
    else if (predicate === "cover" || family === "spread") label = participant(selected.participant) + " " + signed + " spread";
    else if (predicate === "draw") label = "Draw";
    else label = (participant(selected.participant) || selected.label || "Unknown selection") + (predicate === "win" ? "" : predicate === "not_win" ? " · does not win" : " · " + words(predicate));
    return label + (includeSide && nativeSide && nativeSide.toLowerCase() !== "bookmaker_outcome" ? " · " + side(nativeSide) : "");
  }
  function outcome(name) {
    const teams = participants,
      home = teams.find((p) => p.role === "home")?.name || "Home team",
      away = teams.find((p) => p.role === "away")?.name || "Away team";
    const exceptional = /^terminal_grade_(\d)_(.+)$/.exec(name);
    if (exceptional)
      return (
        "Leg " +
        (Number(exceptional[1]) + 1) +
        " exceptional settlement · " +
        outcome(exceptional[2])
      );
    return (
      {
        a_wins: home + " wins",
        b_wins: away + " wins",
        tie: "Tie",
        terminal_noncompletion: "Noncompletion",
      }[name] || words(name)
    );
  }
  return { participant, selection, outcome };
}

export function marketFamily(q) {
  return q.market?.market || (["over", "under"].includes(q.selection?.predicate) ? "total" : q.selection?.predicate === "cover" ? "spread" : "winner");
}
export function marketCaption(q) {
  return ({winner:"Winner / moneyline",spread:"Spread",total:"Total"}[marketFamily(q)] || words(marketFamily(q))) + " · " + words(q.market?.period || "full_game");
}
export function outcomeDisplayKey(q) {
  if (q.same_outcome?.supported && Array.isArray(q.same_outcome.key)) return JSON.stringify(q.same_outcome.key);
  const s = q.selection || {};
  return JSON.stringify([marketFamily(q), q.market?.period || "full_game", s.participant, s.predicate,
    s.signed_line ?? q.market?.line, s.result_interpretation || "normal_win", s.period_boundary || q.market?.period_boundary || ""]);
}
export function matchesMarketFilter(q, family = "", period = "") {
  return (!family || marketFamily(q) === family) && (!period || (q.market?.period || "full_game") === period);
}

export function matchesGameSearch(game, search = "") {
  const term = search.trim().toLowerCase(), participants = game.participants || [];
  const { participant } = labelsFor(participants);
  return [game.title, game.sport, game.league, ...(game.families || []), ...(game.periods || []), ...participants.flatMap(p => [p.id, p.name, participant(p.id)])]
    .some(value => String(value || "").toLowerCase().includes(term));
}

export {
  side,
  unit,
  venue,
  words,
  time,
  residual,
  textLine,
  metric,
  freshness,
  price,
  benchmark,
};
