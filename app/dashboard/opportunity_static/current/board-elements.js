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
  function selection(q) {
    const nativeSide = q.native_side?.toLowerCase();
    return (
      participant(q.selection?.participant) +
      (nativeSide === "bookmaker_outcome" ? "" : " · " + side(q.native_side)) +
      (q.selection?.predicate === "win"
        ? ""
        : " · " + words(q.selection?.predicate))
    );
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
