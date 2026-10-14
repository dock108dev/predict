// The browser formats server results; financial sizing and reconciliation stay in B01/S01.
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
export function checkBoard(v, c) {
  checkPolicy(v.policy, c);
  if (
    v.version !== "predict-comparison-board-1" ||
    v.game_key !== c.game ||
    v.view !== c.view ||
    v.filter !== c.filter ||
    !v.input_version ||
    !Array.isArray(v.prices) ||
    !Array.isArray(v.rows) ||
    v.benchmark?.venue !== c.benchmark_venue
  )
    throw Error("Game or view identity crossed; response withheld.");
  if (v.rows.length && c.view !== "odds" && (!v.result_id || !v.snapshot_id))
    throw Error("Saved result identity missing; response withheld.");
  for (const q of v.prices) {
    if (
      !q.quote_id ||
      !q.original ||
      !q.original.units ||
      q.inputs_identity?.quote_id !== q.quote_id ||
      q.inputs_identity?.game_key !== v.game_key ||
      q.inputs_identity?.input_version !== v.input_version
    )
      throw Error("Original price identity crossed; response withheld.");
  }
  for (const row of v.rows) {
    if (c.view === "odds") continue;
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
      d?.result_id !== v.result_id ||
      d.snapshot_id !== v.snapshot_id ||
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
export function checkDetails(v, c, d) {
  checkPolicy(v.policy, c);
  if (
    v.version !== "predict-board-details-1" ||
    v.game_key !== c.game + ":benchmark:" + c.benchmark_venue ||
    v.original_inputs_identity?.game_key !== c.game ||
    v.original_inputs_identity?.result_id !== d.result_id ||
    v.original_inputs_identity?.policy_revision !== d.policy_revision ||
    v.result_id !== d.result_id ||
    v.snapshot_id !== d.snapshot_id ||
    v.policy.revision !== d.policy_revision ||
    (d.quote_id
      ? v.quote?.id !== d.quote_id || v.pair != null
      : v.pair?.id !== d.pair_id || v.quote != null)
  )
    throw Error("Details identity crossed; response withheld.");
  return v;
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
          throw Error("Response exceeds its saved-data bound.");
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
        throw Error(value.reason || value.error || "Saved data unavailable.");
      return validate(value);
    } finally {
      clearTimeout(timeout);
      if (this.active === active) this.active = undefined;
    }
  }
}
