// The browser formats server results; the server owns financial sizing and reconciliation.
export const defaults = Object.freeze({
  amount: "1000",
  buffer: "0.005",
  benchmark_venue: "pinnacle",
  benchmark_method: "proportional_no_vig",
  sizing_mode: "requested_trade",
});
export const numeric = (v) => {
  if (v == null) return null;
  const [a, b] = String(v).split("/");
  const n = Number(a) / (b === undefined ? 1 : Number(b));
  return Number.isFinite(n) ? n : null;
};
export const money = (v) =>
  numeric(v) === null
    ? "Unknown"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
      }).format(numeric(v));
export const percent = (v) =>
  numeric(v) === null ? "Unknown" : numeric(v).toFixed(2) + "%";
export const quantity = (v) =>
  numeric(v) === null
    ? "Unknown"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(
        numeric(v),
      );
export function followGame(previous, games, key) {
  if (games.some((g) => g.game_key === key) || !previous) return key;
  const matched = (g) =>
    g.scope === "NFL/full_game/winner" &&
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
      g.start_at === previous.start_at &&
      roles(g) === roles(previous) &&
      g.members.some((m) =>
        previous.members.some((p) => p[0] === m[0] && p[1] === m[1]),
      ),
  );
  return candidates.length === 1 ? candidates[0].game_key : key;
}
const ratio = (value) => {
  const parts = String(value).split("/");
  if (parts.length > 2) throw Error("Invalid exact amount");
  const decimal = (text) => {
    const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(text);
    if (!match || text.length > 256) throw Error("Invalid exact amount");
    return [
      BigInt((match[1] === "-" ? "-" : "") + match[2] + (match[3] || "")),
      10n ** BigInt((match[3] || "").length),
    ];
  };
  const a = decimal(parts[0]),
    b = parts.length === 2 ? decimal(parts[1]) : [1n, 1n];
  if (!b[0]) throw Error("Invalid exact amount");
  return [a[0] * b[1], a[1] * b[0]];
};
const decimalEqual = (a, b) => {
  try {
    const x = ratio(a),
      y = ratio(b);
    return x[0] * y[1] === y[0] * x[1];
  } catch {
    return false;
  }
};
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
export function checkPolicy(policy, context) {
  if (
    policy?.version !== "predict-estimate-policy-3" ||
    !policy.revision ||
    !decimalEqual(policy.requested_amount_usd, context.amount) ||
    !decimalEqual(policy.capital_ceiling_usd, context.amount) ||
    !decimalEqual(policy.buffer_rate, context.buffer) ||
    policy.benchmark_venue !== context.benchmark_venue ||
    policy.benchmark_method !== context.benchmark_method ||
    policy.sizing_mode !== "requested_trade"
  )
    throw Error("Settings identity crossed; response withheld.");
}
const availabilityStates = ["numeric_current", "numeric_last_known", "missing_reference", "unsupported_inputs", "calculation_failed", "not_evaluated"];
export function checkAvailability(value, summary = false) {
  if (!value || value.version !== "predict-calculation-availability-1") throw Error("Calculation availability missing; response withheld.");
  if (summary) {
    if (!availabilityStates.every(s => Number.isSafeInteger(value.counts?.[s]) && value.counts[s] >= 0) ||
        Object.values(value.counts).reduce((a, b) => a + b, 0) !== value.total_results ||
        value.numeric_results !== value.counts.numeric_current + value.counts.numeric_last_known ||
        value.current_results !== value.counts.numeric_current ||
        !Number.isSafeInteger(value.positive_results) || value.positive_results < 0 ||
        !Array.isArray(value.causes) || !["not_evaluated", "unavailable", "partial", "last_known_only", "evaluated_no_positive", "positive"].includes(value.outcome))
      throw Error("Calculation availability counts crossed; response withheld.");
  } else if (!availabilityStates.includes(value.state) || !Array.isArray(value.reason_codes) ||
             !Array.isArray(value.numeric_metrics) || !value.metrics ||
             Object.values(value.metrics).some(m => !availabilityStates.includes(m.state) || !Array.isArray(m.reason_codes)) ||
             (value.state.startsWith("numeric_") !== (value.numeric_metrics.length > 0)) ||
             (value.current_opportunity_eligible && value.state !== "numeric_current") ||
             typeof value.current_opportunity_eligible !== "boolean")
    throw Error("Calculation availability state crossed; response withheld.");
  return value;
}
export function checkBoard(v, c) {
  checkPolicy(v.policy, c);
  if (v.availability !== undefined) checkAvailability(v.availability, true);
  if (
    v.version !== "predict-comparison-board-2" ||
    v.game_key !== c.game ||
    v.view !== c.view ||
    v.filter !== c.filter ||
    !v.input_version ||
    !Array.isArray(v.prices) ||
    !Array.isArray(v.rows) ||
    v.benchmark?.venue !== c.benchmark_venue
  )
    throw Error("Game or view identity crossed; response withheld.");
  checkCalculationContext(v.calculation_context, v.policy.revision);
  if (v.calculation_context.dependency_revision !== v.input_version)
    throw Error("Current dependency identity crossed; response withheld.");
  if (v.result_id != null || v.snapshot_id != null)
    throw Error("Legacy saved identity is unavailable; reopen the current view.");
  for (const q of v.prices) {
    if (
      !q.quote_id ||
      !q.original ||
      !q.original.units ||
      q.inputs_identity?.quote_id !== q.quote_id ||
      q.inputs_identity?.game_key !== v.game_key ||
      q.inputs_identity?.input_version !== v.input_version ||
      q.inputs_identity?.context_id !== v.calculation_context.context_id
    )
      throw Error("Original price identity crossed; response withheld.");
  }
  for (const row of v.rows) {
    if (c.view === "odds") continue;
    if (row.availability !== undefined) {
      checkAvailability(row.availability);
      for (const key of row.availability.numeric_metrics) if (numeric(row.financial_metrics?.[key]) === null)
        throw Error("Numeric availability crossed; response withheld.");
      if (row.availability.state === "numeric_last_known" && (row.ranking_eligible || row.classification?.main_positive_eligible || row.classification?.positive_rule_sensitive_eligible))
        throw Error("Last-known result cannot be a current opportunity.");
    }
    if (
      c.filter !== "all" &&
      (row.freshness?.status !== "current" ||
        !row.classification?.[
          c.filter === "positive"
            ? "main_positive_eligible"
            : "positive_rule_sensitive_eligible"
        ])
    )
      throw Error(
        "Positive result freshness or classification crossed; response withheld.",
      );
    if (
      row.model_available &&
      (!row.financial_metrics ||
        !row.funding?.legs?.length ||
        row.funding.legs.some(
          (l) => !l.native_unit?.unit || l.native_quantity == null,
        ))
    )
      throw Error("Funded quantity or units missing; response withheld.");
    const d = row.details;
    if (
      d?.context_id !== v.calculation_context.context_id ||
      d.result_id != null || d.snapshot_id != null ||
      d.policy_revision !== v.policy.revision ||
      !!d.quote_id === !!d.pair_id ||
      (c.view === "ev"
        ? d.quote_id !== row.quote_id
        : d.pair_id !== row.pair_id)
    )
      throw Error("Selection identity crossed; response withheld.");
  }
  return v;
}
export function checkSlate(v, c) {
  checkPolicy(v.policy, c);
  if (v.availability !== undefined) checkAvailability(v.availability, true);
  if (
    v.version !== "predict-comparison-slate-2" ||
    v.view !== c.view ||
    v.filter !== c.filter ||
    !Array.isArray(v.games) ||
    !Array.isArray(v.boards) ||
    v.games.length > 500 ||
    v.boards.length > 50 ||
    v.bounds?.maximum_games !== 500 ||
    v.bounds?.maximum_page_games !== 50 ||
    typeof v.read_revision !== "string" || !v.read_revision ||
    typeof v.epoch !== "string" || !v.epoch ||
    v.bounds?.maximum_bytes !== 8388608 ||
    (v.errors !== undefined && !Array.isArray(v.errors)) ||
    typeof v.stopped !== "boolean"
  )
    throw Error("Slate or view identity crossed; response withheld.");
  const catalog = new Map();
  for (const g of v.games) {
    if (!g.game_key || !g.title || !Array.isArray(g.participants) || catalog.has(g.game_key))
      throw Error("Slate occurrence identity crossed; response withheld.");
    catalog.set(g.game_key, g);
  }
  const coverage = v.coverage;
  if (!coverage || coverage.total_games !== v.games.length ||
      !Number.isSafeInteger(coverage.offset) || coverage.offset < 0 || coverage.offset > v.games.length ||
      !Number.isSafeInteger(coverage.limit) || coverage.limit < 1 || coverage.limit > 50 ||
      coverage.returned_games !== Math.min(coverage.limit, v.games.length - coverage.offset) ||
      coverage.next_offset !== (coverage.offset + coverage.returned_games < v.games.length ? coverage.offset + coverage.returned_games : null) ||
      coverage.complete !== (coverage.next_offset === null))
    throw Error("Current slate page coverage crossed; response withheld.");
  const expected = new Set(v.games.slice(coverage.offset, coverage.offset + coverage.returned_games).map(g => g.game_key));
  const seen = new Set();
  for (const b of v.boards) {
    if (!expected.has(b.game_key) || seen.has(b.game_key) || b.policy?.revision !== v.policy.revision)
      throw Error("Slate board occurrence crossed; response withheld.");
    checkBoard(b, { ...c, game: b.game_key });
    if (b.calculation_context.epoch !== v.epoch)
      throw Error("Current reset identity crossed; response withheld.");
    seen.add(b.game_key);
  }
  for (const error of v.errors || []) {
    if (error.availability !== undefined) checkAvailability(error.availability);
    if (!expected.has(error.game_key) || seen.has(error.game_key) || typeof error.reason !== "string")
      throw Error("Slate unavailable occurrence crossed; response withheld.");
    seen.add(error.game_key);
  }
  if (seen.size !== expected.size)
    throw Error("Slate occurrence board absent; response withheld.");
  return v;
}
export function checkCalculationContext(value, policyRevision) {
  if (!value || !["context_id", "epoch", "dependency_revision", "engine_binding"].every(k => typeof value[k] === "string" && value[k].length > 0 && value[k].length <= 256) || value.policy_revision !== policyRevision)
    throw Error("Current calculation identity unavailable; response withheld.");
  return value;
}
export function checkDetails(v, c, d) {
  checkPolicy(v.policy, c);
  checkCalculationContext(v.calculation_context, v.policy.revision);
  if (
    v.version !== "predict-board-details-2" ||
    v.game_key !== c.game ||
    v.original_inputs_identity?.game_key !== c.game ||
    v.original_inputs_identity?.context_id !== d.context_id ||
    v.original_inputs_identity?.policy_revision !== d.policy_revision ||
    v.calculation_context.context_id !== d.context_id ||
    v.result_id != null || v.snapshot_id != null ||
    v.policy.revision !== d.policy_revision ||
    (d.quote_id
      ? v.quote?.id !== d.quote_id || v.pair != null
      : v.pair?.id !== d.pair_id || v.quote != null)
  )
    throw Error("Details identity crossed; response withheld.");
  const result = v.pair || v.quote?.calculations?.funded_estimate;
  if (result?.availability !== undefined) checkAvailability(result.availability);
  return v;
}
export function checkInputs(v, c, identity) {
  checkCalculationContext(v.calculation_context, identity.policy_revision);
  if (v.version !== "predict-board-inputs-2" || v.game_key !== c.game ||
      v.calculation_context.context_id !== identity.context_id || v.quote_id !== identity.quote_id ||
      !v.evidence || typeof v.evidence !== "object" || Array.isArray(v.evidence))
    throw Error("Original price changed; reopen its current identity.");
  return v;
}
// A complete browser view is assembled from at most ten separately bounded
// wire pages. It has its own identity and byte disclosure; it is never a wire
// slate claiming that 500 boards fit within one 8 MiB response.
export class SlateAccumulator {
  constructor(context) {
    this.context = context;
    this.value = null;
    this.nextOffset = 0;
    this.pageCount = 0;
    this.totalBytes = 0;
  }
  get expectedRevision() { return this.value?.read_revision; }
  get complete() { return this.value !== null && this.nextOffset === null; }
  append(page, bytes) {
    if (this.complete || this.pageCount >= 10 || !Number.isSafeInteger(bytes) || bytes < 0 || bytes > 8388608 || this.totalBytes + bytes > 83886080)
      throw Error("Current slate exceeds its bounded page or complete-read capacity.");
    checkSlate(page, this.context);
    if (page.coverage.offset !== this.nextOffset || page.coverage.limit !== 50 || this.value &&
        (page.read_revision !== this.value.read_revision || page.epoch !== this.value.epoch ||
         JSON.stringify(page.games) !== this.catalogIdentity || page.policy.revision !== this.value.policy.revision))
      throw Error("Current slate changed while reading its pages. Retry the current view.");
    if (!this.value) {
      this.catalogIdentity = JSON.stringify(page.games);
      this.value = { ...page, version: "predict-comparison-slate-view-2", boards: [], errors: [],
        bounds: { maximum_games: 500, maximum_page_games: 50, maximum_page_bytes: 8388608, maximum_read_bytes: 83886080, maximum_pages: 10 } };
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
      let positives = 0;
      for (const a of summaries) {
        for (const state of availabilityStates) states[state] += a.counts[state];
        positives += a.positive_results;
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
        total_results: total, numeric_results: count, current_results: states.numeric_current, positive_results: positives, counts: states,
        outcome: this.context.view === "odds" ? "not_evaluated" : !count && total ? "unavailable" : !total ? "evaluated_no_positive" : positives ? "positive" : count < total ? "partial" : !states.numeric_current ? "last_known_only" : "evaluated_no_positive", causes: [...causes.values()]};
    }
    return this.value;
  }
}
export class LatestRead {
  constructor(fetcher = (...args) => fetch(...args)) {
    this.fetcher = fetcher;
    this.generation = 0;
  }
  get pending() {
    return this.active !== undefined;
  }
  cancel() {
    this.generation++;
    this.controller?.abort();
  }
  async read(url, validate, limit = 524288) {
    this.cancel();
    const token = this.generation,
      controller = (this.controller = new AbortController());
    const active = (this.active = { token, controller });
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await this.fetcher(url, { signal: controller.signal });
      // Read bounded bytes even when the peer omits Content-Length.
      const reader = response.body.getReader();
      let length = 0;
      const chunks = [];
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        length += value.length;
        if (length > limit) {
          await reader.cancel();
          throw Error("Response exceeds its current-data bound.");
        }
        chunks.push(value);
      }
      if (token !== this.generation || controller.signal.aborted) return null;
      const bytes = new Uint8Array(length);
      let at = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, at);
        at += chunk.length;
      }
      const value = JSON.parse(new TextDecoder().decode(bytes));
      if (!response.ok)
        throw Error(value.reason || value.error || "Current data unavailable.");
      return validate(value, { bytes: length });
    } finally {
      clearTimeout(timeout);
      if (this.active === active) this.active = undefined;
    }
  }
}

// Schedule the next saved read after completion. A delayed timer cannot start
// overlapping work or resume a modal/closed controller that withdrew reads.
export class SavedReadPoller {
  constructor({ onRead, canRead, setTimer = (callback, delay) => globalThis.setTimeout(callback, delay), clearTimer = timer => globalThis.clearTimeout(timer) }) {
    this.onRead = onRead;
    this.canRead = canRead;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.delay = 10000;
    this.generation = 0;
  }
  setSlate(v) {
    this.delay = v && !v.stopped && v.storage?.state !== "unavailable" && v.boards?.some(b => b.delivery_state === "pending") ? 2000 : 10000;
  }
  cancel() {
    this.generation++;
    if (this.timer !== undefined) this.clearTimer(this.timer);
    this.timer = undefined;
  }
  schedule() {
    this.cancel();
    if (!this.canRead()) return;
    const token = this.generation;
    this.timer = this.setTimer(() => {
      this.timer = undefined;
      if (token === this.generation && this.canRead()) this.onRead();
    }, this.delay);
  }
}
