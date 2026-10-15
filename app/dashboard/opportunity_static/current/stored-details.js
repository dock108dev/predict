import { money, quantity } from "./board-client.js";
import {
  el,
  side,
  unit,
  venue,
  words,
  time,
  residual,
  textLine,
  metric,
  freshness,
  labelsFor,
} from "./board-elements.js";

export function renderSavedDetails(v, { root, participants }) {
  const { participant, outcome } = labelsFor(participants);
  const selected = v.pair || v.quote.calculations.funded_estimate,
    m = selected.financial_metrics || {},
    f = selected.funding || {},
    quotes = v.pair ? v.leg_quotes : [v.quote];
  root.replaceChildren();
  root.append(
    el(
      "h3",
      quotes
        .map(
          (q) =>
            participant(q.binding.selection.participant) +
            " · " +
            venue(q.venue) +
            (q.source.native_side === "bookmaker_outcome"
              ? ""
              : " " + side(q.source.native_side)),
        )
        .join(" + "),
    ),
  );
  const age = el("div");
  age.id = "detail-freshness";
  freshness(age, selected.freshness);
  root.append(age);
  root.append(el("small", "Calculation as-of " + time(v.as_of)));
  for (const q of quotes)
    textLine(
      root,
      venue(q.venue) + " original price",
      quantity(q.original.value) +
        " " +
        words(q.original.units) +
        " · " +
        side(q.source.native_side),
    );
  const metrics = el("div", undefined, "metrics");
  metric(
    metrics,
    v.pair ? "Buffered decisive margin" : m.buffered_ev_usd == null ? "Conditional EV · buffered" : "Complete buffered EV",
    v.pair ? m.buffered_decisive_opposing_margin_usd : m.buffered_ev_usd ?? m.conditional_buffered_ev_usd,
  );
  if (v.pair) {
    metric(metrics,"Minimum across modeled outcomes · buffered",m.buffered_complete_modeled_minimum_usd);
    if (m.buffered_complete_modeled_minimum_usd == null) metrics.append(el("small","Complete modeled minimum unknown; the decisive margin does not cover every outcome.","conditional-label"));
  }
  root.append(metrics);
  if (!v.pair && m.buffered_ev_usd == null) metrics.append(el("small", "Complete modeled EV unavailable", "conditional-label"));
  const funding = el("div", undefined, "detail-funding");
  for (const [label, value] of [["Requested funding",money(f.requested_usd)],["Deployed",money(f.deployed_usd)],["Residual",residual(f.residual_usd)]]) {
    const item=el("div");item.append(el("small",label),el("strong",value));funding.append(item);
  }
  root.append(funding);
  for (const [i, leg] of (f.legs || []).entries())
    textLine(
      root,
      "Leg " + (i + 1) + " quantity",
      quantity(leg.native_quantity) +
        " " +
        unit(leg.native_unit?.unit) +
        " · acquisition " +
        money(leg.acquisition_usd) +
        " · upfront fees " +
        money(leg.upfront_fee_usd ?? leg.net_upfront_fee_usd),
    );
  root.append(
    el(
      "h3",
      m.net_modeled_ev_usd == null
        ? "Conditional reconciliation · complete EV unknown"
        : "Estimated value reconciliation",
    ),
  );
  const dl = el("dl", undefined, "detail-reconciliation");
  for (const [name, value] of [
    ["Gross benchmark estimate", m.gross_benchmark_ev_usd],
    ["Rule effects", m.rule_adjustment_usd],
    ["Upfront fees", m.net_upfront_fee_usd],
    ["Expected settlement fees", m.reconciliation_expected_settlement_fee_usd],
    [
      "Net estimate before buffer",
      m.net_modeled_ev_usd ?? m.conditional_net_ev_usd,
    ],
    ["One buffer on deployed amount", m.buffer_usd],
    [
      "Estimate after buffer",
      m.buffered_ev_usd ?? m.conditional_buffered_ev_usd,
    ],
  ])
    dl.append(el("dt", name), el("dd", money(value)));
  root.append(dl);
  root.append(
    el(
      "small",
      "Basis: " +
        words(m.reconciliation_condition) +
        ". Settlement fees are expected charges, not maximum charges.",
    ),
  );
  textLine(
    root,
    "Funding support",
    words(f.size_status) +
      " · " +
      (f.residual_reason || "Unknown residual reason"),
  );
  const outcomes=el("details",undefined,"detail-outcomes");
  outcomes.dataset.key="outcomes";
  outcomes.append(el("summary", "Modeled outcomes"));
  const t = el("table"),
    head = el("tr");
  ["Outcome", "Net before buffer", "After buffer"].forEach((x) =>
    head.append(el("th", x)),
  );
  t.append(head);
  for (const [name, state] of Object.entries(selected.states || {})) {
    const tr = el("tr");
    tr.append(
      el("td", outcome(name)),
      el("td", money(state.profit_usd)),
      el(
        "td",
        state.buffered_profit_usd == null
          ? "See one buffer above"
          : money(state.buffered_profit_usd),
      ),
    );
    t.append(tr);
  }
  outcomes.append(t);root.append(outcomes);
  if (selected.assumptions?.length) {
    const assumptions = el("details");
    assumptions.dataset.key = "assumptions";
    assumptions.append(el("summary", "Model assumptions"));
    for (const assumption of selected.assumptions)
      assumptions.append(
        el(
          "p",
          typeof assumption === "string"
            ? assumption
            : JSON.stringify(assumption),
          "muted",
        ),
      );
    root.append(assumptions);
  }
  const advanced = el("details");
  advanced.dataset.key = "originals";
  advanced.append(
    el("summary", "Original contracts, profiles and current calculation evidence"),
    el("pre", JSON.stringify(v, null, 2)),
  );
  root.append(advanced);
  return { advanced };
}
