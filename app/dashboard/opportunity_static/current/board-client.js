import { numeric } from "./board-values.js";
import { checkSlate, availabilityStates } from "./board-contract.js";
export { numeric, money, percent, quantity } from "./board-values.js";
export { checkPolicy, checkAvailability, checkBoard, checkSlate, checkCalculationContext, checkDetails, checkInputs } from "./board-contract.js";
export { LatestRead, SavedReadPoller } from "./board-read.js";

// The browser formats server results; the server owns financial sizing and reconciliation.
export const defaults = Object.freeze({
  amount: "1000",
  buffer: "0.005",
  benchmark_venue: "pinnacle",
  benchmark_method: "proportional_no_vig",
  sizing_mode: "requested_trade",
});
export function followGame(previous, games, key) {
  if (games.some((g) => g.game_key === key) || !previous) return key;
  const matched = (g) =>
    typeof g.scope === "string" &&
    Array.isArray(g.participants) &&
    Array.isArray(g.members) &&
    g.matches?.length &&
    g.matches.every(
      (m) =>
        m.status === "matched" &&
        Array.isArray(m.conflicts) &&
        !m.conflicts.length,
    );
  if (!matched(previous)) return key;
  const roles = (g) =>
    JSON.stringify(g.participants.map((p) => [p.role, p.id]).sort());
  const candidates = games.filter(
    (g) =>
      matched(g) &&
      g.scope === previous.scope &&
      g.league === previous.league &&
      g.sport === previous.sport &&
      g.start_at === previous.start_at &&
      roles(g) === roles(previous) &&
      g.members.some((m) =>
        previous.members.some((p) => p[0] === m[0] && p[1] === m[1]),
      ),
  );
  return candidates.length === 1 ? candidates[0].game_key : key;
}
export function settings(amount, bufferPercent, benchmark) {
  if (
    !/^\d+(\.\d{1,6})?$/.test(amount) ||
    numeric(amount) <= 0 ||
    numeric(amount) > 100000
  )
    throw Error("Enter a trade amount greater than $0 and at most $100,000.");
  if (!/^\d+(\.\d{1,4})?$/.test(bufferPercent) || numeric(bufferPercent) > 100)
    throw Error("Enter a buffer from 0 to 100%.");
  if (!["pinnacle", "novig", "prophetx"].includes(benchmark))
    throw Error("Choose a supported benchmark.");
  // Exact decimal shift, avoiding binary rounding when converting the user percentage to a rate.
  const [whole, fraction = ""] = bufferPercent.split(".");
  const digits = (whole + fraction).padStart(fraction.length + 3, "0");
  const at = digits.length - fraction.length - 2;
  const rate = (digits.slice(0, at) + "." + digits.slice(at))
    .replace(/^0+(?=\d)/, "")
    .replace(/0+$/, "")
    .replace(/\.$/, "");
  return {
    ...defaults,
    amount,
    buffer: rate || "0",
    benchmark_venue: benchmark,
  };
}
export class SlateAccumulator {
  constructor(context) {
    this.context = { ...context };
    this.value = null;
    this.nextOffset = 0;
    this.pageCount = 0;
    this.totalBytes = 0;
  }
  get expectedRevision() { return this.value?.read_revision; }
  get readToken() { return this.value?.read_token; }
  get complete() { return this.value !== null && this.nextOffset === null; }
  append(page, bytes) {
    if (this.complete || this.pageCount >= 500 || !Number.isSafeInteger(bytes) || bytes < 0 || bytes > 8388608 || this.totalBytes + bytes > 83886080)
      throw Error("Current slate exceeds its bounded page or complete-read capacity.");
    checkSlate(page, this.context);
    if (page.coverage.offset !== this.nextOffset || page.coverage.limit !== 50 || this.value &&
        (page.read_revision !== this.value.read_revision || page.epoch !== this.value.epoch ||
         page.read_token !== this.value.read_token || page.read_expires_at !== this.value.read_expires_at ||
         page.read_at !== this.value.read_at || page.as_of !== this.value.as_of || page.stopped !== this.value.stopped ||
         page.sizing_scope !== this.value.sizing_scope || JSON.stringify(page.games) !== this.catalogIdentity ||
         JSON.stringify(page.policy) !== this.policyIdentity))
      throw Error("Current slate changed while reading its pages. Retry the current view.");
    if (!this.value) {
      this.catalogIdentity = JSON.stringify(page.games);
      this.policyIdentity = JSON.stringify(page.policy);
      this.value = { ...page, version: "predict-comparison-slate-view-2", boards: [], errors: [],
        bounds: { maximum_games: 500, maximum_page_games: 50, maximum_page_bytes: 8388608, maximum_read_bytes: 83886080, maximum_pages: 500 } };
    }
    // Retain only these board/error objects and the first small catalog. Later
    // page envelopes and repeated catalogs become collectible immediately.
    this.value.boards.push(...page.boards);
    this.value.errors.push(...(page.errors || []));
    this.nextOffset = page.coverage.next_offset;
    this.pageCount++;
    this.totalBytes += bytes;
  }
  result() {
    if (!this.complete) throw Error("Current slate coverage is incomplete; response withheld.");
    this.value.coverage = { total_games: this.value.games.length, returned_games: this.value.boards.length + this.value.errors.length,
      complete: true, page_count: this.pageCount, wire_bytes: this.totalBytes };
    const summaries = this.value.boards.map(b => b.availability).filter(Boolean);
    if (this.value.availability !== undefined) {
      const states = Object.fromEntries(availabilityStates.map(s => [s, 0])), causes = new Map();
      let positives = 0, partials = 0;
      for (const a of summaries) {
        for (const state of availabilityStates) states[state] += a.counts[state] || 0;
        positives += a.positive_results; partials += a.partial_results || 0;
        for (const c of a.causes) {
          const x = causes.get(c.code) || {code: c.code, affected_results: 0, affected_games: 0, venues: []};
          x.affected_results += c.affected_results; x.affected_games += c.affected_games;
          x.venues = [...new Set([...x.venues, ...c.venues])]; causes.set(c.code, x);
        }
      }
      states.calculation_failed += this.value.errors.length;
      if (this.value.errors.length) causes.set("calculation_read_failed", {code: "calculation_read_failed", affected_results: this.value.errors.length, affected_games: this.value.errors.length, venues: []});
      const total = Object.values(states).reduce((a, b) => a + b, 0), count = states.numeric_current + states.numeric_last_known;
      this.value.availability = {version: "predict-calculation-availability-1", scope: "evaluated_results_before_filter", games: this.value.games.length,
        total_results: total, numeric_results: count, current_results: states.numeric_current, positive_results: positives, partial_results: partials, evaluation_complete: count === total && total > 0 && !states.numeric_last_known && !partials, counts: states,
        outcome: this.context.view === "odds" || !total || states.not_evaluated === total ? "not_evaluated" : !count ? "unavailable" : count < total || partials || states.numeric_current && states.numeric_last_known ? "partial" : !states.numeric_current ? "last_known_only" : positives ? "positive" : "evaluated_no_positive", causes: [...causes.values()]};
    }
    return this.value;
  }
}
// Tokens live only within this invocation. A fresh read (including the one
// allowed recovery) starts at zero and never reuses a partial frame or token.
// Existing completed values stay with the controller until this returns a
// wholly validated result. Cancellation cannot start a recovery or next page.
export async function readSlate(reader, context, { isCurrent = () => true, onRecovery = () => {} } = {}) {
  context = { ...context };
  let generation = reader.generation;
  for (let attempt = 0; attempt < 2; attempt++) {
    const pages = new SlateAccumulator(context);
    const query = new URLSearchParams({ view: context.view, filter: context.filter, limit: "50" });
    try {
      do {
        if (!isCurrent() || reader.generation !== generation) return null;
        query.set("offset", String(pages.nextOffset));
        if (pages.readToken) {
          query.set("read_token", pages.readToken);
          query.set("expected_revision", pages.expectedRevision);
        }
        const request = reader.read("/api/boards/slate?" + query, (page, metadata) => {
          if (!page.read_token) throw Error("Current slate read token unavailable; response withheld.");
          pages.append(page, metadata.bytes);
          return true;
        }, 8388608);
        generation = reader.generation;
        const completed = await request;
        if (!completed || !isCurrent() || reader.generation !== generation) return null;
      } while (!pages.complete);
      return pages.result();
    } catch (error) {
      if (!isCurrent() || reader.generation !== generation || error.name === "AbortError") return null;
      const recoverable = ["current_slate_read_expired", "current_slate_read_capacity", "current_slate_read_authority_changed"]
        .includes(error.reason) || error.code === "current_read_busy";
      if (attempt || !recoverable) throw error;
      onRecovery(error);
    }
  }
}
